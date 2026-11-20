#!/usr/bin/env bash
# Tests of scripts/deploy/deploy-windows.sh with a fake ssh. The fake records the remote command and, in "run" mode, executes the encoded
# PowerShell locally with pwsh against a clone of this repository, so validation, quoting, encoding, commit locking, git archive of the locked
# deployment scripts and the Windows entry script (Status and DryRun paths) run for real. Nothing connects anywhere; no service is touched.
# Run: bash backend/scripts/tests/deploy-windows.test.sh   (needs git and pwsh)
set -uo pipefail
for tool in git pwsh iconv base64; do
  command -v "$tool" >/dev/null || { echo "Infrastructure: missing $tool (run this Linux harness with its documented prerequisites)"; exit 2; }
done
here=$(cd "$(dirname "$0")" && pwd)
script="$here/../deploy/deploy-windows.sh"
repo_root=$(cd "$here/../../.." && pwd)
work=$(mktemp -d)
failures=0; count=0
cleanup() {
  if [ "$failures" -gt 0 ]; then
    artifacts="$repo_root/build/test-artifacts/ssh-$(basename "$work")"
    mkdir -p "$artifacts"
    for name in out command.ps1 ssh-args state; do
      [ ! -e "$work/$name" ] || cp -R "$work/$name" "$artifacts/"
    done
    echo "Failed SSH diagnostics retained: $artifacts"
  fi
  rm -rf "$work"
}
trap cleanup EXIT
check() { count=$((count + 1)); if eval "$2"; then echo "ok    $1"; else echo "FAIL  $1"; [ ! -f "$work/out" ] || cat "$work/out"; failures=$((failures + 1)); fi; }

# Fake ssh: FAKE_SSH=record writes the decoded command and exits with FAKE_EXIT; FAKE_SSH=run executes it with pwsh.
mkdir -p "$work/bin"
cat > "$work/bin/ssh" <<'FAKE'
#!/usr/bin/env bash
encoded="${@: -1}"
printf '%s\n' "$*" > "$FAKE_DIR/ssh-args"
printf '%s' "$encoded" | base64 -d | iconv -f UTF-16LE -t UTF-8 > "$FAKE_DIR/command.ps1"
if [ "${FAKE_SSH:-record}" = run ]; then exec pwsh -NoProfile -NonInteractive -EncodedCommand "$encoded"; fi
echo "AUTHLENS-RESULT: {\"exit\":${FAKE_EXIT:-0}}"
exit "${FAKE_EXIT:-0}"
FAKE
chmod +x "$work/bin/ssh"
export PATH="$work/bin:$PATH" FAKE_DIR="$work" XDG_STATE_HOME="$work/state"

# The "Windows host": a clone of this repository whose origin carries the branch, and a deployment configuration with local paths.
tip=$(git -C "$repo_root" rev-parse HEAD)
# A synthetic remote makes this fixture work on main CI too; never update a real branch.
git clone -q --bare --no-hardlinks "$repo_root" "$work/origin.git"
git --git-dir="$work/origin.git" update-ref refs/heads/experiment/dotnet-backend "$tip"
git clone -q --no-hardlinks "$work/origin.git" "$work/host-repo"
mkdir -p "$work"/{deploy,releases,backups,data,tls}; : > "$work/tls/server.pfx"; : > "$work/tls/cert-password"
cat > "$work/deploy.json" <<JSON
{"RepositoryPath":"$work/host-repo","WorkRoot":"$work/deploy","ReleasesRoot":"$work/releases","BackupRoot":"$work/backups","ListenAddress":"192.0.2.10",
 "Port":18795,"AllowedHosts":["lens.example.com"],"TrustedProxies":["192.0.2.1"],"DataDirectory":"$work/data","CertificatePath":"$work/tls/server.pfx",
 "CertificatePasswordFile":"$work/tls/cert-password"}
JSON
base=(--host 192.0.2.10 --user deployer --repo "$work/host-repo" --config "$work/deploy.json")

# Input validation (exit 64, ssh never called).
run() { rm -f "$work/ssh-args"; "$script" "$@" > "$work/out" 2>&1 < /dev/null; echo $?; }
check 'host is required' '[ "$(run --user u --repo C:\\r)" = 64 ]'
check 'repository is required' '[ "$(run --host h --user u)" = 64 ]'
check 'main is refused' '[ "$(run "${base[@]}" --mode build --branch main)" = 64 ]'
check 'a non-hex commit is refused' '[ "$(run "${base[@]}" --mode build --commit "abc;rm")" = 64 ]'
check 'a quote in a path is refused' '[ "$(run --host h --user u --repo "C:\\x'"'"'y")" = 64 ]'
check 'an unknown mode is refused' '[ "$(run "${base[@]}" --mode wipe)" = 64 ]'
check 'deploy without --yes and without a terminal is refused before ssh' '[ "$(run "${base[@]}" --mode deploy)" = 64 ] && [ ! -e "$work/ssh-args" ]'

# Command construction (fake ssh records only).
export FAKE_SSH=record FAKE_EXIT=0
code=$(run "${base[@]}" --mode deploy --yes --tests full --adopt-service --commit "${tip:0:12}")
check 'deploy passes action, tests, confirmation, adoption and the locked commit' \
  '[ "$code" = 0 ] && grep -q -- "-Action Deploy" "$work/command.ps1" && grep -q -- "-Tests full -Yes -AdoptService" "$work/command.ps1" && grep -q "\$commit = '"'"'${tip:0:12}'"'"'" "$work/command.ps1" && grep -q -- "-Commit \$sha" "$work/command.ps1"'
check 'ssh runs non-interactively with keepalives and PowerShell 5.1' 'grep -q -- "-o BatchMode=yes -o ServerAliveInterval=15" "$work/ssh-args" && grep -q "powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -EncodedCommand" "$work/ssh-args"'
check 'no secret-like option is ever sent' '! grep -qiE -- "--cert-password |--token|password=" "$work/command.ps1"'
code=$(run "${base[@]}" --mode restore --backup 'C:\transfer\SAP-Lens-manual.slbak' --key-file 'C:\transfer\recovery.key' --yes)
check 'restore is a confirmed service change with the backup and key paths' '[ "$code" = 0 ] && grep -q -- "-Action Restore" "$work/command.ps1" && grep -q -- "-Backup .C:.transfer.SAP-Lens-manual.slbak." "$work/command.ps1" && grep -q -- "-KeyFile " "$work/command.ps1" && grep -q -- " -Yes" "$work/command.ps1"'
check 'restore without --backup or --yes is refused before ssh' '[ "$(run "${base[@]}" --mode restore --yes)" = 64 ] && [ "$(run "${base[@]}" --mode restore --backup C:\\b.slbak)" = 64 ] && [ ! -e "$work/ssh-args" ]'
export FAKE_EXIT=4
code=$(run "${base[@]}" --mode recover --yes)
check 'the remote exit code is returned and manual action is announced' '[ "$code" = 4 ] && grep -q "MANUAL ACTION REQUIRED" "$work/out"'
export FAKE_EXIT=0

# End to end through PowerShell (fake ssh runs the command with pwsh).
export FAKE_SSH=run
code=$(run "${base[@]}" --mode status)
check 'status runs the locked commit'"'"'s deployment script and reports no service on a host without one' \
  '[ "$code" = 0 ] && grep -q "locked commit $tip" "$work/out" && grep -q "\"service_model\":\"none\"" "$work/out"'
check 'a local log of the run is kept' '[ -n "$(ls "$work/state/authlens-deploy"/*-status-192.0.2.10.log 2>/dev/null)" ]'
code=$(run "${base[@]}" --mode dry-run)
check 'dry-run locks the branch tip and changes nothing' \
  '[ "$code" = 0 ] && grep -q "\"dry_run\":true" "$work/out" && grep -q "\"commit\":\"$tip\"" "$work/out" && [ -z "$(ls -A "$work/releases")" ] && [ -z "$(ls -A "$work/backups")" ]'
code=$(run "${base[@]}" --mode dry-run --commit 0000000000000000000000000000000000000000)
check 'a commit that is not on the branch is refused remotely' '[ "$code" != 0 ]'

# A commit from before AuthLens (it carries Deploy-SapLens.ps1, not Deploy-AuthLens.ps1) is refused on the host; nothing of it runs.
legacy=$(git -C "$repo_root" log -1 --format=%H "$tip" -- backend/scripts/deploy/Deploy-SapLens.ps1)
git -C "$repo_root" cat-file -e "$legacy:backend/scripts/deploy/Deploy-SapLens.ps1" 2>/dev/null || legacy=$(git -C "$repo_root" rev-parse "$legacy^")   # the rename commit itself
code=$(run --host 192.0.2.10 --user deployer --repo "$work/host-repo" --config "$work/deploy.json" --mode status --commit "$legacy")
check 'a commit from before AuthLens is refused' '[ "$code" != 0 ] && grep -q "predates AuthLens" "$work/out"'

echo "$((count - failures)) of $count checks passed"
[ "$failures" = 0 ]
