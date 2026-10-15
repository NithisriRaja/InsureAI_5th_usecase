"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { Sparkles } from "lucide-react";
import { api, type PolicyView } from "@/lib/api";
import { LINE_NAME } from "@/lib/format";
import { Badge, Card, Empty, ErrorNote, Loading, PageHeader, Table, Td, RowLink } from "@/components/kit";
import { ScanButton } from "@/components/scan";

type Candidate = { policy: PolicyView; eligible: number; recommended: string | null };

export default function CoverPage() {
  // Refresh every few seconds so the agents' picks appear one by one while they work.
  const q = useQuery({
    queryKey: ["overview", "cover-list"],
    queryFn: () => api<Candidate[]>("/overview/cover"),
    refetchInterval: 5000,
  });
  const rows = q.data ?? [];
  return (
    <>
      <PageHeader
        title="Additional Cover"
        subtitle="Customers who can be offered extra protection right now (right age, long enough with us, not already covered, agreed to offers). The agent picks the best one for each. Click a customer to see the options."
        actions={
          rows.some((r) => !r.recommended) && (
            <ScanButton
              path="/overview/cover/suggest"
              label="Ask agents to suggest cover"
              nothingText="Every eligible customer already has a suggestion."
              body={undefined}
              confirmText={null}
            />
          )
        }
      />
      <Card pad={false}>
        {q.error && (
          <div className="p-4">
            <ErrorNote error={q.error} />
          </div>
        )}
        {q.isLoading ? (
          <Loading />
        ) : rows.length === 0 ? (
          <Empty>No customer can be offered extra cover right now.</Empty>
        ) : (
          <Table head={["Customer", "Current policy", "Insurance", "Options", "Agent suggests", ""]}>
            {rows.map((r) => (
              <RowLink key={r.policy.policy_id} href={`/customers/${r.policy.policy_id}#cover`}>
                <Td>
                  <Link href={`/customers/${r.policy.policy_id}#cover`} className="font-semibold text-ink hover:text-brand">
                    {r.policy.customer_name}
                  </Link>
                  <span className="block text-xs whitespace-nowrap text-muted-ink">{r.policy.policy_number}</span>
                </Td>
                <Td>{r.policy.product_name}</Td>
                <Td>{LINE_NAME[r.policy.line] ?? r.policy.line}</Td>
                <Td>{r.eligible}</Td>
                <Td>
                  {r.recommended ? (
                    <Badge tone="brand" icon={false}>
                      <Sparkles className="size-3" aria-hidden /> {r.recommended}
                    </Badge>
                  ) : (
                    <span className="text-sm text-muted-ink">Not picked yet</span>
                  )}
                </Td>
                <Td>
                  <Link href={`/customers/${r.policy.policy_id}#cover`} className="font-semibold text-brand hover:underline">
                    View
                  </Link>
                </Td>
              </RowLink>
            ))}
          </Table>
        )}
      </Card>
    </>
  );
}
