# dram-soc-dashboard-web

Frontend for the SOC Detection Lab dashboard. React 18 + Vite + TypeScript (strict) + TanStack Query v5 + Tailwind CSS. Phase 5 scaffolding only — visualizations land in Phase 6+.

## Setup

```bash
cd dashboard/web
npm install
```

Requires Node 20+ (tested on 24.13).

## Scripts

| Script | What it does |
|---|---|
| `npm run dev` | Starts the Vite dev server (default `http://localhost:5173`, falls through 5174–5180 if busy). Uses a built-in proxy so `/api/*` calls forward to the live API — see "API base URL & CORS" below. |
| `npm run build` | TypeScript project build (`tsc -b`) followed by Vite production bundle. Output: `dist/`. |
| `npm run preview` | Serves the `dist/` bundle locally for sanity-checking the production build. |
| `npm run test` | One-shot Vitest run. Headless. |
| `npm run test:watch` | Vitest in watch mode. |
| `npm run lint` | ESLint with `--max-warnings 0`. |
| `npm run format` | Prettier write across `src/**/*.{ts,tsx,css}`. |

All four core scripts (`dev`, `build`, `test`, `lint`) must pass at the start of every PR.

## Folder structure

```
dashboard/web/
├── public/                       # Static assets served at the site root (favicon)
├── src/
│   ├── api/                      # Typed API client + TanStack Query hooks
│   │   ├── client.ts             # Single fetcher: apiFetch<T>(path, opts)
│   │   ├── endpoints.ts          # One typed wrapper function per endpoint
│   │   ├── queries.ts            # TanStack Query hooks (useSummary, useTimeline, …)
│   │   ├── types.ts              # Hand-written types mirroring backend Pydantic DTOs
│   │   └── client.test.ts        # Smoke test for the fetcher + ApiError shape
│   ├── components/               # Presentational components (Phase 6+)
│   │   └── ui/                   # Lowest-level primitives (Card, Counter, …)
│   ├── routes/
│   │   └── Dashboard.tsx         # Phase 5 placeholder route
│   ├── lib/                      # Utilities (formatters, hooks)
│   ├── styles/
│   │   └── index.css             # Tailwind directives + base styles
│   ├── App.tsx                   # QueryClientProvider + route mount
│   ├── main.tsx                  # Vite entry; mounts <App /> into #root
│   └── vite-env.d.ts             # ImportMetaEnv types
├── tests/
│   └── setup.ts                  # Vitest setup (Testing Library matchers)
├── index.html
├── package.json
├── tsconfig.json                 # references project tsconfig.app + tsconfig.node
├── tsconfig.app.json             # strict + noUncheckedIndexedAccess
├── tsconfig.node.json            # Vite/Vitest config compilation
├── vite.config.ts
├── vitest.config.ts
├── tailwind.config.js
├── postcss.config.js
├── .eslintrc.cjs
├── .prettierrc
├── .env.development              # VITE_API_BASE_URL (empty in dev — proxy in vite.config.ts)
└── README.md
```

## API base URL & CORS

The backend API at `https://mlncxsr5a9.execute-api.us-east-1.amazonaws.com` allows CORS only from `https://dashboard.dram-soc.org`. Local development can't satisfy that.

Two complementary mechanisms keep dev and production both working:

- **`VITE_API_BASE_URL`** environment variable. In `.env.development` it is empty; production builds set it to the public API origin (or to a CloudFront alias once Phase 8 ships).
- **Vite dev-server proxy** in `vite.config.ts` forwards `/api/*` to the real API. Browser sees the request as same-origin → no CORS preflight at all. The proxy URL defaults to the Phase 4 deploy and can be overridden by `VITE_API_BASE_URL` if you want to point at a different stack.

The `apiFetch` client uses `VITE_API_BASE_URL` if set, otherwise relative paths (which Vite proxies in dev; in a real deploy with empty `VITE_API_BASE_URL` they would fail — the production build always sets it).

## Type-safety bridge to the backend

`src/api/types.ts` is **hand-written** to mirror the backend's Pydantic response DTOs (`functions/shared/api_dto.py` + `functions/shared/event_dto.py`). PROJECT_PLAN.md §11 Phase 5 calls this "Approach 1": simple, no codegen, easy to read; downside is manual sync. The Phase 4 API surface is small (10 endpoints) and stable; the trade-off is right at this size.

If we later add many more endpoints or the surface starts churning, switch to `openapi-typescript` codegen against an OpenAPI schema exported by API Gateway.

### `password_raw` boundary (ADR-005)

The backend's `PublicEvent` Pydantic model deliberately omits `password_raw` and uses `extra="forbid"`. The frontend's `PublicEvent` interface mirrors that omission exactly. There is no `password_raw` declaration anywhere in the frontend type tree — confirmed by the grep equivalent `npm run lint` would fail on (unused field) plus the backend's CloudWatch metric filter that alarms if the literal string ever appears in API logs.

## Tailwind theme

Minimal dark-themed palette (`tailwind.config.js`):

- `bg.DEFAULT` — near-black page background
- `bg.elevated` — slightly raised card surfaces
- `bg.border` — subtle dividers
- `fg.DEFAULT` / `fg.muted` / `fg.subtle` — text contrast tiers
- `accent` — teal (per Phase 5 brief; Z's preferred colour)
- `ok` / `danger` — semantic status colors

Phase 6 iterates on this once real visualizations land.

## TanStack Query defaults

In `App.tsx`:

```ts
queries: {
  staleTime: 25_000,        // matches backend 30s cache TTL minus a small buffer
  refetchInterval: 30_000,
  refetchOnWindowFocus: true,
  retry: 2,
  retryDelay: (i) => Math.min(1000 * 2 ** i, 30_000),
}
```

Per-hook overrides in `src/api/queries.ts`:
- `useHealth` polls every 60 s (no need for fast cadence on the health probe).
- `useSession` has `refetchInterval: false` and `staleTime: 5 min` (sessions are immutable once closed).

## Component patterns (Phase 6)

### Component architecture

Each visualization lives in its own folder under `src/components/<Name>/`:
- `<Name>.tsx` — the component itself; calls its own TanStack Query hook, no prop-drilling for server state
- `<Name>.test.tsx` — Vitest tests (mock the API hook, mock Recharts ResponsiveContainer where applicable)

Lowest-level primitives live in `src/components/ui/`: `Skeleton`, `Card`, `Counter`, `TopBarChart`.

### Silent stale data — UX rule for the public dashboard

Every component reads `query.data` directly, **never** `query.isError`:

- If `data` is `undefined` (no cache yet) → render the component's skeleton.
- If `data` is present → render the data, regardless of `isError`.
- A background refetch failure leaves the previous data on screen. **No banners. No "refresh failed" messages. No per-component error UI anywhere visible to the user.**

Rationale: this is a public, read-only, recruiter-visible dashboard. A viewer should never see "Failed to load top usernames" — only loading or data. Failures are operationally important; they route to CloudWatch alarms (Phase 9), not to the viewer.

The pattern is enforced by tests: each component has a "silent stale" test that hands the hook `{ data: <previous>, isError: true }` and asserts no error UI renders.

### Skeleton pattern

`Skeleton.tsx` is a single `animate-pulse` rounded div. Each component's empty/loading state composes Skeletons matching its own shape:
- `CounterRow` — 4 boxes with skeleton number + skeleton label
- `TopBarChart` — 12 horizontal bars at varying widths
- `TimelineChart` — one wide block at chart height
- `RecentEventsTable` — 12 row-height blocks

Skeletons render only when `query.data === undefined`. After data arrives once, skeletons never render again — refetches show stale data, not skeletons.

### `<filtered:len=N>` rendering

Backend stores non-dictionary password attempts as `<filtered:len=N>` (ADR-005). Frontend renders this as `<filtered (N chars)>` in muted color. The transform lives in `parseFilteredPassword(value)` (`src/lib/format.ts`); two components (`TopPasswordsChart`, `RecentEventsTable`) call into it.

### Bundle budget result (Phase 6)

After Phase 6 build:
- `dist/index.html` — 0.60 KB / 0.37 KB gzipped
- `dist/assets/index-<hash>.css` — 9.12 KB / 2.60 KB gzipped
- `dist/assets/index-<hash>.js` — 590.91 KB / **179.89 KB gzipped**

**Total gzipped: ~183 KB** — under the 250 KB target. Recharts is the dominant cost.

If we ever need to shrink: Recharts is replaceable with `visx` or hand-rolled SVG for some charts. Don't preemptively optimize.

### Testing approach

- API hooks are mocked at the `../../api/queries` boundary using Vitest module mocks. Tests don't touch `fetch`.
- Recharts' `ResponsiveContainer` is mocked because jsdom doesn't lay out SVG. Other Recharts internals pass through.
- `@tanstack/react-virtual.useVirtualizer` is mocked in `RecentEventsTable.test.tsx` to bypass virtualization during tests (jsdom has no scroll height).
- Pure-function logic in `src/lib/format.ts` is unit-tested directly.
- Coverage gates: lines/statements ≥ 80%, branches ≥ 70%, **functions ≥ 75%** (Recharts SVG-render callbacks don't fire in jsdom — see comment in `vitest.config.ts`).
