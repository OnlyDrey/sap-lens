# Dashboard and shared notifications

Dashboard is available from the main navigation and at `#/dashboard`. Role Lookup
remains the default route for compatibility with existing links and desktop startup.
Its former KPI row now appears only on Dashboard. No historical trends are inferred
from a single import. All data stays on the managed loopback backend.

## Metrics and data boundaries

`GET /api/dashboard` returns aggregate metrics from the same validated cache used by
investigation APIs. It requires the existing application session/origin protections.
Each metric contains `id`, `label`, numeric `value` or null, `destination`, `context`
and an `unavailable_reason`. Null means disabled or unavailable; zero is used only
when a loaded, enabled source genuinely has no matching records. No identity rows,
paths, source filenames or snapshot IDs are returned.

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
| Directory email matches | SAP identities with unique exact directory-email matches; context supplies the denominator | Employee Directory data quality |
| Missing or ambiguous directory matches | SAP identities in all non-matched coverage categories, including missing email and unmatched values | Employee Directory data quality |

Access metrics require enabled User–Role Mapping and a loaded User Access CSV.
Directory record counts require enabled Employee Directory and imported records.
Email coverage additionally requires enabled User–Role Mapping with SAP identities.
A disabled dependency does not disable Employee Directory or erase its import.

KPI actions open the relevant investigation with fresh list filters, leaving other
views alone. Release Roles opens its ordinary currently-valid assignment view, even
though its KPI includes all validity states; the card explicitly explains this.
Expired/future counts open User Access and explain how to select assignment status
inside User Details. They do not pretend to apply an unsupported directory-wide
status filter. Data-quality cards open the Employee Directory source tab, not a
second Diagnostics implementation. Ordinary navbar navigation retains existing list
filters. Browser Back/Forward uses the existing view-history provider.

The dashboard summarizes data quality. Detailed technical health remains under
Application & Diagnostics; import counts/history live under Data Sources, and
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

- [Employee Directory, feature dependencies and persistence](EMPLOYEE_DIRECTORY.md)
- [Transaction evidence and assignment date filters](INVESTIGATION_FILTERS.md)
- [Local builds and native Windows validation](LOCAL_WINDOWS_BUILD.md)

Automated Chromium screenshots cover both themes at 375, 800 and 1280 pixels.
They do not replace Windows/WebView2, native file-dialog or UNC-share validation.
