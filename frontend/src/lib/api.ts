import { sessionStore } from "./session-store";

// ---------------------------------------------------------------- identity ---
export type Role = "retention" | "adviser" | "admin";
export type UserOut = { id: string; name: string; role: string };
export type SessionOut = { session_id: string; user: UserOut; expires_at: string };

// ---------------------------------------------------------------- overview ---
export type HealthKey = "on_track" | "due_soon" | "at_risk" | "overdue" | "lapsed" | "renewed" | "cancelled";

export type PolicyView = {
  policy_id: string;
  policy_number: string;
  customer_id: string;
  customer_name: string;
  product_name: string;
  line: string;
  lifecycle_type: string;
  channel_owner: string;
  due_date: string | null;
  days_to_due: number | null;
  premium: number;
  health: HealthKey;
  health_label: string;
  at_risk: boolean;
  risk_score: number | null;
  risk_band?: string | null;
  issue: string | null;
  rec_id: string | null;
  rec_status: string | null;
  suggested_action: string | null;
};

export type Slice = { key: string; label: string; count: number };

export type DashboardOut = {
  as_of: string;
  kpis: {
    total_policies: number;
    in_force: number;
    due_for_renewal: number;
    at_risk: number;
    renewal_rate_pct: number | null;
  };
  trend: { month: string; label: string; due: number; premium: number }[];
  status: Slice[];
  alerts: {
    policy_id: string;
    customer_name: string;
    issue: string;
    severity: "high" | "medium" | "low";
    due_date: string | null;
    rec_id: string | null;
  }[];
};

export type PolicyPage = {
  items: PolicyView[];
  total: number;
  limit: number;
  offset: number;
  counts: Record<string, number>;
};

export type RetentionOut = {
  at_risk: number;
  total: number;
  pct_of_total: number;
  bands: Slice[];
  by_line: Slice[];
  indicators: { key: string; label: string; count: number; pct: number }[];
  customers: PolicyView[];
};

export type CoverItem = {
  code: string;
  name: string;
  description: string;
  line: string;
  premium: number;
  recommended: boolean;
  rationale: string | null;
};
export type CoverOut = {
  policy: PolicyView;
  email: string | null;
  phone: string | null;
  current: CoverItem[];
  eligible: CoverItem[];
  not_eligible_reason: string | null;
  rec_id: string | null;
};

export type WorkflowItem = {
  rec_id: string;
  policy_id: string;
  policy_number: string;
  customer_name: string;
  workflow: string;
  action: string;
  channel: string;
  status: string;
  status_label: string;
  next_step: string;
  link: { label: string; url: string } | null;
  updated_at: string;
};
export type WorkflowOut = { steps: Slice[]; items: WorkflowItem[]; total: number };

export type AgentStep = {
  agent: string;
  title: string;
  status: "completed" | "skipped" | "failed" | "waiting";
  at: string | null;
  summary: string;
  uses_ai: boolean;
};
export type AgentTrace = {
  rec_id: string;
  policy_id: string;
  policy_number: string;
  customer_name: string;
  action: string;
  steps: AgentStep[];
  data_sources: { name: string; detail: string }[];
  rules_models: { name: string; detail: string }[];
  outcome: string;
  why: string;
};
// ------------------------------------------------------- recommendations ---
export type RecOut = {
  id: string;
  run_id: string;
  subject_id: string;
  cycle_key: string;
  status: string;
  version: number;
  queue: string;
  priority: string;
  action: string;
  channel_owner: string | null;
  lifecycle_type: string | null;
  band: string | null;
  confidence: string | null;
  needs_review: boolean;
  review_reasons: string[];
  explanation: string | null;
  channel: string | null;
  offer: Record<string, unknown> | null;
  cover_suggestion?: { code: string; name: string; rationale: string } | null;
  link: { label: string; url: string } | null;
  expires_at: string | null;
  created_at: string;
  decided_at: string | null;
  subject_name: string | null;
  line: string | null;
};
export type RuleResult = { id: string; passed: boolean; severity: string; reason: string };
export type RecDetail = RecOut & {
  triggers: { type: string; detail: string }[];
  signals: Record<string, unknown>;
  decisions: Record<string, Record<string, unknown>>;
  rule_results: RuleResult[];
  draft_subject: string | null;
  draft_message: string | null;
  fairness: { passed?: boolean };
  subject: Record<string, unknown>;
  approval: { decision: string; actor: string; reason: string | null; at: string } | null;
  message: { id: string; channel: string; status: string; recipient: string | null } | null;
  justification: { headline?: string; why?: string };
};

export type PolicyDetail = {
  policy_id: string;
  policy_number: string;
  customer_id: string;
  customer_name: string;
  product_name: string;
  line: string;
  lifecycle_type: string;
  payment_frequency: string;
  channel_owner: string;
  intermediary: string | null;
  status: string;
  state: string;
  triggers: string[];
  start_date: string;
  end_date: string;
  next_event_date: string | null;
  premium: number;
  prev_premium: number;
  premium_change_pct: number;
  sum_insured: number;
  tenure_years: number;
  claims_count_3y: number;
  service_complaints_12m: number;
  auto_renew: boolean;
  overdue_payments: number;
  docs_outstanding: string[];
  email: string | null;
  phone: string | null;
  city: string | null;
  consent_marketing: boolean;
  consent_email: boolean;
  consent_sms: boolean;
  preferred_channel: string | null;
  review_due_date: string | null;
  milestone_date: string | null;
  milestone_label: string | null;
  add_ons_held: string[];
  trigger_details: { type: string; detail: string; date: string | null }[];
  allowed_actions: string[];
  payments: { due_date: string; amount: number; status: string; paid_at: string | null }[];
  latest_run: { id: string; status: string; error_code: string | null } | null;
};

export type CrmActivity = {
  id: string;
  kind: string;
  channel: string | null;
  summary: string;
  actor: string;
  recommendation_id: string | null;
  created_at: string;
};

export type Page<T> = { items: T[]; total: number; limit: number; offset: number };
export type BatchOut = { id: string; total: number; done: boolean; counts: Record<string, number>; run_ids: string[] };
export type Health = {
  status: string;
  as_of: string;
  data: { location: string; policies: number };
  llm: { provider: string; model: string; key_configured: boolean };
};

// ------------------------------------------------------------------ client ---
export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public details?: unknown,
  ) {
    super(message);
  }
}

type Query = Record<string, string | number | boolean | null | undefined>;

export async function api<T>(
  path: string,
  opts: { method?: string; body?: unknown; query?: Query } = {},
): Promise<T> {
  const url = new URL(path, API_URL);
  for (const [k, v] of Object.entries(opts.query ?? {})) {
    if (v !== undefined && v !== null && v !== "") url.searchParams.set(k, String(v));
  }
  const headers: Record<string, string> = {};
  const token = sessionStore.get();
  if (token) headers["X-Session-Id"] = token;
  if (opts.body !== undefined) headers["Content-Type"] = "application/json";

  let res: Response;
  try {
    res = await fetch(url, {
      method: opts.method ?? "GET",
      headers,
      body: opts.body === undefined ? undefined : JSON.stringify(opts.body),
    });
  } catch {
    throw new ApiError(0, "network", `API not reachable at ${API_URL}`);
  }
  if (res.status === 204) return undefined as T;
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    const e = data?.error ?? {};
    if (res.status === 401) sessionStore.set(null);
    throw new ApiError(res.status, e.code ?? "http_error", e.message ?? res.statusText, e.details);
  }
  return data as T;
}

export function errorText(e: unknown): string {
  if (e instanceof ApiError) return e.message;
  return e instanceof Error ? e.message : String(e);
}
