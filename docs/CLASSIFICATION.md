# CSV-based SAP area labels

Domains & Classification, profile selection, rule management and preview endpoints
have been removed. SAP Modules remains available for names, icons, colors and
filter preferences. Recognized FUNCTION_KEY values/aliases from the role CSV
provide area labels. Missing, unknown and conflicting areas are Unclassified.
No child-name, description or arbitrary prefix inference is performed.

Role hierarchy, parent/effective-role provenance and transaction assignments are
preserved. Old classification configuration is archived locally and never executed;
reading older settings does not rewrite the original. See [access investigation](ACCESS_INVESTIGATION.md)
for schema-3 compatibility, source setup, matching and release-role behavior.

The [earlier assessment](CLASSIFICATION_ARCHITECTURE.md) is a historical record of
the former behavior, not current configuration instructions.
