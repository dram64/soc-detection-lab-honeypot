# Resume Here

You're picking this up cold, possibly weeks later. Read this **before** you do anything.

If you have 60 seconds, read just §1 and §6.

---

## §1 — Current state

- **🟢 PHASE 2 (2026-09-19, branch `phase-2-detection`): offline detection & analysis.** The archived run was replayed into a **local** Elasticsearch + Kibana 9.5.4 stack (`elastic/`, loopback-only, not in AWS). The replay read the **local** archive at `C:\tmp\cowrie-archive` + `C:\tmp\haproxy-archive`, because S3 `raw/` expires at 90 days and the S3 copy has aged out by design. 8 Sigma rules were deployed as ES|QL detection rules and replayed once: 4,905 alerts, all matching direct-query counts. There are 4 write-ups in `docs/investigations/`. The unbuilt multi-SIEM scaffolding (wazuh/suricata/zeek/misp/scripts, root compose, old top-level docs) was removed. Findings that correct earlier text: `345gs5662d34` is a step of the mdrfckr implant campaign, not "Mirai"; distinct countries from the ip-api output = 83, not 84. See `elastic/README.md`.
- **🔴 SENSOR DECOMMISSIONED (2026-05-21).** The Raspberry Pi 5 honeypot was factory-reset and returned. Cowrie collection is **over** — the project is now a **completed 14-day run (May 6–21, 2026)**, not a live-collecting system. The AWS pipeline + dashboard + portfolio remain fully live and Pi-independent (dashboard headline widgets are now static final-run data). No new attacker data will arrive.
- **Collected dataset (final):** 231,930 events · 36,440 attack sessions · 36,405 SSH login attempts · 16,180 commands · 1,322 unique attacker IPs across 83 countries · 16 uploaded payload hashes (earlier recorded as 84 countries / "20 distinct malware payloads"; corrected 2026-09-19 — duplicate ip-api country labels, and 4 of the 20 hashes were shell-redirect writes, not payloads). Backed up: raw events in S3 `raw/` (90-day lifecycle) **+ permanent local copies** at `C:\tmp\cowrie-archive\` and `C:\tmp\haproxy-archive\`; SHA-256 manifest of the 20 captured files at `s3://dram-soc-honeypot-ingest/captured-samples/` (no lifecycle — persists; the zip of the files themselves was deleted, all versions, on 2026-09-19 to restore ADR-009); Cowrie TTY replays at `C:\tmp\cowrie-tty.tar.gz`.
- **Dashboard reframe (PR #9, merged 48d524f):** dashboard is now a permanent record of the run — static counters, real top-20 passwords (high-frequency attack strings; ADR-005 singleton long-tail stays redacted), static full-run timeline, recent-events passwords masked as bullets, rolling-window markers removed, header states the collection timeframe. CI fix: `dashboard-frontend-deploy.yml` now excludes `apex/*` from its `--delete` sync (it would otherwise wipe the portfolio).
- **Phase 1A (Wazuh SIEM on Pi): SHELVED.** The Pi is gone, so Wazuh-on-Pi as scoped is dead. The `homelab/` directory (Phase 1A WIP artifacts) was removed from the repo. If revived, it needs a new host (re-buy Pi, or a VM/VPS) and a re-scope. Phase 1A never got past Step 4 (3 deploy failures — see git history / the deleted `homelab/wazuh/PHASE_1A_LOG.md` recoverable via `git show 9956e98:homelab/wazuh/PHASE_1A_LOG.md`).
- **Project status:** Portfolio-ready. Phases 1–8.5, 10, 11A, 11B all shipped. **Phase 11B fully complete** (5 of 5 steps; PRs #1–#5 merged). Phase 11C auto-trigger flip was gated on 4 more clean `workflow_dispatch` deploys — now **moot** for new collection (sensor gone), though the backend-deploy path still works for infra changes. Phase 9 / 10.5 obsolete (no live sensor to observe/tune).
- **README:** rewritten 2026-05-07 (SHA 6fe9d28) to accurately describe the deployed AWS-native pipeline. Prior README described an unbuilt homelab stack (Wazuh/ELK/Splunk/MISP/Suricata/Zeek + nonexistent enterprise hardware); new README states only what's actually deployed.
- **Live URLs (all verified 200 as of 2026-05-07):**
  - Portfolio / apex front door: <https://dram-soc.org> · <https://www.dram-soc.org> (Phase 8.5; static HTML deployed to `s3://...dashboard-frontend/apex/index.html`, routed via CF Function `host_router`)
  - Dashboard: <https://dashboard.dram-soc.org> (Phase 8; React SPA; UI refresh in PR #6 — industrial chrome + yellow accent + Bebas Neue display font)
  - Partner project: <https://diamond-iq.dram-soc.org>
- **CSP state:** extended in PR #7 (e1562a3) to allow Google Fonts on `style-src` (`https://fonts.googleapis.com`) and `font-src` (`https://fonts.gstatic.com`) for the apex portfolio. Applied via workstation targeted apply (RHPolicy is AWS-API-untaggable; CI mutate-tag-gate would block); terraform code reconciled to match live state.
- **Cost rate:** ~$2.60/mo. Last billing-alarm threshold: $10 (state OK, billing alerts must be enabled in the AWS console for `EstimatedCharges` to publish).
- **Branch:** `main`, up to date with `origin/main`. Last code commit: `48d524f feat(dashboard): finalize as completed-run view + fix apex-wiping deploy sync` (PR #9). Plus doc updates on top reflecting decommission.
- **Working tree:** `dashboard/soc_detection_dashboard.egg-info/` is the only untracked path — gitignore still queued in backlog.
- **Open follow-up:** the **DigitalOcean droplet** (HAProxy ingress + tunnel endpoint) is still running (~$4–5/mo) with nothing to tunnel to now the Pi is gone — tear it down to stop the cost. Not yet done. **As of 2026-09-19 it is still internet-facing on :22 and its fluent-bit still ships HAProxy connection logs to S3 `raw/haproxy/` every minute** (39,029 objects from 2026-06-18 on; everything older, including all Cowrie data from the run, has expired under the 90-day rule).
- **No `terraform apply` is in flight.** State on S3 backend `diamond-iq-tfstate-334856751632`.

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

- **Synthetic ingest path:** idle — but the bucket is **not** quiet: the droplet's fluent-bit still writes `raw/haproxy/` every minute (see §1 open follow-up, 2026-09-19). No Cowrie data arrives; the 204 objects are leftover from Phase 7's upload window. The ingest Lambda is event-driven, so nothing fires unless new objects arrive.
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

## §6.5 — Post-decommission — next workstream candidates

The honeypot run is complete and the sensor is gone (see §1). The project is now a **finished portfolio piece**: live AWS pipeline + dashboard + portfolio presenting a completed 14-day dataset. Remaining work is cleanup + optional revival, not active collection.

| Candidate | What it is | Status / gate |
|---|---|---|
| (a) Decommission the DigitalOcean droplet | The HAProxy ingress + reverse-tunnel endpoint has nothing to tunnel to now the Pi is gone. Tear down the droplet to stop the ~$4–5/mo spend. Also remove/disable its `soc-fluent-bit` shipping + any DNS pointing at it. | **Recommended next.** Not done yet. Check terraform/edge-shippers state for anything that references the droplet before destroying. |
| (b) ADR-011 §Amendment #3 + runbook for CF tag-bootstrap pattern | Document the CloudFront tag-bootstrap pattern from Step 4 retry #5 (cf:UpdateFunction blocked by mutate-tag-gate on untagged Function) and PR #7 (RHPolicy untaggable → workstation targeted apply). Runbook: "what to do when CI's mutate-tag-gate blocks a CF resource update." | Pure docs; ~1 hour. Still valid. |
| (c) SIEM workstream revival (was Phase 1A) | Wazuh + Suricata + Sigma was scoped on the Pi (now returned). `homelab/` artifacts were deleted from the repo; recover via `git show 9956e98:homelab/wazuh/...`. Needs a **new host** (re-buy Pi, or a VM/VPS) and a re-scope. Phase 1A never got past `docker compose up` (3 distinct deploy failures documented in the old log). | Dead as-scoped. Only revive if the resume strategy specifically needs live SIEM keywords. Discuss before scoping. |

Also queued (smaller, can be batched):
- **`gitignore`** for `dashboard/soc_detection_dashboard.egg-info/`.
- **GHA Node 20 deprecation update** (June 2026 cutoff — workflow actions need bumping).
- **`moto`** pyproject extras realignment.
- **Stale README** in `modules/edge-shippers/`.
- **Backend-deploy auto-trigger flip (was Phase 11C):** now moot for collection (no sensor). The `workflow_dispatch` backend-deploy path still works for infra changes if needed.

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
