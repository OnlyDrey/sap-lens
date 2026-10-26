# Linux Docker Compose

Requires Docker Engine with Compose v2 and BuildKit. Node and Python are built
inside the image. Use the repository root, not a directory containing private CSVs.
The allowlisted `.dockerignore` excludes settings, snapshots, Git history and tests.

## Downloaded image (no source build)

Choose `Linux Docker` or `All` in [Build Deployment Packages](BUILD.md).
The Linux amd64 archive contains `image.tar`, a Compose file referencing that
**locally loaded versioned image**, documentation, manifest and checksum. No registry
is used. After extracting GitHub's outer download ZIP:

```sh
sha256sum -c SAP-Lens-Linux-Docker-amd64-<version>.tar.gz.sha256
mkdir sap-lens-docker
tar -xzf SAP-Lens-Linux-Docker-amd64-<version>.tar.gz -C sap-lens-docker
cd sap-lens-docker
docker load -i image.tar
mkdir -p local-config
sudo install -d -m 0750 -o "$(id -u)" -g 10001 local-config
(umask 077; openssl rand -hex 32 > local-config/server-access.secret)
sudo chgrp 10001 local-config/server-access.secret
chmod 0640 local-config/server-access.secret
docker compose up -d
docker compose ps
docker compose logs -f
```

Open `http://127.0.0.1:18743`; username `saplens`, password from the private secret.
No Python/Node installation or React compilation is needed on the Docker host.
The image embeds the same workflow version/source identity as other platform builds.
Docker amd64 is the tested build target; ARM/multi-architecture images are not claimed.

For another device, configure an explicit HTTPS reverse proxy and the
[access boundary](SECURITY.md). Default publication is loopback-only.
The image runs UID/GID10001 with read-only root, private tmpfs and dropped capabilities.
Keep the access secret outside the image and source control. The pipeline builds,
audits and smoke-tests the image, exports it and verifies its downloadable archive;
it never pushes to an external registry.

## Source-build alternative

From a reviewed source checkout, create the same private secret, then use
`docker compose up -d --build`. This compiles assets inside a Node24 build stage;
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
paths. Browser uploads require no source mount and become Static after confirmation.

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

Choose a directory writable by the operator; creating a protected `/srv` location
may require an administrator first. Installation creates a private configuration
root, preserves repeat installations, generates a private access secret and loads
the offline image. It validates the complete extracted package against its
manifest and embedded version/source identity, then pins Compose to the immutable
image ID. It never pushes to or pulls from a registry. The outer SHA-256 check and
trusted distribution source remain necessary; an unsigned self-contained manifest
is not proof of publisher authenticity.

Configuration is `compose.env`, with reviewed mounts/settings in `compose.yml`.
The initial Basic username is `saplens`; the generated password is in
`local-config/server-access.secret`. It is not printed by routine management.
The runtime reads this file through the existing secret mount. An installation
uses a directory-derived Compose project identity and a separate named data
volume. Default publication remains loopback-only. Configure ports/public origin
consistently before restarting; follow [security requirements](SECURITY.md)
for remote access. Do not copy another installation's management identity files.

Upgrade from a **newly extracted package**, retaining the same installation root:

```sh
sh manage.sh upgrade /srv/sap-lens
```

Upgrade rejects downgrades, verifies the new package and image, stops the current
container and creates a private backup before changing its selected image.
Administrator environment, access secret and source mounts are preserved. Success
requires the new container's actual health check to pass. On failure, the container
is stopped and the backup retained. Inspect logs and data compatibility before
restoring; switching image IDs alone does not reverse storage migrations.

```sh
sh /srv/sap-lens/manage.sh backup /srv/sap-lens
# Explicit backup leaves the service stopped; restart after review:
sh /srv/sap-lens/manage.sh start /srv/sap-lens
```

Backups are owner-only `.tar.gz` files in `/srv/sap-lens-backups`, outside the
installation. They include durable data and configuration (including the private
access secret), with checksum/schema verification. Logs and volatile runtime
state are excluded. External Dynamic CSV mounts are not followed; back them up
separately where required. Keep archives private and apply organizational backup
retention/encryption policy.

Maintenance helpers run temporarily as root with only DAC_OVERRIDE and CHOWN to
read private state and restore ownership. They have no network, Docker socket or
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
sh /srv/sap-lens-recovery/manage.sh restore /srv/sap-lens-recovery \
  /srv/sap-lens-backups/SAP-Lens-example.tar.gz --confirm-restore
```

Data is restored only into that empty volume. The backed-up configuration is
staged in a separate private directory printed by the command, rather than
silently replacing recovery configuration. Review environment/source mounts and
secret-file ownership; copy only approved configuration/secret changes, **not**
`image.id`, `version.txt` or `.sap-lens-project` from a different installation.
The newly generated recovery access secret remains selected until explicitly
changed. Preserve the old installation and archive, then run `start`, inspect
`status`/logs and verify imported records before declaring recovery complete.
Missing source mounts do not justify deleting valid snapshots.

```sh
# Removes this project's containers/network; preserves data and configuration:
sh /srv/sap-lens/manage.sh uninstall /srv/sap-lens
# Explicit destructive option, with confirmation:
sh /srv/sap-lens/manage.sh uninstall /srv/sap-lens --purge-data --confirm-purge
```

Purge removes only the named volume with matching Compose ownership labels.
Configuration, access secrets, backups, imported images and external sources are
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
