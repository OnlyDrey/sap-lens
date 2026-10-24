# Data Health & Coverage

Open **Settings → Data Sources** and expand **Data Health & Coverage**. No new primary navigation. Source-detail actions focus the existing Role Catalogue, User Access or Employee Directory import tab. Detailed technical failures/recovery remain in Health & Diagnostics.

Source cards distinguish enabled preference, configured path, validated data availability, record count, last successful publication and snapshot type. Role and SAP user datasets are memory publications reloaded from their configured CSV at startup; only Employee Directory has an explicit durable snapshot. “Available” means validated published data, not a promise that the original CSV is still accessible. Employee Directory details contain original-file availability and durable recovery. A disabled optional source is neutral, not an application failure.

Coverage denominators:

- Catalogue coverage: every retained ZC/ZO assignment **record**, across all statuses and distinct intervals/groups. Numerator: exact or unambiguous wildcard match. Technical single-role assignments excluded explicitly. Both sources must be available/enabled.
- T-code coverage: all imported catalogue roles; numerator roles with at least one T-code. This measures export completeness, not effective authorization.
- Identity coverage: all SAP users eligible under the existing enabled mapping + available directory dependency; numerator uniquely matched normalized emails. Missing and ambiguous identities remain in the denominator. Zero eligible records has no percentage.

The overview includes raw parsed/unique/identical-duplicate import totals. Repeated role rows representing different transactions are not duplicate role definitions. Importers reject invalid required fields, malformed dates and reversed intervals before replacing the active publication. Rejected rows cannot be reconstructed from the validated dataset; inspect source validation/diagnostics instead.

Warnings: unmapped/ambiguous catalogue relationships, missing assignment bounds, unknown/missing SAP user type. Information: expired/future lifecycle records, unparsed release names, optional missing descriptions/module evidence, catalogue roles without mappings, multiple identity/account observations. Multiple observations may be legitimate; the UI does not declare them conflicting errors. Missing mappings/descriptions or expired historical records are not automatically security issues.

Source cards count catalogue roles, SAP users and directory records; raw CSV rows are shown separately. Findings can overlap and must not be summed as a distinct-user error count.

Select a nonzero finding to inspect paginated exact identifiers and open an existing user/role record. Source-specific directory email/identifier/manager statistics use the existing directory report rather than duplicate rules. Source health details remain available in the existing source panels.

Aggregate catalogue/assignment calculations are cached for one publication/date; refresh invalidates them. A failed replacement preserves previous data and coverage. Browser queries participate in application-scoped refresh invalidation. No result datasets are persisted by Data Health. Routine metrics contain no personal emails or source paths; authenticated drilldown contains the necessary local identifiers.
