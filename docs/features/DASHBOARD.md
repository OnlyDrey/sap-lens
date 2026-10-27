# Dashboard and shared notifications

Dashboard is the default landing page, available from the main navigation and at
`#/dashboard`. Explicit `#/role-lookup`, `#/user-access` and `#/release-roles` routes
still work, and an existing detail history entry remains meaningful. No historical trends are inferred
from a single import. Data stays on the configured SAP Lens instance; desktop defaults to loopback.

## Startup, refresh and navigation

Configured SAP sources initialize in the backend lifespan, independently of which
page opens. The [CSV lifecycle](../data/IMPORT_AND_REFRESH.md) validates independent source
candidates and publishes one coherent generation after committing references. Failed
sources retain validated observations; retained users are remapped if the catalogue changes.

`ApplicationDataProvider` observes configuration above the page routes. It polls
at 500 ms during a load and 3 seconds otherwise. Configuration's `data_revision`
is the published snapshot's timestamp (or `empty`), not CSV contents or a path.
On initial readiness or a changed publication, the provider cancels obsolete
query results and invalidates dataset queries across all routes, including inactive
cached pages. Active queries refetch; inactive pages refetch when used. Backend
publication remains atomic; requests can finish at different times, so a shared
updating indicator remains visible while active views synchronize. Previously
accepted data is retained while loading and after a rejected replacement. Initial
empty/not-found states wait for startup completion. Service loss offers retry
without restarting navigation or discarding the last accepted view.

Previously, refresh state and role/module invalidation lived in page components.
Dashboard, user and release results could remain cached after startup completion;
a delayed response could repopulate an obsolete route cache. Browser regressions
cover that failure, navigation during refresh, stale responses, recovery and restored
detail history. Backend regressions verify atomic two-source publication.

## Overview layout

The compact Dashboard presents **SAP Overview**, **Access & Risk**,
**Directory & Data Health**, **Review Progress**, **Role Distribution**,
**Assignment Distribution**, then **Data Sources & Configuration**. Source setup
buttons open the correct Data Sources tab. Smaller icon/value tiles replace the twelve equal, descriptive cards; metrics
have explanatory accessible text/tooltips and no fabricated historical trends.
The default Dashboard does not mount Role Lookup or download its catalogue until
that investigation is visited. Profile/filter layouts use four/two/one-column
breakpoints at 1100 and 640 pixels; the profile itself uses three/two/one groups.

## Metrics and data boundaries

`GET /api/dashboard` returns aggregate metrics from the same validated cache used by
investigation APIs. It requires the existing application session/origin protections.
Each metric contains `id`, `label`, numeric `value` or null, `destination`, `context`
and an `unavailable_reason`. Null means disabled or unavailable; zero is used only
when a loaded, enabled source genuinely has no matching records. No identity rows, paths, source filenames or snapshot IDs are returned. Compact
source availability and the email-coverage denominator accompany the metrics.

| Metric | Definition | Destination |
| --- | --- | --- |
| Catalogue roles | Distinct catalogue composite-role records | Role Lookup |
| Enabled SAP areas | Enabled areas represented in the loaded catalogue | Role Lookup |
| Role/T-code mappings | Sum of distinct T-codes per catalogue role; a code in two roles counts twice | Role Lookup |
| SAP users | Distinct normalized SAP usernames, including users without roles | User Access |
| Role assignment records | Imported distinct assignment intervals, including technical roles | User Access |
| Users with assignments | Distinct usernames with any retained assignment | User Access |
| Release roles | Distinct normalized ZO role names across all assignment validity states | Release Roles |
| Expired/future assignment records | Existing assignment validity calculation, evaluated today; not account validity | User Access |
| Employee Directory records | Confirmed directory records, when enabled and available | Employee Directory data source |
| Directory email matches | SAP identities with unique exact directory-email matches; context supplies the denominator | Filtered Account Review |
| Missing or ambiguous directory matches | SAP identities in all non-matched coverage categories, including missing email and unmatched values | Filtered Account Review |

Access metrics require enabled User–Role Mapping and a loaded User Access CSV.
Directory record counts require enabled Employee Directory and imported records.
Email coverage additionally requires enabled User–Role Mapping with SAP identities.
A disabled dependency does not disable Employee Directory or erase its import.

KPI actions open the relevant investigation with fresh list filters, leaving other
views alone. Release Roles opens its ordinary currently-valid assignment view, even
though its KPI includes all validity states; the card explicitly explains this.
Expired/future counts open User Access and explain how to select assignment status
inside User Details. They do not pretend to apply an unsupported directory-wide
status filter. Data-quality cards open filtered Account Review evidence, not a second Diagnostics implementation. Ordinary navbar navigation retains existing list
filters. Browser Back/Forward uses the existing view-history provider.

The dashboard summarizes data quality. Detailed technical health remains under
Health & Diagnostics; import counts/history live under Data Sources, and
Features contains preferences plus compact availability only.

## Shared notifications

`Shared/Notification.tsx` provides persistent success, error, warning and information
variants. Content uses the same 1536-pixel maximum width and responsive horizontal
padding as the main application. Dismissal uses a keyboard-focusable Lucide X button
with the accessible label **Dismiss notification**. Text can wrap without overlapping
it. Success uses a status region; errors use an alert. There is no automatic timeout
for important feedback. Existing data-source recovery and service-connection banners
retain their actionable recovery buttons and established status semantics.

## Related workflows

- [Employee Directory, feature dependencies and persistence](../data/EMPLOYEE_DIRECTORY.md)
- [Transaction evidence and assignment date filters](FILTERS.md)
- [Local builds and native Windows validation](../deployment/BUILD.md)

Automated Chromium screenshots cover both themes at 375, 800 and 1280 pixels.
They do not replace Windows/WebView2, native file-dialog or UNC-share validation.

## Operational overview and review links

Overview prioritizes SAP users, Catalogue roles, Release roles and Role/T-code
mappings. User Access groups users-with-assignments, assignment records and supported
account-review findings. Access Lifecycle owns expired/future **assignment** totals:
these are not inherently data-quality failures. Data Quality presents matched SAP
identities, missing/ambiguous matches and an accessible progress indicator/count/
one-decimal percentage (243 of 259 = 93.8%). Unavailable coverage is not zero.
Configuration stays secondary with source state, enabled areas and last successful
refresh. No historical trends or licensing savings are inferred.

Matching/review KPI actions open filtered **User Access → Account Review**. Missing
matches selects the directory-match finding; matched identities selects reliably
matched rows; review findings selects accounts requiring investigation. Source
configuration actions still open Data Sources directly. Release role KPI includes
all imported validity states and opens the ordinary currently-valid view, explained
by its context; lifecycle totals do not silently apply account-validity filters to
assignment evidence. See [Account Review](ACCOUNT_REVIEW.md).

## Overview and investigation workspace

The icon-led shared header introduces SAP Overview's four primary metrics. Access
& Risk uses compact investigation rows rather than another equal-sized card grid;
Directory & Data Health keeps identity counts and the coverage progress together.
Data Sources & Configuration includes all three independent sources with their
feature/availability state and actual last successful refresh. Counts and KPI
navigation retain their existing backend definitions. Lifecycle totals are
informational evidence, not automatically a security-risk finding.

## Investigation distributions and freshness

The middle workspace is three columns on wide desktop, two on tablet and stacked
on mobile: Access & Risk, Directory & Data Health, and Review Progress. Section
headings share the icon-led SectionHeader. One coverage indicator displays matched
count/eligible count, percentage and progress; it is not repeated in adjacent cards.

Review progress uses all currently imported SAP accounts, not just accounts with
findings. Pending includes outdated reviews; decisions never suppress underlying
findings. Reviewed, pending, outdated and AD-disabled/open-account links open the
corresponding Account Review filters. Unavailable annotations are not zero-filled.

Role Distribution counts each catalogue role once using its canonical SAP area;
click a bar to investigate that area in Role Lookup. It does not combine single-role
relationships or release assignments into those counts. Assignment distribution
counts users by distinct **currently valid** business/release roles (1–5, 6–20,
21+; zero-role users remain available through User Directory); it is descriptive, not a security score. The separate Users with assignments
metric still includes imported intervals of every validity state.

Source cards distinguish last import/activation, last validated source check and the
last successful global refresh. Missing timestamps remain unavailable. File modification
times are not inferred. All calculations use validated local snapshots; no history,
license consumption or effective authorization is inferred.

Role Distribution and Data Sources & Configuration share a two-column lower row on wide screens and stack at 800px or below. Source summaries reuse canonical diagnostic state (mode, loaded status, records and actual import freshness). Row navigation highlights the whole target for hover/focus; each source row remains one configuration action.

## Compact analytical row

Role Distribution, Data Sources & Configuration and Assignment Distribution are
separate responsive panels. Assignment bands count distinct currently valid
business/release roles, excluding expired, future and unknown intervals. Selecting
a band opens its filtered User Directory population; the removable chip, Saved
Filters and assignment CSV export retain that scope. High role counts are
informational, not security findings. Review completion uses the existing imported
SAP account population; outdated decisions remain pending.

Role Distribution initially shows the five largest SAP areas, with Show all/Show
less controls. Data Sources & Configuration is the final full-width section.
