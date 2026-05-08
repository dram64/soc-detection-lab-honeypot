# SOC Detection Lab — Honeypot Visualizer Dashboard

**Live dashboard:** https://dashboard.dram-soc.org · **Portfolio:** https://dram-soc.org · **Partner project:** [Diamond IQ](https://diamond-iq.dram-soc.org) ([repo](https://github.com/dram64/diamond-iq))

A serverless AWS-native pipeline that ingests live SSH attacker telemetry from a Cowrie honeypot at the network edge, correlates the captured sessions to their real source IPs through a reverse-tunnel architecture, enriches with GeoIP, and renders the result on a real-time React dashboard.

## What this is

A working production system for collecting, processing, and visualizing live SSH attacker traffic. Real attackers from the public internet probe a Cowrie honeypot and the captured attempts (commands, credentials, session metadata) flow through:

- **Edge** — Raspberry Pi 5 hosting Cowrie SSH/Telnet honeypot, with a DigitalOcean droplet hosting HAProxy as the public ingress. `autossh` holds a persistent reverse SSH tunnel between them so the Pi never has a port forwarded from a residential ISP.
- **Log shipping** — `fluent-bit` on both edge hosts ships JSON logs to S3 with filesystem-backed buffering (1 GB cap, 1-min/8-MB batches, gzip + NDJSON) and per-host IAM scoping.
- **Correlation** — A timestamp-window join in Lambda matches each Cowrie session (which sees `127.0.0.1` because of the reverse tunnel) to the originating HAProxy connection log line, recovering the real source IP. Enriches with MaxMind GeoLite2 Country + ASN.
- **Storage** — Single-table DynamoDB design (per ADR-003) with TTL on raw events and aggregate counters under separate prefixes.
- **API + UI** — API Gateway HTTP API + Lambda + a React SPA on CloudFront. Dashboard auto-refreshes at https://dashboard.dram-soc.org.
- **Observability** — CloudWatch metric filters + alarms on the ingest Lambda's log group; SNS topic (`-edge-alarms`) for alerting from CloudWatch alarms (`-cowrie-heartbeat-missing`, `-haproxy-heartbeat-missing` — 15-min window, `treat_missing_data: breaching`).
- **CI/CD** — GitHub Actions OIDC trust assumes a scoped IAM role (`dram-soc-github-deploy`) for `terraform apply` + Lambda code deploy. ADR-011 formalizes the human-vs-CI permission boundary so the deploy role explicitly cannot mint AWS access keys.

The project is built as a portfolio piece for cloud security and detection engineering. It pairs with [Diamond IQ](https://diamond-iq.dram-soc.org) (sports analytics platform on the same AWS account) to demonstrate end-to-end engineering across two distinct production systems.

## Architecture

```
                Internet (real attackers)
                        │
                        ▼
       ┌──────────────────────────────────────┐
       │  Cloudflare proxied DNS (edge WAF)   │
       │  ADR-007: free WAF, no AWS WAF       │
       └────────────────┬─────────────────────┘
                        │
                ┌───────▼────────┐
                │  DigitalOcean  │
                │  droplet :22   │
                │  HAProxy       │
                │  (public SSH)  │
                └───────┬────────┘
                        │ reverse SSH tunnel
                        │ (autossh, Pi-initiated)
                        ▼
                ┌────────────────┐
                │  Raspberry Pi  │
                │  Cowrie SSH    │
                │  honeypot      │
                └───────┬────────┘
                        │
   ┌────────────────────┴────────────────────┐
   │  fluent-bit on Pi: cowrie.json          │
   │  fluent-bit on droplet: haproxy.log     │
   └────────────────┬────────────────────────┘
                    │ S3 PutObject (per-prefix scoped IAM)
                    ▼
       ┌───────────────────────────┐
       │  AWS pipeline             │
       │                           │
       │  S3  →  Ingest Lambda     │
       │   (bidirectional          │
       │    timestamp-window       │
       │    correlation +          │
       │    MaxMind GeoLite2)      │
       │           ↓               │
       │  DynamoDB (single table)  │
       │           ↓               │
       │  Aggregator Lambda        │
       │  (DDB Streams +           │
       │   EventBridge crons)      │
       │           ↓               │
       │  API Lambda + API Gateway │
       │           ↓               │
       │  CloudFront + ACM         │
       │           ↓               │
       │  React SPA                │
       └───────────────────────────┘
                    ▼
          dashboard.dram-soc.org
```

## Live verification

End-to-end correlation has been verified against real attacker traffic:

- The reverse-tunnel + correlation rewrites the Cowrie-side `127.0.0.1` source IP back to the originating internet IP via the HAProxy log line and a 500ms timestamp window. (Originally 200ms; widened after measuring real-traffic handshake-completion latency clustering at 234–275ms — see ADR-010 §"Empirical window-tuning".) Verified end-to-end against test session `ddc63aaac987` (real source IP `104.174.33.78`, AS20001 Charter Communications, US).
- Real-data-driven schema relaxation in `cowrie_schema.py` (`extra="forbid"` → `extra="ignore"`) caught Cowrie 2.x per-version field churn that the synthetic-data path didn't surface (Phase 11A; `cowrie.client.kex` validation errors dropped from 48/hr to 0 within 3 minutes of deploy; first `command` aggregator item — `uname` — appeared within 2 minutes from a real attacker).
- 10 sanitized real-attacker fixtures (one per observed eventid) committed to the test suite under `dashboard/tests/backend/fixtures/real_data/`. `sanitize_for_fixture()` enforces public-repo publishable rules per ADR-005: `password_raw` strip, RFC 5737 doc-IP swap for the maintainer's home IP, geo-zero on country/asn fields. Real attacker IPs are preserved (already public via passive-DNS / threat-intel feeds).

## Tech stack (real, deployed)

| Layer | Components |
|---|---|
| Edge — honeypot | Cowrie SSH/Telnet honeypot (Pi 5) |
| Edge — networking | HAProxy on DigitalOcean droplet, autossh reverse SSH tunnel from Pi |
| Edge — log shipping | fluent-bit on both edges, filesystem-backed buffer (1 GB), gzip+NDJSON, 1-min/8-MB batches |
| AWS — compute | Lambda (3 functions: ingest, aggregator, api) on Python 3.13 |
| AWS — storage | DynamoDB (single-table per ADR-003) + S3 + S3 Versioning |
| AWS — edge / TLS | CloudFront + ACM (custom domain at dashboard.dram-soc.org, apex at dram-soc.org) |
| AWS — API | API Gateway HTTP API |
| AWS — schedules | EventBridge (daily summary, today summary, rank rebuild crons) |
| AWS — secrets | SSM Parameter Store SecureString for MaxMind license |
| AWS — observability | CloudWatch metric filters + alarms + SNS |
| AWS — IAM | OIDC-trusted GitHub Actions deploy role with ADR-011 permission boundary |
| Edge proxy / WAF | Cloudflare proxied DNS (per ADR-007 — no AWS WAF) |
| GeoIP enrichment | MaxMind GeoLite2 Country + ASN (Lambda layer) |
| IaC | Terraform (modular, separate state for human-managed credentials per ADR-011) |
| Frontend | React 18 + Vite + TypeScript + TanStack Query + Tailwind + Recharts (per ADR-004) |
| CI/CD | GitHub Actions: pytest (262 tests), ruff lint+format, terraform validate matrix, tflint, terraform-plan-on-PR, OIDC apply on workflow_dispatch |

## Architecture decision records

Nine ADRs documenting the trade-offs that shaped the design:

| ADR | Decision |
|---|---|
| [001](dashboard/docs/adr/001-data-schema.md) | Cowrie event schema as the canonical data model |
| [002](dashboard/docs/adr/002-log-shipping.md) | Pi → S3 PutObject → Lambda for log shipping |
| [003](dashboard/docs/adr/003-single-table-design.md) | DynamoDB single-table design |
| [004](dashboard/docs/adr/004-frontend-stack.md) | Frontend stack: React 18 + Vite + TS + TanStack Query + Tailwind |
| [005](dashboard/docs/adr/005-password-filtering.md) | Attempted-password dictionary filtering (`<filtered:len=N>` for non-dictionary values) |
| [007](dashboard/docs/adr/007-cloudflare-waf-over-aws-waf.md) | Cloudflare proxied DNS as edge WAF (no AWS WAF) |
| [009](dashboard/docs/adr/009-captured-malware-policy.md) | Captured-malware policy: SHA + URL only, no binary retention |
| [010](dashboard/docs/adr/010-fluent-bit-edge-shippers.md) | fluent-bit on Pi + droplet, timestamp-window correlation (supersedes part of ADR-002) |
| [011](dashboard/docs/adr/011-cicd-permission-boundary.md) | CI/CD permission boundary: human-managed credentials are separate from CI-managed infrastructure |

## CI / CD

Six workflows in [.github/workflows/](.github/workflows/):

- **`dashboard-ci.yml`** — pytest (262 backend tests), ruff lint + format-check, terraform validate (matrix on `environments/dev` + `stacks/edge-shippers-credentials`), tflint. Runs on every PR + push to main under `dashboard/**`.
- **`dashboard-tf-plan.yml`** — On PRs touching `dashboard/infrastructure/**`: OIDC-assumes the deploy role, runs `terraform plan`, posts the output as a PR comment.
- **`dashboard-backend-deploy.yml`** — `workflow_dispatch` only (the auto-trigger flip lands after 5+ clean manual deploys per the Phase 11B-1 design). Builds Lambda zips + GeoIP layer, runs `terraform apply`.
- **`dashboard-frontend-deploy.yml`** — Auto-fires on `dashboard/web/**` changes pushed to main. Vite build, S3 sync (with `--delete`), CloudFront invalidation. The API endpoint is resolved at deploy time via `aws apigatewayv2 get-apis --query "Items[?Name=='dram-soc-api'].ApiEndpoint"` rather than hardcoded — survives API-recreation events.
- **`security-scan.yml`** — gitleaks (secret scanning) + tfsec (IaC) + yamllint + shellcheck. Runs on every PR + push to main, no path filter.
- **`sigma-validate.yml`** — Sigma rule syntax validation. 5 rules at `sigma/rules/` are validated; see "Sigma rules" note in Repository layout.

## Repository layout

```
soc-detection-lab-honeypot/
├── README.md                           # You are here
├── LICENSE                             # MIT
├── dashboard/                          # The deployed, working system
│   ├── functions/                      #   Lambda source: ingest, aggregator, api, shared
│   ├── infrastructure/terraform/       #   IaC (modules + environments/dev + stacks)
│   ├── web/                            #   React SPA (live at dashboard.dram-soc.org)
│   ├── tests/backend/                  #   262 pytest tests
│   ├── scripts/                        #   package_lambdas.py, dictionary build, frontend deploy
│   ├── tools/                          #   Synthetic data generator (used by tests)
│   ├── edge/                           #   fluent-bit configs + HAProxy snippet for Pi/droplet
│   └── docs/                           #   9 ADRs + 11 phase logs + runbooks + PROJECT_PLAN.md
├── sigma/                              # 5 Sigma rules (syntax-validated by CI; not yet
│                                       # deployed against a live SIEM — see Future work)
└── .github/workflows/                  # 6 workflows (above)
```

The top-level `wazuh/`, `elastic/`, `splunk/`, `misp/`, `suricata/`, `zeek/` directories, the `docker-compose.yml`, and the top-level `docs/` are exploration scaffolding from the project's initial homelab-SIEM scoping that was pivoted away from once the AWS-native pipeline took shape. None of those tools are currently running anywhere in the deployed system. The working system is fully contained in `dashboard/`. Cleanup of the unused scaffolding is on the cleanup backlog (see Future work).

## Future work

Roadmap items genuinely under consideration, distinct from features that already exist:

- **Self-hosted SIEM integration** — pipe a copy of the captured sessions into Wazuh / ELK / Splunk for cross-correlation against host-based agents. The top-level scaffolding directories were placeholders for this; not yet deployed. The 5 Sigma rules at `sigma/rules/` would feed into this if/when it lands.
- **Phase 10.5 — deterministic Pi-side SSH relay** — replace `autossh` with a custom `asyncssh` client that establishes the SSH connection itself, eliminating the timestamp-window correlation entirely. Gated on measured ambiguity rate from real traffic; trigger threshold defined in ADR-010.
- **Phase 11C — backend-deploy auto-trigger flip** — once 5+ clean `workflow_dispatch` deploys are banked, flip `dashboard-backend-deploy.yml` to `push: branches: [main]`. Currently 1 of 5.
- **Phase 11D — CloudFront resource manual-only stack** — move CF resource management to a manual-apply stack (mirroring the `edge-shippers-credentials` pattern from ADR-011) to fully resolve the AWS-API-untaggable resource issue (CF OAC and ResponseHeadersPolicy can't carry tags, so the deploy role's mutate-tag-gate becomes a permanent blocker on those resource types).
- **Repo cleanup** — delete the unused homelab-scoping scaffolding directories at the top level (`wazuh/`, `elastic/`, `splunk/`, `misp/`, `suricata/`, `zeek/`, the top-level `docs/`, and `docker-compose.yml`) once the SIEM-integration future-work item is conclusively resolved one way or the other.

## License

MIT — see [LICENSE](LICENSE)

## About

Built by [Desi Ramirez](https://github.com/dram64) — software engineering grad at Cal Poly SLO, working on cloud and security projects in the run-up to a security/SRE role.

Pairs with [Diamond IQ](https://diamond-iq.dram-soc.org) ([repo](https://github.com/dram64/diamond-iq)) — sports analytics platform on the same AWS account that exercises a different shape of the same skills (real-time WebSocket fanout + Bedrock AI inference + multi-source ingestion).

Portfolio: https://dram-soc.org
