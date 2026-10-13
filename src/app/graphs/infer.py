"""Turn scanned tables into a proposed graph.

How a link between two tables is found, strongest evidence first:
  1. A declared foreign key.                                          confidence 1.0
  2. A column description that says "references <table>".             0.8
  3. A column whose name matches another table's key (supplier_id).   0.6
  4. A text column whose sampled values all appear in another
     table's key, even with an unrelated name (supplier_code).        0.5

Only metadata and the sample rows are used, so inferring costs nothing.
Then each table becomes a node or, if it only joins two other tables
(like part_usage(part_id, model_id)), an edge between them.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .spec import Edge, GraphSpec, Node

NUMERIC = {"INT64", "INTEGER", "NUMERIC", "BIGNUMERIC"}


@dataclass
class Column:
    name: str
    type: str
    description: str = ""


@dataclass
class TableInfo:
    name: str
    columns: list[Column]
    description: str = ""
    primary_key: list[str] = field(default_factory=list)
    foreign_keys: list[tuple[list[str], str, list[str]]] = field(default_factory=list)  # (cols, ref table, ref cols)
    sample: list[dict] = field(default_factory=list)

    def column(self, name: str) -> Column | None:
        return next((c for c in self.columns if c.name == name), None)


@dataclass
class Link:
    table: str
    cols: list[str]
    ref_table: str
    ref_cols: list[str]
    confidence: float
    reason: str


# ---------- naming ----------
def singular(word: str) -> str:
    w = word.lower()
    if w.endswith("ies") and len(w) > 4:
        return word[:-3] + "y"
    if w.endswith(("sses", "shes", "ches", "xes")):
        return word[:-2]
    if w.endswith("s") and not w.endswith("ss"):
        return word[:-1]
    return word


def node_label(table: str) -> str:
    parts = [p for p in re.split(r"[_\W]+", table) if p]
    parts[-1] = singular(parts[-1])
    return "".join(p[:1].upper() + p[1:] for p in parts)


def edge_label(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_").upper()


# ---------- keys ----------
def guess_key(t: TableInfo) -> list[str]:
    """The declared primary key, or the first id-like column that's unique in the sample."""
    if t.primary_key:
        return list(t.primary_key)
    names = [c.name for c in t.columns]
    candidates = ["id", f"{singular(t.name)}_id", f"{t.name}_id"]
    candidates += [n for n in names if n.lower().endswith(("_id", "_key", "_code"))]
    for c in candidates:
        values = [r.get(c) for r in t.sample]
        if c in names and None not in values and len(set(values)) == len(values):
            return [c]
    return []


def _same_type(a: str, b: str) -> bool:
    return a == b or (a in NUMERIC and b in NUMERIC)


_REF = re.compile(r"(?:references?|foreign key (?:to|of|into)|points? to|links? to|id of (?:the|a|an)?)\s+`?([\w.]+)`?", re.I)


def _described(desc: str, table: str) -> bool:
    for m in _REF.finditer(desc or ""):
        word = m.group(1).strip(".").split(".")[-1].lower()
        if word in (table.lower(), singular(table).lower()):
            return True
    return False


def find_links(tables: list[TableInfo]) -> list[Link]:
    keys = {t.name: guess_key(t) for t in tables}
    best: dict[tuple, Link] = {}

    def add(link: Link):
        k = (link.table, tuple(link.cols))  # one target per column: keep the surest
        if k not in best or best[k].confidence < link.confidence:
            best[k] = link

    for t in tables:
        declared = set()
        for cols, ref, ref_cols in t.foreign_keys:
            if ref in keys:
                add(Link(t.name, cols, ref, ref_cols, 1.0, f"declared foreign key {', '.join(cols)} -> {ref}"))
                declared.update(cols)

        for col in t.columns:
            if col.name in declared or keys[t.name] == [col.name]:
                continue
            values = {str(r[col.name]) for r in t.sample if r.get(col.name) is not None}
            for u in tables:
                if u.name == t.name or len(keys[u.name]) != 1:
                    continue
                ukey = keys[u.name][0]
                kcol = u.column(ukey)
                if kcol is None or not _same_type(col.type, kcol.type):
                    continue
                c, p, stem = col.name.lower(), ukey.lower(), singular(u.name).lower()
                if _described(col.description, u.name):
                    add(Link(t.name, [col.name], u.name, [ukey], 0.8, f"description of {col.name} mentions {u.name}"))
                elif (p != "id" and (c == p or c.endswith("_" + p))) or c == f"{stem}_id":
                    add(Link(t.name, [col.name], u.name, [ukey], 0.6, f"{col.name} matches {u.name}.{ukey}"))
                elif col.type == "STRING" and len(values) >= 3 and values <= {str(r.get(ukey)) for r in u.sample}:
                    add(Link(t.name, [col.name], u.name, [ukey], 0.5,
                             f"all {len(values)} sampled values of {col.name} are {u.name}.{ukey} values"))
    return sorted(best.values(), key=lambda link: (link.table, link.cols))


# ---------- graph ----------
def infer(tables: list[TableInfo], *, name: str, project: str, dataset: str, location: str = "US",
          min_confidence: float = 0.5) -> tuple[GraphSpec, list[str]]:
    """Returns the proposed graph and notes about anything skipped."""
    notes: list[str] = []
    keys = {t.name: guess_key(t) for t in tables}
    links = [link for link in find_links(tables) if link.confidence >= min_confidence]
    out_links: dict[str, list[Link]] = {}
    for link in links:
        out_links.setdefault(link.table, []).append(link)
    referenced = {link.ref_table for link in links}

    def is_junction(t: TableInfo) -> bool:
        return len(out_links.get(t.name, [])) == 2 and t.name not in referenced

    labels: dict[str, str] = {}
    nodes = []
    for t in tables:
        if is_junction(t):
            continue
        if not keys[t.name]:
            notes.append(f"Skipped {t.name}: no key column found. Declare a primary key on it to include it.")
            continue
        labels[t.name] = node_label(t.name)
        nodes.append(Node(label=labels[t.name], table=t.name, key=keys[t.name], description=t.description))

    used = set(labels.values())

    def unique(label: str) -> str:
        out, i = label, 2
        while out in used:
            out, i = f"{label}_{i}", i + 1
        used.add(out)
        return out

    edges = []
    for t in tables:
        ls = out_links.get(t.name, [])
        if is_junction(t):
            order = [c.name for c in t.columns]
            a, b = sorted(ls, key=lambda link: order.index(link.cols[0]))
            if a.ref_table not in labels or b.ref_table not in labels:
                notes.append(f"Skipped {t.name}: it links to a table that isn't a node.")
                continue
            key = keys[t.name] or a.cols + b.cols
            edges.append(Edge(
                label=unique(edge_label(t.name)), table=t.name, key=key,
                source=labels[a.ref_table], source_key=a.cols, dest=labels[b.ref_table], dest_key=b.cols,
                confidence=min(a.confidence, b.confidence), reason=f"joins {a.ref_table} and {b.ref_table}",
            ))
        elif t.name in labels:
            for link in ls:
                if link.ref_table not in labels or link.ref_cols != keys[link.ref_table]:
                    continue
                base = re.sub(r"_(id|key|code)$", "", link.cols[0], flags=re.I)
                edges.append(Edge(
                    label=unique("HAS_" + edge_label(base)), table=t.name, key=keys[t.name],
                    source=labels[t.name], source_key=keys[t.name], dest=labels[link.ref_table], dest_key=link.cols,
                    confidence=link.confidence, reason=link.reason,
                ))

    for t in tables:
        if t.name in labels and not any(labels[t.name] in (e.source, e.dest) for e in edges):
            notes.append(f"{labels[t.name]} ({t.name}) has no links. Add an edge if it should have one.")
    spec = GraphSpec(name=name, project=project, dataset=dataset, location=location, nodes=nodes, edges=edges)
    return spec, notes
