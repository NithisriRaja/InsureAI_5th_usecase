"use client";

import Link from "next/link";
import { Suspense, useState } from "react";
import { useSearchParams } from "next/navigation";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Search } from "lucide-react";
import { api, type PolicyPage } from "@/lib/api";
import { day, inDays, LINE_NAME } from "@/lib/format";
import {
  Badge,
  Card,
  Empty,
  ErrorNote,
  HEALTH_TONE,
  inputCls,
  Loading,
  PageHeader,
  Pagination,
  Table,
  Tabs,
  Td,
  RowLink,
} from "@/components/kit";

type View = "all" | "due_7" | "due_30" | "overdue" | "at_risk";
const LIMIT = 10;

function RenewalManagement() {
  const params = useSearchParams();
  const [view, setView] = useState<View>((params.get("view") as View) || "all");
  const [q, setQ] = useState("");
  const [offset, setOffset] = useState(0);
  const data = useQuery({
    queryKey: ["overview", "policies", view, q, offset],
    queryFn: () => api<PolicyPage>("/overview/policies", { query: { view, q, limit: LIMIT, offset } }),
    placeholderData: keepPreviousData,
  });
  const page = data.data;
  const counts = page?.counts ?? {};

  return (
    <>
      <PageHeader title="Renewal Management" subtitle="Track and manage upcoming renewals" />
      <Card pad={false}>
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-rule p-4">
          <Tabs<View>
            value={view}
            onChange={(v) => {
              setView(v);
              setOffset(0);
            }}
            options={[
              { value: "all", label: "All Policies", count: counts.all },
              { value: "due_7", label: "Due in 7 days", count: counts.due_7 },
              { value: "due_30", label: "Due in 30 days", count: counts.due_30 },
              { value: "overdue", label: "Overdue", count: counts.overdue },
              { value: "at_risk", label: "At risk", count: counts.at_risk },
            ]}
          />
          <label className="relative w-full sm:w-64">
            <Search className="absolute top-2.5 left-3 size-4 text-faint" aria-hidden />
            <input
              className={`${inputCls} pl-9`}
              placeholder="Customer or policy no."
              value={q}
              onChange={(e) => {
                setQ(e.target.value);
                setOffset(0);
              }}
              aria-label="Search"
            />
          </label>
        </div>
        {data.error && (
          <div className="p-4">
            <ErrorNote error={data.error} />
          </div>
        )}
        {!page ? (
          !data.error && <Loading />
        ) : page.items.length === 0 ? (
          <Empty>No policies in this view.</Empty>
        ) : (
          <>
            <Table head={["Customer", "Policy No.", "Product", "Expiry / Due Date", "Status", "Next step", "Action"]}>
              {page.items.map((p) => (
                <RowLink key={p.policy_id} href={`/customers/${p.policy_id}`}>
                  <Td>
                    <Link href={`/customers/${p.policy_id}`} className="font-semibold text-ink hover:text-brand">
                      {p.customer_name}
                    </Link>
                  </Td>
                  <Td className="whitespace-nowrap">{p.policy_number}</Td>
                  <Td>
                    <span className="block">{p.product_name}</span>
                    <span className="text-xs text-muted-ink">{LINE_NAME[p.line] ?? p.line}</span>
                  </Td>
                  <Td>
                    <span className="block">{day(p.due_date)}</span>
                    <span className="text-xs text-muted-ink">{inDays(p.days_to_due)}</span>
                  </Td>
                  <Td>
                    <Badge tone={HEALTH_TONE[p.health]}>{p.health_label}</Badge>
                  </Td>
                  <Td className="text-sm">{p.suggested_action ?? "-"}</Td>
                  <Td>
                    <Link href={`/customers/${p.policy_id}`} className="font-semibold text-brand hover:underline">
                      View
                    </Link>
                  </Td>
                </RowLink>
              ))}
            </Table>
            <Pagination total={page.total} limit={LIMIT} offset={offset} onChange={setOffset} />
          </>
        )}
      </Card>
    </>
  );
}

export default function Page() {
  return (
    <Suspense fallback={<Loading />}>
      <RenewalManagement />
    </Suspense>
  );
}
