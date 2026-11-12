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
      'Actions: install [--no-start] [--hostname NAME] [--port N] [--tls-cert FILE --tls-key FILE],' \
      'upgrade [--migrate-legacy --new-administrator NAME [--hostname NAME]], start, stop, restart, status,' \
      'activation-code, recover-administrator USERNAME, backup,' \
      'restore ARCHIVE --confirm-restore [--secret-stdin] [--allow-legacy], uninstall [--purge-data --confirm-purge].' \
      'Run install/upgrade from a freshly extracted checksum-verified package.' \
      'Accounts are created in SAP Lens over HTTPS after a local one-time activation code; there is no default password.'
    [ "$action" = help ] && exit 0
    exit 1
fi
case "$action" in install|upgrade|start|stop|restart|status|backup|restore|uninstall|activation-code|recover-administrator) ;; *) fail 'Unknown lifecycle action.' ;; esac
# Options of install and upgrade, validated before Docker or the file system is touched.
no_start=; hostname=localhost; port=18743; tls_cert=; tls_key=; migrate_legacy=; new_administrator=
if [ "$action" = install ] || [ "$action" = upgrade ]; then
    shift 2
    while [ "$#" -gt 0 ]; do
        case "$action:$1" in
            install:--no-start) no_start=1 ;;
            install:--hostname|upgrade:--hostname) [ "$#" -ge 2 ] || fail 'Missing host name.'; hostname=$2; shift ;;
            install:--port) [ "$#" -ge 2 ] || fail 'Missing port.'; port=$2; shift ;;
            install:--tls-cert) [ "$#" -ge 2 ] || fail 'Missing certificate file.'; tls_cert=$2; shift ;;
            install:--tls-key) [ "$#" -ge 2 ] || fail 'Missing private key file.'; tls_key=$2; shift ;;
            upgrade:--migrate-legacy) migrate_legacy=1 ;;
            upgrade:--new-administrator) [ "$#" -ge 2 ] || fail 'Missing administrator name.'; new_administrator=$2; shift ;;
            install:*) fail 'Unknown installation option.' ;;
            *) fail 'Unknown upgrade option.' ;;
        esac
        shift
    done
    set -- "$action" "$root"
    printf '%s\n' "$hostname" | grep -Eq '^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)*$' || fail 'Use a lower-case DNS name or IPv4 address as host name; wildcards are not supported.'
    printf '%s\n' "$port" | grep -Eq '^[1-9][0-9]{0,4}$' && [ "$port" -le 65535 ] || fail 'Use a port between 1 and 65535.'
    if [ -n "$tls_cert$tls_key" ]; then
        [ -n "$tls_cert" ] && [ -n "$tls_key" ] || fail 'Supply both --tls-cert and --tls-key.'
        [ -f "$tls_cert" ] && [ -f "$tls_key" ] || fail 'The supplied certificate and private key must be existing files.'
        tls_cert=$(realpath -- "$tls_cert"); tls_key=$(realpath -- "$tls_key")
        case "$tls_cert$tls_key" in *:*) fail 'Colon characters are not supported in Docker bind paths.' ;; esac
    fi
    if [ -n "$new_administrator" ]; then printf '%s\n' "$new_administrator" | grep -Eq '^[A-Za-z0-9_.@-]{1,100}$' || fail 'Use 1-100 letters, digits or _ . @ - for the administrator name.'; fi
fi
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
# Host-only files: created inside the image without network access, never replaced, never printed. See backend/container_setup.py.
host_setup() {
    setup_image=$1; shift
    docker run --rm --network none --read-only --user 0:0 --cap-drop=ALL --cap-add=DAC_OVERRIDE --cap-add=CHOWN --security-opt=no-new-privileges \
      -v "$root/local-config:/configuration" "$@"
}
host_files() {
    # $1 image. Each file is created only when it is missing; an existing certificate, key or token stays untouched.
    mkdir -p -- "$root/local-config"; chmod 700 "$root/local-config"
    if [ ! -e "$root/local-config/backup.key" ]; then
        host_setup "$1" --entrypoint python "$1" backend/container_setup.py backup-key --directory /configuration --owner "$(id -u)" --group 10001 >/dev/null
        printf '%s\n' "Backup recovery key created: $root/local-config/backup.key" 'Keep a separate, protected copy: encrypted backups cannot be restored without it.'
    fi
    if [ ! -e "$root/local-config/proxy-token.secret" ]; then
        host_setup "$1" --entrypoint python "$1" backend/container_setup.py proxy-token --directory /configuration --owner "$(id -u)" --group 10001 >/dev/null
    fi
    if [ -e "$root/local-config/tls.crt" ] || [ -e "$root/local-config/tls.key" ]; then
        [ -f "$root/local-config/tls.crt" ] && [ -f "$root/local-config/tls.key" ] || fail 'Only one of tls.crt and tls.key exists; restore the pair. Nothing was replaced.'
        printf '%s\n' 'Existing TLS certificate and private key kept unchanged.'
    elif [ -n "$tls_cert" ]; then
        host_setup "$1" -v "$tls_cert:/supplied/tls.crt:ro" -v "$tls_key:/supplied/tls.key:ro" --entrypoint python "$1" backend/container_setup.py install-tls \
          --directory /configuration --certificate /supplied/tls.crt --key /supplied/tls.key --host "$hostname" --owner "$(id -u)" --group 10001
        printf '%s\n' 'Administrator-supplied TLS certificate installed (details above).'
    else
        host_setup "$1" --entrypoint python "$1" backend/container_setup.py generate-tls --directory /configuration --host "$hostname" --owner "$(id -u)" --group 10001
        printf '%s\n' 'WARNING: a SELF-SIGNED TLS certificate was generated (fingerprint above). Browsers will warn until it is trusted or replaced.' \
          'Verify the SHA-256 fingerprint when you first connect, and replace it with a certificate from your CA for any use beyond this host:' \
          'see "Replace the TLS certificate" in README.md. It is never regenerated or overwritten automatically.'
    fi
}
write_environment() {
    # $1 publish address, $2 port. Non-secret settings only.
    printf '%s\n' "SAP_LENS_PUBLISH_ADDRESS=$1" "SAP_LENS_PUBLISH_PORT=$2" "SAP_LENS_PUBLIC_ORIGIN=https://$hostname:$2" "SAP_LENS_ALLOWED_HOSTS=$hostname" > "$root/compose.env"
}
key_run() {
    # Stopped maintenance on the data volume with the installation's backup key. Group 10001 is the group the key file is readable by.
    docker run --rm --network none --read-only --user 0:10001 --cap-drop=ALL --cap-add=DAC_OVERRIDE --cap-add=CHOWN --cap-add=FOWNER --security-opt=no-new-privileges \
      -e SAP_LENS_BACKUP_KEY_FILE=/keys/backup.key -e SAP_LENS_BACKUP_KEY_GROUP_READ=1 -v "$root/local-config/backup.key:/keys/backup.key:ro" "$@"
}
own_data() {
    docker run --rm --network none --read-only --user 0:0 --cap-drop=ALL --cap-add=DAC_OVERRIDE --cap-add=CHOWN --security-opt=no-new-privileges \
      -v "$volume:/data" --entrypoint python "$image" -c 'import os;from pathlib import Path
for p in [Path("/data"),*Path("/data").rglob("*")]:os.chown(p,10001,10001,follow_symlinks=False)'
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
    [ -f "$root/local-config/backup.key" ] || fail 'No backup recovery key. This installation predates encrypted backups; use upgrade --migrate-legacy.'
    compose stop
    backup_dir=$root-backups
    mkdir -p -- "$backup_dir"; chmod 700 "$backup_dir"
    backup_name=SAP-Lens-$(date -u +%Y%m%dT%H%M%SZ)-$$.slbak
    # Complete portable state, encrypted with the installation's key (AES-256-GCM). Working files stay in the private backup directory.
    key_run -e TMPDIR=/backups -v "$volume:/data" -v "$backup_dir:/backups" --entrypoint python "$image" \
      backend/server.py --maintenance backup --data /data --output "/backups/$backup_name" --mode server
    docker run --rm --network none --read-only --user 0:0 --cap-drop=ALL --cap-add=DAC_OVERRIDE --cap-add=CHOWN --security-opt=no-new-privileges \
      -v "$backup_dir:/backups" --entrypoint python "$image" -c 'import os,sys;os.chown("/backups/"+sys.argv[1],int(sys.argv[2]),int(sys.argv[3]))' "$backup_name" "$(id -u)" "$(id -g)"
    own_data
    printf '%s\n' "Encrypted backup: $backup_dir/$backup_name" \
      'Not included (host-only, preserve separately): compose.env, the TLS certificate and key, the backup recovery key and the proxy token in local-config.' \
      'Service remains stopped; use start after review.'
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
    if [ -f "$root/.sap-lens-project" ]; then managed; if [ -z "$no_start" ]; then ready; fi; exit 0; fi
    [ ! -e "$root" ] || [ -z "$(ls -A -- "$root")" ] || fail 'Installation requires an empty directory; use upgrade for existing managed data.'
    [ "$source_dir" != "$root" ] || fail 'Keep extracted binaries separate from installation configuration.'
    load_package
    stage=installation
    mkdir -p -- "$root/local-config"
    chmod 700 "$root"
    cp "$source_dir/compose.yml" "$root/compose.yml"
    write_environment 127.0.0.1 "$port"
    cp "$source_dir/manage.sh" "$root/manage.sh"
    cp "$source_dir/LICENSE.md" "$root/LICENSE.md"
    sed "s|^    image: .*|    image: $new_image|" "$root/compose.yml" > "$root/compose.pending"
    mv "$root/compose.pending" "$root/compose.yml"
    printf '%s\n' "$new_image" > "$root/image.id"
    printf '%s\n' "$new_version" > "$root/version.txt"
    host_files "$new_image"
    printf '%s\n' "$project" > "$root/.sap-lens-project"
    managed
    if [ -n "$no_start" ]; then
        volume_name
        docker volume create --label "com.docker.compose.project=$project" --label com.docker.compose.volume=sap-lens-data "$volume" >/dev/null
        printf '%s\n' 'Installed without starting; empty managed volume is available for confirmed restore.'
    else
        ready
        printf '%s\n' "Open https://$hostname:$port and create the first administrator with a one-time code:" "  sh $root/manage.sh activation-code $root"
    fi
    ;;
upgrade)
    managed; previous=$image; load_package
    image=$new_image
    image_run backend/server.py --maintenance version-check --application-version "$(cat "$root/version.txt")" --target-version "$new_version"
    image=$previous
    if [ ! -f "$root/local-config/backup.key" ] || [ ! -f "$root/local-config/tls.crt" ]; then
        # An installation from before session accounts: shared Basic access over HTTP. It is never converted silently.
        stage=legacy-migration
        [ -n "$migrate_legacy" ] && [ -n "$new_administrator" ] || fail 'This installation uses the retired shared-password access. Upgrade it explicitly: upgrade ROOT --migrate-legacy --new-administrator NAME [--hostname NAME]. Data is preserved; see README.md.'
        legacy_auth=$(sed -n 's/^SAP_LENS_AUTH=\(.*\)$/\1/p' "$root/compose.env"); legacy_auth=${legacy_auth:-basic}
        case "$legacy_auth" in basic|local|proxy) ;; *) fail 'Unsupported legacy access mode; migrate individual account files with the documented native procedure.' ;; esac
        owned_volume
        compose stop
        stamp=$(date -u +%Y%m%dT%H%M%SZ)
        cp -p "$root/compose.yml" "$root/compose.yml.legacy-$stamp"; cp -p "$root/compose.env" "$root/compose.env.legacy-$stamp"
        old_address=$(sed -n 's/^SAP_LENS_PUBLISH_ADDRESS=\(.*\)$/\1/p' "$root/compose.env"); old_port=$(sed -n 's/^SAP_LENS_PUBLISH_PORT=\(.*\)$/\1/p' "$root/compose.env")
        host_files "$new_image"
        image=$new_image
        # The migration writes its own complete encrypted snapshot before the single activation step and rolls back on failure.
        printf '%s\n' 'Migrating identity. The line below contains a ONE-TIME recovery code for the new administrator: it is shown once and stored nowhere.'
        key_run -e TMPDIR=/data/.application-backups -v "$volume:/data" --entrypoint python "$image" \
          backend/server.py --migrate-identity --data-directory /data --legacy-auth "$legacy_auth" --new-administrator "$new_administrator"
        own_data
        sed "s|^    image: .*|    image: $new_image|" "$source_dir/compose.yml" > "$root/compose.pending"
        mv "$root/compose.pending" "$root/compose.yml"
        write_environment "${old_address:-127.0.0.1}" "${old_port:-18743}"
        printf '%s\n' "$new_image" > "$root/image.id"
        printf '%s\n' "$new_version" > "$root/version.txt"
        ready
        cp "$source_dir/manage.sh" "$root/manage.sh"
        printf '%s\n' "Migrated. Open https://$hostname:${old_port:-18743}, choose account recovery and set the password of $new_administrator with the code above." \
          "Previous compose files are kept as compose.*.legacy-$stamp; the old shared secret is no longer used."
        exit 0
    fi
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
status)
    managed; compose ps; printf 'Installed version: '; cat "$root/version.txt"
    if [ -f "$root/local-config/tls.crt" ]; then
        printf 'TLS certificate: '
        docker run --rm --network none --read-only --cap-drop=ALL --security-opt=no-new-privileges -v "$root/local-config/tls.crt:/configuration/tls.crt:ro" \
          --entrypoint python "$image" backend/container_setup.py describe-tls --directory /configuration
    fi
    ;;
activation-code|recover-administrator)
    # Local operator only: the code is printed to this terminal once, is valid for 15 minutes and five attempts, and is never logged.
    stage=identity-code
    managed
    [ -n "$(compose ps -q --status running sap-lens)" ] || fail 'Start SAP Lens first; the code is issued against the running installation.'
    if [ "$action" = recover-administrator ]; then
        printf '%s\n' "${3:-}" | grep -Eq '^[A-Za-z0-9_.@-]{1,100}$' || fail 'Name the existing administrator to recover.'
        compose exec -T sap-lens python backend/server.py --identity-code --data-directory /data --recover-administrator "$3"
    else
        compose exec -T sap-lens python backend/server.py --identity-code --data-directory /data
    fi
    ;;
backup) managed; backup ;;
restore)
    stage=restore
    managed; owned_volume
    [ "${4:-}" = --confirm-restore ] && [ -f "${3:-}" ] || fail 'Restore requires ARCHIVE --confirm-restore and an empty managed data volume.'
    secret_option=; legacy_option=; interactive=
    for option in "${5:-}" "${6:-}"; do
        case "$option" in '') ;; --secret-stdin) secret_option=--secret-stdin; interactive=-i ;; --allow-legacy) legacy_option=--allow-legacy ;; *) fail 'Unknown restore option.' ;; esac
    done
    [ -f "$root/local-config/backup.key" ] || fail 'No backup recovery key in local-config; install first (it is never taken from an archive).'
    compose stop
    archive=$(realpath -- "$3")
    case "$archive" in *:*) fail 'Colon characters are not supported in Docker bind paths.' ;; esac
    work=$root-restore-work-$$; mkdir -m 700 -- "$work"
    # The archive is authenticated before it is parsed. Accounts and password verifiers come from the archive (--confirm-accounts);
    # sessions and one-time codes never do. An archive from another installation needs its exported recovery key or passphrase on stdin.
    result=0
    key_run $interactive -e TMPDIR=/work -v "$volume:/data" -v "$archive:/archive.slbak:ro" -v "$work:/work" --entrypoint python "$image" \
      backend/server.py --maintenance restore --data /data --archive /archive.slbak --mode server --confirm-restore --confirm-accounts $secret_option $legacy_option || result=$?
    rm -rf -- "$work"
    [ "$result" -eq 0 ] || fail 'Restore refused or failed safely; the archive was not activated.'
    own_data
    printf '%s\n' 'Data restored into the empty volume. Host configuration (compose.env, TLS files, keys) was not part of the archive and was not changed.' \
      'Start and sign in with the restored accounts, or issue a recovery code: recover-administrator USERNAME.'
    ;;
uninstall)
    managed
    if [ -n "${3:-}" ]; then [ "$3" = --purge-data ] && [ "${4:-}" = --confirm-purge ] || fail 'Purge requires --purge-data --confirm-purge.'; owned_volume; fi
    compose down
    if [ "${3:-}" = --purge-data ]; then docker volume rm "$volume"; printf '%s\n' 'Managed data volume explicitly removed. Configuration, backups, external sources and secrets retained.'
    else printf '%s\n' 'Containers/network removed. Data, configuration, secrets, backups and images preserved.'; fi
    ;;
esac
