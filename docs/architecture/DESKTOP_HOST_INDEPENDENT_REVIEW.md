# Independent review: .NET Desktop host proposal

Reviewer scope: challenge [ADR 0001](decisions/0001-dotnet-desktop-host.md) and the four companion documents against the source at `dc52746`+
(documentation only; no application, test, build or CI file changed; no installer was run). Evidence labels: **[V]** verified in source or by a
harmless local reproduction, **[J]** engineering judgement, **[H]** unverified hypothesis. Paths are repository-relative with line numbers.
The earlier documents are preserved; where this review contradicts them it says so (section 7.3).

## 1. Executive summary

- **Recommendation: prototype .NET, conditionally and time-boxed; do not adopt.** The case for a native host rests on process ownership,
  navigation control and a native shell, not on any defect shown to originate in the host layer. [J]
- **The most important finding is not about .NET.** The Desktop installer runs `SAP-Lens.exe --maintenance backup --mode desktop --allow-legacy` in
  `PrepareToInstall` (`deploy/windows/desktop-installer.iss:238-241`). Since the encrypted-backup change (`09b82d4`, 2026-11-12, after the last
  installer change `7b4c4c8`, 2026-11-11), that command fails with exit 1 when no host backup key is configured (`backend/portable_backups.py:185`,
  `backend/backup_crypto.py:107-118`). I reproduced this on Linux with a data directory holding only `settings.json`, the exact shape the
  acceptance harness creates (`scripts/test-desktop-installer.ps1:72`). It is the best-supported hypothesis for the `first isolated installation`
  failure, and, if confirmed, also blocks real upgrades for any user who never configured a key. A new host does not change it.
- **The proposal under-counts three dependencies**: the installer executes the application EXE during setup (so a folder payload changes
  `PrepareToInstall`), the Run-key autostart value points at the old EXE, and the 45 `pywebview` references in the frontend want one adapter first.
- **A real security gain exists**: the current host has no navigation, new-window or message-origin restriction (no such code in `backend/desktop.py`),
  and pywebview's bridge is available to whatever the window loads. A WebView2 host can enforce them. [V for absence, J for the gain]
- **A real security cost exists**: the capability token (`backend/desktop.py:558`) currently never leaves one process. A child backend creates a
  secret-handoff boundary, a process-ownership problem and an executable-integrity problem that signing, not hashing, would solve.

## 2. Verified architectural findings

| # | Finding | Evidence |
|---|---|---|
| V1 | The backend runs inside the window process (uvicorn thread), so ownership equals process lifetime and no orphan is possible | `backend/desktop.py:417-441` (`ManagedBackend`), `:483-495` (`close`), `:704-708` (`webview.start`) |
| V2 | The capability is generated in-process and reaches the page through the startup document and the `#session=` fragment; only the backend compares it | `backend/desktop.py:558-564`, `backend/main.py:149-173`, `:317-329` |
| V3 | The `NativeDialogs` bridge has 19 methods, each repeating `hmac.compare_digest` | `backend/desktop.py:210-395` (checks at 219, 226, 232 and 15 more) |
| V4 | The CSV/PDF/DOCX validators and size caps live in the pywebview-coupled module | `backend/desktop.py:23-118` |
| V5 | The frontend binds to `window.pywebview` in 17 source files (45 references) and 22 test references | `frontend/src/App.tsx:39-43`, `components/Settings/SettingsView.tsx:141,208-209,450`, `components/Shared/ApplicationFooter.tsx:11-14`, `frontend/src/vite-env.d.ts` |
| V6 | No navigation, new-window or origin handling exists in the desktop host; hardening is limited to `ALLOW_DOWNLOADS=False`, `ALLOW_FILE_URLS=False`, `private_mode=True`, `debug=False` | `backend/desktop.py:704-708`; `grep -in navigat backend/desktop.py` is empty |
| V7 | Desktop is PyInstaller one-file, Server is onedir; they already differ | `scripts/build_system/windows/stages.py:172`, `scripts/build_system/windows/server.py:61` |
| V8 | One writer per data directory is enforced by a file lock independent of the process model | `backend/storage_lease.py:21` (`msvcrt.locking`), `:24` (`flock`) |
| V9 | The single-instance mutex is also taken by maintenance commands | `backend/instance.py:17-21`, `backend/maintenance.py:100-103` |
| V10 | Autostart writes `sys.executable` into `HKCU\...\Run` | `backend/windows_tray.py:234,245-249` |
| V11 | The installer extracts the application EXE to `{tmp}` and executes it for version check and backup | `deploy/windows/desktop-installer.iss:210-214,238-241` |
| V12 | Window activation finds the first window titled exactly `SAP Lens` | `backend/instance.py:35` |
| V13 | WebView2 detection is implemented twice with different registry coverage | `backend/windows_runtime.py:3-15` (HKCU and HKLM, both views) vs `deploy/windows/desktop-installer.iss:151-157,168` (HKCU, HKLM32, HKLM64) |
| V14 | The Python Desktop has not produced a defect traced to the host layer in the evidence reviewed (WinError 32 was storage, identity drift was build metadata, the installer failure is below) | `docs/development/PROGRESS.md`, this review section 7 |

## 3. Architecture comparison

Ratings are judgements [J] from this repository; "-" means no meaningful difference.

| Criterion | A. Keep Python/pywebview and improve | B. WinForms + WebView2, child Python backend | C. WPF + WebView2 | D. Alternatives |
|---|---|---|---|---|
| Maintainability, debt | one language, one process; debt is the ctypes tray and `desktop.py` size | two languages and toolchains, a protocol between them, but a thinner Python layer | like B with more framework code | Electron/Tauri add a third runtime: not meaningful here |
| Windows integration | ctypes and pywebview internals (`window.native.FormClosing`, `windows_tray.py:329`) | first-class (NotifyIcon, dialogs, DPI, session end) | same as B | Edge `--app` mode: no native dialogs, breaks V3, rejected |
| Security / attack surface | smallest: no IPC, no second binary; weak navigation control (V6) | adds IPC, a second binary and a secret handoff; can add strict origin control | as B | - |
| Deployment / installer | one EXE; installer already built around it (V11) | folder payload, per-file manifest, installer and Run-key changes (V10, V11) | as B | - |
| Startup / memory | one-file extraction per launch **[H]**, one process | two processes plus the host runtime; extraction avoided with onedir **[H]** | slightly heavier than B | - |
| Debugging, observability | single process log | host log plus backend log; clearer failure attribution | as B | - |
| Frontend compatibility | exact | needs the bridge shim or adapter (V5) | as B | - |
| Linux development | unchanged | backend and frontend unchanged; host build unverified **[H]** | WPF targeting from Linux is less certain **[H]** | - |
| Long-term support | pywebview and PyInstaller pins already managed | adds .NET LTS cadence and one NuGet package | as B | - |

Option A is not a strawman: three of the claimed B benefits can be had inside A. **A+** = (1) one frontend native adapter (section 5.3), (2) PyInstaller
**onedir** for the Desktop (the Server already does it), (3) navigation/new-window hardening if pywebview exposes the hook **[H: verify in the pinned
pywebview 6.2.1]**, (4) installer diagnostics (section 7). A+ keeps the in-process security property (V1, V2). B's remaining unique gains are native
shell quality, WebView2 policy hooks that pywebview lacks, and a testable C# library.

## 4. Security findings, ranked

| Rank | Severity | Finding | Evidence | Regression vs today? | Required automated test |
|---|---|---|---|---|---|
| S1 | High (availability, verified) | Installer backup step fails closed without a backup key, aborting installation and upgrade; no installer test exercises it | iss `:238-241`; `portable_backups.py:185`; `backup_crypto.py:107-118,134`; `test_desktop_installer.py:156` only greps the string | pre-existing since `09b82d4`; independent of host | backend: run `maintenance backup --mode desktop --allow-legacy` on a settings-only directory in a temp dir and assert the intended outcome after the fix; Windows: installer acceptance |
| S2 | High if adopted | Capability crosses a process boundary; exists in host memory and backend | V2 vs proposal 5.1 | yes, new | backend: capability accepted only from stdin; never in argv, env, files or logs (log scan test); host: token never serialised |
| S3 | Medium | Backend executable chosen by the host; a hash check inside a user-writable directory does not stop a same-user attacker who can replace both host and manifest | proposal 5.2; install dir is per user (`iss:43`) | same exposure as the single EXE today, no better | Windows: tamper tests prove detection of accidental change only; real protection needs signing (Q4) |
| S4 | Medium | JavaScript-to-native messaging: a shim injected in every frame and origin, and `WebMessageReceived` from any frame, would widen the bridge | proposal 5.3 | pywebview's bridge has the same property (V6), so not worse, but the fix is available only in B | host: messages from a non-backend origin or sub-frame are rejected; unknown method rejected; token required |
| S5 | Medium (verified gap) | Current host has no navigation or new-window control | V6 | pre-existing | native: attempt to navigate or open a foreign origin is blocked (works for A+ only if pywebview offers a hook) |
| S6 | Medium | Job Object semantics: kill-on-close covers host exit, but a PyInstaller one-file backend starts a child, and breakaway or nested jobs weaken it | proposal 4.2; V7 | new | native: kill the host, assert no backend and no listener remain; run with onedir only |
| S7 | Low | Two guards split: host holds the mutex, backend holds the storage lease; maintenance takes both (`maintenance.py:100-105`) | V8, V9 | semantics preserved if both are kept | native: duplicate launch and maintenance-while-running both refused |
| S8 | Low | Window activation by title only | V12 | pre-existing | native: a foreign window with the same title is not activated, or the contract is changed to a handle |
| S9 | Info | AppLocker/WDAC: language does not change policy outcomes; a second binary and many DLLs must be allowed; unsigned binaries remain at the mercy of policy | `docs/deployment/CODE_SIGNING.md` | no change | acceptance on a policy-enforced VM |
| S10 | Info | Supply chain: a NuGet package and the .NET runtime join Python and npm; no audit step exists for them | proposal 6 | new | CI-free local audit: lock file plus `dotnet list package --vulnerable` equivalent, run in `build.ps1` |

Invariants and tests that must exist before any host is shipped: loopback-only connection (a host unit test with a non-loopback origin), exact Host
and peer (existing backend tests), wrong capability gets 403, native call without capability opens no dialog, validators identical for both entry
points (shared fixtures), single writer (two backends on one directory), no orphan after host kill, navigation blocked, per-file hash mismatch refused,
no secret in logs.

## 5. Migration risks and hidden complexity

### 5.1 Is the roadmap realistic?

Phases 2 to 6 are ordered sensibly but **omit prerequisites and under-state Phase 4**. [J]

- **Missing Phase 0 (prerequisites):** (a) resolve S1 and capture the Windows installer evidence (section 7); (b) the frontend native adapter;
  (c) an onedir Desktop experiment inside the Python product; (d) decide Q4, Q5.
- **Hidden requirements:** the installer runs the application EXE for `version-check` and `backup` before replacing files (V11), which assumes one
  EXE; a folder payload means extracting the whole backend to `{tmp}` or running the old install. The Run-key value must be rewritten (V10). The
  installed variant must reuse the production AppId and directory to upgrade in place, but the roadmap isolates the variant with a separate test AppId, so
  "upgrade from Python Desktop to the host" is not exercised by that isolation. `test-windows-exe.ps1` and `runtime.json` assume one process.
  WebView2 detection exists twice with different coverage (V13); a third copy in C# would add drift.
- **Potentially breaking:** extracting the startup sequence from `desktop.run()` touches the path every Desktop launch uses (the largest regression
  risk in Phase 2); the window title `SAP Lens` is a contract for activation (V12) and for tests.
- **Rollback gaps:** Phase 5 says reinstall the Python package, but a host-variant install may have rewritten the Run key and shortcuts; rollback
  needs those undone, and a data-compatibility check in both directions.
- **Unnecessary work:** a C# re-implementation of validators (Q3); a separate shim if the adapter is introduced first.
- **Reduce complexity:** do Phase 0 first; prototype without installer or tray; keep both variants on one AppId only at Phase 6.

### 5.2 Rollback

Add: (1) a rollback script that restores Run key, shortcuts and files from the previous manifest; (2) both-direction data-compatibility tests; (3) the
Python Desktop remains the default and release artifact until the Phase 6 decision.

### 5.3 The `window.pywebview.api` shim

**Preserving the name long term is not the right decision.** [J] It keeps a removed dependency's name as a permanent contract, and the 45 call sites
plus 22 test references each embed it. A shim is still the cheapest way to prove the host in Phase 2. Recommended order: (1) introduce one typed module
(for example `frontend/src/lib/nativeBridge.ts`) that all call sites use and that today delegates to `window.pywebview`; (2) tests mock that module
(Playwright specs stay valid because the behaviour is unchanged); (3) the host implements the adapter's transport directly, so the shim is internal to
one file and can be renamed freely. This is a frontend-only change that helps either option and is testable on Linux.

## 6. ADR questions Q1 to Q8

| Q | Recommendation | Reasoning | Tradeoff | Evidence still needed | Status |
|---|---|---|---|---|---|
| Q1 target framework | Current .NET LTS at Phase 2 start; baseline Windows 10 22H2 or newer unless the project's own floor says otherwise | LTS lowers servicing churn; the repo floor is Windows 10 (`iss:50`) | newer LTS may drop older Windows | Microsoft support-policy page and an SDK; neither was available here | Conditional |
| Q2 self-contained vs framework-dependent | Self-contained | no extra prerequisite beside WebView2, tested runtime ships | larger download; we own runtime updates | measured size and update plan | Conditional |
| Q3 validators | Keep validators in Python behind a capability-guarded validate endpoint; long term, let the backend hand the bytes to the host so the page never supplies them | one source of truth; the validators and tests exist | one more endpoint and a round trip | design review of the endpoint (no paths, server mode excluded) | Conditional |
| Q4 signing | Treat as a gate: no adoption without a signing plan | hashes inside a user-writable directory do not stop a same-user attacker (S3); AppLocker/WDAC need signatures | cost, certificate custody | certificate availability, target enterprise policies | Unresolved (business decision) |
| Q5 NuGet dependency | Allow one pinned package only with a lock file, vulnerability audit in `build.ps1` and an offline restore story | parity with the pip and npm controls | build complexity | policy decision and an audit tool choice | Conditional |
| Q6 shutdown | stdin EOF as the graceful signal, plus a backend watchdog that exits when stdin closes, plus a Job Object; no authenticated shutdown endpoint | no new network surface; works even if the host crashes | stdin handling in the backend entry | prototype test of crash and forced kill | Ready |
| Q7 installer failure | Treat as the first task, independent of the migration; evidence plan in section 7 | S1 explains it plausibly and also affects production upgrades | none | Windows `setup.log` and the diagnostics in 7.4 | Conditional (hypothesis strong, unconfirmed on Windows) |
| Q8 shim naming | Introduce the frontend adapter first; the transport may keep the pywebview name internally for the transition only | see 5.3 | one frontend refactor before the prototype | none | Ready |

## 7. Installer investigation

### 7.1 What the code supports

`scripts/test-desktop-installer.ps1` fails with `Native process failed during 'first isolated installation' (exit 1)` when the compiled test Setup exits
non-zero (`:32-37`, stage set at `:84`). Hypotheses the **code** supports, in order of support:

| H | Hypothesis | Code that supports it | Against it |
|---|---|---|---|
| H1 | `PrepareToInstall` aborts because the pre-install backup fails: the harness writes `settings.json` into the data directory first (`test-desktop-installer.ps1:72`), so `HasFiles` is true and Setup runs `SAP-Lens.exe --maintenance backup --mode desktop --allow-legacy` (`iss:227-241`); `backup_stopped` calls `crypto.host_key(data)` (`portable_backups.py:185`), which requires `SAP_LENS_BACKUP_KEY_FILE` or `backup-key-location.json` (`backup_crypto.py:107-118`); the harness sets neither (`:21`, `:67`). **Reproduced on Linux: exit 1 with `BackupCryptoError`.** Timeline fits: installer last changed 2026-11-11, encrypted backups landed 2026-11-12 | exit-code mapping unverified (below); an earlier passing run after `09b82d4` would refute it |
| H2 | `InitializeSetup` returns False: workspace variable missing or boundary mismatch (`iss:158-166`), including any reparse point in the workspace's ancestor chain (`iss:103-116,133-134`) | the harness sets the variable (`:66-67`) and a boundary failure would have failed the earlier compile/plan steps only partly | plausible only if the temp path crosses a junction or the `.owner` marker differs |
| H3 | WebView2 below 86.0.622.0 or in a registry view the Inno check does not read (`iss:151-157,168`, V13) | an earlier native smoke in the same build would also have needed WebView2 | if the Desktop smoke of that run passed, this is weakened; **unknown** from the report |
| H4 | `AppMutex` held by a running SAP Lens (`iss:58`) | harness pre-checks the mutex (`:17`) | would have failed before the stage |
| H5 | The installer's `/DIR` or `/LOG` quoting or path problem | `:45` builds `/DIR="..."` inside an argument array | low |
| H6 | Antivirus, SmartScreen or policy blocking the unsigned test installer | unsigned binaries (`CODE_SIGNING.md`) | those usually give a different exit or never start; not distinguishable from code |

### 7.2 Is it the installer or the harness?

The harness reached the stage, verified the compiled proof and file hash, and started the installer (`:75-85`), so the installer process ran. The
failure text contains no log content, so the **message cannot distinguish** H1 to H6. The retained workspace contains `setup.log`
(`/LOG="<root>\setup.log"`, `:45`), which can.

### 7.3 Correction to the earlier documents

[`DESKTOP_HOST_CURRENT.md`](DESKTOP_HOST_CURRENT.md) section 6 attributes exit 1 mainly to `InitializeSetup`, based on an unverified recollection of Inno's
exit codes, and omits H1. It also says the migration "does not change" the failure; that is true only for the cause, since the proposal itself
changes `PrepareToInstall` (hidden requirement in 5.1). That document is left unchanged as history; this section supersedes it for the installer.

### 7.4 Windows diagnostics to distinguish the hypotheses (read-only)

Run on the machine that retained the workspace; do not run production Setup and do not delete the workspace.

1. Read `<workspace>\setup.log` completely. In silent mode `SuppressibleMsgBox` text is written there: the **message text** identifies H2/H3
   (`Test-only Setup requires…`, `Microsoft Edge WebView2 Runtime … is required`) versus H1 (`Private data backup failed…`, from `PrepareToInstall`).
   Also note the last `Exec` line and its exit code (H1 shows the child's non-zero exit).
2. `reg query` the WebView2 key `HKCU\Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}`, and `HKLM` with `/reg:32` and `/reg:64`; record `pv` (H3).
3. Check whether `Local\SAPLensDesktop` exists and which process holds it (H4); list running `SAP-Lens*` processes.
4. `Get-Item` attributes of every ancestor of the workspace for `ReparsePoint`, plus the `.owner` content versus the test AppId (H2).
5. Run the retained **test** installer manually and silently with the same arguments and the same environment variables, outside the harness, and record its exit code.
6. Run the packaged EXE's maintenance command by hand against a copy of the workspace data directory: `SAP-Lens.exe --maintenance backup --mode desktop --allow-legacy --data <copy> --output <new file outside data>`; expect `BackupCryptoError` under H1.
7. Windows Application event log and Defender protection history for the installer and `{tmp}\SAP-Lens.exe` at the failure time (H6).

### 7.5 Controls that must survive any migration

Isolated test AppId with production-key invariance, per-user install, `AppMutex` on the same name, hash equality of payload and verified artifact,
data and backup preservation across reinstall and uninstall, `.owner` boundary and reparse-point checks, cleanup of the owned workspace only, and
a pre-upgrade backup that **succeeds or visibly aborts with a stated reason** (see S1).

## 8. Recommended roadmap improvements

1. **Phase 0 (new):** (a) decide and fix S1 (a separate change with its own tests and owner approval: for example create or require a key, or a documented
   unencrypted legacy path for installer backups), (b) collect section 7.4 evidence, (c) add the setup-log tail to the acceptance failure message,
   (d) frontend `nativeBridge` adapter, (e) onedir Desktop experiment in the existing Python build (measure startup, size, AV behaviour), (f) Q4 and Q5.
2. **Phase 2:** unchanged scope, plus: stdin watchdog, Job Object test, no installer, no tray, success measured against a written parity list.
3. **Phase 3:** add the WebView2 policy tests (S4, S5), the validators decision (Q3), the Run-key rewrite and activation contract (V10, V12).
4. **Phase 4:** add installer `PrepareToInstall` redesign (V11), per-file manifest with tamper tests, same-AppId in-place upgrade test.
5. **Phase 5:** add both-direction upgrade and rollback including Run key and shortcuts.
6. **Kill criteria for the prototype:** stop if Phase 0 shows A+ delivers the onedir and adapter benefits and no host-layer defect remains
   unexplained, or if the secret handoff or Job Object tests cannot be made deterministic, or if signing (Q4) is unavailable.

## 9. Recommendation

**Prototype .NET** (conditional and time-boxed), **after Phase 0**. Not "Adopt": no host-layer defect is evidenced and the security trade is two-sided.
Not "Stay with Python permanently": a native host offers navigation control, deterministic ownership and a testable shell that A+ cannot fully match.
If Phase 0 leaves the host layer with no demonstrated pain, the sound choice is A+ and shelving the prototype.

## 10. Acceptance criteria to proceed to the Phase 2 prototype

1. The installer failure is explained from `setup.log` and the section 7.4 evidence, and S1 has an approved fix plan.
2. A frontend native adapter exists and the frontend suites pass unchanged.
3. An onedir Desktop experiment has measured startup time, memory, size and AV/AppLocker behaviour against the one-file EXE.
4. Q1, Q2, Q5 are decided; Q4 has an owner and a date; Q3 and Q6 are accepted as designs.
5. A written parity list and measurable success criteria (startup, shutdown, crash recovery) are agreed.
6. The ADR is explicitly approved by its owner; until then it stays **Proposed – pending approval**.
