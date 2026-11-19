#!/usr/bin/env bash
# Build, validate and deploy AuthLens on a Windows host over SSH (the Windows side is Deploy-AuthLens.ps1).
#
#   scripts/deploy/deploy-windows.sh --host HOST --user USER [options]
#
# Modes (--mode):
#   status           service model, state, linked release, readiness, interrupted runs (default)
#   health           readiness and identity of the running server
#   build            fetch, lock the commit, build in an isolated worktree with the selected tests, verify; no service change
#   dry-run          lock the commit and show the deployment plan; no build, backup or service change
#   deploy           build, test, verify, back up, stop, switch, start, verify; roll back when safe (needs --yes)
#   rollback         return to the previous release when it can open the data (needs --yes)
#   recover          finish an interrupted deployment (needs --yes)
#   install-service  create or (--reconfigure) update the Windows service from the host's configuration (needs --yes)
#   restore          restore an AuthLens or SAP Lens backup into this installation (--backup, --key-file; needs --yes)
#
# Options:
#   --branch NAME        branch to build (default experiment/dotnet-backend); main and work are refused
#   --commit SHA         exact commit on that branch (default: the branch tip, resolved once and locked)
#   --tests focused|full test selection before deployment (default focused)
#   --repo PATH          repository clone on the Windows host (or $AUTHLENS_WINDOWS_REPO); required
#   --config PATH        deployment configuration on the Windows host (default there: C:\ProgramData\AuthLens\config\deploy.json)
#   --backup PATH        with restore: the .slbak backup on the Windows host
#   --key-file PATH      with restore: the recovery key that sealed it, on the Windows host
#   --port N             SSH port (default 22)
#   --to-release PATH    rollback target folder on the host
#   --adopt-service      first managed deployment of a service that was installed by hand (same arguments)
#   --first-install      first deployment: also installs the service
#   --reconfigure        with install-service: update an existing service
#   --yes                confirm a mode that changes the service (otherwise asked interactively, refused without a terminal)
#   --log-dir DIR        local copy of the remote output (default ${XDG_STATE_HOME:-~/.local/state}/authlens-deploy)
#
# Authentication is SSH keys or an agent only (BatchMode): no password is asked for, stored or passed. No secret is sent: the Windows side reads
# its configuration (paths, addresses, host names) and the server reads its certificate password file itself.
# Exit codes: the Windows script's (0 ok, 1 failed or rolled back, 2 refused, 4 manual action required), 64 usage, 255 SSH failure.
set -euo pipefail

host=''; user=''; port=22; mode='status'; branch='experiment/dotnet-backend'; commit=''; tests='focused'
repo="${AUTHLENS_WINDOWS_REPO:-}"; config=''; to_release=''; backup=''; key_file=''; yes=0; adopt=0; first=0; reconfigure=0
log_dir="${XDG_STATE_HOME:-$HOME/.local/state}/authlens-deploy"

usage() { sed -n '2,/^# Exit codes/p' "$0" | sed 's/^# \{0,1\}//'; exit 64; }
die() { echo "deploy-windows: $*" >&2; exit 64; }
need() { [ $# -ge 2 ] && [ -n "$2" ] || die "$1 needs a value"; }

while [ $# -gt 0 ]; do
  case "$1" in
    --host) need "$@"; host=$2; shift 2 ;;
    --user) need "$@"; user=$2; shift 2 ;;
    --port) need "$@"; port=$2; shift 2 ;;
    --mode) need "$@"; mode=$2; shift 2 ;;
    --branch) need "$@"; branch=$2; shift 2 ;;
    --commit) need "$@"; commit=$2; shift 2 ;;
    --tests) need "$@"; tests=$2; shift 2 ;;
    --repo) need "$@"; repo=$2; shift 2 ;;
    --config) need "$@"; config=$2; shift 2 ;;
    --to-release) need "$@"; to_release=$2; shift 2 ;;
    --backup) need "$@"; backup=$2; shift 2 ;;
    --key-file) need "$@"; key_file=$2; shift 2 ;;
    --log-dir) need "$@"; log_dir=$2; shift 2 ;;
    --yes) yes=1; shift ;;
    --adopt-service) adopt=1; shift ;;
    --first-install) first=1; shift ;;
    --reconfigure) reconfigure=1; shift ;;
    -h|--help) usage ;;
    *) die "unknown option $1 (see --help)" ;;
  esac
done

# Strict input validation: every value ends up inside a PowerShell single-quoted literal, and none may change the command's meaning.
[ -n "$host" ] || die '--host is required'
[ -n "$user" ] || die '--user is required'
[ -n "$repo" ] || die '--repo (or AUTHLENS_WINDOWS_REPO) is required'
[[ "$host" =~ ^[A-Za-z0-9.:-]+$ ]] || die 'invalid --host'
[[ "$user" =~ ^[A-Za-z0-9._\\-]+$ ]] || die 'invalid --user'
[[ "$port" =~ ^[0-9]{1,5}$ ]] || die 'invalid --port'
[[ "$branch" =~ ^[A-Za-z0-9._/-]+$ ]] || die 'invalid --branch'
case "$branch" in main|work) die "deployments are never built from $branch" ;; esac
[ -z "$commit" ] || [[ "$commit" =~ ^[0-9a-f]{7,40}$ ]] || die '--commit must be a hexadecimal SHA'
case "$tests" in focused|full) ;; *) die '--tests must be focused or full' ;; esac
for value in "$repo" "$config" "$to_release" "$backup" "$key_file"; do
  [[ "$value" != *$'\n'* && "$value" != *"'"* ]] || die 'paths may not contain quotes or line breaks'
done
case "$mode" in
  status) action='Status' ;; health) action='Health' ;; build) action='Build' ;; dry-run) action='Deploy' ;; deploy) action='Deploy' ;;
  rollback) action='Rollback' ;; recover) action='Recover' ;; install-service) action='InstallService' ;; restore) action='Restore' ;;
  *) die "unknown --mode $mode" ;;
esac

changing=0
case "$mode" in deploy|rollback|recover|install-service|restore) changing=1 ;; esac
[ "$mode" != restore ] || [ -n "$backup" ] || die 'restore needs --backup <path of the .slbak file on the Windows host>'
if [ "$changing" = 1 ] && [ "$yes" != 1 ]; then
  if [ -t 0 ]; then
    read -r -p "Mode '$mode' restarts or changes the AuthLens service on $host. Continue? [y/N] " answer
    [[ "$answer" =~ ^[Yy]$ ]] || { echo 'cancelled'; exit 2; }
  else
    die "mode '$mode' changes the service: pass --yes (review --mode status or --mode dry-run first)"
  fi
fi

# PowerShell single-quoted literal.
ps() { printf "'%s'" "${1//\'/\'\'}"; }

arguments="-Action $action"
[ -n "$config" ] && arguments+=" -ConfigFile $(ps "$config")"
case "$mode" in
  build|deploy|dry-run) arguments+=" -Branch $(ps "$branch") -Tests $tests" ;;
esac
[ "$mode" = dry-run ] && arguments+=' -DryRun'
[ "$changing" = 1 ] && arguments+=' -Yes'
[ "$adopt" = 1 ] && arguments+=' -AdoptService'
[ "$first" = 1 ] && arguments+=' -FirstInstall'
[ "$reconfigure" = 1 ] && arguments+=' -Reconfigure'
[ -n "$to_release" ] && arguments+=" -ToRelease $(ps "$to_release")"
[ -n "$backup" ] && arguments+=" -Backup $(ps "$backup")"
[ -n "$key_file" ] && arguments+=" -KeyFile $(ps "$key_file")"

# The Windows side runs the deployment scripts of the locked commit itself (git archive of that commit), never a copy from a developer checkout.
read -r -d '' bootstrap <<PWSH || true
\$ErrorActionPreference = 'Stop'
\$repo = $(ps "$repo"); \$branch = $(ps "$branch"); \$commit = $(ps "$commit")
\$git = { param([string[]]\$a) \$ErrorActionPreference = 'Continue'; \$o = & git -C \$repo @a 2>&1; if (\$LASTEXITCODE -ne 0) { throw ("git " + (\$a -join ' ') + ": " + ((\$o | Out-String).Trim())) }; @(\$o | ForEach-Object { "\$_".Trim() } | Where-Object { \$_ }) }
\$null = & \$git @('fetch', '--quiet', 'origin', "refs/heads/\${branch}:refs/remotes/origin/\$branch")
\$sha = @(& \$git @('rev-parse', \$(if (\$commit) { "\$commit^{commit}" } else { "origin/\$branch^{commit}" })))[0]
Write-Host "locked commit \$sha (\$branch)"
\$dir = Join-Path ([System.IO.Path]::GetTempPath()) ('authlens-deploy-' + \$sha.Substring(0, 12))
\$source = 'backend/scripts/deploy'
if (-not (& \$git @('ls-tree', '--name-only', \$sha, '--', "\$source/Deploy-AuthLens.ps1"))) { throw "commit \$sha predates AuthLens (no backend/scripts/deploy/Deploy-AuthLens.ps1); AuthLens deploys AuthLens commits only" }
\$deploy = Join-Path \$dir \$source
if (-not (Test-Path -LiteralPath \$deploy)) {
  New-Item -ItemType Directory -Force \$dir | Out-Null
  \$null = & \$git @('archive', '--format=zip', '-o', (Join-Path \$dir 'deploy.zip'), \$sha, \$source)
  Expand-Archive -LiteralPath (Join-Path \$dir 'deploy.zip') -DestinationPath \$dir -Force
}
\$script = Join-Path \$deploy 'Deploy-AuthLens.ps1'
& \$script $arguments -Commit \$sha
exit \$LASTEXITCODE
PWSH

encoded=$(printf '%s' "$bootstrap" | iconv -f UTF-8 -t UTF-16LE | base64 -w0)
mkdir -p "$log_dir"
log="$log_dir/$(date -u +%Y%m%dT%H%M%SZ)-$mode-$host.log"

interrupted() {
  echo >&2
  echo "Interrupted. The Windows side records every phase in its deployment journal. Check, then recover if needed:" >&2
  echo "  $0 --host $host --user $user --mode status" >&2
  echo "  $0 --host $host --user $user --mode recover --yes    # only if status reports recovery_needed" >&2
  exit 130
}
trap interrupted INT TERM

echo "AuthLens deployment: mode $mode on $user@$host (log: $log)"
set +e
ssh -o BatchMode=yes -o ServerAliveInterval=15 -o ServerAliveCountMax=4 -p "$port" "$user@$host" \
  powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -EncodedCommand "$encoded" 2>&1 | tee "$log"
code=${PIPESTATUS[0]}
set -e
result=$(grep -aE 'AUTHLENS-RESULT: ' "$log" | tail -1 || true)
[ -n "$result" ] || echo "No result line from the Windows host (SSH or PowerShell failure, exit $code); see $log." >&2
case "$code" in
  0) echo "done: $mode succeeded" ;;
  1) echo "failed: nothing changed, or the deployment was rolled back and the previous release is ready (exit 1)" >&2 ;;
  2) echo "refused before any change (exit 2)" >&2 ;;
  4) echo "MANUAL ACTION REQUIRED (exit 4): see RECOVERY-REQUIRED.txt in the run folder named in the log" >&2 ;;
esac
exit "$code"
