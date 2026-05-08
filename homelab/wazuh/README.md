# Wazuh Single-Node SIEM — Deploy Notes

**Deployed:** 2026-05-08
**Wazuh version:** 4.14.5 (linux/arm64)
**Host:** Pi 5 honeypot (jackal user)
**Phase:** 1A iteration 1 (deploy verification only — no Cowrie integration yet)

## What this is

A single-node Wazuh SIEM (manager + indexer + dashboard) running in Docker on the
honeypot Pi, alongside the existing SOC pipeline (Cowrie + fluent-bit + reverse
tunnel). This is iteration 1: deploy + health-verify only. Iteration 2 will add
Cowrie log integration, custom decoders, and detection rules.

Context:
- `dashboard/docs/PROJECT_PLAN.md` (in soc-detection-lab repo) for project context
- `dashboard/docs/RESUME_HERE.md` §6.5 for next-workstream candidates

## Components

| Service | Image | Port (host-side) | Memory limit |
|---|---|---|---|
| Manager | wazuh/wazuh-manager:4.14.5 | none (docker-internal) | 1Gi |
| Indexer | wazuh/wazuh-indexer:4.14.5 | none (docker-internal) | 1.5Gi |
| Dashboard | wazuh/wazuh-dashboard:4.14.5 | **127.0.0.1:5601** (loopback only) | 768Mi |

## Start / stop / inspect

```bash
cd /opt/wazuh-deploy
docker compose up -d            # start
docker compose down             # stop (preserves data volumes)
docker compose ps               # container state
docker compose logs -f          # tail all logs
docker compose logs -f wazuh.indexer    # tail one service
```

## Dashboard access

The dashboard is bound to **127.0.0.1:5601 only** — not LAN, not internet.
From your workstation:

```bash
# from Windows / Mac / Linux
ssh -L 5601:127.0.0.1:5601 pi-honeypot
# then in browser:  https://localhost:5601
# accept the self-signed cert warning (Wazuh ships with self-signed)
# user:     admin
# password: see "Passwords" section below
```

## Passwords

All passwords live in `/opt/wazuh-deploy/.env` (mode 0600, jackal:jackal).

| Variable | Used for |
|---|---|
| `WAZUH_ADMIN_PASSWORD` | **Dashboard login as `admin`** — this is what you want |
| `INDEXER_PASSWORD` | Manager + Dashboard service-to-service auth to indexer |
| `API_PASSWORD` | Wazuh manager API (used by dashboard) |
| `DASHBOARD_PASSWORD` | Internal `kibanaserver` service account |

Read with:
```bash
grep WAZUH_ADMIN_PASSWORD /opt/wazuh-deploy/.env
```

To rotate the admin password later, run the in-cluster password tool:
```bash
docker compose exec wazuh.manager bash /var/ossec/integrations/wazuh-passwords-tool.sh \
  -u admin -p <new_password>
# then update .env so future-you can find the new value
```

### Password generation

Generating passwords for this stack is harder than it looks. Wazuh's manager,
docker compose's .env parser, and Python's JSON serializer each impose disjoint
character constraints; satisfying all three requires an explicit, narrow alphabet.

**The approved generator (Python `secrets`-based, policy-verified):**

```python
"""Generate Wazuh-compatible password."""
import secrets, string

SAFE_SPECIALS = "!@#%^&*_-"
ALPHABET = string.ascii_letters + string.digits + SAFE_SPECIALS

def generate():
    while True:
        pw = "".join(secrets.choice(ALPHABET) for _ in range(32))
        if any(c in SAFE_SPECIALS for c in pw):  # Wazuh policy
            return pw
```

Length 32. Alphabet 71 chars (62 alphanumeric + 9 safe specials). Loops until at
least one special is present (P(no-special after 32 draws) ≈ 1.3%).

**Why this exact alphabet — every excluded character has a reason:**

| Char | Reason for exclusion |
|---|---|
| `$` | Docker compose interpolates `$X` in `.env` values as `${X}`. If `X` is unset, the `$X` substring is silently deleted from the password before reaching the container. We hit this on Step 4 retry #1 — DASHBOARD_PASSWORD contained `$N`, compose deleted it, container saw a different password than .env contained, JSON parse failed downstream. |
| `\` | Wazuh's `create_user.py` writes the API password into a JSON file, then re-reads it via `json.load()`. Backslashes in the password become `\X` escape sequences; if X isn't a valid JSON escape (`n t r " \\ uXXXX`), `json.decoder.JSONDecodeError: Invalid \escape` aborts the manager's `cont-init` and the container falls into a restart loop. Hit this on Step 4 retry #1 — both API_PASSWORD and DASHBOARD_PASSWORD contained `\` (came in via the `tr` `+-_` range expansion). |
| `` ` `` | Backticks trigger command substitution in shell contexts. Avoided as defense-in-depth even though docker compose itself doesn't shell-parse .env values. |
| `"`, `'` | Quote characters can break shell quoting if a password is ever copy-pasted into a `docker exec` command, curl call, or API client. Avoided. |
| `=` | The `.env` file format is `KEY=VALUE`. A `=` in the value technically works (parsers split on first `=`), but creates ambiguity for downstream tooling. Avoided. |
| `<`, `>` | Shell redirection operators. If a password is interpolated into a shell command without quoting, `<` and `>` become file-redirect requests. Defense-in-depth. |
| `?`, `*`, `[`, `]`, `{`, `}` | Glob/wildcard chars. `*` IS allowed in our SAFE_SPECIALS because Wazuh's policy explicitly accepts it and `bash` only globs *unquoted* values; we always quote. The others are excluded. |
| `+`, `.`, `,`, `/`, `:`, `;`, `(`, `)`, `\|`, `~` | Excluded from this alphabet but not strictly hazardous. The principle here is "smallest workable alphabet" — fewer chars = less surface for unexpected interactions in the Wazuh / docker / shell pipeline. |

**The 9 safe specials in the kept set — `! @ # % ^ & * _ -` — are individually
shell-safe (when quoted), JSON-safe (no escape required), and env-file-safe (no
value-format ambiguity).**

**Wazuh password policy** (manager-side, enforced in
`/var/ossec/framework/scripts/create_user.py`):

- Length ≥ 8
- ≥ 1 special character (any of `. * ? ! " # $ % & ' ( ) , : ; < = > @ [ \ ] ^ _ { | } ~ /`)
- Failure raises `wazuh.core.exception.WazuhError: Error 5007 - Insecure user
  password provided`. Surfaces as a manager `cont-init` failure → restart loop.

**To rotate any password:**

```bash
cd /opt/wazuh-deploy
docker compose down
# (regenerate via the Python generator above; write to .env mode 0600)
docker compose up -d
# wait ~3 min, verify dashboard login + manager API still work
```

## Rollback — if Cowrie / fluent-bit / tunnel destabilizes

If the Wazuh stack appears to be impacting the SOC pipeline (RAM exhaustion,
disk pressure, anything destabilizing `cowrie.service`, `soc-fluent-bit.service`,
or `soc-tunnel.service`), execute in order:

```bash
# 1. STOP Wazuh stack — preserves data volumes for diagnosis
cd /opt/wazuh-deploy
docker compose down

# 2. Verify SOC pipeline still healthy
systemctl is-active cowrie.service soc-fluent-bit.service soc-tunnel.service
# expected: active / active / active

# 3. Confirm freed resources
free -h
docker ps        # should be empty
```

If issues persist after `docker compose down`, the cause is NOT Wazuh —
investigate the SOC services directly via `journalctl -u <service>`.

## Full purge — wipe Wazuh data + reset for clean redeploy

```bash
cd /opt/wazuh-deploy
docker compose down -v          # removes named volumes (Wazuh data lost)
docker image rm wazuh/wazuh-manager:4.14.5 \
                wazuh/wazuh-indexer:4.14.5 \
                wazuh/wazuh-dashboard:4.14.5 \
                wazuh/wazuh-certs-generator:0.0.4
sudo rm -rf /opt/wazuh-deploy
```

## Uninstall Docker entirely (only if decommissioning the experiment)

```bash
sudo systemctl stop docker docker.socket
sudo apt-get purge -y docker-ce docker-ce-cli containerd.io \
                      docker-buildx-plugin docker-compose-plugin
sudo rm -rf /var/lib/docker /var/lib/containerd /etc/docker
sudo gpasswd -d jackal docker
sudo rm /etc/sysctl.d/99-wazuh.conf
sudo sysctl -w vm.max_map_count=65530    # back to default
sudo sysctl -w vm.swappiness=60          # back to default
```

## Certificates

The cert generator produces 12 PKI artifacts in `config/wazuh_indexer_ssl_certs/`,
all mode `400` (read-only by owner). Generated 2026-05-08:

| File pair | Purpose |
|---|---|
| `root-ca.pem` / `root-ca.key` | Cluster root CA (signs indexer + dashboard + admin certs) |
| `root-ca-manager.pem` / `root-ca-manager.key` | **Separate** root CA for the manager (intentional split per upstream design) |
| `admin.pem` / `admin-key.pem` | Cluster admin user (used by Wazuh's password-rotation tooling) |
| `wazuh.indexer.pem` / `wazuh.indexer-key.pem` | Indexer node TLS |
| `wazuh.dashboard.pem` / `wazuh.dashboard-key.pem` | Dashboard node TLS |
| `wazuh.manager.pem` / `wazuh.manager-key.pem` | Manager (filebeat → indexer) TLS |

To regenerate (e.g. after a year, before expiry):
```bash
cd /opt/wazuh-deploy
sudo rm -rf config/wazuh_indexer_ssl_certs/
docker compose -f generate-indexer-certs.yml run --rm generator
docker compose down && docker compose up -d
```

## Known operational gotcha — UID collision on cert files

Inside `config/wazuh_indexer_ssl_certs/`, the manager-side cert files
(`root-ca-manager.*`, `wazuh.manager.*`) appear on the host owned by
`fluent-bit:systemd-journal` rather than `jackal:jackal` or `root:root`.

**This is NOT actually fluent-bit owning the files.** It's a UID/GID number
coincidence — inside the wazuh-manager container, the same numeric UID maps
to the `wazuh` user. The cert generator chowned the files to that container
UID; the host happens to assign that same numeric UID to fluent-bit (which
was created when fluent-bit was installed earlier for the SOC pipeline).

**Why this is currently safe:** the parent dir `wazuh_indexer_ssl_certs/` is
`dr-x------` (root-only). fluent-bit cannot traverse into it, so even though
it nominally owns 4 files, it cannot reach them.

**DO NOT loosen the permissions on this directory.** If `chmod` is applied to
make the dir group/other traversable, the layering violation becomes real:
fluent-bit (the SOC pipeline service) would gain unintended access to the
Wazuh manager's TLS private keys. The current `dr-x------` is what keeps the
two systems isolated despite the UID collision.

If you need to inspect the cert dir, use `sudo`:
```bash
sudo ls -la /opt/wazuh-deploy/config/wazuh_indexer_ssl_certs/
```

## Untouched services — guaranteed

These are NEVER stopped, restarted, reconfigured, or modified by anything in
this directory or by any `docker compose` operation:

- `cowrie.service` (Cowrie SSH honeypot, listens 0.0.0.0:2223)
- `soc-fluent-bit.service` (fluent-bit ship to s3://dram-soc-honeypot-ingest/raw/cowrie/)
- `soc-tunnel.service` (reverse SSH tunnel to DigitalOcean droplet 209.38.129.19)

If `docker compose down` doesn't restore SOC pipeline health, the issue is
NOT in this directory — look at the SOC services themselves.

## Version drift notes (deploy time: 2026-05-08)

The deploy plan was scoped against expected versions; actual installed versions
differ. None block deploy, but if `docker compose up` or runtime behavior
misbehaves, check these first before assuming a Wazuh-specific issue:

- **Docker Engine 29.4.3** — scoped: "~27.x". Docker is on the 29.x branch as
  of May 2026. Backward compat with the compose v5 plugin is expected.
- **docker compose plugin v5.1.3** — scoped: "v2.x". Plugin numbering jumped
  to v5 generation. Wazuh's official CI matrix tests against v2.x of the plugin.
  Behavior should be compatible but is untested in Wazuh's matrix.
- **Pi OS = Debian trixie (13)**, but the Docker apt repo suite configured is
  `bookworm` (12). Docker doesn't yet ship a `trixie` repo as of 2026-05-08;
  bookworm packages install cleanly on trixie but are technically version-skewed.
  Standard pattern across the Pi community in this transition window.

If a deploy-time issue surfaces and isn't obviously Wazuh-config-related, the
debug starting point is to verify these three vs. Wazuh-docker's tested matrix
in the upstream repo.

## Filesystem layout

```
/opt/wazuh-deploy/                       # this directory (jackal:jackal 0755)
├── README.md                            # this file
├── .env                                 # passwords (0600 jackal:jackal)
├── docker-compose.yml                   # main stack definition
├── generate-indexer-certs.yml           # one-shot cert generator (canonical upstream)
└── config/
    ├── certs.yml                        # input to cert generator
    ├── wazuh_indexer_ssl_certs/         # OUTPUT of cert generator (12 files — see Certificates section)
    ├── wazuh_indexer/                   # indexer config (canonical upstream)
    ├── wazuh_dashboard/                 # dashboard config (canonical upstream)
    └── wazuh_cluster/                   # manager config (canonical upstream)
```

**Persistent data lives in named docker volumes**, NOT in this directory.
Bind mounts are config-only (read-only into containers). Therefore:
- `rm -rf /opt/wazuh-deploy` does NOT delete Wazuh data — `docker volume rm wazuh-indexer-data` does
- A backup of this directory + `.env` is sufficient to redeploy if the volumes
  are intact

## Backlog

Items deferred from Phase 1A iteration 1, queued for separate sessions:

- **Enable cgroup memory accounting on Pi.** The compose YAML's `mem_limit:`
  settings (manager 1g, indexer 1.5g, dashboard 768m) are silently ignored by
  the kernel:
  > `Your kernel does not support memory limit capabilities or the cgroup is
  > not mounted. Limitation discarded.`
  Pi OS's default kernel cmdline doesn't enable cgroup memory. To fix, append
  `cgroup_enable=memory cgroup_memory=1` to `/boot/firmware/cmdline.txt` (single
  line, space-separated) and reboot. The actual RAM consumption at iter-1
  steady state is well under the budget without the limits being enforced, so
  not blocking. Worth doing before Phase 1B (which adds the wazuh-agent + may
  push memory usage higher). **Requires ~1 min of Pi downtime** for the reboot
  (cowrie + tunnel briefly drop, fluent-bit's filesystem-backed buffer prevents
  log loss).

## Pointers

- Upstream Wazuh-docker reference: <https://github.com/wazuh/wazuh-docker/tree/v4.14.5/single-node>
- SOC pipeline repo: <https://github.com/dram64/soc-detection-lab-honeypot>
- Live SOC dashboard (separate from Wazuh): <https://dashboard.dram-soc.org>
