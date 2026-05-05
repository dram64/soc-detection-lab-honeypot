#!/usr/bin/env bash
# Tear down the SOC Detection Lab cleanly

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$SCRIPT_DIR"

echo "==> SOC Detection Lab teardown"
echo
echo "This will:"
echo "  - Stop all containers"
echo "  - Remove all volumes (DESTROYS ALL DATA)"
echo "  - Remove the lab network"
echo
echo "Type 'DESTROY' to confirm:"
read -r confirm

if [[ "$confirm" != "DESTROY" ]]; then
  echo "Aborted. No changes made."
  exit 0
fi

echo
echo "[1/3] Stopping containers..."
docker compose down

echo "[2/3] Removing volumes..."
docker compose down -v

echo "[3/3] Removing network..."
docker network rm soc-detection-lab_soc-net 2>/dev/null || true

echo
echo "==> Teardown complete."
echo
echo "To start fresh:  ./scripts/setup.sh && docker compose up -d"
