"""The graph proposal: which tables are nodes, which are edges, and the
CREATE PROPERTY GRAPH statement and Terraform that would build it."""
from __future__ import annotations

import re

from pydantic import BaseModel, Field

LABEL = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
# GCP project ids (letters, digits, -, optionally domain:project) and dataset ids.
PROJECT = r"^[a-z][a-z0-9.:-]{4,61}[a-z0-9]$"
DATASET = r"^[A-Za-z0-9_]{1,1024}$"


class Node(BaseModel):
    label: str  # e.g. "Supplier"
    table: str  # e.g. "suppliers"
    key: list[str]  # columns that identify one node
    description: str = ""


class Edge(BaseModel):
    label: str  # e.g. "MADE_BY"
    table: str  # table that holds the link (a junction table, or the table with the foreign key)
    key: list[str]  # columns that identify one edge
    source: str  # source node label
    source_key: list[str]  # columns in `table` that point at the source node
    dest: str  # destination node label
    dest_key: list[str]  # columns in `table` that point at the destination node
    confidence: float = 1.0  # how sure the scan was, 0 to 1
    reason: str = ""  # why the scan thinks this link exists


class GraphSpec(BaseModel):
    name: str = Field(pattern=LABEL.pattern)
    project: str = Field(pattern=PROJECT)  # project that holds the dataset
    dataset: str = Field(pattern=DATASET)  # the graph is created in the same dataset as its tables
    location: str = "US"  # dataset location; the DDL job must run there
    nodes: list[Node] = []
    edges: list[Edge] = []

    def problems(self) -> list[str]:
        """What must be fixed before the DDL can run. Empty means ready."""
        out = []
        labels = [n.label for n in self.nodes] + [e.label for e in self.edges]
        for label in sorted({x for x in labels if labels.count(x) > 1}):
            out.append(f"Label {label} is used more than once.")
        for label in labels:
            if not LABEL.match(label or ""):
                out.append(f"Label {label!r} must start with a letter and use only letters, digits and _.")
        keys = {n.label: n.key for n in self.nodes}
        if not self.nodes:
            out.append("The graph needs at least one node.")
        for n in self.nodes:
            if not n.key:
                out.append(f"Node {n.label} needs a key column.")
        for e in self.edges:
            for end, cols in ((e.source, e.source_key), (e.dest, e.dest_key)):
                if end not in keys:
                    out.append(f"Edge {e.label} points at unknown node {end}.")
                elif len(cols) != len(keys[end]):
                    out.append(f"Edge {e.label}: {end} has {len(keys[end])} key column(s), the edge gives {len(cols)}.")
            if not e.key:
                out.append(f"Edge {e.label} needs a key column.")
        return out

    def full_name(self) -> str:
        return f"{self.project}.{self.dataset}.{self.name}"

    def ddl(self) -> str:
        """The CREATE PROPERTY GRAPH statement (BigQuery GQL)."""
        def table(name):
            return f"`{self.project}.{self.dataset}.{name}`"

        keys = {n.label: n.key for n in self.nodes}
        nodes = [
            f"    {table(n.table)} AS {n.label}\n"
            f"      KEY ({', '.join(n.key)})\n"
            f"      LABEL {n.label} PROPERTIES ALL COLUMNS"
            for n in self.nodes
        ]
        edges = [
            f"    {table(e.table)} AS {e.label}\n"
            f"      KEY ({', '.join(e.key)})\n"
            f"      SOURCE KEY ({', '.join(e.source_key)}) REFERENCES {e.source} ({', '.join(keys.get(e.source, []))})\n"
            f"      DESTINATION KEY ({', '.join(e.dest_key)}) REFERENCES {e.dest} ({', '.join(keys.get(e.dest, []))})\n"
            f"      LABEL {e.label} PROPERTIES ALL COLUMNS"
            for e in self.edges
        ]
        sql = f"CREATE OR REPLACE PROPERTY GRAPH `{self.full_name()}`\n  NODE TABLES (\n" + ",\n".join(nodes) + "\n  )"
        if edges:
            sql += "\n  EDGE TABLES (\n" + ",\n".join(edges) + "\n  )"
        return sql + ";\n"

    def terraform(self) -> dict[str, str]:
        """A small Terraform folder a developer can review and run themselves."""
        safe = re.sub(r"[^A-Za-z0-9_]", "_", self.name).lower()
        main_tf = f'''# Proposed by the Graph Creator. Review it, then run it yourself:
#   terraform init
#   terraform plan
#   terraform apply
# Re-running after graph.sql changes re-creates the graph (CREATE OR REPLACE).

terraform {{
  required_version = ">= 1.6"
  required_providers {{
    google = {{
      source  = "hashicorp/google"
      version = ">= 6.0, < 8.0"
    }}
  }}
}}

provider "google" {{
  project = "{self.project}"
}}

locals {{
  ddl = file("${{path.module}}/graph.sql")
}}

resource "google_bigquery_job" "property_graph" {{
  # A new job id whenever the DDL changes, so Terraform runs the new version.
  job_id   = "graph_{safe}_${{substr(sha256(local.ddl), 0, 16)}}"
  location = "{self.location}"

  query {{
    query              = local.ddl
    use_legacy_sql     = false
    create_disposition = "" # must be empty for DDL statements
    write_disposition  = ""
  }}
}}

output "graph" {{
  value = "{self.full_name()}"
}}
'''
        return {"main.tf": main_tf, "graph.sql": self.ddl()}
