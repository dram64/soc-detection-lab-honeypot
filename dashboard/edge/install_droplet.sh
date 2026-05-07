#!/usr/bin/env bash
###############################################################################
# Install fluent-bit on the DigitalOcean droplet for the HAProxy feed.
#
# Also applies the HAProxy log-format change (option logasap + custom
# log-format) required by ADR-010 §Decision. Idempotent.
#
# Prereq: drop the AWS credentials file at /etc/fluent-bit/aws-credentials
# (mode 0600) BEFORE the systemd service starts. Get the contents from
#   terraform output -raw fluentbit_droplet_credentials
###############################################################################

set -euo pipefail

REPO_DIR="${REPO_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
EDGE_DIR="${REPO_DIR}/edge/fluent-bit/droplet"
HAPROXY_SNIPPET="${REPO_DIR}/edge/haproxy/haproxy.cfg.snippet"

if [[ $EUID -ne 0 ]]; then
  echo "must run as root (use sudo)" >&2
  exit 1
fi

echo "==> ensuring fluent-bit user/group exist"
getent group fluent-bit > /dev/null || groupadd --system fluent-bit
getent passwd fluent-bit > /dev/null || \
  useradd --system --no-create-home --shell /usr/sbin/nologin --gid fluent-bit fluent-bit

echo "==> installing fluent-bit (Treasure Data APT repo)"
if ! command -v fluent-bit > /dev/null && [[ ! -x /opt/fluent-bit/bin/fluent-bit ]]; then
  curl -fsSL https://packages.fluentbit.io/fluentbit.key | gpg --dearmor -o /usr/share/keyrings/fluentbit-keyring.gpg
  # Pick the right Treasure Data repo path. The vendor publishes builds
  # for a specific debian/ubuntu codename matrix; codenames not in the
  # matrix (e.g. Ubuntu noble at the time of Phase 10) need to fall back
  # to the closest LTS the vendor supports.
  . /etc/os-release
  case "${ID}-${VERSION_CODENAME}" in
    ubuntu-noble|ubuntu-mantic)
      # No vendor build for noble yet; jammy packages run cleanly on noble.
      REPO_PATH="ubuntu/jammy"; REPO_CODENAME="jammy" ;;
    ubuntu-*)
      REPO_PATH="ubuntu/${VERSION_CODENAME}"; REPO_CODENAME="${VERSION_CODENAME}" ;;
    debian-*)
      REPO_PATH="debian/${VERSION_CODENAME}"; REPO_CODENAME="${VERSION_CODENAME}" ;;
    *)
      echo "unsupported distro: ${ID} ${VERSION_CODENAME}" >&2; exit 1 ;;
  esac
  echo "deb [signed-by=/usr/share/keyrings/fluentbit-keyring.gpg] https://packages.fluentbit.io/${REPO_PATH} ${REPO_CODENAME} main" \
    > /etc/apt/sources.list.d/fluent-bit.list
  apt-get update
  apt-get install -y fluent-bit
fi

echo "==> placing fluent-bit config"
install -d -m 0755 /etc/fluent-bit
install -m 0644 -o root -g root "${EDGE_DIR}/fluent-bit.conf" /etc/fluent-bit/fluent-bit.conf
install -m 0644 -o root -g root "${EDGE_DIR}/parsers.conf"    /etc/fluent-bit/parsers.conf

if [[ ! -f /etc/fluent-bit/aws-credentials ]]; then
  cat <<'WARN' >&2
WARNING: /etc/fluent-bit/aws-credentials is missing.

Drop it before starting the service:
  terraform output -raw fluentbit_droplet_credentials \
      | sudo tee /etc/fluent-bit/aws-credentials >/dev/null
  sudo chown fluent-bit:fluent-bit /etc/fluent-bit/aws-credentials
  sudo chmod 0600 /etc/fluent-bit/aws-credentials
WARN
fi

echo "==> ensuring storage + DB dirs exist"
install -d -m 0755 -o fluent-bit -g fluent-bit /var/lib/fluent-bit
install -d -m 0755 -o fluent-bit -g fluent-bit /var/lib/fluent-bit/storage

echo "==> ensuring fluent-bit user can READ /var/log/haproxy.log"
HAPROXY_LOG=/var/log/haproxy.log
if [[ -f "${HAPROXY_LOG}" ]]; then
  HAPROXY_GROUP="$(stat -c '%G' "${HAPROXY_LOG}")"
  if ! id -nG fluent-bit | grep -qw "${HAPROXY_GROUP}"; then
    usermod -aG "${HAPROXY_GROUP}" fluent-bit
    echo "    added fluent-bit to group ${HAPROXY_GROUP}"
  fi
fi

echo "==> applying HAProxy log-format change (ADR-010)"
# Sentinel grep — only patch if the deployed config doesn't already have
# `option logasap` AND the expected log-format. The snippet file is the
# canonical declaration; the operator can paste it in by hand if more
# customization is needed.
if ! grep -q "option logasap" /etc/haproxy/haproxy.cfg 2>/dev/null \
   || ! grep -q "client=%ci:%cp" /etc/haproxy/haproxy.cfg 2>/dev/null; then
  cat <<NOTE
NOTE: HAProxy config does not have the ADR-010 log-format change.
      Review and merge: ${HAPROXY_SNIPPET}
      Then run:
        sudo haproxy -c -f /etc/haproxy/haproxy.cfg
        sudo systemctl reload haproxy
      The droplet-side fluent-bit parser depends on the log-format. Without
      the change, the parser regex won't match and HAProxy lines will be
      dropped at parse time.
NOTE
fi

echo "==> installing systemd unit"
install -m 0644 "${EDGE_DIR}/soc-fluent-bit.service" /etc/systemd/system/soc-fluent-bit.service
systemctl daemon-reload
systemctl enable soc-fluent-bit.service

echo "==> starting service"
systemctl restart soc-fluent-bit.service
sleep 2
systemctl --no-pager status soc-fluent-bit.service | head -20 || true

echo "==> done. tail logs with: journalctl -u soc-fluent-bit.service -f"
