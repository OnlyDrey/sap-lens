using System.Globalization;

namespace SapLens.Domain.Imports;

public sealed record ImportCheckSettings(bool Enabled = true, int MaxDropPercent = 30, int MinPreviousRecords = 20);

public sealed record Anomaly(string Rule, string Metric, string? Group, int Old, int New, double? Percent, string Message);

public sealed record ImportEvaluation(bool Suspicious, IReadOnlyList<Anomaly> Anomalies, IReadOnlyDictionary<string, int> Old, IReadOnlyDictionary<string, int> New);

public sealed record DiffCounts(int Added, int Removed, int Modified, int Unchanged, int AmbiguousIdentifiers);

/// <summary>Port of import_checks.evaluate (suspicious-change detection against the active revision of the same source) and the counting part
/// of csv_lifecycle.diff_records (multiset comparison; only one remaining old/new observation per identifier is a modification).</summary>
public static class ImportChecks
{
    private static readonly Dictionary<string, ((string Label, string Field)[] Entities, (string Field, string Label)? Groups)> Spec = new()
    {
        ["roles"] = ([("role catalogue entries", "AGR_NAME"), ("transactions", "TCODE")], ("FUNCTION_KEY", "SAP module area")),
        ["users"] = ([("SAP users", "USERNAME"), ("assigned roles", "ROLE_NAME")], ("USER_GROUP", "SAP user group")),
        ["sod"] = ([("risks", "RISK")], null),
        ["employees"] = ([("directory accounts", "SamAccountName")], ("Department", "department")),
    };
    private const int GroupMinRows = 5;

    private static string Norm(string? value) => (value ?? "").Trim().ToLowerInvariant();

    public static Dictionary<string, int> Metrics(string source, IReadOnlyList<IReadOnlyDictionary<string, string>> rows)
    {
        var result = new Dictionary<string, int> { ["records"] = rows.Count };
        foreach (var (label, field) in Spec[source].Entities)
            result[label] = rows.Select(r => Norm(r.GetValueOrDefault(field))).Where(v => v.Length > 0).Distinct().Count();
        return result;
    }

    public static ImportEvaluation Evaluate(string source, IReadOnlyList<IReadOnlyDictionary<string, string>> before, IReadOnlyList<IReadOnlyDictionary<string, string>> after, ImportCheckSettings checks)
    {
        var old = Metrics(source, before);
        var current = Metrics(source, after);
        var anomalies = new List<Anomaly>();
        if (checks.Enabled && before.Count >= checks.MinPreviousRecords)
        {
            foreach (var (label, previous) in old)
            {
                var now = current[label];
                if (previous > 0 && now < previous * (1 - checks.MaxDropPercent / 100.0))
                {
                    var percent = Math.Round(100.0 * (previous - now) / previous, 1, MidpointRounding.ToEven);
                    anomalies.Add(new Anomaly("drop", label, null, previous, now, percent,
                        string.Create(CultureInfo.InvariantCulture, $"{label} fell from {previous:N0} to {now:N0} ({percent.ToString("0.0", CultureInfo.InvariantCulture)} %, limit {checks.MaxDropPercent} %).")));
                }
            }
            if (Spec[source].Groups is { } groups)
            {
                var was = before.Select(r => Norm(r.GetValueOrDefault(groups.Field))).Where(v => v.Length > 0).GroupBy(v => v).ToDictionary(g => g.Key, g => g.Count());
                var isNow = after.Select(r => Norm(r.GetValueOrDefault(groups.Field))).Where(v => v.Length > 0).ToHashSet();
                var floor = Math.Max(GroupMinRows, before.Count / 100);
                foreach (var name in was.Where(p => !isNow.Contains(p.Key) && p.Value >= floor).Select(p => p.Key).Order(StringComparer.Ordinal))
                    anomalies.Add(new Anomaly("group_missing", groups.Label, name, was[name], 0, null,
                        string.Create(CultureInfo.InvariantCulture, $"All {was[name]:N0} records of {groups.Label} \"{name}\" are missing from the new file.")));
            }
        }
        return new ImportEvaluation(anomalies.Count > 0, anomalies, old, current);
    }

    public static string[] RecordKey(string source, IReadOnlyDictionary<string, string> row)
    {
        if (source == "employees")
        {
            // Email is deliberately not a record identity; rows without DN or account name are add/remove evidence, never guessed modifications.
            var dn = row.GetValueOrDefault("DistinguishedName", "").Trim();
            var sam = row.GetValueOrDefault("SamAccountName", "").Trim();
            return dn.Length > 0 ? ["dn", dn.ToUpperInvariant().ToLowerInvariant()] : sam.Length > 0 ? ["sam", sam.ToUpperInvariant().ToLowerInvariant()]
                : ["none", string.Join('\u001e', row.OrderBy(p => p.Key, StringComparer.Ordinal).Select(p => p.Key + "\u001f" + p.Value))];
        }
        string[] fields = source switch
        {
            "sod" => ["RISK", "ACTIVITY_SLOT", "ACTIVITY", "TCODE"],
            "roles" => ["AGR_NAME", "CHILD_AGR", "PARENT_AGR", "Effective_Role", "TCODE"],
            _ => ["USERNAME", "ROLE_NAME", "USER_GROUP"],
        };
        return fields.Select(f => source == "sod" ? row.GetValueOrDefault(f, "") : row.GetValueOrDefault(f, "").Trim().ToUpperInvariant()).ToArray();
    }

    public static DiffCounts Diff(string source, IReadOnlyList<IReadOnlyDictionary<string, string>> before, IReadOnlyList<IReadOnlyDictionary<string, string>> after)
    {
        static string Identity(IReadOnlyDictionary<string, string> row) => string.Join('\u001e', row.Where(p => p.Key != "id").OrderBy(p => p.Key, StringComparer.Ordinal).Select(p => p.Key + "\u001f" + p.Value));
        var oldCounts = before.GroupBy(Identity).ToDictionary(g => g.Key, g => g.Count());
        var newCounts = after.GroupBy(Identity).ToDictionary(g => g.Key, g => g.Count());
        var unchanged = oldCounts.Sum(p => Math.Min(p.Value, newCounts.GetValueOrDefault(p.Key)));
        IEnumerable<IReadOnlyDictionary<string, string>> Leftovers(IReadOnlyList<IReadOnlyDictionary<string, string>> rows, Dictionary<string, int> mine, Dictionary<string, int> other)
        {
            var remaining = mine.ToDictionary(p => p.Key, p => p.Value - Math.Min(p.Value, other.GetValueOrDefault(p.Key)));
            foreach (var row in rows)
            {
                var id = Identity(row);
                if (remaining[id] > 0) { remaining[id]--; yield return row; }
            }
        }
        var oldGroups = Leftovers(before, oldCounts, newCounts).GroupBy(r => string.Join('\u001f', RecordKey(source, r))).ToDictionary(g => g.Key, g => g.Count());
        var newGroups = Leftovers(after, newCounts, oldCounts).GroupBy(r => string.Join('\u001f', RecordKey(source, r))).ToDictionary(g => g.Key, g => g.Count());
        int added = 0, removed = 0, modified = 0, ambiguous = 0;
        foreach (var key in oldGroups.Keys.Union(newGroups.Keys))
        {
            var o = oldGroups.GetValueOrDefault(key); var n = newGroups.GetValueOrDefault(key);
            if (o == 1 && n == 1) { modified++; continue; }
            if (o > 0 && n > 0) ambiguous++;
            removed += o; added += n;
        }
        return new DiffCounts(added, removed, modified, unchanged, ambiguous);
    }
}
