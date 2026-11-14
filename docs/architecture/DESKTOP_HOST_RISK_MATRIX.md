# Desktop host: compatibility and risk matrix

Companion to the [proposal](DESKTOP_HOST_DOTNET_PROPOSAL.md) and [roadmap](DESKTOP_HOST_MIGRATION_ROADMAP.md). Likelihood and impact are L/M/H and are
judgements from the repository, not measurements. **[A]** means unverified here.

## Compatibility

| Area | Statement | Status |
|---|---|---|
| Windows | repository floor is Windows 10 (`MinVersion=10.0`) and WebView2 86.0.622.0; the host adds the .NET runtime (bundled if self-contained) | floor [V], .NET and WebView2 support dates [A] |
| Linux build | backend, frontend and C# library tests build and run on Linux; the host may build with Windows targeting enabled; nothing Windows-specific runs | [A] for the host build |
| Python runtime | unchanged: 3.12 and the pinned requirements; backend packaged by PyInstaller onedir | [V] for pinning, onedir for Desktop is new |
| WebView2 | Evergreen runtime required, checked by the host and the installer; no fixed-version bundling proposed | [V] check exists, [P] for the host |
| Windows Server distribution | untouched: separate onedir bundle, Service Manager, WinSW | [V] separation |

## Risks

| ID | Risk | L | I | Mitigation | Test or gate |
|---|---|---|---|---|---|
| P1 | Capability crosses a process boundary and could leak | M | H | stdin handoff, never argv/env/file, no logging | host and backend tests; Phase 3 review |
| P2 | Validator drift if re-implemented in C# | M | H | keep validators in Python (validate endpoint), shared fixtures | contract tests |
| P3 | Orphan backend after a host crash | M | M | Job Object kill-on-close, `runtime.json` identity | native kill test |
| P4 | Backend executable substitution in a user-writable install directory | M | H | fixed path, hash against manifest before start | tamper test; note the same exposure exists today for the single EXE |
| P5 | Page script abuses the native bridge | L | H | exact-origin check, capability in every call, fixed method list | unauthorized-call tests |
| P6 | WebView2 navigates to or loads untrusted content | L | H | `NavigationStarting`, new-window and download cancellation, no DevTools | navigation tests (a gap today) |
| P7 | Packaging gets larger and more complex (two executables, per-file manifest) | H | M | per-file manifest, variant isolated until Phase 6 | Phase 4 gate |
| P8 | Onedir changes AV and AppLocker behaviour in unknown ways | M | M | test on a policy-enforced VM; signing remains a separate requirement | Phase 5 |
| P9 | The unexplained installer failure is blamed on the wrong layer and recurs | M | H | diagnose from `setup.log` first; add the log tail to the failure message | Phase 5 precondition |
| P10 | Two Desktop variants coexist and share one data directory | L | H | same mutex name and `StorageLease` mode marker refuse a second writer | native test |
| P11 | New third-party dependency (WebView2 SDK NuGet) and .NET servicing | M | M | exact pin, recorded in manifest, audited like Python pins | dependency audit step to add |
| P12 | Accessibility regression in the startup/recovery screen | L | M | keep the existing HTML document, test with keyboard and UIA | a11y spec |
| P13 | Enterprise policy blocks the host, backend or installer regardless of language | M | H | document signing and policy requirements; do not promise otherwise | Phase 5 |
| P14 | Test coverage gaps: WebView2 policy, activation by title, per-method capability check | H | M | add tests in Phase 2 and 3 | roadmap matrix |
| P15 | Time and attention diverted from stabilizing the current Desktop | M | M | keep Python Desktop shippable; stop/go gates | gates |

## Installer and enterprise deployment

Per-user install without elevation, `AppMutex`, isolated-AppId acceptance and data preservation are retained. New: the payload is a folder, the
WebView2 and (if framework-dependent) .NET prerequisites multiply, and unsigned binaries remain subject to SmartScreen, AppLocker and WDAC
(`docs/deployment/CODE_SIGNING.md`). A C# host does not remove any of these.
