# Public repository privacy

The application ships only generic defaults and clearly synthetic examples. Organization names, SAP identities, domains/rules, imported exports and custom logos belong in per-user application storage. Do not commit local configuration, diagnostic records or customer screenshots. Portable configuration exports may contain confidential naming rules; handle them as private files.

An audit of reachable Git objects found organization logo binaries in older commits under `frontend/public`, including the initial source history. These files have been removed from the current tree and distribution inputs. **Removing current files does not remove their historical Git objects.** Historical code also includes naming-convention assumptions; the historical classification documentation records compatibility without treating those assumptions as universal SAP rules.

No history rewrite has been performed. Repository owners should assess disclosure rights and whether historical removal is required. Any rewrite needs explicit authorization, coordination with forks/clones and fresh publication checks. No obvious credential/private-key literals were detected in the initial tracked-text review; this is not a guarantee that every historical object is non-sensitive.

The protected README product branding remains unchanged. The Windows icon and default application logo are the project’s canonical product assets; that description does not determine legal ownership or resolve employer-related rights. Custom organization logos affect only the configured local interface.

The repository cleanup rechecked 205 reachable text blobs for bounded credential/private-key signatures with no candidates, and confirmed two unique historical nonproduct image blobs. This does not supersede owner review of historical naming conventions, forks, clones or earlier asset exposure. No history was rewritten and no discovered private values are printed in the cleanup report.

User exports may contain personal data. Desktop reads them locally; server-mode browser uploads send them only to the operator’s configured SAP Lens instance for validation and import. They are not sent to a third-party cloud service or bundled into distributions. User previews are bounded and omit email fields; diagnostic exports remain redacted. Routine logs never include user identifiers or contact details. Private settings backups may retain inactive legacy configuration; handle them as confidential.


## Outgoing delivery review — 25 October 2026

The live remote baseline was `582e39a9c72e09d07aaf3da041fe9261ece14b9d`.
Through validated checkpoint `8e11ae7`, nine intentional outgoing commits changed
87 paths and introduced 103 unique new/intermediate text blobs. Intermediate
commit versions were scanned as well as the net diff. Final documentation-only
records are also reviewed before push.

Local static/manual review found no newly introduced employee identities,
credentials, private configuration, company-identifying assets or infrastructure.
All detected email domains were reserved example/test domains. All 157 novel
role literals belonged to explicit synthetic namespaces; existing public SAP
conventions were not treated as confirmed confidential information. The three
linked CSVs reproduce from their deterministic generator without reading exports,
settings or production data. Generic UNC examples and public vendor/GitHub URLs
were reviewed; no sensitive values are reproduced here.

No new binary/image blobs, tracked runtime snapshots, screenshots, test artifacts
or new Git author identities were introduced. Docker/package privacy exclusions
still reject CSVs, private settings, snapshots and secrets; the example exceptions
are restricted to their documented source files. Existing third-party notices
remain required. The product license and accepted historical branding are not
rewritten or reinterpreted by this review.

No blocking new privacy finding was identified. P-01 remains the separately
accepted, unresolved historical-branding issue; no history rewrite, asset removal
or legal ownership determination was performed. This is a scoped local review
using signatures, generated-data verification, repository tests and manual source
inspection, not a hosted vulnerability scan or a guarantee about ownership or
every possible historical exposure.
