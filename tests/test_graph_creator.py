"""Graph Creator: inference, DDL/Terraform output, and the /graphs API.

BigQuery is faked. The tables are the sample supply-chain data in
graphs/supply_chain/data, with the same keys and descriptions the sample
Terraform gives them, so the proposal should match the hand-made graph.
"""
import csv
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.api.routes import graphs as graphs_route
from app.graphs import bigquery as bq
from app.graphs.infer import Column, TableInfo, infer
from app.main import app

DATA = Path(__file__).parents[1] / "graphs" / "supply_chain" / "data"
HEADERS = {"X-API-Key": "test-key"}

# table: (primary key, {column: (type, description)}). Unlisted columns are STRING.
TABLES = {
    "suppliers": (["supplier_id"], {"tier": ("INT64", "")}),
    "plants": (["plant_id"], {}),
    "parts": (["part_id"], {"supplier_id": ("STRING", "References suppliers: the maker"), "unit_cost": ("FLOAT64", "")}),
    "vehicle_models": (["model_id"], {"model_year": ("INT64", "")}),
    "part_usage": (["part_id", "model_id"], {"qty_per_vehicle": ("INT64", "")}),
    "recalls": (["recall_id"], {"report_date": ("DATE", "")}),
    "recall_parts": (["recall_id", "part_id"], {}),
    "recall_models": (["recall_id", "model_id"], {}),
    "shipments": (["shipment_id"], {"units": ("INT64", ""), "ship_date": ("DATE", "")}),
}


def sample_tables() -> list[TableInfo]:
    out = []
    for name, (pk, types) in TABLES.items():
        with open(DATA / f"{name}.csv") as f:
            rows = list(csv.DictReader(f))
        columns = [Column(c, *types.get(c, ("STRING", ""))) for c in rows[0]]
        for r in rows:
            for c in columns:
                if c.type == "INT64":
                    r[c.name] = int(r[c.name])
        out.append(TableInfo(name=name, columns=columns, primary_key=pk, sample=rows[:50]))
    return out


def test_infers_the_supply_chain_graph():
    spec, notes = infer(sample_tables(), name="SupplyChain", project="my-project", dataset="vehicle_supply_chain")
    assert {n.label for n in spec.nodes} == {"Supplier", "Plant", "Part", "VehicleModel", "Recall"}
    edges = {e.label: (e.source, e.dest, e.confidence) for e in spec.edges}
    assert edges == {
        "HAS_SUPPLIER": ("Part", "Supplier", 0.8),  # from the column description
        "HAS_PLANT": ("VehicleModel", "Plant", 0.6),  # from the column name
        "PART_USAGE": ("Part", "VehicleModel", 0.6),  # junction table -> edge
        "RECALL_PARTS": ("Recall", "Part", 0.6),
        "RECALL_MODELS": ("Recall", "VehicleModel", 0.6),
        "SHIPMENTS": ("Supplier", "Plant", 0.5),  # supplier_code matched by its values only
    }
    assert spec.problems() == []
    assert notes == []


def test_ddl_and_terraform():
    spec, _ = infer(sample_tables(), name="SupplyChain", project="my-project", dataset="vehicle_supply_chain")
    ddl = spec.ddl()
    assert ddl.startswith("CREATE OR REPLACE PROPERTY GRAPH `my-project.vehicle_supply_chain.SupplyChain`")
    assert "`my-project.vehicle_supply_chain.part_usage` AS PART_USAGE" in ddl
    assert "SOURCE KEY (part_id) REFERENCES Part (part_id)" in ddl
    tf = spec.terraform()
    assert tf["graph.sql"] == ddl
    assert 'resource "google_bigquery_job" "property_graph"' in tf["main.tf"]
    assert 'location = "US"' in tf["main.tf"]


def test_problems_are_reported():
    spec, _ = infer(sample_tables(), name="SupplyChain", project="my-project", dataset="vehicle_supply_chain")
    spec.edges[0].dest = "Nope"
    spec.nodes[1].label = spec.nodes[0].label
    problems = spec.problems()
    assert any("unknown node Nope" in p for p in problems)
    assert any("used more than once" in p for p in problems)


def test_tables_without_a_key_are_skipped():
    t = TableInfo(name="logs", columns=[Column("message", "STRING")], sample=[{"message": "a"}, {"message": "a"}])
    spec, notes = infer([t], name="G", project="my-project", dataset="d")
    assert spec.nodes == [] and "Skipped logs" in notes[0]


# ---------- BigQuery reads, with a fake client ----------

class FakeBigQuery:
    def __init__(self):
        self.queries = []

    def list_datasets(self, project, max_results):
        return [SimpleNamespace(dataset_id="vehicle_supply_chain"), SimpleNamespace(dataset_id="locked")]

    def query(self, sql):
        self.queries.append(sql)
        if "locked" in sql:
            raise PermissionError("Access Denied")
        rows = [{"PROPERTY_GRAPH_NAME": "SupplyChain", "DDL": "CREATE PROPERTY GRAPH ..."}]
        return SimpleNamespace(result=lambda: [SimpleNamespace(items=r.items) for r in rows])


def test_list_graphs_reads_information_schema_and_keeps_going_on_errors():
    client = FakeBigQuery()
    graphs, errors = bq.list_graphs(client, "my-project", ["vehicle_supply_chain", "locked"])
    assert graphs == [{
        "name": "SupplyChain", "dataset": "vehicle_supply_chain",
        "full_name": "my-project.vehicle_supply_chain.SupplyChain", "ddl": "CREATE PROPERTY GRAPH ...",
    }]
    assert errors and errors[0].startswith("locked:")
    assert client.queries[0] == "SELECT * FROM `my-project.vehicle_supply_chain`.INFORMATION_SCHEMA.PROPERTY_GRAPHS"


# ---------- API ----------

@pytest.fixture
def api(monkeypatch):
    monkeypatch.setattr(bq, "scan_tables", lambda client, project, dataset, tables: sample_tables())
    monkeypatch.setattr(bq, "dataset_location", lambda client, project, dataset: "US")
    app.dependency_overrides[graphs_route.get_bigquery] = FakeBigQuery
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


def test_api_needs_the_key(api):
    assert api.get("/graphs").status_code == 401
    assert api.post("/graphs/proposals", json={"dataset": "d", "name": "G"}).status_code == 401


def test_propose_edit_list_and_delete(api):
    created = api.post("/graphs/proposals", headers=HEADERS,
                       json={"dataset": "vehicle_supply_chain", "name": "SupplyChain"})
    assert created.status_code == 201
    p = created.json()
    assert p["status"] == "proposed" and p["problems"] == []
    assert p["terraform"]["graph.sql"] == p["ddl"]

    # Rename an edge, like the editor in the UI does.
    spec = p["spec"]
    edge = next(e for e in spec["edges"] if e["label"] == "PART_USAGE")
    edge["label"] = "USED_IN"
    updated = api.put(f"/graphs/proposals/{p['id']}", headers=HEADERS, json={"spec": spec}).json()
    assert "AS USED_IN" in updated["ddl"] and updated["updated_at"]

    listing = api.get("/graphs", headers=HEADERS, params={"project": "test-project"}).json()
    assert [g["name"] for g in listing["existing"]] == ["SupplyChain"]
    assert [x["id"] for x in listing["proposals"]] == [p["id"]]
    assert listing["errors"][0].startswith("locked:")

    assert api.delete(f"/graphs/proposals/{p['id']}", headers=HEADERS).status_code == 204
    assert api.get(f"/graphs/proposals/{p['id']}", headers=HEADERS).status_code == 404


def test_bad_names_are_rejected(api):
    bad = api.post("/graphs/proposals", headers=HEADERS, json={"dataset": "d`; DROP", "name": "G"})
    assert bad.status_code == 422
    assert api.get("/graphs", headers=HEADERS, params={"dataset": "x`y"}).status_code == 422
