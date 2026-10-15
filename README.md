# Insurance AI Agents POC: Policy Renewals, Retention & Personalised Offers

AI agents track every renewal, spot customers likely to leave, send the right message at the right time and suggest suitable extra cover (Use Case 5). Hard business rules run first, an LLM makes bounded decisions inside them, a human approves every follow-up, and every step is audited.

- Requirements: [docs/prd.md](docs/prd.md)
- Rules, thresholds and limits: [docs/business_rules.md](docs/business_rules.md)
- Architecture: [docs/architecture.md](docs/architecture.md)
- Product catalogue: [docs/product_catalogue.md](docs/product_catalogue.md)

## Layout

```
insuranceai/
  .venv/              Python virtual environment (create it, see below)
  requirements.txt    backend dependencies
  .env                settings + LLM keys (copy from .env.example)
  backend/
    agents/           the five use case 5 agents (one folder each) + graph.py
    data/             all data: one CSV file per table
    api/              FastAPI routes and schemas
    services/         hard rules, LLM client, run queue, approvals, lifecycle scan
    integrations/     CRM, policy admin, billing, messaging (mock adapters)
    db/               CSV-backed store, models, repositories
    scripts/          seed / reset data, renewal demo, OpenAPI export
    tests/            unit + integration tests
  docs/               PRD, business rules, architecture, product catalogue
  frontend/           InsureAI web UI (Next.js): the 8 use case 5 pages
```

## The agents (`backend/agents/`)

```
renewal → retention → recommendation → personalisation → workflow
```

| Agent | Does |
|---|---|
| **Renewal** | Tracks upcoming expiries, payment status and pending documents; works out which next steps the rules allow |
| **Retention** | Spots early signs a customer may not renew and picks the next step, channel and any discount (LLM, rule-bounded) |
| **Recommendation** | Finds the extra cover the customer is eligible for and that suits them |
| **Personalisation** | Drafts the message from the customer's policy and preferences (LLM) |
| **Workflow** | Queues the follow-up for approval with the right renewal / payment / upload link; after approval sends it and updates the CRM |

## Quick start (Windows PowerShell; on macOS / Linux use `source .venv/bin/activate`)

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env                              # set LLM_PROVIDER + its API key

python -m backend.scripts.seed_data --size full    # writes backend/data/*.csv
python -m uvicorn main:app --reload        # API docs: http://127.0.0.1:8000/docs
python -m backend.scripts.run_renewal_demo         # scripted demo against the running API
```

Run every command from this folder (`D:\insuranceai`).

- To start from scratch, run `python -m backend.scripts.reset_db`, which deletes the CSV files.
- Stop the API before seeding, resetting or editing a CSV by hand: the running app owns the data folder.

## Web UI (`frontend/`)

In a second terminal, with the API running:

```bash
cd frontend
npm install
npm run dev                                        # http://localhost:3000
```

Pick a name and team on first visit; approvals need the retention or adviser team (or admin).

| Page | What it shows |
|---|---|
| Renewals Dashboard | Total / due / at-risk / renewal-rate tiles, renewal trend, policy status (with what each status means), urgent customers, "Run agents" |
| Renewal Management | Every policy with filters (due in 7 / 30 days, overdue, at risk), status and suggested next step |
| Retention & Churn | How many customers may leave, the main reasons, and who they are, with a risk score |
| Messages to Approve | Every message the agents prepared that is waiting for a person to approve |
| Additional Cover | Customers who can be offered extra cover, and the cover the agent suggests |
| Workflow & Follow-ups | Identify → Message → Send → Track counts, and each follow-up's status and next step |
| **Customer** (click any name) | Everything about one customer in one place: what's happening and what to do next, the message with Approve & Send / Edit / Reject, extra cover options, CRM history, how the AI decided, policy, contact and consent, documents still needed (mark received), payments |

The UI calls the API at `NEXT_PUBLIC_API_URL` (default `http://localhost:8000`); that origin must be in the backend's `CORS_ORIGINS` (default `http://localhost:3000`).

## Data

Everything lives in `backend/data/`, one CSV file per table:

| Group | Files |
|---|---|
| Business data | `products.csv`, `customers.csv`, `policies.csv`, `payments.csv` |
| Agent results | `recommendations.csv`, `approvals.csv`, `messages.csv`, `crm_activities.csv` |
| Audit | `audit_events.csv` (every step, with time) |

Kept in memory only while the app runs (no file): agent jobs and their progress, sign-in names and logins, and the AI prompts and answers. After a restart, everyone picks their name again, and any agent run that was still going is simply started again with "Run agents".

How the files are used:

- **At startup:** the app loads them.
- **After every change:** it writes the changed tables back to their files.
- **Format:**
  - an empty cell is empty
  - booleans are `true` / `false`
  - dates are ISO 8601
  - JSON columns hold JSON text

There is no database.

## LLM providers (`.env`)

| Provider | Settings | Notes |
|---|---|---|
| Domo AI | `LLM_PROVIDER=domo`, `DOMO_API_KEY`, `DOMO_BASE_URL`, `DOMO_MODEL` | Keep `LLM_STRUCTURED_MODE=prompt` |
| Anthropic | `LLM_PROVIDER=anthropic`, `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL` | Use `LLM_STRUCTURED_MODE=json_schema` |

The LLM is required. If it is unavailable after retries, the run fails with `llm_unavailable` and can be retried with `POST /runs/{id}/retry`. `GET /health?deep=true` makes one real test call. Set `AS_OF_DATE=2026-10-13` to freeze "today" for reproducible demos.

## API

Pick a user first (no passwords): `POST /sessions {"name": "Rita", "role": "retention"}`, then send the returned id as `X-Session-Id`. Roles: `retention`, `adviser`, `admin`; each approval queue accepts its own role plus admin.

| Endpoint | Purpose |
|---|---|
| `GET /health` | Data store, runner, LLM config (`?deep=true` pings the LLM) |
| `POST /sessions`, `GET /sessions/me`, `POST /sessions/heartbeat`, `DELETE /sessions/current`, `GET /users/active` | Lightweight identity |
| `POST /renewals/scan`, `GET /renewals`, `GET /renewals/{id}`, `POST /renewals/{id}/runs` | Lifecycle scan, worklist, policy detail, run one policy |
| `POST /renewals/{id}/documents`, `GET /renewals/{id}/crm` | Record documents received; CRM activity written back by the workflow agent |
| `GET /runs`, `GET /runs/{id}`, `POST /runs/{id}/retry`, `GET /batches/{id}` | Async progress |
| `GET /recommendations`, `GET /recommendations/{id}` | Approval queue + full context (rules, LLM calls, audit, justification) |
| `POST /approvals/{id}/approve` · `/reject` · `/edit` | Human decision |
| `GET /dashboard`, `GET /kpi/renewal/{metric}` | Dashboard and drill-downs |
| `GET /audit`, `GET /messages`, `POST /messages/{id}/retry`, `GET /stats` | Audit, outbox, stats |

Errors always look like `{"error": {"code", "message", "details"}}`.

## Tests

```bash
python -m pytest          # offline: fake LLM + mocked HTTP (settings in pytest.ini)
```
