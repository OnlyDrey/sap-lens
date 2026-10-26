# Installation lifecycle implementation and validation

> Historical evidence: applies to the source/phase recorded below, not later
> commits. Use the [current documentation index](../../README.md) for instructions.

Current status: lifecycle tooling, Docker management integration, documentation
alignment and linked synthetic examples are implemented locally. Windows installer
and SCM execution, real systemd, reboot/recovery and UNC acceptance remain pending.
Docker and Linux user-mode results below use their documented synthetic fixtures;
they do not certify a newly built current-source production distribution.
See [UI and final integrated validation](UI_CONSOLIDATION_VALIDATION.md) and
[local-build validation](LOCAL_BUILD_VALIDATION.md) for their separate scopes.

The initial checkpoint and subsequent dated sections retain historical results.
Later sections supersede their earlier pending-work statements.

## Initial implementation and local checkpoint

- Local-only maintenance commands: private backup, checksum/schema verification,
  empty-destination restore and downgrade rejection. No HTTP maintenance endpoint.
- Linux native management: install, upgrade, start, stop, restart, status, backup,
  restore and uninstall; systemd and non-root user-mode paths share the installer.
- Immutable versioned application directories; administrator configuration and
  mutable records live in separate dedicated directories.
- Existing configuration is preserved. Upgrade stops the runtime and backs up
  recognized data before activation. Failed startup does not claim that switching
  binaries alone would restore data compatibility.
- Uninstall preserves data and configuration. Destruction requires both
  `uninstall --purge-data --confirm-purge` and recognized data ownership.
- User-mode process management checks PID identity, process start time and listener
  ownership. It never stops processes by executable name.

Targeted execution: 8 maintenance tests, 5 Linux lifecycle contract tests,
8 headless-server tests and 19 desktop unit tests passed. The expanded native
package smoke also passed with an isolated synthetic package made from the prior
verified Linux wheelhouse and current lifecycle sources. It exercised offline
installation, Unicode/spaced paths, repeated installation, startup/version/import,
managed start/status/restart/stop, backup and empty-target restore, synthetic
upgrade persistence and data-preserving uninstall. This synthetic package is not
a new production distribution or a claim of final package verification.

The initial expanded smoke rejected bytecode files created by maintenance inside
an immutable bundle. Maintenance now disables bytecode writes; the affected
integration smoke passed afterward. No privacy checks were relaxed.

## Native Linux commands

Run from an extracted verified native package, using Python 3.12. No Node.js or
frontend compilation is required on the target. Python venv support and the
package's documented glibc/platform baseline remain prerequisites.

```sh
sudo python3.12 scripts/install-linux-server.py install
sudo python3.12 scripts/install-linux-server.py status
sudo python3.12 scripts/install-linux-server.py restart
sudo python3.12 scripts/install-linux-server.py backup
sudo python3.12 scripts/install-linux-server.py upgrade
sudo python3.12 scripts/install-linux-server.py uninstall
```

For a workstation without systemd, add `--user` and explicit absolute dedicated
`--prefix`, `--data` and `--config` paths. `install --user` does not start a
background process automatically; use `start`, then `status`. A stopped status is
an operational state, not evidence of readiness. The systemd path requires root
for management; normal runtime uses the `saplens` identity.

Use a newly extracted verified package for an upgrade. Do not modify the old
installed files or reuse a partially staged release without inspection.

## Backups and recovery

Backups may contain personal data, configuration and secrets. Keep them outside
source control and distribution outputs. POSIX archives are owner-only; Windows
maintenance applies explicit file ACLs. Logs and volatile runtime tokens are
excluded. External CSV paths and external secret files are not followed or
implicitly copied. Back up such external dependencies separately when required.

`backup` stops the managed service/process and leaves it stopped for operator
review. Restart explicitly after confirming success. Default backups are in a
sibling `<data-directory>-backups` directory; `--backup-dir` selects another
private location. The application rejects symlinks, unknown data ownership,
existing backup filenames and incompatible versions/schemas.

Restore never overwrites existing data. Stop the application, retain/rename the
old data and configuration directories, then restore into empty original paths:

```sh
sudo python3.12 scripts/install-linux-server.py restore \
  --archive /private/backups/example.sap-lens-backup.tar.gz \
  --restore-data /var/lib/sap-lens \
  --restore-config /etc/sap-lens --confirm-restore
```

The managed installation and its currently configured paths must still be
available to run this management command. If recovery moved those paths already,
use the installed venv directly instead:

```sh
sudo /opt/sap-lens/current/.venv/bin/python \
  /opt/sap-lens/current/backend/maintenance.py restore \
  --archive /private/backups/example.sap-lens-backup.tar.gz \
  --data /var/lib/sap-lens --config-destination /etc/sap-lens \
  --mode server --target-version 0.1.0 --confirm-restore
```

Review restored paths and permissions before restarting. Restored files are
private to the restoring identity; restore the service account's required data
ownership and configuration read access explicitly. Verify `status`, readiness,
source records and saved state before declaring recovery complete. Preserve the
old directories and the archive until acceptance. Do not restore newer data into
older binaries; use a compatible application version and backup.

## Initial pending list — historical, superseded by later sections

- Native Windows installer/service lifecycle, reboot, recovery and UNC acceptance.
- Real systemd installation/start/stop/reboot and service-account permissions.
- Docker lifecycle automation and its backup/restore integration.
- Windows desktop installer packaging and management integration.
- Final current-source production packages and one final integrated validation.
- Later queued modernization and privacy-safe example datasets have not started.

No GitHub Actions, tags, releases or pushes were performed for this phase.

## Follow-up guards — 25 October 2026

The resumed implementation defers the Unix-only `grp` import until actual Linux
system installation, so Windows backend test discovery can import the Linux
lifecycle regression module. Linux `/proc` lifecycle cases are explicitly
platform-scoped; a portable regression simulates an unavailable `grp` module.
Stopping and data-preserving uninstall no longer require valid runtime
configuration. Start/restart/readiness and destructive purge still validate it.
The deployment builder also holds the legacy Windows `local-build.lock` handle
while it owns shared build environments; actual Windows file-sharing acceptance
remains pending. The PowerShell facade explicitly requires version 5.1 or newer.

Targeted maintenance, Linux lifecycle, local deployment and packaging regressions:
**33 passed**. PowerShell parsing/static checks and whitespace checks passed.
These are narrow prerequisite fixes, not completion of the pending installer,
Docker lifecycle, native Windows or systemd acceptance work.

## Windows Service management implementation

The canonical WinSW management script now includes Upgrade, Backup and Restore.
It preserves registration/XML/identity, verifies the replacement's exact file set
and hashes, rejects downgrades through the new headless runtime, creates a private
stopped-state backup, stages application files and checks listener ownership and
readiness. Failed activation leaves the service stopped with backup and prior
binaries retained. Restore targets empty directories and never silently activates
them. Uninstall continues to preserve all private state and installation files.

The portable `test-service-management.ps1` helper tests passed on Linux/PowerShell:
valid identity, unexpected-file and checksum rejection, administrator XML
preservation and external-entity rejection. Static parsing passed for all ten
PowerShell scripts and three deployment-contract tests passed. The native SCM
smoke definition was extended to backup, restore and same-version staged upgrade;
it has **not been executed here**. Windows installer, real service upgrade,
reboot/recovery/UNC and Docker lifecycle acceptance remain pending.

## Docker offline lifecycle

`deploy/docker/manage.sh` is included as `manage.sh` in offline packages. It uses
Docker Compose and the packaged Python runtime, with no host Python requirement.
It supports install/start/stop/restart/status/upgrade/backup/restore/uninstall,
immutable image selection, private configuration preservation, exact package
verification and explicit confirmation for managed-volume purge. Normal runtime
privileges are unchanged. Isolated maintenance helpers use only DAC_OVERRIDE and
CHOWN, explicit application mounts and no network or Docker socket.

Actual disposable Docker acceptance passed on this Linux engine: offline image
load and installation, repeat installation, Basic authentication, synthetic CSV
import, private stopped-state backup, same-version staged upgrade, restart,
configuration/secret/data preservation, preserving uninstall, empty-volume data
restore with separately staged configuration, readiness and an isolated confirmed
purge which preserved the other installation's volume. Two CLI admission tests
also passed. All test containers and volumes were removed.

The test image was derived from the previously validated `0.1.0-alpha.1` image
with the current maintenance module. This validates the management integration;
it is **not** a newly validated current-source production distribution. The image
fixture initially retained a restrictive source mode on the copied module; its
test COPY now sets 0644, matching the production Dockerfile's existing runtime
permission normalization. An earlier helper traversal failure was fixed by
including DAC_OVERRIDE in the temporary archive ownership helper. No runtime
permissions or package/privacy checks were relaxed.

Production packaging now runs the lifecycle smoke after the existing image
smoke, includes the management entry point and proprietary notice, and retains
third-party notices. Native and Windows service packages also include LICENSE.md;
the service verifier requires that known file explicitly. Current-source final
packages, Windows desktop installer work, native SCM/systemd, reboot/recovery and
UNC acceptance remain pending. No image registry or GitHub publication occurred.

## Desktop installer and shared recovery guards — implementation pending Windows

The desktop deployment path now wraps the existing canonical portable EXE in a
per-user Inno Setup 7.1.0 installer, with hash-pinned build-tool provisioning,
WebView2 prerequisite checks, Start Menu/optional desktop shortcuts, Installed
Apps registration, downgrade rejection, private pre-replacement backup and
managed-file uninstall which preserves private data. The license is installed
as a notice, not an EULA. The legacy Windows release workflow is unchanged.
The outer deployment ZIP adds explicit installer assets/manifest; the portable
verifier's exactly-two-file ZIP contract remains unchanged and is called again
on download. Native installer acceptance is defined but has not executed here.

Four installer resource/source-contract and outer-distribution tests passed using synthetic parser
fixtures. They cover version identity, numeric version, unsigned GUI resources,
data-preserving recipe and explicit WebView2 requirements. They do not compile
Pascal Script or execute an installer. PowerShell parsing is separate from native
compiler/installation acceptance.

Restore now holds the actual runtime storage lease without initializing a marker
before extracting the backup, rechecks each copied hash, and cleans up failures
before releasing the lease. Normal runtime lease initialization is unchanged.
An explicit local `purge --confirm-purge` removes private files only from a stopped,
recognized store, rejects links, and retains the nonprivate lock stub after release.
Windows Service exposes that option only with Uninstall -PurgeData -ConfirmPurge;
Desktop removal is a separate explicit portable-maintenance command. Eleven
maintenance regressions passed, including lock exclusion, post-verification
archive change, confirmed removal and retention of external backups.

After the storage-lease changes, both disposable Docker lifecycle acceptance and
the offline native Linux installation/recovery smoke passed again. The latter
still did not exercise systemd. These remain synthetic integration fixtures,
not final current-source production package builds. The targeted backend set
passed 89 tests before the additional outer-distribution regression; that
additional regression also passed. All twelve PowerShell scripts parsed and the
portable service helper tests passed. No native Windows result is claimed.
