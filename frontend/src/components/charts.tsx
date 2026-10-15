"use client";

import { useState } from "react";

/* Chart colours: categorical slot 1 for a single series; the reserved status palette for state
 * (always shown with its label, never colour alone). */
export const SERIES_1 = "#2a78d6";
export const STATUS_COLOR: Record<string, string> = {
  on_track: "#0ca30c",
  due_soon: "#fab219",
  overdue: "#ec835a",
  lapsed: "#d03b3b",
  high: "#d03b3b",
  medium: "#fab219",
  low: "#0ca30c",
};
const GRID = "#e6ebf2";
const AXIS_TEXT = "#56667d";

// ------------------------------------------------------------------ line ---

export function LineChart({
  points,
  valueLabel,
  height = 200,
}: {
  points: { label: string; value: number; detail?: string }[];
  valueLabel: string;
  height?: number;
}) {
  const [hover, setHover] = useState<number | null>(null);
  const W = 560;
  const H = height;
  const pad = { l: 34, r: 14, t: 14, b: 26 };
  const max = Math.max(1, ...points.map((p) => p.value));
  const step = Math.ceil(max / 4);
  const top = step * 4;
  const x = (i: number) => pad.l + (i * (W - pad.l - pad.r)) / Math.max(1, points.length - 1);
  const y = (v: number) => pad.t + (1 - v / top) * (H - pad.t - pad.b);
  const path = points.map((p, i) => `${i ? "L" : "M"}${x(i)},${y(p.value)}`).join(" ");
  const area = `${path} L${x(points.length - 1)},${y(0)} L${x(0)},${y(0)} Z`;
  const h = hover !== null ? points[hover] : null;

  return (
    <div className="relative">
      <svg viewBox={`0 0 ${W} ${H}`} className="h-auto w-full" role="img" aria-label={valueLabel}>
        {[0, 1, 2, 3, 4].map((k) => (
          <g key={k}>
            <line x1={pad.l} x2={W - pad.r} y1={y(k * step)} y2={y(k * step)} stroke={GRID} strokeWidth={1} />
            <text x={pad.l - 8} y={y(k * step) + 4} textAnchor="end" fontSize={11} fill={AXIS_TEXT}>
              {k * step}
            </text>
          </g>
        ))}
        <path d={area} fill={SERIES_1} opacity={0.08} />
        <path d={path} fill="none" stroke={SERIES_1} strokeWidth={2} strokeLinejoin="round" />
        {points.map((p, i) => (
          <g key={p.label + i}>
            <text x={x(i)} y={H - 6} textAnchor="middle" fontSize={11} fill={AXIS_TEXT}>
              {p.label}
            </text>
            <circle cx={x(i)} cy={y(p.value)} r={hover === i ? 5 : 4} fill="#fff" stroke={SERIES_1} strokeWidth={2} />
          </g>
        ))}
        {h && hover !== null && (
          <line x1={x(hover)} x2={x(hover)} y1={pad.t} y2={y(0)} stroke={AXIS_TEXT} strokeDasharray="3 3" strokeWidth={1} />
        )}
        {points.map((p, i) => (
          <rect
            key={`hit-${i}`}
            x={x(i) - (W - pad.l - pad.r) / Math.max(1, points.length - 1) / 2}
            y={pad.t}
            width={(W - pad.l - pad.r) / Math.max(1, points.length - 1)}
            height={H - pad.t - pad.b}
            fill="transparent"
            onMouseEnter={() => setHover(i)}
            onMouseLeave={() => setHover(null)}
          />
        ))}
      </svg>
      {h && hover !== null && (
        <div
          className="pointer-events-none absolute -translate-x-1/2 rounded-lg border border-rule bg-card px-3 py-2 text-xs shadow-raised"
          style={{ left: `${(x(hover) / W) * 100}%`, top: 0 }}
        >
          <p className="font-semibold text-ink">{h.label}</p>
          <p className="text-ink-2">
            {valueLabel}: <b>{h.value}</b>
          </p>
          {h.detail && <p className="text-muted-ink">{h.detail}</p>}
        </div>
      )}
    </div>
  );
}

// ----------------------------------------------------------------- donut ---

export function Donut({
  slices,
  centerLabel,
}: {
  slices: { key: string; label: string; count: number }[];
  centerLabel: string;
}) {
  const [hover, setHover] = useState<string | null>(null);
  const total = slices.reduce((a, s) => a + s.count, 0);
  const R = 70;
  const r = 48;
  const C = 2 * Math.PI * ((R + r) / 2);
  let acc = 0;
  const active = slices.find((s) => s.key === hover);
  return (
    <div className="flex w-full flex-wrap items-center justify-center gap-x-8 gap-y-4">
      <svg viewBox="0 0 160 160" className="size-44 shrink-0" role="img" aria-label={`${centerLabel}: ${total}`}>
        <circle cx={80} cy={80} r={(R + r) / 2} fill="none" stroke="#eef2f7" strokeWidth={R - r} />
        {total > 0 &&
          slices.map((s) => {
            const len = (s.count / total) * C;
            const gap = slices.filter((x) => x.count).length > 1 ? 2 : 0;
            const el = (
              <circle
                key={s.key}
                cx={80}
                cy={80}
                r={(R + r) / 2}
                fill="none"
                stroke={STATUS_COLOR[s.key] ?? SERIES_1}
                strokeWidth={hover === s.key ? R - r + 4 : R - r}
                strokeDasharray={`${Math.max(0, len - gap)} ${C}`}
                strokeDashoffset={-acc}
                transform="rotate(-90 80 80)"
                onMouseEnter={() => setHover(s.key)}
                onMouseLeave={() => setHover(null)}
              />
            );
            acc += len;
            return el;
          })}
        <text x={80} y={78} textAnchor="middle" fontSize={22} fontWeight={700} fill="#18283e">
          {active ? active.count : total}
        </text>
        <text x={80} y={96} textAnchor="middle" fontSize={10} fill={AXIS_TEXT}>
          {active ? active.label : centerLabel}
        </text>
      </svg>
      <ul className="min-w-[170px] space-y-3 text-sm">
        {slices.map((s) => (
          <li
            key={s.key}
            className="flex items-center justify-between gap-3"
            onMouseEnter={() => setHover(s.key)}
            onMouseLeave={() => setHover(null)}
          >
            <span className="flex items-center gap-2 text-ink-2">
              <span className="size-2.5 rounded-full" style={{ background: STATUS_COLOR[s.key] ?? SERIES_1 }} />
              {s.label}
            </span>
            <span className="font-semibold text-ink tabular-nums">
              {total ? Math.round((s.count / total) * 100) : 0}%
              <span className="ml-1.5 font-normal text-muted-ink">({s.count})</span>
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

// ----------------------------------------------------------------- gauge ---

export function Gauge({ value, max, label }: { value: number; max: number; label: string }) {
  const pct = max ? Math.min(1, value / max) : 0;
  const R = 60;
  const len = Math.PI * R;
  return (
    <svg viewBox="0 0 160 96" className="h-auto w-44" role="img" aria-label={`${label}: ${value} of ${max}`}>
      <path d="M20 84 A60 60 0 0 1 140 84" fill="none" stroke="#eef2f7" strokeWidth={14} strokeLinecap="round" />
      <path
        d="M20 84 A60 60 0 0 1 140 84"
        fill="none"
        stroke={STATUS_COLOR.overdue}
        strokeWidth={14}
        strokeLinecap="round"
        strokeDasharray={`${pct * len} ${len}`}
      />
      <text x={80} y={72} textAnchor="middle" fontSize={26} fontWeight={700} fill="#18283e">
        {value}
      </text>
      <text x={80} y={90} textAnchor="middle" fontSize={10} fill={AXIS_TEXT}>
        {label}
      </text>
    </svg>
  );
}

// ------------------------------------------------------------------ bars ---

/** Horizontal bars with the value written at the end (magnitude, one hue). */
export function BarList({ rows, unit = "" }: { rows: { label: string; value: number; note?: string }[]; unit?: string }) {
  const max = Math.max(1, ...rows.map((r) => r.value));
  return (
    <ul className="space-y-3">
      {rows.map((r) => (
        <li key={r.label} title={r.note}>
          <div className="mb-1 flex items-center justify-between text-sm">
            <span className="text-ink-2">{r.label}</span>
            <span className="font-semibold text-ink tabular-nums">
              {r.value}
              {unit}
            </span>
          </div>
          <div className="h-2 rounded-full bg-viz-track">
            <div className="h-2 rounded-full" style={{ width: `${(r.value / max) * 100}%`, background: SERIES_1 }} />
          </div>
        </li>
      ))}
    </ul>
  );
}
