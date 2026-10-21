# Domains and classification: functional review

## Recommendation: SIMPLIFY

Retain the classification engine, saved profiles and business domains; simplify
their presentation and explain the currently selected method before exposing
advanced rules. SAP Modules is an appearance/catalog/filter configuration,
whereas classification assigns area/domain labels to roles. They are not two
implementations of the same responsibility. A valid module column makes custom
classification optional, but does not make normalization, conflict handling,
child-label compatibility or optional customer domains redundant.

This assessment precedes UI implementation. It authorizes no deletion, automatic
profile switching, schema migration, rule rewrite or removal of saved settings.
The UI task preserves the separately completed CI commit
`3bb960d766828b6c208992a3ad4f724d8154c59b` and changes no workflow or packaging code.

## Trace from CSV to consumers

1. `backend/csv_import.py` maps CSV headers through the active ImportProfile.
   AGR_NAME is required; FUNCTION_KEY is optional and means the source SAP area.
   Mapping changes column names, not classification values. Row validation,
   deduplication and explicit child/parent/effective-role/transaction provenance
   happen before classification.
2. `backend/cache.py:build_cache` groups records by composite AGR_NAME, preserving
   all distinct source module values and relationships. `Classifier` receives
   the role name, first source area and description. Multiple distinct normalized
   source areas mark the composite ambiguous; Generic also makes it UNCLASSIFIED.
3. `backend/classification.py` resolves recognized areas using the stable registry
   and aliases from `backend/module_registry.py`. Generic returns that evidence.
   Legacy additionally preserves unknown composite source values; its separate
   child-label helper reads recognized description prefixes or the second
   colon-separated child-name segment. Generic has no child-area column to read
   and does not inherit a composite's area into its children.
4. Custom checks an exact role override first, then name rules (prefix, exact,
   contains or bounded regex). Lowest numeric priority wins. Equal-priority
   winners targeting different domains produce ambiguity. If nothing matches,
   its optional fallback domain applies. A chosen domain supplies its mapped
   SAP area; no area mapping means UNCLASSIFIED, even if the CSV supplied FI.
   A fallback can therefore override valid CSV evidence too. Rules do not infer
   areas from T-codes; the classifier's description argument is not a general
   rule input. Legacy's child helper is the separate description-based path.
5. `module_definition` attaches catalog name/icon/color/enabled overrides. It does
   not evaluate role rules or change role membership. Cache publication is atomic:
   only a complete valid new generation replaces the previous one.
6. `backend/models.py` exposes function_key/module_name, domain_id, ambiguity,
   source_modules and profile/import fingerprints. Child roles expose area/name
   labels. Transaction/relationship sets are built independently of these labels.

Every application consumer found by tracing classification fields and registry
lookups (tests are additional consumers of the contracts):

| Consumer | Effect |
| --- | --- |
| `backend/routers/roles.py`, frontend API client and RoleList | SAP-area filtering, module-name text search, area counts/grouping; client-side domain filtering and domain counts |
| `backend/routers/modules.py`, `useModules` | Distinct observed area names/colors/enabled states for the role browser |
| `ModuleRegistry.tsx`, `ModuleIcon.tsx`, RoleCard | Registry visuals, active-profile domain labels, area/domain and ambiguity display |
| `RoleDetailPanel.tsx` | Composite/child area labels, customer domain, ambiguity, source/profile/import provenance |
| `backend/routers/comparison.py`, `ComparisonView.tsx` | Composite/child area labels and icons; mathematical intersections/exclusivity use role/T-code sets, not classification |
| `backend/configuration_routes.py`, SettingsView | Active profile selection, validation, dataset/name preview, proposed changes and conflict counts |
| `backend/cache.py` import report, main metadata/configuration responses | Profile ID/version/fingerprint, import profile and configuration revision identify the analysis generation |
| `backend/diagnostics.py`, frontend Diagnostics | Analysis-generation/import diagnostics; not a second classification algorithm |
| `backend/config.py`, `portable_config.py` | Persist and restore profiles, selected profile and module overrides; no role inference during export |

There is no separate authorization policy based on the area/domain, and no rule
changes SAP transaction assignments or role hierarchy. Label changes can still
change filters, search results, counts and comparison presentation, so they are
behavioral changes that must not be applied silently.

## Responsibilities and overlap

| Concept | Owns | Does not own |
| --- | --- | --- |
| SAP Modules / area registry | Stable area IDs, aliases, names, categories, parent metadata, icons, colors and filter visibility | Role-name rules or customer-domain definitions |
| Domains & Classification | Selection/preview/editing of the classification method | A second SAP catalog or CSV parser |
| Classification profile | Versioned Generic, Legacy or Custom assignment behavior | CSV delimiter/header mapping |
| Custom rules/domains | Optional customer taxonomy, overrides and area mapping based on role names | Relationships, T-codes, permissions or a universal SAP naming convention |
| SAP area detection/mapping | Normalization/alias resolution of explicit CSV values; Legacy child hints; optional custom mappings | Transaction-based inference or automatic correction of contradictory CSV evidence |
| Import profile | Encoding, delimiter and CSV column mapping | Classification-rule priority or area presentation |

There is real coupling worth documenting: each custom domain has one optional
area mapping, so assigning a domain can replace an otherwise valid source area.
An organization-wide domain spanning several SAP areas cannot currently just
add a label while always preserving source areas. Decoupling those assignments
could be useful later, but would change saved-rule semantics and needs an
explicit versioned design, not an incidental UI refactor.

The module filter checkbox is not independent from its Enabled/Disabled status:
both use ModuleOverride.enabled. Disabled areas are omitted as available filter
choices and rendered as disabled visuals; their roles/transactions remain in
the dataset and other searches/comparisons. Introduce no second boolean. Explain
the existing control as filter availability, with the status reflecting the
same saved value and the editor showing an unsaved preview separately.

## Executed synthetic examples

Executed against the actual `build_cache`, not a hand-written model. Six CSV rows
contain five composites. Custom defines finance→FI, buying→MM and technical→BC;
prefix rules cover Z_DEMO_PAY, Z_DEMO_BUY and standard synthetic child prefixes,
an exact rule covers Z_DEMO_LOCAL, and an override covers Z_DEMO_BASIS. No fallback
domain is configured in this example.

| Composite / CSV FUNCTION_KEY | Generic | Legacy | Custom |
| --- | --- | --- | --- |
| Z_DEMO_PAYABLES / FI | FI, no domain | FI, no domain | FI / finance |
| Z_DEMO_BUYER / FI | FI, no domain | FI, no domain | MM / buying: rule deliberately overrides CSV FI |
| Z_DEMO_LOCAL / LOCAL_FIN | UNCLASSIFIED | LOCAL_FIN preserved | FI / finance from exact rule |
| Z_DEMO_BASIS / empty | UNCLASSIFIED | UNCLASSIFIED | BC / technical from exact override |
| Z_DEMO_MIXED / MM and FI on separate rows | UNCLASSIFIED, ambiguous | MM (first source), ambiguous | MM, ambiguous; no matching custom composite rule |

Child Z:FI:AP_POST is UNCLASSIFIED in Generic, FI in Legacy (recognized name/text
hint), and FI in Custom (explicit child-name rule). Z:MM:PURCH similarly becomes
UNCLASSIFIED/MM/MM. A child does not acquire the composite's CSV module merely
because its parent has one. All three complete imports retain exactly five
unique transactions, six assignments and six relationships.

For a reliable CSV area column, Generic usually provides sufficient composite
classification; an ordinary user need not author rules. Recognized aliases such
as Finance normalize to FI in every profile before optional custom overrides.
Unknown/local area values, incomplete child evidence, business-domain labels and
conflicting multi-row values are reasons not to remove the engine or silently
replace every saved profile with Generic.

## Persistence, compatibility and preview limitations

Schema 2 stores profiles, active ID and module overrides in per-user settings
(Windows: %LOCALAPPDATA%/SAP Lens), outside Git and the EXE. Configuration apply
validates IDs/targets, checks the revision, increments profile versions when
content changes and rebuilds the cache before committing settings. Failures
retain the previous settings/data. Existing file-only settings migration creates
compatibility defaults and keeps a local backup. No classification migration is
needed merely to change explanatory UI.

Private configuration export includes profiles/rules when explicitly requested;
the default sanitized export intentionally uses default profiles and only carries
theme settings. Imports restore the exported profile selection and rebuild using
the locally retained data path. Do not silently alter this privacy boundary.

The baseline name-only preview supplies no source area, so Generic reports
UNCLASSIFIED even when an imported role has FI evidence. Its dataset preview also
retains only the first source value and misses the loader's multi-source conflict
policy. Those are preview fidelity problems, not reasons to delete classification.
Safe improvements are to expose/use explicit CSV evidence, distinguish overrides,
rules, fallbacks and no-match, and mirror the existing conflict policy without
changing the production classifier. Preview remains read-only and must not alter
configuration revision, active generation, relationships or transactions.

## Options assessment

**A — KEEP separate:** Preserves all behavior and existing saved configurations
without migration; CSV import and classification accuracy remain unchanged.
Implementation complexity and regression risk are low. However, the current UX
still exposes advanced concepts early, misleading preview results need repair,
and users may mistake the catalog for another classification engine. Maintenance
retains current terminology/coupling. No data loss, but limited usability benefit.

**B — MERGE:** A shared SAP Modules navigation entry with Appearance and Advanced
Classification subsections could improve discovery without changing storage or
accuracy. A UI-only merge has moderate layout/navigation/test cost and can retain
old settings unchanged. Merging the actual configuration/models is much harder:
domain rules and overrides cannot be represented by per-area appearance settings.
Existing profiles/versions, CSV behavior and rule precedence need migration and
equivalence tests. Collapsing them into static assignments risks losing rules on
future imports. Maintenance might improve navigation but not eliminate either
functional layer. Not justified as a destructive change in this task.

**C — SIMPLIFY (recommended):** Show the current saved method, explain CSV area
evidence, provide a meaningful read-only preview and disclose technical/rule
controls only when needed. Preserve every profile, active selection, CSV mapping,
override and migration unchanged. This has low technical complexity and low data
loss/regression risk, while improving the normal UX. Accurate preview improves
confidence without changing production classification. Maintenance retains one
engine and one catalog; advanced features remain discoverable. Automatic profile
selection is not safe for existing settings because it can change unknown source
values and child labels. Recommend Generic for suitable CSVs; do not auto-switch.

**D — REMOVE:** Would simplify menus and reduce rule-editor maintenance, but is
safe only if no required custom taxonomy, unknown/local mapping or Legacy child
behavior exists. The repository's actual consumers and executed examples show
otherwise. Existing saved profiles/domain filters/provenance would lose meaning,
CSV interpretations would change, and classification accuracy could regress.
Retaining source normalization/conflict handling would still require logic.
Migration complexity and data-loss/behavioral risk are high. Lack of production
usage telemetry is not evidence that saved rules are unused. Reject removal.

## Migration strategy before any future destructive change

This task performs no destructive migration. A later merge/automatic mode or
domain/area decoupling must first specify a new versioned schema and opt-in
behavior. Preserve old profiles and exact IDs, priority, case sensitivity,
overrides/fallbacks, active selection and unknown-source compatibility. Back up
local settings; private exports remain local and opt-in. Load old settings with
the old semantics until an explicit preview and successful apply. Never convert
rules into a one-time snapshot of today's CSV.

Demonstrate equivalence for all synthetic cases above, conflicts, custom domains
without area mappings and fallback overrides; verify role/assignment/relationship
sets, displayed labels, filter counts and version/fingerprint provenance. Only
publish the new settings and generation atomically after validation. Keep rollback
to the original saved profiles. Removal requires explicit evidence and approval
that affected saved behavior is no longer needed; it is not implied by this review.
