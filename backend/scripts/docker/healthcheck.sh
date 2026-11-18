#!/bin/sh
set -eu
port=${SAP_LENS_V2_PORT:-18795}
host=${SAP_LENS_V2_HEALTH_HOST:-${SAP_LENS_V2_ALLOWED_HOSTS%%,*}}
[ -n "$host" ] && [ -n "${SAP_LENS_V2_CERT:-}" ] || { echo 'Health probe requires a TLS certificate and advertised host.' >&2; exit 1; }
# Probe the one container listener; hostname and chain validation remain enabled.
address=${SAP_LENS_V2_LISTEN:-$(hostname -i | awk '{print $1}')}
exec curl --fail --silent --show-error --max-time 3 --noproxy '*' --cacert "$SAP_LENS_V2_CERT" \
    --resolve "$host:$port:$address" "https://$host:$port/health/ready"
