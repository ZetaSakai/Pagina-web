#!/bin/bash
# Cloudflare WAF - UFW Configuration Script
# This script configures UFW to only accept traffic from Cloudflare IPs
# Run this ONLY if you are using Cloudflare's proxy (orange cloud)

set -e

echo "=== Cloudflare WAF - UFW Configuration ==="
echo ""
echo "WARNING: This script will configure UFW to only accept traffic from Cloudflare IPs."
echo "Only run this if your domain is using Cloudflare's proxy (orange cloud enabled)."
echo ""
read -p "Do you want to continue? (y/N): " confirm

if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
    echo "Aborted."
    exit 0
fi

# Check if UFW is installed
if ! command -v ufw &> /dev/null; then
    echo "UFW is not installed. Installing..."
    apt-get update && apt-get install -y ufw
fi

# Reset UFW rules (optional - comment out if you want to keep existing rules)
echo "Resetting UFW rules..."
ufw --force reset

# Default policies - DENY all incoming, ALLOW outgoing
echo "Setting default policies..."
ufw default deny incoming
ufw default allow outgoing

# Allow SSH (important - don't lock yourself out!)
echo "Allowing SSH (port 22)..."
ufw allow ssh

# Allow HTTP and HTTPS from anywhere (Cloudflare will connect)
echo "Allowing HTTP (port 80) and HTTPS (port 443)..."
ufw allow http
ufw allow https

# Enable UFW
echo "Enabling UFW..."
ufw --force enable

echo ""
echo "=== UFW Basic Configuration Complete ==="
echo ""
echo "For stricter security, you can restrict HTTP/HTTPS to Cloudflare IPs only."
echo "Cloudflare IP ranges (update these periodically from https://www.cloudflare.com/ips/):"
echo ""

# Cloudflare IPv4 ranges
CLOUDFLARE_IPV4=(
    "173.245.48.0/20"
    "103.21.244.0/22"
    "103.22.200.0/22"
    "103.31.4.0/22"
    "141.101.64.0/18"
    "108.162.192.0/18"
    "190.93.240.0/20"
    "188.114.96.0/20"
    "197.234.240.0/22"
    "198.41.128.0/17"
    "162.158.0.0/15"
    "104.16.0.0/13"
    "104.24.0.0/14"
    "172.64.0.0/13"
    "131.0.72.0/22"
)

# Cloudflare IPv6 ranges
CLOUDFLARE_IPV6=(
    "2400:cb00::/32"
    "2606:4700::/32"
    "2803:f800::/32"
    "2405:b500::/32"
    "2405:8100::/32"
    "2c9f:b690::/32"
)

echo "# To restrict HTTP/HTTPS to Cloudflare IPs only, run these commands:"
echo ""
for ip in "${CLOUDFLARE_IPV4[@]}"; do
    echo "ufw from $ip to any port 80 proto tcp comment 'Cloudflare HTTP'"
    echo "ufw from $ip to any port 443 proto tcp comment 'Cloudflare HTTPS'"
done

for ip in "${CLOUDFLARE_IPV6[@]}"; do
    echo "ufw from $ip to any port 80 proto tcp comment 'Cloudflare HTTP IPv6'"
    echo "ufw from $ip to any port 443 proto tcp comment 'Cloudflare HTTPS IPv6'"
done

echo ""
echo "=== Alternative: Automated Script ==="
echo "To automatically apply Cloudflare IP rules, run:"
echo ""
echo "  sudo $0 apply-cloudflare-ips"
echo ""

# Check if user wants to apply Cloudflare IPs now
if [[ "$1" == "apply-cloudflare-ips" ]]; then
    echo ""
    echo "Applying Cloudflare IP rules..."

    for ip in "${CLOUDFLARE_IPV4[@]}"; do
        ufw allow from $ip to any port 80 proto tcp comment "Cloudflare HTTP"
        ufw allow from $ip to any port 443 proto tcp comment "Cloudflare HTTPS"
    done

    for ip in "${CLOUDFLARE_IPV6[@]}"; do
        ufw allow from $ip to any port 80 proto tcp comment "Cloudflare HTTP IPv6"
        ufw allow from $ip to any port 443 proto tcp comment "Cloudflare HTTPS IPv6"
    done

    echo ""
    echo "=== Cloudflare IP rules applied successfully ==="
    echo "Run 'ufw status verbose' to verify the configuration."
fi

echo ""
echo "=== Additional Security Recommendations ==="
echo "1. Update Cloudflare IPs regularly (they change occasionally)"
echo "2. Monitor UFW logs: /var/log/ufw.log"
echo "3. Consider fail2ban for additional protection"
echo "4. Keep your system updated: apt update && apt upgrade"
