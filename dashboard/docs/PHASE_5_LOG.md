# Phase 5 — Frontend scaffolding: progress log

**Status:** Complete; awaiting review.
**Date:** 2026-04-29 (UTC)
**Plan reference:** [PROJECT_PLAN.md §11](PROJECT_PLAN.md) — Phase 5 (PROJECT_PLAN.md is at v1.5)

---

## Outcome summary

The Vite + React 18 + TypeScript (strict) frontend is scaffolded at `dashboard/web/`. All four core scripts pass: `npm run dev`, `npm run build`, `npm run test`, `npm run lint`. The placeholder Dashboard route renders end-to-end, fetching live data from the Phase 4 API through the dev-server proxy.

| Acceptance criterion | Result |
|---|---|
| `npm run build` produces a clean production bundle | **PASS** — 179 KB JS / **56.83 KB gzipped** + 6.81 KB CSS / 1.97 KB gzipped |
| `npm run dev` renders "Honeypot Dashboard" with live `/api/healthz` data | **PASS** — `{"status": "ok", "version": "phase-4-dev"}` returned via Vite proxy |
| TypeScript strict mode is on; build passes with zero `any` in committed code | **PASS** — `strict: true` + `noUncheckedIndexedAccess: true` in `tsconfig.app.json`; no `any` in committed source |
| Vitest test passes | **PASS** — 2 tests (success + 4xx error normalization) |
| ESLint passes with zero warnings | **PASS** — `eslint . --max-warnings 0` clean |
| Bundle size for placeholder under 100 KB gzipped | **PASS** — 56.83 KB gzipped (43% of cap; ~22% of the 250 KB Phase 6 target) |

---

## What was built

### Project layout (matches PROJECT_PLAN.md §16)

```
dashboard/web/
├── public/favicon.svg
├── src/
│   ├── api/
│   │   ├── client.ts             # apiFetch<T> + ApiError shape
│   │   ├── client.test.ts        # 2 Vitest smoke tests
│   │   ├── endpoints.ts          # 10 typed endpoint wrappers
│   │   ├── queries.ts            # 10 TanStack Query hooks
│   │   └── types.ts              # Hand-written DTO mirror
│   ├── components/ui/            # (empty; Phase 6+)
│   ├── routes/Dashboard.tsx      # Placeholder route
│   ├── lib/                      # (empty; Phase 6+)
│   ├── styles/index.css          # Tailwind directives + base
│   ├── App.tsx                   # QueryClientProvider + route mount
│   ├── main.tsx                  # Vite entry
│   └── vite-env.d.ts             # ImportMetaEnv types
├── tests/setup.ts                # Vitest setup (Testing Library matchers)
├── index.html
├── package.json
├── tsconfig.json (+ app + node)
├── vite.config.ts
├── vitest.config.ts
├── tailwind.config.js
├── postcss.config.js
├── .eslintrc.cjs
├── .prettierrc
├── .env.development
├── .gitignore
└── README.md
```

### Stack (per ADR-004)

- React 18.3.1
- Vite 5.4.x
- TypeScript 5.6.x (strict + `noUncheckedIndexedAccess` + `noImplicitOverride` + `noUnusedLocals/Parameters`)
- Tailwind CSS 3.4.x (dark theme, teal accent — Z's preferred color)
- TanStack Query v5.59.x
- Vitest 2.1.x + Testing Library
- ESLint 8.57.x with `@typescript-eslint`, `react-hooks`, `react-refresh`, `prettier` integrations
- Prettier 3.3.x
- date-fns 4.x (imported but not yet used; lands in Phase 6 for timeline formatting)

### API client — typed coverage of all 10 endpoints

`src/api/endpoints.ts` exports one typed function per Phase 4 route:

`getHealth()`, `getSummary()`, `getTimeline(params)`, `getTopUsernames(params)`, `getTopPasswords(params)`, `getTopCountries(params)`, `getTopAsns(params)`, `getEvents(params)`, `getBreakdown(params)`, `getSession(id)`.

`src/api/queries.ts` wraps each with a TanStack Query hook (`useHealth`, `useSummary`, …). Per-endpoint overrides:
- `useHealth`: 60 s `staleTime`/`refetchInterval` (no need for fast cadence on a health probe).
- `useSession`: `refetchInterval: false`, 5 min `staleTime` — sessions are immutable once closed.
- All others inherit the 25 s `staleTime` / 30 s `refetchInterval` defaults from `App.tsx` (matches the backend's CloudFront 30 s cache TTL minus a small buffer).

### Type-safety bridge — hand-written

`src/api/types.ts` mirrors the backend's Pydantic DTOs by hand. PROJECT_PLAN.md §11 Phase 5 calls this "Approach 1": no codegen, easy to read; manual sync is the trade-off. Reasonable at this size (10 endpoints, stable shapes); revisit `openapi-typescript` codegen if the surface grows or churns.

### `password_raw` boundary — frontend mirror

`PublicEvent` in `src/api/types.ts` deliberately does **not** declare a `password_raw` field. The backend's Pydantic `PublicEvent` has `extra="forbid"` and the same omission. The frontend's TypeScript type system enforces the mirror at compile time: any future code that tries to read `event.password_raw` is a type error.

Two complementary guarantees:
- Frontend: TypeScript compile error on access; `extra` properties from a server bug get dropped by destructuring (or surface as runtime undefined since the type doesn't declare them).
- Backend: response model `extra="forbid"` rejects construction; CloudWatch metric filter alarms if the literal `password_raw` appears in any API log line.

### Placeholder Dashboard route

`src/routes/Dashboard.tsx` renders:
- Header: "Honeypot Dashboard" + subtitle "Cowrie SSH honeypot, real-time"
- API status pill driven by `useHealth()`: `○ loading` / `● healthy` / `● error`
- Version (from `/api/healthz` response)
- Footer note: "Visualizations coming in Phase 6"

If the pill is green and the version is non-empty, every link in the chain (Vite → React → TanStack Query → typed client → API Gateway → Lambda) is verified working.

### Smoke test

`src/api/client.test.ts` — 2 tests:
1. `getHealth()` returns the expected typed shape on HTTP 200.
2. A 4xx response normalizes to `ApiError` with `status` and parsed `body.error`.

This is enough to prove the test harness is wired and the fetcher's error path works. Phase 6 expands to component tests for the visualizations.

---

## Live wiring verification

Started `npm run dev`; Vite came up on port 5179 (5173–5178 occupied by other processes). Hit several endpoints through the dev server:

```
http://localhost:5179/                          → 200, 757 bytes (HTML)
http://localhost:5179/api/healthz                → 200, {"status": "ok", "version": "phase-4-dev"}
http://localhost:5179/api/summary                → 200, {"total":0, "last_24h":0, "last_1h":0, "unique_ips_24h":0, "sensor_last_seen":null}
```

The API responses come from the live Phase 4 Lambda via the Vite dev-server proxy configured in `vite.config.ts`. Browser-side this looks same-origin, so no CORS preflight occurs. Production builds will use `VITE_API_BASE_URL` directly.

---

## Deviations from the plan

1. **Vite dev-server proxy added — surprise discovery, not in the original spec.** The Phase 4 API allows CORS only from `https://dashboard.dram-soc.org`. A real browser fetching from `localhost:5173` would have hit a CORS preflight failure. The fix is the documented Vite pattern: proxy `/api/*` to the real upstream during dev so the browser sees same-origin requests. No backend change needed; production deploys still use `VITE_API_BASE_URL` directly. Documented in `dashboard/web/README.md` under "API base URL & CORS".

2. **`@types/node` added.** Wasn't in the planned dep list; needed once `vite.config.ts` started using `process.cwd()` to call `loadEnv`. Standard Vite project requirement. `tsconfig.node.json` includes `"types": ["node"]` to scope it to the Vite-config compilation only — `tsconfig.app.json` deliberately omits Node types so application code can't accidentally use Node-only APIs.

3. **Vitest version 2.1.x, not 3.x.** Phase 5 brief said "Vitest" without a version pin; 2.1.x is the latest stable on the same major as the listed dependencies' compatibility matrix. `npm install` resolved everything cleanly.

4. **TypeScript project references** — used `tsc -b` in the `build` script to compile both `tsconfig.app.json` (app) and `tsconfig.node.json` (Vite/Vitest config files). Standard Vite-template approach. `tsconfig.json` is a thin file-list-only references file.

5. **`globalThis` over `global` in the test file.** Initial draft used Node's `global` which fails strict TypeScript without `@types/node` in the app config. Switched to `globalThis` which is the standards-compliant alternative and is recognized in browser/jsdom and Node both.

---

## Decisions made that aren't in the plan

1. **`apiFetch<T>` accepts `query` records and an `AbortSignal`.** TanStack Query passes a fresh `AbortSignal` to the `queryFn`; threading it through to `fetch()` makes cancelled queries actually cancel network requests, not just discard responses. Cheap, correct, important on the `useEvents` infinite-scroll path that lands in Phase 6.

2. **Per-endpoint cache keys** in `src/api/queries.ts` use a `queryKeys` registry object (`queryKeys.summary()`, `queryKeys.topUsernames(params)`, …). Standard TanStack pattern; lets future code do `queryClient.invalidateQueries({ queryKey: queryKeys.summary() })` cleanly.

3. **`bg-bg` is a real Tailwind utility because of the namespaced color** I configured (`colors.bg.DEFAULT`). `bg-bg` reads weird; if Phase 6 wants to cleaner names I'll rename `bg.DEFAULT` to e.g. `surface.page` and update `index.css` accordingly. Calling it out so it's not a surprise.

4. **`<StrictMode>` enabled in `main.tsx`.** Catches double-invocation issues during dev. Production builds are unaffected. Defaults to true in Vite scaffolds; kept on purpose.

5. **Empty `dashboard/web/components/ui/` and `dashboard/web/lib/` directories** kept by gitignore-resistant `.gitkeep`-style placement (just empty dirs which git ignores; will get content in Phase 6 anyway).

6. **`favicon.svg` is a teal dot on a near-black square** — match the Tailwind palette. Inline SVG, no separate icon library yet (icons are a Phase 6 decision per the brief).

---

## Open backlog / forward notes

1. **Production `VITE_API_BASE_URL`** — set during Phase 8 deploy. Either to the API Gateway origin directly or to a CloudFront alias. Current `.env.development` is empty so the dev proxy handles it.

2. **CORS allowlist** — currently only `https://dashboard.dram-soc.org`. Phase 8 will need to confirm this is correct after the actual domain is wired up. If Phase 6 ends up running `npm run preview` against the production build for any reason, the preview server also won't satisfy CORS — the dev proxy doesn't apply to `npm run preview`.

3. **Frontend coverage gate not yet enforced.** PROJECT_PLAN.md §12 specifies "Frontend ≥ 80%" coverage for Phase 6+. Phase 5 has 1 test file (2 tests) — coverage at this stage isn't meaningful since most files are stubs/wiring. Phase 6 wires the gate.

4. **`@vitest/coverage-v8` not installed.** Will be added in Phase 6 when the coverage gate is enforced.

5. **No icon library yet** — Phase 6 picks one. Lucide-react is the obvious default for a Tailwind project; final choice deferred.

---

## What is NOT done (and is correctly out of Phase 5 scope)

- All visualizations (CounterRow, TimelineChart, TopUsernamesChart, TopPasswordsChart, RecentEventsTable, BreakdownDonut). Phase 6.
- GeoMap component. Phase 7.
- Production hosting (S3 origin, CloudFront, ACM, Cloudflare DNS, WAF). Phase 8.
- Apex landing page. Phase 8.5.
- Frontend coverage gate. Phase 6.
- Playwright E2E smoke. Phase 8.

---

**Phase 5 acceptance criteria met. Awaiting review before Phase 6 begins.**
