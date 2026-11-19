namespace AuthLens.Domain.Roles;

public sealed record RoleMatch(string Status, IReadOnlyList<string> Candidates)
{
    public static readonly RoleMatch Unmapped = new("unmapped", []);
    public bool Resolved => Status is "exact" or "wildcard";
}

/// <summary>Port of role_matching.RoleMatcher: anchored literal names and literal-prefix wildcards; catalogue patterns are never assignments.</summary>
public sealed class RoleMatcher
{
    private readonly Dictionary<string, List<string>> _exact = new(StringComparer.Ordinal);
    private readonly Dictionary<string, List<string>> _prefixes = new(StringComparer.Ordinal);
    public List<string> InvalidPatterns { get; } = [];

    public RoleMatcher(IEnumerable<string> names)
    {
        foreach (var original in names)
        {
            var key = RoleNames.Normalize(original);
            if (key.Length == 0 || key.Length > 512 || key.IndexOfAny(['?', '[', ']', '\\']) >= 0) { InvalidPatterns.Add(original); continue; }
            if (key.Contains('*'))
            {
                if (key.Count(c => c == '*') != 1 || !key.EndsWith('*') || key.Length == 1) { InvalidPatterns.Add(original); continue; }
                Add(_prefixes, key[..^1], original);
            }
            else Add(_exact, key, original);
        }
    }

    private static void Add(Dictionary<string, List<string>> map, string key, string value)
    {
        if (!map.TryGetValue(key, out var list)) map[key] = list = [];
        list.Add(value);
    }

    public RoleMatch Match(string assigned)
    {
        var key = RoleNames.Normalize(assigned);
        if (key.Length == 0 || key.Contains('*') || key.Length > 512) return RoleMatch.Unmapped;
        if (_exact.TryGetValue(key, out var exact))
            return new RoleMatch(exact.Count == 1 ? "exact" : "ambiguous", exact.Order(StringComparer.Ordinal).ToList());
        for (var length = key.Length; length > 0; length--)
            if (_prefixes.TryGetValue(key[..length], out var candidates))
                return new RoleMatch(candidates.Count == 1 ? "wildcard" : "ambiguous", candidates.Order(StringComparer.Ordinal).ToList());
        return RoleMatch.Unmapped;
    }
}
