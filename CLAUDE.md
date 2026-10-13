# Notes for Claude

Read GUIDE.md for the full walkthrough. Vikas is learning to become an AI engineer (basic Python, good with Git, learns by building): explain changes in plain words and keep code readable.

## The project

Google ADK 2.11 multi-agent assistant on GCP. Code lives under `src/` (`pytest.ini` sets `pythonpath = src`; run the API with `uvicorn app.main:app --app-dir src`).
- `src/app/agents/vehicle_assistants/`: `vehicle_assistant` coordinator routes to `safety_insights` (3 curated BigQuery reports), `sql_analyst` (read-only BigQueryToolset), `supply_chain_analyst` (read-only GQL, only added when `SUPPLY_CHAIN_GRAPH` is set) and `report_writer` (reads `{last_findings?}`).
- `agent.py` exposes `app = App(..., plugins=build_plugins())`; `guardrails.py` adds ADK's `ModelArmorPlugin` only when `MODEL_ARMOR_TEMPLATE` is set. `services/runner.py` runs that `App`.
- `src/app/graphs/` + `src/app/api/routes/graphs.py` + `pages/graph_creator.py`: Graph Creator. It lists BigQuery property graphs and proposes new ones as DDL + Terraform. It must never create graphs itself: the developer runs the Terraform. Automation is a later, separate step.
- FastAPI with `X-API-Key` auth; sessions in memory or Firestore (`SESSION_BACKEND`). Streamlit UI in `ui.py` (API client in `ui_api.py`).
- CI/CD: `.github/workflows/ci-cd.yml` (tests on PRs; on main, builds and deploys API and UI to Cloud Run with Workload Identity). Optional features are switched on by the GitHub Actions variables `MODEL_ARMOR_TEMPLATE` and `SUPPLY_CHAIN_GRAPH`.
- `infra/`: Terraform (Google provider 7.x). `graphs/supply_chain/terraform/` is a separate folder the developer runs by hand.

## Commands

```bash
pip install -r requirements-dev.txt
pytest -q
adk web src/app/agents
uvicorn app.main:app --app-dir src --reload
streamlit run ui.py
adk eval src/app/agents/vehicle_assistants evals/vehicle_assistant.test.json --config_file_path evals/test_config.json
```

## Things learned the hard way

- NHTSA public table ids have a leading space (`. accident_2020`); see `tools/safety_queries.py`.
- Tests rely on `tests/conftest.py` (`APP_API_KEY=test-key`, a fake `SUPPLY_CHAIN_GRAPH`). Don't override them in CI.
- ADK 2.11: BigQuery tools are in `google.adk.integrations.bigquery`, Model Armor in `google.adk.integrations.model_armor` (needs `google-cloud-modelarmor`), evals need `google-adk[eval]`.
- If you rename graph labels, update `prompts.py` (`SUPPLY_CHAIN`); a test checks them against `graphs/supply_chain/graph.sql.tftpl`.

## Not tried on real GCP yet

Model Armor template, live evals, the supply-chain Terraform and graph queries, and the Graph Creator against real BigQuery (`INFORMATION_SCHEMA.PROPERTY_GRAPHS` column names are read defensively).
