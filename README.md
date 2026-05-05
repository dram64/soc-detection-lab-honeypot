# SOC Detection Lab

A multi-tool detection engineering platform combining open-source SIEM, IDS, and threat intelligence systems into a working homelab security operations center. Designed to demonstrate detection engineering, incident response, and security operations skills end-to-end.

## What this demonstrates

- **Multi-SIEM detection engineering** — Wazuh, Elastic Stack (ELK), and Splunk Free running in parallel with custom Sigma rules
- **Network detection** — Suricata IDS with ET Open ruleset and Zeek for traffic metadata analysis
- **Threat intelligence** — MISP (Malware Information Sharing Platform) integrated with detection pipelines
- **Live attacker data** — Cowrie SSH/Telnet honeypot on Raspberry Pi 5 feeding real attack telemetry
- **Detection-as-code** — Sigma rules version-controlled, tested, and converted to platform-specific queries
- **Incident response** — Runbook templates and postmortem framework
- **Security CI** — `tfsec` and `gitleaks` enforced on every push

## Architecture

```
                     ┌─────────────────────────────────────────────┐
                     │           Internet (live attackers)         │
                     └──────────────┬──────────────────────────────┘
                                    │
                                    ▼
                  ┌──────────────────────────────────┐
                  │   Cloudflare Tunnel (no port     │
                  │   forwarding on home router)     │
                  └────────────────┬─────────────────┘
                                   │
                                   ▼
            ┌────────────────────────────────────────────┐
            │  Raspberry Pi 5 — hardened Linux baseline  │
            │  ┌──────────────────────────────────────┐  │
            │  │  Cowrie SSH/Telnet Honeypot          │  │
            │  │  (port 2222, NAT redirect from :22)  │  │
            │  └──────────────┬───────────────────────┘  │
            └─────────────────┼──────────────────────────┘
                              │ JSON logs over filebeat / syslog
                              ▼
       ┌──────────────────────────────────────────────────────┐
       │         SOC Stack (Docker Compose, single host)      │
       │                                                      │
       │  ┌──────────┐  ┌──────────┐  ┌──────────┐            │
       │  │  Wazuh   │  │   ELK    │  │  Splunk  │            │
       │  │  Manager │  │  Stack   │  │   Free   │            │
       │  └────┬─────┘  └────┬─────┘  └────┬─────┘            │
       │       │             │             │                  │
       │       └─────────────┼─────────────┘                  │
       │                     │                                │
       │           ┌─────────▼─────────┐                      │
       │           │  Sigma rules      │                      │
       │           │  (version-ctrl)   │                      │
       │           └─────────┬─────────┘                      │
       │                     │                                │
       │           ┌─────────▼─────────┐                      │
       │           │  MISP threat      │                      │
       │           │  intel platform   │                      │
       │           └───────────────────┘                      │
       │                                                      │
       │  Network sensors:                                    │
       │  ┌──────────┐  ┌──────────┐                          │
       │  │ Suricata │  │   Zeek   │                          │
       │  └──────────┘  └──────────┘                          │
       └──────────────────────────────────────────────────────┘
                              │
                              ▼
                ┌─────────────────────────────┐
                │  Analyst dashboards:        │
                │  - Wazuh UI (alerting)      │
                │  - Kibana (hunting)         │
                │  - Splunk (cross-search)    │
                └─────────────────────────────┘
```

See [`docs/architecture.md`](docs/architecture.md) for component details and data flow diagrams.

## Tech stack

| Layer | Tool | Version | Purpose |
|---|---|---|---|
| SIEM | Wazuh | 4.7.x | Host-based detection, file integrity, primary alert pipeline |
| SIEM | Elasticsearch + Kibana + Logstash | 8.11.x | Log search, visualization, threat hunting |
| SIEM | Splunk Free | 9.x | Cross-platform comparison, ad-hoc search |
| Network IDS | Suricata | 7.x | Inline + IDS-mode network detection (ET Open ruleset) |
| Network metadata | Zeek | 6.x | Connection logs, protocol analysis |
| Honeypot | Cowrie | 2.x | SSH/Telnet attacker capture |
| Threat intel | MISP | 2.4.x | IOC ingestion, threat-feed correlation |
| Detection-as-code | Sigma | 0.20.x | Platform-agnostic detection rules |
| Orchestration | Docker Compose | 2.x | Local stack management |
| OS (sensor) | Raspberry Pi OS Lite | 12 (Bookworm) | Hardened baseline on the Pi |

## Quick start

### Prerequisites

- Docker 24+ and Docker Compose v2
- 16 GB RAM minimum, 32 GB recommended (Wazuh + ELK + Splunk together are heavy)
- 100 GB free disk for log retention
- Linux/macOS host (Windows works via WSL2)
- Raspberry Pi 5 (optional — for live honeypot data; lab works with synthetic data otherwise)

### Bring up the stack

```bash
git clone https://github.com/dram64/soc-detection-lab.git
cd soc-detection-lab

# Generate self-signed certs and starter passwords
./scripts/setup.sh

# Bring up all services
docker compose up -d

# Watch services come up (Wazuh + ELK take ~3-5 min on first boot)
docker compose ps
docker compose logs -f wazuh-manager elasticsearch
```

### Verify each tool

| Tool | URL | Default credentials |
|---|---|---|
| Wazuh dashboard | https://localhost:443 | `admin / SecretPassword` (change on first login) |
| Kibana | http://localhost:5601 | `elastic / changeme` |
| Splunk | http://localhost:8000 | `admin / changeme` |
| MISP | https://localhost:8443 | `admin@admin.test / admin` |

**Important:** Change all default credentials before exposing the lab anywhere. See `docs/hardening.md`.

### Generate synthetic detection events (no honeypot needed)

```bash
./scripts/generate-test-events.sh
# Watch alerts appear in Wazuh dashboard
```

### Connect the Pi honeypot (optional)

See [`docs/honeypot-setup.md`](docs/honeypot-setup.md) for the full Pi 5 hardening + Cowrie + Cloudflare Tunnel walkthrough.

## Repository layout

```
soc-detection-lab/
├── README.md                           # You are here
├── docker-compose.yml                  # Full stack
├── .env.example                        # Configurable defaults
├── scripts/
│   ├── setup.sh                        # First-run setup
│   ├── generate-test-events.sh         # Synthetic event generation
│   └── teardown.sh                     # Clean shutdown + volume removal
├── wazuh/
│   ├── ossec.conf                      # Wazuh manager config
│   ├── decoders/                       # Custom log decoders
│   │   ├── cowrie_decoder.xml
│   │   └── suricata_decoder.xml
│   ├── rules/                          # Custom Wazuh rules
│   │   ├── 100100-cowrie.xml
│   │   ├── 100200-suricata-correlation.xml
│   │   └── 100300-misp-correlation.xml
│   └── integrations/
│       └── misp-lookup.py              # MISP IOC enrichment
├── elastic/
│   ├── logstash.conf                   # Pipeline config
│   ├── pipelines/
│   │   ├── cowrie-pipeline.conf
│   │   └── suricata-pipeline.conf
│   └── kibana-saved-objects.ndjson     # Pre-built dashboards
├── splunk/
│   ├── apps/
│   │   └── soc-detection/              # Custom app with searches
│   └── conf/
│       └── inputs.conf
├── sigma/
│   ├── README.md
│   ├── rules/
│   │   ├── ssh_brute_force.yml
│   │   ├── credential_stuffing.yml
│   │   ├── lateral_movement_smb.yml
│   │   ├── known_bad_ip_match.yml
│   │   └── unusual_outbound_ports.yml
│   └── tests/                          # Rule unit tests
├── suricata/
│   ├── suricata.yaml
│   └── custom-rules/
│       └── local.rules
├── zeek/
│   └── local.zeek
├── misp/
│   └── feeds.json                      # Curated threat feeds
├── docs/
│   ├── architecture.md
│   ├── honeypot-setup.md               # Pi 5 hardening + Cowrie + Cloudflare Tunnel
│   ├── hardening.md                    # Lab hardening before exposure
│   ├── detection-engineering.md        # How rules are written + tested
│   ├── runbooks/
│   │   ├── ssh-brute-force.md
│   │   ├── credential-stuffing.md
│   │   └── lateral-movement.md
│   └── postmortem-template.md
├── ci/
│   ├── tfsec.yml                       # IaC security scanning
│   └── gitleaks.toml                   # Secret scanning
└── .github/workflows/
    ├── security-scan.yml               # tfsec + gitleaks on every push
    └── sigma-validate.yml              # Sigma rule syntax check

```

## Detection coverage

Currently shipping rules for the following MITRE ATT&CK tactics:

| Tactic | Technique | Rule |
|---|---|---|
| Initial Access | T1110 — Brute Force | `sigma/rules/ssh_brute_force.yml` |
| Initial Access | T1110.004 — Credential Stuffing | `sigma/rules/credential_stuffing.yml` |
| Lateral Movement | T1021.002 — SMB/Windows Admin Shares | `sigma/rules/lateral_movement_smb.yml` |
| Command & Control | T1071 — Application Layer Protocol | `sigma/rules/unusual_outbound_ports.yml` |
| Reconnaissance | T1595 — Active Scanning | Wazuh + Suricata correlation rule |

Coverage matrix and detection logic notes: [`docs/detection-engineering.md`](docs/detection-engineering.md).

## CI / security

Every commit runs:

- **`tfsec`** — Terraform/IaC scanning for misconfigurations
- **`gitleaks`** — Secret scanning to prevent credential leaks
- **`sigma-cli`** — Detection rule syntax validation

See [`.github/workflows/`](.github/workflows/) for the CI configuration.

## Roadmap

- [ ] Active response / SOAR primitives (auto-block IPs at firewall on high-severity alerts)
- [ ] TheHive integration for case management
- [ ] Live YARA scanning on captured malware samples
- [ ] Kubernetes deployment for resilient multi-node setup
- [ ] Wazuh-to-Slack alert routing for on-call simulation

## License

MIT — see [`LICENSE`](LICENSE)

## About

Built by [Z](https://github.com/dram64) as part of a self-directed cloud security and detection engineering portfolio. Pairs with [Diamond IQ](https://github.com/dram64/diamond-iq) (production AWS cloud project) to demonstrate end-to-end engineering across both detection/SOC operations and cloud architecture.
