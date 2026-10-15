"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useState, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  BadgePlus,
  Bot,
  CheckCircle2,
  CircleDashed,
  FileText,
  History,
  Info,
  MessageSquareText,
  Play,
  ShieldAlert,
  Sparkles,
  Wallet,
} from "lucide-react";
import {
  api,
  errorText,
  type AgentTrace,
  type CoverOut,
  type CrmActivity,
  type PolicyDetail,
  type RecDetail,
} from "@/lib/api";
import { ACTION_NAME, CHANNEL_NAME, day, HEALTH_HELP, human, money, stamp } from "@/lib/format";
import { Badge, Button, Card, cx, ErrorNote, HEALTH_TONE, Loading, type Tone } from "@/components/kit";
import { CustomerHeader } from "@/components/customer-header";
import { MessageReview } from "@/components/message-review";
import { useToast } from "@/components/toast";

const PAYMENT_TONE: Record<string, Tone> = { paid: "ok", due: "info", overdue: "bad", failed: "bad" };
const CRM_TEXT: Record<string, string> = {
  follow_up_approved: "Follow-up approved",
  follow_up_rejected: "Follow-up rejected",
  message_delivered: "Message delivered",
  documents_received: "Documents received",
};

function Section({ id, icon, title, children, action }: { id: string; icon: ReactNode; title: string; children: ReactNode; action?: ReactNode }) {
  return (
    <section id={id} className="scroll-mt-20 rounded-xl border border-rule bg-card p-5 shadow-card">
      <header className="mb-4 flex items-center justify-between gap-3">
        <h2 className="flex items-center gap-2 font-display text-base font-bold text-ink">
          <span className="text-brand">{icon}</span>
          {title}
        </h2>
        {action}
      </header>
      {children}
    </section>
  );
}

function Facts({ rows }: { rows: [string, ReactNode][] }) {
  return (
    <dl className="divide-y divide-rule text-sm">
      {rows.map(([k, v]) => (
        <div key={k} className="flex justify-between gap-3 py-2">
          <dt className="text-muted-ink">{k}</dt>
          <dd className="text-right font-semibold text-ink">{v}</dd>
        </div>
      ))}
    </dl>
  );
}

function RunAgents({ policyId }: { policyId: string }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [runId, setRunId] = useState<string | null>(null);
  useQuery({
    queryKey: ["run", runId],
    queryFn: async () => {
      const r = await api<{ status: string; error_message: string | null }>(`/runs/${runId}`);
      if (["succeeded", "failed", "skipped"].includes(r.status)) {
        setRunId(null);
        qc.invalidateQueries();
        if (r.status === "failed") toast(`The agents could not finish: ${r.error_message ?? "error"}`, "error");
        else toast("The agents finished for this customer.", "success");
      }
      return r;
    },
    enabled: !!runId,
    refetchInterval: 1000,
  });
  const run = useMutation({
    mutationFn: () => api<{ id: string }>(`/renewals/${policyId}/runs`, { method: "POST" }),
    onSuccess: (r) => setRunId(r.id),
    onError: (e) => toast(errorText(e), "error"),
  });
  return (
    <Button variant="primary" busy={run.isPending || !!runId} onClick={() => run.mutate()}>
      <Play className="size-4" aria-hidden /> {runId ? "Agents working…" : "Ask the agents to prepare a follow-up"}
    </Button>
  );
}

export default function CustomerPage() {
  const { id } = useParams<{ id: string }>();
  const qc = useQueryClient();
  const toast = useToast();
  const detail = useQuery({ queryKey: ["policy", id], queryFn: () => api<PolicyDetail>(`/renewals/${id}`) });
  const view = useQuery({ queryKey: ["overview", "cover", id], queryFn: () => api<CoverOut>(`/overview/cover/${id}`) });
  const recId = view.data?.rec_id ?? null;
  const rec = useQuery({ queryKey: ["rec", recId], queryFn: () => api<RecDetail>(`/recommendations/${recId}`), enabled: !!recId });
  const trace = useQuery({
    queryKey: ["overview", "agents", recId],
    queryFn: () => api<AgentTrace>(`/overview/agents/${recId}`),
    enabled: !!recId,
  });
  const crm = useQuery({ queryKey: ["crm", id], queryFn: () => api<CrmActivity[]>(`/renewals/${id}/crm`) });
  const received = useMutation({
    mutationFn: (doc: string) => api(`/renewals/${id}/documents`, { method: "POST", body: { received: [doc] } }),
    onSuccess: () => {
      toast("Document recorded. The agents will stop chasing it.", "success");
      qc.invalidateQueries();
    },
    onError: (e) => toast(errorText(e), "error"),
  });

  const err = detail.error ?? view.error;
  if (err) return <ErrorNote error={err} />;
  const p = detail.data;
  const v = view.data;
  if (!p || !v) return <Loading />;
  const pv = v.policy;
  const r = rec.data;
  const lr = r?.decisions?.lapse_risk as { band?: string; reasons?: { explanation: string }[] } | undefined;

  return (
    <>
      <Link href="/renewals" className="mb-4 inline-flex items-center gap-1.5 text-sm font-semibold text-brand hover:underline">
        <ArrowLeft className="size-4" aria-hidden /> Back to all policies
      </Link>

      <Card className="mb-5">
        <CustomerHeader
          name={p.customer_name}
          line={p.line}
          policyNumber={p.policy_number}
          email={p.email}
          phone={p.phone}
          daysToDue={pv.days_to_due}
          dueTone={HEALTH_TONE[pv.health]}
        />
        <nav aria-label="On this page" className="mt-4 flex flex-wrap gap-1.5 border-t border-rule pt-4 text-sm">
          {[
            ["#summary", "What's happening"],
            ["#message", "Message"],
            ["#cover", "Extra cover"],
            ["#history", "History"],
            ["#ai", "How the AI decided"],
            ["#policy", "Policy & payments"],
          ].map(([href, label]) => (
            <a key={href} href={href} className="rounded-lg bg-ice px-3 py-1.5 font-semibold text-ink-2 hover:bg-brand-soft hover:text-brand">
              {label}
            </a>
          ))}
        </nav>
      </Card>

      <div className="grid gap-5 xl:grid-cols-[1fr_360px]">
        <div className="space-y-5">
          <Section id="summary" icon={<Info className="size-4.5" />} title="What's happening with this customer">
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone={HEALTH_TONE[pv.health]}>{pv.health_label}</Badge>
              {pv.at_risk && pv.health !== "at_risk" && <Badge tone="bad">At risk of leaving</Badge>}
            </div>
            <p className="mt-2 text-sm text-ink-2">{HEALTH_HELP[pv.health]}</p>
            {p.trigger_details.length > 0 && (
              <ul className="mt-4 space-y-1.5 text-sm">
                {p.trigger_details.map((t, i) => (
                  <li key={i} className="flex gap-2 text-ink">
                    <span className="mt-1.5 size-1.5 shrink-0 rounded-full bg-brand" />
                    <span>
                      <b>{human(t.type)}:</b> {t.detail}
                    </span>
                  </li>
                ))}
              </ul>
            )}
            <div className="mt-4 grid gap-3 sm:grid-cols-2">
              <div className="rounded-lg bg-ice p-3">
                <p className="text-xs text-muted-ink">Risk of not renewing</p>
                <p className="mt-0.5 font-semibold text-ink">
                  {pv.risk_score !== null ? `${pv.risk_score} / 10 (${lr?.band ?? "-"})` : "Not scored yet"}
                </p>
                {lr?.reasons?.[0] && <p className="mt-1 text-xs text-ink-2">{lr.reasons[0].explanation}</p>}
              </div>
              <div className="rounded-lg bg-brand-soft p-3">
                <p className="text-xs text-muted-ink">Suggested next step</p>
                <p className="mt-0.5 font-semibold text-brand">
                  {r ? (ACTION_NAME[r.action] ?? human(r.action)) : (pv.suggested_action ?? "Nothing needed")}
                </p>
                {r?.justification?.headline && <p className="mt-1 text-xs text-ink-2">{r.justification.headline}</p>}
              </div>
            </div>
          </Section>

          <Section id="message" icon={<MessageSquareText className="size-4.5" />} title="Message to the customer">
            {r ? (
              <MessageReview rec={r} />
            ) : rec.isLoading && recId ? (
              <Loading />
            ) : pv.health === "on_track" ? (
              <p className="text-sm text-muted-ink">Nothing to send: this customer needs no follow-up right now.</p>
            ) : (
              <div className="space-y-3">
                <p className="text-sm text-ink-2">The agents have not prepared a follow-up for this customer yet.</p>
                <RunAgents policyId={id} />
              </div>
            )}
          </Section>

          <Section id="cover" icon={<BadgePlus className="size-4.5" />} title="Extra cover">
            <p className="mb-2 text-xs font-semibold text-muted-ink uppercase">They already have</p>
            <ul className="mb-4 space-y-1.5 text-sm">
              {v.current.map((c) => (
                <li key={c.code} className="flex items-center gap-2 text-ink">
                  <CheckCircle2 className="size-4 text-ok" aria-hidden /> {c.name}
                </li>
              ))}
            </ul>
            <p className="mb-2 text-xs font-semibold text-muted-ink uppercase">They could add</p>
            {v.eligible.some((c) => c.recommended) && r && r.action !== "add_on_offer" && (
              <p className="mb-3 rounded-lg bg-ice p-3 text-xs text-ink-2">
                The agent picked the best cover below. Today&apos;s message deals with something more urgent, so it
                isn&apos;t offered yet. An adviser can raise it later.
              </p>
            )}
            {v.eligible.length === 0 ? (
              <p className="text-sm text-muted-ink">{v.not_eligible_reason}</p>
            ) : (
              <div className="grid gap-3 sm:grid-cols-2">
                {v.eligible.map((c) => (
                  <div key={c.code} className={cx("rounded-xl border p-4", c.recommended ? "border-brand bg-brand-soft" : "border-rule")}>
                    <div className="flex items-start justify-between gap-2">
                      <p className="font-semibold text-ink">{c.name}</p>
                      {c.recommended && (
                        <Badge tone="brand" icon={false}>
                          <Sparkles className="size-3" aria-hidden /> Suggested
                        </Badge>
                      )}
                    </div>
                    <p className="mt-1 text-xs text-muted-ink">{c.description}</p>
                    {c.rationale && <p className="mt-2 text-xs text-ink-2">{c.rationale}</p>}
                    <p className="mt-2 text-sm font-bold text-ink">
                      {money(c.premium)} <span className="font-normal text-muted-ink">/ year from</span>
                    </p>
                  </div>
                ))}
              </div>
            )}
          </Section>

          <Section id="history" icon={<History className="size-4.5" />} title="What has been done (CRM history)">
            {!crm.data?.length ? (
              <p className="text-sm text-muted-ink">Nothing recorded yet.</p>
            ) : (
              <ol className="space-y-3">
                {crm.data.map((a) => (
                  <li key={a.id} className="flex gap-3 text-sm">
                    <span className="mt-1.5 size-2 shrink-0 rounded-full bg-brand" />
                    <div>
                      <p className="font-semibold text-ink">
                        {CRM_TEXT[a.kind] ?? human(a.kind)}
                        {a.channel && <span className="font-normal text-muted-ink"> · {CHANNEL_NAME[a.channel] ?? a.channel}</span>}
                      </p>
                      <p className="text-ink-2">{a.summary}</p>
                      <p className="text-xs text-muted-ink">
                        {stamp(a.created_at)} · {a.actor}
                      </p>
                    </div>
                  </li>
                ))}
              </ol>
            )}
          </Section>

          <Section id="ai" icon={<Bot className="size-4.5" />} title="How the AI decided">
            {!trace.data ? (
              <p className="text-sm text-muted-ink">The agents have not looked at this customer yet.</p>
            ) : (
              <>
                <ol className="space-y-3">
                  {trace.data.steps.map((s) => (
                    <li key={s.agent} className="flex gap-3 text-sm">
                      {s.status === "completed" ? (
                        <CheckCircle2 className="mt-0.5 size-4.5 shrink-0 text-ok" aria-label="done" />
                      ) : (
                        <CircleDashed className="mt-0.5 size-4.5 shrink-0 text-faint" aria-label="not needed" />
                      )}
                      <div>
                        <p className="font-semibold text-ink">
                          {s.title}
                          {s.uses_ai && <span className="ml-1.5 text-xs font-semibold text-brand">AI</span>}
                        </p>
                        <p className="text-ink-2">{s.summary}</p>
                      </div>
                    </li>
                  ))}
                </ol>
                {trace.data.why && <p className="mt-4 rounded-lg bg-ice p-3 text-sm text-ink-2">{trace.data.why}</p>}
              </>
            )}
          </Section>
        </div>

        <div className="space-y-5">
          <Section id="policy" icon={<FileText className="size-4.5" />} title="Policy">
            <Facts
              rows={[
                ["Product", p.product_name],
                ["Policy start", day(p.start_date)],
                ["Policy end", day(p.end_date)],
                ["Premium", `${money(p.premium)} (${p.payment_frequency})`],
                ["Change from last term", `${p.premium_change_pct > 0 ? "+" : ""}${p.premium_change_pct}%`],
                ["Sum insured", money(p.sum_insured)],
                ["Customer for", `${p.tenure_years} year(s)`],
                ["Claims (3 years)", p.claims_count_3y],
                ["Complaints (12 months)", p.service_complaints_12m],
                ["Handled by", `${human(p.channel_owner)}${p.intermediary ? ` · ${p.intermediary}` : ""}`],
              ]}
            />
          </Section>

          <Section id="contact" icon={<ShieldAlert className="size-4.5" />} title="Contact & consent">
            <Facts
              rows={[
                ["Prefers", p.preferred_channel ? CHANNEL_NAME[p.preferred_channel] : "No preference"],
                ["Email allowed", p.consent_email ? "Yes" : "No"],
                ["SMS allowed", p.consent_sms ? "Yes" : "No"],
                ["Offers allowed", p.consent_marketing ? "Yes" : "No"],
                ["City", p.city ?? "-"],
              ]}
            />
          </Section>

          <Section id="documents" icon={<FileText className="size-4.5" />} title="Documents still needed">
            {p.docs_outstanding.length === 0 ? (
              <p className="text-sm text-muted-ink">None. All documents are on file.</p>
            ) : (
              <ul className="space-y-2">
                {p.docs_outstanding.map((d) => (
                  <li key={d} className="flex items-center justify-between gap-2 text-sm">
                    <span className="text-ink">{human(d)}</span>
                    <Button size="sm" busy={received.isPending && received.variables === d} onClick={() => received.mutate(d)}>
                      Mark received
                    </Button>
                  </li>
                ))}
              </ul>
            )}
          </Section>

          <Section id="payments" icon={<Wallet className="size-4.5" />} title="Payments">
            {p.payments.length === 0 ? (
              <p className="text-sm text-muted-ink">No payments on record.</p>
            ) : (
              <ul className="max-h-72 divide-y divide-rule overflow-y-auto text-sm">
                {[...p.payments].reverse().map((x, i) => (
                  <li key={i} className="flex items-center justify-between gap-2 py-2">
                    <span className="text-ink-2">{day(x.due_date)}</span>
                    <span className="font-semibold text-ink">{money(x.amount)}</span>
                    <Badge tone={PAYMENT_TONE[x.status] ?? "neutral"}>{human(x.status)}</Badge>
                  </li>
                ))}
              </ul>
            )}
          </Section>
        </div>
      </div>
    </>
  );
}
