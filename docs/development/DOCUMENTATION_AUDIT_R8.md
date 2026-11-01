# Documentation audit (R8)

Method: link and anchor validation (`python scripts/check-docs.py`, 0 failures before and after), extraction and checking of every documented command
(136 `python`, `node` and `npm run` references: each script and npm script exists), comparison of every documented `SAP_LENS_*` variable with the
code and deployment files, and a read of the feature and configuration guides against the R6 to R8 behavior.

| Finding | Type | Action |
|---|---|---|
| The SoD guide said the heatmap choice is a per-browser local-storage preference that holds across reloads | Outdated (changed in R7) | Corrected: session-scoped, expanded again in a new session |
| `CONFIGURATION.md` listed three data sources and did not mention the SoD import format key | Outdated | Four sources named; `sod_import` explained |
| `UI_UX_GAP_AUDIT.md` was a dated verification record kept among the current development guides | Superseded | Moved to `archive/validation/` with a banner; every link updated |
| `SAP_LENS_PUBLISH_ADDRESS` and `SAP_LENS_PUBLISH_PORT` (compose) were undocumented | Missing configuration | Added to the Linux Docker guide |
| Six build-time variables (`SAP_LENS_FRONTEND_STAGE`, `_BUILD_INFO`, `_BUILD_CA`, `_BUILD_PROXY_HOST`, `_AUDIT_PYTHON`, `_EXPECTED_BUILD_JSON`) were undocumented | Missing configuration | Table added to the build guide |
| No troubleshooting page for end users | Missing guidance | `getting-started/TROUBLESHOOTING.md` added from the application's real messages; linked from the index and the quick start |
| No record of the review results | Missing security documentation | `SECURITY_REVIEW_R8.md` and `CODE_REVIEW_R8.md` added and linked from the security architecture and the development index |
| Optional SoD descriptive metadata, pill descriptions, coverage and the new endpoints | New behavior | Added to the SoD matrix, SoD feature and API guides |
| Handoff page had no R7 or R8 sections | Incomplete | Sections added |

Checked and found current: the deployment guides for Windows desktop, Windows service, Linux native and Docker (install, upgrade, backup, restore),
the CSV and import guides, and the architecture overview. No duplicate guides were found: the two security documents are deliberately split (architecture
versus deployment configuration) and cross-linked. No obsolete screenshot references exist (image links are validated by `check-docs.py`). There is no
CHANGELOG, by decision.

Not verifiable here: the Windows and systemd procedures were read, not executed; external URLs are not fetched by the checker.
