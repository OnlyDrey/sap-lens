using AuthLens.Domain.Roles;

namespace AuthLens.Domain.Analysis;

/// <summary>Port of transaction_filters.py: bounded exact T-code filters with independent include and exclude groups.</summary>
public static class TransactionFilters
{
    public static IReadOnlyList<string> Normalize(IEnumerable<string> values)
    {
        var list = values.ToList();
        if (list.Count > 21) throw new DomainValidationException("At most 20 saved transaction filters and one draft are supported.");
        if (list.Any(v => v.Length > 128)) throw new DomainValidationException("Transaction filters must not exceed 128 characters.");
        return list.Select(v => v.Trim().PyUpper()).Where(v => v.Length > 0).Distinct().ToList();
    }

    public static IEnumerable<string> MatchingCodes<T>(IReadOnlyDictionary<string, T> index, string query) =>
        query.Contains('*') ? index.Keys.Where(code => TextMatching.TextMatches(code, query)) : index.ContainsKey(query) ? [query] : [];

    public static HashSet<string> MatchingRoleNames(IReadOnlyDictionary<string, HashSet<string>> index, IReadOnlyList<string> codes, string mode)
    {
        if (codes.Count == 0) return [];
        var groups = codes.Select(code => MatchingCodes(index, code).SelectMany(actual => index[actual]).ToHashSet(StringComparer.Ordinal)).ToList();
        var result = new HashSet<string>(groups[0], StringComparer.Ordinal);
        foreach (var group in groups.Skip(1)) { if (mode == "and") result.IntersectWith(group); else result.UnionWith(group); }
        return result;
    }

    public static HashSet<string> SelectRoleNames(IReadOnlyDictionary<string, HashSet<string>> index, IReadOnlyList<string> include, string includeMode,
        IReadOnlyList<string> exclude, string excludeMode)
    {
        HashSet<string>? selected = null;
        if (include.Count > 0) selected = MatchingRoleNames(index, include, includeMode == "all" ? "and" : "or");
        if (exclude.Count > 0)
        {
            var holding = index.Values.SelectMany(v => v).ToHashSet(StringComparer.Ordinal);
            var removed = MatchingRoleNames(index, exclude, excludeMode == "any" ? "or" : "and");
            selected = selected is null ? holding : new HashSet<string>(selected.Intersect(holding), StringComparer.Ordinal);
            selected.ExceptWith(removed);
        }
        return selected ?? [];
    }

    public static (IReadOnlyList<string> Include, string IncludeMode, IReadOnlyList<string> Exclude, string ExcludeMode) LegacyGroups(IReadOnlyList<string> codes, string mode, bool exclude) =>
        exclude ? ([], "all", codes, mode == "and" ? "all" : "any") : (codes, mode == "and" ? "all" : "any", [], "any");
}
