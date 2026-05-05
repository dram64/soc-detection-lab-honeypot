# Hardening the SOC Lab Before Exposure

This is a homelab. Before exposing it (or its honeypot) to the internet, harden these areas.

## Lab host

```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Enable automatic security updates
sudo apt install -y unattended-upgrades
sudo dpkg-reconfigure -plow unattended-upgrades

# Configure UFW
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow from <YOUR_LAN_SUBNET>
sudo ufw --force enable

# SSH hardening
sudo sed -i 's/#PasswordAuthentication yes/PasswordAuthentication no/' /etc/ssh/sshd_config
sudo sed -i 's/#PermitRootLogin .*/PermitRootLogin no/' /etc/ssh/sshd_config
sudo systemctl restart sshd
```

## Docker security

```bash
# Don't run docker as root unless necessary
sudo usermod -aG docker $USER

# Use rootless Docker if possible
# https://docs.docker.com/engine/security/rootless/
```

## Credentials

Before `docker compose up`:

1. Copy `.env.example` to `.env`
2. Change EVERY password
3. Generate strong random passwords (`openssl rand -base64 32` or similar)
4. Never commit `.env` to Git (it's gitignored — verify)

## TLS / certificates

The default lab uses self-signed certs. For any deployment beyond localhost:

1. Generate proper certs (Let's Encrypt for public-facing, internal CA for private)
2. Mount the certs into containers via volumes
3. Update each tool's config to use real certs instead of self-signed

## Network exposure

**Default lab** binds to `localhost` only. To expose any service to the LAN:

1. Edit `docker-compose.yml`
2. Change port mapping from `127.0.0.1:5601:5601` to `5601:5601` (or a specific interface)
3. Configure firewall to allow only trusted source IPs

**Never expose** these services directly to the internet:

- Wazuh manager / dashboard (use VPN or Cloudflare Tunnel)
- Elasticsearch / Kibana (use VPN)
- Splunk admin port (8089)
- MISP admin (8443)

The honeypot (Cowrie) is the ONLY component meant to be exposed to attackers.

## Honeypot containment

If running the honeypot on the same network as production:

1. Put the honeypot on its own VLAN
2. Block all egress from the honeypot to your LAN
3. Allow only outbound to the SOC stack (over a specific port)
4. Monitor for any unexpected outbound connections from the honeypot (signal that the attacker escaped Cowrie's containment)

## Backups

```bash
# Backup the rules + configs (lightweight, version-controlled)
git push origin main

# Backup the data volumes (heavy, do less frequently)
docker run --rm \
  -v wazuh-config:/source:ro \
  -v $(pwd)/backups:/backup \
  alpine tar czf /backup/wazuh-config-$(date +%Y%m%d).tar.gz -C /source .
```

Store backups off-host (S3, separate disk, etc.).

## Monitoring the SOC stack itself

Wazuh's agent should be installed on the SOC host to monitor the SIEM itself:

```bash
# Install Wazuh agent
curl -s https://packages.wazuh.com/key/GPG-KEY-WAZUH | sudo apt-key add -
echo "deb https://packages.wazuh.com/4.x/apt/ stable main" | sudo tee /etc/apt/sources.list.d/wazuh.list
sudo apt update
sudo apt install -y wazuh-agent

# Configure to point at the manager
sudo sed -i 's|MANAGER_IP|127.0.0.1|' /var/ossec/etc/ossec.conf
sudo systemctl enable wazuh-agent
sudo systemctl start wazuh-agent
```

Now Wazuh monitors itself (file integrity, log analysis, vulnerability detection on the host).

## Audit log review

Set a monthly cadence:

1. Review Wazuh authentication logs for suspicious admin access
2. Review Docker daemon logs for unusual container starts
3. Review the lab's own GitHub repo for any committed secrets (scan with gitleaks before every push — already in CI)
4. Review which IPs are accessing the lab UI

## Compliance baseline

If running this lab as a SOC training environment that touches anything regulated, additional steps:

- CIS Docker Benchmark
- CIS Linux Benchmark for the host OS
- Audit log retention (90+ days minimum)
- Documented access control list (who has admin on the lab)
- Documented incident response runbooks (already shipped — see `docs/runbooks/`)

This lab is designed for personal portfolio use. For any production deployment, professional security review is required.
