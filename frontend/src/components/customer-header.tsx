"use client";

import { Mail, Phone } from "lucide-react";
import { inDays, LINE_NAME } from "@/lib/format";
import { Avatar, Badge, type Tone } from "./kit";

export function CustomerHeader({
  name,
  line,
  policyNumber,
  email,
  phone,
  daysToDue,
  dueTone = "warn",
}: {
  name: string;
  line: string;
  policyNumber: string;
  email?: string | null;
  phone?: string | null;
  daysToDue?: number | null;
  dueTone?: Tone;
}) {
  return (
    <div className="flex flex-wrap items-center gap-4">
      <Avatar name={name} size="lg" />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="font-display text-lg font-bold text-ink">{name}</h2>
          <Badge tone="brand" icon={false}>
            {LINE_NAME[line] ?? line}
          </Badge>
          <span className="text-sm text-muted-ink">{policyNumber}</span>
        </div>
        <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-sm text-muted-ink">
          {email && (
            <span className="flex items-center gap-1.5">
              <Mail className="size-3.5" aria-hidden />
              {email}
            </span>
          )}
          {phone && (
            <span className="flex items-center gap-1.5">
              <Phone className="size-3.5" aria-hidden />+{phone}
            </span>
          )}
        </div>
      </div>
      {daysToDue !== null && daysToDue !== undefined && (
        <Badge tone={dueTone}>{daysToDue >= 0 ? `Due ${inDays(daysToDue)}` : `${-daysToDue} days past due`}</Badge>
      )}
    </div>
  );
}
