#!/usr/bin/env bash
# Repeatable release build on Linux: React UI, .NET build and tests, then two versioned release folders under OUTPUT_DIR (default artifacts/release):
#   SAP-Lens-2-<version>-<UTC time>-<commit>-win-x64/   the same layout as build-release.ps1 (server/, desktop/, symbols/, build-manifest.json, README.txt,
#                                                       SHA256SUMS), cross-published
#   SAP-Lens-2-<version>-<UTC time>-<commit>-linux-x64/ server/SapLens.Api (single file) and libe_sqlite3.so, symbols/, build-manifest.json, SHA256SUMS
# Self-contained single-file executables; no trimming, Native AOT or compression. Nothing is installed or started.
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
if [ -n "$dirty" ]; then echo "warning: the working tree has uncommitted changes; the manifest records source_dirty=true" >&2; fi
# Product version: product-version.json is the only source (docs/experiments/dotnet-backend/VERSIONING.md); a build never changes it.
version="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["version"])' "$root/product-version.json")"
echo "$version" | grep -Eq '^(0|[1-9][0-9]{0,4})\.(0|[1-9][0-9]{0,4})\.(0|[1-9][0-9]{0,4})(-(alpha|beta|rc)\.[1-9][0-9]{0,4})?$' \
  || { echo "product-version.json: '$version' is not MAJOR.MINOR.PATCH[-alpha.N|-beta.N|-rc.N]" >&2; exit 2; }
now="$(date -u +%s)"; stamp="$(date -u -d "@$now" +%Y%m%d-%H%M%S)"; built="$(date -u -d "@$now" +%Y-%m-%dT%H:%M:%SZ)"; shown="$(date -u -d "@$now" '+%Y-%m-%d %H:%M:%S')"
win="$output/SAP-Lens-2-$version-$stamp-${sha:0:7}-win-x64"; linux="$output/SAP-Lens-2-$version-$stamp-${sha:0:7}-linux-x64"
for release in "$win" "$linux"; do [ ! -e "$release" ] || { echo "$release exists; an existing release is never overwritten" >&2; exit 1; }; done
identity=(-p:SourceRevisionId="$sha")
(cd "$frontend" && npm ci --no-audit --no-fund && npm run build)
# The solution contains every project, the test project included, so `dotnet test --no-build` runs exactly what this build produced (with the UI
# embedded from the dist just built), never older binaries left in tests/*/bin.
dotnet build "$root/SapLens.slnx" -c Release "${identity[@]}"
if [ "$tests" = 1 ]; then
  if [ "$publish_tests" = 1 ]; then dotnet test "$root/tests/SapLens.Tests" -c Release --no-build
  else dotnet test "$root/tests/SapLens.Tests" -c Release --no-build --filter "Category!=Publish"; fi
fi
mkdir -p "$output"
# Windows single-file settings live in the project files; Linux passes the same ones explicitly (native library beside the executable, not extracted).
dotnet publish "$root/src/SapLens.Api" -c Release -r win-x64 -o "$win/server" "${identity[@]}"
dotnet publish "$root/src/SapLens.Desktop" -c Release -o "$win/desktop" "${identity[@]}"
dotnet publish "$root/src/SapLens.Api" -c Release -r linux-x64 --self-contained true -p:PublishSingleFile=true -p:IncludeNativeLibrariesForSelfExtract=false \
  -o "$linux/server" "${identity[@]}"
for release in "$win" "$linux"; do
  for part in server desktop; do
    [ -d "$release/$part" ] || continue
    mkdir -p "$release/symbols/$part"; find "$release/$part" -maxdepth 1 -name '*.pdb' -exec mv {} "$release/symbols/$part/" \;
  done
done
sed -e "s/{{VERSION}}/$version/" -e "s/{{SHA}}/$sha/" -e "s/{{BUILT}}/$shown/" -e "s/{{PLATFORM}}/Windows x64/" \
  "$root/scripts/release-README.txt" | sed 's/$/\r/' > "$win/README.txt"

# Artifact validation, manifests and checksums (same schema as build-release.ps1).
python3 - "$win" "$linux" "$sha" "${dirty:+true}" "$version" "$built" "$root/../.." <<'PY'
import hashlib, json, re, subprocess, sys
from pathlib import Path
win, linux, sha, dirty, version, built = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3], sys.argv[4] == 'true', sys.argv[5], sys.argv[6]
def run(*cmd): return subprocess.run(cmd, capture_output=True, text=True).stdout.strip()
def files(folder): return sorted(str(f.relative_to(folder)).replace('\\', '/') for f in folder.rglob('*') if f.is_file())
def check(cond, message):
    if not cond: sys.exit(f'release validation failed: {message}')
expected = {win: {'server': ['SapLens.Api.exe', 'e_sqlite3.dll'], 'desktop': ['SapLens2Prototype.exe']}, linux: {'server': ['SapLens.Api', 'libe_sqlite3.so']}}
for release, parts in expected.items():
    for part, names in parts.items():
        check(files(release / part) == sorted(names), f'{release.name}/{part} holds {files(release / part)}, expected {sorted(names)}')
for exe in (win / 'server/SapLens.Api.exe', win / 'desktop/SapLens2Prototype.exe', linux / 'server/SapLens.Api'):
    data = exe.read_bytes()
    check(f'{version}+{sha}'.encode() in data, f'product version and build identity {version}+{sha} missing in {exe.name}')
    check(b'SapLensUi/index.html' in data, f'index.html missing from the embedded UI of {exe.name}')
    check(b'SapLensUi/assets/' in data or b'SapLensUi/assets\\' in data, f'React UI assets missing in {exe.name}')
check(b'Microsoft.Extensions.Hosting.WindowsServices.dll' in (win / 'server/SapLens.Api.exe').read_bytes(), 'Windows service host missing')
def digest(path): return hashlib.sha256(path.read_bytes()).hexdigest()
for release, platform in ((win, 'win-x64'), (linux, 'linux-x64')):
    executables = {'server': 'server/SapLens.Api.exe', 'desktop': 'desktop/SapLens2Prototype.exe'} if platform == 'win-x64' else {'server': 'server/SapLens.Api'}
    artifacts = [dict(path=p, bytes=(release / p).stat().st_size, sha256=digest(release / p)) for p in files(release)]
    match = re.fullmatch(r'(\d+)\.(\d+)\.(\d+)(?:-(alpha|beta|rc)\.(\d+))?', version)
    ui_version = json.loads((Path(sys.argv[7]) / 'backend/resources/product-version.json').read_text())['version']   # recorded, never used as this version
    manifest = dict(schema=1, product='SAP Lens 2', version=version, channel=match[4] or 'stable', file_version=[int(match[1]), int(match[2]), int(match[3]), int(match[5] or 0)],
                    ui_source_version=ui_version, source_sha=sha, source_dirty=dirty,
                    source_committed_at=run('git', 'log', '-1', '--format=%cI'), branch=run('git', 'rev-parse', '--abbrev-ref', 'HEAD'), build_timestamp_utc=built,
                    target_platform=platform, dotnet_sdk=run('dotnet', '--version'), node=run('node', '--version'),
                    publish=dict(self_contained=True, single_file=True, trimmed=False, native_aot=False, compressed=False,
                                 server_native_libraries='beside the executable', **({'desktop_native_libraries': 'bundled, extracted to a temporary folder at start'} if platform == 'win-x64' else {})),
                    executables=executables, artifacts=artifacts)
    (release / 'build-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    sums = [f'{digest(release / p)}  ./{p}' for p in files(release) if p != 'SHA256SUMS']
    (release / 'SHA256SUMS').write_text('\n'.join(sums) + '\n')
    print(f'{release.name}: ' + ', '.join(f"{a['path']} {a['bytes'] / 1048576:.1f} MB" for a in artifacts if a['path'] in executables.values()))
PY
for release in "$win" "$linux"; do (cd "$release" && sha256sum --quiet -c SHA256SUMS); python3 "$root/../../scripts/check-secrets.py" --path "$release"; done
echo "Release build complete: $win and $linux. Nothing was installed or started."
