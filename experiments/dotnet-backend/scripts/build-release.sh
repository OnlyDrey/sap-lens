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
sha="$(git -C "$root" rev-parse HEAD)"
dirty="$(git -C "$root" status --porcelain -- . ../../frontend | head -1)"
if [ -n "$dirty" ]; then echo "warning: the working tree has uncommitted changes; the manifest records dirty=true" >&2; fi
identity=(-p:SourceRevisionId="$sha")
(cd "$frontend" && npm ci --no-audit --no-fund && npm run build)
dotnet build "$root/SapLens.slnx" -c Release "${identity[@]}"
if [ "$tests" = 1 ]; then
  if [ "$publish_tests" = 1 ]; then dotnet test "$root/tests/SapLens.Tests" -c Release --no-build
  else dotnet test "$root/tests/SapLens.Tests" -c Release --no-build --filter "Category!=Publish"; fi
fi
rm -rf "$output"; mkdir -p "$output"
dotnet publish "$root/src/SapLens.Api" -c Release -r linux-x64 --self-contained true -o "$output/server-linux-x64" "${identity[@]}"
dotnet publish "$root/src/SapLens.Api" -c Release -r win-x64 --self-contained true -o "$output/server-win-x64" "${identity[@]}"
dotnet publish "$root/src/SapLens.Desktop" -c Release -o "$output/desktop-win-x64" "${identity[@]}"
# Artifact validation: build identity stamped in every package, React UI embedded, no loose UI folders.
for check in "server-linux-x64/SapLens.Api.dll" "server-win-x64/SapLens.Api.dll" "desktop-win-x64/SapLens2Prototype.exe"; do
  grep -qa "+$sha" "$output/$check" || { echo "build identity $sha missing in $check" >&2; exit 1; }
  grep -qa 'SapLens.Api.wwwroot.assets.' "$output/$check" || { echo "React UI missing in $check" >&2; exit 1; }
done
for package in server-linux-x64 server-win-x64 desktop-win-x64; do [ ! -d "$output/$package/wwwroot" ] && [ ! -d "$output/$package/frontend" ] || { echo "unexpected loose UI folder in $package" >&2; exit 1; }; done
(cd "$output" && find . -type f ! -name SHA256SUMS ! -name manifest.json | sort | xargs sha256sum > SHA256SUMS)
python3 - "$output" "$sha" "${dirty:+true}" <<'PY'
import hashlib, json, subprocess, sys
from pathlib import Path
out, sha, dirty = Path(sys.argv[1]), sys.argv[2], sys.argv[3] == 'true'
def run(*cmd): return subprocess.run(cmd, capture_output=True, text=True).stdout.strip()
packages = {}
for package in sorted(p for p in out.iterdir() if p.is_dir()):
    files = sorted(f for f in package.rglob('*') if f.is_file())
    packages[package.name] = dict(files=len(files), bytes=sum(f.stat().st_size for f in files))
manifest = dict(product='SAP Lens 2 (.NET experiment)', version='0.0.0-experiment', source_sha=sha, source_dirty=dirty, branch=run('git', 'rev-parse', '--abbrev-ref', 'HEAD'),
                dotnet_sdk=run('dotnet', '--version'), node=run('node', '--version'), packages=packages,
                checksums_sha256=hashlib.sha256((out / 'SHA256SUMS').read_bytes()).hexdigest())
(out / 'manifest.json').write_text(json.dumps(manifest, indent=1) + '\n')
print(json.dumps(manifest, indent=1))
PY
du -sh "$output"/*
echo "Release build complete. Nothing was installed or started."
