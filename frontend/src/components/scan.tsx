"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Play } from "lucide-react";
import { api, errorText, type BatchOut } from "@/lib/api";
import { Button } from "./kit";
import { useToast } from "./toast";

/** "Run agents": scan every policy and let the five agents work each due one. The same button
 * drives other batch actions (e.g. extra-cover suggestions) through ``path`` and ``label``. */
export function ScanButton({
  path = "/renewals/scan",
  label = "Run agents on due policies",
  nothingText = "Nothing to run: every due policy has already been decided by a person.",
  body = { rerun_pending: true },
  confirmText = null,
}: {
  path?: string;
  label?: string;
  nothingText?: string;
  body?: unknown;
  confirmText?: string | null;
} = {}) {
  const qc = useQueryClient();
  const toast = useToast();
  const [batch, setBatch] = useState<string | null>(null);
  const finish = (b: BatchOut) => {
    setBatch(null);
    qc.invalidateQueries();
    const failed = b.counts.failed ?? 0;
    toast(
      failed ? `Agents finished; ${failed} run(s) failed (check the LLM settings).` : "Agents finished.",
      failed ? "error" : "success",
    );
  };
  const progress = useQuery({
    queryKey: ["batch", batch],
    queryFn: async () => {
      const b = await api<BatchOut>(`/batches/${batch}`);
      if (b.done) finish(b);
      return b;
    },
    enabled: !!batch,
    refetchInterval: (q) => (q.state.data?.done ? false : 1000),
  });
  const scan = useMutation({
    mutationFn: () => api<BatchOut>(path, { method: "POST", body }),
    onSuccess: (b) => {
      if (!b.run_ids.length) {
        toast(nothingText, "info");
        return;
      }
      setBatch(b.id);
      toast("Agents started.", "success");
    },
    onError: (e) => toast(errorText(e), "error"),
  });
  const p = progress.data;
  const running = !!batch && !!p && !p.done;
  return (
    <Button
      variant="primary"
      onClick={() => {
        if (!confirmText || window.confirm(confirmText)) scan.mutate();
      }}
      busy={scan.isPending || running}
    >
      {!running && <Play className="size-4" aria-hidden />}
      {running ? "Agents working…" : label}
    </Button>
  );
}
