# User Comparison

Open **User Access → Compare users**, or **Compare users** in an existing SAP User Details profile. The latter seeds User A. Search both selectors by username, name or email; select an actual SAP username. Identical users are excluded. Missing names/emails are labeled, not matched heuristically. Search includes alternate source email/name observations; server-filtered options are not re-filtered against only the displayed representative identity. Multiple observations are flagged in the comparison header. SAP identity remains authoritative; directory enrichment is not required.

The default includes **Currently valid** role-assignment intervals only. Choose Expired, Future, Unknown or All intervals explicitly. Account validity and lock are shown separately and do not change assignment validity. Missing bounds never establish active access; 31.12.9999 is a real date. ZC business and ZO release assignments participate; technical assignments remain in the underlying catalogue model.

Roles are compared by the existing normalized exact assigned role identifier, not by equal descriptions or equal catalogue patterns. Every distinct source interval/group is preserved. Shared means each selected user has at least one interval in the selected validity view; it does not mean all their intervals are identical or overlap outside the current-date view.

Transaction comparison unions mappings only from exact or unambiguous wildcard catalogue matches. A shared T-code may come through different roles. Each side lists all explaining exact assigned roles; select one to inspect its interval evidence. Role evidence links to actual matched catalogue records, avoiding broken links for unmapped or wildcard-assigned names. T-code links open the existing User Directory transaction investigation. Missing mappings cannot prove absence of effective SAP access.

Search, category (All/Shared/Only A/Only B) and SAP area filters apply to the selected result section. Summary metrics describe the selected pair/validity before result search/category/area filters. Results are sorted deterministically by identifier and paginated. The backend reads only the two selected users' assignments; it does not transfer the entire user dataset to the browser.

User/role navigation uses existing history; Back returns to the preserved comparison. Saved comparison filters deliberately omit User A/B identities, allowing the same investigation to be reused for a different pair.

**Export comparison CSV** exports the current section and filters. Rows identify A/B, category, compared usernames and interval evidence (or transaction-to-role evidence). All pages must share a source generation/date; changes or leaving the comparison cancel export before saving. Spreadsheet formulas are neutralized, export size is bounded, and desktop export uses the existing authenticated local save bridge. No SAP data uploads occur.

See [Saved Filters](SAVED_FILTERS.md), [Data Health](DATA_HEALTH.md) and [Access Insights assessment](ACCESS_INSIGHTS_FEASIBILITY.md).
