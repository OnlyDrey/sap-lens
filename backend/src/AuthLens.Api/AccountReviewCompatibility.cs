using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using AuthLens.Domain.Directory;
using AuthLens.Domain.Text;
using AuthLens.Domain.Users;
using AuthLens.Persistence;

namespace AuthLens.Api;

/// <summary>Read-only compatibility for Python V1 schema-2 annotations. Newly written .NET fingerprints are unchanged.</summary>
internal static class AccountReviewCompatibility
{
    // Python sorts Unicode scalar values, rather than UTF-16 code units. Evidence keys themselves are ASCII.
    private static readonly IComparer<string> PythonOrder = Comparer<string>.Create((a, b) =>
    {
        using var left = a.EnumerateRunes().GetEnumerator();
        using var right = b.EnumerateRunes().GetEnumerator();
        while (true)
        {
            var l = left.MoveNext(); var r = right.MoveNext();
            if (!l || !r) return l.CompareTo(r);
            var difference = left.Current.Value.CompareTo(right.Current.Value);
            if (difference != 0) return difference;
        }
    });

    private static string Dump(object? value, bool ascii = false)
    {
        var json = PythonJson.Dumps(JsonSerializer.SerializeToNode(value));
        if (!ascii) return json;
        var result = new StringBuilder();
        foreach (var c in json) if (c < 127) result.Append(c); else result.Append("\\u").Append(((int)c).ToString("x4"));
        return result.ToString();
    }

    private static string Hash(object? value) => Convert.ToHexStringLower(SHA256.HashData(Encoding.UTF8.GetBytes(Dump(value))));

    public static bool Matches(ReviewDecision decision, string current, SapUser user, Dictionary<string, object?>? employee,
        string match, IReadOnlyList<string> groups, string validity, List<string> findings)
    {
        var details = JsonNode.Parse(decision.DetailsJson ?? "{}") as JsonObject;
        // V1's disappearance marker is independent of the fingerprint. Never revive a removed/reappeared account.
        if (details?["absent_since"] is JsonValue absent && absent.TryGetValue<string>(out var stamp) && stamp.Length > 0) return false;
        if (decision.EvidenceVersion == current) return true;
        // Unknown and schema-1 encodings stay fail-closed; only the established schema-2 contract is reconstructed.
        if (details?["evidence_schema"] is not JsonValue schema || !schema.TryGetValue<int>(out var version) || version != 2) return false;
        var identity = Hash(new object[]
        {
            user.Username.Trim().PyUpper(), user.Emails.Select(EmployeeDirectory.Normalized).Distinct().Order(PythonOrder).ToList(),
            user.Names.OrderBy(n => n.First, PythonOrder).ThenBy(n => n.Last, PythonOrder).Select(n => new[] { n.First, n.Last }).ToList(),
        });
        var accounts = user.Accounts.Select(a => Dump(new { valid_from = a.ValidFrom, valid_to = a.ValidTo, locked = a.Locked, user_type = a.UserType, user_group = a.UserGroup }, true)).Order(StringComparer.Ordinal).ToList();
        var assignments = user.Assignments.Select(a => Dump(new
        {
            role_name = a.RoleName, user_group = a.UserGroup, valid_from = a.ValidFrom, valid_to = a.ValidTo, scope = a.Scope,
            match_status = a.MatchStatus, catalogue_roles = a.CatalogueRoles, tcodes = a.Tcodes,
        }, true)).Order(StringComparer.Ordinal).ToList();
        var expected = Hash(new object?[]
        {
            identity, accounts, assignments, user.Groups.Order(PythonOrder).ToList(),
            employee is null ? null : new { email = employee["email"], username = employee["username"], account_status = employee["account_status"] },
            match, groups.Select(g => g.Trim().PyCasefold()).Order(PythonOrder).ToList(), validity, findings,
        });
        return decision.EvidenceVersion == expected;
    }
}
