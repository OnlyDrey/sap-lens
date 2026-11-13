# Linux Docker Compose

Requires Docker Engine with Compose v2 and BuildKit. Node and Python are built
inside the image. Use the repository root, not a directory containing private CSVs.
The allowlisted `.dockerignore` excludes settings, snapshots, Git history and tests.

## Downloaded image (no source build)

Choose `Linux Docker` or `All` in [Build Deployment Packages](../BUILD.md).
The Linux amd64 archive contains `image.tar`, a Compose file referencing that
**locally loaded versioned image**, documentation, manifest and checksum. No registry
is used. After extracting GitHub's outer download ZIP:

```sh
sha256sum -c SAP-Lens-Linux-Docker-amd64-<version>.tar.gz.sha256
mkdir sap-lens-docker
tar -xzf SAP-Lens-Linux-Docker-amd64-<version>.tar.gz -C sap-lens-docker
cd sap-lens-docker
sh manage.sh install /srv/sap-lens            # see "Managed offline installation and lifecycle"
sh /srv/sap-lens/manage.sh activation-code /srv/sap-lens
```

Open `https://localhost:18743`, enter the one-time code and create the first
administrator. **There is no default user or password**, and Basic authentication
no longer exists: every person signs in with an individual SAP Lens account
(Administrator, Reviewer or Viewer) created under Settings, User Management.

The container always serves **HTTPS**. Plain HTTP is not answered, and the server
refuses to start with an `http://` origin on a non-loopback listener. The health
probe verifies the configured certificate and host name; TLS verification is never
disabled.

`compose.env` (written by `install`) holds only non-secret values:
`SAP_LENS_PUBLISH_ADDRESS` (default `127.0.0.1`), `SAP_LENS_PUBLISH_PORT`,
`SAP_LENS_PUBLIC_ORIGIN` (`https://<host>:<port>`) and `SAP_LENS_ALLOWED_HOSTS`.
Keep the origin, the allowed hosts and the certificate names consistent. Optional:
`SAP_LENS_TRUSTED_PROXIES` (see below). There is no access-mode setting.

Host-only files live in `local-config/` (mode 0700). They are created once, never
overwritten by any management action and never part of a backup:

| File | Purpose | Mode |
| --- | --- | --- |
| `tls.crt`, `tls.key` | Server certificate and private key | 0644 / 0640, group 10001 |
| `backup.key` | Recovery key for encrypted backups and migrations | 0640, group 10001 |
| `proxy-token.secret` | Token a trusted TLS proxy must send; unused otherwise | 0640, group 10001 |

Keep a separate, protected copy of `backup.key`: an encrypted backup cannot be
restored without it.

### TLS certificate

`install` accepts an administrator-supplied pair, validated before it is copied
(the key matches, the certificate is currently valid and covers the host name):

```sh
sh manage.sh install /srv/sap-lens --hostname lens.example.org --port 443 \
  --tls-cert /secure/lens.example.org.crt --tls-key /secure/lens.example.org.key
```

Without a supplied pair, `install` generates a **self-signed** certificate
(ECDSA P-256, 825 days, not a CA) whose subject alternative names are the
`--hostname` value (default `localhost`) plus `localhost`, `127.0.0.1` and `::1`.
It prints the SHA-256 fingerprint and a warning. Browsers warn until the
certificate is trusted on the client or replaced; compare the fingerprint when you
first connect. Use it for local access and evaluation, not for other devices.

**Replace the TLS certificate** (also for renewal). Nothing is replaced
automatically, so the procedure is explicit:

```sh
sh /srv/sap-lens/manage.sh stop /srv/sap-lens
cd /srv/sap-lens/local-config
mv tls.crt tls.crt.previous && mv tls.key tls.key.previous      # keep until the new pair works
install -m 0644 /secure/new.crt tls.crt
install -m 0640 -g 10001 /secure/new.key tls.key                  # may need sudo for the group
sh /srv/sap-lens/manage.sh start /srv/sap-lens                    # fails closed if the pair or its names do not match
sh /srv/sap-lens/manage.sh status /srv/sap-lens                   # shows fingerprint, names and expiry
```

If the host name changes, update `SAP_LENS_PUBLIC_ORIGIN` and
`SAP_LENS_ALLOWED_HOSTS` in `compose.env` to names the certificate covers.
`status` reports the expiry date; an expired certificate stops the server at start.

### Trusted TLS-terminating proxy

To let a reverse proxy terminate TLS instead, set in `compose.env`:

```sh
SAP_LENS_PUBLIC_ORIGIN=https://lens.example.org
SAP_LENS_ALLOWED_HOSTS=lens.example.org
SAP_LENS_TLS_CERT_FILE=
SAP_LENS_TLS_KEY_FILE=
SAP_LENS_TRUSTED_PROXIES=172.18.0.1/32          # the exact address the proxy connects from; never 0.0.0.0/0
```

The proxy must send `X-Forwarded-Proto: https` and
`X-SAP-Lens-Proxy-Token: <content of local-config/proxy-token.secret>` on every
request and must itself be reachable only over HTTPS. A request is accepted only
when all three hold: the peer is a listed proxy, the token matches and the
forwarded protocol is `https`; anything else answers 403. The proxy supplies
transport only: it never authenticates a person, and identity headers are ignored.
Keep the published port on loopback or a private network so clients cannot bypass
the proxy.

No Python/Node installation or React compilation is needed on the Docker host.
The image embeds the same workflow version/source identity as other platform builds.
Docker amd64 is the tested build target; ARM/multi-architecture images are not claimed.
The image runs UID/GID10001 with read-only root, private tmpfs and dropped capabilities.
The pipeline builds, audits and smoke-tests the image, exports it and verifies its
downloadable archive; it never pushes to an external registry.

## Source-build alternative

From a reviewed source checkout, create `local-config/` with the four host files
first (`python backend/container_setup.py generate-tls|backup-key|proxy-token
--directory local-config --host localhost --group 10001`, or supply your own
certificate), then use `docker compose up -d --build` and issue the activation code
with `docker compose exec sap-lens python backend/server.py --identity-code
--data-directory /data`. This compiles assets inside a Node24 build stage;
the final Python3.12 image contains production assets/runtime only. Source builds
without supplied validated build metadata show development identity. Base tags can
receive updates; record image digests for controlled rollback.

For managed environments an optional BuildKit `build_ca` secret supplies build-time
trust only; never disable TLS or bake a session CA into the image.

## Sources and storage

The named `sap-lens_sap-lens-data` volume persists `/data`; inspect the actual name
with `docker volume ls` if using a different Compose project name. Do not use
`docker compose down -v` unless deliberately deleting all private application state.
To enable Dynamic CSVs, uncomment the source mount in `compose.yml`:

```yaml
volumes:
  - sap-lens-data:/data
  - /srv/sap-lens-exports:/sources:ro
```

Give UID10001 read/traverse permission, then configure paths such as
`/sources/roles.csv` in Settings. Container paths are not arbitrary Docker host
paths. Browser uploads require no source mount and become Static after successful validation and automatic activation.

## Managed offline installation and lifecycle

Downloaded packages include `manage.sh`. It requires a local Linux Docker engine,
Compose v2 and standard Linux tools (`sh`, `sha256sum`, `realpath`); **no host
Python or Node.js** is needed. Verify the outer archive sidecar before extracting.
Keep the extracted package separate from the installation/configuration directory.
Do not use a remote Docker context: bind paths refer to this Docker host.

```sh
# From the newly extracted, verified offline package:
sh manage.sh install /srv/sap-lens
sh /srv/sap-lens/manage.sh status /srv/sap-lens
sh /srv/sap-lens/manage.sh stop /srv/sap-lens
sh /srv/sap-lens/manage.sh start /srv/sap-lens
sh /srv/sap-lens/manage.sh restart /srv/sap-lens
```

Options of `install`: `--hostname NAME` (default `localhost`), `--port N` (default
18743), `--tls-cert FILE --tls-key FILE`, `--no-start`.

Choose a directory writable by the operator; creating a protected `/srv` location
may require an administrator first. Installation creates a private configuration
root, preserves repeat installations, creates the host files that are missing
(see above) and loads the offline image. It validates the complete extracted
package against its manifest and embedded version/source identity, then pins
Compose to the immutable image ID. It never pushes to or pulls from a registry. The
outer SHA-256 check and trusted distribution source remain necessary; an unsigned
self-contained manifest is not proof of publisher authenticity.

### First administrator and account recovery

```sh
sh /srv/sap-lens/manage.sh activation-code /srv/sap-lens                 # fresh installation only
sh /srv/sap-lens/manage.sh recover-administrator /srv/sap-lens USERNAME  # an existing administrator
```

Both print a one-time code on the terminal of the local operator: valid for 15
minutes and five attempts, shown once, never logged and never returned by the web
API. `activation-code` works only until the first administrator exists; a
populated or damaged installation never reopens first-run setup. Recovery targets
an existing administrator, keeps its identity and history, signs out its sessions
and lets it set a new password under "account recovery" on the sign-in page.
Everything else (users, roles, enabling and disabling, password resets, session
revocation, session timeouts) is done in SAP Lens under User Management.

An installation uses a directory-derived Compose project identity and a separate
named data volume. Default publication remains loopback-only. Follow
[security requirements](SECURITY.md) for remote access. Do not copy another
installation's management identity files.

Upgrade from a **newly extracted package**, retaining the same installation root:

```sh
sh manage.sh upgrade /srv/sap-lens
```

Upgrade rejects downgrades, verifies the new package and image, stops the current
container and creates an encrypted backup before changing its selected image.
Administrator environment, certificate, keys and source mounts are preserved.
Success requires the new container's actual health check to pass. On failure, the
container is stopped and the backup retained. Inspect logs and data compatibility
before restoring; switching image IDs alone does not reverse storage migrations.

**Upgrading an installation that used the shared password (Basic over HTTP).**
Such an installation is never converted silently; a plain `upgrade` stops with an
explanation and leaves the old service running. Upgrade it explicitly:

```sh
sh manage.sh upgrade /srv/sap-lens --migrate-legacy --new-administrator NAME [--hostname NAME]
```

This stops the old container, keeps `compose.yml` and `compose.env` as
`*.legacy-<time>`, creates the missing host files, and runs the identity
migration: a complete encrypted snapshot of the existing data is written first
(kept until an administrator confirms and deletes it under User Management), then
one administrator named `NAME` is created with an unknown random password and a
**one-time recovery code is printed once**. Business data, review history and
evidence are unchanged. The old shared secret is not converted into a password
and opens nothing afterwards; the URL changes to `https://`. Sign in through
"account recovery" with the code, then create the other accounts.

```sh
sh /srv/sap-lens/manage.sh backup /srv/sap-lens
# Explicit backup leaves the service stopped; restart after review:
sh /srv/sap-lens/manage.sh start /srv/sap-lens
```

Backups are owner-only encrypted `.slbak` files (AES-256-GCM, keyed by
`local-config/backup.key`) in `/srv/sap-lens-backups`, outside the installation.
They contain the complete portable state: sources and snapshots, SoD periods,
decisions, approvals and evidence, accounts with roles and password verifiers,
branding and logos, and application settings. They do **not** contain active
sessions, one-time codes, `compose.env`, the TLS certificate and key, the backup
key or the proxy token: preserve `local-config/` and `compose.env` separately.
External Dynamic CSV mounts are not followed. Archive retention on the host is the
operator's decision; in-application retention is described in
[backup/restore](BACKUP_RESTORE.md).

Maintenance helpers run temporarily as root with only DAC_OVERRIDE, CHOWN and
(for stopped maintenance) FOWNER to read private state and restore ownership. They have no network, Docker socket or
privileged-container access. The application itself continues to run UID/GID10001,
with dropped capabilities and read-only root. Helpers mount only the recognized
application volume, explicit configuration and private backup/recovery locations.

Restore requires an **empty managed volume** and explicit confirmation. To retain
the old data, create a separate recovery installation without starting it:

```sh
# Stop the old installation; do not delete its data volume.
sh /srv/sap-lens/manage.sh stop /srv/sap-lens
# Run from a compatible verified offline package:
sh manage.sh install /srv/sap-lens-recovery --no-start
# The archive was written with the OLD installation's key: pass that key on stdin.
sh /srv/sap-lens-recovery/manage.sh restore /srv/sap-lens-recovery \
  /srv/sap-lens-backups/SAP-Lens-example.slbak --confirm-restore --secret-stdin \
  < /srv/sap-lens/local-config/backup.key
```

Restoring into the installation that wrote the archive needs no `--secret-stdin`.
The archive is authenticated before anything is parsed: a wrong key or a modified
archive is refused and leaves the empty volume empty, so the attempt can be
repeated. Accounts, roles and password verifiers come from the archive; sessions
and one-time codes never do, so everyone signs in again (or an administrator is
recovered with `recover-administrator`). Host configuration is not in the archive
and is not changed: the recovery installation keeps its own certificate, keys and
`compose.env`. `--allow-legacy` accepts an old unencrypted `.tar.gz` archive
deliberately. Preserve the old installation and archive, then run `start`, inspect
`status`/logs and verify imported records before declaring recovery complete.
Missing source mounts do not justify deleting valid snapshots.

```sh
# Removes this project's containers/network; preserves data and configuration:
sh /srv/sap-lens/manage.sh uninstall /srv/sap-lens
# Explicit destructive option, with confirmation:
sh /srv/sap-lens/manage.sh uninstall /srv/sap-lens --purge-data --confirm-purge
```

Purge removes only the named volume with matching Compose ownership labels.
Configuration, certificates, keys, backups, imported images and external sources are
retained for an explicit administrator retention decision. Shared/external volumes
are not purged by the helper. Never use global Docker pruning for uninstall.

For logs use `docker compose --project-directory /srv/sap-lens \
--env-file /srv/sap-lens/compose.env -f /srv/sap-lens/compose.yml \
-p <project-from-.sap-lens-project> logs -f`; ordinary `docker compose` in that
directory must also use the recorded project identity. Do not publish private logs
or secrets. Health uses `/health/ready`; missing optional CSVs alone are not a
service outage.

Source-build users can continue using Compose directly as described above. The
offline management helper deliberately requires a downloaded package for
install/upgrade; it does not silently build source or bypass validation receipts.

## Shared operational limits

These targets use the same source, evidence, backup and retention contracts as
Windows. Scheduled backups currently wait for host restart; plan a controlled
maintenance window rather than restarting a browser. Follow [backup/restore](BACKUP_RESTORE.md)
and [server security](SECURITY.md), including individual-account limitations.
The Docker image and `manage.sh` lifecycle are exercised against a real Docker
engine by `scripts/testing/test-docker-deployment.py` and
`test-docker-lifecycle.py` (TLS-only sessions, activation, roles, revocation,
encrypted backup, upgrade, keyed restore, refusal of wrong-key and modified
archives). Those checks do not certify systemd reboot/recovery, Docker host
hardening, a production reverse proxy or production load. Validate those on the intended host before production acceptance.
