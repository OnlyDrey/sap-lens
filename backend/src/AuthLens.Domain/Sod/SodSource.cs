using AuthLens.Domain.Csv;
using AuthLens.Domain.Json;
using AuthLens.Domain.Roles;

namespace AuthLens.Domain.Sod;

public sealed class SodDataset
{
    public required List<Dictionary<string, object?>> Records { get; init; }
    /// <summary>Risk definitions as canonical dictionaries (the same shape and keys as the Python store, so evidence versions match).</summary>
    public required List<Dictionary<string, object?>> Risks { get; init; }
    public required string ContentHash { get; init; }
    /// <summary>v1 report['metadata']: optional descriptive values per risk, activity and source, present only when a mapped optional column exists.</summary>
    public SodMetadata? Metadata { get; init; }
    public required List<string> Warnings { get; init; }
    public int DuplicateRows { get; init; }
}

/// <summary>Port of sod_import.build_sod: validated, canonical SoD source; policy v1 evaluates two-sided TYPE S risks only.</summary>
public static class SodSource
{
    public const string EvaluationPolicy = "sod-two-sided-v1";

    public static SodDataset Build(IEnumerable<IReadOnlyDictionary<string, string>> records, IEnumerable<string>? reportWarnings = null)
    {
        var headers = CsvSpec.SodHeaders;
        var canonical = new SortedDictionary<string, Dictionary<string, string>>(StringComparer.Ordinal);
        var keyOrder = new Dictionary<string, string[]>(StringComparer.Ordinal);
        var risks = new Dictionary<string, (string[] Definition, SortedDictionary<string, string> A1, SortedDictionary<string, string> A2)>(StringComparer.Ordinal);
        int duplicates = 0, missingText = 0, index = 0;
        var metadata = new SodMetadataCollector();
        foreach (var raw in records)
        {
            metadata.Collect(raw);
            if (index++ >= CsvImport.MaxRows) throw new DomainValidationException("SoD exceeds the one-million-record safety limit.");
            var row = headers.ToDictionary(h => h, h => raw.TryGetValue(h, out var v) ? v.Trim() : throw new DomainValidationException("SoD records must contain exactly the documented fields."));
            if (row.Values.Any(v => v.Length > 4096 || v.Contains('\0'))) throw new DomainValidationException("SoD contains invalid or oversized fields.");
            if (CsvSpec.Sod.IdentifierFields.Any(f => row[f].Length > 512)) throw new DomainValidationException("A SoD identifier is too long.");
            if (headers.Where(h => h != "TTEXT").Any(h => row[h].Length == 0)) throw new DomainValidationException("A SoD record is missing a required value.");
            var slot = row["ACTIVITY_SLOT"];
            if (slot is not ("ACTVT1" or "ACTVT2") || row["ACTIVITY"] != row[slot])
                throw new DomainValidationException("SoD ACTIVITY_SLOT must be ACTVT1 or ACTVT2 and reference the matching ACTIVITY.");
            if (row["ACTVT1"] == row["ACTVT2"]) throw new DomainValidationException("SoD requires two distinct activity definitions.");
            var tuple = headers.Select(h => row[h]).ToArray();
            var key = TupleKey(tuple);
            if (canonical.ContainsKey(key)) { duplicates++; continue; }
            canonical[key] = row;
            keyOrder[key] = tuple;
            var definition = new[] { row["CRITICITY"], row["TYPE"], row["TEXT"], row["ACTVT1"], row["ACTVT2"] };
            if (!risks.TryGetValue(row["RISK"], out var entry))
                risks[row["RISK"]] = entry = (definition, new SortedDictionary<string, string>(StringComparer.Ordinal), new SortedDictionary<string, string>(StringComparer.Ordinal));
            if (!entry.Definition.SequenceEqual(definition)) throw new DomainValidationException("SoD contains conflicting definitions for the same risk.");
            var side = slot == "ACTVT1" ? entry.A1 : entry.A2;
            var activityKey = TupleKey([row["ACTIVITY"], row["TCODE"]]);
            if (side.TryGetValue(activityKey, out var previous) && previous != row["TTEXT"])
                throw new DomainValidationException("SoD contains conflicting descriptions for the same activity transaction.");
            side[activityKey] = row["TTEXT"];
            if (row["TTEXT"].Length == 0) missingText++;
        }
        if (canonical.Count == 0) throw new DomainValidationException("An empty SoD dataset cannot replace the current source.");
        var definitions = new List<Dictionary<string, object?>>();
        foreach (var (riskId, entry) in risks.OrderBy(p => p.Key, StringComparer.Ordinal))
        {
            if (entry.A1.Count == 0 || entry.A2.Count == 0) throw new DomainValidationException("Every SoD risk requires transaction mappings for both activity sides.");
            var supported = entry.Definition[1] == "S";
            definitions.Add(new Dictionary<string, object?>
            {
                ["risk_id"] = riskId, ["criticality"] = entry.Definition[0], ["risk_type"] = entry.Definition[1], ["source_text"] = entry.Definition[2],
                ["activity1"] = entry.Definition[3], ["activity2"] = entry.Definition[4],
                ["activities"] = new Dictionary<string, object?> { ["ACTVT1"] = Mappings(entry.A1), ["ACTVT2"] = Mappings(entry.A2) },
                ["supported"] = supported, ["evaluation_policy"] = supported ? EvaluationPolicy : null,
            });
        }
        var rows = canonical.Values.Select(r => (Dictionary<string, object?>)r.ToDictionary(p => p.Key, p => (object?)p.Value)).ToList();
        var warnings = new List<string>(reportWarnings ?? []);
        warnings.AddRange(metadata.Warnings());
        if (duplicates > 0) warnings.Add($"{duplicates} identical duplicate SoD records were deduplicated.");
        if (missingText > 0) warnings.Add($"{missingText} SoD transaction mappings have no TTEXT description.");
        var unsupported = definitions.Count(d => !(bool)d["supported"]!);
        if (unsupported > 0) warnings.Add($"{unsupported} SoD risk definitions have unsupported TYPE values and will not be evaluated.");
        var overlaps = definitions.Count(d => Codes(d, "ACTVT1").Overlaps(Codes(d, "ACTVT2")));
        if (overlaps > 0) warnings.Add($"{overlaps} SoD risk definitions contain overlapping transaction codes between activity sides; definition overlap needs review.");
        var imported = metadata.Result();
        // Imported descriptions belong to the content identity only when the source provides them, so files without optional columns keep their hash.
        var hash = imported is null ? CanonicalJson.Sha256(rows) : CanonicalJson.Sha256(new Dictionary<string, object?> { ["records"] = rows, ["metadata"] = imported.ToJson() });
        return new SodDataset { Records = rows, Risks = definitions, ContentHash = hash, Metadata = imported, Warnings = warnings.Distinct().ToList(), DuplicateRows = duplicates };
    }

    /// <summary>Sort key with the ordering of Python tuple comparison over strings: element by element, ordinal.</summary>
    private static string TupleKey(IEnumerable<string> values) => string.Join('\u0000', values);

    private static List<object?> Mappings(SortedDictionary<string, string> side) =>
        side.Select(p => { var parts = p.Key.Split('\u0000'); return (object?)new Dictionary<string, object?> { ["activity"] = parts[0], ["tcode"] = parts[1], ["ttext"] = p.Value }; }).ToList();

    public static HashSet<string> Codes(Dictionary<string, object?> risk, string slot) =>
        ((List<object?>)((Dictionary<string, object?>)risk["activities"]!)[slot]!).Select(m => (string)((Dictionary<string, object?>)m!)["tcode"]!).ToHashSet(StringComparer.Ordinal);
}
