"use client";

import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { ApiError, API_URL, api, type Health } from "@/lib/api";
import { TooltipProvider } from "@/components/ui/tooltip";
import { SessionProvider } from "./session";
import { ToastProvider } from "./toast";

export function Providers({ children }: { children: ReactNode }) {
  const [qc] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 5_000,
            refetchOnWindowFocus: true,
            // 4xx won't fix itself; retry network/5xx a couple of times.
            retry: (n, e) => !(e instanceof ApiError && e.status >= 400 && e.status < 500) && n < 2,
          },
        },
      }),
  );
  return (
    <QueryClientProvider client={qc}>
      <ToastProvider>
        <TooltipProvider delayDuration={500}>
          <SessionProvider>{children}</SessionProvider>
        </TooltipProvider>
      </ToastProvider>
    </QueryClientProvider>
  );
}

export function useHealth() {
  return useQuery({
    queryKey: ["health"],
    queryFn: () => api<Health>("/health"),
    refetchInterval: 15_000,
    retry: false,
  });
}

/** Shown above every page while the API is unreachable. */
export function BackendBanner() {
  const h = useHealth();
  if (!h.isError) return null;
  return (
    <div role="alert" className="mb-4 rounded-lg bg-bad px-4 py-2.5 text-sm text-white">
      The service at {API_URL} is not responding, so figures may be out of date and actions will fail. Start it with{" "}
      <code className="rounded bg-black/20 px-1">python -m uvicorn main:app</code> in the insuranceai folder.
    </div>
  );
}
