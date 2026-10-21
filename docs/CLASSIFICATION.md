# Classification profiles

SAP areas, organization-specific business domains and raw SAP identifiers are separate concepts. Classification never rewrites role names, transactions or relationship fields. Each result carries profile ID, version and a deterministic content fingerprint, plus import profile/version and configuration revision.

- **Legacy** preserves previous area-hint behavior, including unknown explicit source values and recognized child-description/name hints. Compatibility does not make historic naming assumptions universal SAP rules.
- **Generic** recognizes central-registry area codes/aliases in FUNCTION_KEY. It does not infer company domains from arbitrary prefixes. Missing/unknown/conflicting source hints remain Unclassified.
- **Custom** uses organization-authored domains mapped optionally to stable SAP areas. Domain labels are configurable independently of SAP abbreviations.

Custom exact role overrides take precedence. Prefix, exact, contains and regex rules then use ascending numerical priority (smaller wins). Equal-priority matches to different domains are ambiguous and remain Unclassified. With no match, the configured fallback domain applies, otherwise Unclassified. Case sensitivity is explicit. Rules are evaluated against role identifiers, not executable code.

Preview shows domain/area totals, unclassified/ambiguous counts, detected conflicts, samples and changes against current results. Test an individual role before applying. Applying a material profile change rebuilds the analysis atomically while preserving source assignments. Static conflict warnings do not establish that two arbitrary regexes can never overlap; inspect observed ambiguity too.

Profiles permit at most 100 domains and 64 rules, regex patterns at most 256 characters, identifiers at most 512. Regex matching times out after 2 ms per match; a classification pass has a five-second deadline. Preview is limited to 100,000 roots and runs in bounded daemon work slots. Expensive/invalid patterns fail safely, preserving the active analysis. Reserved object-property identifiers are rejected.

Use the invented examples in [examples](../examples/README.md), never commit organization rules or live SAP exports.
