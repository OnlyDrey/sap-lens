#!/usr/bin/env sh
# Offline Docker lifecycle. Requires Docker Compose v2 and standard Linux tools.
set -eu
umask 077
stage=prerequisites
trap 'result=$?; if [ "$result" -ne 0 ]; then printf "Lifecycle operation failed during %s; inspect the preceding message. Existing state and backups are retained.\n" "$stage" >&2; fi' 0
source_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
action=${1:-help}
root=${2:-}
fail() { printf '%s\n' "$*" >&2; exit 1; }
if [ "$action" = help ] || [ -z "$root" ]; then
    printf '%s\n' 'Usage: sh manage.sh ACTION /absolute/installation [OPTION]' \
      'Actions: install [--no-start], upgrade, start, stop, restart, status, backup,' \
      'restore ARCHIVE --confirm-restore, uninstall [--purge-data --confirm-purge].' \
      'Run install/upgrade from a freshly extracted checksum-verified package.'
    [ "$action" = help ] && exit 0
    exit 1
fi
case "$action" in install|upgrade|start|stop|restart|status|backup|restore|uninstall) ;; *) fail 'Unknown lifecycle action.' ;; esac
if [ "$action" = install ]; then case "${3:-}" in ''|--no-start) ;; *) fail 'Unknown installation option.' ;; esac; fi
case "$root:$source_dir" in *'
'*) fail 'Control characters are not supported in deployment paths.' ;; esac
case "$root" in *:*) fail 'Colon characters are not supported in Docker bind paths.' ;; esac
for command in docker sha256sum realpath sed grep; do command -v "$command" >/dev/null 2>&1 || fail "Missing prerequisite: $command"; done
docker compose version >/dev/null
case "$root" in /*) ;; *) fail 'Use an absolute, dedicated installation directory.' ;; esac
[ "$root" = "$(realpath -m -- "$root")" ] || fail 'Use a canonical installation path without links or traversal.'
case "$root" in /|/etc|/var|/var/lib|/usr|/opt|/home|/tmp|"${HOME:-/}") fail 'Use a dedicated application directory.' ;; esac
project=sap-lens-$(printf '%s' "$root" | sha256sum | cut -c1-12)
compose() { docker compose --project-directory "$root" --env-file "$root/compose.env" -p "$project" -f "$root/compose.yml" "$@"; }
image_run() { docker run --rm --network none --read-only --cap-drop=ALL --security-opt=no-new-privileges --entrypoint python "$image" "$@"; }
managed() {
    [ -f "$root/.sap-lens-project" ] && [ ! -L "$root/.sap-lens-project" ] || fail 'No recognized managed installation.'
    [ "$(cat "$root/.sap-lens-project")" = "$project" ] || fail 'Installation identity does not match its directory.'
    image=$(cat "$root/image.id")
    printf '%s\n' "$image" | grep -Eq '^sha256:[0-9a-f]{64}$' || fail 'Invalid installed image identity.'
    docker image inspect "$image" >/dev/null
}
volume_name() {
    volume=$(compose config --format json | docker run --rm -i --network none --read-only --cap-drop=ALL --security-opt=no-new-privileges --entrypoint python "$image" -c 'import json,sys;v=json.load(sys.stdin)["volumes"]["sap-lens-data"];assert not v.get("external");print(v["name"])')
    printf '%s\n' "$volume" | grep -Eq '^[a-zA-Z0-9][a-zA-Z0-9_.-]+$' || fail 'Unrecognized data volume name.'
}
owned_volume() {
    volume_name
    [ "$(docker volume inspect --format '{{index .Labels "com.docker.compose.project"}}' "$volume")" = "$project" ] || fail 'Data volume belongs to another installation.'
    [ "$(docker volume inspect --format '{{index .Labels "com.docker.compose.volume"}}' "$volume")" = sap-lens-data ] || fail 'Data volume ownership is not recognized.'
}
ready() {
    stage=readiness
    compose up -d --no-build --pull never
    count=0
    while [ "$count" -lt 60 ]; do
        container=$(compose ps -q sap-lens)
        if [ -n "$container" ] && [ "$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{end}}' "$container")" = healthy ]; then
            printf '%s\n' 'SAP Lens container is healthy. Native/browser acceptance remains a separate check.'
            return
        fi
        count=$((count+1)); sleep 1
    done
    compose stop
    fail 'Readiness failed; container stopped. Preserve the backup and inspect private logs. Binary-only rollback is not data recovery.'
}
backup() {
    stage=backup
    owned_volume
    compose stop
    backup_dir=$root-backups
    mkdir -p -- "$backup_dir"
    backup_name=SAP-Lens-$(date -u +%Y%m%dT%H%M%SZ)-$$.tar.gz
    docker run --rm --network none --read-only --user 0:0 --cap-drop=ALL --cap-add=DAC_OVERRIDE --cap-add=CHOWN --security-opt=no-new-privileges \
      -v "$volume:/data" -v "$root:/configuration:ro" -v "$backup_dir:/backups" --entrypoint python "$image" \
      backend/maintenance.py backup --data /data --config-dir /configuration --output "/backups/$backup_name" --mode server --application-version "$(cat "$root/version.txt")"
    docker run --rm --network none --read-only --user 0:0 --cap-drop=ALL --cap-add=DAC_OVERRIDE --cap-add=CHOWN --security-opt=no-new-privileges \
      -v "$backup_dir:/backups" --entrypoint python "$image" -c 'import os,sys;os.chown("/backups/"+sys.argv[1],int(sys.argv[2]),int(sys.argv[3]))' "$backup_name" "$(id -u)" "$(id -g)"
    printf '%s\n' "Private backup: $backup_dir/$backup_name" 'Service remains stopped; use start after review.'
}
load_package() {
    stage=package-verification
    [ -f "$source_dir/image.tar" ] && [ -f "$source_dir/package-manifest.json" ] || fail 'Use the extracted offline package, not a source checkout.'
    expected=$(sed -n 's/^[[:space:]]*"image.tar": "\([a-f0-9]\{64\}\)".*/\1/p' "$source_dir/package-manifest.json")
    [ "${#expected}" -eq 64 ] || fail 'Missing image digest. Verify the package sidecar before extraction.'
    (cd "$source_dir" && printf '%s  image.tar\n' "$expected" | sha256sum -c -)
    tag=$(sed -n 's/^    image: \(sap-lens:[a-zA-Z0-9.+-]*\)$/\1/p' "$source_dir/compose.yml")
    [ -n "$tag" ] || fail 'Package must reference one local SAP Lens image.'
    docker load -i "$source_dir/image.tar"
    new_image=$(docker image inspect --format '{{.Id}}' "$tag")
    # No host Python: validate the complete extracted package in the loaded image,
    # with a read-only mount, the operator UID and no network or Docker socket.
    new_version=$(docker run --rm --network none --read-only --cap-drop=ALL --security-opt=no-new-privileges --user "$(id -u):$(id -g)" \
      -v "$source_dir:/bundle:ro" --entrypoint python "$new_image" -c 'import hashlib,json,pathlib,sys;sys.path.insert(0,"backend");from version import BUILD_INFO;r=pathlib.Path("/bundle");m=json.loads((r/"package-manifest.json").read_text());assert m["platform"]=="Linux-Docker-amd64" and m["identity"]==BUILD_INFO;assert not any(p.is_symlink() for p in r.rglob("*"));actual={p.relative_to(r).as_posix():hashlib.file_digest(p.open("rb"),"sha256").hexdigest() for p in r.rglob("*") if p.is_file() and p!=r/"package-manifest.json"};assert actual==m["files"];print(BUILD_INFO["version"])')
}
case "$action" in
install)
    if [ -f "$root/.sap-lens-project" ]; then managed; if [ "${3:-}" != --no-start ]; then ready; fi; exit 0; fi
    [ ! -e "$root" ] || [ -z "$(ls -A -- "$root")" ] || fail 'Installation requires an empty directory; use upgrade for existing managed data.'
    [ "$source_dir" != "$root" ] || fail 'Keep extracted binaries separate from installation configuration.'
    load_package
    stage=installation
    mkdir -p -- "$root/local-config"
    chmod 700 "$root"
    cp "$source_dir/compose.yml" "$root/compose.yml"
    cp "$source_dir/compose.env.example" "$root/compose.env"
    cp "$source_dir/manage.sh" "$root/manage.sh"
    cp "$source_dir/LICENSE.md" "$root/LICENSE.md"
    sed "s|^    image: .*|    image: $new_image|" "$root/compose.yml" > "$root/compose.pending"
    mv "$root/compose.pending" "$root/compose.yml"
    printf '%s\n' "$new_image" > "$root/image.id"
    printf '%s\n' "$new_version" > "$root/version.txt"
    printf '%s\n' "$project" > "$root/.sap-lens-project"
    docker run --rm --network none --read-only --user 0:0 --cap-drop=ALL --cap-add=DAC_OVERRIDE --cap-add=CHOWN --security-opt=no-new-privileges \
      -v "$root/local-config:/configuration" --entrypoint python "$new_image" -c 'import os,pathlib,secrets,sys;p=pathlib.Path("/configuration/server-access.secret");f=p.open("x");p.chmod(0o640);os.chown(p,int(sys.argv[1]),10001);f.write(secrets.token_urlsafe(48)+"\n");f.close()' "$(id -u)"
    managed
    if [ "${3:-}" = --no-start ]; then
        volume_name
        docker volume create --label "com.docker.compose.project=$project" --label com.docker.compose.volume=sap-lens-data "$volume" >/dev/null
        printf '%s\n' 'Installed without starting; empty managed volume is available for confirmed restore.'
    elif [ -n "${3:-}" ]; then fail 'Unknown installation option.'
    else ready; fi
    ;;
upgrade)
    managed; previous=$image; load_package
    image=$new_image
    image_run backend/maintenance.py version-check --application-version "$(cat "$root/version.txt")" --target-version "$new_version"
    image=$previous
    compose config --quiet
    backup
    stage=activation
    sed "s|^    image: $previous$|    image: $new_image|" "$root/compose.yml" > "$root/compose.pending"
    grep -q "^    image: $new_image$" "$root/compose.pending" || fail 'Administrator image configuration differs; review manually.'
    mv "$root/compose.pending" "$root/compose.yml"
    printf '%s\n' "$new_image" > "$root/image.id"
    printf '%s\n' "$new_version" > "$root/version.txt"
    image=$new_image; ready
    cp "$source_dir/manage.sh" "$root/manage.sh"
    ;;
start) managed; ready ;;
stop) managed; compose stop ;;
restart) managed; compose stop; ready ;;
status) managed; compose ps; printf 'Installed version: '; cat "$root/version.txt" ;;
backup) managed; backup ;;
restore)
    stage=restore
    managed; owned_volume
    [ "${4:-}" = --confirm-restore ] && [ -f "${3:-}" ] || fail 'Restore requires ARCHIVE --confirm-restore and an empty managed data volume.'
    compose stop
    archive=$(realpath -- "$3"); recovery=$root-recovered-configuration-$(date -u +%Y%m%dT%H%M%SZ)-$$
    mkdir -m 700 -- "$recovery"
    docker run --rm --network none --read-only --user 0:0 --cap-drop=ALL --cap-add=DAC_OVERRIDE --cap-add=CHOWN --security-opt=no-new-privileges \
      -v "$volume:/data" -v "$archive:/backup.tar.gz:ro" -v "$recovery:/restored-configuration" --entrypoint python "$image" \
      -c 'import os,sys;sys.path.insert(0,"backend");import maintenance;maintenance.restore("/backup.tar.gz","/data","server",sys.argv[1],"/restored-configuration",True);from pathlib import Path
for p in [Path("/data"),*Path("/data").rglob("*")]:os.chown(p,10001,10001)
for p in [Path("/restored-configuration"),*Path("/restored-configuration").rglob("*")]:os.chown(p,int(sys.argv[2]),int(sys.argv[3]))' "$(cat "$root/version.txt")" "$(id -u)" "$(id -g)"
    printf '%s\n' "Data restored; configuration staged privately at $recovery." 'Review/apply required configuration and secret-file permissions, then start and verify. Existing configuration was not overwritten.'
    ;;
uninstall)
    managed
    if [ -n "${3:-}" ]; then [ "$3" = --purge-data ] && [ "${4:-}" = --confirm-purge ] || fail 'Purge requires --purge-data --confirm-purge.'; owned_volume; fi
    compose down
    if [ "${3:-}" = --purge-data ]; then docker volume rm "$volume"; printf '%s\n' 'Managed data volume explicitly removed. Configuration, backups, external sources and secrets retained.'
    else printf '%s\n' 'Containers/network removed. Data, configuration, secrets, backups and images preserved.'; fi
    ;;
esac
