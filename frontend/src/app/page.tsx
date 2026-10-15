"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, CalendarClock, FileCheck2, TrendingUp } from "lucide-react";
import { api, type DashboardOut } from "@/lib/api";
import { day, money, num } from "@/lib/format";
import { Card, ErrorNote, KpiTile, Loading, PageHeader, SeverityBadge } from "@/components/kit";
import { Donut, LineChart } from "@/components/charts";
import { ScanButton } from "@/components/scan";

export default function DashboardPage() {
  const q = useQuery({ queryKey: ["overview", "dashboard"], queryFn: () => api<DashboardOut>("/overview/dashboard") });
  const d = q.data;
  return (
    <>
      <PageHeader
        title="Renewals Dashboard"
        subtitle="Keep customers covered and reduce policy lapses"
        actions={<ScanButton />}
      />
      {q.error && <ErrorNote error={q.error} />}
      {!d ? (
        !q.error && <Loading />
      ) : (
        <div className="space-y-5">
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <KpiTile
              label="Total Policies"
              value={num(d.kpis.total_policies)}
              note={`${num(d.kpis.in_force)} in force`}
              icon={<FileCheck2 className="size-5" />}
            />
            <KpiTile
              label="Due for Renewal"
              value={num(d.kpis.due_for_renewal)}
              note="lifecycle event needs action"
              icon={<CalendarClock className="size-5" />}
              tone="warn"
            />
            <KpiTile
              label="At Risk of Lapse"
              value={num(d.kpis.at_risk)}
              note={`${d.kpis.in_force ? Math.round((d.kpis.at_risk / d.kpis.in_force) * 100) : 0}% of in-force policies`}
              icon={<AlertTriangle className="size-5" />}
              tone="bad"
            />
            <KpiTile
              label="Renewal Rate"
              value={d.kpis.renewal_rate_pct === null ? "-" : `${d.kpis.renewal_rate_pct}%`}
              note="renewed out of ended terms"
              icon={<TrendingUp className="size-5" />}
              tone="ok"
            />
          </div>

          <div className="grid gap-5 xl:grid-cols-[1.6fr_1fr]">
            <Card title="Renewal Trend" action={<span className="text-xs text-muted-ink">renewals falling due per month</span>}>
              <LineChart
                valueLabel="Renewals due"
                points={d.trend.map((t) => ({ label: t.label, value: t.due, detail: `${money(t.premium)} premium` }))}
              />
            </Card>
            <Card title="Policy Status">
              <div className="flex min-h-[212px] items-center justify-center">
                <Donut slices={d.status} centerLabel="in force" />
              </div>
            </Card>
          </div>

          <Card
            title="Recent Alerts"
            action={
              <Link href="/renewals?view=overdue" className="text-sm font-semibold text-brand hover:underline">
                View all
              </Link>
            }
            pad={false}
          >
            {d.alerts.length === 0 ? (
              <p className="p-5 text-sm text-muted-ink">No alerts: nothing needs attention right now.</p>
            ) : (
              <ul className="divide-y divide-rule">
                {d.alerts.map((a) => (
                  <li key={a.policy_id} className="flex flex-wrap items-center gap-x-4 gap-y-1 px-5 py-3 text-sm">
                    <Link href={`/customers/${a.policy_id}`} className="w-40 font-semibold text-ink hover:text-brand">
                      {a.customer_name}
                    </Link>
                    <span className="min-w-0 flex-1 text-ink-2">{a.issue}</span>
                    <span className="text-muted-ink">{day(a.due_date)}</span>
                    <SeverityBadge severity={a.severity} />
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>
      )}
    </>
  );
}
