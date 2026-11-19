using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;
using Microsoft.EntityFrameworkCore;
using AuthLens.Persistence;

namespace AuthLens.Cli;

/// <summary>Imports v1 private SoD annotation files (sod-catalogue.json, optionally sod-reference.json) into the .NET SoD documents. The files are
/// validated against the v1 storage contract first (CatalogueStorage / Library: field names, types, lengths, fingerprints); nothing is converted,
/// so observed and reviewed definition fingerprints keep their meaning. Both documents are written in one transaction, and existing .NET
/// documents are never overwritten. The server must have been started once on this data directory (current schema).</summary>
public static partial class ImportV1Sod
{
    [GeneratedRegex("^[a-f0-9]{64}$")] private static partial Regex Hex64();
    [GeneratedRegex("^(?:[a-f0-9]{64})?$")] private static partial Regex OptionalHex64();
    [GeneratedRegex("^[A-Za-z0-9_:-]{1,128}$")] private static partial Regex ReferenceId();
    [GeneratedRegex("^#[0-9a-f]{6}$")] private static partial Regex Color();

    private static readonly Dictionary<string, int> RiskText = new()
    {
        ["display_name"] = 200, ["business_category"] = 120, ["explanation_en"] = 12000, ["explanation_no"] = 12000, ["consequence_en"] = 8000, ["consequence_no"] = 8000,
        ["mitigating_controls_en"] = 12000, ["mitigating_controls_no"] = 12000, ["review_guidance_en"] = 8000, ["review_guidance_no"] = 8000, ["notes"] = 8000, ["color"] = 7,
    };
    private static readonly Dictionary<string, int> ActivityText = new()
    { ["display_name"] = 200, ["business_category"] = 120, ["explanation_en"] = 12000, ["review_guidance_en"] = 8000, ["notes"] = 8000, ["color"] = 7 };

    public static void ValidateMetadata(JsonObject metadata, bool risk)
    {
        var text = risk ? RiskText : ActivityText;
        foreach (var (key, value) in metadata)
        {
            if (risk && key == "enabled") { if (value?.GetValueKind() is not (JsonValueKind.True or JsonValueKind.False)) throw new InvalidDataException("enabled must be a boolean."); continue; }
            if (risk && key == "description_review_status") { if ((string?)value is not ("Needs description review" or "Reviewed")) throw new InvalidDataException("Unsupported description review status."); continue; }
            if (!text.TryGetValue(key, out var max)) throw new InvalidDataException($"Unknown metadata field '{key}'.");
            if (value?.GetValueKind() != JsonValueKind.String) throw new InvalidDataException($"Metadata field '{key}' must be text.");
            var s = value.GetValue<string>();
            if (s.EnumerateRunes().Count() > max || s.Any(c => c < 32 && c is not ('\n' or '\r' or '\t'))) throw new InvalidDataException($"Metadata field '{key}' is too long or contains control characters.");
            if (key == "color" && s.Length > 0 && !Color().IsMatch(s)) throw new InvalidDataException("Color must be empty or a #rrggbb value.");
        }
    }

    private static void Key(string key) { if (key.Length is 0 or > 512 || key.Any(c => c < 32)) throw new InvalidDataException("Invalid risk or activity identifier."); }

    public static JsonObject ValidateCatalogue(JsonObject storage)
    {
        if ((int?)storage["version"] != 1 || storage["revision"]?.GetValueKind() != JsonValueKind.Number || (int)storage["revision"]! < 0) throw new InvalidDataException("Unsupported catalogue version or revision.");
        if (storage.Any(p => p.Key is not ("version" or "revision" or "entries" or "activities"))) throw new InvalidDataException("Unknown catalogue field.");
        var entries = storage["entries"] as JsonObject ?? throw new InvalidDataException("entries must be an object.");
        var activities = storage["activities"] as JsonObject ?? new JsonObject();
        storage["activities"] = activities;
        if (entries.Count > 5000 || activities.Count > 5000) throw new InvalidDataException("Catalogue exceeds 5000 entries.");
        foreach (var (key, node) in entries)
        {
            Key(key);
            var entry = node as JsonObject ?? throw new InvalidDataException("Invalid catalogue entry.");
            if (entry.Any(p => p.Key is not ("metadata" or "observed_definition" or "reviewed_definition" or "modified"))) throw new InvalidDataException("Unknown catalogue entry field.");
            ValidateMetadata(entry["metadata"] as JsonObject ?? throw new InvalidDataException("Missing metadata."), risk: true);
            if ((string?)entry["observed_definition"] is not { } observed || !Hex64().IsMatch(observed)) throw new InvalidDataException("Invalid observed_definition fingerprint.");
            if (entry["reviewed_definition"] is { } reviewed && !Hex64().IsMatch((string?)reviewed ?? "")) throw new InvalidDataException("Invalid reviewed_definition fingerprint.");
            if (!DateTimeOffset.TryParse((string?)entry["modified"], out _)) throw new InvalidDataException("Invalid modified timestamp.");
        }
        foreach (var (key, node) in activities)
        {
            Key(key);
            var entry = node as JsonObject ?? throw new InvalidDataException("Invalid activity entry.");
            ValidateMetadata(entry["metadata"] as JsonObject ?? throw new InvalidDataException("Missing activity metadata."), risk: false);
            if (!DateTimeOffset.TryParse((string?)entry["modified"], out _)) throw new InvalidDataException("Invalid modified timestamp.");
        }
        return storage;
    }

    public static JsonObject ValidateReference(JsonObject library)
    {
        if ((int?)library["version"] != 1 || (string?)library["origin"] is not ("custom" or "bundled") || !OptionalHex64().IsMatch((string?)library["digest"] ?? "")) throw new InvalidDataException("Unsupported reference library.");
        foreach (var (field, risk) in new[] { ("risks", true), ("activities", false) })
            foreach (var (key, node) in library[field] as JsonObject ?? [])
            {
                if (!ReferenceId().IsMatch(key)) throw new InvalidDataException("Invalid reference identifier.");
                var record = node as JsonObject ?? throw new InvalidDataException("Invalid reference record.");
                if (!risk && record.Any(p => p.Key is "consequence_en" or "mitigating_controls_en")) throw new InvalidDataException("Invalid reference activity field.");
                ValidateMetadata(record, risk);
            }
        return library;
    }

    public static async Task<int> RunAsync(string data, string cataloguePath, string? referencePath)
    {
        try
        {
            var catalogue = ValidateCatalogue(JsonNode.Parse(await File.ReadAllBytesAsync(cataloguePath)) as JsonObject ?? throw new InvalidDataException("Not a JSON object."));
            var reference = referencePath is null ? null : ValidateReference(JsonNode.Parse(await File.ReadAllBytesAsync(referencePath)) as JsonObject ?? throw new InvalidDataException("Not a JSON object."));
            var (writer, _) = DbCommands.Open(data);
            await writer.WriteAsync(async (db, ct) =>
            {
                if (await db.SodDocuments.AnyAsync(d => d.Name == "catalogue" || reference != null && d.Name == "reference", ct))
                    throw new InvalidOperationException("SoD annotations already exist in this data directory; nothing was imported.");
                db.SodDocuments.Add(new SodDocument { Name = "catalogue", Revision = (int)catalogue["revision"]!, Json = catalogue.ToJsonString(), UpdatedUtc = DateTime.UtcNow, UpdatedBy = "v1-import" });
                if (reference is not null)
                    db.SodDocuments.Add(new SodDocument { Name = "reference", Revision = (int?)reference["revision"] ?? 0, Json = reference.ToJsonString(), UpdatedUtc = DateTime.UtcNow, UpdatedBy = "v1-import" });
                return true;
            });
            Console.WriteLine(JsonSerializer.Serialize(new { imported = true, risks = catalogue["entries"]!.AsObject().Count, activities = catalogue["activities"]!.AsObject().Count, reference = reference is not null }));
            return 0;
        }
        catch (Exception error) when (error is InvalidDataException or JsonException or InvalidOperationException or IOException or Microsoft.Data.Sqlite.SqliteException)
        {
            Console.Error.WriteLine("v1 SoD import refused: " + error.Message);
            return 1;
        }
    }
}
