# Vehicle Safety Assistant

A multi-agent AI assistant on Google Cloud that answers questions about US vehicle crash data and an automotive supply chain. It's built with [Google ADK](https://google.github.io/adk-docs/) and Gemini on Vertex AI, served by FastAPI and Streamlit on Cloud Run, and deployed by GitHub Actions on every merge to `main`.

Ask things like:

- "Which states had the most traffic deaths in 2020?"
- "Write that up as a report for my manager."
- "Which vehicle models use parts from Northstar Brakes?"

## How it works

```
Streamlit UI ──X-API-Key──▶ FastAPI on Cloud Run (/chat, /sessions, /graphs)
                                │
                                ▼  Model Armor screens every prompt and answer
                         ADK Runner ◀──▶ Firestore sessions (memory locally)
                                │
                     vehicle_assistant  (coordinator: routes each request)
                     ├── safety_insights       3 curated BigQuery reports
                     ├── sql_analyst           free-form, read-only SQL
                     ├── supply_chain_analyst  read-only GQL on a BigQuery property graph
                     └── report_writer         turns findings into a manager report
                                │
                                ▼
          BigQuery: NHTSA crash data (2015-2020) + vehicle_supply_chain graph
```

## Features

- **Multi-agent routing:** a coordinator hands each question to the right specialist, and the specialists share findings through session state.
- **Safe data access:** curated parameterized queries, read-only SQL with a 2 GB scan cap, and graph queries that refuse anything that writes.
- **Guardrails:** Model Armor blocks prompt injection, jailbreaks, harmful content and sensitive data, both going in and coming out.
- **Graph Creator:** scans a BigQuery dataset, infers how its tables link, and proposes a property graph as DDL plus Terraform for a developer to review. It never creates anything itself.
- **Persistent conversations:** sessions are stored in Firestore, so chats survive restarts.
- **Structured logging:** one JSON line per agent step (transfers, tool calls, tool errors, guardrail blocks), all tied together by a request id, so you can see in Cloud Logging where an agent went wrong.
- **Tested and evaluated:** pytest with a fake LLM (no cloud calls), plus an ADK eval set with pass thresholds.
- **Infrastructure as code:** Terraform for every GCP resource. GitHub Actions uses keyless Workload Identity Federation.

## Tech stack

Python 3.12 · Google ADK 2.11 · Gemini 2.5 Flash (Vertex AI) · BigQuery and BigQuery Graph · Firestore · Model Armor · FastAPI · Streamlit · Docker · Cloud Run · Terraform · GitHub Actions

## Quick start (local)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env                  # set your GCP project id and a random APP_API_KEY
gcloud auth application-default login

pytest -q                             # all tests, no cloud calls
adk web src/app/agents                # chat with the agents in ADK's dev UI
uvicorn app.main:app --app-dir src --reload --port 8080   # the API (docs at /docs)
pip install -r requirements-ui.txt && streamlit run ui.py # the chat UI
```

## Deploy to GCP

1. `cd infra && terraform init && terraform apply` creates the APIs, service accounts, Artifact Registry, Secret Manager, Firestore, Model Armor and the GitHub OIDC trust.
2. Copy the Terraform outputs into GitHub Actions variables (`GCP_PROJECT_ID`, `GCP_REGION`, `GCP_WORKLOAD_IDENTITY_PROVIDER` and the rest).
3. Push to `main`. GitHub Actions tests, builds and deploys both the API and the UI to Cloud Run.

Optional features turn on with the GitHub variables `MODEL_ARMOR_TEMPLATE` and `SUPPLY_CHAIN_GRAPH`. The supply-chain graph has its own Terraform in `graphs/supply_chain/terraform/`. Graph queries need a BigQuery Enterprise reservation.

See **[GUIDE.md](GUIDE.md)** for the full step-by-step setup, troubleshooting and design notes.

## Project layout

| Path | What's there |
| --- | --- |
| `src/app/agents/vehicle_assistants/` | The agents, prompts, tools, settings and Model Armor guardrails |
| `src/app/api/`, `src/app/core/`, `src/app/schemas/` | FastAPI routes, settings, API-key auth, request models |
| `src/app/services/` | ADK runner and the Firestore session service |
| `src/app/graphs/` | Graph Creator: inference, DDL and Terraform generation |
| `ui.py`, `ui_api.py`, `pages/` | Streamlit chat UI and Graph Creator page |
| `tests/`, `evals/` | Unit tests (fake LLM) and the ADK eval set |
| `infra/` | Terraform for the platform |
| `graphs/supply_chain/` | Sample supply-chain data and the Terraform that builds its graph |
| `.github/workflows/ci-cd.yml` | Test on PR, deploy on merge |

## License

[MIT](LICENSE) © 2026 Vikas Reddy Bodireddy
