#!/usr/bin/env bash
# Repeatable release build on Linux: React UI, .NET build and tests, self-contained server-linux-x64 plus the Windows packages (cross-published).
#   scripts/build-release.sh [OUTPUT_DIR] [--skip-tests] [--skip-publish-tests] [--allow-unsupported-node]
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"; frontend="$(cd "$root/../../frontend" && pwd)"
output="$root/artifacts/release"; tests=1; publish_tests=1; allow_node=0
for arg in "$@"; do case "$arg" in
  --skip-tests) tests=0 ;; --skip-publish-tests) publish_tests=0 ;; --allow-unsupported-node) allow_node=1 ;; -*) echo "unknown option $arg" >&2; exit 2 ;; *) output="$arg" ;;
esac; done
major="$(node --version | sed 's/^v//; s/\..*//')"
if [ "$major" -lt 24 ] || [ "$major" -gt 25 ]; then
  if [ "$allow_node" = 1 ]; then echo "warning: Node.js $(node --version) is outside 24-25 (frontend/package.json); continuing because --allow-unsupported-node" >&2
  else echo "Node.js $(node --version) is not supported (24 or 25 required); use --allow-unsupported-node only for development builds" >&2; exit 2; fi
fi
(cd "$frontend" && npm ci --no-audit --no-fund && npm run build)
dotnet build "$root/SapLens.slnx" -c Release
if [ "$tests" = 1 ]; then
  if [ "$publish_tests" = 1 ]; then dotnet test "$root/tests/SapLens.Tests" -c Release --no-build
  else dotnet test "$root/tests/SapLens.Tests" -c Release --no-build --filter "Category!=Publish"; fi
fi
dotnet publish "$root/src/SapLens.Api" -c Release -r linux-x64 --self-contained true -o "$output/server-linux-x64"
dotnet publish "$root/src/SapLens.Api" -c Release -r win-x64 --self-contained true -o "$output/server-win-x64"
dotnet publish "$root/src/SapLens.Desktop" -c Release -o "$output/desktop-win-x64"
du -sh "$output"/*
echo "Release build complete. Nothing was installed or started."
