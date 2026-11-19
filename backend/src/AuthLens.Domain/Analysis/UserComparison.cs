using AuthLens.Domain.Catalogue;
using AuthLens.Domain.Roles;
using AuthLens.Domain.Users;

namespace AuthLens.Domain.Analysis;

public sealed class ComparedRole
{
    public required string Identifier { get; init; }
    public List<Dictionary<string, object?>> A { get; } = [];
    public List<Dictionary<string, object?>> B { get; } = [];
    public List<string> Areas { get; } = [];
    public string Description { get; set; } = "";
    public string Difference { get; set; } = "";
}

public sealed class ComparedTransaction
{
    public required string Identifier { get; init; }
    public SortedSet<string> A { get; } = new(StringComparer.Ordinal);
    public SortedSet<string> B { get; } = new(StringComparer.Ordinal);
    public List<string> Areas { get; set; } = [];
    public string Difference { get; set; } = "";
}

public sealed record ComparedUser(UserSummary Summary, bool IdentityAmbiguous);

public sealed class ComparisonResult
{
    public required List<ComparedUser> Users { get; init; }
    public required List<ComparedRole> Roles { get; init; }
    public required List<ComparedTransaction> Transactions { get; init; }
}

public sealed class NotFoundException(string message) : Exception(message);

/// <summary>Port of routers/user_comparison._compare: role-derived coverage of two users. Never infers effective SAP authorization; every distinct
/// interval and source group is retained as evidence.</summary>
public static class UserComparison
{
    public static ComparisonResult Compare(RoleCatalogue catalogue, UserDirectory users, string left, string right, string validity, DateOnly today)
    {
        var keys = new[] { RoleNames.NormalizeUsername(left), RoleNames.NormalizeUsername(right) };
        if (keys[0] == keys[1]) throw new DomainValidationException("Choose two different SAP users.");
        if (keys.Any(k => !users.Users.ContainsKey(k))) throw new NotFoundException("A selected SAP user is not in the current export.");
        var roles = new Dictionary<string, ComparedRole>(StringComparer.Ordinal);
        var roleOrder = new List<ComparedRole>();
        var codes = new Dictionary<string, ComparedTransaction>(StringComparer.Ordinal);
        var codeOrder = new List<ComparedTransaction>();
        foreach (var (side, key) in new[] { ("a", keys[0]), ("b", keys[1]) })
        {
            foreach (var a in users.Users[key].Assignments)
            {
                if (a.Scope == "other") continue;
                var status = SapDates.IntervalStatus(a.ValidFrom, a.ValidTo, today);
                if (validity != "all" && status != validity) continue;
                var name = RoleNames.Normalize(a.RoleName);
                if (!roles.TryGetValue(name, out var item)) { roles[name] = item = new ComparedRole { Identifier = name }; roleOrder.Add(item); }
                (side == "a" ? item.A : item.B).Add(Evidence(a, status, today));
                if (a.Resolved)
                    foreach (var role in a.CatalogueRoles)
                        if (catalogue.Roles.TryGetValue(role, out var detail))
                        {
                            if (detail.ModuleName.Length > 0 && !item.Areas.Contains(detail.ModuleName)) item.Areas.Add(detail.ModuleName);
                            if (item.Description.Length == 0) item.Description = detail.Text ?? "";
                        }
                if (!a.Resolved) continue;
                foreach (var code in a.Tcodes)
                {
                    if (!codes.TryGetValue(code, out var entry)) { codes[code] = entry = new ComparedTransaction { Identifier = code }; codeOrder.Add(entry); }
                    (side == "a" ? entry.A : entry.B).Add(name);
                    entry.Areas = entry.Areas.Union(item.Areas).Order(StringComparer.Ordinal).ToList();
                }
            }
        }
        foreach (var r in roleOrder) r.Difference = r.A.Count > 0 && r.B.Count > 0 ? "shared" : r.A.Count > 0 ? "a" : "b";
        foreach (var t in codeOrder) t.Difference = t.A.Count > 0 && t.B.Count > 0 ? "shared" : t.A.Count > 0 ? "a" : "b";
        var summaries = keys.Select(k =>
        {
            var u = users.Users[k];
            return new ComparedUser(UserLookup.Summary(u, u.Assignments, today), u.Names.Count(n => n.First.Length > 0 || n.Last.Length > 0) > 1 || u.Emails.Count > 1);
        }).ToList();
        return new ComparisonResult { Users = summaries, Roles = roleOrder, Transactions = codeOrder };
    }

    private static Dictionary<string, object?> Evidence(Assignment a, string status, DateOnly today) => new()
    {
        ["id"] = a.Id, ["username"] = a.Username, ["user_key"] = a.UserKey, ["role_name"] = a.RoleName, ["user_group"] = a.UserGroup, ["scope"] = a.Scope,
        ["valid_from"] = a.ValidFrom, ["valid_to"] = a.ValidTo, ["match_status"] = a.MatchStatus, ["catalogue_roles"] = a.CatalogueRoles.Cast<object?>().ToList(),
        ["tcode_count"] = a.Tcodes.Count, ["status"] = status, ["account_status"] = SapDates.IntervalStatus(a.UserValidFrom, a.UserValidTo, today),
    };

    /// <summary>Port of the listing filters of GET /api/user-comparison: difference, SAP areas (OR), search, sort with identifier tie-break.</summary>
    public static List<T> Select<T>(IEnumerable<T> rows, string difference, IReadOnlySet<string> areas, string search, string sort, bool descending,
        Func<T, string> identifier, Func<T, string> diff, Func<T, IReadOnlyList<string>> rowAreas, Func<T, string> description, Func<T, int> countA, Func<T, int> countB)
    {
        var term = search.Trim();
        var list = rows.Where(r => (difference.Length == 0 || diff(r) == difference) && (areas.Count == 0 || areas.Overlaps(rowAreas(r)))
                                   && (term.Length == 0 || TextMatching.SearchFields(term, identifier(r), description(r)))).ToList();
        Comparison<T> primary = sort switch
        {
            "a" => (x, y) => countA(x).CompareTo(countA(y)),
            "b" => (x, y) => countB(x).CompareTo(countB(y)),
            "difference" => (x, y) => string.CompareOrdinal(diff(x), diff(y)),
            _ => (x, y) => string.CompareOrdinal(identifier(x), identifier(y)),
        };
        list.Sort((x, y) => { var p = primary(x, y); return p != 0 ? p : string.CompareOrdinal(identifier(x), identifier(y)); });
        if (descending) list.Reverse();
        return list;
    }
}
