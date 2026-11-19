using AuthLens.Domain.Catalogue;

namespace AuthLens.Domain.Analysis;

public sealed record RoleLookupQuery(string? Search = null, IReadOnlyList<string>? FunctionKeys = null, string? FunctionKey = null, IReadOnlyList<string>? Tcodes = null,
    string TransactionMode = "and", bool ExcludeMatching = false, string? Tcode = null, IReadOnlyList<string>? ExcludeTcodes = null, string ExcludeMode = "any");

public sealed record RoleSummary(string AgrName, string? Text, string FunctionKey, string ModuleName, int TcodeCount, int SingleRoleCount, IReadOnlyList<string> MatchingTcodes);

/// <summary>Port of routers/roles.list_roles: SAP area filter, include/exclude transaction groups (AND/OR, ANY/ALL), text search and T-code search.
/// Result order is the Python order; sorting and paging are applied by the API on top of it.</summary>
public static class RoleLookup
{
    public static List<RoleSummary> Find(RoleCatalogue catalogue, RoleLookupQuery q)
    {
        IEnumerable<Role> roles = catalogue.Ordered;
        var keys = q.FunctionKeys ?? [];
        if (keys.Any(k => k.Length > 256)) throw new Roles.DomainValidationException("SAP area identifiers must not exceed 256 characters.");
        if (keys.Count > 0) roles = roles.Where(r => keys.Contains(r.FunctionKey));
        if (!string.IsNullOrEmpty(q.FunctionKey)) roles = roles.Where(r => r.FunctionKey == q.FunctionKey);
        var exact = TransactionFilters.Normalize(q.Tcodes ?? []);
        var excludedCodes = TransactionFilters.Normalize(q.ExcludeTcodes ?? []);
        var (include, includeMode, excluded, excludedMode) = TransactionFilters.LegacyGroups(exact, q.TransactionMode, q.ExcludeMatching);
        if (excludedCodes.Count > 0)
        {
            (excluded, excludedMode) = (excludedCodes, q.ExcludeMode);
            if (q.ExcludeMatching) (include, includeMode) = ([], "all");
        }
        var index = catalogue.TcodeIndex;
        if (include.Count > 0 || excluded.Count > 0)
        {
            var names = TransactionFilters.SelectRoleNames(index, include, includeMode, excluded, excludedMode);
            var result = roles.Where(r => names.Contains(r.AgrName)).Select(r => Summary(r,
                include.SelectMany(code => TransactionFilters.MatchingCodes(index, code)).Where(actual => index[actual].Contains(r.AgrName)).Distinct().Order(StringComparer.Ordinal).ToList()));
            if (!string.IsNullOrWhiteSpace(q.Search))
            {
                var query = q.Search.Trim().PyLower();
                result = result.Where(r => TextMatching.TextMatches(r.AgrName, query) || TextMatching.TextMatches(r.Text, query));
            }
            return result.ToList();
        }
        if (!string.IsNullOrWhiteSpace(q.Tcode))
        {
            var query = q.Tcode.Trim().PyUpper();
            bool Hit(string code) => query.Contains('*') ? TextMatching.TextMatches(code, query) : code.StartsWith(query, StringComparison.Ordinal);
            var matching = index.Where(p => Hit(p.Key)).SelectMany(p => p.Value).ToHashSet(StringComparer.Ordinal);
            var found = new List<RoleSummary>();
            foreach (var r in roles.Where(r => matching.Contains(r.AgrName)))
            {
                var seen = new HashSet<string>(StringComparer.Ordinal);
                var codes = new List<string>();
                foreach (var tc in r.SingleRoles.SelectMany(s => s.Tcodes))
                    if (!seen.Contains(tc.Code) && Hit(tc.Code.PyUpper())) { codes.Add(tc.Code); seen.Add(tc.Code); }
                found.Add(Summary(r, codes));
            }
            // Python's sorted() is stable: ties keep catalogue order.
            return found.OrderBy(x => (x.Text ?? x.AgrName).PyLower(), StringComparer.Ordinal).ToList();
        }
        if (!string.IsNullOrWhiteSpace(q.Search))
        {
            var query = q.Search.Trim().PyLower();
            roles = roles.Where(r => TextMatching.TextMatches(r.Text, query) || TextMatching.TextMatches(r.AgrName, query));
        }
        return roles.Select(r => Summary(r, [])).ToList();
    }

    private static RoleSummary Summary(Role r, IReadOnlyList<string> matching) => new(r.AgrName, r.Text, r.FunctionKey, r.ModuleName, r.TcodeCount, r.SingleRoles.Count, matching);
}
