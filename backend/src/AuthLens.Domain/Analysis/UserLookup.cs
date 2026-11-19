using AuthLens.Domain.Roles;
using AuthLens.Domain.Users;

namespace AuthLens.Domain.Analysis;

public sealed record UserLookupQuery(string Search = "", string Group = "", IReadOnlyList<string>? Groups = null, string Role = "", IReadOnlyList<string>? Roles = null,
    string Tcode = "", IReadOnlyList<string>? Tcodes = null, string TransactionMode = "and", bool ExcludeTransactions = false, IReadOnlyList<string>? ExcludeTcodes = null,
    string ExcludeMode = "any", string Status = "", bool ShowExpired = false, string Sort = "username", bool Descending = false);

public sealed record UserSummary(string Username, string UserKey, IReadOnlyList<string> Groups, string FirstName, string LastName, string Email,
    string AccountStatus, string LockStatus, int RelevantRoles);

/// <summary>Port of the core of routers/access.directory_selection (User Access): search, SAP user groups (OR), roles (OR), transaction include
/// and exclude groups, assignment validity, sorting. Not ported: username lists, missing-role, functional-group, manager and band filters and the
/// Directory-dependent filters, which V1Access applies; the Directory job title and department reach the search through <c>directoryFields</c>.</summary>
public static class UserLookup
{
    public static IEnumerable<Assignment> MatchingEntries(UserDirectory state, string role = "", string tcode = "")
    {
        if (tcode.Length > 0)
        {
            var unique = new SortedDictionary<int, Assignment>();
            var names = TransactionFilters.MatchingCodes(state.TcodeIndex, tcode.Trim().PyUpper()).SelectMany(code => state.TcodeIndex[code]).ToHashSet(StringComparer.Ordinal);
            foreach (var name in names) foreach (var a in state.RoleIndex.GetValueOrDefault(name) ?? []) unique[a.Id] = a;
            return unique.Values;
        }
        if (role.Length > 0)
        {
            var key = RoleNames.Normalize(role);
            return state.Assignments.Where(a => RoleNames.Normalize(a.RoleName) == key || (a.CatalogueRoles.Any(n => RoleNames.Normalize(n) == key) && a.Resolved));
        }
        return state.Assignments;
    }

    public static bool Relevant(Assignment a, string status, bool showExpired, DateOnly today)
    {
        var current = SapDates.IntervalStatus(a.ValidFrom, a.ValidTo, today);
        return status.Length > 0 ? current == status : showExpired || current != "expired";
    }

    public static UserSummary Summary(SapUser user, IEnumerable<Assignment> entries, DateOnly today)
    {
        var named = user.Names.Where(n => n.First.Length > 0 || n.Last.Length > 0).ToList();
        var (first, last) = named.Count > 0 ? named[0] : ("", "");
        var statuses = user.Accounts.Select(a => SapDates.IntervalStatus(a.ValidFrom, a.ValidTo, today)).Distinct().Order(StringComparer.Ordinal);
        var locks = user.Accounts.Select(a => a.Locked).Distinct().ToList();
        var lockStatus = locks.Count == 1 && locks[0] == true ? "Locked" : locks.Count == 1 && locks[0] == false ? "Unlocked" : "Mixed / unknown";
        return new UserSummary(user.Username, RoleNames.NormalizeUsername(user.Username), user.Groups, first, last, user.Emails.FirstOrDefault() ?? "",
            string.Join('/', statuses), lockStatus, entries.Where(a => a.Scope != "other").Select(a => RoleNames.Normalize(a.RoleName)).Distinct().Count());
    }

    public static List<UserSummary> Find(UserDirectory state, bool catalogueAvailable, UserLookupQuery q, DateOnly today, Func<string, (string Title, string Department)>? directoryFields = null) =>
        FindWithEvidence(state, catalogueAvailable, q, today, directoryFields).Result;

    /// <summary>directory_selection: the matching users and, per user key, the assignments that matched the filters (export MATCHED_FILTER).</summary>
    public static (List<UserSummary> Result, Dictionary<string, List<Assignment>> Evidence) FindWithEvidence(UserDirectory state, bool catalogueAvailable, UserLookupQuery q, DateOnly today,
        Func<string, (string Title, string Department)>? directoryFields = null)
    {
        var wanted = TransactionFilters.Normalize(q.Tcode.Length > 0 ? [q.Tcode, .. q.Tcodes ?? []] : q.Tcodes ?? []);
        var (include, includeMode, excluded, excludedMode) = TransactionFilters.LegacyGroups(wanted, q.TransactionMode, q.ExcludeTransactions);
        var explicitExcluded = TransactionFilters.Normalize(q.ExcludeTcodes ?? []);
        if (explicitExcluded.Count > 0)
        {
            (excluded, excludedMode) = (explicitExcluded, q.ExcludeMode);
            if (q.ExcludeTransactions) (include, includeMode) = ([], "all");
        }
        var groupSet = new[] { q.Group }.Concat(q.Groups ?? []).Where(v => v.Length > 0).ToHashSet(StringComparer.Ordinal);
        var roleList = new[] { q.Role }.Concat(q.Roles ?? []).Where(v => v.Length > 0).ToList();
        IEnumerable<Assignment> candidates = roleList.Count > 0
            ? roleList.SelectMany(value => MatchingEntries(state, value)).DistinctBy(a => a.Id)  // per-user evidence order does not affect any output
            : MatchingEntries(state);
        var evidence = new Dictionary<string, List<Assignment>>(StringComparer.Ordinal);
        foreach (var a in candidates)
            if (a.Scope != "other" && Relevant(a, q.Status, q.ShowExpired, today) && (groupSet.Count == 0 || groupSet.Contains(a.UserGroup)))
            {
                if (!evidence.TryGetValue(a.UserKey, out var list)) evidence[a.UserKey] = list = [];
                list.Add(a);
            }
        if ((include.Count > 0 || excluded.Count > 0) && catalogueAvailable)
        {
            var codeIds = include.Concat(excluded).Distinct().ToDictionary(code => code, code => TransactionFilters.MatchingCodes(state.TcodeIndex, code)
                .SelectMany(actual => state.TcodeIndex[actual]).SelectMany(name => state.RoleIndex.GetValueOrDefault(name) ?? []).Select(a => a.Id).ToHashSet());
            foreach (var key in evidence.Keys.ToList())
            {
                var entries = evidence[key];
                var matches = codeIds.Where(p => entries.Any(a => p.Value.Contains(a.Id))).Select(p => p.Key).ToHashSet(StringComparer.Ordinal);
                if (include.Count > 0)
                {
                    var hit = matches.Intersect(include).Count();
                    if (!(includeMode == "all" ? hit == include.Count : hit > 0)) { evidence.Remove(key); continue; }
                }
                if (excluded.Count > 0)
                {
                    var hit = matches.Intersect(excluded).Count();
                    if ((excludedMode == "all" ? hit == excluded.Count : hit > 0) || entries.Count == 0 || entries.Any(a => !a.Resolved)) { evidence.Remove(key); continue; }
                }
                if (include.Count > 0) evidence[key] = entries.Where(a => include.Any(code => codeIds[code].Contains(a.Id))).ToList();
            }
        }
        else if (excluded.Count > 0) evidence.Clear();
        var term = q.Search.Trim();
        var result = new List<UserSummary>();
        foreach (var key in state.UserOrder)
        {
            var user = state.Users[key];
            if (groupSet.Count > 0 && !groupSet.Overlaps(user.Groups)) continue;
            if ((roleList.Count > 0 || (include.Count > 0 && catalogueAvailable) || excluded.Count > 0 || q.Status.Length > 0) && !evidence.ContainsKey(key)) continue;
            if (term.Length > 0)
            {
                // v1: the Directory job title and department of a matched employee take part in the free-text search.
                var (title, department) = directoryFields?.Invoke(key) ?? ("", "");
                if (!TextMatching.SearchFields(term, [user.Username, .. user.Groups, .. user.Emails, .. user.Names.Select(n => n.First + " " + n.Last), title, department])) continue;
            }
            result.Add(Summary(user, evidence.GetValueOrDefault(key) ?? [], today));
        }
        IComparer<string> ordinal = StringComparer.Ordinal;
        Func<UserSummary, IComparable> primary = q.Sort switch
        {
            "group" => u => u.Groups.Count > 0 ? u.Groups[0] : "",
            "first_name" => u => u.FirstName, "last_name" => u => u.LastName, "email" => u => u.Email, "account_status" => u => u.AccountStatus,
            "lock_status" => u => u.LockStatus, "relevant_roles" => u => u.RelevantRoles, "user_key" => u => u.UserKey,
            _ => u => u.Username,
        };
        var comparer = Comparer<UserSummary>.Create((x, y) =>
        {
            var p = primary(x) is string a && primary(y) is string b ? string.CompareOrdinal(a, b) : primary(x).CompareTo(primary(y));
            return p != 0 ? p : string.CompareOrdinal(x.UserKey, y.UserKey);
        });
        result.Sort(comparer);
        if (q.Descending) result.Reverse();
        return (result, evidence);
    }
}
