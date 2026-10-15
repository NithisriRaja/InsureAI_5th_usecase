# Product Requirements Document (PRD)

## Insurance AI Agents POC: Policy Renewals, Retention & Personalised Offers (Use Case 5)

| | |
|---|---|
| **Version** | 2.0 |
| **Date** | 15 October 2026 |
| **Status** | Locked for implementation |
| **Audience** | Internal team |

### Change log
| Version | Change |
|---|---|
| 1.1 | Initial locked backend PRD. |
| 1.2 | LLM structured output for decisions; async run queue; approve-with-changes; fairness guardrail; lightweight identity. |
| 2.0 | Scope narrowed to Use Case 5 only (acquisition / underwriting removed). Five named agents: renewal, retention, recommendation, personalisation, workflow. Storage moved from SQLite to CSV files in `backend/data/`. Renewal links, CRM write-back, customer channel preference and document intake added. Backend lives in `backend/`; Python environment from `requirements.txt` at the repository root. |

---

## 1. Overview
AI agents track every renewal, spot customers likely to leave, send the right message at the right time and suggest suitable extra cover.

Specialised agents collaborate in one LangGraph. Hard business rules run first, an LLM makes bounded decisions inside them, a human approves every follow-up, and every step is audited.

### The problem
- **Policies lapse.** Late reminders and manual follow-ups mean customers miss renewals.
- **Information is scattered.** Policy, premium, payment and customer details sit in different systems.
- **Messages feel generic.** Customers get the same standard reminder, whatever their situation.
- **Missed chances to offer more.** Insurers often miss suitable extra cover for existing customers.
- **Too much manual chasing.** Collecting documents, renewal follow-ups and status updates need staff again and again.

### Primary goals
- Prove that agents can collaborate safely and transparently on the renewal journey.
- Keep hard rules (deterministic) clearly separate from LLM judgements (probabilistic).
- Show full auditability of every recommendation, including every LLM request and response.
- Keep the implementation lightweight and local: one Python process, data in CSV files.

## 2. Agents and how they map to the approach

| Approach | Agent | What it does in the POC |
|---|---|---|
| Watch every renewal | **Renewal agent** | Loads policy, customer, product and payments through the integration adapters. The lifecycle rules then work out which triggers fired: upcoming expiry, scheme anniversary, overdue or missed premium, pending documents, scheduled review, milestone, or an early lapse signal. They also work out which next steps are allowed. No LLM. |
| Spot customers at risk | **Retention agent** | Rates the risk of not renewing (high / medium / low, with confidence and reasons citing real signals). It then picks one allowed next step, a channel (following the customer's preference where consent allows) and, for a retention offer, a discount within the cap. |
| Suggest suitable cover | **Recommendation agent** | When an extra-cover conversation is the right step, picks the add-on the customer is eligible for and that suits them best. The rules decide eligibility; the LLM chooses between several eligible options. |
| Send the right message | **Personalisation agent** | Drafts the message for that step from only the facts the step needs (no other policy data), in the agreed tone. A broker or employer that owns the relationship gets a task note instead of a customer message. |
| Do the follow-up work | **Workflow agent** | Stores the follow-up (reminder, document request, offer, review invitation) for human approval with the right portal link (renew / pay / upload documents / book a review). Once approved, it sends the message and writes the contact and decision back to the CRM through the integration adapter. |

### Lifecycle types (one mixed book of business)
- **General insurance** (motor, medical, home, personal accident): fixed one-year terms, renewed at expiry.
- **Employee benefits**: scheme-anniversary renewals through brokers or employers.
- **Life and savings**: adviser-led, kept in force by premiums, with scheduled reviews and milestones.

Premium-based products never get expiry triggers.

## 3. Technology stack (locked)

| Layer | Technology | Notes |
|---|---|---|
| Runtime | Python 3.12, `.venv` + `requirements.txt` at the repo root | Local development in VS Code |
| API | FastAPI | Lightweight identity only (no passwords) |
| Agent orchestration | LangGraph | One graph, explicit routing, no checkpointer |
| Hard business rules | Pure Python over data tables (`rulebook.py`) | Lifecycle, consent, offer caps, suitability, routing, fairness |
| LLM | Domo AI or Anthropic, selected by `LLM_PROVIDER` | Structured output, validated, one repair attempt |
| Storage | CSV files in `backend/data/` (one per table) | Loaded into memory on start, written back after each change |
| Execution | In-process run queue + async workers | Every trigger is asynchronous |
| Integrations | Mock CRM, policy admin, billing, messaging | Protocols ready for real adapters |
| Observability | structlog | Agent steps, LLM calls, approvals, correlated by run id |

## 4. Architecture
```
FastAPI (backend/api)
  ├── Routes: health, sessions, renewals, runs, recommendations, approvals, audit, messages,
  │           dashboard, kpi
  ├── Run queue + async workers (rate-limited LLM access)        backend/services/runner.py
  ├── Agents (LangGraph)                                          backend/agents/
  │     renewal -> retention -> recommendation -> personalisation -> workflow
  ├── Services: rules/, llm/, approvals, lifecycle, intake, justification, guardrails
  ├── Integrations (mocks): CRM, policy admin, billing, messaging backend/integrations/
  └── Data store: CSV files                                       backend/data/*.csv
```

## 5. Execution model
- Every trigger (renewal scan, single-policy run) returns `202 Accepted` with a run or batch id.
- Runs move through `queued → running → succeeded | failed | skipped` and are claimed atomically by in-process workers.
- A global rate limiter and concurrency cap protect LLM quotas.
- Crash recovery: stale `running` runs are requeued or failed on start.
- Clients poll `GET /runs/{id}` / `GET /batches/{id}`.

## 6. Human-in-the-loop (locked)
- The graph runs to completion and stores a recommendation with status `pending_approval`.
- `POST /approvals/{id}/approve`, `/reject` (reason required), `/edit` (approve with changes; edited fields are re-checked by the rules).
- Only the first decision wins (version check); others get `409`. Stale or expired recommendations are refused.
- Exactly one outbox message per recommendation; nothing is sent before approval.
- The acting user comes from the server-side session, never from the request body.

## 7. Decision layer

### Hard rules (never overridden by the LLM)
Lifecycle state and triggers, allowed next steps, consent per purpose (service vs marketing), channel availability, discount cap, add-on suitability, approval routing, never bypassing the broker or employer, and fairness.

### LLM decisions
- Lapse-risk band, next step, channel, discount (retention agent).
- Best-suited extra cover among eligible add-ons (recommendation agent).
- Message draft (personalisation agent).

Design rules:
- Python computes measurable signals; the LLM only sees an allow-listed feature set.
- Every reason must cite an existing signal key; output is validated (schema, enums, ranges, allowed codes, channel preference); one repair attempt, then the run fails.
- Low confidence forces `needs_review`. Temperature 0.
- If the LLM is unavailable after retries, the run fails (no silent fallback) and can be retried.

### Fairness guardrail
Protected attributes are never sent to the LLM or used by the rules. Each outbound payload is scanned before the call, and every recommendation records the check.

## 8. Identity (lightweight, not security)
Users pick a name and role (`retention`, `adviser`, `admin`). Each queue accepts its own role plus admin. Sessions survive reloads and restarts.

## 9. Functional requirements
- Scan every in-force policy and queue one run per lifecycle event.
- Produce transparent recommendations: band, confidence, grounded reasons, rule results, next step, offer, draft, portal link.
- Approve / reject / edit, with full audit trail.
- Record documents received (`POST /renewals/{id}/documents`) so the agents stop chasing them.
- Write contacts and decisions back to the CRM; show them per policy (`GET /renewals/{id}/crm`).
- Seed synthetic data: **small** (18 handcrafted edge-case policies) and **full** (80 policies).

## 10. Non-functional requirements
- Runs locally: `pip install -r requirements.txt`, then `uvicorn main:app`.
- Zero infrastructure beyond the chosen LLM provider; data in plain CSV files.
- Structured logging of every agent and decision step.
- Easy to reset and re-seed (`backend.scripts.reset_db`, `backend.scripts.seed_data`).

## 11. Out of scope
New-business acquisition and underwriting; real authentication; LangGraph interrupt/resume; model training; event streaming; production security and monitoring; real CRM / policy admin / billing / messaging integrations; localisation beyond English.

## 12. Success criteria
1. A renewal scan runs the five agents end to end through the API.
2. Hard rules + LLM decisions produce transparent, auditable recommendations.
3. A human can approve / reject / edit any recommendation; concurrent decisions are handled safely.
4. Approved messages carry the right portal link and are logged on the CRM record.
5. No protected attribute reaches the LLM.
6. Synthetic data covers every lifecycle type and edge case.

## 13. Key design decisions
| Decision | Choice | Rationale |
|---|---|---|
| Scope | Use case 5 only | Focus the POC on renewals and retention |
| Agents | Five agents matching the approach | Each responsibility is visible and testable |
| Decision model | LLM structured output, validated | Typed, provider-agnostic, auditable |
| LLM failure | Retry, then fail the run | Honest behaviour; no silent substitution |
| Scores | Bands + confidence + grounded reasons | LLM numbers are not calibrated probabilities |
| Links | Added in code, never by the LLM | Always the approved URL |
| Storage | CSV files, in-memory while running | Zero-ops; data readable and editable in Excel |
| Concurrency | Single asyncio process; atomic check-then-set | First-decision-wins and atomic claims without a database |
| HITL | Approve / reject / edit API | Simple, long-running human decisions |
