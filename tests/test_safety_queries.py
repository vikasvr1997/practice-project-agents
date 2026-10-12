from app.agents.vehicle_assistants.tools import safety_queries


def test_year_outside_dataset_returns_error_without_querying(monkeypatch):
    def fail(*args):
        raise AssertionError("BigQuery should not be called")

    monkeypatch.setattr(safety_queries, "_run", fail)
    result = safety_queries.fatalities_by_state(year=1999)
    assert result["status"] == "error"
    assert "2015" in result["error"]


def test_top_n_is_clamped(monkeypatch):
    seen = {}

    def fake_run(sql, params):
        seen["top_n"] = params[0].value
        return {"status": "success", "rows": []}

    monkeypatch.setattr(safety_queries, "_run", fake_run)
    safety_queries.fatalities_by_state(year=2020, top_n=500)
    assert seen["top_n"] == 51
