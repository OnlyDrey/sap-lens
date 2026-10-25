# Public repository privacy

The application ships only generic defaults and clearly synthetic examples. Organization names, SAP identities, domains/rules, imported exports and custom logos belong in per-user application storage. Do not commit local configuration, diagnostic records or customer screenshots. Portable configuration exports may contain confidential naming rules; handle them as private files.

An audit of reachable Git objects found organization logo binaries in older commits under `frontend/public`, including the initial source history. These files have been removed from the current tree and distribution inputs. **Removing current files does not remove their historical Git objects.** Historical code also includes naming-convention assumptions; the historical classification documentation records compatibility without treating those assumptions as universal SAP rules.

No history rewrite has been performed. Repository owners should assess disclosure rights and whether historical removal is required. Any rewrite needs explicit authorization, coordination with forks/clones and fresh publication checks. No obvious credential/private-key literals were detected in the initial tracked-text review; this is not a guarantee that every historical object is non-sensitive.

The protected README product branding remains unchanged. The Windows icon and default application logo are the project’s canonical product assets; that description does not determine legal ownership or resolve employer-related rights. Custom organization logos affect only the configured local interface.

The repository cleanup rechecked 205 reachable text blobs for bounded credential/private-key signatures with no candidates, and confirmed two unique historical nonproduct image blobs. This does not supersede owner review of historical naming conventions, forks, clones or earlier asset exposure. No history was rewritten and no discovered private values are printed in the cleanup report.

User exports may contain personal data. Desktop reads them locally; server-mode browser uploads send them only to the operator’s configured SAP Lens instance for validation and import. They are not sent to a third-party cloud service or bundled into distributions. User previews are bounded and omit email fields; diagnostic exports remain redacted. Routine logs never include user identifiers or contact details. Private settings backups may retain inactive legacy configuration; handle them as confidential.
