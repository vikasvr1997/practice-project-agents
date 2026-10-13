import re
from pathlib import Path

from fastapi.testclient import TestClient

from app.agents.vehicle_assistants import agent as agent_module
from app.agents.vehicle_assistants import prompts
from app.agents.vehicle_assistants.sub_agents import supply_chain_analyst
from app.agents.vehicle_assistants.tools import supply_chain_graph
from app.main import app
from tests.fake_llm import FakeLlm, call, last_part, text

ROOT = Path(__file__).parents[1]


def test_only_read_only_graph_queries_run(monkeypatch):
    def fail(query):
        raise AssertionError("BigQuery should not be called")

    monkeypatch.setattr(supply_chain_graph, "_run", fail)
    for bad in ["SELECT * FROM suppliers", "DROP TABLE parts", "GRAPH g MATCH (a) RETURN a; DELETE FROM t WHERE true"]:
        assert supply_chain_graph.run_graph_query(bad)["status"] == "error"


def test_rows_are_capped_and_errors_returned(monkeypatch):
    monkeypatch.setattr(supply_chain_graph, "_run", lambda q: [{"n": i} for i in range(80)])
    out = supply_chain_graph.run_graph_query("GRAPH g MATCH (s:Supplier) RETURN s.name")
    assert len(out["rows"]) == 50 and out["truncated"] is True

    def boom(q):
        raise RuntimeError("Unrecognized name: Supplierr")

    monkeypatch.setattr(supply_chain_graph, "_run", boom)
    out = supply_chain_graph.run_graph_query("GRAPH g MATCH (s:Supplierr) RETURN s")
    assert out == {"status": "error", "error": "Unrecognized name: Supplierr"}


def test_prompt_labels_match_the_graph_terraform_creates():
    ddl = (ROOT / "graphs" / "supply_chain" / "graph.sql.tftpl").read_text()
    created = set(re.findall(r" AS (\w+)\n", ddl))
    edges_section = prompts.SUPPLY_CHAIN.split("Edges")[1].split("Examples")[0]
    in_prompt = set(re.findall(r"\[:(\w+)\]", edges_section)) | set(re.findall(r"\((\w+)\)", edges_section))
    assert len(in_prompt) == 12  # 5 nodes + 7 edge labels
    assert in_prompt <= created


def test_coordinator_routes_supply_chain_questions(monkeypatch):
    def coordinator(request):
        return call("transfer_to_agent", agent_name="supply_chain_analyst")

    def analyst(request):
        part = last_part(request)
        if part.function_response:
            return text(f"Found {len(part.function_response.response['rows'])} models.")
        return call("run_graph_query", query="GRAPH g MATCH (s:Supplier)-[:SUPPLIES]->(p:Part) RETURN p.name")

    monkeypatch.setattr(agent_module.root_agent, "model", FakeLlm(reply=coordinator, requests=[]))
    monkeypatch.setattr(supply_chain_analyst, "model", FakeLlm(reply=analyst, requests=[]))
    monkeypatch.setattr(supply_chain_graph, "_run", lambda q: [{"name": "Atlas"}, {"name": "Comet"}])

    with TestClient(app) as client:
        out = client.post("/chat", headers={"X-API-Key": "test-key"},
                          json={"user_id": "vikas", "message": "Which models use Northstar parts?"}).json()
    assert out["agent"] == "supply_chain_analyst"
    assert out["answer"] == "Found 2 models."
