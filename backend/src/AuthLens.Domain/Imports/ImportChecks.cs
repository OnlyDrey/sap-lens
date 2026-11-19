using System.Globalization;

namespace AuthLens.Domain.Imports;

public sealed record ImportCheckSettings(bool Enabled = true, int MaxDropPercent = 30, int MinPreviousRecords = 20);

public sealed record Anomaly(string Rule, string Metric, string? Group, int Old, int New, double? Percent, string Message);

public sealed record ImportEvaluation(bool Suspicious, IReadOnlyList<Anomaly> Anomalies, IReadOnlyDictionary<string, int> Old, IReadOnlyDictionary<string, int> New);

public sealed record DiffCounts(int Added, int Removed, int Modified, int Unchanged, int AmbiguousIdentifiers);

/// <summary>Port of import_checks.evaluate (suspicious-change detection against the active revision of the same source) and the counts
/// of csv_lifecycle.diff_records (<see cref="RecordDiff"/>).</summary>
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

    private static string Norm(string? value) => (value ?? "").Trim().PyCasefold();

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

    /// <summary>The counts of csv_lifecycle.diff_records (see <see cref="RecordDiff"/>, which also reports the changed records).</summary>
    public static DiffCounts Diff(string source, IReadOnlyList<IReadOnlyDictionary<string, string>> before, IReadOnlyList<IReadOnlyDictionary<string, string>> after) =>
        RecordDiff.Compare(source, before, after, includeChanges: false).Counts;
}
