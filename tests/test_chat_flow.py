"""End-to-end: HTTP request -> coordinator -> specialist -> tool -> answer -> session.

The model and BigQuery are faked; everything else (ADK routing, tools,
session state, FastAPI, auth) is the real code.
"""
import pytest
from fastapi.testclient import TestClient

from app.agents.vehicle_assistants import agent as agent_module
from app.agents.vehicle_assistants.sub_agents import report_writer, safety_insights, sql_analyst
from app.agents.vehicle_assistants.tools import safety_queries
from app.main import app
from tests.fake_llm import FakeLlm, call, last_part, last_user_text, text

HEADERS = {"X-API-Key": "test-key"}
FAKE_ROWS = [
    {"state_name": "Texas", "crashes": 3500, "fatalities": 3874},
    {"state_name": "California", "crashes": 3600, "fatalities": 3847},
]


def coordinator_reply(request):
    if "report" in last_user_text(request).lower():
        return call("transfer_to_agent", agent_name="report_writer")
    return call("transfer_to_agent", agent_name="safety_insights")


def safety_reply(request):
    part = last_part(request)
    if part.function_response:
        rows = part.function_response.response["rows"]
        return text(f"{rows[0]['state_name']} had the most fatalities ({rows[0]['fatalities']}).")
    if "report" in last_user_text(request).lower():
        return call("transfer_to_agent", agent_name="report_writer")
    return call("fatalities_by_state", year=2020, top_n=2)


def report_reply(request):
    # The instruction template {last_findings?} should now contain the earlier answer.
    findings_seen = "Texas" in str(request.config.system_instruction)
    return text(f"REPORT (used saved findings: {findings_seen})")


@pytest.fixture
def fake_models(monkeypatch):
    models = [
        (agent_module.root_agent, coordinator_reply),
        (safety_insights, safety_reply),
        (sql_analyst, lambda r: text("not used")),
        (report_writer, report_reply),
    ]
    for agent, reply in models:
        monkeypatch.setattr(agent, "model", FakeLlm(reply=reply, requests=[]))
    monkeypatch.setattr(safety_queries, "_run", lambda sql, params: {"status": "success", "rows": FAKE_ROWS})


def test_question_then_report_in_same_session(fake_models):
    with TestClient(app) as client:
        first = client.post(
            "/chat",
            headers=HEADERS,
            json={"user_id": "vikas", "message": "Which state had the most fatalities in 2020?"},
        ).json()
        assert first["agent"] == "safety_insights"
        assert "Texas" in first["answer"]

        second = client.post(
            "/chat",
            headers=HEADERS,
            json={"user_id": "vikas", "session_id": first["session_id"], "message": "Write a report"},
        ).json()
        assert second["session_id"] == first["session_id"]
        assert second["agent"] == "report_writer"
        assert second["answer"] == "REPORT (used saved findings: True)"

        history = client.get(f"/sessions/vikas/{first['session_id']}", headers=HEADERS).json()
        authors = [turn["author"] for turn in history]
        assert authors == ["user", "safety_insights", "user", "report_writer"]

        sessions = client.get("/sessions/vikas", headers=HEADERS).json()
        assert [s["session_id"] for s in sessions] == [first["session_id"]]

        assert client.delete(f"/sessions/vikas/{first['session_id']}", headers=HEADERS).status_code == 204
        assert client.get(f"/sessions/vikas/{first['session_id']}", headers=HEADERS).status_code == 404
