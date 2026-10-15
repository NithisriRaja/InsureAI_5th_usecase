# Business Rules & Fixed Thresholds

**Insurance AI Agents POC (Use case 5: renewals, retention & personalised offers): how decisions are made**

Rulebook version `2026.10-poc.2`. All values are POC placeholders, not taken from a real regulator or carrier.

- Every number below lives in **`backend/rulebook.py`** (data only).
- The rule code in `backend/services/rules/` reads it and holds no thresholds of its own.
- Every recommendation stores the rulebook version and the rule IDs it relied on.

---

## 1. One book, two distribution models

The POC runs a single book of business that mixes two ways of selling and keeping insurance. The same engine handles both; the product's **line**, **lifecycle type** and **relationship owner** decide which steps, triggers and routes apply.

| | General insurance | Life, savings & employee benefits |
|---|---|---|
| Lines | Motor, Medical, Home, Personal accident | Life & protection, Savings & wealth, Employee benefits (group) |
| Who owns the customer | **Broker** or **direct** | **Adviser** (life, savings); **broker** or **employer** (group) |
| How cover stays in force | Fixed one-year term, renewed at **expiry** | **Premiums keep being paid**; periodic **reviews** and **milestones**; group schemes renew on the **scheme anniversary** |
| Retention trigger | Days to expiry, missing documents, payment issue | Missed premium, lapse-risk signal, review due, milestone |
| Outreach route | Broker-owned: task to the broker. Direct: approved message to the customer | Adviser approves, then message to the customer |
| Headline KPI | Renewal rate / lapse | Persistency / lapse |

---

## 2. Who decides what

| Layer | Decides | Can it be overridden? |
|---|---|---|
| **Hard rules** (rulebook + Python) | Lifecycle triggers, cover state, allowed actions, consent and channels, discount caps, add-on eligibility, routing, fairness | **Never**: not by the LLM, not by prompt text in customer data |
| **LLM** | Lapse-risk band, which allowed action and channel to pick, discount within the cap, which eligible add-on suits best, explanation, draft message | Only inside the options the rules allow. Output is validated; invalid output is rejected |
| **Human** | Every recommendation (approve / reject / edit) | Edits are re-checked by the same hard rules |

Order inside a run: **rules first → LLM only if rules allow → human always last.**

### 2.1 What the system never does (guardrails in code)
File: `services/guardrails.py`, checked on every recommendation before it is stored. A violation fails the run and writes a `guardrail.blocked` audit event.

| Never | How it is enforced |
|---|---|
| Bind, issue or renew cover | Not an action the agent can produce; it only prepares the renewal and sends the portal link |
| Price outside the approved cap | A discount is only allowed on a retention offer and never above the product cap |
| Message a customer without consent and approval | Every recommendation is created as `pending_approval`; messages are only queued after a human approves. `AUTO_SEND_MESSAGES = False` |
| Go around the broker / employer who owns the relationship | Broker- or employer-owned records can only get an `intermediary` task, never an email or SMS to the customer (`BROKER_DIRECT_CONTACT_ALLOWED = False`) |
| Market to a customer without marketing consent | Offers (retention discount, extra cover) need marketing consent plus a consented channel; service messages need only a consented channel |
| Write its own links | Portal links (renew / pay / upload / review) are added by code from `CUSTOMER_PORTAL_URL`, never written by the LLM |
| Use protected attributes | See section 7 |

---

## 2A. The agents: how many, what each does, how each processes

The work is done by **one LangGraph workflow with 5 agents** (`backend/agents/graph.py`), one folder per agent under `backend/agents/`.

- **3 agents call the LLM:** retention, recommendation (only when several add-ons qualify) and personalisation.
- **2 agents are rules and code only:** renewal and workflow.
- **Around the graph sit non-AI services:** the run queue, the lifecycle scan, approvals, and the integrations (CRM, policy admin, billing, messaging).

```
renewal → retention → recommendation → personalisation → workflow
   └ stop: nothing due ────────────────────────────────────→ workflow
```

| # | Agent (folder) | Approach it covers | Uses LLM? | Input | Output |
|---|---|---|---|---|---|
| 1 | **Renewal agent** (`renewal/`) | Watch every renewal | no | Policy, customer, product, payments, add-ons | Fired triggers, cover state, allowed actions, channels (preferred first), discount cap, eligible add-ons, next event |
| 2 | **Retention agent** (`retention/`) | Spot customers at risk | yes, `lapse_risk` | Signals + allowed options + channel preference | Risk-of-leaving band, chosen action, channel, discount, rationale; then queue and priority by code |
| 3 | **Recommendation agent** (`recommendation/`) | Suggest suitable cover | yes, `add_on_fit` (only when several add-ons qualify) | Eligible add-ons + signals | The extra-cover offer (code, name, why it suits) |
| 4 | **Personalisation agent** (`personalisation/`) | Send the right message | yes, `message_draft` | Facts for the chosen action only | Customer message, or a task note for the broker / employer |
| 5 | **Workflow agent** (`workflow/`) | Do the follow-up work | no | Everything above | Guardrail check, portal link, one `pending_approval` recommendation; after approval: delivery and CRM write-back |

### How each agent processes a case

**1. Renewal agent** (no LLM)
1. Loads the policy, customer, payments and the product's add-on products through the integration adapters.
2. Reads the lifecycle type and fires only the triggers that type allows (section 4.1):
   - expiry or scheme anniversary for fixed-term products
   - missed premium, lapse-risk signal, review and milestone for life and savings
   - missing documents for all products
3. Derives cover state (due / in grace / lapsed / skip) from dates and payments.
4. Builds the allowed actions, the allowed channels (broker-owned → `intermediary` only; the customer's preferred channel first), the discount cap (fixed-term only) and eligible add-ons.
5. Nothing fired → skip, no recommendation, 0 LLM calls.

**2. Retention agent** (LLM, then rules)
1. Sends the signals, fired triggers, the allowed options and the customer's preferred channel.
2. The LLM returns a risk-of-leaving band and picks **one** allowed action, its channel, and a discount (retention offer only, within the cap).
3. Every choice is re-validated with the same function a human edit goes through. A single-channel choice must follow the customer's preference when consent allows it. Anything outside the rules is repaired once, or the run fails.
4. Code sets priority (in grace / lapsed is always high) and the queue (section 4.6).

**3. Recommendation agent** (rules, then LLM if needed)
1. For **every** customer with at least one eligible add-on, picks the best-suited extra cover:
   - one eligible add-on → it is picked
   - several → the LLM picks the best fit, with reasons citing real signals, and the code is re-checked against the eligible list
2. The pick is stored as the cover suggestion (code, name, why it suits) and shown on the Additional Cover page and the customer page.
3. It becomes the customer message only when the retention agent chose an extra-cover conversation (`add_on_offer`). Otherwise the message deals with the more urgent matter, and the suggestion waits for an adviser.
4. Customers whose message was prepared before they had a pick can be re-run from the Additional Cover page ("Ask agents to suggest cover", `POST /overview/cover/suggest`).

**4. Personalisation agent** (LLM)
1. Internal task → no draft.
2. Otherwise builds the facts for **that action only** (for example, a payment reminder sees the amount overdue and the grace end date, never renewal pricing) and the sign-off for the owner.
3. The LLM writes a customer message (email / SMS) or a task note for the broker / employer (`intermediary`).
4. Checks:
   - length and subject rules
   - only the `{first_name}` placeholder
   - money copied exactly from the facts
   - only the approved percentages
   - "monthly" wording only for monthly products
   - no discount talk without a discount

   The real first name is filled in by code after the LLM.

**5. Workflow agent** (no LLM)
1. Works out "needs review" (low confidence, LLM flag).
2. **Guardrail check** (section 2.1); a violation fails the run and writes a `guardrail.blocked` audit event.
3. Adds the portal link for the action (section 4.9).
4. Stores one `pending_approval` recommendation with the rule IDs, triggers, signals, LLM decisions and the rulebook version. It supersedes any older pending one for the same lifecycle event.
5. After a human approves:
   - the delivery step (`workflow/delivery.py`) sends the message or broker task exactly once
   - every decision and every delivered message is written back to the CRM (`crm_activities.csv`)

### Services around the agents (no AI)

| Service | File | What it does |
|---|---|---|
| Run queue / runner | `services/runner.py` | Runs the graph in the background with retries, heartbeats and crash recovery; one active run per policy |
| Lifecycle scan | `services/intake.py`, `services/lifecycle.py` | Assesses every in-force policy, stores its next event and queues one run per fired event |
| Approvals | `services/approvals.py` | Role check, staleness re-check against today's data, rule re-check of edits, first-decision-wins, CRM write-back |
| Integrations | `integrations/` | Mock CRM (customers, activity log), policy admin (policies, products, documents received), billing (payments) |

### LLM calls per case

| Case | LLM calls |
|---|---|
| Policy with nothing due | 0 |
| Policy with an internal task (no consented channel) | 1 (retention) |
| Policy with a message or broker task | 2 (retention, personalisation) |
| Any case with several eligible add-ons | +1 (recommendation picks the best one) |

---

## 3. Product catalogue
Amounts in AED (stored internally in fils). `channels` = relationship owners allowed to sell the product. Discounts apply to retention offers on fixed-term products only.

| Code | Name | Line | Lifecycle | Pay | Age | Sum insured / amount | Base premium | Max disc. | Grace | Channels | Add-on |
|---|---|---|---|---|---|---|---|---|---|---|---|
| MOTOR_TPL | Motor Third-Party Liability | Motor | expiry_renewal | annual | 18–80 | 10k – 150k | 900 | 10% | 0 d | broker, direct | PA_INDIVIDUAL |
| MOTOR_COMPREHENSIVE | Motor Comprehensive | Motor | expiry_renewal | annual | 21–75 | 20k – 600k | 2,800 | 15% | 0 d | broker, direct | PA_INDIVIDUAL |
| MEDICAL_ESSENTIAL | Individual Medical Essential | Medical | expiry_renewal | annual | 18–65 | 150k – 1M | 4,500 | 10% | 30 d | broker, direct | PA_INDIVIDUAL |
| MEDICAL_FAMILY | Family Medical Plus | Medical | expiry_renewal | annual | 18–60 | 500k – 5M | 14,000 | 12% | 30 d | broker, direct | PA_INDIVIDUAL |
| HOME_CONTENTS | Home Contents | Home | expiry_renewal | annual | 18–85 | 50k – 750k | 600 | 10% | 15 d | broker, direct | — |
| HOME_BUILDINGS_CONTENTS | Home Buildings & Contents | Home | expiry_renewal | annual | 25–85 | 500k – 8M | 2,200 | 15% | 15 d | broker, direct | — |
| PA_INDIVIDUAL | Personal Accident Cover | Personal accident | expiry_renewal | annual | 18–70 | 100k – 2M | 350 | 10% | 15 d | broker, direct | — |
| LIFE_TERM | Term Life Protection | Life | premium_continuation | monthly | 18–60 | 250k – 10M | 1,500 | 0% | 30 d | adviser | LIFE_CRITICAL_ILLNESS |
| LIFE_CRITICAL_ILLNESS | Critical Illness Protection | Life | premium_continuation | monthly | 18–55 | 100k – 3M | 2,000 | 0% | 30 d | adviser | — |
| LIFE_WHOLE_OF_LIFE | Whole-of-Life Unit-Linked Plan | Life | premium_continuation | monthly | 18–65 | 500k – 20M | 12,000 | 0% | 30 d | adviser | LIFE_CRITICAL_ILLNESS |
| SAVINGS_EDUCATION | Education Savings Plan | Savings | milestone | monthly | 18–55 | 50k – 2M | 6,000 | 0% | 30 d | adviser | LIFE_TERM |
| SAVINGS_REGULAR | Regular Savings Plan | Savings | premium_continuation | monthly | 18–60 | 50k – 5M | 6,000 | 0% | 30 d | adviser | LIFE_TERM |
| SAVINGS_SINGLE_PREMIUM | Single-Premium Wealth Plan | Savings | scheduled_review | single | 18–75 | 100k – 20M | 100,000 (one-off) | 0% | — | adviser | — |
| GROUP_MEDICAL | Group Medical Scheme | Employee benefits | group_scheme_renewal | annual | n/a | 150k – 5M | 60,000 | 8% | 30 d | broker, employer | — |
| GROUP_LIFE | Group Life Scheme | Employee benefits | group_scheme_renewal | annual | n/a | 100k – 10M | 25,000 | 8% | 30 d | broker, employer | — |

Age limits are **inclusive** and decide which add-ons a customer may be offered. Life and savings products are **regulated**: extra-cover suggestions on them are advice and are approved by an adviser.

---

## 4. Renewal & retention: lifecycle rules

### 4.1 Lifecycle types and their triggers
File: `services/rules/renewal.py`, data in `rulebook.LIFECYCLES`. **A trigger can only fire for the lifecycle types listed against it.** Premium-based products never get an expiry trigger, even if their term end date falls inside a window.

| Lifecycle | Products | Triggers that may fire | Windows |
|---|---|---|---|
| `expiry_renewal` | Motor, medical, home, PA | upcoming expiry, missing document, payment overdue, lapse-risk signal | Notice points 45 / 30 / 14 / 7 days; documents chased from 30 days; reinstatement up to 60 days after expiry |
| `group_scheme_renewal` | Group medical, group life | scheme anniversary, missing document, payment overdue, lapse-risk signal | Notice points 90 / 60 / 30 days; documents from 60 days; reinstatement 60 days |
| `premium_continuation` | Term, critical illness, whole-of-life, regular savings | premium missed, lapse-risk signal, scheduled review, missing document | Review notice 30 days; reinstatement up to 90 days after the missed premium |
| `milestone` | Education savings | premium missed, lapse-risk signal, milestone, scheduled review, missing document | Milestone notice 60 days; review notice 30 days; reinstatement 90 days |
| `scheduled_review` | Single-premium wealth | scheduled review, missing document | Review notice 30 days |

**Lapse-risk signal** (placeholder): any failed payment, any complaint in the last 12 months, or (fixed-term only) a renewal premium up **15 %** or more.

The optional `RENEWAL_WINDOW_DAYS` setting / scan `window_days` overrides the 45-day window of one-year renewals only; group schemes keep their 90 days.

### 4.2 Cover state
Worked out from **dates and payments**, not the stored status (which can lag). Only *cancelled* and *renewed* are final.

| Lifecycle | Situation | State |
|---|---|---|
| Any | Cancelled / already renewed | Skip |
| Expiry | Ends more than the notice window away | Skip (out of window) |
| Expiry | Ends today or within the window | **Due** |
| Expiry | Ended, within the product's grace period | **In grace** |
| Expiry | Ended, past grace, within reinstatement lookback | **Lapsed** |
| Premium | Oldest missed premium within the grace period (30 d) | **In grace** |
| Premium | Past grace, within 90 days | **Lapsed** |
| Premium | No missed premium but a review / milestone / signal / document event | **Due** |
| Premium | No event | Skip (no trigger) |
| Any | Older than the reinstatement lookback | Skip |

Each run is tied to one **lifecycle event** (its cycle key, e.g. `upcoming_expiry:2026-11-12` or `premium_missed:2026-09-23`); re-running the same event replaces the pending recommendation.

### 4.3 Allowed actions
The LLM must pick from this list; it cannot invent an action.

| Action | Allowed when |
|---|---|
| **Internal task** | Direct / adviser-owned customer with **no consented contact channel**: the only option, no customer message |
| **Reinstatement** | State is lapsed (only option) |
| **Reminder** | Upcoming expiry / scheme anniversary fired |
| **Payment reminder** | Payment overdue / premium missed fired, or a failed payment |
| **Document request** | Missing document fired |
| **Plan review** | Scheduled review or milestone fired |
| **Service follow-up** | Lapse-risk signal fired |
| **Retention offer** | Fixed-term products only, and **all** of: marketing consent + channel; tenure ≥ 2 years; ≤ 1 claim in 3 years; no overdue or failed payments; product allows a discount |
| **Add-on offer** | State is due (cover not at risk), marketing consent + channel, tenure ≥ 1 year, no overdue or failed payments, an add-on in the product's list the customer does not hold and whose age band fits (`suitability.add_on`) |

### 4.4 Channels
| Owner | Service actions | Offers |
|---|---|---|
| Broker / employer | `intermediary` task only | `intermediary` task only |
| Direct / adviser | Consented email / SMS | Consented email / SMS **and** marketing consent |

The customer's **preferred channel** (`customers.csv: preferred_channel`) is listed first. The retention agent must use it whenever consent allows it for the action. `email_sms` (both at once) stays available for urgent cases.

### 4.5 Offer and edit checks
Applied to the LLM's choice **and** to any human edit:
- Discount must be **> 0** and **≤ the product's max discount**, and only on a retention offer.
- An add-on offer must name a suitable add-on.
- The action must be in the allowed list and the channel must be allowed for it (an internal task cannot contact the customer; a broker-owned policy cannot be switched to email).

### 4.6 Approval routing (approval matrix)
Data: `rulebook.APPROVAL_MATRIX`. The agents only **draft** (message or task); a human always decides.

| Action | Agent | Default queue | Adviser-owned relationship |
|---|---|---|---|
| Reminder, document request, service follow-up, retention offer, reinstatement, internal task | draft | Retention (service team) | Adviser |
| Payment reminder | draft | Retention | **Retention** (service team) |
| Plan review | draft | Adviser | Adviser |
| Add-on offer (regulated advice) | draft | Adviser (retention if the product is not regulated and the customer is not adviser-owned) | Adviser |

| Queue | Who may approve |
|---|---|
| Adviser | Adviser, Admin |
| Retention | Retention, Admin |

### 4.7 Priority and expiry
- Lapse-risk band sets priority: high → High, medium → Medium, low → Low. In grace or lapsed → always **High**.
- Expiry products: the recommendation expires at **end date + grace**. Premium in grace: **missed premium date + grace**. Lapsed: **14 days** after the scan. Reviews / milestones / documents: **event date (or today) + 14 days**.
- An expired recommendation cannot be approved.

### 4.8 Message drafts
Each draft sees only the facts its action needs (a payment reminder sees the amount overdue and grace end, never renewal pricing; a plan review sees the review / milestone date, never prices). Premiums are described with the product's own frequency (annual / monthly / single). Sign-off: direct → "Your insurance team", adviser-owned → "Your financial adviser", broker / employer task → "Insurer operations team". Add-on and plan-review drafts invite a conversation; they never give advice or quote a price.

### 4.9 Portal links, documents and CRM (workflow agent)
| Action | Link sent with the message |
|---|---|
| Reminder, retention offer | Renew online → `{CUSTOMER_PORTAL_URL}/renew/{policy number}` |
| Reinstatement | Restart your cover → `/renew/{policy number}` |
| Payment reminder | Pay online → `/pay/{policy number}` |
| Document request | Upload documents → `/documents/{policy number}` |
| Plan review, add-on offer | Book your review / talk to us → `/review/{policy number}` |
| Internal task | none |

- Links are added in code (never by the LLM) and recomputed when an approver edits the action.
- `POST /renewals/{policy}/documents` records documents received (retention, adviser or admin). It clears them from the policy, so the next scan stops chasing them, and logs the change on the CRM record.
- The CRM record (`GET /renewals/{policy}/crm`) gets one activity for each of these events:
  - a decision (`follow_up_approved` / `follow_up_rejected`)
  - a delivered message (`message_delivered`)
  - a document intake (`documents_received`)

---

## 6. How LLM decisions are constrained
- The LLM returns a **band** (high / medium / low), a **confidence** and **reasons**. Every reason must cite a real signal key; ungrounded reasons are rejected.
- A numeric score is kept for reference only.
- **Low confidence** or an LLM flag → **needs review**.
- Temperature 0. Invalid output (bad JSON, action / channel / discount / add-on outside the rules, ignored channel preference) → one repair attempt → otherwise the run **fails** (no guessing).

| Output | Check |
|---|---|
| Lapse risk | Band high / medium / low; score fits the band (high 0.6–1.0, medium 0.3–0.7, low 0.0–0.4); action, channel and discount must pass section 4.5; preferred channel used when allowed |
| Add-on fit | Code must be one of the eligible add-ons |
| Reasons | 1–5 per decision, each citing an existing signal; ≤ 300 characters |
| Draft message | Email / intermediary note ≤ 1,200 characters with a subject; SMS ≤ 320 characters, no subject; only `{first_name}`; only the approved discount and the actual premium change as percentages; money copied from the data; "monthly" wording only for monthly products; no `[REDACTED]` markers |

### Signals passed to the LLM
- **Renewals:** line, lifecycle type, relationship owner, payment frequency, fired triggers, grace days, overdue / failed payments, days premium overdue, days to expiry / review / milestone (as applicable), premium change % (fixed-term only), documents outstanding, tenure, claims, complaints, customer age band, sum insured, premium.
- Never: names, contact details, date of birth, city, intermediary names, protected attributes.

---

## 7. Fairness guardrail
Files: `backend/services/rules/fairness.py`, `backend/agents/shared/features.py`

| Control | Detail |
|---|---|
| Stored, never used | Gender, ethnicity/race, religion, marital status, nationality/citizenship, disability, sexual orientation, pregnancy are kept in a separate `protected` field for record only |
| Location excluded | City, postcode and address are not sent |
| Allow-list | The LLM only receives the signals listed in section 6 |
| Text redaction | `redact_text` replaces protected words in free text with `[REDACTED]` before use |
| Pre-call scan | The exact payload is checked before every LLM call (including product descriptions); anything protected → the call is **blocked** and the run fails as `fairness_violation` |
| Prompt injection | Customer text is wrapped as untrusted data |

Age bands: under 18, 18–24, 25–34, 35–44, 45–54, 55–64, 65–74, 75+.

---

## 8. Human approval rules
- Every recommendation waits in **pending approval**; nothing is sent automatically.
- **Approve** → queues the drafted message (customer channels) or the task note (`intermediary`, delivered to the owning broker / employer).
- **Reject** → reason required. **Edit** = approve with changes, re-checked by section 4.5; the original is kept in the audit trail.
- Only the first decision counts. If the data changed since the recommendation (paid, renewed, cancelled, lifecycle event moved), the approval is refused as **stale**.
- Role checks are for demo realism, not security (no passwords).

---

## 9. Operational limits (configurable in `.env`)
| Setting | Default | Meaning |
|---|---|---|
| `DATA_DIR` | `backend/data` | Folder with the CSV files (one per table) |
| `CURRENCY` | AED | Display currency in drafts and signals |
| `CUSTOMER_PORTAL_URL` | `https://portal.example.com` | Base of the renew / pay / upload / review links |
| `RENEWAL_WINDOW_DAYS` | empty | Optional override of the one-year renewal notice window (rulebook default 45) |
| `LLM_RPM` | 15 | Max LLM requests per minute |
| `LLM_MAX_CONCURRENCY` | 2 | Max LLM calls at the same time |
| `LLM_MAX_ATTEMPTS` | 5 | Retries for rate limits / server errors |
| `LLM_MAX_TOTAL_WAIT_S` | 120 | Give up after this much total waiting |
| `LLM_TIMEOUT_S` | 60 | Per-request timeout |
| `RUNNER_WORKERS` | 2 | Runs processed in parallel |
| `RUN_MAX_ATTEMPTS` | 3 | Times a crashed run is retried automatically |
| `RUN_STALE_AFTER_S` | 60 | A run with no heartbeat for this long is treated as crashed |
| `SESSION_IDLE_HOURS` | 12 | Reviewer session expires after this much inactivity |
| `AS_OF_DATE` | today | Freeze "today" for demos and tests |
