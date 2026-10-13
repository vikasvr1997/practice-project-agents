"""The logs show each step of a chat turn, so you can see where an agent went wrong."""
import json
import logging

from fastapi.testclient import TestClient
from google.genai import errors as genai_errors

from app.agents.vehicle_assistants import agent as agent_module
from app.agents.vehicle_assistants.sub_agents import safety_insights
from app.agents.vehicle_assistants.tools import safety_queries
from app.core.logs import JsonFormatter, request_id
from app.main import app
from tests.fake_llm import FakeLlm, call, last_part, text
from tests.test_chat_flow import HEADERS, install_fakes

QUESTION = {"user_id": "vikas", "message": "Which state had the most fatalities in 2020?"}


def lines(caplog, message):
    return [r.fields for r in caplog.records if r.getMessage() == message]


def test_chat_turn_logs_every_step(monkeypatch, caplog):
    install_fakes(monkeypatch)
    caplog.set_level(logging.INFO)
    caplog.handler.setFormatter(JsonFormatter())
    with TestClient(app) as client:
        response = client.post("/chat", headers=HEADERS, json=QUESTION)

    assert response.status_code == 200
    rid = response.headers["X-Request-ID"]
    assert lines(caplog, "agent transfer")[0]["to_agent"] == "safety_insights"
    assert lines(caplog, "tool call")[0]["tool"] == "fatalities_by_state"
    assert lines(caplog, "tool result")[0]["rows"] == 2

    [turn] = lines(caplog, "chat turn")
    assert turn["agent"] == "safety_insights"
    assert turn["agents"] == ["vehicle_assistant", "safety_insights"]
    assert turn["tools"] == ["fatalities_by_state"]
    assert turn["user_id"] == "vikas"
    assert "prompt" not in turn  # prompts stay out of the logs by default

    [request_line] = lines(caplog, "request")
    assert request_line["status"] == 200 and request_line["path"] == "/chat"
    # Every line from this request carries the id returned in X-Request-ID.
    entries = [json.loads(line) for line in caplog.text.splitlines()]
    assert {e["request_id"] for e in entries if e["logger"].startswith("app.")} == {rid}


def test_tool_error_is_a_warning(monkeypatch, caplog):
    install_fakes(monkeypatch)
    monkeypatch.setattr(safety_queries, "_run", lambda sql, params: {"status": "error", "error": "table not found"})

    def safety_reply(request):
        if last_part(request).function_response:
            return text("Sorry, the query failed.")
        return call("fatalities_by_state", year=2020, top_n=2)

    monkeypatch.setattr(safety_insights, "model", FakeLlm(reply=safety_reply, requests=[]))
    caplog.set_level(logging.INFO)
    with TestClient(app) as client:
        client.post("/chat", headers=HEADERS, json=QUESTION)

    [error] = [r for r in caplog.records if r.getMessage() == "tool error"]
    assert error.levelno == logging.WARNING
    assert error.fields["tool"] == "fatalities_by_state"
    assert "table not found" in error.fields["error"]
    [turn] = [r for r in caplog.records if r.getMessage() == "chat turn"]
    assert turn.levelno == logging.WARNING and turn.fields["tool_errors"] == 1


def test_rate_limit_returns_503(monkeypatch, caplog):
    install_fakes(monkeypatch)

    def busy(request):
        raise genai_errors.ClientError(429, {"error": {"code": 429, "message": "Resource exhausted", "status": "RESOURCE_EXHAUSTED"}})

    monkeypatch.setattr(agent_module.root_agent, "model", FakeLlm(reply=busy, requests=[]))
    with TestClient(app) as client:
        response = client.post("/chat", headers=HEADERS, json=QUESTION)

    assert response.status_code == 503
    assert response.headers["Retry-After"] == "10"
    assert lines(caplog, "model rate limited")[0]["error_code"] == 429


def test_json_lines_for_cloud_logging():
    token = request_id.set("abc123")
    try:
        record = logging.LogRecord("app", logging.WARNING, __file__, 1, "tool error", None, None)
        record.fields = {"tool": "execute_sql"}
        entry = json.loads(JsonFormatter().format(record))
    finally:
        request_id.reset(token)
    assert entry == {"severity": "WARNING", "message": "tool error", "logger": "app",
                     "request_id": "abc123", "tool": "execute_sql"}
