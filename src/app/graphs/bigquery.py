"""Read-only BigQuery calls for the Graph Creator: list datasets and graphs,
and read table metadata plus a few sample rows. Nothing here writes."""
from __future__ import annotations

from google.cloud import bigquery

from .infer import Column, TableInfo

MAX_DATASETS = 50  # how many datasets to look through when listing graphs
SAMPLE_ROWS = 50


def list_datasets(client: bigquery.Client, project: str) -> list[dict]:
    out = []
    for item in client.list_datasets(project=project, max_results=MAX_DATASETS):
        out.append({"dataset": item.dataset_id})
    return sorted(out, key=lambda d: d["dataset"])


def list_graphs(client: bigquery.Client, project: str, datasets: list[str]) -> tuple[list[dict], list[str]]:
    """Property graphs that already exist, from each dataset's INFORMATION_SCHEMA.

    Returns (graphs, errors). One dataset failing (no access, wrong region)
    doesn't stop the rest.
    """
    graphs, errors = [], []
    for dataset in datasets[:MAX_DATASETS]:
        sql = f"SELECT * FROM `{project}.{dataset}`.INFORMATION_SCHEMA.PROPERTY_GRAPHS"
        try:
            rows = [dict(r.items()) for r in client.query(sql).result()]
        except Exception as e:  # shown in the UI, next to the list
            errors.append(f"{dataset}: {str(e)[:200]}")
            continue
        for row in rows:
            row = {k.lower(): v for k, v in row.items()}
            name = row.get("property_graph_name") or row.get("graph_name") or row.get("name")
            graphs.append({
                "name": name,
                "dataset": dataset,
                "full_name": f"{project}.{dataset}.{name}",
                "ddl": row.get("ddl") or row.get("property_graph_ddl") or "",
            })
    return graphs, errors


def dataset_location(client: bigquery.Client, project: str, dataset: str) -> str:
    return client.get_dataset(f"{project}.{dataset}").location or "US"


def scan_tables(client: bigquery.Client, project: str, dataset: str, tables: list[str] | None = None) -> list[TableInfo]:
    """Columns, descriptions, declared keys and a few sample rows of each table.

    Sample rows come from list_rows, which reads storage directly: free, no query.
    """
    if tables is None:
        tables = sorted(t.table_id for t in client.list_tables(f"{project}.{dataset}") if t.table_type == "TABLE")
    infos = []
    for name in tables:
        t = client.get_table(f"{project}.{dataset}.{name}")
        columns = [Column(f.name, f.field_type if f.mode != "REPEATED" else "ARRAY", f.description or "") for f in t.schema]
        pk, fks = [], []
        constraints = getattr(t, "table_constraints", None)
        if constraints is not None:
            if constraints.primary_key:
                pk = list(constraints.primary_key.columns)
            for fk in constraints.foreign_keys or []:
                fks.append((
                    [c.referencing_column for c in fk.column_references],
                    fk.referenced_table.table_id,
                    [c.referenced_column for c in fk.column_references],
                ))
        sample = [dict(r.items()) for r in client.list_rows(t, max_results=SAMPLE_ROWS)]
        infos.append(TableInfo(name=name, columns=columns, description=t.description or "",
                               primary_key=pk, foreign_keys=fks, sample=sample))
    return infos
