using System.Text;
using System.Text.RegularExpressions;

namespace AuthLens.Domain.Roles;

public sealed record ReleaseRole(bool Parsed, string? DocumentType, string? ReleaseGroup, string? ReleaseStrategy, string? OpaqueScope = null, string? OpaqueSuffix = null);

/// <summary>Port of role_matching.normalize_role / role_scope and user_access.parse_release_role.</summary>
public static partial class RoleNames
{
    /// <summary>Removes every whitespace character and upper-cases. Python str.split() also treats U+001C..U+001F as whitespace.</summary>
    public static string Normalize(string? value)
    {
        var builder = new StringBuilder(value?.Length ?? 0);
        foreach (var c in value ?? "")
            if (!char.IsWhiteSpace(c) && c is not ('\u001c' or '\u001d' or '\u001e' or '\u001f')) builder.Append(c);
        return builder.ToString().PyUpper();
    }

    public static string Scope(string? value)
    {
        var name = Normalize(value);
        return name.StartsWith("ZC:", StringComparison.Ordinal) ? "business" : name.StartsWith("ZO:", StringComparison.Ordinal) ? "release" : "other";
    }

    [GeneratedRegex(@"^ZO:MM:([A-Z0-9_-]+):(PR|PO)_REL_ST_([A-Z0-9]+)_([A-Z0-9]+):([A-Z0-9_-]+)$", RegexOptions.CultureInvariant)]
    private static partial Regex ReleasePattern();

    /// <summary>MM, PR/PO_REL_ST and group/strategy positions are confirmed; scope and suffix tokens stay opaque.</summary>
    public static ReleaseRole ParseRelease(string? value)
    {
        var match = ReleasePattern().Match(Normalize(value));
        if (!match.Success) return new ReleaseRole(false, null, null, null);
        var g = match.Groups;
        return new ReleaseRole(true, g[2].Value, g[3].Value, g[4].Value, g[1].Value, g[5].Value);
    }

    public static string NormalizeUsername(string? value) => (value ?? "").Trim().PyUpper();
}
