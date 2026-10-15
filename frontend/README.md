# Frontend

Minimal web UI for the insurance agents POC: worklists, approvals and run progress on top of the FastAPI backend in the repo root.

```bash
npm install
npm run dev          # http://localhost:3000 (backend expected on http://localhost:8000)
```

Copy `.env.local.example` to `.env.local` to point at another backend.

## Scripts

| Script | |
|---|---|
| `npm run dev` | Dev server |
| `npm run build` / `npm start` | Production build / serve |
| `npm run lint` / `npm run typecheck` | ESLint / `tsc --noEmit` |
| `npm run gen:api` | Regenerate `src/lib/api-types.ts` from the backend's OpenAPI schema (needs `uv`) |

## Layout

```
src/app/            pages: / (dashboard), recommendations, recommendations/[id], leads,
                    renewals, runs, runs/[id], batches/[id], messages
src/components/     ui.tsx (badges, buttons, cards, tables), session.tsx (acting-as picker,
                    heartbeat), providers.tsx (query client, backend-down banner), toast.tsx
src/lib/            api.ts (fetch wrapper, error envelope, types), format.ts, session-store.ts
```

## Behaviour notes

- **Identity**: no passwords. The picker calls `POST /sessions`; the session id is kept in `localStorage` and sent as `X-Session-Id`. All tabs share it. A 401 reopens the picker. Heartbeat every 60s while the tab is visible.
- **Decisions** send `expected_version`. A 409 (someone else decided, stale, expired) shows a toast and reloads the item. A 422 rule violation from an edit is shown next to the fields.
- **Role check** is shown in the UI (sales → sales queue, underwriter → underwriting, retention → retention, admin → all); the API enforces it.
- **Polling**: running runs and batches poll every 2s and stop at a terminal state; lists refresh slowly otherwise. Polling pauses in background tabs.
- **Money**: policy premiums and offers come from the API in minor units (cents); signals and lead sum insured are whole units.
