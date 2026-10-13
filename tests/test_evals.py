"""Checks for the eval set in evals/.

- test_evalset_matches_agents: always runs. Catches typos in tool or agent
  names before anyone spends money running evals.
- test_eval_harness_*: run ADK's real evaluator against the fake model, to
  show the trajectory metric passes the right tool and fails the wrong one.
- test_live_evals: runs the full eval set against real Gemini. Opt in with
  RUN_LIVE_EVALS=1 (it costs money and needs GCP credentials).
"""
import json
import os
from pathlib import Path

import pytest
from google.adk.evaluation.eval_set import EvalSet

from app.agents.vehicle_assistants import agent as agent_module

EVALS = Path(__file__).parent.parent / "evals"
EVAL_SET = EvalSet.model_validate_json((EVALS / "vehicle_assistant.test.json").read_text())


def agent_tree(agent):
    yield agent
    for sub in agent.sub_agents:
        yield from agent_tree(sub)


def test_evalset_matches_agents():
    agents = {a.name: a for a in agent_tree(agent_module.root_agent)}
    tool_names = {"transfer_to_agent"}
    tool_names |= {"list_table_ids", "get_table_info", "execute_sql"}  # BigQueryToolset
    for a in agents.values():
        tool_names |= {t.__name__ for t in a.tools if callable(t) and hasattr(t, "__name__")}

    assert len(EVAL_SET.eval_cases) >= 8
    for case in EVAL_SET.eval_cases:
        for invocation in case.conversation:
            for call in invocation.intermediate_data.tool_uses:
                assert call.name in tool_names, f"{case.eval_id}: unknown tool {call.name}"
                if call.name == "transfer_to_agent":
                    assert call.args["agent_name"] in agents, f"{case.eval_id}: unknown agent"


def test_eval_config_is_valid():
    from google.adk.evaluation.eval_config import EvalConfig

    config = EvalConfig.model_validate(json.loads((EVALS / "test_config.json").read_text()))
    assert "tool_trajectory_avg_score" in config.criteria


def _run_trajectory_eval(eval_id: str):
    import asyncio

    from google.adk.evaluation.agent_evaluator import AgentEvaluator
    from google.adk.evaluation.eval_config import EvalConfig

    subset = EVAL_SET.model_copy(
        update={"eval_cases": [c for c in EVAL_SET.eval_cases if c.eval_id == eval_id]}
    )
    config = EvalConfig(
        criteria={"tool_trajectory_avg_score": {"threshold": 0.8, "match_type": "IN_ORDER", "ignore_args": True}}
    )
    asyncio.run(
        AgentEvaluator.evaluate_eval_set(
            agent_module="app.agents.vehicle_assistants",
            eval_set=subset,
            eval_config=config,
            num_runs=1,
            print_detailed_results=False,
        )
    )


@pytest.fixture
def fake_agents(monkeypatch):
    pytest.importorskip("vertexai", reason="needs google-adk[eval]")
    from tests.test_chat_flow import install_fakes

    install_fakes(monkeypatch)


def test_eval_harness_passes_correct_tool(fake_agents):
    # The fake safety agent always calls fatalities_by_state: right for this case.
    _run_trajectory_eval("state_ranking_2020")


def test_eval_harness_fails_wrong_tool(fake_agents):
    # This case expects monthly_trend, so the eval must fail.
    with pytest.raises(AssertionError):
        _run_trajectory_eval("michigan_monthly_2019")


@pytest.mark.skipif(not os.getenv("RUN_LIVE_EVALS"), reason="set RUN_LIVE_EVALS=1 to run against real Gemini")
async def test_live_evals():
    from google.adk.evaluation.agent_evaluator import AgentEvaluator

    await AgentEvaluator.evaluate(
        agent_module="app.agents.vehicle_assistants",
        eval_dataset_file_path_or_dir=str(EVALS),
        num_runs=2,  # LLMs vary; run each case twice
    )
