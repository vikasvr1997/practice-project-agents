# Vehicle Safety Assistant: setup guide

This project is a multi-agent assistant built with Google ADK. It answers questions about vehicle crash data in BigQuery, using Gemini on Vertex AI. It remembers each conversation in memory (no persistence across restarts yet) and sits behind a FastAPI API that needs an API key. Every push to `main` deploys it to Cloud Run.

## How it fits together

```
client ──X-API-Key──▶ FastAPI (/chat, /sessions)
                        │
                        ▼
                 ADK Runner ◀──▶ In-memory session service (sessions, events, state)
                        │
             vehicle_assistant  (coordinator: routes each request)
             ├── safety_insights  curated, parameterized BigQuery reports
             ├── sql_analyst      free-form read-only SQL (ADK BigQueryToolset)
             └── report_writer    turns saved findings into a manager report
                        │
                        ▼
                   BigQuery (NHTSA crash data, 2015-2020)
```

- **The coordinator** never answers data questions itself. It transfers the conversation to a specialist.
- **safety_insights** can run only 3 pre-written queries, so it's cheap and safe. **sql_analyst** can write any `SELECT`, but ADK blocks writes and caps each query at 2 GB scanned.
- Both data agents save their answer to session state as `last_findings`, and **report_writer** reads it through its `{last_findings?}` instruction template. This is how agents share memory across turns within a session.
- To use your own data, set `BQ_DATA_PROJECT` and `BQ_DATASET`. The curated reports are written for the NHTSA table layout, so you'd adapt them to your tables.

## Project layout

| Path | What it does |
| --- | --- |
| `src/app/agents/vehicle_assistants/` | The 4 agents, their prompts, settings and tools. Self-contained, so `adk web` can load it on its own |
| `src/app/services/runner.py` | Wires the agents to an in-memory ADK session service (Firestore-backed persistence isn't wired up yet) |
| `src/app/api/routes/` | `/health`, `/chat` and `/sessions` routes |
| `src/app/core/` | Settings and API-key auth |
| `src/app/schemas/` | Request and response models |
| `ui.py`, `.streamlit/` | Claude-style Streamlit chat UI and its theme |
| `tests/` | Tests: auth, an end-to-end chat with a fake model, and the tools |
| `infra/` | Terraform: registry, secret, service accounts, build trigger |
| `cloudbuild.yaml`, `Dockerfile` | CI/CD: test, build, deploy to Cloud Run |

## Run it locally first (30 min)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env            # fill in your project ID and a random API key
gcloud auth application-default login

pytest -q
adk web src/app/agents          # chat in the browser at http://localhost:8000
uvicorn app.main:app --app-dir src --reload   # the real API; try it at http://localhost:8000/docs
```

Try asking: "Which states had the most traffic deaths in 2020?", then "Write that up as a report for my manager." The second answer should come from `report_writer` and use the numbers from the first.

To run the Firestore tests too:

```bash
gcloud emulators firestore start --host-port=127.0.0.1:8085   # in another terminal
FIRESTORE_EMULATOR_HOST=127.0.0.1:8085 pytest -q              # 10 pass
```

## Chat UI (Streamlit)

`ui.py` is a Claude-style chat screen for the agents. It talks to the API over HTTP with your API key, like a real frontend would.

```bash
pip install -r requirements-ui.txt
uvicorn app.main:app --app-dir src --port 8080      # terminal 1: the API
streamlit run ui.py                   # terminal 2: the UI at http://localhost:8501
```

Enter your API key under Settings at the bottom of the sidebar, or set `APP_API_KEY` before starting the UI. To use the deployed API, set the API URL in Settings to your Cloud Run URL.

| Where | Button | What it does |
| --- | --- | --- |
| Sidebar | New chat | Starts a fresh conversation (a new session) |
| Sidebar | Search chats | Filters your recent chats by title |
| Sidebar | Recents | Opens a past conversation, loaded from Firestore |
| Sidebar | ••• | Rename or delete a chat |
| Sidebar | Settings | API URL, API key and user ID, plus a connected/offline light |
| Top bar | Export | Downloads the conversation as Markdown |
| Top bar | End chat | Asks to confirm, then deletes the conversation and its memory |
| Empty chat | Suggestion buttons | Sends a starter question |
| Your message | Edit | Change the message and resend it |
| Answer | Copy | Shows the text in a box with a copy icon |
| Answer | Retry | Sends your last message again |
| Answer | Thumbs up/down | Rates the answer |
| Chat box | + | Attach text files (txt, md, csv, json, sql); their content is added to your message |
| Chat box | Send / Stop | While the agents work, Send turns into Stop |

Limits to know:
- **Stop** ends the wait in the UI, but the API finishes the request in the background. Its answer is saved to the session and shows if you reopen the chat.
- **Edit** and **Retry** add a new turn to the same session; ADK sessions don't support branching. **Rename** and the thumbs ratings live only in your browser session. Saving them would need a small extra API endpoint.

## API

| Method | Path | Body or result |
| --- | --- | --- |
| GET | `/health` | No key needed |
| POST | `/chat` | `{"user_id", "session_id"?, "message"}` returns `{"session_id", "agent", "answer"}`. Leave `session_id` empty to start a new conversation |
| GET | `/sessions/{user_id}` | That user's conversations, newest first |
| GET | `/sessions/{user_id}/{session_id}` | The conversation's messages |
| DELETE | `/sessions/{user_id}/{session_id}` | Deletes it from the session store |

All routes except `/health` need the header `X-API-Key`.

## Deploy to GCP

### Step 1: Prerequisites (10 min)

1. You need a GCP project **with billing turned on**. Cloud Run and Cloud Build need it, but this project stays inside the free tier at low traffic. Set a budget alert of $5 under Billing > Budgets & alerts.
2. Install Terraform 1.6 or newer.
3. Sign in:

```bash
gcloud auth login
gcloud auth application-default login
gcloud config set project YOUR_PROJECT_ID
```

4. Push this project to your own GitHub repo. The included `.gitignore` already keeps `.env`, Terraform state and `terraform.tfvars` out of Git.

### Step 2: Create the infrastructure with Terraform (15 min)

```bash
cd infra
cp terraform.tfvars.example terraform.tfvars   # then edit your project ID and GitHub names
terraform init
terraform plan     # read this: it should list about 25 resources to create
terraform apply
```

The default is `us-central1` for Cloud Run. If you're in India, set `region = "asia-south1"` in `terraform.tfvars`.

### Step 3: Add the API key value (2 min)

Terraform creates an empty secret, so the key never lands in Git or Terraform state. Add the value yourself:

```bash
openssl rand -hex 32 | gcloud secrets versions add app-api-key --data-file=-
gcloud secrets versions access latest --secret=app-api-key   # copy this for testing
```

Cloud Run passes this to the app as the `APP_API_KEY` environment variable, which `src/app/core/config.py` reads.

### Step 4: Allow Gemini on Vertex AI (2 min)

In the console, open Vertex AI and enable the API if it asks. The pipeline deploys with `MODEL=gemini-3.5-flash` on the `global` endpoint. If that model isn't available in your project, change `model` in `terraform.tfvars` and `_MODEL` in `cloudbuild.yaml`.

### Step 5: Connect GitHub and turn on the trigger (10 min)

1. In the console, open Cloud Build > Repositories (1st gen) > Connect repository. Choose GitHub (Cloud Build GitHub App) and select your repo. Don't create a trigger there.
2. In `infra/terraform.tfvars`, set `create_trigger = true`, then run `terraform apply` again.

### Step 6: Deploy by pushing (5 min)

```bash
git push origin main
```

Watch it run under Cloud Build > History. When it's green, test it:

```bash
URL=$(gcloud run services describe vehicle-agent --region us-central1 --format='value(status.url)')
curl $URL/health
curl -X POST $URL/chat -H "X-API-Key: YOUR_KEY" -H "Content-Type: application/json" \
     -d '{"user_id": "vikas", "message": "Which state had the most fatal crashes in 2020?"}'
```

## If something fails

| Error | Fix |
| --- | --- |
| Deploy step: `Permission denied ... iam.serviceaccounts.actAs` | Re-run `terraform apply`; IAM changes can take a few minutes to apply |
| Deploy step: secret `app-api-key` has no versions | Do step 3 |
| Agent errors on Cloud Run about an API key | Cloud Run uses Vertex AI, not your AI Studio key. Check that `GOOGLE_GENAI_USE_VERTEXAI=TRUE` is set (the pipeline sets it) |

## Known limits (good interview talking points)

- **One shared API key.** Anyone with the key can read any `user_id`'s sessions. The next step is real user sign-in, such as Firebase Auth or Google ID tokens, with `user_id` taken from the verified token instead of the request body.
- **The curated report queries use the NHTSA column names `state_name`, `month_of_crash`, `hour_of_crash` and `number_of_fatalities`.** They were tested with fake data, not against live BigQuery. If one errors, the agent hands over to `sql_analyst`. Fix the column name in `src/app/agents/vehicle_assistants/tools/safety_queries.py`.
- **Sessions are in-memory only.** They don't survive a restart or scale past one instance. Swap in a persistent `BaseSessionService` (e.g. Firestore-backed) in `src/app/services/runner.py` when that's needed.

## What to say about this in interviews

- **Multi-agent design:** a coordinator routes to specialists, so each agent has a small prompt and few tools. That makes them more reliable and easier to test.
- **Infrastructure as code:** every resource is in Terraform, so the environment is reviewable and reproducible.
- **Least privilege:** the app and the pipeline run as separate service accounts. Each has only the roles it needs.
- **Secrets:** they live in Secret Manager, never in code, Git or Terraform state.
- **CI/CD:** every push runs the tests before anything deploys, and every image is tagged with its build ID so you can roll back.
- **Next upgrades:** remote Terraform state in GCS, a staging environment, and Workload Identity Federation for GitHub Actions.
