#!/bin/sh
set -eu
# One private interface, never 0.0.0.0. The existing host policy validates it and requires TLS.
if [ -z "${SAP_LENS_V2_LISTEN:-}" ]; then
    set -- "$@"
    SAP_LENS_V2_LISTEN=$(hostname -i | awk '{print $1}')
    export SAP_LENS_V2_LISTEN
fi
exec dotnet /app/SapLens.Api.dll "$@"
