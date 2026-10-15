"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState, type ReactNode } from "react";
import {
  BadgePlus,
  ShieldCheck,
  Check,
  Bell,
  LayoutDashboard,
  Menu,
  MessageSquareText,
  RefreshCcw,
  ShieldAlert,
  Workflow,
  X,
} from "lucide-react";
import { BackendBanner } from "./providers";
import { ROLES, useSession } from "./session";
import { Avatar, cx } from "./kit";

export const NAV = [
  { href: "/", label: "Renewals Dashboard", icon: LayoutDashboard },
  { href: "/renewals", label: "Renewal Management", icon: RefreshCcw },
  { href: "/retention", label: "Retention & Churn", icon: ShieldAlert },
  { href: "/messaging", label: "Messages to Approve", icon: MessageSquareText },
  { href: "/cover", label: "Additional Cover", icon: BadgePlus },
  { href: "/workflow", label: "Workflow & Follow-ups", icon: Workflow },
];

const SWITCH_LABEL: Record<string, string> = {
  retention: "Retention",
  adviser: "Financial advisor",
  admin: "Administrator",
};

function RoleSwitch() {
  const { user, switchRole } = useSession();
  const [open, setOpen] = useState(false);
  if (!user) return null;
  return (
    <div className="relative m-3">
      {open && (
        <ul className="absolute right-0 bottom-full left-0 mb-2 overflow-hidden rounded-xl bg-nav-2 p-1 shadow-raised">
          {ROLES.map((r) => (
            <li key={r}>
              <button
                onClick={() => {
                  setOpen(false);
                  if (r !== user.role) switchRole(r);
                }}
                className={cx(
                  "flex w-full items-center justify-between rounded-lg px-3 py-2 text-left text-sm",
                  r === user.role ? "bg-brand text-white" : "text-nav-text hover:bg-nav-hover hover:text-white",
                )}
              >
                {SWITCH_LABEL[r]}
                {r === user.role && <Check className="size-4" aria-hidden />}
              </button>
            </li>
          ))}
        </ul>
      )}
      <div className="flex items-center gap-3 rounded-xl bg-nav-2 p-3">
        <Avatar name={user.name} size="sm" />
        <div className="min-w-0 flex-1 leading-tight">
          <p className="truncate text-sm font-semibold text-white">{user.name}</p>
          <p className="truncate text-xs text-nav-glow">{SWITCH_LABEL[user.role] ?? user.role}</p>
        </div>
        <button
          onClick={() => setOpen(!open)}
          aria-expanded={open}
          className="text-xs font-semibold text-nav-glow hover:text-white"
        >
          Switch
        </button>
      </div>
    </div>
  );
}

function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  const path = usePathname();
  return (
    <div className="flex h-full flex-col bg-nav text-nav-text">
      <Link href="/" onClick={onNavigate} className="flex items-center gap-3 px-5 py-5" aria-label="InsureAI home">
        <span className="grid size-10 shrink-0 place-items-center rounded-xl bg-gradient-to-br from-[#3b82f6] to-[#1d4ed8] shadow-[0_4px_14px_rgba(37,99,235,0.45)] ring-1 ring-white/15">
          <ShieldCheck className="size-5.5 text-white" strokeWidth={2.25} aria-hidden />
        </span>
        <span className="leading-tight">
          <span className="block font-display text-xl font-extrabold tracking-tight text-white">
            Insure<span className="bg-gradient-to-r from-[#60a5fa] to-[#a5b4fc] bg-clip-text text-transparent">AI</span>
          </span>
          <span className="block text-[11px] font-medium tracking-wide text-nav-glow/80">Renewals &amp; Retention</span>
        </span>
      </Link>
      <nav aria-label="Main" className="flex-1 space-y-1 px-3">
        {NAV.map(({ href, label, icon: Icon }) => {
          const active = href === "/" ? path === "/" : path.startsWith(href);
          return (
            <Link
              key={href}
              href={href}
              onClick={onNavigate}
              aria-current={active ? "page" : undefined}
              className={cx(
                "flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors",
                active ? "bg-brand text-white" : "text-nav-text hover:bg-nav-hover hover:text-white",
              )}
            >
              <Icon className="size-4.5 shrink-0" aria-hidden />
              {label}
            </Link>
          );
        })}
      </nav>
      <RoleSwitch />
    </div>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const path = usePathname();
  const current = NAV.find((n) => (n.href === "/" ? path === "/" : path.startsWith(n.href)));
  return (
    <div className="min-h-screen bg-canvas">
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-64 lg:block">
        <Sidebar />
      </aside>
      {open && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <div className="absolute inset-0 bg-nav/50" onClick={() => setOpen(false)} />
          <aside className="absolute inset-y-0 left-0 w-64">
            <Sidebar onNavigate={() => setOpen(false)} />
          </aside>
        </div>
      )}
      <div className="lg:pl-64">
        <header className="sticky top-0 z-20 flex h-14 items-center justify-between gap-3 border-b border-rule bg-card/90 px-4 backdrop-blur sm:px-6">
          <div className="flex items-center gap-2">
            <button className="rounded-lg p-1.5 hover:bg-ice lg:hidden" onClick={() => setOpen(!open)} aria-label="Menu">
              {open ? <X className="size-5" /> : <Menu className="size-5" />}
            </button>
            <span className="text-sm font-semibold text-muted-ink">
              InsureAI · {current?.label ?? (path.startsWith("/customers") ? "Customer" : "")}
            </span>
          </div>
          <Link href="/workflow" className="rounded-lg p-2 text-muted-ink hover:bg-ice" aria-label="Follow-ups">
            <Bell className="size-4.5" />
          </Link>
        </header>
        <main className="mx-auto max-w-[1400px] px-4 py-6 sm:px-6">
          <BackendBanner />
          {children}
        </main>
      </div>
    </div>
  );
}
