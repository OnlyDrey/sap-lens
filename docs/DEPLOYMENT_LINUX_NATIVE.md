# Linux native/systemd and browser client

## Supported target

The downloadable **Linux-Native-x64** archive targets Ubuntu 22.04/24.04 x86-64,
glibc 2.35+, Python **3.12**, its `venv` module, CA certificates, `libgcc-s1` and
`libstdc++6`. Other distributions are not certified; Alpine/musl, ARM and older
glibc are unsupported by this bundle. Provision Python 3.12 through your supported
OS/provider (Ubuntu 22.04 does not include it as its default Python).

**Node.js and React compilation are not required on the target.** The archive
contains backend, production frontend, version metadata, hash-locked Python
requirements and compatible binary wheels, environment/unit templates, installer,
operator documentation and checksums. A fresh venv is created on the destination;
a build-machine venv is never relocated. No compiler/Rust toolchain should be needed.

## Download and install

Build `Linux Native/systemd` or `All` using [manual packaging](DEPLOYMENT_PACKAGES.md).
Extract GitHub's download wrapper, verify the sidecar checksum, then extract the
inner archive into a new staging directory:

```sh
sha256sum -c SAP-Lens-Linux-Native-x64-<version>.tar.gz.sha256
mkdir sap-lens-staging
tar -xzf SAP-Lens-Linux-Native-x64-<version>.tar.gz -C sap-lens-staging
cd sap-lens-staging
sudo python3.12 scripts/install-linux-server.py install
sudo systemctl status sap-lens
sudo journalctl -u sap-lens -f
```

Default binaries: `/opt/sap-lens/releases/<identity>/`, selected atomically through
`/opt/sap-lens/current`. Data: `/var/lib/sap-lens`. Administrator configuration:
`/etc/sap-lens/server.env`. The service uses dedicated `saplens`, loopback by default,
a restrictive umask/read-only filesystem and private temporary storage. Installer
verifies every bundle file, installs offline with hashes and checks configuration
before switching the active release. Existing configuration is never overwritten.

Options `--prefix`, `--data`, `--config` select **absolute** separate locations;
`--no-start` installs without enabling/starting the unit. A running systemd host is
required for system installation. Existing administrator-managed or differing units
are preserved and require explicit migration/review; do not delete them blindly.
Failed staging leaves the active release intact; review the unused release directory
before retrying. If configuration is invalid, correct it explicitly and retry.

```sh
sudo systemctl stop sap-lens
sudo systemctl start sap-lens
sudo systemctl restart sap-lens
sudoedit /etc/sap-lens/server.env
```

Read [security](DEPLOYMENT_SECURITY.md) before remote access. For Basic/proxy mode
create a private secret readable by the service and configure the exact public
origin/allowed hosts/trusted proxy peers. Dynamic CSV paths must be under the
configured source root; give `saplens` read access. Uploads become Static after
confirmation and snapshots persist independently of the original client file.

## Upgrade, rollback and uninstall

Back up the full stopped data directory and administrator environment/secret files.
Extract/verify the next archive into a new staging directory and run its installer
with the **same** prefix/data/config options and the `upgrade` action. It stages a new environment, preserves
configuration, stops the existing service before switching and starts it again.
A private stopped-state backup is made before activation when existing data is
present. Keep the previous release and backup until acceptance checks succeed. A modified
systemd unit is not silently replaced. Rollback requires stopping the service,
reviewing storage migration compatibility, restoring the prior `current` link (and
consistent backup if necessary), then restarting; never run two versions against
one writable store.

```sh
sudo python3.12 scripts/install-linux-server.py backup
sudo python3.12 scripts/install-linux-server.py upgrade
sudo python3.12 scripts/install-linux-server.py status
sudo python3.12 scripts/install-linux-server.py uninstall
```

Uninstall stops/disables and unregisters the managed service and removes its
recognized application binaries. External source files, secrets, configuration
and data are preserved by default. Explicit `--purge-data --confirm-purge` also
removes the recognized data directory and selected environment file; external
sources, external secrets and backups remain untouched. Use the matching prefix/config/data options
if defaults were changed.

## Linux workstation, no systemd or root

The **same native archive** supports a local browser client. It is not an AppImage
or standalone GUI. After verification/extraction:

```sh
python3.12 scripts/install-linux-server.py install --user \
  --prefix "$HOME/.local/opt/sap-lens" \
  --data "$HOME/.local/share/sap-lens-server" \
  --config "$HOME/.config/sap-lens/server.env"
"$HOME/.local/opt/sap-lens/current/.venv/bin/python" \
  "$HOME/.local/opt/sap-lens/current/scripts/run-installed-server.py" \
  --env "$HOME/.config/sap-lens/server.env"
```

Open `http://127.0.0.1:18743`; Ctrl+C stops. Stop this process before a user-mode
upgrade. Use `uninstall --user` with the same paths to retain local state. On shared
workstations configure Basic/proxy protection even on loopback.

Source development remains available: install `backend/requirements.txt`, run
`npm --prefix frontend ci` and `npm --prefix frontend run build`, then start
`python backend/server.py`. Those Node/build requirements apply to **source builds**,
not to downloaded native packages.

CI's non-root install/start/import/synthetic-upgrade/persistence/uninstall smoke
test does not certify systemd boot, journald, OS hardening or production permissions.
Those require a real target host. See [actual validation](PACKAGING_VALIDATION.md).

Local lifecycle commands also support `start`, `stop`, `restart` and `status`
with `--user` and the same explicit paths. `backup` stops the runtime and leaves
it stopped until an explicit `start`. See
[backup and recovery details](INSTALLATION_LIFECYCLE_VALIDATION.md); native systemd
acceptance remains pending.
