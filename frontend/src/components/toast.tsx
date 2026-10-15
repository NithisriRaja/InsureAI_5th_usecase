"use client";

import { createContext, useCallback, useContext, useState, type ReactNode } from "react";
import { cx } from "./kit";

type Toast = { id: number; text: string; tone: "info" | "error" | "success" };
type Push = (text: string, tone?: Toast["tone"]) => void;

const Ctx = createContext<Push>(() => {});
export const useToast = () => useContext(Ctx);

let seq = 0;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const push = useCallback<Push>((text, tone = "info") => {
    const id = ++seq;
    setToasts((t) => [...t, { id, text, tone }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), tone === "error" ? 7000 : 4000);
  }, []);

  return (
    <Ctx.Provider value={push}>
      {children}
      <div className="pointer-events-none fixed right-4 bottom-4 left-4 z-50 flex flex-col items-end gap-2">
        {toasts.map((t) => (
          <div
            key={t.id}
            role="status"
            className={cx(
              "pointer-events-auto max-w-sm rounded-lg px-4 py-3 text-sm font-medium shadow-raised",
              t.tone === "error" && "bg-bad text-white",
              t.tone === "success" && "bg-ok text-white",
              t.tone === "info" && "bg-nav text-white",
            )}
          >
            {t.text}
          </div>
        ))}
      </div>
    </Ctx.Provider>
  );
}
