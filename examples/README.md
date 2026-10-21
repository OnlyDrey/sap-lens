# Synthetic examples

Every record and description in `synthetic.csv` is invented. No customer exports, system identifiers or confidential naming conventions are included. Transaction names beginning with DEMO are also invented.

The nine canonical columns demonstrate composite/child relationships, explicit parent/effective-role provenance, multiple module areas and conservative Unclassified handling. The current seven-column schema continues to work; PARENT_AGR and Effective_Role are optional.

`synthetic-profile.sap-lens.json` is a portable configuration example with simple local customer-domain rules over these invented names. It contains no CSV path or raw records. Import it through Application & Diagnostics, then select the synthetic CSV separately. It demonstrates Custom classification rather than claiming these prefixes are SAP standards.
