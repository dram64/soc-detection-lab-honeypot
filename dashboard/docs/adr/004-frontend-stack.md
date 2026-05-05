# ADR-004 — Frontend stack: React 18 + Vite + TS + TanStack Query + Tailwind

**Status:** Accepted
**Date:** 2026-04-28
**Phase introduced:** Phase 1 (decision); Phases 5–7 (implementation)

## Context

The dashboard is a single-page, public, read-only data visualization. Requirements:

- Loads fast on a recruiter's first click (Lighthouse Performance ≥ 90).
- Polls a small set of JSON endpoints on an interval, displays charts and a virtualized table.
- Mobile-first responsive.
- No authentication, no write surface.
- Maintained by one developer; no team-shared learning curve to amortize.
- Must reuse Diamond IQ's frontend pattern (proven in this AWS account).

## Decision

| Concern | Choice |
|---|---|
| Framework | React 18 |
| Build tool | Vite |
| Language | TypeScript (strict) |
| Server-state | TanStack Query v5 |
| UI-state | `useState` / `useReducer`; no Redux |
| Styling | Tailwind CSS |
| Charts | Recharts |
| Map | `react-simple-maps` + TopoJSON |
| Date formatting | `date-fns` |
| Virtualization | `@tanstack/react-virtual` |
| Test runner | Vitest |
| Component testing | Testing Library |
| E2E smoke | Playwright |

Bundle target: < 250 KB gzipped (code, no map data) for the initial dashboard route.

## Consequences

**Positive:**
- Same stack as Diamond IQ — engineering knowledge transfers; muscle memory works.
- Vite's dev-server start is < 1 s; iteration is fast.
- TanStack Query handles the only complex piece of state we have (server data with refetch / stale-time / window-focus refetch). One concept, no Redux.
- Tailwind avoids a CSS architecture debate; the design is utility-first by default.
- Recharts is "boring" and well-documented; no novel charting library risk.

**Negative:**
- React 18's bundle baseline is ~45 KB gzipped. Acceptable given the target.
- TanStack Query has a learning cliff for developers new to it. Single developer; not a real risk here.
- TopoJSON world data is ~100 KB before tree-shaking; we'll inline a small subset (countries only, no admin-1) and lazy-load the GeoMap to keep the initial bundle small.

## Alternatives considered

- **Next.js.** Rejected — server-side rendering is unnecessary for a single-page public dashboard backed by an HTTP API. SSG would be possible but adds build-time AWS coupling. Static SPA on CloudFront is simpler.
- **Solid / Svelte / Vue.** All viable; rejected purely on pattern reuse with Diamond IQ. No technical disqualifier.
- **Plain `fetch` + `useEffect` instead of TanStack Query.** Rejected — we'd reinvent refetch interval, stale-while-revalidate, retry, and dedup. TanStack Query is well worth its bundle cost.
- **D3 instead of Recharts.** Rejected — D3 is too low-level for our chart set (bar / line / choropleth all done by Recharts and react-simple-maps with declarative props). D3 would extend dev time without visual benefit.
- **Mantine / shadcn / MUI.** All viable; rejected to keep bundle small. We have ~6 visual primitives (card, counter, chart, table row, header, footer); Tailwind handles them directly without a component library tax.
