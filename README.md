# Vehicle Safety Assistant

A multi-agent AI assistant that answers questions about US vehicle crash data and a vehicle supply chain. It is built with [Google ADK](https://google.github.io/adk-docs/), runs on Gemini through Vertex AI, and is deployed on Google Cloud Run.

Ask it things like:
- "Which states had the most traffic deaths in 2020?"
- "Write that up as a report for my manager."
- "If supplier Northstar Brakes fails, which vehicle models are affected?"

## What's inside

```
Streamlit UI ──▶ FastAPI (X-API-Key) ──▶ Model Armor guardrails ──▶ ADK agents ──▶ BigQuery
```

| Agent | What it does |
| --- | --- |
| `vehicle_assistant` | Coordinator. It sends each question to the right specialist |
| `safety_insights` | Runs 3 pre-written, parameterized reports on NHTSA crash data |
| `sql_analyst` | Writes its own read-only SQL with ADK's BigQuery toolset |
| `supply_chain_analyst` | Runs read-only graph queries (GQL) on a BigQuery property graph |
| `report_writer` | Turns the last findings into a short report |

It also includes:
- **Graph Creator:** a UI page that lists the property graphs in BigQuery and proposes new ones from a dataset's tables. It outputs DDL and Terraform for a developer to review and run, and never creates a graph itself.
- **Model Armor:** screens every prompt and answer for prompt injection and sensitive data.
- **Evals:** an ADK golden eval set that checks tool choice, answer quality, hallucination and safety.
- **Sessions:** kept in memory or in Firestore.
- **Infra and CI/CD:** Terraform for GCP, and GitHub Actions that test every PR and deploy `main` to Cloud Run with Workload Identity.

## Quick start

You need Python 3.12+, a GCP project with Vertex AI and BigQuery enabled, and the `gcloud` CLI.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env                 # fill in your project ID and an API key
gcloud auth application-default login

pytest -q                                         # tests, using a fake model
adk web src/app/agents                            # try the agents in a browser
uvicorn app.main:app --app-dir src --reload       # the API, docs at /docs
streamlit run ui.py                               # the chat UI
```

## Project layout

| Path | What it holds |
| --- | --- |
| `src/app/agents/vehicle_assistants/` | Agents, prompts, tools and guardrails |
| `src/app/api/`, `src/app/core/`, `src/app/services/` | FastAPI routes, settings, API-key auth and the ADK runner |
| `src/app/graphs/` | Graph Creator logic |
| `ui.py`, `ui_api.py`, `pages/` | Streamlit chat UI and the Graph Creator page |
| `evals/` | Eval set and pass thresholds |
| `graphs/supply_chain/` | Sample supply-chain data and the Terraform for its graph |
| `infra/` | Terraform for the cloud setup |
| `tests/` | pytest suite |

## Learn more

[GUIDE.md](GUIDE.md) is the full walkthrough: how the agents share memory, deploying to Cloud Run, evals, Model Armor, the graph agent and Graph Creator.

## Data

- Crash data comes from the public NHTSA FARS dataset in BigQuery (`bigquery-public-data.nhtsa_traffic_fatalities`).
- The supply-chain data in `graphs/supply_chain/data/` is made up for this project.

## License

MIT. See [LICENSE](LICENSE).
