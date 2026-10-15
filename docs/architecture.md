# System architecture

This document describes the backend of the use case 5 proof of concept: policy renewals, retention and personalised offers. The backend runs the agents and owns all data; any frontend talks to it through the HTTP API.

## Component and data-flow diagram

```mermaid
flowchart LR
    Client["Frontend / API client<br/>X-Session-Id header"]

    subgraph ApiService["FastAPI service (backend/)"]
        Routes["REST routes (api/)<br/>health · sessions · renewals · runs<br/>recommendations · approvals · audit<br/>messages · dashboard · kpi"]
        Intake["Lifecycle scan (services/intake, lifecycle)<br/>assess every policy · enqueue"]
        Runner["Run queue + workers (services/runner)<br/>atomic claims · heartbeats · recovery"]

        subgraph Agents["Agents (agents/, LangGraph)"]
            Renewal["Renewal agent<br/>expiries · payments · documents"]
            Retention["Retention agent<br/>lapse risk · next step"]
            Recommendation["Recommendation agent<br/>suitable extra cover"]
            Personalisation["Personalisation agent<br/>message draft"]
            Workflow["Workflow agent<br/>approval queue · links · delivery · CRM"]
            Renewal --> Retention --> Recommendation --> Personalisation --> Workflow
            Renewal -. "nothing due" .-> Workflow
        end

        Rules["Hard rules (services/rules, rulebook.py)<br/>lifecycle · consent · caps · suitability<br/>routing · fairness"]
        LLMClient["LLM client (services/llm)<br/>fairness scan · rate limit · retries<br/>validation + one repair"]
        HITL["Approvals (services/approvals)<br/>role · version · expiry · revalidation"]
        Store["Data store (db/)<br/>in-memory records · unique rules"]

        Routes --> Intake --> Runner --> Agents
        Agents --> Rules
        Agents --> LLMClient
        Routes --> HITL --> Workflow
        Agents --> Store
        HITL --> Store
        Routes --> Store
    end

    CSV[("backend/data/*.csv<br/>one file per table")]
    LLM["Domo AI or Anthropic<br/>(fake provider in tests)"]
    Mocks["Integrations (integrations/)<br/>CRM · policy admin · billing · messaging<br/>mock adapters"]

    Client <-->|"JSON over HTTP"| Routes
    Store <-->|"load on start · save after each change"| CSV
    LLMClient <-->|"bounded prompts / structured output"| LLM
    Agents <--> Mocks
    Workflow --> Mocks
```

## Workflow sequence

```mermaid
sequenceDiagram
    actor Reviewer
    participant API as FastAPI
    participant Store as Data store (CSV)
    participant Worker as Run queue worker
    participant Agents as Agents (LangGraph)
    participant Model as LLM
    participant CRM as CRM / messaging (mock)

    Reviewer->>API: POST /renewals/scan
    API->>Store: Assess every policy, queue one run per lifecycle event
    API-->>Reviewer: 202 Accepted (batch id)
    Worker->>Store: Claim queued run, heartbeat
    Worker->>Agents: Run the graph for one policy
    Agents->>Agents: Renewal agent: triggers, allowed steps (rules)
    Agents->>Model: Retention agent: lapse risk + next step
    Agents->>Model: Recommendation agent: best extra cover (if several)
    Agents->>Model: Personalisation agent: draft message
    Agents->>Store: Workflow agent: guardrails, link, pending_approval
    Reviewer->>API: GET /recommendations, then approve / edit / reject
    API->>Store: Check role, version, expiry, re-check rules on today's data
    API->>CRM: Log the decision
    alt Approved with a message
        Worker->>CRM: Deliver message with portal link (once)
        Worker->>CRM: Log message_delivered
    end
```

## Runtime and boundaries

- **Entry point:** `main.py` builds the FastAPI app, installs CORS, loads the CSV data and starts the run-queue workers. Run it from the repository root with `uvicorn main:app`.
- **Agents:** `backend/agents/` has one folder per agent (`renewal`, `retention`, `recommendation`, `personalisation`, `workflow`) plus `shared/` (node wrapper, decision helpers, LLM-safe features). `graph.py` wires them; `state.py` is the state they pass along.
- **Decision safety:** Python rules decide what is allowed. Model output is validated and cannot overrule the rules. Approval is a separate human action, checked by role and recommendation version, and edits are validated again before commit.
- **Storage:** every table is a CSV file in `backend/data/` (`DATA_DIR`).
  - On start the files are loaded into memory.
  - After each unit of work, the changed tables are written back with an atomic file replace.
  - The app runs on one asyncio event loop, so a check-then-write with no `await` in between is atomic. This gives atomic run claims and first-decision-wins approvals without a database.
  - The store enforces unique rules: one active run per policy, one open recommendation per lifecycle event, one approval per recommendation.
- **External services:** the LLM provider is chosen by backend settings, and credentials stay server-side. CRM, policy administration, billing and messaging are integration protocols with mock implementations (`backend/integrations/`). The CRM mock writes `crm_activities.csv`.
- **Verification:** `backend/tests/` holds unit and integration tests. Run `python -m pytest` from the repository root.

## Deployment notes

The repository defines no hosting provider, container image or CI/CD workflow. A deployment needs to provide these:

- **One backend process:** the data folder is owned by a single process.
- **A persistent `DATA_DIR`:** the CSV files are the only storage.
- **`CORS_ORIGINS`:** must include the frontend origin.
- **LLM credentials:** set in the backend environment.

Moving to a multi-process deployment would mean replacing `backend/db/store.py` with a database-backed store behind the same repository functions.
