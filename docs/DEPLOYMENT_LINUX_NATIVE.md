# Linux native and workstation server

Use Python 3.12, Node 24 LTS (25 also supported for frontend tooling), npm 10/11,
Git, and a supported Linux distribution. Node is needed only to build frontend
assets. Desktop/WebView2 dependencies are not needed at runtime.

## Local Linux workstation, no systemd/root

From the repository root:

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements.txt
npm --prefix frontend ci
npm --prefix frontend run build
# Default is loopback only and separate XDG user storage.
.venv/bin/python backend/server.py
```

Open `http://127.0.0.1:18743`; Ctrl+C stops gracefully. For a custom store:

```sh
export SAP_LENS_DATA_DIR="$HOME/.local/share/sap-lens-server-testing"
export SAP_LENS_SOURCE_DIR="$HOME/sap-lens-exports"
.venv/bin/python backend/server.py
```

A source directory need not contain files to start the application. Create it and
grant permissions before configuring a Dynamic source. For shared machines use the
Basic access boundary, even on loopback, as documented in Security.

## Dedicated systemd host

Build from the reviewed checkout in `/opt/sap-lens` using the commands above, then
protect application files from writes by the service identity. These example
commands require administrator access for installation, not runtime:

```sh
sudo useradd --system --home-dir /var/lib/sap-lens --shell /usr/sbin/nologin saplens
sudo install -d -o saplens -g saplens -m 0700 /var/lib/sap-lens
sudo install -d -o root -g saplens -m 0750 /srv/sap-lens-sources /etc/sap-lens
sudo install -o root -g saplens -m 0640 deploy/server.env.example /etc/sap-lens/server.env
sudo install -o root -g root -m 0644 deploy/linux/sap-lens.service /etc/systemd/system/sap-lens.service
# Review exact paths, origin and boundary before starting.
sudoedit /etc/sap-lens/server.env
sudo systemctl daemon-reload
sudo systemctl enable --now sap-lens
sudo systemctl status sap-lens
sudo journalctl -u sap-lens -f
```

The unit uses `/opt/sap-lens/.venv/bin/python`, a dedicated user, private temporary
storage, restrictive umask and a read-only filesystem except `/var/lib/sap-lens`.
Changing the data directory requires updating `ReadWritePaths` and permissions in
an explicit unit override. Home directories are inaccessible with `ProtectHome`.
Give the service read access to source files; avoid group/world-writable exports.
For TLS/gateway deployment see [Security](DEPLOYMENT_SECURITY.md). The service does
not grant access to a remote share automatically; mount an administrator-managed
read-only source directory with appropriate credentials outside application config.

```sh
sudo systemctl stop sap-lens
sudo systemctl start sap-lens
sudo systemctl restart sap-lens
sudo systemctl is-enabled sap-lens
```

## Upgrade and uninstall

Stop the unit, back up all `/var/lib/sap-lens` plus protected environment/secret
files, update the immutable checkout to the reviewed version, reinstall pinned
runtime requirements in its venv, rebuild production frontend, and start the unit.
Review logs and health before removing the previous checkout/backup. Do not replace
individual private snapshot files. Existing configuration migrations are retained.

```sh
sudo systemctl disable --now sap-lens
sudo rm /etc/systemd/system/sap-lens.service
sudo systemctl daemon-reload
```

This removes service registration only. Data, source files, secrets, service user
and application installation are deliberately preserved. Remove those separately
only after retention/backup decisions. Linux automated process tests are not a
claim that installation/reboot recovery was tested on a running systemd host.
