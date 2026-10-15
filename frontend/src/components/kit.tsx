"use client";

import type { ButtonHTMLAttributes, ReactNode } from "react";
import { useRouter } from "next/navigation";
import { AlertTriangle, CheckCircle2, CircleDot, Clock, Info, Loader2, XCircle } from "lucide-react";
import { initials } from "@/lib/format";

export function cx(...parts: (string | false | null | undefined)[]): string {
  return parts.filter(Boolean).join(" ");
}

// ------------------------------------------------------------------- layout ---

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle: string; actions?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="font-display text-2xl font-bold text-ink">{title}</h1>
        <p className="mt-1 text-sm text-muted-ink">{subtitle}</p>
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function Card({
  title,
  action,
  children,
  className,
  pad = true,
}: {
  title?: ReactNode;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
  pad?: boolean;
}) {
  return (
    <section className={cx("rounded-xl border border-rule bg-card shadow-card", className)}>
      {(title || action) && (
        <header className="flex items-center justify-between gap-3 px-5 pt-4">
          {title && <h2 className="font-display text-base font-bold text-ink">{title}</h2>}
          {action}
        </header>
      )}
      <div className={pad ? "p-5" : ""}>{children}</div>
    </section>
  );
}

// ------------------------------------------------------------------ buttons ---

type BtnProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "outline" | "ghost" | "danger";
  size?: "sm" | "md";
  busy?: boolean;
};

export function Button({ variant = "outline", size = "md", busy, className, children, disabled, ...rest }: BtnProps) {
  return (
    <button
      {...rest}
      disabled={disabled || busy}
      className={cx(
        "inline-flex items-center justify-center gap-1.5 rounded-lg font-semibold whitespace-nowrap transition-colors disabled:cursor-not-allowed disabled:opacity-50",
        size === "sm" ? "h-8 px-3 text-xs" : "h-9 px-4 text-sm",
        variant === "primary" && "bg-brand text-white hover:bg-brand-hover",
        variant === "outline" && "border border-rule bg-card text-ink hover:bg-ice",
        variant === "ghost" && "text-brand hover:bg-brand-soft",
        variant === "danger" && "border border-bad/30 bg-card text-bad hover:bg-bad-soft",
        className,
      )}
    >
      {busy && <Loader2 className="size-4 animate-spin" aria-hidden />}
      {children}
    </button>
  );
}

// ------------------------------------------------------------------- status ---

export type Tone = "ok" | "warn" | "bad" | "info" | "neutral" | "brand";

const TONE: Record<Tone, string> = {
  ok: "bg-ok-soft text-ok",
  warn: "bg-warn-soft text-warn",
  bad: "bg-bad-soft text-bad",
  info: "bg-info-soft text-info",
  neutral: "bg-ice-2 text-ink-2",
  brand: "bg-brand-soft text-brand",
};
const ICON: Record<Tone, typeof Info> = {
  ok: CheckCircle2,
  warn: Clock,
  bad: AlertTriangle,
  info: Info,
  neutral: CircleDot,
  brand: CircleDot,
};

/** A state pill: colour + icon + label, never colour alone. */
export function Badge({ tone = "neutral", children, icon = true }: { tone?: Tone; children: ReactNode; icon?: boolean }) {
  const Icon = ICON[tone];
  return (
    <span className={cx("inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-semibold whitespace-nowrap", TONE[tone])}>
      {icon && <Icon className="size-3" aria-hidden />}
      {children}
    </span>
  );
}

export const HEALTH_TONE: Record<string, Tone> = {
  on_track: "ok",
  due_soon: "warn",
  at_risk: "bad",
  overdue: "bad",
  lapsed: "bad",
  renewed: "info",
  cancelled: "neutral",
};

export const STATUS_TONE: Record<string, Tone> = {
  awaiting_approval: "warn",
  pending_approval: "warn",
  scheduled: "info",
  sent: "ok",
  delivered: "ok",
  approved: "ok",
  approved_with_edits: "ok",
  task_created: "brand",
  failed: "bad",
  rejected: "neutral",
  superseded: "neutral",
  expired: "neutral",
};

export function SeverityBadge({ severity }: { severity: "high" | "medium" | "low" }) {
  const tone: Tone = severity === "high" ? "bad" : severity === "medium" ? "warn" : "info";
  return <Badge tone={tone}>{severity[0].toUpperCase() + severity.slice(1)}</Badge>;
}

// --------------------------------------------------------------------- tiles ---

export function KpiTile({
  label,
  value,
  note,
  icon,
  tone = "brand",
}: {
  label: string;
  value: ReactNode;
  note?: ReactNode;
  icon: ReactNode;
  tone?: Tone;
}) {
  return (
    <div className="flex items-start justify-between gap-3 rounded-xl border border-rule bg-card p-5 shadow-card">
      <div className="min-w-0">
        <p className="text-sm font-medium text-muted-ink">{label}</p>
        <p className="mt-2 font-display text-3xl font-bold tracking-tight text-ink">{value}</p>
        {note && <p className="mt-1 text-xs text-muted-ink">{note}</p>}
      </div>
      <span className={cx("grid size-10 shrink-0 place-items-center rounded-lg", TONE[tone])}>{icon}</span>
    </div>
  );
}

// ------------------------------------------------------------------- people ---

export function Avatar({ name, size = "md" }: { name: string; size?: "sm" | "md" | "lg" }) {
  return (
    <span
      aria-hidden
      className={cx(
        "grid shrink-0 place-items-center rounded-full bg-brand-soft font-bold text-brand",
        size === "sm" && "size-8 text-xs",
        size === "md" && "size-10 text-sm",
        size === "lg" && "size-14 text-lg",
      )}
    >
      {initials(name)}
    </span>
  );
}

// -------------------------------------------------------------------- tables ---

export function Table({ head, children }: { head: ReactNode[]; children: ReactNode }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[640px] text-left text-sm">
        <thead>
          <tr className="border-b border-rule text-xs font-semibold tracking-wide text-muted-ink uppercase">
            {head.map((h, i) => (
              <th key={i} className="px-4 py-3 font-semibold">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-rule">{children}</tbody>
      </table>
    </div>
  );
}

/** A table row that opens ``href`` when clicked anywhere (or with Enter). */
export function RowLink({ href, children }: { href: string; children: ReactNode }) {
  const router = useRouter();
  return (
    <tr
      role="link"
      tabIndex={0}
      onClick={(e) => {
        if (!(e.target as HTMLElement).closest("a, button")) router.push(href);
      }}
      onKeyDown={(e) => {
        if (e.key === "Enter") router.push(href);
      }}
      className="cursor-pointer hover:bg-ice focus-visible:bg-ice"
    >
      {children}
    </tr>
  );
}

export function Td({ children, className }: { children: ReactNode; className?: string }) {
  return <td className={cx("px-4 py-3 align-middle text-ink-2", className)}>{children}</td>;
}

export function Tabs<T extends string>({
  value,
  onChange,
  options,
}: {
  value: T;
  onChange: (v: T) => void;
  options: { value: T; label: string; count?: number }[];
}) {
  return (
    <div role="tablist" className="flex flex-wrap gap-1.5">
      {options.map((o) => (
        <button
          key={o.value}
          role="tab"
          aria-selected={value === o.value}
          onClick={() => onChange(o.value)}
          className={cx(
            "inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-semibold transition-colors",
            value === o.value ? "bg-brand text-white" : "border border-rule bg-card text-ink-2 hover:bg-ice",
          )}
        >
          {o.label}
          {o.count !== undefined && (
            <span
              className={cx(
                "rounded-full px-1.5 text-xs",
                value === o.value ? "bg-white/20 text-white" : "bg-ice-2 text-muted-ink",
              )}
            >
              {o.count}
            </span>
          )}
        </button>
      ))}
    </div>
  );
}

export function Pagination({
  total,
  limit,
  offset,
  onChange,
}: {
  total: number;
  limit: number;
  offset: number;
  onChange: (offset: number) => void;
}) {
  const pages = Math.max(1, Math.ceil(total / limit));
  const page = Math.floor(offset / limit) + 1;
  const shown = Array.from({ length: pages }, (_, i) => i + 1).filter(
    (p) => p === 1 || p === pages || Math.abs(p - page) <= 2,
  );
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-3 text-sm text-muted-ink">
      <span>
        Showing {total ? offset + 1 : 0}-{Math.min(offset + limit, total)} of {total}
      </span>
      <div className="flex items-center gap-1">
        {shown.map((p, i) => (
          <span key={p} className="flex items-center gap-1">
            {i > 0 && shown[i - 1] !== p - 1 && <span className="px-1">…</span>}
            <button
              onClick={() => onChange((p - 1) * limit)}
              aria-current={p === page ? "page" : undefined}
              className={cx(
                "size-8 rounded-lg text-sm font-semibold",
                p === page ? "bg-brand text-white" : "text-ink-2 hover:bg-ice",
              )}
            >
              {p}
            </button>
          </span>
        ))}
      </div>
    </div>
  );
}

// -------------------------------------------------------------------- states ---

export function Loading({ label = "Loading" }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 p-6 text-sm text-muted-ink">
      <Loader2 className="size-4 animate-spin" aria-hidden /> {label}…
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="p-6 text-center text-sm text-muted-ink">{children}</div>;
}

export function ErrorNote({ error }: { error: unknown }) {
  return (
    <div role="alert" className="flex items-center gap-2 rounded-lg bg-bad-soft p-4 text-sm text-bad">
      <XCircle className="size-4" aria-hidden />
      {error instanceof Error ? error.message : String(error)}
    </div>
  );
}

export const inputCls =
  "h-9 w-full rounded-lg border border-rule-2 bg-card px-3 text-sm text-ink placeholder:text-faint focus:border-brand focus:outline-none";
