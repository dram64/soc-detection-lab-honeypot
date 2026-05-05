# SOC Detection Lab — Honeypot Visualizer Dashboard

> **Live:** <https://dram-soc.org> (front door) · <https://dashboard.dram-soc.org> (dashboard)
> **Status: portfolio-ready** — Phases 1–8.5 shipped. Phases 9–11 pending.

A serverless dashboard visualizing SSH-honeypot login attempts in near-real time. Cowrie → S3 → ingest Lambda → DynamoDB → API Lambda → React/Recharts SPA → CloudFront → Cloudflare. Built end-to-end on AWS at ~$2.60/month.

## Read these first

| Document | When to open it |
|---|---|
| [docs/RESUME_HERE.md](docs/RESUME_HERE.md) | **You're picking this up cold weeks later.** Current AWS state, git state, the next phase, the exact prompt to resume Phase 8.5. |
| [docs/ENGINEERING_NARRATIVE.md](docs/ENGINEERING_NARRATIVE.md) | **You're a recruiter or want a 5-min capstone read.** Architecture, phases shipped, the 8 architectural fixes caught + resolved, plan amendments, deferred decisions, what's left, cost. |
| [docs/PROJECT_PLAN.md](docs/PROJECT_PLAN.md) | The full design. Living document, v1.5. |
| Per-phase logs `docs/PHASE_{1..8}_LOG.md` | The blow-by-blow of what shipped in each phase, including bugs caught and prompt deviations. |

## Architecture decisions

Read 005 and 007 before any infrastructure change.

- [ADR-001 — Data schema](docs/adr/001-data-schema.md)
- [ADR-002 — Log shipping](docs/adr/002-log-shipping.md)
- [ADR-003 — Single-table DynamoDB design](docs/adr/003-single-table-design.md)
- [ADR-004 — Frontend stack](docs/adr/004-frontend-stack.md)
- [ADR-005 — Password filtering boundary](docs/adr/005-password-filtering.md) ← **load-bearing**
- [ADR-007 — Cloudflare proxy as edge WAF (no AWS WAF)](docs/adr/007-cloudflare-waf-over-aws-waf.md) ← **load-bearing**
- [ADR-009 — Captured-malware policy](docs/adr/009-captured-malware-policy.md)

## Layout

```
dashboard/
├── README.md                       # this file
├── docs/
│   ├── RESUME_HERE.md              # resume-from-cold guide
│   ├── ENGINEERING_NARRATIVE.md    # 5-min capstone
│   ├── PROJECT_PLAN.md             # living design doc, v1.5
│   ├── PHASE_{1..8}_LOG.md         # per-phase logs
│   ├── PHASE_8_5_LOG.md            # apex landing page log
│   ├── adr/                        # architectural decision records
│   └── runbooks/
├── functions/
│   ├── ingest/handler.py           # S3 → DDB ingest, password classifier (ADR-005)
│   ├── aggregator/handler.py       # DDB Streams consumer, SUMMARY/RANK rollups
│   └── api/handler.py              # 8 read routes, Pydantic strict, parallel boto3 Client
├── infrastructure/terraform/
│   ├── environments/dev/           # backend = s3://diamond-iq-tfstate-334856751632
│   └── modules/{dynamodb,ingest,aggregator,api,api-gateway,cloudfront,hosting,alarms}/
├── tools/
│   ├── synthetic_data_generator.py # Cowrie-shape generator with --anchor-time determinism
│   └── data/asn_pools.json         # 25 ASNs, 22 countries, documented Phase 7 distribution
├── web/                            # React 18 + Vite + TS strict + TanStack Query v5 + Tailwind
├── frontend-apex/                  # Phase 8.5 — apex landing page (static, ~952 KB)
│   ├── index.html                  #   inline CSS + inline JS (live-fetch from /api/top/countries)
│   ├── architecture.svg            #   palette-matched system diagram (Treatment D)
│   ├── preview.webm                #   12s autoplay loop captured from the live dashboard (Treatment C)
│   ├── preview.jpg                 #   poster + prefers-reduced-motion fallback
│   └── favicon.svg
└── scripts/
    ├── deploy_frontend.sh          # build + s3 sync + CloudFront invalidate
    ├── package_lambdas.sh
    └── package_lambdas.py
```

## Costs

~$2.60/month steady state. $10 CloudWatch billing alarm armed (defense before the Phase 9 viral-traffic runbook).

## Pairs with

[Diamond IQ](https://github.com/dram64/diamond-iq) — separate detection-engineering portfolio piece. Together they cover the analyst-side (Diamond IQ) and the platform-side (this) of a small SOC.
