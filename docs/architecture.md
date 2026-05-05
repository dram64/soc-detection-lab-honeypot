# Architecture

## Design principles

1. **Multi-SIEM by intent.** Running Wazuh, ELK, and Splunk in parallel demonstrates detection portability and tool-agnostic engineering. Sigma rules sit at the top, converted to platform-specific queries via `sigma-cli`.

2. **Detection-as-code.** All detection logic lives in Git. No clicking through dashboards to build queries. Rules are version-controlled, reviewable, testable, and deployable via CI.

3. **Real attacker data via honeypot.** Synthetic test data is useful for development, but real attacker behavior from a Cowrie honeypot exposed via Cloudflare Tunnel demonstrates production-shaped detection engineering.

4. **Correlation over isolated alerts.** Single-signal alerts have high false-positive rates. Correlation rules (e.g., Wazuh `100210` — IP attacking honeypot AND triggering Suricata IDS) demonstrate higher-confidence detection.

5. **Containment via runbook.** Every alert has a runbook. The runbooks in `docs/runbooks/` translate "rule fired" into "what does Tier 1 do for the next 5/15/30 minutes."

## Data flow

### Honeypot → SIEM (live attackers)

```
Internet attacker
    ↓ SSH/Telnet on port 22 (NAT redirect to 2222 internally)
Raspberry Pi 5 (hardened, no inbound except via Cloudflare Tunnel)
    ↓ Cowrie writes JSON events to /var/log/cowrie/cowrie.json
    ↓ filebeat tails the JSON file
    ↓ filebeat ships to Logstash (5044/tcp) and Wazuh (514/udp via syslog)
ELK indexes for hunting
Wazuh alerts via custom rules (100100-100199)
    ↓ Triggers correlation if Suricata also alerted (100210)
Wazuh dashboard surfaces alert
```

### Network sensors → SIEM (perimeter traffic)

```
Network traffic
    ↓ Span port / inline capture
Suricata IDS analyzes packets against ET Open ruleset + custom rules
    ↓ JSON alerts to /var/log/suricata/eve.json
    ↓ filebeat → Logstash → Elasticsearch
    ↓ syslog → Wazuh manager (514/udp)
Zeek captures connection metadata in parallel
    ↓ logs to /usr/local/zeek/logs/
    ↓ filebeat → Logstash → Elasticsearch
Both feed correlation engine in Wazuh
```

### Threat intel → detection enrichment

```
MISP threat-intel platform
    ↓ Curated feeds (MISP project, Abuse.ch, DigitalSide, etc.)
    ↓ Refreshed every 6 hours via cron
    ↓ MISP API exposes IOCs
Wazuh integration: misp-lookup.py
    ↓ Per-event lookup of src_ip / dest_ip against MISP IOC DB
    ↓ If match: enrich event with misp.event_id, misp.threat_level
Wazuh rule 100300 fires on enriched events
ELK searches against misp-iocs index for threat hunting
```

### Sigma → multi-platform deployment

```
sigma/rules/*.yml (the canonical detection)
    ↓ sigma-cli convert -t splunk
Splunk savedsearches.conf
    ↓ sigma-cli convert -t elasticsearch
Kibana / Elasticsearch detection rule
    ↓ sigma-cli convert -t wazuh
Wazuh local rule XML
```

This pattern means: write the rule once, deploy it in Wazuh + ELK + Splunk simultaneously. CI validates syntax on every push.

## Component responsibilities

### Wazuh (primary SIEM)

- Host-based intrusion detection (HIDS)
- File integrity monitoring (FIM) on the SOC stack itself
- Real-time alerting via custom rules
- Active response capability (auto-block on high-severity alerts — enable carefully)
- MITRE ATT&CK mapping on every rule
- Acts as the canonical "alerting" tool

### Elastic Stack (hunting + visualization)

- Long-term log retention (90 days hot, 365 days warm via ILM)
- Threat hunting via Kibana KQL
- Custom dashboards per detection category
- Suricata + Zeek metadata search
- MISP IOC lookups via search

### Splunk Free (cross-tool comparison)

- Demonstrates portability of Sigma rules
- 500 MB/day free tier limit (sufficient for honeypot data)
- Used as a "third opinion" — when Wazuh and ELK disagree, Splunk acts as tiebreaker

### Suricata (network IDS)

- Inline + IDS-mode packet inspection
- ET Open ruleset (~50K signatures)
- Custom rules in `suricata/custom-rules/local.rules`
- JSON event output via EVE format

### Zeek (network metadata)

- Connection logs (conn.log)
- Protocol analysis (http.log, dns.log, ssl.log, etc.)
- Asset discovery via passive observation
- Complements Suricata: Suricata = "did this match a signature," Zeek = "what happened on the wire"

### Cowrie (SSH/Telnet honeypot)

- Captures attacker keystrokes, credentials, commands
- Records full TTY sessions
- File upload sandbox (catches malware drops)
- Provides real-world detection test data

### MISP (threat intelligence)

- IOC ingestion from public + private feeds
- Sharing community for SOC-to-SOC IOC exchange
- Provides lookup data for Wazuh + ELK enrichment
- Acts as case management for IOCs Diamond IQ team contributes

## Hardware sizing (homelab scale)

| Component | RAM | Disk | CPU |
|---|---|---|---|
| Wazuh manager + indexer + dashboard | 8 GB | 50 GB | 2 cores |
| Elastic stack (ES + Kibana + Logstash) | 6 GB | 50 GB | 2 cores |
| Splunk Free | 4 GB | 20 GB | 1 core |
| MISP + MySQL | 4 GB | 10 GB | 1 core |
| Suricata + Zeek | 2 GB | 30 GB | 2 cores |
| Filebeat (lightweight) | 256 MB | 1 GB | shared |
| **Total** | **~24 GB** | **~160 GB** | **8 cores** |

Recommended host: 32 GB RAM, 250 GB SSD, modern 8-core CPU.

The Raspberry Pi 5 runs only Cowrie + filebeat (1 GB RAM is sufficient).

## Production-vs-homelab gaps

This is a homelab, not a production SOC. Production-grade differences would include:

- **Multi-node cluster** — Wazuh/Elastic in HA mode (3+ master nodes, dedicated indexer pool, dedicated dashboard nodes)
- **Hot/warm/cold storage tiering** — ILM policies pushing old data to cheaper storage
- **Dedicated network segments** — SOC stack on its own VLAN, restricted ingress
- **Active response with full SOAR** — TheHive + Cortex + Shuffle for case management and orchestration
- **Compliance integrations** — CIS benchmarks, PCI-DSS audits, SOC2 controls
- **24/7 staffing** — Tier 1/2/3 analyst rotation with clear escalation paths

The lab demonstrates the engineering discipline; the gaps would be filled in a production environment.
