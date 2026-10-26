# CSV-based SAP area labels

Domains & Classification, profile selection, rule management and preview endpoints
have been removed. SAP Modules remains available for names, icons, colors and
filter preferences. Recognized FUNCTION_KEY values/aliases from the role CSV
provide area labels. Missing, unknown and conflicting areas are Unclassified.
No role-identifier fragments create backend module classifications. Single-role
headers may display an unambiguous recognized module prefix from source descriptions
without changing backend area IDs; see [Role Lookup](../features/ROLE_LOOKUP.md).

Role hierarchy, parent/effective-role provenance and transaction assignments are
preserved. Old classification configuration is archived locally and never executed;
reading older settings does not rewrite the original. See [Configuration](../getting-started/CONFIGURATION.md)
for schema-3 compatibility, source setup, matching and release-role behavior.

The [earlier assessment](../archive/implementation/CLASSIFICATION_ARCHITECTURE.md) is a historical record of
the former behavior, not current configuration instructions.
