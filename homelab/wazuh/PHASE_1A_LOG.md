# Phase 1A — Wazuh single-node SIEM on Pi 5

**Status:** 🟡 IN PROGRESS — blocked at Step 4 (`docker compose up -d`).
**Session date:** 2026-05-08
**Goal:** Deploy a working Wazuh SIEM on the existing honeypot Pi 5, ingesting Cowrie logs, with detections firing on real attacker traffic. Resume keywords this legitimizes (once shipped): Wazuh, SIEM operations, detection engineering, threat detection, log analysis, incident response.

## Why this matters

The SOC Detection Lab repo's prior README (rewritten 2026-05-07, SHA 6fe9d28) explicitly excluded SIEM keyword claims as aspirational. Phase 1A is the work that backs them up. **Until Phase 1A is shipped, do not add Wazuh / SIEM / detection-engineering claims to the top-level README, the resume, or the portfolio site.**

## Hard constraints (carried throughout this session)

1. SOC pipeline (`cowrie.service`, `soc-fluent-bit.service`, `soc-tunnel.service`) MUST stay live throughout. The dashboard at https://dashboard.dram-soc.org must remain functional. fluent-bit must continue shipping cowrie.json to S3 uninterrupted.
2. If any deploy step breaks the SOC pipeline, halt and rollback immediately.
3. Wazuh runs in Docker on the Pi (NOT k3s — that's Phase 1D, separate workstream).
4. Strict memory limits to prevent OOM-killing Cowrie (kernel ignored these — see "Backlog" in README.md).

## Steps shipped

### Gate 1 — pre-flight assessment ✅

- Pi 5 baseline: 7.8Gi RAM (6.6 Gi free), 117G disk (105G free), 4 cores aarch64, Debian trixie kernel 6.12.75
- SOC pipeline confirmed healthy: cowrie.service uptime 1d 14h, soc-fluent-bit shipping every 10s, soc-tunnel.service active
- Cowrie listens on `0.0.0.0:2223` (NOT 2222); reverse tunnel forwards droplet:22 → Pi:2223
- 611 Cowrie objects in S3 confirming end-to-end pipeline live
- Docker NOT installed (prerequisite identified); jackal sudo requires password

### Step 1 — Docker install ✅

- `docker-ce 5:29.4.3`, `containerd.io 2.2.3`, compose plugin `v5.1.3` — all from Docker's official bookworm repo (using bookworm packages on trixie host; standard pattern at this point in the trixie-rollout cycle)
- jackal added to docker group
- `vm.max_map_count=262144`, `vm.swappiness=1` applied + persisted to `/etc/sysctl.d/99-wazuh.conf`
- Docker daemon `enabled` + `active`
- Verified: `hello-world` ran sans sudo, `docker version` reports 29.4.3

### Step 2 — Deploy directory + certificates ✅

- `/opt/wazuh-deploy/` created (jackal:jackal owned)
- `README.md` written FIRST (before any cert work) with full deployment guide, rollback procedure, version drift notes
- `generate-indexer-certs.yml` + `config/certs.yml` pulled from upstream v4.14.5 ref
- Cert generator ran cleanly via `docker compose -f generate-indexer-certs.yml run --rm generator`
- **12 PKI artifacts generated** (not 9 as initially estimated — there are TWO root CAs: cluster root + separate manager root)
- Important UID-collision noted: manager-side certs appear owned by `fluent-bit:systemd-journal` on host. UID coincidence (the wazuh user inside the container has the same numeric UID as fluent-bit on the host). Safe currently because the dir is `dr-x------` (root only); fluent-bit cannot traverse in. **DO NOT loosen permissions on `wazuh_indexer_ssl_certs/`** — fluent-bit (a SOC pipeline service) would gain unintended access to manager TLS keys.

### Step 3 — `.env` + customized `docker-compose.yml` + canonical configs ✅

- `.env` generated (eventually) with 32-char passwords meeting Wazuh's policy + our constraint set (see "Failure mode 2" below for what we ruled out before landing on the Python `secrets` generator)
- 5 canonical config files pulled from upstream v4.14.5 ref:
  `wazuh.indexer.yml`, `internal_users.yml`, `opensearch_dashboards.yml`, `wazuh.yml`, `wazuh_manager.conf`
- Customized `docker-compose.yml` written:
  - Dashboard bound to `127.0.0.1:5601` only (not LAN)
  - Manager + indexer ports NOT published (docker-internal only)
  - `mem_limit` per container: 1g manager, 1.5g indexer, 768m dashboard (kernel ignored — see Backlog)
  - Passwords sourced from `.env` via `${VAR}` substitution
- Verified compose YAML parses cleanly; dashboard `host_ip: 127.0.0.1` confirmed via `docker compose config --format json`

## Steps blocked

### Step 4 — `docker compose up -d` ❌ — three distinct failure modes in one step

#### Failure mode 1 — `Error 5007 - Insecure user password`

- Generated passwords via `openssl rand -base64 24 | tr -d "/+="` — pure alphanumeric (A-Za-z0-9)
- Wazuh manager's `create_user.py` rejected with `WazuhError 5007 - Insecure user password provided`
- Manager `cont-init` aborted, container fell into restart loop
- **Root cause:** Wazuh's password policy requires ≥1 special character; base64-stripped output had none

#### Failure mode 2 — `${N}` interpolation + `JSONDecodeError: Invalid \escape`

- Regenerated via `< /dev/urandom tr -dc 'A-Za-z0-9!@#$%^&*+-_' | head -c 32`
- Two breakages compounded:
  - **Docker compose interpolation:** charset included `$`. When `.env` value contained `$N`, docker compose silently substituted `${N}` (unset) → empty string. Password reaching the container ≠ password in `.env` — silent mutation.
  - **JSON encoding:** `tr` interpreted `+-_` as ASCII range 0x2B–0x5F, which silently includes `\`. Manager's `create_user.py` writes the password to a JSON file, then re-reads via `json.load()`. Backslash in password → invalid `\X` escape sequence → `JSONDecodeError: Invalid \escape: line 3 column 44 (char 72)` → restart loop.
- **Root cause:** the `tr -dc` charset was hostile to both docker compose (silent `$X` interpolation) and Python's JSON parser (strict escape validation). Required a much narrower alphabet.

#### Failure mode 3 — TLS cert chain mismatch

- Switched to Python `secrets`-based generator with explicit safe alphabet (`!@#%^&*_-` only — no `$ \ ` " ' = < > ?`)
- Passwords clean — no Error 5007, no JSONDecodeError, no `${N}` warnings
- Stack stayed UP for 5 min (no restart loop!)
- BUT: manager's filebeat → indexer connection failed:
  - `x509: certificate is valid for demo.indexer, not wazuh.indexer`
- Cert forensics confirmed our certs ARE correctly issued for `wazuh.indexer`, `wazuh.manager`, `wazuh.dashboard`:
  - Verified via `docker run --rm alpine/openssl x509 -noout -subject -ext subjectAltName` against each cert
  - All subjects + SANs are correct
- **Root cause (best diagnosis):** The indexer is presenting a self-generated **demo cert** as a fallback because something in our customized mount paths or our `wazuh.indexer.yml` config doesn't align with what the indexer expects. OpenSearch has a "demo certificates" fallback mode that activates when configured certs aren't found at expected paths — that's likely what's happening. The dashboard's `[ConnectionError]: unable to verify the first certificate` is a downstream cascade from the same root.

### Step 5 — Health verification + admin password rotation

Blocked. Cannot run `securityadmin` or `wazuh-passwords-tool.sh` until stack is healthy.

### Step 6 — ISM policy

Blocked. Cannot apply ISM policy until indexer + dashboard auth chain works.

## Resolution path for next session — Option B

**Drop ALL customizations from `docker-compose.yml`. Run upstream v4.14.5 single-node manifest UNMODIFIED.**

The hypothesis: our customizations (port bindings, mem_limits, env-file passwords, possibly the mount paths themselves) introduced the cert breakage. Proving unmodified upstream works first isolates whether the issue is our customization OR environmental.

### Procedure

1. **Wipe state cleanly:**

   ```bash
   cd /opt/wazuh-deploy
   docker compose down -v          # remove containers + volumes (volumes already wiped this session, but safe to re-run)
   sudo rm -rf config/wazuh_indexer_ssl_certs/   # remove old certs
   ```

2. **Replace customized compose with verbatim upstream:**

   ```bash
   curl -fsSL -O https://raw.githubusercontent.com/wazuh/wazuh-docker/v4.14.5/single-node/docker-compose.yml
   ```

   Note: upstream uses hardcoded passwords (`SecretPassword`, `MyS3cr37P450r.*-`, `kibanaserver`). Accept this for the unmodified test — we're proving the deploy path, not security. Will harden after it works.

3. **Re-run cert generator:**

   ```bash
   docker compose -f generate-indexer-certs.yml run --rm generator
   ```

4. **Bring up:**

   ```bash
   docker compose up -d
   ```

5. **Wait 5 min, check:**
   - `docker compose ps` — all 3 Up
   - Manager logs — no `x509` errors connecting to indexer
   - Dashboard logs — no `ConnectionError` verifying cert
   - Browse `https://localhost:5601` (after `ssh -L 5601:127.0.0.1:5601 pi-honeypot`) — login as `admin` / `SecretPassword`

### If unmodified upstream WORKS

Layer customizations back one at a time, deploying between each:

1. Localhost-only port binding (dashboard `5601` → `127.0.0.1`)
2. Memory limits (kernel ignores them anyway, but compose accepts; verify no behavior regression)
3. Env-file passwords (the breakage point of attempts 1 + 2 — use the Python `secrets` generator)
4. Mount path adjustments (suspected breakage point of attempt 3 — needs careful comparison vs upstream defaults)

Whichever step breaks the deploy is the customization at fault. That's the precise diagnosis.

### If unmodified upstream ALSO fails

Environmental issue — Pi 5 / arm64 / Debian trixie / Docker 29.4.3 / compose v5 may have an incompatibility with Wazuh 4.14.5 single-node. Options:

- Try Wazuh 4.14.3 or 4.14.4 (last 2 versions also have arm64 image support)
- Switch to a different SIEM stack: Graylog (similar feature set, often easier on Pi-class hardware) or ELK
- Defer the entire workstream and pick up an alternate next-workstream candidate (e.g. homelab-scaffolding cleanup commit per `dashboard/docs/RESUME_HERE.md` §6.5)

## SOC pipeline status — UNTOUCHED throughout

All 3 SOC services confirmed `active` at every checkpoint across all 3 deploy attempts:

- `cowrie.service` — uptime > 1d 14h across the entire session
- `soc-fluent-bit.service` — shipping S3 every 10s
- `soc-tunnel.service` — reverse tunnel up

**No regression on the production SOC pipeline.** The whole point of the halt-and-rollback discipline.

## State left on the Pi

| Path / artifact | State |
|---|---|
| `/opt/wazuh-deploy/` | Exists, jackal:jackal. Contains: `README.md` (308 lines), `.env` (mode 0600, 3 working passwords from Python generator), customized `docker-compose.yml`, `generate-indexer-certs.yml`, `config/` (12 cert files + 5 canonical configs) |
| Docker images | 4 images cached (~7 GB total): `wazuh-manager:4.14.5`, `wazuh-indexer:4.14.5`, `wazuh-dashboard:4.14.5`, `wazuh-certs-generator:0.0.4` |
| Docker volumes | wiped (`down -v` after retry #2) |
| Docker network | wiped |
| Docker daemon | enabled, active |
| Kernel sysctls | `vm.max_map_count=262144`, `vm.swappiness=1` persistent in `/etc/sysctl.d/99-wazuh.conf` |
| jackal docker group | added |

**Do not modify any of this until the next session decides on resume-from-state vs full wipe.**

## Resume-claims policy

DO NOT add Wazuh / SIEM / detection-engineering / threat-detection / log-analysis / incident-response keyword claims to:

- Top-level `README.md` (`soc-detection-lab-honeypot/README.md`)
- Resume document
- Portfolio site (`https://dram-soc.org`)
- LinkedIn profile

Until Phase 1A is closed (deploy verified working AND attack data flowing through to dashboard with detections firing).

## Backlog deferred from this session

- **Enable cgroup memory accounting on Pi.** Add `cgroup_enable=memory cgroup_memory=1` to `/boot/firmware/cmdline.txt` and reboot. Currently `mem_limit` settings in compose are silently ignored by the kernel ("Your kernel does not support memory limit capabilities or the cgroup is not mounted. Limitation discarded"). Not blocking; defer until Phase 1B (which adds the wazuh-agent + may push memory usage higher). Requires ~1 min of Pi downtime for the reboot.
