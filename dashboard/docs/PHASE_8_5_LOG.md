# Phase 8.5 — Apex landing page (log)

**Outcome:** Complete. Live at <https://dram-soc.org/> and <https://www.dram-soc.org/>. Both URLs serve a recruiter-facing static landing page that links to the dashboard, GitHub, and the four most-meaningful ADRs. The Phase 8 dashboard at <https://dashboard.dram-soc.org/> is unchanged; cert replacement happened with `create_before_destroy`, no service window.

## What landed

### Static page — `dashboard/frontend-apex/`

- `index.html` — single file, inline CSS + inline JS, ~17 KB. Sticky nav with Dashboard CTA, hero (Treatment C — autoplay-loop video), live-stat badge with API fetch, "What this is" prose (3 paragraphs), architecture section (Treatment D — SVG), tech-stack chips, four ADR summary cards (003 / 005 / 007 / 009), links section, footer.
- `architecture.svg` — 9 KB, palette-matched, three rows (INGEST PATH / READ PATH / RENDER PATH), with explicit ADR-005 + ADR-007 boundary callouts.
- `preview.webm` — 872 KB, 12-second loop captured live from `dashboard.dram-soc.org` via Playwright + Chromium VP9 encoder. Cycles top → GeoMap → Timeline → recent events.
- `preview.jpg` — 33 KB, poster frame + `prefers-reduced-motion: reduce` fallback.
- `favicon.svg` — reused from the dashboard.
- **Total page weight: ~952 KB** (target was < 200 KB excluding hero media; index alone is 17 KB).

### Terraform — `modules/hosting/`

- `aws_acm_certificate.dashboard` — **replaced** with SANs `dram-soc.org` + `www.dram-soc.org` added. New ARN `278d4709-44cf-46f6-9a5c-c6421d6bd20d`. `lifecycle { create_before_destroy = true }` made the swap zero-downtime.
- `aws_cloudfront_distribution.frontend` — `aliases` extended to all 3 hostnames; `function_association` added on default + `/index.html` cache behaviors.
- `aws_cloudfront_function.host_router` — **created**. CloudFront-JS 2.0 viewer-request that rewrites apex/www URIs to `/apex/*` so a single distribution + a single S3 bucket can serve two distinct site contents.
- `aws_s3_bucket_policy.frontend` — refreshed downstream of the distribution change.

### Terraform — `modules/api/`

- `cors_configuration.allow_origins` — extended from `["https://dashboard.dram-soc.org"]` to all three origins.
- New `allowed_origins` list-typed variable; legacy `allowed_origin` kept for back-compat (falls back to a 1-element list when the new variable is empty).
- Lambda env `ALLOWED_ORIGIN` becomes a comma-separated list at apply.

### Lambda code — `dashboard/functions/api/handler.py`

- `ALLOWED_ORIGIN` env var parsed once at cold start into `ALLOWED_ORIGINS` tuple + `DEFAULT_ALLOWED_ORIGIN`.
- New `_select_origin(request_origin)` — echoes the request `Origin` header back if in the allowlist, else falls back to the first allowlisted origin.
- New `_route(event)` extracted from `handler()` so the dispatcher can rewrite `Access-Control-Allow-Origin` after dispatch without threading the origin through 8 inner handlers.
- `Vary: Origin` set when allowlist has > 1 entry (cache-poisoning defense).
- 4 new pytest cases: allowlisted origin echo / unknown origin → default fallback / no-Origin-header → default / single-origin-allowlist omits Vary. **All 26 api tests pass.**

## Apply choreography (what actually happened)

1. `terraform apply phase8_5.tfplan` — new ACM cert created with PENDING_VALIDATION; surfaced 2 new CNAMEs (apex + www, grey cloud). The dashboard subdomain's existing validation CNAME was reused (ACM recognized the unchanged SAN and reissued the same challenge token).
2. User added 2 new validation records in Cloudflare DNS-only.
3. ACM ISSUED in < 5 min; CloudFront rebuilt with the new cert; old cert detached cleanly. Status: Deployed in ~12 min total.
4. Surfaced Round 2 — apex + www CNAMEs to `d2y21apawycitj.cloudfront.net`, both proxied / orange cloud.
5. After DNS resolved, `aws s3 sync dashboard/frontend-apex/ s3://dram-soc-dashboard-frontend/apex/` + a `/*` invalidation completed in < 2 min.
6. Live verification — see below.

## Live verification

| Check | Result |
|---|---|
| `curl -I https://dram-soc.org/` | 200 OK, `server: cloudflare`, `via: ... CloudFront`, all 6 security headers present |
| `curl -I https://www.dram-soc.org/` | 200 OK, identical content (host-router function correctly serves apex content for both hostnames) |
| `curl -I https://dashboard.dram-soc.org/` | 200 OK, `last-modified: Wed, 29 Apr 2026 08:50:36 GMT` — Phase 8 bundle untouched, **no regression** from cert replace |
| `/preview.webm` | 200, `video/webm`, 872 KB |
| `/architecture.svg` | 200, `image/svg+xml`, 9 KB |
| Apex CSP / HSTS / X-Frame-Options / X-Content-Type-Options / Referrer-Policy / Permissions-Policy | all present, identical to dashboard |
| CORS preflight from `https://dram-soc.org` | 204 with `access-control-allow-origin: https://dram-soc.org` + `vary: origin` |
| Live-fetch GET from apex origin | 200 with the right echoed origin + `vary: Origin`; payload returns 16 countries with count > 0 (CN 923, BR 244, US 236, VN 156, EG 131, NL 120, DE 104, IN 78, SE 33, RU 32, ...) |

## Issues caught and fixed

### Issue 1 — Multi-origin CORS required a Lambda code change

The Phase 4 api Lambda hardcoded `Access-Control-Allow-Origin: <single string>` from the env var. API GW handles preflight via its own `cors_configuration` block (terraform-only fix), but the actual GET response comes from the Lambda — a request from `https://dram-soc.org` would have received a response with the dashboard subdomain in the header and the browser would have rejected it.

Fixed in handler.py with origin-echo logic + `Vary: Origin`. Surfaced at Gate 2 because it materially changed the deployment surface (Lambda zip rebuild + redeploy, not just terraform-only). 4 regression tests cover the new behavior.

### Issue 2 — Synthetic data aged out of the rolling rollup window

Verified Phase 8.5 against the live API and `/api/top/countries` returned `{"items": []}` — the Phase 7 synthetic data (still resident in DDB at 19,861 items) had timestamps 2 days old, outside the aggregator's 24h rank-rollup window. The apex live-fetch correctly fell through to its "Live data unavailable" graceful fallback.

Fixed by re-running the synthetic generator with a current `--anchor-time` (2026-04-30T22:46:30Z), 5000 events, `--days 1`. Rollup populated within ~50 seconds; live-fetch then rendered "Currently observing **16** countries targeting this honeypot."

**Operational note for future selves:** until Phase 10 ships real Pi data, the synthetic rollup will age out within ~24h. Three handling options:
- Periodic re-anchor: cron the synthetic generator on a schedule (Phase 9 is the right place to formalize this if Phase 10 slips).
- Accept the fallback: the apex page degrades cleanly to "Live data unavailable" — fully functional, just optically less compelling.
- Bring Phase 10 forward: real data is the permanent fix.

### Issue 3 — `<object>` for SVG would have been blocked by CSP

Initial draft used `<object type="image/svg+xml" data="/architecture.svg">` for the architecture diagram. The shared response-headers policy carries `object-src 'none'`. Caught before deploy; switched to `<img src="/architecture.svg" alt="...">` which renders SVG cleanly with accessibility intact and avoids loosening the CSP.

## Decisions

- **Single distribution, viewer-request URI rewrite.** CloudFront cache behaviors match path-pattern only, not Host header. A small CloudFront-JS 2.0 viewer-request function reads the `Host` header and rewrites the URI to `/apex/<path>` for apex/www requests. ~10 lines of JS, free-tier covers 10M invocations/mo. Cleaner than a second distribution.
- **Hero treatment C primary, Treatment D below the fold.** Per the brief — both shipped initially; user evaluates live and may rebalance later.
- **No MP4 fallback.** All modern browsers (Chrome / Edge / Firefox / Safari 14+) support WebM. Older Safari falls back cleanly to the JPEG poster.
- **No CSP change.** The existing `connect-src 'self' https://mlncxsr5a9.execute-api.us-east-1.amazonaws.com` covers the apex's API fetch (same API origin); the response-headers policy applies as-is to apex without modification.
- **`<img>` not `<object>`** for the architecture SVG — keeps `object-src 'none'`.
- **Origin-echo at the dispatcher, not in each handler.** Threading `request_origin` through 8 inner handlers would have been invasive; rewriting `Access-Control-Allow-Origin` once at the top-level handler after dispatch was the smaller change.

## Cost projection delta

| Line item | Phase 8.5 incremental |
|---|---|
| CloudFront function invocations | ~$0 (10M free / mo, recruiter traffic ~1k/mo) |
| Additional S3 storage (`/apex/*` ~952 KB × 5 versions) | rounding error |
| Lambda redeploy (one-time) | $0 |
| **Phase 8.5 incremental** | **~$0/mo** |

Project total stays at **~$2.60/month**.

## Open backlog (for Phase 9+)

- Synthetic re-anchor cron — formalize the periodic re-upload if Phase 10 slips. Best place: Phase 9's observability + cost guards. ~10 lines of EventBridge + Lambda, or a scheduled GitHub Action against the existing generator.
- `/api/summary` still returns zeros — the SUMMARY#OVERVIEW rollup is built differently from the RANK rollup the live-fetch uses; the synthetic re-upload populated the rank rollup but not the overview. Investigate if the apex's stat ever needs to widen beyond the country count.
- Mobile CLS polish (carried from Phase 8 backlog).
- Consider widening the live-fetch to a richer signal once real Pi data lands (top attacker country, peak hour, etc.).

## State

- Cert ARN: `arn:aws:acm:us-east-1:334856751632:certificate/278d4709-44cf-46f6-9a5c-c6421d6bd20d` (replaces Phase 8's `c78640f1...`, ISSUED, attached to CloudFront)
- CloudFront distribution: `EBQKMKUKZIT8N` → `d2y21apawycitj.cloudfront.net` (3 aliases)
- CloudFront function: `dram-soc-host-router` (cloudfront-js-2.0)
- S3 prefix: `s3://dram-soc-dashboard-frontend/apex/` (5 objects: index.html, architecture.svg, favicon.svg, preview.webm, preview.jpg)
- Live URLs: <https://dram-soc.org/>, <https://www.dram-soc.org/>, <https://dashboard.dram-soc.org/> (untouched)
- Last invalidation: `ICD29GGJ89NM5U6EAOQGJA6S8M` (Completed)
- Last synthetic re-anchor: `2026-04-30T22:46:30Z`, 5000 events, seed 42, days 1
