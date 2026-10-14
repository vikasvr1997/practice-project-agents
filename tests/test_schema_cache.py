from app.agents.vehicle_assistants.tools import schema_cache


def test_second_call_within_ttl_does_not_refetch(monkeypatch):
    schema_cache.clear_cache()
    calls = []
    monkeypatch.setattr(schema_cache, "_fetch_schema_text", lambda: (calls.append(1), "`d.t` (a INT64)")[1])
    first = schema_cache.get_schema_text(ttl=3600)
    second = schema_cache.get_schema_text(ttl=3600)
    assert first == second
    assert len(calls) == 1


def test_ttl_zero_always_refetches(monkeypatch):
    schema_cache.clear_cache()
    calls = []
    monkeypatch.setattr(schema_cache, "_fetch_schema_text", lambda: (calls.append(1), "schema")[1])
    schema_cache.get_schema_text(ttl=0)
    schema_cache.get_schema_text(ttl=0)
    assert len(calls) == 2


def test_fetch_error_falls_back_and_is_not_cached(monkeypatch):
    schema_cache.clear_cache()

    def boom():
        raise RuntimeError("BigQuery unavailable")

    monkeypatch.setattr(schema_cache, "_fetch_schema_text", boom)
    out = schema_cache.get_schema_text()
    assert "schema lookup failed" in out
    assert schema_cache._cache is None  # failure wasn't cached; next call retries live


def test_fetch_schema_text_preserves_leading_space_in_table_name(monkeypatch):
    class FakeRow:
        def __init__(self, table_name, column_name, data_type):
            self.table_name = table_name
            self.column_name = column_name
            self.data_type = data_type

    class FakeResult:
        def result(self):
            return [
                FakeRow(" accident_2020", "state_name", "STRING"),
                FakeRow(" accident_2020", "number_of_fatalities", "INT64"),
            ]

    class FakeClient:
        def query(self, sql):
            return FakeResult()

    monkeypatch.setattr(schema_cache, "_client", lambda: FakeClient())
    text = schema_cache._fetch_schema_text()
    assert ". accident_2020`" in text
    assert "state_name STRING" in text
