const CURRENCY = "AED";

/** Minor units (fils) -> "AED 1,234". */
export function money(minor: number | null | undefined, digits = 0): string {
  if (minor === null || minor === undefined) return "-";
  return `${CURRENCY} ${(minor / 100).toLocaleString("en-US", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })}`;
}

export function num(n: number | null | undefined): string {
  return n === null || n === undefined ? "-" : n.toLocaleString("en-US");
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "2026-11-05" -> "05 Nov 2026". */
export function day(iso: string | null | undefined): string {
  if (!iso) return "-";
  const [y, m, d] = iso.slice(0, 10).split("-");
  return `${d} ${MONTHS[Number(m) - 1]} ${y}`;
}

/** Timestamp -> "15 Oct 2026, 09:12". */
export function stamp(iso: string | null | undefined): string {
  if (!iso) return "-";
  const t = new Date(iso);
  const hh = String(t.getHours()).padStart(2, "0");
  const mm = String(t.getMinutes()).padStart(2, "0");
  return `${day(t.toISOString())}, ${hh}:${mm}`;
}

/** Days until a date in words: "in 12 days", "today", "8 days ago". */
export function inDays(days: number | null | undefined): string {
  if (days === null || days === undefined) return "";
  if (days === 0) return "today";
  if (days === 1) return "tomorrow";
  if (days > 0) return `in ${days} days`;
  return `${-days} day${days === -1 ? "" : "s"} ago`;
}

export function human(key: string | null | undefined): string {
  if (!key) return "";
  const s = key.replace(/_/g, " ");
  return s[0].toUpperCase() + s.slice(1);
}

export const LINE_NAME: Record<string, string> = {
  motor: "Car insurance",
  medical: "Medical insurance",
  home: "Home insurance",
  personal_accident: "Personal accident",
  life: "Life & protection",
  savings: "Savings & wealth",
  group: "Employee benefits",
};

export const CHANNEL_NAME: Record<string, string> = {
  email: "Email",
  sms: "SMS",
  email_sms: "SMS + Email",
  intermediary: "Broker / employer",
  internal: "Internal task",
};

export const ROLE_NAME: Record<string, string> = {
  retention: "Retention team",
  adviser: "Financial adviser",
  admin: "Administrator",
};

export function initials(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((p) => p[0]!.toUpperCase())
    .join("");
}

export const ACTION_NAME: Record<string, string> = {
  reminder: "Renewal reminder",
  payment_reminder: "Payment reminder",
  document_request: "Document request",
  plan_review: "Plan review",
  service_follow_up: "Service follow-up",
  retention_offer: "Retention offer",
  add_on_offer: "Extra cover offer",
  reinstatement: "Reinstatement",
  internal_task: "Internal task",
};

/** What each status means, in plain words (shown next to the badge). */
export const HEALTH_HELP: Record<string, string> = {
  on_track: "Nothing to do right now. Cover is in place and nothing is due soon.",
  due_soon: "A renewal, payment, review or document is coming up. The agents prepare a reminder.",
  at_risk: "Signs this customer may not renew, such as a big price rise, complaints or a failed payment.",
  overdue: "A payment is late, but the customer is still covered because they are inside the grace period.",
  lapsed: "Cover has stopped: the grace period ended without payment or renewal. The customer can be offered reinstatement.",
  renewed: "Already renewed for the next term.",
  cancelled: "The policy was cancelled.",
};
