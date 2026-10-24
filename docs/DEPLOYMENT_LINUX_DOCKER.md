# Linux Docker Compose

Requires Docker Engine with Compose v2 and BuildKit. Node and Python are built
inside the image. Use the repository root, not a directory containing private CSVs.
The allowlisted `.dockerignore` excludes settings, snapshots, Git history and tests.

## First deployment

```sh
mkdir -p local-config
# UID/GID 10001 is the image's non-root runtime identity.
sudo install -d -m 0750 -o "$(id -u)" -g 10001 local-config
(umask 077; openssl rand -hex 32 > local-config/server-access.secret)
sudo chgrp 10001 local-config/server-access.secret
chmod 0640 local-config/server-access.secret

docker compose up -d --build
docker compose ps
docker compose logs -f
```

Open `http://127.0.0.1:18743`. Username `saplens`; password is the private access
secret. This uses shared Basic access, only suitable for controlled local testing
without HTTPS. Access from another device requires the explicitly configured
HTTPS reverse proxy and security boundary described in [Security](DEPLOYMENT_SECURITY.md).
Mobile browsers use that same HTTPS URL and browser CSV picker/downloads.

The Dockerfile uses Node 24, Python 3.12, locked frontend install and pinned runtime
Python dependencies, no development dependencies in the final image, UID/GID10001,
read-only root filesystem, dropped capabilities and a private tmpfs. Production
assets are compiled once in a separate stage. Base image tags receive security
updates; record image digests during controlled deployment for byte-for-byte
rollback. Builds are source deployments and show development identity unless a
separately reviewed release identity is included; no tags/releases are generated.

For an environment with an explicitly supplied build proxy CA, use BuildKit
`--secret id=build_ca,src=/absolute/ca.crt` with `docker build`. Trust is mounted only
for dependency download steps and is not retained in the runtime image. Do not
bypass TLS checks. Ordinary builds require no CA secret.

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
docker compose up -d --build
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

Compose's default built image is `sap-lens-sap-lens`; confirm with `docker compose
images` before running this command. The backup helper uses root only to read
volume ownership, no network or Docker socket. Store backups encrypted/offline.
For restore, stop/remove the application container, restore the archive into the
volume using `tar -xzf ... -C /data`, retain UID/GID10001 ownership, and start it.
Do not restore into a running process or combine partial snapshots.

Health uses `/health/ready` through loopback. `unhealthy` means check startup/config,
permissions or loading; missing optional CSVs alone are not an outage. Container
stop sends SIGTERM, allows 25 seconds, then enforces shutdown. Duplicate data-store
writers fail rather than silently changing ports.
