# Product lines and products

The insurance products this POC knows about, grouped by product line. There are **7 product lines** and **15 products**. Amounts are in AED.

Source of truth: `rulebook.LINES` (product lines) and `rulebook.PRODUCTS` (the catalogue) in `backend/`, loaded into `backend/data/products.csv` by the seed script. If those change, regenerate this page.

## At a glance

| Product line | Type | Sold through | Products |
|---|---|---|---|
| [Motor](#motor) | General insurance | broker, direct | Motor Third-Party Liability, Motor Comprehensive |
| [Medical](#medical) | General insurance | broker, direct | Individual Medical Essential, Family Medical Plus |
| [Home](#home) | General insurance | broker, direct | Home Contents, Home Buildings & Contents |
| [Personal accident](#personal-accident) | General insurance | broker, direct | Personal Accident Cover |
| [Life & protection](#life--protection) | Life & wealth (regulated advice) | adviser | Term Life Protection, Critical Illness Protection, Whole-of-Life Unit-Linked Plan |
| [Savings & wealth](#savings--wealth) | Life & wealth (regulated advice) | adviser | Education Savings Plan, Regular Savings Plan, Single-Premium Wealth Plan |
| [Employee benefits](#employee-benefits) | Employee benefits | broker, employer | Group Medical Scheme, Group Life Scheme |

## Motor

- **Type:** General insurance
- **Sold through:** broker, direct

| Product | Tier | What it covers | Ages | Sum insured | Base premium |
|---|---|---|---|---|---|
| **Motor Third-Party Liability** (`MOTOR_TPL`) | basic | Legal liability to third parties for injury and property damage. | 18–80 | AED 10,000 – AED 150,000 | AED 900 | 10% |
| **Motor Comprehensive** (`MOTOR_COMPREHENSIVE`) | premium | Own damage, theft, fire and third-party cover with agency repair option. | 21–75 | AED 20,000 – AED 600,000 | AED 2,800 |

| Product | Stays in force by | Premiums | Grace days | Regulated advice | Extra cover offered |
|---|---|---|---|---|---|
| Motor Third-Party Liability | Yearly renewal | annual | 0 | No | Personal Accident Cover |
| Motor Comprehensive | Yearly renewal | annual | 0 | No | Personal Accident Cover |

## Medical

- **Type:** General insurance
- **Sold through:** broker, direct

| Product | Tier | What it covers | Ages | Sum insured | Base premium |
|---|---|---|---|---|---|
| **Individual Medical Essential** (`MEDICAL_ESSENTIAL`) | basic | In-patient and essential out-patient cover within a local network. | 18–65 | AED 150,000 – AED 1,000,000 | AED 4,500 | 10% |
| **Family Medical Plus** (`MEDICAL_FAMILY`) | premium | Family cover with a wider network, out-patient and dental benefits. | 18–60 | AED 500,000 – AED 5,000,000 | AED 14,000 |

| Product | Stays in force by | Premiums | Grace days | Regulated advice | Extra cover offered |
|---|---|---|---|---|---|
| Individual Medical Essential | Yearly renewal | annual | 30 | No | Personal Accident Cover |
| Family Medical Plus | Yearly renewal | annual | 30 | No | Personal Accident Cover |

## Home

- **Type:** General insurance
- **Sold through:** broker, direct

| Product | Tier | What it covers | Ages | Sum insured | Base premium |
|---|---|---|---|---|---|
| **Home Contents** (`HOME_CONTENTS`) | basic | Contents and personal belongings for tenants and owners. | 18–85 | AED 50,000 – AED 750,000 | AED 600 | 10% |
| **Home Buildings & Contents** (`HOME_BUILDINGS_CONTENTS`) | premium | Buildings and contents with accidental damage for owner-occupiers. | 25–85 | AED 500,000 – AED 8,000,000 | AED 2,200 |

| Product | Stays in force by | Premiums | Grace days | Regulated advice | Extra cover offered |
|---|---|---|---|---|---|
| Home Contents | Yearly renewal | annual | 15 | No | — |
| Home Buildings & Contents | Yearly renewal | annual | 15 | No | — |

## Personal accident

- **Type:** General insurance
- **Sold through:** broker, direct

| Product | Tier | What it covers | Ages | Sum insured | Base premium |
|---|---|---|---|---|---|
| **Personal Accident Cover** (`PA_INDIVIDUAL`) | standard | Lump sum for accidental death or disability, worldwide, 24/7. | 18–70 | AED 100,000 – AED 2,000,000 | AED 350 | 10% |

| Product | Stays in force by | Premiums | Grace days | Regulated advice | Extra cover offered |
|---|---|---|---|---|---|
| Personal Accident Cover | Yearly renewal | annual | 15 | No | — |

## Life & protection

- **Type:** Life & wealth (regulated advice)
- **Sold through:** adviser

| Product | Tier | What it covers | Ages | Sum insured | Base premium |
|---|---|---|---|---|---|
| **Term Life Protection** (`LIFE_TERM`) | standard | Level cover for a fixed term; pays a lump sum on death or terminal illness. | 18–60 | AED 250,000 – AED 10,000,000 | AED 1,500 | 0% |
| **Critical Illness Protection** (`LIFE_CRITICAL_ILLNESS`) | standard | Lump sum on diagnosis of a listed critical illness. | 18–55 | AED 100,000 – AED 3,000,000 | AED 2,000 | 0% |
| **Whole-of-Life Unit-Linked Plan** (`LIFE_WHOLE_OF_LIFE`) | premium | Lifelong cover with an investment component linked to a fund range. | 18–65 | AED 500,000 – AED 20,000,000 | AED 12,000 |

| Product | Stays in force by | Premiums | Grace days | Regulated advice | Extra cover offered |
|---|---|---|---|---|---|
| Term Life Protection | Ongoing premiums | monthly | 30 | Yes | Critical Illness Protection |
| Critical Illness Protection | Ongoing premiums | monthly | 30 | Yes | — |
| Whole-of-Life Unit-Linked Plan | Ongoing premiums | monthly | 30 | Yes | Critical Illness Protection |

## Savings & wealth

- **Type:** Life & wealth (regulated advice)
- **Sold through:** adviser

| Product | Tier | What it covers | Ages | Sum insured | Base premium |
|---|---|---|---|---|---|
| **Education Savings Plan** (`SAVINGS_EDUCATION`) | standard | Regular savings towards a child's education with life cover built in. | 18–55 | AED 50,000 – AED 2,000,000 | AED 6,000 | 0% |
| **Regular Savings Plan** (`SAVINGS_REGULAR`) | standard | Flexible monthly savings into a choice of funds. | 18–60 | AED 50,000 – AED 5,000,000 | AED 6,000 | 0% |
| **Single-Premium Wealth Plan** (`SAVINGS_SINGLE_PREMIUM`) | premium | One-off investment into a managed fund range with a death benefit. | 18–75 | AED 100,000 – AED 20,000,000 | AED 100,000 |

| Product | Stays in force by | Premiums | Grace days | Regulated advice | Extra cover offered |
|---|---|---|---|---|---|
| Education Savings Plan | Premiums + milestone | monthly | 30 | Yes | Term Life Protection |
| Regular Savings Plan | Ongoing premiums | monthly | 30 | Yes | Term Life Protection |
| Single-Premium Wealth Plan | Periodic review | single | 0 | Yes | — |

## Employee benefits

- **Type:** Employee benefits
- **Sold through:** broker, employer

| Product | Tier | What it covers | Ages | Sum insured | Base premium |
|---|---|---|---|---|---|
| **Group Medical Scheme** (`GROUP_MEDICAL`) | standard | Employer medical scheme for staff and dependants. | n/a (company applicant) | AED 150,000 – AED 5,000,000 | AED 60,000 | 8% |
| **Group Life Scheme** (`GROUP_LIFE`) | standard | Employer-paid death-in-service cover as a multiple of salary. | n/a (company applicant) | AED 100,000 – AED 10,000,000 | AED 25,000 | 8% |

| Product | Stays in force by | Premiums | Grace days | Regulated advice | Extra cover offered |
|---|---|---|---|---|---|
| Group Medical Scheme | Scheme anniversary | annual | 30 | No | — |
| Group Life Scheme | Scheme anniversary | annual | 30 | No | — |

## How the agents use this

- **Renewal agent:** each product's lifecycle sets when a policy needs attention: expiry, scheme anniversary, missed premium, review or milestone. Grace days decide when cover is in grace or has lapsed.
- **Retention agent:** max discount caps any retention offer, which applies to fixed-term products only.
- **Recommendation agent:** the extra cover listed is what may be suggested as an add-on. The customer must be inside its age band and must not hold it already.
- **Who approves:** the product line decides the relationship owner. Life and savings always go to an adviser; employee benefits to a broker or employer. Suggestions on regulated products are advice and are approved by an adviser.

See [business_rules.md](business_rules.md) for the full rules and limits.

