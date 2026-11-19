using System.Text.RegularExpressions;

namespace AuthLens.Domain.Roles;

public sealed record PackageItem(string Role, string Suffix, string Source);

/// <summary>One proposed role name. Field order and values follow v1 access_package.preview.</summary>
public sealed class PackageRow
{
    public required string Role { get; init; }
    public string Description { get; init; } = "";
    public string Suffix { get; init; } = "";
    public string SuffixSource { get; init; } = "none";
    public bool SuffixEligible { get; init; }
    public string? SuffixNote { get; init; }
    public string? Name { get; set; }
    public string Status { get; set; } = "ok";
    public string Validation { get; set; } = "attention";
    public bool Exportable { get; set; }
    public List<string> Messages { get; set; } = [];
    public RoleMatch? Catalogue { get; set; }
    public required string Source { get; init; }
}

/// <summary>Port of access_package.py: proposed SAP role names from catalogue roles with an organizational suffix. Pure derivations over the
/// imported catalogue; nothing changes SAP access or stored data. Ambiguous source identifiers are reported, never silently rewritten.</summary>
public static partial class AccessPackage
{
    public const int MaxRoleName = 30; // SAP AGR_NAME length
    public const int MinStems = 2;     // a final segment is an organizational suffix when used under at least this many role stems
    public const string ExactNote = "Exact role name: the catalogue has no suffix variants for it, so the name is kept.";

    public static readonly IReadOnlyDictionary<string, string> ValidationLabel = new Dictionary<string, string>
    {
        ["confirmed"] = "Confirmed", ["pattern"] = "Pattern match", ["attention"] = "Needs attention", ["invalid"] = "Invalid",
    };

    [GeneratedRegex("^[A-Z0-9_-]{1,16}$", RegexOptions.CultureInvariant)]
    private static partial Regex SuffixPattern();

    [GeneratedRegex("^[A-Z0-9_:/.-]+$", RegexOptions.CultureInvariant)]
    private static partial Regex NamePattern();

    /// <summary>Final segments of business roles (ZC:) used under several stems, with the number of stems.</summary>
    public static Dictionary<string, int> NamingEvidence(IEnumerable<string> names)
    {
        var stems = new Dictionary<string, HashSet<string>>(StringComparer.Ordinal);
        foreach (var name in names)
        {
            var key = RoleNames.Normalize(name);
            if (key.Contains('*') || !key.Contains(':') || RoleNames.Scope(key) != "business") continue;
            var cut = key.LastIndexOf(':');
            var last = key[(cut + 1)..];
            if (last.Length == 0) continue;
            if (!stems.TryGetValue(last, out var set)) stems[last] = set = new HashSet<string>(StringComparer.Ordinal);
            set.Add(key[..cut]);
        }
        return stems.Where(p => p.Value.Count >= MinStems).ToDictionary(p => p.Key, p => p.Value.Count, StringComparer.Ordinal);
    }

    public static string NormalizeSuffix(string? value) => RoleNames.Normalize(value).Trim(':');

    public static string? SuffixError(string suffix) =>
        suffix.Length == 0 || SuffixPattern().IsMatch(suffix) ? null : "Suffix may only use letters, digits, underscore and hyphen (1 to 16 characters).";

    public static string? SuffixKind(string source, IReadOnlyDictionary<string, int> known)
    {
        var key = RoleNames.Normalize(source);
        if (key.Contains('*')) return "wildcard";
        return key.Contains(':') && known.ContainsKey(key[(key.LastIndexOf(':') + 1)..]) ? "organizational" : null;
    }

    public static (string? Name, string Kind, string? Message) Propose(string source, string suffix, IReadOnlyDictionary<string, int> known)
    {
        var key = RoleNames.Normalize(source);
        var kind = SuffixKind(key, known);
        if (kind is null) return (key, "exact", null);
        if (kind == "organizational") return ($"{key[..key.LastIndexOf(':')]}:{suffix}", "organizational", null);
        if (key.Count(c => c == '*') != 1 || !key.EndsWith('*') || key.Length == 1) return (null, "ambiguous", "Unsupported wildcard pattern; only a trailing * is supported.");
        var prefix = key[..^1];
        if (prefix.EndsWith(':')) return (prefix + suffix, "wildcard", null);
        var partial = prefix[(prefix.LastIndexOf(':') + 1)..];
        if (partial.Length > 0 && suffix.StartsWith(partial, StringComparison.Ordinal)) return (prefix[..^partial.Length] + suffix, "wildcard", null);
        return (null, "ambiguous", $"The pattern keeps the partial segment '{partial}'; the suffix must start with it.");
    }

    public static string? NameError(string name)
    {
        if (!NamePattern().IsMatch(name)) return "Only A-Z, 0-9 and _ : / . - are allowed in a role name.";
        var length = name.EnumerateRunes().Count();
        return length > MaxRoleName ? $"Longer than {MaxRoleName} characters ({length})." : null;
    }

    /// <summary>Deterministic, order-preserving preview. Confirmed needs the exact generated name in the explicit catalogue roles or user assignments;
    /// a wildcard match alone is a Pattern match and an unsupported name Needs attention. Release roles always keep their exact name.</summary>
    /// <param name="catalogue">agr_name to description, in catalogue order.</param>
    public static List<PackageRow> Preview(string? defaultSuffix, IEnumerable<PackageItem> items, IReadOnlyDictionary<string, string> catalogue,
        IReadOnlySet<string> releaseRoles, IEnumerable<string> assignedRoles)
    {
        var known = NamingEvidence(catalogue.Keys);
        var explicitNames = catalogue.Keys.Where(n => !n.Contains('*')).Select(RoleNames.Normalize).Concat(assignedRoles.Select(RoleNames.Normalize)).ToHashSet(StringComparer.Ordinal);
        var matcher = new RoleMatcher(catalogue.Keys);
        var fallback = NormalizeSuffix(defaultSuffix);
        var rows = new List<PackageRow>();
        var seen = new Dictionary<string, string>(StringComparer.Ordinal);

        void Finish(PackageRow row, string name, string validation, bool? exportable = null)
        {
            row.Name = name;
            row.Validation = validation;
            row.Exportable = exportable ?? validation is "confirmed" or "pattern";
            if (seen.ContainsKey(name) && row.Exportable)
            {
                (row.Status, row.Validation, row.Exportable) = ("duplicate", "invalid", false);
                row.Messages = [.. row.Messages, "Same name as another role in the package."];
            }
            else if (row.Exportable) seen[name] = row.Role;
        }

        foreach (var item in items)
        {
            if (item.Source == "release")
            {
                var releaseName = RoleNames.Normalize(item.Role);
                var release = new PackageRow { Role = item.Role, Description = catalogue.GetValueOrDefault(item.Role, ""), Source = "release" };
                rows.Add(release);
                if (!releaseRoles.Contains(releaseName)) (release.Status, release.Messages) = ("unknown_role", ["Not in the imported User Access data."]);
                else if (NameError(releaseName) is { } error) (release.Status, release.Validation, release.Messages) = ("invalid", "invalid", [error]);
                else
                {
                    release.Messages.Add("Release role names are kept exactly; no suffix is applied.");
                    Finish(release, releaseName, "confirmed");
                }
                continue;
            }
            var over = NormalizeSuffix(item.Suffix);
            var eligible = SuffixKind(item.Role, known) is not null;
            var suffix = eligible ? (over.Length > 0 ? over : fallback) : "";
            var row = new PackageRow
            {
                Role = item.Role, Description = catalogue.GetValueOrDefault(item.Role, ""), Suffix = suffix,
                SuffixSource = eligible ? (over.Length > 0 ? "override" : fallback.Length > 0 ? "default" : "none") : "none",
                SuffixEligible = eligible, SuffixNote = eligible ? null : ExactNote, Source = "catalogue",
            };
            rows.Add(row);
            if (!catalogue.ContainsKey(item.Role)) { (row.Status, row.Messages) = ("unknown_role", ["Not in the imported catalogue; re-import or remove it."]); continue; }
            if (eligible && suffix.Length == 0) { (row.Status, row.Messages) = ("needs_suffix", ["Needs suffix: set a package default suffix or a suffix for this role."]); continue; }
            if ((eligible ? SuffixError(suffix) : null) is { } suffixProblem) { (row.Status, row.Validation, row.Messages) = ("invalid", "invalid", [suffixProblem]); continue; }
            var (name, _, message) = Propose(item.Role, suffix, known);
            if (name is null) { (row.Status, row.Messages) = ("ambiguous", [message!]); continue; }
            if (NameError(name) is { } nameProblem) { (row.Status, row.Validation, row.Messages) = ("invalid", "invalid", [nameProblem]); continue; }
            var match = matcher.Match(name);
            row.Catalogue = match;
            if (explicitNames.Contains(name)) Finish(row, name, "confirmed");
            else if (match.Status is "exact" or "wildcard")
            {
                row.Messages.Add("Matches a catalogue pattern; the exact role is not in the imported data.");
                Finish(row, name, "pattern");
            }
            else
            {
                row.Messages.Add("Not found in imported roles, assignments or catalogue patterns. Check it in SAP before use.");
                Finish(row, name, "attention", exportable: true);
            }
        }
        return rows;
    }

    /// <summary>Unique exportable names in deterministic order: (name, description, suffix, validation label); the first row of a name wins.</summary>
    public static List<string[]> CsvRows(IEnumerable<PackageRow> rows)
    {
        var unique = new Dictionary<string, string[]>(StringComparer.Ordinal);
        foreach (var row in rows.Reverse())
            if (!string.IsNullOrEmpty(row.Name) && row.Exportable) unique[row.Name] = [row.Name, row.Description, row.Suffix, ValidationLabel[row.Validation]];
        return [.. unique.Values.OrderBy(v => v[0].PyCasefold(), StringComparer.Ordinal).ThenBy(v => v[0], StringComparer.Ordinal)];
    }
}
