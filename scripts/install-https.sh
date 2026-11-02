#!/usr/bin/env bash
# Run interactively as root. Certbot asks for the ACME account and terms consent.
set -euo pipefail
[[ $(id -u) == 0 ]] || { echo 'Run this script with sudo.' >&2; exit 1; }
for command in certbot nginx tar flock; do
    command -v "$command" >/dev/null || { echo "Missing $command. Install certbot and python3-certbot-nginx first." >&2; exit 1; }
done
exec 9>/run/lock/poe2guild-https.lock
flock -n 9 || { echo 'Another HTTPS installation is running.' >&2; exit 1; }
nginx -t
umask 077
backup=$(mktemp -d /var/backups/poe2guild-https.XXXXXXXX)
tar -C /etc -cpf "$backup/nginx.tar" nginx
printf 'Nginx backup: %s/nginx.tar\n' "$backup"
project=$(dirname -- "$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}")")")
"$project/poe2guild" install
# Only the virtual host for this domain is selected; existing locations stay intact.
certbot --nginx --domain dyyyl.ovh --redirect
nginx -t
nginx -s reload
certbot renew --dry-run
printf 'HTTPS configured. Verify https://dyyyl.ovh/poe2guild/ from your browser.\n'
printf 'Verify that port 443 is allowed by the host/provider firewall.\n'
