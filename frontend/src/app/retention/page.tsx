"use client";

import Link from "next/link";
import { useState } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { api, type RetentionOut } from "@/lib/api";
import { day } from "@/lib/format";
import { Badge, Card, Empty, ErrorNote, HEALTH_TONE, Loading, PageHeader, Pagination, Table, Td, RowLink } from "@/components/kit";
import { BarList, Gauge, STATUS_COLOR } from "@/components/charts";

const LIMIT = 10;

export default function RetentionPage() {
  const [offset, setOffset] = useState(0);
  const [band, setBand] = useState<"" | "high" | "medium" | "low">("");
  const q = useQuery({
    queryKey: ["overview", "retention", band],
    queryFn: () => api<RetentionOut>("/overview/retention", { query: { band } }),
    placeholderData: keepPreviousData,
  });
  const d = q.data;
  const scored = d ? d.bands.reduce((a, b) => a + b.count, 0) : 0;
  return (
    <>
      <PageHeader
        title="Retention & Risk of Churn"
        subtitle="Identify customers at risk and take early action"
      />
      {q.error && <ErrorNote error={q.error} />}
      {!d ? (
        !q.error && <Loading />
      ) : (
        <div className="space-y-5">
          <div className="grid gap-5 lg:grid-cols-3">
            <Card title="At Risk Customers">
              <div className="flex flex-col items-center">
                <Gauge value={d.at_risk} max={d.total} label="customers at risk" />
                <p className="mt-2 text-sm text-muted-ink">
                  <b className="text-ink">{d.pct_of_total}%</b> of {d.total} in-force policies
                </p>
              </div>
            </Card>
            <Card title="Risk of not renewing" action={<span className="text-xs text-muted-ink">retention agent</span>}>
              {scored === 0 ? (
                <p className="text-sm text-muted-ink">
                  No policy has been scored yet. Run the agents from the Dashboard to get a risk rating per customer.
                </p>
              ) : (
                <ul className="space-y-3">
                  {d.bands.map((b) => (
                    <li key={b.key}>
                      <div className="mb-1 flex justify-between text-sm">
                        <span className="flex items-center gap-2 text-ink-2">
                          <span className="size-2.5 rounded-full" style={{ background: STATUS_COLOR[b.key] }} />
                          {b.label} risk
                        </span>
                        <span className="font-semibold text-ink tabular-nums">{b.count}</span>
                      </div>
                      <div className="h-2 rounded-full bg-viz-track">
                        <div
                          className="h-2 rounded-full"
                          style={{ width: `${(b.count / scored) * 100}%`, background: STATUS_COLOR[b.key] }}
                        />
                      </div>
                    </li>
                  ))}
                </ul>
              )}
              {d.by_line.length > 0 && (
                <p className="mt-4 text-xs text-muted-ink">
                  Most at risk: {d.by_line.slice(0, 3).map((l) => `${l.label} (${l.count})`).join(", ")}
                </p>
              )}
            </Card>
            <Card title="Top Risk Indicators">
              <BarList rows={d.indicators.map((i) => ({ label: i.label, value: i.pct, note: `${i.count} customers` }))} unit="%" />
            </Card>
          </div>

          <Card
            title={band ? `${band[0].toUpperCase()}${band.slice(1)} risk customers (${d.customers.length})` : `At Risk Customers (${d.customers.length})`}
            action={
              <label className="flex items-center gap-2 text-sm text-muted-ink">
                Show
                <select
                  className="h-9 rounded-lg border border-rule-2 bg-card px-3 text-sm font-semibold text-ink focus:border-brand focus:outline-none"
                  value={band}
                  onChange={(e) => {
                    setBand(e.target.value as typeof band);
                    setOffset(0);
                  }}
                >
                  <option value="">All at-risk customers</option>
                  <option value="high">High risk</option>
                  <option value="medium">Medium risk</option>
                  <option value="low">Low risk</option>
                </select>
              </label>
            }
            pad={false}
          >
            <div className="pt-4" />
            {d.customers.length === 0 ? (
              <Empty>{band ? `No customers rated ${band} risk.` : "No customers at risk right now."}</Empty>
            ) : (
              <Table head={["Customer", "Policy No.", "Risk Score", "Status", "Reason", "Suggested Action", ""]}>
                {d.customers.slice(offset, offset + LIMIT).map((c) => (
                  <RowLink key={c.policy_id} href={`/customers/${c.policy_id}`}>
                    <Td>
                      <Link href={`/customers/${c.policy_id}`} className="font-semibold text-ink hover:text-brand">
                        {c.customer_name}
                      </Link>
                    </Td>
                    <Td className="whitespace-nowrap">{c.policy_number}</Td>
                    <Td className="font-semibold tabular-nums">
                      {c.risk_score === null ? <span className="font-normal text-muted-ink">not scored</span> : c.risk_score}
                    </Td>
                    <Td>
                      <Badge tone={HEALTH_TONE[c.health]}>{c.health_label}</Badge>
                    </Td>
                    <Td className="max-w-xs text-sm">
                      {c.issue}
                      <span className="block text-xs text-muted-ink">due {day(c.due_date)}</span>
                    </Td>
                    <Td className="text-sm">{c.suggested_action ?? "-"}</Td>
                    <Td>
                      <Link href={`/customers/${c.policy_id}`} className="font-semibold text-brand hover:underline">
                        View
                      </Link>
                    </Td>
                  </RowLink>
                ))}
              </Table>
            )}
            {d.customers.length > LIMIT && (
              <Pagination total={d.customers.length} limit={LIMIT} offset={offset} onChange={setOffset} />
            )}
          </Card>
        </div>
      )}
    </>
  );
}
