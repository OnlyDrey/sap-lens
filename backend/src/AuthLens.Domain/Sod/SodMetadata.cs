using AuthLens.Domain.Csv;

namespace AuthLens.Domain.Sod;

/// <summary>Optional descriptive SoD values (v1 report['metadata']). They never change a record, a risk definition, a duplicate or a detection.</summary>
public sealed record SodMetadata(
    SortedDictionary<string, SortedDictionary<string, string>> Risks,
    SortedDictionary<string, SortedDictionary<string, string>> Activities,
    SortedDictionary<string, List<string>> Source)
{
    public Dictionary<string, object?> ToJson() => new()
    {
        ["risks"] = Risks.ToDictionary(p => p.Key, p => (object?)p.Value.ToDictionary(v => v.Key, v => (object?)v.Value)),
        ["activities"] = Activities.ToDictionary(p => p.Key, p => (object?)p.Value.ToDictionary(v => v.Key, v => (object?)v.Value)),
        ["source"] = Source.ToDictionary(p => p.Key, p => (object?)p.Value.Cast<object?>().ToList()),
    };
}

/// <summary>Port of SodCsvImport._collect/_clean/_keep: the first value per risk or activity field wins and a different later value is a reported
/// conflict; values longer than 4096 characters or with control characters (other than tab and line breaks) are ignored and reported; at most 20
/// distinct values per source field. Collected from every record in file order, before duplicate removal, as v1 does.</summary>
public sealed class SodMetadataCollector
{
    public static readonly IReadOnlyDictionary<string, string> RiskFields = new Dictionary<string, string>
    { ["RISK_NAME"] = "name", ["RISK_DESCRIPTION"] = "description", ["RISK_IMPACT"] = "impact", ["BUSINESS_PROCESS"] = "business_process" };
    public static readonly IReadOnlyDictionary<string, string> ActivityFields = new Dictionary<string, string>
    { ["ACTIVITY_NAME"] = "name", ["ACTIVITY_DESCRIPTION"] = "description", ["ACTIVITY_TYPE"] = "type", ["ACTIVITY_BUSINESS_PROCESS"] = "business_process" };
    public static readonly IReadOnlyDictionary<string, string> SourceFields = new Dictionary<string, string>
    { ["RULESET_ID"] = "ruleset_ids", ["RULESET_VERSION"] = "ruleset_versions", ["SOURCE_SYSTEM"] = "source_systems", ["LANGUAGE"] = "languages", ["LAST_CHANGED"] = "last_changed" };
    public const int MaxValue = 4096, MaxSourceValues = 20;

    private readonly SortedDictionary<string, SortedDictionary<string, string>> _risks = new(StringComparer.Ordinal);
    private readonly SortedDictionary<string, SortedDictionary<string, string>> _activities = new(StringComparer.Ordinal);
    private readonly Dictionary<string, HashSet<string>> _source = SourceFields.Keys.ToDictionary(k => k, _ => new HashSet<string>(StringComparer.Ordinal));
    private bool _detected;
    private int _conflicts, _ignored;

    private string Clean(string? value)
    {
        var text = (value ?? "").Trim();
        if (text.Length == 0) return "";
        if (text.EnumerateRunes().Count() > MaxValue || text.Any(c => c < 32 && c is not ('\n' or '\r' or '\t'))) { _ignored++; return ""; }
        return text;
    }

    private void Keep(SortedDictionary<string, SortedDictionary<string, string>> store, string key, string field, string? value)
    {
        var text = Clean(value);
        if (text.Length == 0) return;
        if (!store.TryGetValue(key, out var entry)) store[key] = entry = new SortedDictionary<string, string>(StringComparer.Ordinal);
        if (entry.TryGetValue(field, out var existing)) { if (existing != text) _conflicts++; }
        else entry[field] = text;
    }

    public void Collect(IReadOnlyDictionary<string, string> raw)
    {
        if (!CsvSpec.SodOptional.Any(raw.ContainsKey)) return;
        _detected = true;
        var risk = raw.GetValueOrDefault("RISK", "").Trim();
        var activity = raw.GetValueOrDefault("ACTIVITY", "").Trim();
        foreach (var (column, field) in RiskFields) if (raw.TryGetValue(column, out var v)) Keep(_risks, risk, field, v);
        foreach (var (column, field) in ActivityFields) if (raw.TryGetValue(column, out var v)) Keep(_activities, activity, field, v);
        foreach (var column in SourceFields.Keys)
            if (raw.TryGetValue(column, out var v) && Clean(v) is { Length: > 0 } text && _source[column].Count < MaxSourceValues) _source[column].Add(text);
    }

    public IEnumerable<string> Warnings()
    {
        if (_conflicts > 0) yield return $"{_conflicts} optional SoD metadata values conflict for the same risk or activity; the first value was kept.";
        if (_ignored > 0) yield return $"{_ignored} optional SoD metadata values were ignored (longer than {MaxValue} characters or containing control characters).";
    }

    public SodMetadata? Result() => !_detected ? null : new SodMetadata(_risks, _activities,
        new SortedDictionary<string, List<string>>(_source.Where(p => p.Value.Count > 0).ToDictionary(p => SourceFields[p.Key], p => p.Value.Order(StringComparer.Ordinal).ToList()), StringComparer.Ordinal));
}
