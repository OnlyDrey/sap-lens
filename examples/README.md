# Synthetic examples

Every record and description in `synthetic.csv` is invented. No customer exports, system identifiers or confidential naming conventions are included. Transaction names beginning with DEMO are also invented.

The nine canonical columns demonstrate composite/child relationships, explicit parent/effective-role provenance, multiple module areas and conservative Unclassified handling. The current seven-column schema continues to work; PARENT_AGR and Effective_Role are optional.

`synthetic-profile.sap-lens.json` is retained as a schema-2 compatibility example,
not an active classification preset. Its old rules are archived without execution
when imported. It contains no source path or raw records. Current source setup
and user/release investigation are described in [the access guide](../docs/ACCESS_INVESTIGATION.md).
The automated user fixture is synthetic and uses example.invalid addresses.
