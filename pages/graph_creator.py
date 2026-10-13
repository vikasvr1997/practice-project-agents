"""Graph Creator page: see every property graph in BigQuery, and propose new ones.

Opened from the "Graph Creator" button at the top of the chat. Nothing on
this page creates a graph: a proposal ends as Terraform files that a
developer reviews and runs themselves.
"""
from __future__ import annotations

import io
import os
import zipfile

import streamlit as st

from ui_api import ApiClient, ApiError

st.set_page_config(page_title="Graph Creator", page_icon="🕸️", layout="wide")

NODE_COLUMNS = ["label", "table", "key", "description"]
EDGE_COLUMNS = ["label", "source", "dest", "table", "key", "source_key", "dest_key", "confidence", "reason"]


def init_state() -> None:
    # Shared with the chat page when you come from there; env vars otherwise.
    s = st.session_state
    s.setdefault("api_url", os.getenv("API_URL", "http://localhost:8080"))
    s.setdefault("api_key", os.getenv("APP_API_KEY", ""))
    s.setdefault("user_id", os.getenv("UI_USER_ID", "vikas"))
    s.setdefault("gc_proposal", None)  # the proposal open in the editor


def client() -> ApiClient:
    s = st.session_state
    return ApiClient(s.api_url, s.api_key, s.user_id)


def cols(value: str) -> list[str]:
    return [c.strip() for c in str(value or "").split(",") if c.strip()]


# ---------- picture ----------

def dot(spec: dict) -> str:
    """Graphviz picture: circles for node labels, arrows for edges."""
    lines = ['digraph G {', '  rankdir=LR; bgcolor="transparent"; size="10,4";',
             '  node [shape=circle, width=1.1, fixedsize=true, style=filled, fillcolor="#D97757", color="#D97757",'
             ' fontcolor=white, fontname="Helvetica", fontsize=10];',
             '  edge [fontname="Helvetica", fontsize=9, color="#8a8a8a", fontcolor="#8a8a8a"];']
    for n in spec["nodes"]:
        lines.append(f'  "{n["label"]}";')
    for e in spec["edges"]:
        style = ', style=dashed, color="#E8A13A"' if e.get("confidence", 1) < 0.6 else ""
        lines.append(f'  "{e["source"]}" -> "{e["dest"]}" [label="{e["label"]}"{style}];')
    return "\n".join(lines + ["}"])


# ---------- list ----------

def graph_list(project: str | None) -> None:
    left, right = st.columns([3, 1], vertical_alignment="bottom")
    datasets = ["All datasets"]
    try:
        datasets += [d["dataset"] for d in client().datasets(project)]
    except ApiError as e:
        st.error(str(e))
    dataset = left.selectbox("Dataset", datasets, key="gc_list_dataset")
    right.button("↻ Refresh", use_container_width=True)
    try:
        data = client().graphs(project, None if dataset == "All datasets" else dataset)
    except ApiError as e:
        st.error(str(e))
        return

    st.markdown(f"#### In BigQuery ({len(data['existing'])})")
    if data["existing"]:
        for g in data["existing"]:
            with st.expander(f"**{g['name']}** · {g['dataset']}"):
                st.caption(f"`{g['full_name']}` · ask the chat agents about it, or open it in BigQuery Studio.")
                if g.get("ddl"):
                    st.code(g["ddl"], language="sql")
    else:
        st.caption("No property graphs yet in this project" + ("" if dataset == "All datasets" else f" / {dataset}") + ".")
    for err in data.get("errors", []):
        st.caption(f"⚠️ Couldn't read {err}")

    st.markdown(f"#### Proposed, not created yet ({len(data['proposals'])})")
    if not data["proposals"]:
        st.caption("Nothing proposed. Use **Create a graph** to scan a dataset.")
    for p in data["proposals"]:
        spec = p["spec"]
        name_col, info_col, open_col, del_col = st.columns([3, 3, 1, 1], vertical_alignment="center")
        name_col.markdown(f"**{spec['name']}** · {spec['dataset']}")
        problems = f" · ⚠️ {len(p['problems'])} to fix" if p["problems"] else ""
        info_col.caption(f"{len(spec['nodes'])} nodes, {len(spec['edges'])} edges · {p['created_at'][:16].replace('T', ' ')}{problems}")
        if open_col.button("Open", key=f"open_{p['id']}", use_container_width=True):
            st.session_state.gc_proposal = p
            st.toast(f"Opened {spec['name']}. See the Create a graph tab.")
        if del_col.button("Delete", key=f"del_{p['id']}", use_container_width=True):
            try:
                client().delete_graph(p["id"])
                if (st.session_state.gc_proposal or {}).get("id") == p["id"]:
                    st.session_state.gc_proposal = None
                st.rerun()
            except ApiError as e:
                st.error(str(e))


# ---------- create ----------

def new_proposal_form(project: str | None) -> None:
    try:
        datasets = [d["dataset"] for d in client().datasets(project)]
    except ApiError as e:
        st.error(str(e))
        datasets = []
    with st.form("gc_new"):
        a, b = st.columns(2)
        dataset = a.selectbox("Dataset to scan", datasets, index=None, placeholder="Pick a dataset",
                              accept_new_options=True)
        name = b.text_input("Graph name", placeholder="SupplyChain", help="Letters, digits and _; starts with a letter.")
        st.caption("Reads table metadata and 50 sample rows per table (free: no query is run). Creates nothing.")
        if st.form_submit_button("🔍 Scan tables and propose a graph", type="primary"):
            if not dataset or not name:
                st.warning("Pick a dataset and give the graph a name.")
                return
            with st.spinner(f"Scanning {dataset}..."):
                try:
                    st.session_state.gc_proposal = client().propose_graph(project, dataset, name)
                except ApiError as e:
                    st.error(str(e))


def editor(p: dict) -> None:
    spec = p["spec"]
    st.markdown(f"### {spec['name']} · `{spec['project']}.{spec['dataset']}`")
    st.caption("Circles are node tables, arrows are links. Dashed orange arrows were guessed from values only: check them.")
    st.graphviz_chart(dot(spec), use_container_width=True)
    for note in p.get("notes", []):
        st.caption(f"ℹ️ {note}")

    st.markdown("#### Edit")
    st.caption("Change labels or keys, tick **flip** to reverse an arrow, or select rows and delete them. Then save.")
    nodes = st.data_editor(
        [{c: ", ".join(n[c]) if c == "key" else n[c] for c in NODE_COLUMNS} for n in spec["nodes"]],
        num_rows="dynamic", use_container_width=True, key=f"nodes_{p['id']}_{p.get('updated_at', '')}",
        column_config={"key": st.column_config.TextColumn(help="Key columns, comma-separated")},
    )
    edges = st.data_editor(
        [{"flip": False, **{c: ", ".join(e[c]) if isinstance(e[c], list) else e[c] for c in EDGE_COLUMNS}}
         for e in spec["edges"]],
        num_rows="dynamic", use_container_width=True, key=f"edges_{p['id']}_{p.get('updated_at', '')}",
        disabled=["confidence", "reason"],
        column_config={
            "flip": st.column_config.CheckboxColumn(help="Reverse the arrow"),
            "confidence": st.column_config.ProgressColumn(min_value=0, max_value=1, format="%.1f"),
        },
    )
    if st.button("💾 Save changes", type="primary"):
        new_edges = []
        for e in edges:
            if not e.get("label"):
                continue
            src, src_key, dst, dst_key = e["source"], cols(e["source_key"]), e["dest"], cols(e["dest_key"])
            if e.get("flip"):
                src, src_key, dst, dst_key = dst, dst_key, src, src_key
            new_edges.append({"label": e["label"], "table": e["table"], "key": cols(e["key"]),
                              "source": src, "source_key": src_key, "dest": dst, "dest_key": dst_key,
                              "confidence": e.get("confidence") or 1.0, "reason": e.get("reason") or "added by hand"})
        new_spec = {**spec,
                    "nodes": [{"label": n["label"], "table": n["table"], "key": cols(n["key"]),
                               "description": n.get("description") or ""} for n in nodes if n.get("label")],
                    "edges": new_edges}
        try:
            st.session_state.gc_proposal = client().update_graph(p["id"], new_spec)
            st.rerun()
        except ApiError as e:
            st.error(str(e))

    if p["problems"]:
        st.warning("Fix these before running the Terraform:\n\n" + "\n".join(f"- {x}" for x in p["problems"]))

    st.markdown("#### Proposed Terraform (you run it)")
    st.info(
        "This page doesn't create the graph. Download the files, review them, then run:\n\n"
        "`terraform init` → `terraform plan` → `terraform apply`\n\n"
        "Automatic creation can be switched on later."
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for fname, text in p["terraform"].items():
            z.writestr(f"{spec['name']}/{fname}", text)
    st.download_button("⬇️ Download Terraform (.zip)", buf.getvalue(), file_name=f"graph-{spec['name']}.zip",
                       mime="application/zip")
    tf_tab, sql_tab = st.tabs(["main.tf", "graph.sql"])
    tf_tab.code(p["terraform"]["main.tf"], language="hcl")
    sql_tab.code(p["terraform"]["graph.sql"], language="sql")


# ---------- page ----------

def main() -> None:
    init_state()
    s = st.session_state
    back, title = st.columns([1, 6], vertical_alignment="center")
    if back.button("← Chat", use_container_width=True):
        st.switch_page("ui.py")
    title.markdown("## 🕸️ Graph Creator")
    st.caption("See the property graphs in BigQuery, and propose new ones from a dataset's tables. "
               "Proposals become Terraform that a developer reviews and runs.")
    if not s.api_key:
        st.info("Add your API key in ⚙️ Settings on the chat page first.")
        return
    project = st.text_input("GCP project", key="gc_project", placeholder="Leave empty for the API's own project").strip() or None

    list_tab, create_tab = st.tabs(["All graphs", "Create a graph"])
    with list_tab:
        graph_list(project)
    with create_tab:
        new_proposal_form(project)
        if s.gc_proposal:
            st.divider()
            editor(s.gc_proposal)


main()
