"use client";

import Link from "next/link";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, type Page, type RecOut } from "@/lib/api";
import { ACTION_NAME, CHANNEL_NAME, human, LINE_NAME, ROLE_NAME, stamp } from "@/lib/format";
import { Badge, Card, Empty, ErrorNote, Loading, PageHeader, Pagination, Table, Tabs, Td, type Tone, RowLink } from "@/components/kit";

const PRIORITY_TONE: Record<string, Tone> = { high: "bad", medium: "warn", low: "info" };
const LIMIT = 10;

export default function MessagesPage() {
  const [queue, setQueue] = useState("");
  const [offset, setOffset] = useState(0);
  const q = useQuery({
    queryKey: ["recommendations", "pending", queue],
    queryFn: () => api<Page<RecOut>>("/recommendations", { query: { status: "pending_approval", queue, limit: 200 } }),
  });
  const items = q.data?.items ?? [];
  return (
    <>
      <PageHeader
        title="Messages to Approve"
        subtitle="Every message the agents prepared waits here until a person approves it. Click a customer to read and send it."
      />
      <Card pad={false}>
        <div className="border-b border-rule p-4">
          <Tabs
            value={queue}
            onChange={(v) => {
              setQueue(v);
              setOffset(0);
            }}
            options={[
              { value: "", label: "All" },
              { value: "retention", label: "Retention team" },
              { value: "adviser", label: "Advisers" },
            ]}
          />
        </div>
        {q.error && (
          <div className="p-4">
            <ErrorNote error={q.error} />
          </div>
        )}
        {q.isLoading ? (
          <Loading />
        ) : items.length === 0 ? (
          <Empty>Nothing waiting. Run the agents from the Dashboard to prepare follow-ups.</Empty>
        ) : (
          <>
            <Table head={["Customer", "Insurance", "Message", "Sent by", "Priority", "Who approves", "Prepared", ""]}>
              {items.slice(offset, offset + LIMIT).map((r) => (
                <RowLink key={r.id} href={`/customers/${r.subject_id}#message`}>
                  <Td>
                    <Link href={`/customers/${r.subject_id}#message`} className="font-semibold text-ink hover:text-brand">
                      {r.subject_name}
                    </Link>
                  </Td>
                  <Td>{LINE_NAME[r.line ?? ""] ?? r.line}</Td>
                  <Td>{ACTION_NAME[r.action] ?? human(r.action)}</Td>
                  <Td>{CHANNEL_NAME[r.channel ?? ""] ?? r.channel ?? "-"}</Td>
                  <Td>
                    <Badge tone={PRIORITY_TONE[r.priority] ?? "neutral"}>{human(r.priority)}</Badge>
                  </Td>
                  <Td className="text-sm">{ROLE_NAME[r.queue] ?? r.queue}</Td>
                  <Td className="text-xs whitespace-nowrap text-muted-ink">{stamp(r.created_at)}</Td>
                  <Td>
                    <Link href={`/customers/${r.subject_id}#message`} className="font-semibold text-brand hover:underline">
                      Review
                    </Link>
                  </Td>
                </RowLink>
              ))}
            </Table>
            <Pagination total={items.length} limit={LIMIT} offset={offset} onChange={setOffset} />
          </>
        )}
      </Card>
    </>
  );
}
