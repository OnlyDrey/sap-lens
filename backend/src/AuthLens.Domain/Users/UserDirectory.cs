using AuthLens.Domain.Catalogue;
using AuthLens.Domain.Roles;

namespace AuthLens.Domain.Users;

public sealed record Account(string? ValidFrom, string? ValidTo, bool? Locked, string UserType, string UserGroup);

public sealed class Assignment
{
    public int Id { get; init; }
    public required string Username { get; init; }
    public required string UserKey { get; init; }
    public required string RoleName { get; init; }
    public required string UserGroup { get; init; }
    public required string Scope { get; init; }
    public string? ValidFrom { get; init; }
    public string? ValidTo { get; init; }
    public string? UserValidFrom { get; init; }
    public string? UserValidTo { get; init; }
    public bool? UserLocked { get; init; }
    public required string UserType { get; init; }
    public required string MatchStatus { get; init; }
    public required IReadOnlyList<string> CatalogueRoles { get; init; }
    public required IReadOnlyList<string> Tcodes { get; init; }
    public ReleaseRole? Release { get; init; }
    public bool Resolved => MatchStatus is "exact" or "wildcard";
}

public sealed class SapUser
{
    public required string Username { get; init; }
    public List<(string First, string Last)> Names { get; set; } = [];
    public List<string> Emails { get; set; } = [];
    public List<string> Groups { get; set; } = [];
    public List<Account> Accounts { get; set; } = [];
    public List<Assignment> Assignments { get; } = [];
}

public sealed class UserDirectory
{
    public Dictionary<string, SapUser> Users { get; } = new(StringComparer.Ordinal);
    public List<string> UserOrder { get; } = [];
    public List<Assignment> Assignments { get; } = [];
    public Dictionary<string, List<Assignment>> RoleIndex { get; } = new(StringComparer.Ordinal);
    public Dictionary<string, List<string>> TcodeIndex { get; } = new(StringComparer.Ordinal);
    public int GroupCount { get; set; }
    public int InvalidCataloguePatterns { get; set; }
    public int RelevantAssignments => Assignments.Count(a => a.Scope != "other");
    public int DirectoryOnlyUsers => Users.Values.Count(u => u.Assignments.Count == 0);
}

/// <summary>Port of user_access.build_users: identity, accounts, deduplicated assignment evidence, catalogue matching and indexes.</summary>
public static class UserDirectoryBuilder
{
    public const int MaxUsers = 100_000;

    public static UserDirectory Build(IEnumerable<IReadOnlyDictionary<string, string>> records, RoleCatalogue catalogue)
    {
        var state = new UserDirectory();
        var matcher = new RoleMatcher(catalogue.Ordered.Select(r => r.AgrName));
        var matched = new Dictionary<string, (RoleMatch Match, List<string> Codes)>(StringComparer.Ordinal);
        var unique = new HashSet<string>(StringComparer.Ordinal);
        var names = new Dictionary<string, HashSet<(string, string)>>();
        var emails = new Dictionary<string, HashSet<string>>();
        var groups = new Dictionary<string, HashSet<string>>();
        var accounts = new Dictionary<string, HashSet<Account>>();
        foreach (var row in records)
        {
            var key = RoleNames.NormalizeUsername(row["USERNAME"]);
            if (!state.Users.TryGetValue(key, out var user))
            {
                if (state.Users.Count >= MaxUsers) throw new DomainValidationException("User CSV exceeds the 100,000-user safety limit; no data was applied.");
                state.Users[key] = user = new SapUser { Username = row["USERNAME"] };
                state.UserOrder.Add(key);
                names[key] = []; emails[key] = new(StringComparer.Ordinal); groups[key] = new(StringComparer.Ordinal); accounts[key] = [];
            }
            names[key].Add((row["FIRST_NAME"], row["LAST_NAME"]));
            if (row["EMAIL"].Length > 0) emails[key].Add(row["EMAIL"]);
            groups[key].Add(row["USER_GROUP"]);
            var start = SapDates.Parse(row["USER_VALID_FROM"]); var end = SapDates.Parse(row["USER_VALID_TO"]);
            var roleStart = SapDates.Parse(row["ROLE_VALID_FROM"]); var roleEnd = SapDates.Parse(row["ROLE_VALID_TO"]);
            if ((start is { } s && end is { } e && s > e) || (roleStart is { } rs && roleEnd is { } re && rs > re))
                throw new DomainValidationException("A validity interval ends before it starts; no data was applied.");
            var lockText = row["USER_LOCKED"].Trim().PyUpper();
            bool? locked = lockText.Length == 0 ? null
                : lockText is "0" or "FALSE" or "NO" or "N" or "UNLOCKED" ? false
                : lockText is "X" or "TRUE" or "YES" or "Y" or "LOCKED" || (lockText.All(char.IsAsciiDigit) && lockText.Any(c => c != '0')) ? true : null;
            accounts[key].Add(new Account(SapDates.Iso8601(start), SapDates.Iso8601(end), locked, row["USER_TYPE"], row["USER_GROUP"]));
            if (row["ROLE_NAME"].Length == 0) continue; // supported directory-only record
            var identity = string.Join('\u001f', key, row["ROLE_NAME"], row["USER_GROUP"], start, end, roleStart, roleEnd, locked, row["USER_TYPE"]);
            if (!unique.Add(identity)) continue;
            var role = row["ROLE_NAME"];
            if (role.Contains('*')) throw new DomainValidationException("User exports require exact assigned role names, not catalogue wildcard patterns.");
            var normalized = RoleNames.Normalize(role);
            if (!matched.TryGetValue(normalized, out var hit))
            {
                var match = matcher.Match(role);
                var codes = match.Resolved
                    ? match.Candidates.SelectMany(n => catalogue.Roles[n].SingleRoles).SelectMany(s => s.Tcodes).Select(t => t.Code).Distinct(StringComparer.Ordinal).Order(StringComparer.Ordinal).ToList()
                    : [];
                matched[normalized] = hit = (match, codes);
            }
            var scope = RoleNames.Scope(role);
            var entry = new Assignment
            {
                Id = state.Assignments.Count, Username = user.Username, UserKey = key, RoleName = role, UserGroup = row["USER_GROUP"], Scope = scope,
                ValidFrom = SapDates.Iso8601(roleStart), ValidTo = SapDates.Iso8601(roleEnd), UserValidFrom = SapDates.Iso8601(start), UserValidTo = SapDates.Iso8601(end),
                UserLocked = locked, UserType = row["USER_TYPE"], MatchStatus = hit.Match.Status, CatalogueRoles = hit.Match.Candidates, Tcodes = hit.Codes,
                Release = scope == "release" ? RoleNames.ParseRelease(role) : null,
            };
            state.Assignments.Add(entry);
            user.Assignments.Add(entry);
            if (hit.Match.Resolved)
                foreach (var name in hit.Match.Candidates)
                {
                    if (!state.RoleIndex.TryGetValue(name, out var list)) state.RoleIndex[name] = list = [];
                    list.Add(entry);
                }
        }
        foreach (var name in state.RoleIndex.Keys)
            foreach (var code in catalogue.Roles[name].SingleRoles.SelectMany(s => s.Tcodes).Select(t => t.Code.PyUpper()).Distinct())
            {
                if (!state.TcodeIndex.TryGetValue(code, out var holders)) state.TcodeIndex[code] = holders = [];
                holders.Add(name);
            }
        foreach (var key in state.UserOrder)
        {
            var user = state.Users[key];
            user.Names = names[key].OrderBy(n => n.Item1, StringComparer.Ordinal).ThenBy(n => n.Item2, StringComparer.Ordinal).ToList();
            user.Emails = emails[key].Order(StringComparer.Ordinal).ToList();
            user.Groups = groups[key].Order(StringComparer.Ordinal).ToList();
            user.Accounts = accounts[key].OrderBy(PyRepr, StringComparer.Ordinal).ToList();
        }
        state.GroupCount = state.Users.Values.SelectMany(u => u.Groups).Where(g => g.Length > 0).Distinct().Count();
        state.InvalidCataloguePatterns = matcher.InvalidPatterns.Count;
        return state;
    }

    /// <summary>The order Python gives `sorted(accounts, key=repr)`: the repr text of the (from, to, locked, type, group) tuple.</summary>
    private static string PyRepr(Account a) => $"({Repr(a.ValidFrom)}, {Repr(a.ValidTo)}, {(a.Locked is null ? "None" : a.Locked.Value ? "True" : "False")}, {Repr(a.UserType)}, {Repr(a.UserGroup)})";

    private static string Repr(string? value)
    {
        if (value is null) return "None";
        var quote = value.Contains('\'') && !value.Contains('"') ? '"' : '\'';
        var body = value.Replace("\\", "\\\\", StringComparison.Ordinal);
        if (quote == '\'') body = body.Replace("'", "\\'", StringComparison.Ordinal);
        return quote + body.Replace("\n", "\\n", StringComparison.Ordinal).Replace("\r", "\\r", StringComparison.Ordinal).Replace("\t", "\\t", StringComparison.Ordinal) + quote;
    }
}
