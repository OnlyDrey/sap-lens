#!/usr/bin/env sh
set -eu
cd "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
if [ -n "${SAP_LENS_BUILD_PYTHON:-}" ]; then
    build_python=$SAP_LENS_BUILD_PYTHON
elif command -v python3.12 >/dev/null 2>&1; then
    build_python=python3.12
elif command -v python3 >/dev/null 2>&1; then
    build_python=python3
else
    printf '%s\n' 'Install Python 3.12 x64 before building SAP Lens.' >&2
    exit 1
fi
exec "$build_python" scripts/build-deployments.py "$@"
