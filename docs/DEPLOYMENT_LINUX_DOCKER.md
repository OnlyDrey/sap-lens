# Linux Docker Compose

Requires Docker Engine with Compose v2 and BuildKit. Node and Python are built
inside the image. Use the repository root, not a directory containing private CSVs.
The allowlisted `.dockerignore` excludes settings, snapshots, Git history and tests.

## Downloaded image (no source build)

Choose `Linux Docker` or `All` in [Build Deployment Packages](DEPLOYMENT_PACKAGES.md).
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
[access boundary](DEPLOYMENT_SECURITY.md). Default publication is loopback-only.
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

## Lifecycle, backup, restore

```sh
docker compose restart
docker compose stop
docker compose start
# Upgrade after backing up data; check out the intended source commit first.
docker load -i /path/to/new-package/image.tar
# Use the new package Compose file, preserving reviewed administrator configuration.
docker compose up -d
# Removes containers/network, preserves named volume and private secret:
docker compose down
```

For a consistent backup stop the application, then archive the full volume using
an operator-approved local helper image or Docker's volume backup tooling. Example:

```sh
docker compose stop
mkdir -m 700 -p backups
docker run --rm --network none --user 0:0 \
  -v sap-lens_sap-lens-data:/data:ro -v "$PWD/backups:/backup" \
  --entrypoint tar sap-lens-sap-lens -czf /backup/sap-lens.tar.gz -C /data .
docker compose start
```

The source-build example uses image `sap-lens-sap-lens`; downloaded packages use
`sap-lens:<version>`. Substitute the image shown by `docker compose images` in the
backup command. The backup helper uses root only to read
volume ownership, no network or Docker socket. Store backups encrypted/offline.
For restore, stop/remove the application container, restore the archive into the
volume using `tar -xzf ... -C /data`, retain UID/GID10001 ownership, and start it.
Do not restore into a running process or combine partial snapshots.

Health uses `/health/ready` through loopback. `unhealthy` means check startup/config,
permissions or loading; missing optional CSVs alone are not an outage. Container
stop sends SIGTERM, allows 25 seconds, then enforces shutdown. Duplicate data-store
writers fail rather than silently changing ports.
