# Installation and deployment (SAP Lens)

| Guide | Content |
| --- | --- |
| [DESKTOP_SERVER_DEPLOYMENT.md](DESKTOP_SERVER_DEPLOYMENT.md) | The two products: Desktop (WebView2, one user, loopback) and Server (console or Windows service); release folder, run commands, acceptance checklist |
| [SERVER_NETWORK_ACCESS.md](SERVER_NETWORK_ACCESS.md) | Every Server option and environment variable, HTTPS and certificates, host allow-list, Origin/CSRF, reverse proxy and trusted proxies, authentication, firewall, Windows service and systemd |
| [WINDOWS_DEPLOYMENT.md](WINDOWS_DEPLOYMENT.md) | SSH-driven build, verified deployment, rollback and recovery of the Windows service; `SapLens2` to `SapLens` migration; firewall behind a reverse proxy; Desktop and Server installers; acceptance checklist |
| [DOCKER.md](DOCKER.md) | Optional non-root .NET container, TLS, persistent volume, readiness and isolated configuration |
| [WINDOWS_TEST_VM.md](WINDOWS_TEST_VM.md) | Windows test machine runbook: native release build, test launcher, TLS checks, logs and acceptance levels |

## Commands

```powershell
# Windows release folder (Server and Desktop, versioned, with build-manifest.json and SHA256SUMS)
powershell -NoProfile -File .\backend\scripts\build-release.ps1 -Output C:\saplens\builds
powershell -NoProfile -File .\backend\scripts\verify-release.ps1 -ReleasePath <release folder>
# Installers (Inno Setup 6) from a verified release folder
powershell -NoProfile -File .\backend\scripts\build-installers.ps1 -ReleasePath <release folder> -Output C:\saplens\installers
# Managed Windows service deployment on the host (or over SSH with backend/scripts/deploy/deploy-windows.sh)
.\backend\scripts\deploy\Deploy-SapLens.ps1 -Action Status
```

The previous `experiments/dotnet-backend` path is historical. Current checkouts use
`backend/scripts`; the deployment resolver supports older commits for compatibility. Installed services run from the deployment's release folder (`ReleasesRoot\current`) and are not affected by the
repository layout.

SAP Lens 1 deployment (WinSW service, Docker, Linux native, v1 installer): [legacy v1 deployment](../legacy/v1/deployment/README.md).
