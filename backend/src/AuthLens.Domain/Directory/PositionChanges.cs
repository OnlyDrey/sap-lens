using System.Globalization;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;

namespace AuthLens.Domain.Directory;

/// <summary>MIG-003, port of position_changes.py: Department, Job Title and Manager changes between two successive validated Employee Directory
/// snapshots. Pure detection; a change is a review prompt, never a finding about access. Manager-only differences are a separate signal; missing
/// values, formatting-only differences, ambiguous (duplicate e-mail) identities and suspiciously incomplete replacements never create a change.</summary>
public static partial class PositionChanges
{
    public const int MaxEvents = 5000, RecentDays = 90;
    private const double MinCompleteShare = 0.5;
    private static readonly (string Source, string Label)[] Fields = [("Department", "department"), ("Title", "title")];

    [GeneratedRegex(@"\s+")] private static partial Regex Spaces();

    /// <summary>normalize_text: NFKC, collapsed whitespace, trimmed, str.casefold().</summary>
    public static string NormalizeText(string? value) => Text.PythonText.Casefold(Spaces().Replace(Text.PythonText.Nfkc(value), " ").Trim());

    private static string Get(IReadOnlyDictionary<string, string> row, string field) => row.GetValueOrDefault(field, "") ?? "";

    private static Dictionary<string, IReadOnlyDictionary<string, string>> UniqueByMail(IReadOnlyList<IReadOnlyDictionary<string, string>> rows)
    {
        var seen = new Dictionary<string, IReadOnlyDictionary<string, string>>();
        var duplicates = new HashSet<string>();
        foreach (var row in rows)
        {
            var key = NormalizeText(Get(row, "Mail"));
            if (key.Length == 0) continue;
            if (!seen.TryAdd(key, row)) { duplicates.Add(key); seen[key] = row; }
        }
        return seen.Where(p => !duplicates.Contains(p.Key)).ToDictionary(p => p.Key, p => p.Value);
    }

    private static double BlankShare(IReadOnlyList<IReadOnlyDictionary<string, string>> rows, string field) =>
        rows.Count(r => Get(r, field).Trim().Length == 0) / (double)Math.Max(1, rows.Count);

    private static string Sha(string text) => Json.Digests.Text(text);

    /// <summary>detect: (events, notices) for two directories.</summary>
    public static (List<JsonObject> Events, List<string> Notices) Detect(EmployeeDirectory? previous, EmployeeDirectory? current, string detectedAt)
    {
        if (previous is null || current is null || previous.Digest == current.Digest) return ([], []);
        if (current.Rows.Count < MinCompleteShare * previous.Rows.Count)
            return ([], ["The replacement directory has far fewer records than the previous one, so no position changes were derived from it."]);
        var fields = new List<(string Source, string Label)>();
        var notices = new List<string>();
        foreach (var (source, label) in Fields)
            if (BlankShare(current.Rows, source) - BlankShare(previous.Rows, source) > 0.5)
                notices.Add($"The replacement directory has mostly empty {label} values, so {label} changes were not derived from it.");
            else fields.Add((source, label));
        var old = UniqueByMail(previous.Rows);
        var events = new List<JsonObject>();
        foreach (var (key, record) in UniqueByMail(current.Rows))
        {
            if (!old.TryGetValue(key, out var before)) continue;
            var changed = fields.Where(f => Get(before, f.Source).Trim().Length > 0 && Get(record, f.Source).Trim().Length > 0
                && NormalizeText(Get(before, f.Source)) != NormalizeText(Get(record, f.Source))).Select(f => f.Label).ToList();
            if (changed.Count == 0) continue;
            events.Add(new JsonObject
            {
                ["id"] = Sha($"{key}|{current.Digest}"), ["key"] = key, ["email"] = Get(record, "Mail").Trim(), ["name"] = Get(record, "Name").Trim(),
                ["ad_username"] = Get(record, "SamAccountName").Trim(), ["fields"] = new JsonArray([.. changed.Select(c => (JsonNode)c)]),
                ["previous_department"] = Get(before, "Department").Trim(), ["current_department"] = Get(record, "Department").Trim(),
                ["previous_title"] = Get(before, "Title").Trim(), ["current_title"] = Get(record, "Title").Trim(),
                ["detected_at"] = detectedAt, ["source_generation"] = current.Digest, ["previous_generation"] = previous.Digest,
                ["previous_imported_at"] = previous.ImportedAt ?? "", ["current_imported_at"] = current.ImportedAt ?? "",
            });
        }
        return (events.OrderBy(e => (string)e["key"]!, StringComparer.Ordinal).ToList(), notices);
    }

    /// <summary>manager_key: mail, then account name, then DN; a name alone never identifies a manager.</summary>
    public static string ManagerKey(IReadOnlyDictionary<string, string> row)
    {
        foreach (var field in new[] { "ManagerMail", "ManagerSamAccountName", "ManagerDN" })
            if (NormalizeText(Get(row, field)) is { Length: > 0 } value) return value;
        return "";
    }

    public static List<JsonObject> DetectManagers(EmployeeDirectory? previous, EmployeeDirectory? current, string detectedAt)
    {
        if (previous is null || current is null || previous.Digest == current.Digest || current.Rows.Count < MinCompleteShare * previous.Rows.Count) return [];
        var old = UniqueByMail(previous.Rows);
        var events = new List<JsonObject>();
        foreach (var (key, record) in UniqueByMail(current.Rows))
        {
            if (!old.TryGetValue(key, out var before) || ManagerKey(before).Length == 0 || ManagerKey(record).Length == 0 || ManagerKey(before) == ManagerKey(record)) continue;
            events.Add(new JsonObject
            {
                ["id"] = Sha($"{key}|{current.Digest}|manager"), ["key"] = key, ["email"] = Get(record, "Mail").Trim(), ["name"] = Get(record, "Name").Trim(),
                ["previous_manager"] = Get(before, "ManagerName").Trim(), ["previous_manager_email"] = Get(before, "ManagerMail").Trim(),
                ["current_manager"] = Get(record, "ManagerName").Trim(), ["current_manager_email"] = Get(record, "ManagerMail").Trim(),
                ["detected_at"] = detectedAt, ["source_generation"] = current.Digest, ["previous_generation"] = previous.Digest,
            });
        }
        return events.OrderBy(e => (string)e["key"]!, StringComparer.Ordinal).ToList();
    }

    /// <summary>latest_recent / latest_managers: the newest change per employee e-mail within the last 90 days (stable on clock ties).</summary>
    public static Dictionary<string, JsonObject> LatestRecent(IEnumerable<JsonObject> events, DateOnly today)
    {
        var cutoff = new DateTimeOffset(today.ToDateTime(TimeOnly.MinValue), TimeSpan.Zero).AddDays(-RecentDays);
        var latest = new Dictionary<string, JsonObject>();
        foreach (var item in events.OrderBy(e => DateTimeOffset.Parse((string)e["detected_at"]!, CultureInfo.InvariantCulture)))
            if (DateTimeOffset.Parse((string)item["detected_at"]!, CultureInfo.InvariantCulture) >= cutoff) latest[(string)item["key"]!] = item;
        return latest;
    }
}
