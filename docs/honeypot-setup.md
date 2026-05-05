# Honeypot Setup: Raspberry Pi 5 + Cowrie + Cloudflare Tunnel

This guide sets up a Raspberry Pi 5 as an SSH/Telnet honeypot exposed to the internet via Cloudflare Tunnel — no port forwarding on the home router required.

## Why Cloudflare Tunnel instead of port forwarding?

- **No router admin access needed.** The Pi connects outbound to Cloudflare; no inbound ports opened on the home network.
- **No public IP exposure.** Your home IP stays hidden from attackers.
- **Free.** Cloudflare's free plan includes Tunnel for non-commercial use.
- **DDoS protection.** Cloudflare absorbs volumetric attacks before they hit the Pi.

## Hardware

- Raspberry Pi 5 (4 GB or 8 GB)
- 32 GB+ microSD card or USB SSD
- Power supply (official 27W USB-C recommended)
- Ethernet cable (Wi-Fi works but ethernet is more reliable for a sensor)

## Step 1: Install Raspberry Pi OS Lite

Use Raspberry Pi Imager. Choose:

- OS: Raspberry Pi OS Lite (64-bit, Bookworm)
- Hostname: `soc-honeypot-1`
- SSH: enabled, key-based auth only (paste your public key)
- Username: `socadmin` (NOT `pi` — too obvious)
- Strong password (or disable password login entirely once SSH key works)
- WiFi: configure if not using ethernet
- Locale: your timezone

Boot the Pi. SSH in:

```bash
ssh socadmin@soc-honeypot-1.local
```

## Step 2: Harden the Pi baseline

```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install essentials
sudo apt install -y \
  ufw fail2ban unattended-upgrades \
  curl wget vim git htop \
  python3 python3-pip python3-venv \
  authbind

# Enable automatic security updates
sudo dpkg-reconfigure -plow unattended-upgrades

# Configure UFW firewall
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow from <YOUR_LAN_SUBNET> to any port 22
sudo ufw allow 2222/tcp comment 'Cowrie SSH honeypot'
sudo ufw --force enable

# Disable unused services
sudo systemctl disable bluetooth.service
sudo systemctl disable hciuart.service

# Harden SSH (real SSH on management port)
sudo sed -i 's/#Port 22/Port 22/' /etc/ssh/sshd_config
sudo sed -i 's/#PasswordAuthentication yes/PasswordAuthentication no/' /etc/ssh/sshd_config
sudo sed -i 's/#PermitRootLogin .*/PermitRootLogin no/' /etc/ssh/sshd_config
sudo sed -i 's/X11Forwarding yes/X11Forwarding no/' /etc/ssh/sshd_config
sudo systemctl restart sshd
```

## Step 3: Install Cowrie

```bash
# Create dedicated user
sudo adduser --disabled-password --gecos "" cowrie

# Switch to cowrie user
sudo su - cowrie

# Clone Cowrie
git clone https://github.com/cowrie/cowrie.git
cd cowrie

# Set up Python virtual environment
python3 -m venv cowrie-env
source cowrie-env/bin/activate

# Install dependencies
pip install --upgrade pip
pip install -r requirements.txt

# Copy default config
cp etc/cowrie.cfg.dist etc/cowrie.cfg

# Edit config — important settings
vim etc/cowrie.cfg
```

Edit `etc/cowrie.cfg`:

```ini
[honeypot]
# Make the honeypot look like a real Linux server
hostname = ubuntu-server-01
log_path = var/log/cowrie
download_path = var/lib/cowrie/downloads

[ssh]
# Listen on 2222; we redirect 22 -> 2222 via iptables
listen_endpoints = tcp:2222:interface=0.0.0.0

[telnet]
listen_endpoints = tcp:2223:interface=0.0.0.0

[output_jsonlog]
enabled = true
logfile = var/log/cowrie/cowrie.json

[output_localsyslog]
enabled = true
facility = LOCAL5
format = text
```

Start Cowrie:

```bash
cd ~/cowrie
bin/cowrie start
```

Verify:

```bash
ss -tlnp | grep 2222   # should show cowrie listening
tail -f var/log/cowrie/cowrie.log
```

## Step 4: NAT redirect 22 → 2222

```bash
# Back to the admin user
exit

# Persistent iptables redirect
sudo apt install -y iptables-persistent

# Add NAT rule — incoming :22 redirects to local :2222
sudo iptables -t nat -A PREROUTING -p tcp --dport 22 -j REDIRECT --to-port 2222

# Save persistent rules
sudo netfilter-persistent save
sudo netfilter-persistent reload

# Verify
sudo iptables -t nat -L -n -v
```

## Step 5: Cloudflare Tunnel

This exposes the Pi to the internet without any inbound ports on your router.

### 5.1 Create a Cloudflare account (if you don't have one)

Sign up at https://cloudflare.com — free plan is fine.

### 5.2 Add a domain

You need a domain (or subdomain) on Cloudflare. If you don't have one:
- Buy a `.xyz` or `.online` domain (~$2-5/year)
- Or use a free subdomain service (limited)

Add the domain to Cloudflare; follow their nameserver instructions.

### 5.3 Install cloudflared on the Pi

```bash
# Download the Cloudflare daemon
curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64 -o cloudflared
chmod +x cloudflared
sudo mv cloudflared /usr/local/bin/

# Verify
cloudflared --version
```

### 5.4 Authenticate and create the tunnel

```bash
# Authenticate (opens browser)
cloudflared tunnel login

# Create the tunnel
cloudflared tunnel create soc-honeypot

# Note the Tunnel UUID it returns
```

### 5.5 Configure the tunnel

```bash
mkdir -p ~/.cloudflared
vim ~/.cloudflared/config.yml
```

```yaml
tunnel: <YOUR_TUNNEL_UUID>
credentials-file: /home/socadmin/.cloudflared/<UUID>.json

ingress:
  # Route incoming SSH connections to Cowrie
  - hostname: ssh-honeypot.<your-domain>.xyz
    service: ssh://localhost:2222

  # Catch-all
  - service: http_status:404
```

### 5.6 Add DNS route

```bash
cloudflared tunnel route dns soc-honeypot ssh-honeypot.<your-domain>.xyz
```

### 5.7 Run the tunnel as a service

```bash
sudo cloudflared service install
sudo systemctl enable cloudflared
sudo systemctl start cloudflared
sudo systemctl status cloudflared
```

## Step 6: Ship logs to the SOC stack

Install filebeat on the Pi:

```bash
# Add Elastic repo
curl -fsSL https://artifacts.elastic.co/GPG-KEY-elasticsearch | sudo gpg --dearmor -o /usr/share/keyrings/elastic.gpg
echo "deb [signed-by=/usr/share/keyrings/elastic.gpg] https://artifacts.elastic.co/packages/8.x/apt stable main" | sudo tee /etc/apt/sources.list.d/elastic-8.x.list
sudo apt update
sudo apt install -y filebeat
```

Configure `/etc/filebeat/filebeat.yml`:

```yaml
filebeat.inputs:
  - type: log
    enabled: true
    paths:
      - /home/cowrie/cowrie/var/log/cowrie/cowrie.json
    json.keys_under_root: true
    json.add_error_key: true
    fields:
      log_source: cowrie
      sensor_name: soc-honeypot-1
    fields_under_root: false

output.logstash:
  hosts: ["soc-stack.<your-domain>:5044"]

logging.level: info
```

If shipping over the internet, use TLS:

```yaml
output.logstash:
  hosts: ["soc-stack.<your-domain>:5044"]
  ssl.certificate_authorities: ["/etc/filebeat/ca.crt"]
  ssl.verification_mode: full
```

Start filebeat:

```bash
sudo systemctl enable filebeat
sudo systemctl start filebeat
sudo systemctl status filebeat
```

## Step 7: Verify end-to-end

From an external host (not your home network), try to SSH to the honeypot:

```bash
ssh -p 22 root@ssh-honeypot.<your-domain>.xyz
# Cowrie should accept the connection and present a fake shell
# Try password "password", "123456", "admin" — all should "work"
```

Check the SOC stack:

```bash
# In Wazuh dashboard, search for:
data.eventid:cowrie.login.failed

# In Kibana:
log_source:"cowrie" AND eventid:"cowrie.login.failed"

# Should show the SSH attempts within seconds of them happening
```

## Step 8: Wait for real attackers

Within 24-48 hours of being internet-exposed, expect:

- Mass scanning from common attack sources (DigitalOcean, OVH, Aliyun)
- Brute force attempts against `root`, `admin`, `ubuntu`, `pi`
- Credential stuffing using leaked breach databases
- Occasional malware download attempts

Wazuh alerts will start firing as the attack patterns match the rules in `wazuh/rules/100100-cowrie.xml`.

## Operational notes

- **Cowrie disk usage:** JSON logs grow. Set up logrotate or ship to ELK and let Cowrie's local logs rotate.
- **Pi heat:** Cowrie + filebeat + cloudflared together use ~20% CPU during active attacks. Add a heatsink/fan if running 24/7.
- **Cloudflare Tunnel limits:** Free plan has unlimited bandwidth but rate limits on connections (~100/sec). Should not be an issue for a honeypot.
- **Legal:** Honeypots are legal for defensive research in most jurisdictions. You're attracting attacks to a system you control. Don't run a honeynet on a corporate network without authorization.

## Troubleshooting

### Cowrie not accepting connections

```bash
# Check it's running
ps aux | grep cowrie
ss -tlnp | grep 2222

# Check logs
tail -f /home/cowrie/cowrie/var/log/cowrie/cowrie.log
```

### Cloudflare Tunnel not routing

```bash
# Check tunnel status
cloudflared tunnel info soc-honeypot

# Check the daemon
sudo systemctl status cloudflared
sudo journalctl -u cloudflared -f
```

### No logs reaching SOC stack

```bash
# On the Pi
sudo systemctl status filebeat
sudo journalctl -u filebeat -f

# Test connectivity
nc -zv soc-stack.<your-domain> 5044

# Check Logstash is listening
# (on the SOC stack host)
docker compose logs logstash | grep "5044"
```

## Next steps

Once the honeypot is generating real attacker data:

1. Tune detection rules based on observed attack patterns
2. Build dashboards in Wazuh/Kibana showing attack origin (geo), top attempted credentials, common commands
3. Submit interesting IOCs to MISP for community sharing
4. Write postmortems on notable attack campaigns

The whole point of the honeypot: detection rules tested against real adversary behavior, not theoretical attacks.
