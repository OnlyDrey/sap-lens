# Release status and checkpoint (Phases 3 to 6)

## Permanent Windows service promotion — local acceptance completed

2026-11-21: **PASS for controlled local promotion; Pangolin/external authenticated acceptance remains OUTSTANDING.** Existing artifacts under
`C:\AuthLens-Acceptance\promotion-0372c2b687d14ed0bb312bc9eebfd6a4` were reused. A transactional comparison found no business/security-table
changes since the verified current-state backup, so no replacement backup or product rebuild was needed. The old installation/data/configuration,
isolated data and every backup remain retained. The current source is build **0c2e999** / product **2.0.0-alpha.1**.

### Permanent service and state

- `AuthLens` is **Running**, **Automatic**, account **NT SERVICE\AuthLens** (service SID enabled); final accepted process **12272** after a
  controlled restart. Root `C:\ProgramData\AuthLens`; program `releases/current/server/AuthLens.Api.exe` links to the verified
  `AuthLens-2.0.0-alpha.1-20261121-011033-0c2e999-win-x64` server package. Persistent state is in `data`, accounts in `data/security/accounts.sqlite3`,
  key in `keys/host.key`, TLS in `tls/server.pfx` plus protected password file, deployment configuration in `config/deploy.json`.
- Existing public deployment-module operations initialized/protected the new root, published/verified the server package, set the release link,
  configured the existing service and granted its least-privilege file rights. The NTFS audit passed. Normal Windows chain/hostname TLS probes
  were used; the deployment module's skip-validation diagnostic probe was not used.
- The owned console was stopped gracefully before copying. All **25** persistent files were copied offline and SHA-256 matched before startup;
  no old archive was restored over the validated state, and no SQL was edited directly. The identical copied key was selected through supported
  `--backup-key use`. Source data stays untouched and the original service installation stays separate under its retained acceptance root.
- Pre-copy, first-service-start and post-restart comparisons match **every business/settings/evidence table**, account credentials/roles, policy,
  metadata and all previous audit rows. No operational security table changed in the observed acceptance window. Counts: 38 revisions / 332,348
  records, 3 Account Review events, 1,086 SoD events, 1,023 evidence snapshots, zero saved filters and five refresh reports. Integrity, foreign keys
  and evidence content hashes pass. `arkasa` remains the one active administrator; `acceptance-admin` remains absent. Schema is unchanged.
- Scheduled refresh is disabled; all four sources remain static with empty external paths and no queued/running jobs or pending restore. Normal
  service workers therefore have no external refresh to execute. The temporary 18796 process is stopped and no listener remains there.

The first stop attempt also interrupted its PowerShell controller after gracefully stopping the source, before data copy/service changes. The
last working source was immediately resumed against the same intact data (PID 16076), with normal HTTPS readiness. A separately built guarded
signal utility then passed a disposable rehearsal and sent Ctrl+C without attaching the migration controller to the source console. The successful
continuation reused the already prepared empty root, retained the first attempt and recovery logs, migrated the stopped state and completed the
service restart/persistence checks. No forced source stop or database replacement was used.

Local `https://10.0.7.50:18795/health/ready` and frontend/index/build identity pass with certificate validation enabled. All **91** initial frontend
assets returned 200. The sign-in page rendered at 390/768/1440 px without horizontal overflow; account setup remains closed. These unauthenticated
checks do not replace a fresh interactive `arkasa` sign-in or authenticated dashboard acceptance after cutover. No password was reset or collected.

### Pangolin and remaining external checks

The external browser redirect identifies existing resource **sap-lens**, auth-resource GUID **7537c399-5952-46af-9290-6c38578e7341**, at
`auth.akio.no`. Its authentication gate is retained. Pangolin management access, current target configuration, Newt site/host/network and connector
reachability are unavailable through the connected tools. No resource, tunnel, policy, DNS/router setting or public certificate was changed.

The operator must verify/update **only that existing resource**:

| Setting | Required verification |
| --- | --- |
| Domain / policy | Keep `lens.akio.no` and existing authentication/access policy |
| Upstream | Certificate-valid reachable hostname/IP for this VM, e.g. **10.0.7.50**, protocol **HTTPS**, port **18795**; if it still uses 18796, change only that target port |
| TLS / SNI | Keep verification enabled; use a server name covered by the preserved backend certificate and trust its issuing certificate on the verifying proxy/connector. Never skip validation |
| Newt site | Keep the existing connector; prove its TCP/HTTPS reachability to 10.0.7.50:18795 from its own network location |
| Host / forwarding | Inspect the actual Host and forwarded headers and then configure only the proven trusted peer. Current AuthLens configuration remains the validated local host list with no guessed trusted proxies; public-origin forwarding/authentication is not yet accepted |

TLS to a certificate-valid upstream IP/name does not inherently need `lens.akio.no` in its SAN. Public TLS and backend TLS are distinct. The
installed build additionally couples its allowed-HTTP-host startup validation to certificate names; public Host/forwarding support must therefore
be checked against the actual resource configuration, without weakening Host/Origin or certificate safeguards. The lack of management access is
not used to block the completed local service promotion or to infer a certificate error in Pangolin.

The only new firewall rule is service-scoped `AuthLens-Service-18795`: inbound TCP, local address **10.0.7.50**, port **18795**, profiles **Private,
Domain**, remote **LocalSubnet**. It opens neither the Public profile nor arbitrary remote addresses. If the actual connector is outside that scope,
identify its exact private peer before any narrowly scoped adjustment. No router port-forward/public backend exposure was added. Independent LAN
reachability and outside-network authenticated flow remain unverified. VM public probes still receive 401 at the existing Pangolin gate; the
browser displays its login page. This proves the gate, **not** AuthLens backend/asset/API/admin accessibility through it. Production code contains
no AuthLens WebSocket/EventSource channel to exercise; Newt tunnel transport itself is not claimed verified.

`ROLLBACK.md` in the retained promotion root now describes the accepted service and post-cutover no-data-loss rules; its original version is
preserved as `ROLLBACK-precutover.md`. After newer writes, rollback must retain/copy the CURRENT stopped service state into a new protected directory,
not blindly resume the frozen 18796 database or start the original stale installation. No full regression, CI, push or merge ran. Overall production
readiness is not declared until authenticated local/external and independent-network acceptance is complete.

## Permanent-service promotion preflight

Historical initial checkpoint; local promotion is subsequently completed above. Its external-access findings remain acceptance limits, not proof
that a certificate-valid upstream connection must use the public hostname.

2026-11-21: **BLOCKED before cutover; the last working validated instance is preserved.** The requested target is existing service `AuthLens`,
Automatic, `NT SERVICE\AuthLens`, HTTPS 18795. It is Stopped/PID 0, with no 18795 listener. Its existing junction/configuration still references
the separate `server-v1-29d52739de914a138386dee79c11aab2` acceptance root and build **4b20cdb**. The validated instance remains running as owned
process **11728** from `fresh-67da2781db144878816e6502f5734d4f/program-0c2e999`, data under that root's `data`, HTTPS **18796**, accounts mode,
`--no-worker`. Its existing **0c2e999** release verifies all 17 artifacts and build identity; no rebuild was needed. Canonical `C:\ProgramData\AuthLens`
was absent. No service, junction, data location, ACL, firewall, DNS, router, proxy or certificate trust was changed during this preflight.

The operator has subsequently completed permanent deletion of `acceptance-admin`: read-only inspection now finds only enabled administrator
`arkasa`, zero temporary-account rows, no orphan sessions/one-time codes, and one `user.delete` audit event. Account database schema 1, integrity
and foreign keys pass. This supersedes the earlier pending deletion checkpoint below; the agent did not perform that operator action. The shared
browser still returns 401 for `/api/auth/me`, so fresh administrator authentication/permission acceptance is not verified by this task.

### Network gates

- `lens.akio.no` resolves to Cloudflare addresses. VM requests receive **401 text/plain** before AuthLens at both `/` and `/health/ready`.
  The external TLS hostname/chain validated normally from the VM (TLS 1.3, certificate `CN=akio.no`, Google Trust Services WE1, expires
  2027-02-17). It was not modified. This does not verify the AuthLens upstream, sign-in, assets, API or WebSocket traffic.
- No local reverse-proxy/connector process/service or known connector directory was found. No available SSH host/connected management tool
  identified the remote resource. Its current target port, SNI/upstream trust, Host/forwarded-header behavior and exact trusted TCP peer are
  unknown. Do not assume that it routes to 18795, or guess a trusted-proxy address. The operator has been asked for its management/configuration location.
- Both preserved backend TLS copies have the same self-signed certificate, SANs `localhost`, `WINDOWS-VM`, `10.0.7.50`, expiry 2027-02-18.
  They lack `lens.akio.no`. AuthLens must have certificate coverage for its allowed hosts; do not add the external allowed host and weaken
  validation to make it start. Resolve backend SAN/upstream trust with the existing proxy setup while preserving the external certificate/security.
- Ethernet is Private and Windows firewall profiles are enabled. The read-only queries found no AuthLens-specific/explicit 18795/18796 rule;
  this is not a proof of effective remote reachability or router port exposure. No public backend port was opened. A separate LAN machine and
  outside-network authenticated client were unavailable. Independent web probes could not access the public resource, so external application
  accessibility is **NOT VERIFIED**, rather than passed or inferred from VM-local DNS/TLS.

### Backup/recovery and rollback preparation

Protected root `C:\AuthLens-Acceptance\promotion-0372c2b687d14ed0bb312bc9eebfd6a4` retains exact SCM state, copied keys/TLS/configuration,
program/key/TLS SHA inventory, reports and a concrete `ROLLBACK.md`. Both source installations remain intact and in place. New encrypted archives
were created and fully verified through supported maintenance CLI:

| Instance | Archive SHA-256 | Accounts / enabled administrators |
| --- | --- | --- |
| Current validated state | `8d992e79b822c284ef89420ee0d8a0cca333a79c81d243e9096ae2b756646abb` | 1 / 1 |
| Preserved old installation | `26243af09edc37b6d9b0d3d4fde4bb4e163bf7a1bd9d9d256484570e610b3c39` | 1 / 1 |

The CURRENT validated archive was restored only into a new disposable rehearsal directory, never over a real instance or from the old supplied
archive. HTTPS readiness and console restart passed with normal TLS checks. Every business table/document, user/verifier, audit and policy matched
the authenticated backup; all 332,348 records, both history chains, evidence hashes, SQLite integrity and foreign keys passed. Settings content
matched; its revision had only the documented portable-restore increment. A separately ownership/console-membership-guarded Ctrl+C rehearsal
logged application shutdown without signalling either real instance. Rehearsal hosts are stopped and all recovery data is retained.

Transactional preflight fingerprints cover the 38 datasets, 332,348 records, 3 Account Review events, 1,086 SoD events, 1,023 evidence snapshots,
settings, zero saved filters, five refresh reports and all documents. Scheduling stays disabled. No direct live SQLite copy or SQL edit occurred.
These checks demonstrate current-backup recovery and console shutdown/restart, **not a tested SCM cutover/rollback**. The planned promotion must
gracefully stop the owned source, migrate its COMPLETE persistent state offline into a new protected service data directory, use the supported
deployment/ACL mechanisms, reselect the identical copied key and compare all state. It must not restore the original supplied backup. Rollback
must preserve newer writes: never point at a stale old database or automatically restore an older archive after post-cutover business changes.

Remaining gates: identify/verify the exact proxy resource and backend TLS/forwarding configuration; authenticate `arkasa`; rehearse the final SCM
rollback configuration; then perform controlled migration, virtual-account ACL/startup/readiness/restart checks, and independent LAN/external
authentication/assets/API/WebSocket acceptance where applicable. No full regression, push, merge or production-readiness claim was made.

## Permanent local-account deletion

Implemented: `DELETE /api/auth/users/{id}` and the confirmed **Delete account** action in Settings → User Management. Current administrator
authorization, CSRF, exact confirmed username and expected revision are required. Self-deletion and last-active-administrator removal are refused.
One account-store transaction removes the user/verifier, all sessions and owned one-time codes, minimizes ID-linked security-audit names while
keeping opaque accountability, and records `user.delete`. Failure rolls back audit minimization and removal together. Account schema remains 1;
application schema and immutable business evidence are untouched. Unlinked legacy audit text and retained encrypted backups are not rewritten;
see [account retention constraints](../deployment/SERVER_NETWORK_ACCESS.md#accounts-mode-default).

Focused validation: **64/64** in `AccountDeletionTests`, `AccountsTests` and `AccountCompatibilityTests`; **3/3** new browser/component tests
cover confirmation/cancellation/Escape, self/last-admin UI protection, exact DELETE payload, stale refusal, account/audit refresh and mobile dialog
containment. Frontend build/type checks and scoped lint passed. New backend cases exercise authorization/CSRF, name/revision/confirmation checks,
session/code removal, concurrent removal, unchanged unrelated accounts/application state, minimized accountable audit and injected audit-failure
rollback. No full regression ran. Test code initially hit xUnit analyzer rules and ambiguous heading/action selectors; corrected tests retained
the protections and original failed artifacts under ignored `build/test-artifacts/account-deletion`.

Two directly dependent profile/session browser cases also passed (**5/5 selected frontend cases in total**); their run was kept separate from
packaging because the release script rebuilds disposable frontend assets. The native release from **0c2e999** was verified (17 artifacts, clean
source identity, checksums, embedded UI, zero release-secret findings) and safely installed into the isolated root's `program-0c2e999` directory.
Only its owned console process was restarted, now PID 11728 on HTTPS 18796, same accounts/TLS/host configuration and `--no-worker`. The previous
program and state are retained for binary rollback. Schema inspection refused pending changes; all six application migrations and account schema
1 remain unchanged. Both instances' eight application/settings/history-table and every document fingerprints match before/after. The original
`AuthLens` service remains Stopped, PID 0, without configuration changes.

**Actual deletion acceptance: BLOCKED on authenticated operator access.** The port-18796 target remains `acceptance-admin`, already disabled,
with zero sessions; `arkasa` is the one active administrator. A fresh encrypted application/account backup was created and independently verified
(2 accounts, 1 enabled administrator) before the update. Live account integrity/foreign keys pass. No destructive API call has occurred: the shared
browser remains on sign-in, and `/api/auth/me` returns 401. The operator has been asked to sign in as `arkasa` without sending a password in chat.
Its authentication and post-delete access, permanent row/verifier/code/session removal, and deployed deletion/audit behavior cannot be claimed
verified until that authenticated API operation is actually performed. No recovery/password reset, direct SQLite edit, credential-file deletion,
change to another installation, push or merge was used to bypass this gate. The upgraded Server is left running.

## Fresh Windows Server package and supplied-backup restore

2026-11-21 (local date): **PASS for fresh isolated package/restore and exercised read-only workflows; left running for manual testing.**
The clean `791ac11896cae0721a8f17c7157232efc2363233` source includes the Account Review compatibility fix and responsive frontend, product
`2.0.0-alpha.1`. The existing Windows release script built a self-contained win-x64 package with .NET runtime 10.0.15; all 17 manifest artifacts,
checksums, embedded UI/build identity and the release secret scan passed. The 22 selected Account Review/migration tests passed; no full suite or
installer rebuild ran. An initial invocation with a relative output path failed the script's relative-file check after publishing; that incomplete
output was retained and never deployed. The successful invocation used an absolute output path and reused the unchanged passing focused tests.

- Verified release: `backend/artifacts/release/AuthLens-2.0.0-alpha.1-20261120-225824-791ac11-win-x64`.
- Separate protected installation: `C:\AuthLens-Acceptance\fresh-67da2781db144878816e6502f5734d4f`, program under `program`, database under
  `data/authlens.sqlite3`. No existing migrated database was copied. The original `AuthLens` service was already Stopped (PID 0) at task start
  and remains Stopped; its database/table/document fingerprints match. No SCM configuration or legacy/Desktop installation was changed.
- Server runs as a hidden isolated console process (initial PID 2328), accounts authentication, HTTPS port 18796, `--no-worker`. No second service
  or automatic restart/logon/reboot task was installed. Operator access on the VM: `https://windows-vm:18796`; IP fallback `https://10.0.7.50:18796`.
  Using the separate hostname avoids browser-cookie sharing with the old IP endpoint; otherwise use a separate browser profile.
- TLS uses protected file copies of the existing trusted machine certificate/password file; originals are unchanged and normal chain/hostname
  validation passed. A newly generated certificate's trust import did not complete; its files remain retained but unused. No TLS bypass was used.
  Other-client trust, DNS and firewall reachability were not established by the VM-local checks.

Supplied archive `AuthLens-backup-61af3b0a1d474e93bdaf41ead07346e5.slbak` remains byte-identical, SHA-256
`9e1785837ed5b1d4dc6af24a1e901687e61d9bed15b9c87b893214faf10c85ef`. Its SLBAK3 host-key fingerprint matched an available existing recovery key;
only a private key copy was selected. Supported `--backup-verify` authenticated/decrypted and verified the archive: version `2.0.0-alpha.1`, created
`2026-11-20T18:42:50.765931+00:00`, four members including an accounts store. A fresh empty host first reached administrator setup and was stopped.
Supported offline `--restore ... --replace-all-data` staged/confirmed the copied archive; HTTPS startup applied it and reported completed restore
with the expected archive SHA, never an empty fallback. The original input archive/key and all prior recovery artifacts were preserved.

Source-versus-restored comparison uses the authenticated staged backup itself, not assumptions from the earlier V1 migration:

| Retained data | Source and restored |
| --- | ---: |
| Dataset revisions / records | 38 / 332,348 |
| User/assignment revision records | 112,400 |
| Role revision records | 182,846 |
| Directory revision records | 36,550 |
| SoD matrix revision records | 552 |
| Account Review events / invalidations | 3 / 0 |
| SoD events / evidence snapshots | 1,086 / 1,023 |
| Saved filters / refresh reports | 0 / 5 |
| Enabled administrator accounts | 1 |

Every business table and historical document matched. Reads advanced only the assignment lifecycle's observed-source marker and integrity seal;
its items, baseline, revision and all other fields remain equal, and the new seal verifies. Both event chains and all evidence content addresses
verified, SQLite integrity/foreign keys passed, and all six known schema migrations are applied with none pending. Account credentials/roles remain unchanged; normal sign-in updates
last-login/audit/session state. Restore deliberately cleared four unavailable external source paths, made modes static and rebound lifecycle paths;
other settings matched. Scheduling was already disabled and stays disabled; background refresh remains off. No records were imported or edited.

Fourteen authenticated read routes passed plus sampled Account Review history, SoD history/evidence, frozen-period details, directory matching and
pure access-package CSV export. Current views show 265 SAP users, 96 catalogue roles, 1,767 directory records, 257 matched identities (6 missing
email, 2 unmatched), three reviewed/zero outdated Account Reviews and one SoD period. Access-package preview/export returned one exportable row;
it stores no business record. Zero saved filters is the actual backup state. The isolated Edge installed-frontend check passed Dashboard rendering,
Role Lookup, mobile drawer/Account Review, profile menu, viewport containment and absence of runtime errors. Node's `--use-system-ca` was needed
for the HTTP test client to use Windows certificate trust; certificate checks were retained. Initial browser navigation opens Data Sources because
the portable restore cleared old paths; **Back to AuthLens** exposes the retained snapshots without selecting a source or refreshing.

Private reports and the authenticated source snapshot remain under the acceptance root; no credentials, keys or record exports were committed.
PowerShell acceptance-client array wrapping/serialization mistakes were corrected without product changes or weakened assertions. The original
archive and original instance fingerprints were rechecked after use. No push/merge, version/CI change or production-readiness claim is made.
Manual business-action acceptance, installer upgrade/rollback, interruption recovery and off-VM connectivity remain separate gates.

## Account Review compatibility correction and isolated continuation

The source correction adds a local read-only V1 schema-2 comparator; it preserves the current .NET fingerprint format and immutable decision
history. It reproduces Python default JSON spacing, nested ASCII escaping and Unicode-scalar ordering without changing the global serializer.
Database invalidations and V1 `absent_since` markers remain stale regardless of matching hashes; unknown/schema-1 encodings do not gain fallback.
The real three migrated reviews are not automatically cleared or rewritten.

Focused regression: **22 passed, 0 failed** across `AccountReviewCompatibilityTests`, `AccountReviewTests` and `V1DataMigrationTests`, including
mixed formats/users, changed identity/account/assignment/group evidence, independent Python Unicode golden vectors, and exact database-history
preservation with a verified hash chain. The first affected migration run exposed a fixture assumption: a genuinely completed V1 review was
previously visible only because of false staleness. The fixture now requests completed reviews and explicitly asserts current/completed status;
its original source/history assertions remain. TRX evidence is under ignored `build/test-artifacts/review-compatibility`.

**Isolated Windows compatibility and recovery acceptance: PASS for the exercised paths.** An online SQLite copy of the migrated Server was
placed in a new ACL-protected acceptance root and run using the corrected API, separate accounts-mode loopback endpoints and `--no-worker`.
The exact archived V1 `rows`/`digest`/`validity` implementation was evaluated against complete source observations: all three decisions are
current/completed, matching the corrected API (0 outdated, 3 reviewed, 262 pending). Earlier reconstruction used a detail API capped at 100
transaction codes per assignment; the complete assignment sizes are 255, 649 and 387. Its contrary conclusion was an acceptance-oracle error,
not changed evidence. Original decision/evidence rows and hashes were never rewritten.

All 332,348 source records/38 revisions matched, SQLite integrity/foreign keys and both history chains passed, and all 539 assignment-lifecycle
items/baseline/revision remained equal with a valid seal. Health, anonymous/wrong-password rejection, authenticated dashboard/database access,
source counts and disabled scheduling passed on the copy. A fresh encrypted backup was created and verified before a unique synthetic saved
filter was written. A dedicated manual-start virtual-account Windows service successfully restarted with a new PID and retained the filter.
A second verified encrypted backup restored through the supported CLI into a separate clean directory; authenticated restored API access passed.
Datasets, all 332,348 records, 3 Account Review events, 1,086 SoD events, 1,023 evidence snapshots, 5 refresh reports, saved filter and every stored
document matched exactly. Portable restore intentionally cleared four absolute source paths, made source modes static and rebound only lifecycle
source paths; other settings matched and scheduling remained disabled. The owned synthetic filter was then removed through optimistic-concurrency
APIs from both disposable copies; protective/post-write archives and private evidence remain retained.

The original running Server installation/data and protected V1 originals remain unchanged. Version and CI configuration are unchanged; no installer
rebuild, full regression, push or merge occurred. This does not authorize deployment or establish production readiness. Installer upgrade/binary
rollback, interruption/power-loss recovery, cross-device TLS trust/renewal, external source review, approved-period/remediation workflows and
schema-1 fingerprint compatibility remain separate gates. The disposable service is stopped with Manual startup, and the clean-restore host is
stopped; their private data/backups and service registration are retained. Final original-table/document fingerprints and protected archive/key
hashes match the baseline, and the original `AuthLens` service remains Running with its original PID.

### Responsive navigation and layout continuation

The development frontend now uses an accessible full-label navigation drawer below 1024 px, preserving route groups/permissions and desktop
navigation. Shared Dialog supplies background isolation/scroll lock, keyboard trapping/restoration and Escape; drawer presentation adds outside
dismissal and reduced-motion-aware sliding. Route selection/history and desktop resize close the drawer. Header utilities remain available as
labelled drawer actions. A named, tooltip-equipped profile icon opens the bounded shared Popover and existing profile/session dialog and logout.
Below 768 px Settings uses a full-text section selector; toolbars/actions wrap and readable complex tables retain internal horizontal scrolling.
See [navigation contracts](../architecture/NAVIGATION.md) and [component APIs](../architecture/COMPONENTS.md).

Development build/type checks passed. Scoped ESLint has no errors and five existing Settings hook warnings. Focused browser validation passed
**52/52** across responsive navigation/profile, existing navigation/accessibility, Settings and reviewer identity, plus **24/24** direct dependent
source/record navigation and shared component/dialog tests. These are selected files, not the full browser suite. Edge was used through
`PLAYWRIGHT_EXECUTABLE_PATH` because the managed Chromium executable is unavailable. Synthetic sources and isolated browser-host storage were used;
no migrated business records were used for write tests. Screenshots and JSON results are under ignored `build/test-artifacts/responsive-ui` and
`build/test-artifacts/responsive-*.json`. The viewport set is 360, 375, 390, 768, 800, 1024, 1280, 1440 and 1600 px in light/dark, covering Dashboard,
Role Lookup, User Access, comparison, Account Review, Release Roles, SoD overview/matrices/reviews/periods and Health & Diagnostics.

Visual review identified an early Dashboard screenshot captured during loading; the test now waits for Review Progress and completed initial load,
and asserts the actual active SoD route. It also caught a low-contrast hamburger in light mode: the trigger now shares the header's foreground,
hover and focus tokens, with an explicit color-parity regression check. The final responsive spec passed **13/13** after that correction, including
all nine widths in both themes and regenerated loaded-content screenshots (36 images retained). The 76 selected unique browser cases have passing
focused coverage; reruns are not counted as additional unique tests. Complex matrices remain horizontally scrollable on phones; this is
intentional preservation of complete evidence, not a claim of phone-equivalent matrix editing. Access-package dialog flows, every Settings form,
all business-action dialogs and every possible long-data combination have not received a complete mobile acceptance pass. No production readiness
or deployment is claimed.

## Windows Server functional acceptance

This section retains the initial installed-build checkpoint. The isolated continuation above closes its compatibility and controlled-write gates
on disposable corrected copies only; the installed Server has not been upgraded.

2026-11-20, installed **4b20cdb**, repository starting at **9b85ac6**, AuthLens **2.0.0-alpha.1**: every independent requested read area was
attempted against the authenticated Server and its migrated database. The operator's sign-in and the agent's rendered dashboard observation
close the previous browser sign-in gate. **Overall functional acceptance: FAIL on one demonstrated compatibility defect; controlled writes
BLOCKED by the read-only gate. Not production-ready.** Product code and the installation were not changed.

| Feature | Result and scope |
| --- | --- |
| Dashboard/navigation | PASS: signed-in dashboard and navigation render populated source, review, directory and SoD metrics |
| Role Lookup/User Access | PASS: 96-role catalogue, no-match search and reset, role detail, 265-user listing and actual user detail |
| User comparison | PASS: two distinct users render comparison; roles/transactions and transaction evidence API return 200; same-user request is correctly refused |
| Employee Directory/account mapping | PASS: source UI shows 1,767 records; status/match routes work; 257 of 265 identities match (6 missing emails, 2 unmatched) |
| Saved filters | PASS for read/empty state (0 migrated); create/update/delete and restart persistence NOT TESTED |
| Access packages | PASS for pure preview and CSV response: one actual catalogue role yields one valid export row; no package/business record is stored |
| Account Review/history | PASS for real listing/history access and retained events; FAIL for unchanged V1 schema-2 compatibility in the synthetic reproduction below |
| SoD periods/decisions/risks/evidence | PASS for overview, both matrices, explorer, risk-review list, queue, migrated period details/UI snapshot, and sampled activity/assignment history/evidence APIs |
| Data Health/data sources | PASS for four-source health/status and diagnostics; warnings remain source limitations to investigate, not evidence of migration loss |
| Settings/configuration | PASS for read access, reload-stable revision/content and disabled scheduling; no Apply/refresh/reset was invoked |
| Controlled writes/extra backup/restart | BLOCKED: no phase-3 backup, synthetic saved-filter write or service restart was attempted after the compatibility failure |

Count consistency: Dashboard 413 release roles is an all-validity count; the default current-validity list has 407 and `status=all` returns 413.
Dashboard 6,847 pending SoD reviews equals queue Pending 6,696 + Investigate 148 + Outdated 3; the full 7,881-item queue also includes reviewed,
removal, resolved and historical items. Role source rows, distinct catalogue roles and distinct role/T-code pairs have different units. Data Health
reports 5,886 assignments without a catalogue mapping and 9 unparsed release-role names; all original observations remain retained. No unexplained
dashboard/detail count inconsistency was established. Two guessed legacy route probes returned 501; the actual UI routes returned 200, so those
probes are not product failures. Initial comparison/period selector mistakes were corrected against observed controls, without weakening checks.

### Confirmed defect: V1 Account Review evidence serialization

**Severity: Medium (P2), migration compatibility.** Reproduction: construct a synthetic unchanged SAP identity/account and a saved schema-2
`No action required` decision with the evidence fingerprint computed as V1 did; call `V1AccountReview.Rows` on the same evidence with no
invalidation. Expected: `stale=false`, decision remains applicable. Actual: `stale=true`, reopening the review. The isolated executable reproduced
this against the current API project without starting a host or touching the service database. Root cause: the exact original backup source commit
`b1fd924a6610` uses `json.dumps(..., sort_keys=True, ensure_ascii=False)` with default spaced separators for identity/outer hashes and default ASCII
escaping for nested canonical evidence strings. Current .NET uses compact `CanonicalJson` for those layers. The bytes and hashes differ even when
the evidence does not. Existing focused `AccountReviewTests` still pass **3/3**; their scope does not cover this V1 hash compatibility.

Impact: unnecessary Outdated/Needs review status and loss of derived completion across otherwise unchanged evidence; no decision/evidence history
loss and no authorization grant were observed. Proposed correction: schema-aware comparison supporting V1 and existing .NET encodings without
rewriting immutable history, preserving absence/invalidation behavior, with explicit unchanged, changed, Unicode and schema-1 tests. No fix or
replacement package was deployed during acceptance. The separate [Account Review guide](../features/ACCOUNT_REVIEW.md) records the limitation.

**Superseded oracle finding:** this initial phase incorrectly classified the three actual decisions as stale using transaction lists truncated by
the detail API. The exact full-observation V1 oracle now proves all three current; see the isolated continuation above. All three decisions remain
accessible, each with zero earlier events as in the source. No reviewer was asked to re-save them. Archived Git source was inspected read-only;
no legacy installation was changed.

Safety evidence: before/after fingerprints matched for all eight audited tables (38 datasets, 332,348 records, 3 review events, 1,086 SoD events,
1,023 evidence snapshots, settings, 0 saved filters, 5 refresh reports) and **every stored document**. Service remains Running as `NT SERVICE\AuthLens`;
original archive/key hashes remain equal, and scheduling remains disabled. Private fingerprints and the synthetic reproduction are retained outside
tracked files; no credentials, keys or business-record exports were committed. Only focused Account Review tests and the in-memory reproduction
ran; no full .NET/Playwright suite, service restart, installer rebuild, upgrade confirmation, push or merge occurred.

The isolated continuation above subsequently completed the compatibility/read-only gate, fresh encrypted backups, a synthetic saved filter,
service restart and clean-directory restore. Approved-period history is NOT TESTED (the sole migrated period is In review);
remediation-action, approval/rejection and new-history workflows remain untested. Destructive restore over existing data, interruption/power-loss, binary rollback,
other-client TLS trust, certificate renewal, source-path review and production cutover are separate acceptance gates.

## Windows V1 migration into the installed Server

2026-11-20: the existing verified **4b20cdb** win-x64 release (17 artifacts) and matching Server Setup were used without rebuilding. Initial
inspection found no `AuthLens` service, Server installer registration or canonical Server data directory. A new private acceptance root received
copied V1 inputs, a new AuthLens backup key, a new TLS certificate and explicit deployment configuration. No Desktop or legacy installation was
changed. The protected original archive and recovery key remained byte-identical by SHA-256.

The supported `--migrate-v1 preview → run → activate` path authenticated all 1,209 members, reported zero blockers, and imported **332,348 records
across 38 revisions**. Independent post-service-restart comparison matched every record, all eight source documents and the 24 original settings
fields except the deliberate scheduling isolation. Counts: 112,400 user/assignment records, 182,846 role records, 36,550 directory records and 552
SoD matrix records; 1,086 SoD events, 1,023 evidence snapshots, three Account Review events and four SoD report-log entries. SQLite integrity,
foreign keys and both event chains passed. All six known schema migrations are applied, with none pending. The encrypted migration backup and
activation audit remain retained; no upgrade confirmation or irreversible cleanup was performed.

Before installation, an isolated no-worker console host applied activation and provisioned a new administrator using the standard one-time
activation and account-login APIs. A request missing its same-origin signal was correctly refused with 403; supplying the required Origin fixed
the acceptance client without changing product safeguards. Scheduled refresh was disabled through the revision-checked configuration API before
the service started. Original external paths remain for explicit operator review; no automatic source refresh was enabled.

**Native Server installation and restart verified:** the Server installer ran with normal UAC elevation and explicit `/CONFIGFILE`, exited **0**,
and created `AuthLens` as `NT SERVICE\AuthLens`. It is **Running**, startup **Auto**, and passed the packaged NTFS ACL audit. A supported graceful
service restart changed its PID and retained migrated data and authentication. Independent HTTPS checks used normal certificate validation and
no proxy: health **200**, anonymous dashboard **401**, wrong password **401**, administrator login/dashboard **200**, and frontend HTML **200**.
The service created and fully verified a new encrypted SLBAK3 application backup, proving access to its private data and backup key.

**Frontend sign-in verification pending:** the real browser renders the Server sign-in page over trusted HTTPS; observation of the signed-in
migrated dashboard awaits the operator's sign-in handoff, so end-to-end Server acceptance is not yet claimed complete. New administrator
credentials are held only in private operator escrow outside Git. The new acceptance certificate is trusted in the current user's store only;
no machine-wide trust or firewall rule was added. It expires **2027-02-18**. A new private AuthLens recovery copy was exported and verified without
printing key material; separate/offline custody remains an operator requirement. Other-client certificate trust, reviewed source paths, renewal
and detailed business workflows remain operator requirements. Product code, version and CI are unchanged;
no rebuild, full regression, push or merge was performed. This supersedes the earlier statement that no Server migration had been exercised,
without certifying production deployment or cross-device access.

## Isolated Windows V1 backup migration acceptance

2026-11-20, installed AuthLens **2.0.0-alpha.1**, clean build **4b20cdb**, Windows PowerShell 5.1: **PASS for actual isolated migration,
basic Desktop UI accessibility and restart persistence**. No product code changed. This result does not certify production or Server migration.

The real input was a copied SAP Lens 1 **1.0.0-beta.2+local.b1fd924a6610** Desktop backup: SLBAK2, AES-256-GCM, HKDF-SHA256 host-key mode.
Its recovery key authenticated it; all **1,209 members** passed manifest validation. Preview had **0 blockers**, with **3 files preserved only in
the encrypted migration backup**. Normal Desktop upload intentionally refuses this format; the packaged `--migrate-v1` path was used instead.
The installed Desktop and migration executables matched their release manifest hashes.

Source versus restored, including independent post-restart read-only comparison:

| Data | Source / restored |
| --- | --- |
| User/assignment revisions and records | 13 / 13 revisions; 112,400 / 112,400 records |
| Role revisions and records | 3 / 3 revisions; 182,846 / 182,846 records |
| SoD matrix revisions and records | 1 / 1 revision; 552 / 552 records |
| Directory revisions and records | 21 / 21 revisions; 36,550 / 36,550 records |
| Settings and source documents | 24 fields matched before isolation; 8 documents matched at activation |
| Account Review | 3 / 3 decisions/events; full event contents and chain verified; no unmatched decisions |
| SoD | 1,086 / 1,086 immutable events; 1,023 evidence snapshots; 4 / 4 report-log entries |
| Review periods | 1 / 1, state `In review`; document content preserved |
| Saved filters / remediation actions / Server accounts | Absent in source; not positive acceptance coverage |

The migration backup was encrypted and recorded; activation audit status was `activated`. SQLite integrity and foreign keys passed; all **6**
known migrations were applied with **0** pending/unknown migrations. All **332,348 records** matched field by field. Desktop self-check passed
before UI use and after restart; the real WebView2 dashboard rendered restored data and directory matching. UI reads changed only assignment
lifecycle's source marker/seal; all **539** items, baseline and revision stayed equal, the marker matched active dataset hashes, and its seal
verified. Both review hash chains and Account Review contents verified after restart. The dashboard showed three retained account reviews as
outdated; parity with the old application's derived review status remains unverified.

Safety: a fresh protected-ACL acceptance root held copied inputs, private reports, candidate and destination key. Scheduling was enabled in the
source with four external source paths: the isolated console activation used `--no-worker`, then the normal configuration API disabled scheduling
only in that copy before Desktop use. No existing service or Desktop data was changed. Protected originals remained byte-identical by SHA-256;
no key/decrypted records were printed or committed. Acceptance processes were stopped; private data and recovery evidence were retained outside Git.

Focused `V1DataMigrationTests` and `BackupCryptoTests`: **20 passed**, no full .NET or Playwright suite. Detailed SoD UI navigation was unverified
because the computer-use approval timed out; no workaround was used. Approved-period behavior, absent data categories, service identities/ACLs,
Server accounts/TLS, interruption/power-loss recovery and production cutover remain separate gates. See the updated
[Desktop rehearsal procedure](V1_MIGRATION.md#desktop-compatibility-and-isolated-rehearsal). Release recommendation remains **NOT READY**.

## Installer callback isolation (after e16b9d3)

Operator-reported Windows release evidence: **477/477 .NET tests**, **17 verified artifacts**, both Inno installers compiled, and no secret
findings. Desktop then displayed the Server-only `/CONFIGFILE` refusal during Preparing to Install. Those release results are reported evidence,
not reruns here. Version remains **2.0.0-alpha.1**; release recommendation remains **NOT READY**.

The shared Pascal include previously contained both Server preparation and mode-specific transaction arguments behind `InstallerMode`
conditionals. Both entry scripts now include physically separate Desktop/Server callbacks before shared events. Desktop contains no Server
configuration refusal or protected-root provisioning; Server retains the exact explicit-configuration refusal and provisioning commands.
The shared immutable-payload guard and transaction failure handling remain intact. Per-user Desktop data selection, Server rollback proof,
legacy SAP Lens boundaries, stash and recovery artifacts are preserved. No version or CI change, push, merge, tag or release is authorized.

**Cause limitation:** native Inno Setup **6.7.4** preprocessing and compilation also correctly isolate the original `e16b9d3` sources.
The initial suspicion that directive indentation caused leakage is not substantiated on this compiler. Physical callback isolation removes the
shared conditional validation path, but the failing executable's provenance/compiler behavior remains unresolved without its SHA-256,
compiler version, exact build command and Setup log. Do not claim this is a reproduced runtime fix or completed native acceptance.

Focused Windows validation: `InstallerTests` **12 passed, 0 failed** (.NET SDK 10.0.404); Pester 5.9.1 on Windows PowerShell 5.1,
`InnoIsolation.Tests.ps1`, `AuthLens.Installer.Tests.ps1` and `AuthLens.Deploy.Tests.ps1`: **70 passed, 0 failed, 1 skipped** (51.89 seconds).
The skip is the opt-in real-release Desktop adapter test; no verified release was selected. Both synthetic entry scripts compiled with Inno
Setup 6.7.4 and their preprocessed code passed absence/presence checks for configuration, privileges, data, provisioning and shared guards.
Pester's unused TestRegistry plugin was disabled because the sandbox blocks its registry fixture; no application registry was selected.
Documentation links: **100 files, 0 failures**; `git diff --check` passed. Focused JSON/TRX and original preprocessing evidence are retained under
ignored `build/test-artifacts/inno-isolation`. An intermediate .NET run failed against stale tests while callback files were being moved;
the rebuilt complete affected class passed. Native compiler fixtures use synthetic payloads and do not launch Setup or produce deployable
releases. Rebuild the clean release and both installers from the final local commit, using fresh output paths, then run
isolated Desktop no-configuration/per-user/update/recovery and Server missing/invalid/valid configuration/SCM acceptance as described in
[Windows deployment](../deployment/WINDOWS_DEPLOYMENT.md#desktop-and-server-callback-isolation). Full .NET and Playwright regression are excluded
from this task. Preserve the failed installer and all existing recovery artifacts.

## Installer Pascal include correction (after fdb7e87)

Native acceptance reported .NET SDK 10.0.404, Node 24.22.3 and Windows PowerShell 5.1: solution build, all 473 .NET tests, Server/Desktop publish,
zero secret findings and 17 verified artifacts passed. Inno Setup 6 then refused Desktop compilation at line 1 of `AuthLens-Transaction.iss` with
`'BEGIN' expected`. These are operator-reported acceptance results, separate from execution on this development workstation.

Root cause: two Setup-style `;` header comments were inserted into Pascal Script because both callers already include the shared file under
`[Code]`. They are now Pascal `//` comments; no installer event, integrity gate, rollback behavior or service/data operation changed. The focused
regression failed against the original include for **both** variants and checks expanded code-section comments plus include context. A separate
fixture check distinguishes legal Setup comments from invalid Pascal headers. Native ISCC is unavailable on this workstation (PATH and the
standard machine/per-user Inno Setup 6 locations); neither corrected installer is claimed compiled. Rebuild a clean release and matching helpers
from the fixed commit, compile both variants into a fresh output directory, then continue isolated installer/SCM acceptance.

Focused local validation: the new regression failed before the comment fix (one test, reporting both callers); after the fix the complete
`InstallerTests` class passed **11, failed 0, skipped 0** using .NET SDK 10.0.204. Documentation links passed (100 files, zero failures), and
`git diff --check` passed. Original/fixed TRX evidence is preserved under ignored `build/test-artifacts/installer-include-fix`.

Release recommendation remains **NOT READY**. Browser regression remains **DEFERRED**; no full .NET/browser suite or full secret scan is rerun for
this focused correction. Product version 2.0.0-alpha.1, CI, protected installations, stash and recovery artifacts are unchanged. No push is authorized.

## Installer stabilization continuation (2026-11-20, starting 798d3d0)

**NOT READY for release.** Manual installer transactions are implemented using the existing Inno/deployment/backup approach, with focused Windows
and native isolated Desktop evidence. Inno compilation, compiled Setup rollback, elevated SCM and interactive WebView2 acceptance
remain open. The dated continuation below records the previous checkpoint; this section supersedes its installer implementation status.

Local installer commit: `fddf6f6`. The existing stash and ignored recovery artifacts remain preserved. No push, merge, tag, release or CI was
requested or performed. Product version, AuthLens identity and main-only CI policy are unchanged.

- Desktop: closed-instance check, private directories before writes, verified full package and previous executable, encrypted protective backup,
  schema-change/downgrade refusal, atomic replacement, readiness probe and verified compatible rollback. Durable checkpoints and retained recovery
  tools support explicit interrupted recovery. Custom data-directory selection persists through shortcuts and subsequent updates.
- Server: explicit configuration, secure root before extraction, immutable versioned package, existing deployment lock/journal/SCM/readiness and
  recovery engine. Installer updates require a verified compatible previous release and unchanged service account/arguments; its executable makes
  the verified backup before stopping. Packaged recovery needs no Git/SDK. No native SCM operation ran here.
- UI and CLI still share `ApplicationBackups`. A new regression round-trips the application-written synthetic v1 fixture through a portable
  AuthLens archive into fresh canonical storage, rechecking review history, SoD decisions/remediation/periods and frozen evidence. Managed CSV,
  branding and account payload coverage remains in the existing backup/legacy restore classes. No existing migration was repeated.
- The [current parity inventory](MIGRATION_MATRIX.md#release-stabilization-inventory-2026-11-20) explicitly classifies COMPLETE/PARTIAL/MISSING/BLOCKED;
  native tray/start-at-login controls remain missing, and private real-backup acceptance needs an approved copy and recovery key.

Focused evidence: installer/deployment/helper/release Pester **108 passed, 0 failed**, plus subsequently added Server delegation/recovery and native
junction cases passed separately; installer/backup/legacy/governance .NET **32 passed, 0 failed**. Native adapter acceptance using the verified
`bfa7226` package passed five stages (fresh/readiness, isolated key, update/verified backup/readiness, interrupted recovery, preserved database).
A subsequent native different-build fixture passed bfa7226-to-8d05990 atomic replacement, an injected readiness failure with verified old-binary
rollback/probe, successful update and explicit interrupted recovery (1 Pester case, 237.79 seconds). This is adapter evidence, not compiled Setup acceptance. PowerShell 5.1 parsed all 26 scripts without errors;
documentation links passed (100 Markdown files). The complete Pester checkpoint passed **193, failed 0, skipped 11** (204 discovered, zero failed containers, 362.28 seconds). Nine skips are Linux
launcher cases and two need elevated ACL restoration. A final retained-installation guard is in `7b789df`; its three focused cases passed after that
checkpoint. Two additional packaged-entry integrity tests passed. The real packaged entry point also passed a fresh private Desktop installation
with its hashed helpers, full package verification, readiness and canonical database (1 stage, 21.93 seconds).

The complete .NET checkpoint passed **473, failed 0, skipped 0** in 587.30 seconds. It includes native Windows publish/Desktop self-check;
Linux-only publish methods are platform-gated and do not establish Linux execution here. Frontend types passed; units **46/46**; lint passed
with 66 existing warnings and zero errors. Repository structure/workflow contracts, Python **7/7**, Node **5/5**, Lucide and Ruff passed.
The tracked secret scan and the new package scan found zero findings; no repeated full scan is required for these documentation updates.

**Browser checkpoint: DEFERRED.** The single attempt was interrupted by explicit instruction after its log reached case 52/865. No full summary
was produced and no complete pass/fail/skip counts are claimed. Its partial log and artifacts remain unchanged under ignored
`build/test-artifacts/installer-final-browser*`; the deferred marker is separate. No equivalent full browser run will substitute for it.
Focused checks remain the development policy; another consolidated full regression requires completed implementation and explicit approval.

The additional clean unsigned package is `AuthLens-2.0.0-alpha.1-20261120-132006-8d05990-win-x64`, source_dirty=false, **17 artifacts verified**.
It is indexed by `build/test-artifacts/installer-stabilization-release-result.json`; the earlier bfa7226 package/index was preserved. This package
predates the retained-installation Server guard in `7b789df` and later test/documentation commits. No compiled installer exists. Build a new clean
release and helper inventory from the final approved commit before compiling Setup; do not mix helper commits or edit historical manifests.

Local implementation commits after 798d3d0: `fddf6f6` (manual installer transaction), `8d05990` (portable governance recovery/parity),
`7b789df` (retained-installation rollback guard), `94f74fb` (helper integrity/native evidence). Final documentation is a subsequent local commit.
The branch remains `experiment/dotnet-backend`; all original seven unpushed commits, the stash and ignored recovery artifacts are retained.
No push, merge, tag, release, CI trigger or protected installation operation occurred.

Operator gates: provide approved Inno Setup 6; build a clean release and helper inventory at the same commit; compile into a new empty output;
then execute fresh install, same-schema different-build update, induced readiness failure and interrupted recovery in a disposable elevated VM
with an explicitly isolated service/root/data/TLS/key/port. Verify all old hashes, data, service identity and readiness after rollback, and complete
WebView2 window/download and approved real-backup restoration acceptance. Do not use protected SAP Lens services or paths. The exact recovery
commands and prerequisites are in [Windows installers](../deployment/WINDOWS_DEPLOYMENT.md#installers).

## Windows continuation: final assessment (2026-11-20)

**NOT READY.** The independent implementation and local validation work is complete. Installer-managed update/rollback remains incomplete, and critical VM acceptance needs prerequisites that are unavailable here. The dated sections below are historical evidence and do not override this assessment.

### Repository and implementation

Starting HEAD was 814c88d; the checkout safely fast-forwarded to the expected origin 50bed6d. Pre-existing edits were preserved in a retained named stash, reconciled through the AuthLens renames, and useful import-policy/test fixes retained. Six superseded untracked drafts/helpers remain byte-for-byte in ignored preservation storage with a hash manifest. No private exports, configuration, logs, keys or test artifacts were committed.

The [repository assessment](AUTHLENS_AUDIT.md#windows-continuation-assessment-2026-11-20-baseline-50bed6d) classifies the reviewed areas and the [naming register](../architecture/VERSIONING.md#naming-register) explains required compatibility identifiers. Product version 2.0.0-alpha.1, logo, colors and main-only CI policy are unchanged.

Implemented corrections:

- [Managed source files](../../backend/src/AuthLens.Application/ManagedSourceFiles.cs) retain immutable, deduplicated CSV copies for active/held datasets, reject unsafe paths and corrupted copies, and collect unreferenced generated copies under the backup lock order. [ImportService](../../backend/src/AuthLens.Application/ImportService.cs) freezes each job's import-check policy and preserves active data on invalid/empty imports.
- The existing [backup engine](../../backend/src/AuthLens.Application/Backups/ApplicationBackups.cs) includes referenced raw files with hashes and validates them before replacement. Restore rebinds managed paths locally, clears historical machine-specific source paths, retains observations, and preserves protective backup/rollback behavior. No new schema or backup engine was introduced. Imports made before managed copies cannot retroactively recover exact raw bytes; a successful reimport supplies them.
- Functional Groups and Desktop Account Review use the stable profile/authenticated actor rather than request aliases. SAP revisions exclude independent SoD changes. Export filename parsing accepts safe quoted, unquoted and UTF-8 headers; Windows workbook fixtures use fileURLToPath.
- Explicit Desktop data overrides also isolate logs, WebView2 profile and mutex; invalid/linked/earlier-product paths are refused. Native published Server coverage now executes on Windows instead of returning early. Startup deadline tests use the existing nonparallel process collection; deadlines are unchanged.
- The Server installer refuses existing service/program-file updates before changing anything because the old overwrite path provided no verified rollback. The existing versioned deployment procedure remains available; installer-managed updates are not complete or accepted.
- V1 documentation moved intact to [docs/archive/v1](../archive/v1/README.md). Required legacy backup readers, schema IDs, golden fixtures and optional reference generators remain. Unused local Python helpers were preserved outside the tracked tree, not published or destroyed. LICENSE differs only by five product-reference replacements; legal terms, ownership and attribution requirements are unchanged.

### Executed validation

Windows host: Windows 11 Enterprise build 26200, Windows PowerShell 5.1.26100.9711, .NET SDK 10.0.204, Node 25.8.0. The packaged Server reports .NET runtime 10.0.8. This workstation has no elevated token, protected SAP Lens services, or the supplied VM installation directories. It is not production-VM acceptance.

| Check | Actual result |
| --- | --- |
| Native solution and clean release builds | Passed, zero warnings/errors; frontend production/type build passed |
| Complete .NET checkpoint | 470 total: 468 passed, 2 failed. Causes: startup deadline competing with concurrent fixtures and obsolete duplicate-file expectation. Corrected complete Startup/DataSources classes: 13/13. Affected import/backup/review/Desktop/installer group: 75/75. Final native publish/portable-restore group: 22/22, including an added Windows Desktop executable case. No clean single full rerun is claimed; Linux-only publish methods remain platform-gated |
| Pester 5.9.1 on Windows PowerShell 5.1 | 182 total: 171 passed, 0 failed, 11 skipped, zero failed containers. Nine Linux-only launcher cases and two elevated native ACL restoration cases |
| PowerShell 5.1 parser | 23 active scripts, zero errors; PowerShell 7 unavailable |
| Frontend units/type/lint | 46/46 unit tests; type checks pass; full lint passes with 66 existing warnings and zero errors; changed fixtures pass scoped lint |
| Complete Windows browser checkpoint | 865 total: 862 passed, 3 failed, 0 skipped, one worker, 73.24 minutes. Failures were fixture defects: missing snapshot variables, optional-source counts dependent on retained lifecycle history, and reading confirmation metadata before the save response completed |
| Browser correction/dependent checks | Six complete specs: 45 passed, 1 failed while identifying the remaining history-dependent fixture setup. Explicit optional-source seeding then passed the complete CSV spec 8/8 and its formerly failing case 3/3 repeats. All three original failures now have passing scoped verification; no clean single full rerun is claimed |
| Packaged Desktop | Clean package self-check passed with canonical fixture database and isolated log; no window was opened |
| Packaged Server | Five isolated stages passed: ephemeral loopback startup and anonymous API rejection; synthetic data saved; encrypted online backup created/verified while running; owned console restart preserved data; fresh restore reproduced data and stable-copy SQLite inspection returned ok=true |
| Repository checks | Docs: 100 files/zero failures; Python contracts 7/7; Node contracts 5/5; structure, workflow, Ruff, Lucide and whitespace checks pass; final tracked secret scan and release secret scan: zero findings |
| Dependency audit | NuGet and production npm: zero reported vulnerable package references |
| Bash deployment harness | Syntax passed; execution refused with infrastructure exit 2 because PowerShell 7 is unavailable |
| Installer compilation | Release verification passed first, then the builder refused because Inno Setup 6/ISCC.exe was not found. No installer was built or installed |

Full-run failures, scoped corrections, TRX/XML/JSON reports, traces, logs and synthetic fixtures remain under ignored `build/test-artifacts`. Machine-readable aggregate: `authlens-windows-checkpoint-summary.json`. The first packaged-backup probe correctly refused a missing private key directory; the corrected fixture provisions protected directories before key creation and passed all five stages.

### Verified local package and Git

The clean unsigned Windows package is `AuthLens-2.0.0-alpha.1-20261120-121637-bfa7226-win-x64`, built from **bfa7226567524f72493bcdde25d691c61225deca**, source_dirty=false. All **17 artifacts** verified. Server executable: 116.9 MiB; Desktop: 169.6 MiB. No historical release manifest was edited. The local output is indexed by ignored `build/test-artifacts/authlens-native-release-result.json`; it is a verified build, not an accepted installer or published release.

Logical local commits through that package: 679897f (archive/product references), 33cdfb8 (Windows repository checks), 26ee870 (managed imports/portable restore/reviewer correctness), d9735eb (Desktop isolation/native executable coverage/installer refusal), 63fb450 (download parsing/browser fixtures), bfa7226 (validation checkpoint). Final evidence is a subsequent documentation-only commit. Origin was rechecked and remains 50bed6d. No push, merge, tag, release publication or workflow dispatch occurred; pushing still requires explicit authorization.

### Remaining gates and operator validation

1. Provide an approved Inno Setup 6 compiler. Implement and validate installer-managed updates, readiness and rollback; the current Server installer deliberately refuses in-place updates.
2. Use an elevated, disposable Windows acceptance environment for SCM registration/start/restart, service-account ACLs, privileged ACL restoration, TLS/network behavior and installer recovery. Reboot requires separate explicit authorization. Workstation tests cannot certify the production VM.
3. Complete native WebView2 window interactions/downloads and Desktop installer acceptance. Self-check and Chromium tests do not cover that integration.
4. Supply an approved copy of a real SAP Lens .NET backup and its recovery key for isolated restore/integrity acceptance. Do not copy a live main SQLite file alone, repeat an already completed v1 migration, or operate on existing services/data/keys/TLS/recovery directories.
5. PowerShell 7 is needed to execute the documented Linux fake-SSH harness and to add a separate PowerShell 7 checkpoint. Production cutover and Git push remain separately authorized actions.

Read-only checks from this checkout (the local result index exists only on this acceptance workstation):

```powershell
$package = Get-Content .\build\test-artifacts\authlens-native-release-result.json -Raw -Encoding UTF8 | ConvertFrom-Json
powershell -NoProfile -File .\backend\scripts\verify-release.ps1 -ReleasePath $package.ReleasePath
& (Join-Path $package.ReleasePath 'server\AuthLens.Api.exe') --version
Get-CimInstance Win32_Service -Filter "Name='SapLens2' OR Name='sap-lens' OR Name='SapLens' OR Name='AuthLens'" | Select-Object Name, State, StartName
```

| Working phase | Final state |
| --- | --- |
| 1 Synchronization and assessment | Completed; retained local recovery stash/drafts |
| 2 Identity, paths and database contracts | Completed; canonical AuthLens defaults and explicit legacy safeguards |
| 3 Managed imports, backup and installers | Partial: imports/backup completed; installer update/rollback remains blocked |
| 4 Functional and browser defects | Completed with full checkpoint plus passing scoped corrections |
| 5 Windows acceptance and final validation | Partial: builds, native console/Desktop self-check, synthetic recovery and local suites completed; critical external/native gates above remain open |
| 6 Documentation, local commits and assessment | Completed; no push authorized |

Four of six phases are complete; two remain partial with explicit blockers. No production service, ACL, database, certificate, key, backup, release junction or global Windows directory permission was modified.

Durable checkpoint for the next session. Evidence tags as in [README](README.md). Branch `experiment/dotnet-backend`; `work` and `main` are not
touched; CI runs only on pushes to `main` (`validate.yml`), so experiment pushes trigger nothing.

## Post-migration infrastructure checkpoint (2026-11-18)

.NET is now the default browser/dev host, active frontend version metadata uses
`backend/product-version.json` and CI definitions are .NET-first/main-only. An optional Docker deployment was added in this round and
**removed on 2026-11-18** (no supported use case; its image build was never verified). This is infrastructure stabilization, not production
certification. Pester acquisition is blocked by PowerShell Gallery access.
Native Windows service/Desktop/installers and real-data migration remain separate
acceptance gates. Consolidated local evidence is recorded below after validation.
The earlier dated tables below remain historical evidence.

## Release decision: NO-GO (not a Release Candidate), updated 2026-11-17

AuthLens (.NET, `2.0.0-alpha.1`) is **not** a Release Candidate. Functional migration is complete on Linux: **145 of 145** API routes the React UI
references are served ([ROUTE_AUDIT.md](ROUTE_AUDIT.md)), the v1 data migration passes on synthetic fixtures, and branding, deployment tooling and
installers exist. What blocks a release candidate:

1. Native Windows acceptance of the Server service, Desktop, installers and SSH deployment
   ([WINDOWS_DEPLOYMENT.md](../deployment/WINDOWS_DEPLOYMENT.md#acceptance-checklist-windows-pending)); nothing ran on Windows from this environment.
2. A v1 migration rehearsal on a copy of real (private) v1 data ([V1_MIGRATION.md](V1_MIGRATION.md)).
3. The installers are uncompiled (Inno Setup runs on Windows only) and unsigned.
4. The promotion to `backend/`, Python retirement and CI change need the gates and authorizations in [BACKEND_PROMOTION.md](BACKEND_PROMOTION.md).

The phase table and validation sections below are the checkpoint of 2026-11-16 and are kept as history.

## Repository exposure audit (2026-11-16)

Scope: all 8 refs (local and `origin`: `experiment/dotnet-backend`, `experiment/go-python`, `main`, `work`), 661 commits, every added line;
tracked files at HEAD; untracked and ignored files of the working tree. Tool: `scripts/check-secrets.py` (and `--history`) plus targeted searches.

| Finding | Severity | Where | Status |
| --- | --- | --- | --- |
| No private key, certificate with key, PFX, real token, API key, connection-string password or credential file has ever been committed | None | All refs | Two `BEGIN ... PRIVATE KEY`/`CERTIFICATE` hits are synthetic test placeholders (`b'A'*100`) and PEM-parsing code; credential-like literals are labelled synthetic test passphrases |
| The private addresses and the public host name of one test environment appeared in documentation, the test launcher defaults, a release README template and tests | Low (infrastructure detail, not a secret: private RFC 1918 addresses and a public DNS name) | Commits `0c04b52`, `848afe0`, `5be1658`, `f407dc4`, `7fc13e7`, only on `experiment/dotnet-backend` (pushed to `origin`); never on `main` or `work` | Removed from HEAD (replaced with reserved examples; launcher values now come from a git-ignored local file). Still present in those historical commits |
| Two reference tools hard-coded the build container's checkout path | Low | `backend/tools/sod_catalogue_reference.py`, `sod_fingerprints_reference.py` | Fixed (relative path, `SAP_LENS_V1_BACKEND` override) |
| `.gitignore` did not cover TLS material, secret files, SQLite databases or machine-specific configuration | Low (preventive) | `.gitignore` | Fixed; covered by `test_repository_privacy` |

No credential or certificate rotation is needed: no secret was exposed. Rewriting history to remove the environment values is **not**
recommended (they are not secrets; a rewrite would force-push a shared branch and invalidate every clone and commit reference); it would need
explicit approval. Release folders are scanned by the build scripts (`check-secrets.py --path`) before they are shared.

## Phase status

| Phase | Status | Evidence | What blocks exit |
| --- | --- | --- | --- |
| 3 Integration and stabilization | **In progress; exit criteria not met** | Route audit generated from code (no undocumented 501: every unmigrated route answers `501 not_migrated`, contract-tested); React UI verified against .NET in Chromium for sign-in, Data Sources import, Role Lookup, User Access, Compare Users [M]; Data Health findings equal Python v1 `calculations()` on the small synthetic set (11 of 11) [M]; Dashboard KPIs and distributions identical to Python v1 `overview()` on the 20 000-user set [M]; Saved Filters and Access Packages migrated with the v1 test cases ported [T]; v1 accounts, sessions and roles migrated (Accounts mode is the Server default), React activation, sign-in, User Management and viewer restrictions verified in Chromium [M]; Employee Directory on the versioned dataset pipeline [T][M]; Account Review on the hash-chained decision store with per-user attribution [T][M]; SoD source metadata and risk catalogue with Python-identical fingerprints and catalogue output [T][M]; SoD reference workbook upload and analysis findings equal to Python v1 on golden fixtures [T]; configuration export/import/reset, reviewer profile, User Access selection/export, Release Roles, diagnostics and legacy compare with Python v1 golden fixtures [T]; 300 automated tests [T]; remaining work in [MIGRATION_BACKLOG.md](MIGRATION_BACKLOG.md); release build embeds the current frontend build incrementally and tests the solution it built (build-integration tests) [T] | 68 routes not migrated (and the sub-routes listed in MIGRATION_BACKLOG.md); browser tests exist only as ad-hoc scripts in `tools/` and scratch, not a suite |
| 4 Platform and distribution | **Partial** | Reproducible release build (`scripts/build-release.sh`, `.ps1`): React build, tests, self-contained single-file Server win-x64 (`AuthLens.Api.exe` + `e_sqlite3.dll`) and linux-x64, single-file Desktop win-x64, in a versioned release folder (`server/`, `desktop/`, `symbols/`, `build-manifest.json` with every artifact's SHA-256, `README.txt`, `SHA256SUMS`, `verify-release.ps1`), build identity stamped (`+<sha>`) and verified [M on Linux; single-file layout not yet built on Windows]; Windows service and systemd hosting in code; install/upgrade commands documented | Windows release build validated natively at `ea09de2` (Windows 11 Pro, .NET SDK 10.0.404, Node.js 24.22.3): 238 tests passed, React build, Server win-x64 (117 MB) and Desktop win-x64 (151 MB) published, script exit 0 (output `C:\saplens2\builds\release-ea09de2a849c-20261116-135041`) [M on Windows]. Earlier Windows failures ("user interface is incomplete") came from the separator-sensitive, stale-prone embedded-files manifest, replaced by explicit `AuthLensUi/<path>` resources (see [UI_INTEGRATION.md](../architecture/UI_INTEGRATION.md#how-it-works)). Not yet done on Windows: Server and Desktop startup, HTTPS, application workflows (runtime acceptance); installer and upgrade/rollback scripts are documented commands, not tested tooling; Desktop installer not built |
| 5 Full regression and hardening | **Not started as a phase** | Existing suites: equivalence 68/68 small and large (domain), benchmarks, security and TLS tests, multi-process SQLite tests [T][M] | Depends on Phase 3 parity; the v1 Playwright suite cannot pass until the UI's areas are migrated |
| 6 Release Candidate and acceptance | **Not started** | Windows acceptance commands and checklists exist ([UI_INTEGRATION.md](../architecture/UI_INTEGRATION.md), [SERVER_NETWORK_ACCESS.md](../deployment/SERVER_NETWORK_ACCESS.md), [DESKTOP_SERVER_DEPLOYMENT.md](../deployment/DESKTOP_SERVER_DEPLOYMENT.md)) | No RC exists (see decision); no Windows or mobile acceptance run |

## Validation at the end of the functional migration sprint (2026-11-16)

| Check | Result |
| --- | --- |
| .NET suite (`dotnet test tests/AuthLens.Tests -c Release`) | 160/160, two consecutive full runs [T] |
| Equivalence harness vs Python v1 | 68/68 small, 68/68 large [T] |
| EF migrations (`dotnet ef migrations has-pending-model-changes`) | No pending model changes [T] |
| Frontend unit tests, `tsc --noEmit`, production build | 41/41, clean, built [T] (no frontend code changed) |
| ESLint | 0 errors, 115 existing warnings (threshold 115) [T] |
| Browser smoke in Chromium, Accounts mode | Sign-in, Dashboard, Role Lookup, User Access, Account Review, Data Sources, Employee Directory, User Management; only expected 401 before sign-in and 501 for unmigrated `diagnostics` and `functional-groups/options` [M] |
| Docs link check | 0 failures [T] |

A test-isolation defect was found and fixed in this round: the Data Sources "one load at a time" gate was process-wide static state, so two hosts in
one test process refused each other's imports (409). It is now a per-host singleton; three repeated parallel runs passed after the fix, all three failed before.

## Checkpoint: SoD governance (next task)

Done: steps 1 and 2 (optional source columns with v1 content hash; risk and activity catalogue with byte-identical definition fingerprints, metadata
lookup, reference status/reset/template). Golden fixtures in `tests/AuthLens.Tests/Fixtures/sod` are produced by `tools/sod_fingerprints_reference.py`
and `tools/sod_catalogue_reference.py` from Python v1.

Next, in order, each a validated commit:

1. Done: reference workbook upload (`SodReferenceWorkbook`, golden fixtures from `tools/sod_reference_fixtures.py`; known difference: a value
   that fails the field rules is refused with a .NET message instead of Pydantic's text). The v1 file migration is done: `AuthLens.Cli import-v1-sod --data DIR --catalogue sod-catalogue.json [--reference sod-reference.json]` validates
   against the v1 storage contract, writes both documents in one transaction and never overwrites existing .NET annotations.
2. **Scope and analysis**: `routers/sod_analysis.py` is done (golden fixtures from `tools/sod_analysis_reference.py`). Next: `sod_scope.py` with
   `context`, `filter-options` and `overview`; the React SoD workspace loads these first, so the Explorer and Overview screens can only be
   browser-checked after them (the analysis routes are verified at API level).
3. **Decisions and reviews** (`sod_decisions.py`, `sod_reviews.py`) on the hash-chained review store (subject types per v1; never rewrite).
4. **Periods** (`sod_periods.py`): frozen snapshots, transitions, approval gates; then **governance** (`sod_governance.py`, 21 routes: acceptance,
   remediation, explorer, matrices) and **reports** (`sod_reports.py`, PDF/DOCX/CSV from the frozen model).

## Remaining work, in dependency order

1. Windows acceptance checklist ([WINDOWS_DEPLOYMENT.md](../deployment/WINDOWS_DEPLOYMENT.md#acceptance-checklist-windows-pending)), including the
   AuthLens scenarios (fresh install, restore of a SAP Lens backup, earlier services untouched). The service-to-service migration
   (`SapLens2` to `sap-lens`) and its preflight were removed on 2026-11-20: SAP Lens data reaches AuthLens only through a fresh installation plus
   [restore](../deployment/WINDOWS_DEPLOYMENT.md#migrating-from-sap-lens), so the VM preflight blockers of 2026-11-19 no longer gate it.
   Restore, legacy-archive compatibility and fail-safe database handling are tested on Linux only.
2. Installer compilation and acceptance on Windows (`scripts/build-installers.ps1`); code signing as an authorized release step.
3. v1 migration rehearsal on a copy of real data.
4. Owner decision on Desktop identity (beside v1 or replacing it), then the promotion in [BACKEND_PROMOTION.md](BACKEND_PROMOTION.md).
5. Browser regression against the .NET server. Complete run on 2026-11-20 (Linux, one worker, 36 min): **836 passed, 17 failed** of 853
   (2026-11-18: 532 passed, 327 failed). The specs now set source files through Data Sources activation ([browser tests](../development/README.md#browser-tests)),
   and the run found two application defects, both fixed: `/api/access/*` ignored a disabled User–Role Mapping, and every source activation
   left Settings with phantom unsaved changes. Two of the 17 were test defects, fixed and re-run afterwards (`desktop` app information,
   `ui-polish-actions` locator). Remaining 15, classified and open:
   - **.NET behaviour differences:** `sod-integration` (a SoD-only refresh advances the SAP part of `data_revision`), `csv-lifecycle` (3:
     refresh result counts, and the Employee Directory import check holds a 48 % drop the spec expects to pass).
   - **Missing functionality:** `functional-groups-members` (confirmation attribution shows the seeding actor, not the acting reviewer).
   - **Not yet investigated:** `navigation-modules` (6: first-run data-source alert text, two focus checks, two timeouts), `sod-metadata` (timeout),
     `startup-recovery` (session-token replacement navigation count).

## Next commands

```bash
git fetch origin && git checkout experiment/dotnet-backend && git pull --ff-only
cd backend && dotnet build AuthLens.slnx -c Release && dotnet test tests/AuthLens.Tests -c Release --no-build
python -I tools/route_audit.py .. ../docs/migration/ROUTE_AUDIT.md     # regenerate parity after each step
scripts/build-release.sh /tmp/authlens-rc --skip-tests                                          # Linux; Windows: scripts\build-release.ps1 -Output C:\AuthLens-Build\builds
```

## Infrastructure stabilization evidence (2026-11-18)

Starting source: `6fa0c7f0b1b9fbeb3727cec5b9597d33469665a3` on
`experiment/dotnet-backend`. Product version remains `2.0.0-alpha.1`.

| Phase | Implementation and validation | Commit/checkpoint |
| --- | --- | --- |
| A — Playwright/dev | .NET is default; disposable Desktop-capability host, owned child cleanup, occupied ports fail closed. Python-runtime specs were removed with SAP Lens 1 (2026-11-18); two active reference-generator specs still need optional Python. No claim of complete browser parity | `2d5741f` |
| B — Versioning | Frontend manifests, generated identity and release UI metadata use `backend/product-version.json`; v1 metadata unchanged | `45579d6` |
| C — Docker (removed 2026-11-18: no supported use, image never built) | Multi-stage Node 24/.NET 10, non-root app user, persistent volume, mandatory TLS/private bind, exact-host readiness and loopback-only published port. Compose/shell/contracts pass; actual image build blocked at MCR redirected layer download (403) | `03f7e10`, **partial validation** |
| D — CI | One pinned/read-only main-push workflow, .NET Linux/Windows, frontend, focused browser, Docker; no dispatch/PR/schedule/deploy/publisher. Historical workflows archived; actionlint and trigger tests pass | `6e7b7ba` |
| E — Scripts | SDK selection, canonical paths, no-reuse browser compiler settings, fail-fast missing SDK, isolated fake deployment remote. Historical root fallback retained only for older-commit compatibility | `3f1e6c0` |
| F — Windows | Host/TLS/proxy/installer/location contracts, PowerShell syntax and fake SSH orchestration pass on Linux; exact native follow-up commands recorded. Existing service/release/data/key paths unchanged | `faea923` |
| G — Docs/verification | Current guides, agent instructions, migration gates and security checks aligned; evidence below. No merge, version bump, release or workflow execution | This checkpoint |

Validation performed:

- SDK 10.0.404 solution build: **0 warnings, 0 errors**. SDK and Linux PowerShell
  7.7.0 were downloaded into temporary storage and checked against official hashes.
- Initial focused .NET group: **23 passed, 1 failed** (outdated frontend=v1 version
  assertion). The contract now requires the canonical v2 frontend version and keeps
  the v1 resource distinct. Corrected version/startup/TLS/proxy/installer/Desktop
  group: **25 passed, 0 failed/skipped**.
- Consolidated non-publish/non-build .NET selection: **411 passed, 1 failed, 0 skipped**
  (412 total). The failure compared a November 17 golden `as_of` value with the
  November 18 live context. Initial historical-date recheck showed `/context`
  deliberately ignores `as_of`; final test explicitly asserts its current-day
  contract (including midnight boundary), while historical query comparisons use
  the fixture evaluation date. Final complete affected class: **2 passed**. No
  production SoD rule or response assertion was removed. The broad selection was
  not rerun; this is not reported as a clean single-run full regression.
- Embedded-UI incremental build contract passed in the initial focused group;
  its expensive rebuilds were reused rather than repeated in the consolidated run.
  Publish/package acceptance (`Category=Publish`) was intentionally not executed.
- Frontend typecheck and production build passed; **41 unit tests passed**. ESLint:
  **0 errors, 114 existing warnings** (threshold 115).
- Final .NET Playwright selection: **12 passed, 0 failed/skipped**, one worker,
  system Chromium (`PLAYWRIGHT_EXECUTABLE_PATH=/usr/bin/chromium`), private port
  18856. Component interactions, focus and light/dark at 375/1280px, host identity,
  unauthenticated rejection, CSV activation and Role Lookup. No complete browser
  regression was requested/executed. Owned host exited and its port was released.
- Repository tests: **5 Node tests** (version, source commit, missing SDK cleanup,
  invalid ports); **8 Python infrastructure contracts** (CI triggers/permissions,
  Docker boundaries, structure, incomplete/vulnerable advisory reports).
- PowerShell parsing: **10 scripts, 0 errors**, Linux PowerShell 7 only. Fake SSH
  deployment tests: **18/18 passed**, disposable local clones, no remote operations.
  Pester 5.7.1 acquisition failed because the managed proxy blocks PowerShell
  Gallery; Pester was **not executed**. No native PowerShell 5.1 result is claimed.
- NuGet advisory report (9 projects) and production npm audit: **0 vulnerabilities**.
  The audit parser separately rejects incomplete/error reports. Tracked secret
  scan: **0 findings**. Icon catalogue: **1,447 icons verified**. Docs: **99 Markdown
  files, 0 broken links**. Workflow YAML/contracts, actionlint, Bash syntax and
  whitespace checks passed. No runtime dependency or product version was changed; PyYAML 6.0.3 is a new development-only workflow-check dependency.
- No GitHub Actions were dispatched. API inspection showed **0 workflow runs** for
  pushed commit `45579d6`; final push verification is recorded by the delivery report.

External follow-up:

1. (Obsolete: Docker support was removed on 2026-11-18.) Allow the official MCR layer host `centralus.data.mcr.microsoft.com` in the
   managed network, then run the exact image build.
   Registry manifest access works; layer access returns 403. Image/runtime acceptance
   remains unverified, and no production container was deployed.
2. Obtain pinned Pester from an approved source and run the commands in
   [Windows verification](../deployment/WINDOWS_DEPLOYMENT.md#post-promotion-infrastructure-verification).
3. Run native Windows service/Desktop/installer, ACL/firewall and recovery checks
   on disposable data. Preserve the real installation and all release/backup/key
   directories. Rehearse real-data v1 migration separately before release approval.

Private production hosts, keys, configuration and data are not included in this
record. `main`, local historical `work`, and remote `work-v1` were preserved.
