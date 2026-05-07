# Resume Here

You're picking this up cold, possibly weeks later. Read this **before** you do anything.

If you have 60 seconds, read just §1 and §6.

---

## §1 — Current state

- **Project status:** Portfolio-ready. Phases 1–8.5 shipped. **Phase 10 SHIPPED LIVE** (real attacker traffic flowing, MaxMind GeoIP enriched, bidirectional correlation working). Phase 9 / 10.5 / 11 still pending.
- **Live URLs:**
  - Apex front door: <https://dram-soc.org> · <https://www.dram-soc.org> (Phase 8.5)
  - Dashboard: <https://dashboard.dram-soc.org> (Phase 8)
- **Cost rate:** ~$2.60/mo. Last billing-alarm threshold: $10 (state OK, billing alerts must be enabled in the AWS console for `EstimatedCharges` to publish).
- **Branch:** `main`, up to date with `origin/main`. Last commit: `1b5984e Fix Sigma rules: ... ssh_brute_force to correlation`.
- **Working tree:** intentionally dirty. The whole `dashboard/` subtree is untracked — Phases 1–8 have **not yet been committed**. See §5 for the parking commit you should run.
- **No `terraform apply` is in flight.** Last apply finished 2026-04-29; state file is on the S3 backend `diamond-iq-tfstate-334856751632`.

## §2 — AWS resource inventory (us-east-1)

| Resource | Name / ID | Status |
|---|---|---|
| DynamoDB table | `dram-soc-honeypot` | 19,953 items (Phase 7 synthetic data still resident — see §4) |
| Lambda × 3 | `dram-soc-ingest` / `dram-soc-aggregator` / `dram-soc-api` | last-modified 2026-04-29; alarms OK |
| API Gateway HTTP API | `dram-soc-api` (`mlncxsr5a9`) | endpoint `https://mlncxsr5a9.execute-api.us-east-1.amazonaws.com` |
| S3 ingest bucket | `dram-soc-honeypot-ingest` | 204 objects (~1.24 MB) — Phase 7 synthetic uploads, idle |
| S3 frontend bucket | `dram-soc-dashboard-frontend` | 5 objects (favicon, index.html, hashed JS×2, CSS) — current production bundle |
| CloudFront | `EBQKMKUKZIT8N` → `d2y21apawycitj.cloudfront.net` | `Status: Deployed`, alias `dashboard.dram-soc.org` |
| ACM cert | `arn:aws:acm:us-east-1:334856751632:certificate/c78640f1-aa7d-4794-9f0d-62ff7060595b` | ISSUED, used by CloudFront |
| CloudWatch alarms | 15 alarms, prefix `dram-soc-` | all `OK` |

## §3 — Cloudflare DNS state (zone `dram-soc.org`)

- `dashboard` → `d2y21apawycitj.cloudfront.net` — **proxied / orange cloud** (the live alias).
- `_9dc519d3562de5e194ad521179e4471a.dashboard` → `_fa067c3335d73e2d14e8d59ecfce8567.jkddzztszm.acm-validations.aws.` — **DNS only / grey cloud** (ACM validation; safe to leave; ACM re-checks on cert renewal).

## §4 — What's running unattended

- **Synthetic ingest path:** **idle.** No process is writing to `s3://dram-soc-honeypot-ingest/`; the 204 objects are leftover from Phase 7's upload window. The ingest Lambda is event-driven, so nothing fires unless new objects arrive.
- **Synthetic data in DDB:** **left in place.** 19,953 items aged out of the dashboard's 24h window; the live UI shows zeros for `last_24h` / `last_1h`. Leaving the data costs ~rounding-error in DDB storage and lets a cold-start visitor see populated GeoMap/top-list charts (Phase 7 distribution). Will be naturally displaced when real Pi data arrives in Phase 10.
- **Local dev server:** Vite is **still listening** on `localhost:5173` and `localhost:5181` from the Phase 7 verification session. Harmless but waste; kill with `taskkill /F /IM node.exe` (Windows) or just close the IDE-attached terminal.
- **`/tmp/lh/`:** Lighthouse runs left ~553 KB JSON in `C:/tmp/lh/result*.json`. Safe to delete.

## §5 — Git state and the parking commit

The whole `dashboard/` subtree is untracked. To park the project cleanly, stage the tree explicitly (don't `git add -A` — that would also pull in `.claude/` which you may not want versioned):

```bash
cd "D:/Resume 2026/soc-detection-lab"
git status

# Stage Phases 1–8 work + the .gitignore tweak
git add .gitignore
git add dashboard/

# Suggested commit (do NOT run from the agent — review first)
git commit -m "$(cat <<'EOF'
docs: Phase 1-8 capstone narrative and resume-here guide

Phases 1-8 of the SOC Detection Lab honeypot dashboard. Live at
https://dashboard.dram-soc.org. Adds engineering narrative and a
resume-here guide so the project can be picked back up cold for
Phase 8.5 (apex landing page) without re-reading every phase log.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

After that, `git status` should be clean. **Don't push** until you've reviewed the staged tree (it's ~3 weeks of unreviewed work).

## §6 — Phase 10 SHIPPED. Next: 10.5 (gated) or 9 (observability) or 11 (real-data tuning)

- Pi (192.168.1.253) runs Cowrie 2.9.17; DigitalOcean droplet (209.38.129.19) terminates public SSH on port 22 via HAProxy and reverse-tunnels to Cowrie. fluent-bit on both edges ships gzipped batches to S3 every ~60s.
- Ingest Lambda does **bidirectional timestamp-window correlation** (200ms tight window, microsecond precision). Forward in `_process_cowrie_object`; backward in `_process_haproxy_object`. Conditional UpdateItem prevents last-writer-wins races. EMF metric `BackwardCorrelationOutcomes` measures per-outcome rates so Phase 10.5 (deterministic SSH-relay replacing autossh) can be gated on real-world ambiguity data.
- MaxMind GeoLite2 layer is attached. country/asn/asn_org enriched on both forward and backward correlation paths.
- Verified end-to-end with test session `ddc63aaac987` (real attacker IP `104.174.33.78`, Charter Communications US ASN 20001) — see `dashboard/docs/PHASE_10_LOG.md`.

### Phase 10.5 (gated)
Replace autossh with custom SSH client that surfaces `forwarded-tcpip` originator info to Cowrie's local-side log. Triggered when `BackwardCorrelationOutcomes{result=ambiguous}` > 10% over 7 days of real traffic. Spec in ADR-010 §Phase 10.5. ~1–2 days.

### Phase 9 — observability + cost guards (deferrable)
CloudWatch dashboard + viral-traffic runbook + heartbeat alarm now active. Add a scheduled MaxMind layer refresher to remove the per-deploy churn (PHASE_10_LOG follow-up).

### Phase 11 — real-data tuning buffer
3–5 days post-cutover. Tune password dictionary against real attacker-traffic distribution (PROJECT_PLAN v1.0).

## §6.bak — Phase 8.5 — apex landing page (DONE)

**Goal:** `https://dram-soc.org` and `https://www.dram-soc.org` resolve to a tiny static "front door" page that links to the dashboard, the GitHub repo, and Diamond IQ. Recruiter-friendly portfolio entry.

**Deliverables (PROJECT_PLAN.md §11 Phase 8.5):**

- `dashboard/frontend-apex/` — minimal static HTML/CSS, ~10 KB, no build step, no React.
- Same CloudFront distribution; second behavior matching apex with a separate origin path `/apex/` in the same S3 bucket.
- ACM cert SANs extended to cover apex + `www`.
- Cloudflare DNS: apex CNAME-flatten to the CloudFront alias, proxy ON.
- Same response-headers policy applied.

**Acceptance:** both URLs resolve with green padlock; landing-page links work; ~$0 incremental cost.

**Manual checkpoints to expect:** one ACM-DNS-validation record (grey cloud) for the new SAN; one apex CNAME-flatten + a `www` CNAME (both orange cloud).

### Exact prompt to paste to begin Phase 8.5

```
Phase 8 reviewed and approved. Live at https://dashboard.dram-soc.org. Begin Phase 8.5 — apex landing page.

Deliverables (PROJECT_PLAN.md §11 Phase 8.5):
- dashboard/frontend-apex/ — minimal static HTML/CSS, ~10 KB, no build step, no React. Three links: live dashboard, GitHub repo (https://github.com/dram64/soc-detection-lab), Diamond IQ.
- Re-use the existing dram-soc-dashboard-frontend S3 bucket via /apex/ prefix.
- Add a second CloudFront ordered_cache_behavior matching the apex/www host header, origin path /apex/.
- Extend ACM cert SANs to dram-soc.org + www.dram-soc.org. New SAN means a new DNS validation record — surface and pause when it appears.
- Same response_headers_policy applied to the new behavior.
- Cloudflare DNS: apex CNAME-flatten + www CNAME, both proxied / orange cloud.

Acceptance: https://dram-soc.org and https://www.dram-soc.org both resolve with green padlock; landing-page links work; ~$0 incremental cost.

Order of work:
1. Write the apex HTML/CSS.
2. Update modules/hosting: SAN-extended cert (this is a destroy/replace on aws_acm_certificate — confirm before applying), new ordered_cache_behavior, S3 sync of /apex/.
3. terraform plan and surface for approval.
4. Two-stage apply: cert first, surface validation CNAME, wait, full apply.
5. After CloudFront deployed, surface the apex + www CNAMEs (proxied/orange) for me to add.
6. Verify both URLs.
7. Update PHASE_8_5_LOG.md and output "Phase 8.5 complete — awaiting review".

Stop conditions: ACM SAN validation > 60 min, CloudFront 5xx, mixed-content warnings, apex/www mismatch.

Don't: don't redirect www → apex (or vice versa) — both should serve the same page; don't add a second distribution; don't touch the existing dashboard alias.

Begin.
```

## §7 — Backlog still open

| Item | Where it's tracked | Status |
|---|---|---|
| MaxMind GeoLite2 license + layer | PHASE_2_LOG / Phase 7 prompt | Layer absent in current deploy; ingest falls back to source-supplied enrichment when the synthetic path supplies it. Real Pi data won't have country/asn fields and will need MaxMind. |
| Lambda concurrency-quota ticket | PROJECT_PLAN v1.3 | Account at floor (10). Per-function reservation deferred until granted. Cost defense currently lives in API GW throttling + alarms. |
| Pi deployment decision | PROJECT_PLAN §11 Phase 10 | Three paths: primary (port-forward), Fallback A (VPS reverse-tunnel), Fallback B (indefinite synthetic). Decision deferred until Phase 9 observability is in place. |

## §8 — Known polish items

- **Mobile Lighthouse Performance = 84.** Bound by `cumulative-layout-shift = 0.281` (chart-skeleton → Recharts handoff). Fix: reserve fixed heights on chart skeletons. Phase 9 polish.
- **Cloudflare Web Analytics beacon blocked by CSP.** CSP is strict (`script-src 'self'`); Cloudflare auto-injects `static.cloudflareinsights.com`. Decision in Phase 8 was to leave it blocked; Phase 9 sets up CloudWatch + RUM properly.
- **Lighthouse `aria-required-children` and `color-contrast` failures.** Address in an a11y polish pass.
- **`style-src 'unsafe-inline'` in CSP.** Carried for Tailwind. Tighten via report-only mode first when revisited.

## §9 — Sanity-check commands

```bash
# Live URL
curl -I https://dashboard.dram-soc.org

# CloudFront state
aws cloudfront get-distribution --id EBQKMKUKZIT8N --query "Distribution.Status" --output text

# DDB count
aws dynamodb scan --table-name dram-soc-honeypot --select COUNT --region us-east-1 --query Count

# Alarms
aws cloudwatch describe-alarms --region us-east-1 \
  --query "MetricAlarms[?starts_with(AlarmName,'dram-soc')].{Name:AlarmName,State:StateValue}" \
  --output table

# Last terraform output (from environments/dev)
cd dashboard/infrastructure/terraform/environments/dev && terraform output
```

## §10 — Pointers

- Per-phase logs: `dashboard/docs/PHASE_{1..8,8_5,10}_LOG.md`
- Capstone narrative: `dashboard/docs/ENGINEERING_NARRATIVE.md`
- Full design: `dashboard/docs/PROJECT_PLAN.md`
- ADRs: `dashboard/docs/adr/` — read 005 (password) and 007 (Cloudflare WAF) before any infra change
- Runbooks: `dashboard/docs/runbooks/`
- Terraform: `dashboard/infrastructure/terraform/`
- Frontend: `dashboard/web/`
- Lambdas: `dashboard/functions/{ingest,aggregator,api}/handler.py`
- Synthetic generator: `dashboard/tools/synthetic_data_generator.py`
- Deploy script: `dashboard/scripts/deploy_frontend.sh`
