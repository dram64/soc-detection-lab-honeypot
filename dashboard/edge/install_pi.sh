#!/usr/bin/env bash
###############################################################################
# Install fluent-bit on the Pi for the Cowrie shipper feed.
#
# Run from the Pi (or via rsync + ssh from the deployer machine), as a user
# with sudo. Idempotent — reruns safely.
#
# Prereq: drop the AWS credentials file at /etc/fluent-bit/aws-credentials
# (mode 0600, owner fluent-bit:fluent-bit) BEFORE this script's first run, OR
# during the systemd enable step. Get the contents from
#   terraform output -raw fluentbit_pi_credentials
###############################################################################

set -euo pipefail

REPO_DIR="${REPO_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
EDGE_DIR="${REPO_DIR}/edge/fluent-bit/pi"

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
  # Distro-aware repo selection — the Treasure Data vendor matrix doesn't
  # cover every codename. Fall back to the closest supported LTS when needed.
  . /etc/os-release
  case "${ID}-${VERSION_CODENAME}" in
    ubuntu-noble|ubuntu-mantic)
      REPO_PATH="ubuntu/jammy"; REPO_CODENAME="jammy" ;;
    ubuntu-*)
      REPO_PATH="ubuntu/${VERSION_CODENAME}"; REPO_CODENAME="${VERSION_CODENAME}" ;;
    debian-*|raspbian-*)
      REPO_PATH="debian/${VERSION_CODENAME}"; REPO_CODENAME="${VERSION_CODENAME}" ;;
    *)
      echo "unsupported distro: ${ID} ${VERSION_CODENAME}" >&2; exit 1 ;;
  esac
  echo "deb [signed-by=/usr/share/keyrings/fluentbit-keyring.gpg] https://packages.fluentbit.io/${REPO_PATH} ${REPO_CODENAME} main" \
    > /etc/apt/sources.list.d/fluent-bit.list
  apt-get update
  apt-get install -y fluent-bit
fi

echo "==> placing config files"
install -d -m 0755 /etc/fluent-bit
install -m 0644 -o root -g root "${EDGE_DIR}/fluent-bit.conf" /etc/fluent-bit/fluent-bit.conf
install -m 0644 -o root -g root "${EDGE_DIR}/parsers.conf"    /etc/fluent-bit/parsers.conf

if [[ ! -f /etc/fluent-bit/aws-credentials ]]; then
  cat <<'WARN' >&2
WARNING: /etc/fluent-bit/aws-credentials is missing.

Drop it before starting the service:
  terraform output -raw fluentbit_pi_credentials \
      | sudo tee /etc/fluent-bit/aws-credentials >/dev/null
  sudo chown fluent-bit:fluent-bit /etc/fluent-bit/aws-credentials
  sudo chmod 0600 /etc/fluent-bit/aws-credentials

Continuing setup; the service will fail-loop on AccessDenied until the
credentials are in place.
WARN
fi

echo "==> ensuring storage + DB dirs exist"
install -d -m 0755 -o fluent-bit -g fluent-bit /var/lib/fluent-bit
install -d -m 0755 -o fluent-bit -g fluent-bit /var/lib/fluent-bit/storage

echo "==> ensuring fluent-bit user can READ Cowrie's log file"
# Cowrie writes JSON owned by user `cowrie`. fluent-bit needs read.
# Add fluent-bit to the cowrie group AND make /home/cowrie traversable
# by the group — Cowrie's home dir defaults to 0700, which blocks group
# members from descending into var/log/cowrie/ even though the leaf file
# is group-readable. 0750 fixes traversal without exposing it world-wide.
COWRIE_HOME=/home/cowrie
COWRIE_LOG=${COWRIE_HOME}/cowrie/var/log/cowrie/cowrie.json
if [[ -f "${COWRIE_LOG}" ]]; then
  COWRIE_GROUP="$(stat -c '%G' "${COWRIE_LOG}")"
  if ! id -nG fluent-bit | grep -qw "${COWRIE_GROUP}"; then
    usermod -aG "${COWRIE_GROUP}" fluent-bit
    echo "    added fluent-bit to group ${COWRIE_GROUP}"
  fi
  # 0750 = owner rwx, group rx, world none. Idempotent.
  chmod 0750 "${COWRIE_HOME}"
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
