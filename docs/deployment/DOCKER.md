# Docker (SAP Lens 2)

Optional Linux deployment of the same ASP.NET Core Server; no Windows service is
changed. SAP Lens 1 Docker files remain archived in `legacy/v1/`.

## Build and configuration

Use Docker with BuildKit and Compose v2. The multi-stage build uses Node 24 and
.NET 10, builds the React UI, then publishes only the API and its shared projects.
Neither Python nor the Windows Desktop runtime ships. Product version comes from
`backend/product-version.json`; pass the exact source commit separately:

```bash
export SAP_LENS_SOURCE_SHA=$(git rev-parse HEAD)
docker build --build-arg SAP_LENS_SOURCE_SHA="$SAP_LENS_SOURCE_SHA" -t sap-lens:local .
```

The runtime uses the non-root `app` user (UID 1654) and a persistent `/data` volume.
The minimal `compose.yml` publishes only `127.0.0.1:18795`; no production container
is started by validation. Configure a private TLS directory outside the checkout
with `server.crt` (PEM chain) and `server.key`, readable by UID/group 1654. Never
commit certificates, passwords, keys or operator configuration. A corporate build
CA can be mounted with `--secret id=build_ca,src=/absolute/ca-bundle.pem`; it is not
copied into the runtime image. Runtime trust is configured separately.

Before starting, set `SAP_LENS_TLS_DIRECTORY` to that existing directory and
`SAP_LENS_V2_ALLOWED_HOSTS` to the certificate's DNS names. Set
`SAP_LENS_SOURCE_SHA` as above. Inspect `docker compose config`, then start with
`docker compose up -d --build` on the intended disposable/deployment host.
The Compose example's port is loopback-only; a remote proxy needs an explicitly
reviewed private bind/firewall rule. Never expose an unreviewed public listener.

## Runtime boundaries

The entrypoint selects one container interface (or explicit
`SAP_LENS_V2_LISTEN`), not `0.0.0.0`. The existing Server policy requires a private
interface, TLS, an exact host allow-list and Accounts authentication. Missing TLS
or invalid network configuration fails closed. Configure trusted proxy CIDRs with
`SAP_LENS_V2_TRUSTED_PROXIES` and a bounded hop count; arbitrary forwarded headers
remain untrusted. TLS remains enabled between proxy and backend.

Readiness calls `/health/ready` using `curl`, bounded to three seconds, with the
configured certificate chain and advertised hostname verification. The probe
resolves only to the container's own listener and carries no credential.
`SAP_LENS_V2_HEALTH_HOST` can select another name covered by the certificate.
No database is opened or initialized by the health probe.

First-run activation and backup-key provisioning use the existing local Server
commands through `docker compose exec sap-lens dotnet /app/SapLens.Api.dll` (see
[server access](SERVER_NETWORK_ACCESS.md) and [Windows operations](WINDOWS_DEPLOYMENT.md)
for account/backup contracts). Keep backup keys outside data/archive storage;
mount protected key material only when needed. Restores require their existing
preflight, explicit account rollback acknowledgement and recovery safeguards.
Do not use `docker compose down -v` on real application data. A container image
build is not deployment, migration or restore acceptance.

## Validation limits

The post-migration local build attempt was blocked while downloading an official
Microsoft runtime layer from `centralus.data.mcr.microsoft.com` (403 from the
managed network). Compose parsing and shell/contract checks ran; image/runtime
acceptance remains pending until registry-layer access is available. No production
containers or Windows services were touched.
