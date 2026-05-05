#!/usr/bin/env bash
# SOC Detection Lab — first-run setup
# Run before `docker compose up -d`

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$SCRIPT_DIR"

echo "==> SOC Detection Lab setup"
echo

# --- Check prerequisites ---
echo "[1/5] Checking prerequisites..."

if ! command -v docker &>/dev/null; then
  echo "ERROR: Docker not installed. Install Docker Engine 24+ first."
  exit 1
fi

if ! docker compose version &>/dev/null; then
  echo "ERROR: Docker Compose v2 plugin not available. Install via: sudo apt install docker-compose-plugin"
  exit 1
fi

DOCKER_VERSION=$(docker --version | grep -oP '\d+\.\d+\.\d+' | head -1)
echo "    Docker $DOCKER_VERSION ✓"

# --- Check available memory ---
echo "[2/5] Checking available RAM..."

if [[ "$(uname)" == "Linux" ]]; then
  AVAIL_MEM_GB=$(free -g | awk '/^Mem:/{print $2}')
elif [[ "$(uname)" == "Darwin" ]]; then
  AVAIL_MEM_GB=$(($(sysctl -n hw.memsize) / 1024 / 1024 / 1024))
else
  AVAIL_MEM_GB=0
fi

if (( AVAIL_MEM_GB < 16 )); then
  echo "    WARN: Only ${AVAIL_MEM_GB}GB RAM available. Lab needs 16GB minimum, 32GB recommended."
  echo "    Continue anyway? [y/N]"
  read -r answer
  [[ "$answer" =~ ^[Yy]$ ]] || exit 1
else
  echo "    ${AVAIL_MEM_GB}GB RAM available ✓"
fi

# --- Generate .env from template if missing ---
echo "[3/5] Setting up environment file..."

if [[ ! -f .env ]]; then
  cp .env.example .env
  
  # Generate strong random passwords for each placeholder
  for var in WAZUH_INDEXER_PASSWORD WAZUH_API_PASSWORD ELASTIC_PASSWORD KIBANA_PASSWORD SPLUNK_PASSWORD MISP_ADMIN_PASSWORD MISP_DB_PASSWORD MISP_DB_ROOT_PASSWORD; do
    if grep -q "ChangeMe_StrongPassword" .env; then
      newpass=$(openssl rand -base64 24 | tr -d "/+=" | cut -c1-24)
      sed -i.bak "s|${var}=ChangeMe_StrongPassword.*|${var}=${newpass}|" .env
    fi
  done
  
  rm -f .env.bak
  
  echo "    .env generated with random passwords ✓"
  echo "    Saved to .env (gitignored — never commit this)"
else
  echo "    .env already exists ✓"
fi

# --- Generate self-signed certs ---
echo "[4/5] Generating self-signed certificates..."

mkdir -p certs

if [[ ! -f certs/ca.crt ]]; then
  openssl req -x509 -newkey rsa:4096 -days 365 -nodes \
    -keyout certs/ca.key -out certs/ca.crt \
    -subj "/CN=SOC Lab CA" 2>/dev/null
  echo "    CA cert generated ✓"
else
  echo "    CA cert exists ✓"
fi

# --- Set required kernel parameters ---
echo "[5/5] Setting kernel parameters..."

if [[ "$(uname)" == "Linux" ]]; then
  current_max_map=$(sysctl -n vm.max_map_count)
  if (( current_max_map < 262144 )); then
    echo "    Setting vm.max_map_count=262144 (required by Elasticsearch)..."
    sudo sysctl -w vm.max_map_count=262144
    echo "vm.max_map_count=262144" | sudo tee -a /etc/sysctl.conf > /dev/null
    echo "    Kernel parameter updated ✓"
  else
    echo "    vm.max_map_count already sufficient ✓"
  fi
fi

echo
echo "==> Setup complete!"
echo
echo "Next steps:"
echo "  1. Review and edit .env if needed"
echo "  2. Bring up the stack:    docker compose up -d"
echo "  3. Watch services start:  docker compose ps"
echo "  4. View logs:             docker compose logs -f"
echo
echo "Service URLs (after stack is up):"
echo "  Wazuh dashboard:    https://localhost:443    (admin / SecretPassword)"
echo "  Kibana:             http://localhost:5601    (elastic / changeme)"
echo "  Splunk:             http://localhost:8000    (admin / changeme)"
echo "  MISP:               https://localhost:8443   (admin@admin.test / admin)"
echo
echo "Change all default credentials before exposure. See docs/hardening.md"
