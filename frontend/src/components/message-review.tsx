"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Pencil, Send, X } from "lucide-react";
import { api, errorText, type RecDetail } from "@/lib/api";
import { ACTION_NAME, CHANNEL_NAME, day, human, ROLE_NAME } from "@/lib/format";
import { Badge, Button, inputCls, STATUS_TONE } from "./kit";
import { useSession } from "./session";
import { useToast } from "./toast";

/** The message (or task) the agents prepared, and the approve / edit / reject actions. */
export function MessageReview({ rec: r }: { rec: RecDetail }) {
  const qc = useQueryClient();
  const toast = useToast();
  const { user } = useSession();
  const [mode, setMode] = useState<"view" | "edit" | "reject">("view");
  const [body, setBody] = useState("");
  const [subject, setSubject] = useState("");
  const [reason, setReason] = useState("");

  const done = (text: string, tone: "success" | "info") => {
    toast(text, tone);
    setMode("view");
    qc.invalidateQueries();
  };
  const approve = useMutation({
    mutationFn: () => api(`/approvals/${r.id}/approve`, { method: "POST", body: { expected_version: r.version } }),
    onSuccess: () => done("Approved: the message is on its way and the CRM is updated.", "success"),
    onError: (e) => toast(errorText(e), "error"),
  });
  const edit = useMutation({
    mutationFn: () =>
      api(`/approvals/${r.id}/edit`, {
        method: "POST",
        body: {
          expected_version: r.version,
          edits: { draft_message: body, ...(r.draft_subject !== null ? { draft_subject: subject } : {}) },
        },
      }),
    onSuccess: () => done("Approved with your changes and sent.", "success"),
    onError: (e) => toast(errorText(e), "error"),
  });
  const reject = useMutation({
    mutationFn: () => api(`/approvals/${r.id}/reject`, { method: "POST", body: { reason } }),
    onSuccess: () => done("Rejected. Nothing was sent.", "info"),
    onError: (e) => toast(errorText(e), "error"),
  });

  const pending = r.status === "pending_approval";
  const canDecide = !!user && (user.role === r.queue || user.role === "admin");

  return (
    <div>
      <div className="space-y-4">
        <div className="flex flex-wrap items-center gap-2 text-sm text-muted-ink">
          <Badge tone="info" icon={false}>
            {ACTION_NAME[r.action] ?? human(r.action)}
          </Badge>
          by <b className="text-ink">{CHANNEL_NAME[r.channel ?? ""] ?? r.channel}</b>
          <Badge tone={STATUS_TONE[r.status] ?? "neutral"}>
            {r.status === "pending_approval" ? "Waiting for your approval" : human(r.status)}
          </Badge>
        </div>

        {!r.draft_message ? (
          <p className="rounded-lg bg-ice p-4 text-sm text-ink-2">
            No message to the customer: the team should contact them directly. {r.explanation}
          </p>
        ) : mode === "edit" ? (
          <div className="space-y-2">
            {r.draft_subject !== null && (
              <input className={inputCls} value={subject} onChange={(e) => setSubject(e.target.value)} aria-label="Subject" />
            )}
            <textarea className={`${inputCls} h-48 py-2`} value={body} onChange={(e) => setBody(e.target.value)} aria-label="Message" />
            <p className="text-xs text-muted-ink">Your edit is checked again (consent, channel, amounts) before it is sent.</p>
          </div>
        ) : (
          <div className="rounded-xl border border-rule bg-ice p-5">
            {r.draft_subject && <p className="mb-3 text-sm font-semibold text-ink">Subject: {r.draft_subject}</p>}
            <p className="text-sm leading-relaxed whitespace-pre-line text-ink-2">{r.draft_message}</p>
          </div>
        )}

        {pending && (
          <div className="flex flex-wrap items-center gap-2">
            {mode === "edit" ? (
              <>
                <Button variant="primary" busy={edit.isPending} disabled={!canDecide} onClick={() => edit.mutate()}>
                  <Send className="size-4" aria-hidden /> Save & Send
                </Button>
                <Button onClick={() => setMode("view")}>Cancel</Button>
              </>
            ) : mode === "reject" ? (
              <>
                <input
                  className={`${inputCls} max-w-sm`}
                  placeholder="Why not send it? (required)"
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                />
                <Button variant="danger" busy={reject.isPending} disabled={!reason.trim() || !canDecide} onClick={() => reject.mutate()}>
                  Reject
                </Button>
                <Button onClick={() => setMode("view")}>Cancel</Button>
              </>
            ) : (
              <>
                <Button variant="primary" busy={approve.isPending} disabled={!canDecide} onClick={() => approve.mutate()}>
                  <Send className="size-4" aria-hidden /> {r.draft_message ? "Approve & Send" : "Approve task"}
                </Button>
                {r.draft_message && (
                  <Button
                    disabled={!canDecide}
                    onClick={() => {
                      setBody(r.draft_message ?? "");
                      setSubject(r.draft_subject ?? "");
                      setMode("edit");
                    }}
                  >
                    <Pencil className="size-4" aria-hidden /> Edit
                  </Button>
                )}
                <Button variant="danger" disabled={!canDecide} onClick={() => setMode("reject")}>
                  <X className="size-4" aria-hidden /> Reject
                </Button>
              </>
            )}
            {!canDecide && (
              <span className="text-xs text-warn">
                Only the {ROLE_NAME[r.queue] ?? r.queue} or an administrator can approve this one.
              </span>
            )}
          </div>
        )}
        {r.approval && (
          <p className="text-sm text-muted-ink">
            {human(r.approval.decision)} by {r.approval.actor} on {day(r.approval.at)}
            {r.approval.reason ? `: ${r.approval.reason}` : ""}.{r.message && ` Message ${r.message.status}.`}
          </p>
        )}
      </div>
    </div>
  );
}
