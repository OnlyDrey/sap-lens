using System.Collections.Concurrent;
using System.Globalization;
using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using Microsoft.EntityFrameworkCore;
using AuthLens.Application;
using AuthLens.Domain.Json;
using AuthLens.Domain.Sod;
using AuthLens.Persistence;

namespace AuthLens.Api;

/// <summary>Port of sod_catalogue.py, sod_metadata.lookup and the read side of sod_reference.py. Operator-authored annotations are kept apart
/// from the immutable imported definitions, in v1's CatalogueStorage shape (one revisioned SQLite document). An annotation records the definition
/// fingerprint it observed and reviewed (byte-identical to v1), so a changed definition is flagged and a review never silently carries over.
/// Definitions of risks no longer in the current SoD source stay visible from the retired SoD datasets; nothing historical is deleted.</summary>
public static class V1SodCatalogue
{
    public const int MaxRisks = 5000;
    public static readonly (string Name, int Max)[] RiskText =
    [
        ("display_name", 200), ("business_category", 120), ("explanation_en", 12000), ("explanation_no", 12000), ("consequence_en", 8000), ("consequence_no", 8000),
        ("mitigating_controls_en", 12000), ("mitigating_controls_no", 12000), ("review_guidance_en", 8000), ("review_guidance_no", 8000), ("notes", 8000),
    ];
    public static readonly (string Name, int Max)[] ActivityText = [("display_name", 200), ("business_category", 120), ("explanation_en", 12000), ("review_guidance_en", 8000), ("notes", 8000)];
    private static readonly string[] ReviewStatuses = ["Needs description review", "Reviewed"];

    // sod_metadata: resolved field -> (key in the imported metadata, attribute of the local annotation).
    private static readonly (string Name, string Imported, string Local)[] RiskFields =
    [
        ("name", "name", "display_name"), ("description", "description", "explanation_en"), ("impact", "impact", "consequence_en"), ("business_process", "business_process", "business_category"),
        ("controls", "controls", "mitigating_controls_en"), ("guidance", "guidance", "review_guidance_en"), ("notes", "notes", "notes"),
    ];
    private static readonly (string Name, string Imported, string Local)[] ActivityFields =
    [
        ("name", "name", "display_name"), ("description", "description", "explanation_en"), ("business_process", "business_process", "business_category"),
        ("guidance", "guidance", "review_guidance_en"), ("notes", "notes", "notes"),
    ];

    private static readonly Lazy<(byte[] Raw, JsonObject Library)> BundledReference = new(() =>
    {
        using var stream = Assembly.GetExecutingAssembly().GetManifestResourceStream("V1Reference.sod-reference-defaults.json")!;
        using var memory = new MemoryStream();
        stream.CopyTo(memory);
        var raw = memory.ToArray();
        var library = JsonNode.Parse(raw)!.AsObject();
        library["digest"] = Convert.ToHexStringLower(SHA256.HashData(raw));
        return (raw, library);
    });

    private static IResult Detail(int status, string detail) => Results.Json(new { detail }, statusCode: status);
    private static IResult Json(JsonNode node) => Results.Content(node.ToJsonString(), "application/json");
    private static string Fold(string? value) => (value ?? "").PyLower();
    private static string Stamp(TimeProvider clock) => clock.GetUtcNow().UtcDateTime.ToString("yyyy-MM-dd'T'HH:mm:ss.ffffff'+00:00'", CultureInfo.InvariantCulture);
    private static JsonNode ToNode(object? value) => JsonNode.Parse(CanonicalJson.Serialize(value))!;

    public static JsonObject DefaultRiskMetadata()
    {
        var m = new JsonObject { ["enabled"] = true };
        foreach (var (name, _) in RiskText.Take(10)) m[name] = "";
        m["notes"] = "";
        m["description_review_status"] = "Needs description review";
        m["color"] = "";
        return m;
    }

    public static JsonObject DefaultActivityMetadata()
    {
        var m = new JsonObject();
        foreach (var (name, _) in ActivityText) m[name] = "";
        m["color"] = "";
        return m;
    }

    // ---- storage

    public static async Task<(JsonObject Storage, int Revision)> ReadAsync(AuthLensDb db, CancellationToken ct)
    {
        var row = await db.SodDocuments.AsNoTracking().FirstOrDefaultAsync(d => d.Name == "catalogue", ct);
        var storage = row is null ? new JsonObject { ["version"] = 1, ["revision"] = 0, ["entries"] = new JsonObject(), ["activities"] = new JsonObject() } : JsonNode.Parse(row.Json)!.AsObject();
        return (storage, (int?)storage["revision"] ?? 0);
    }

    public static async Task<JsonObject> ReferenceAsync(AuthLensDb db, CancellationToken ct)
    {
        var row = await db.SodDocuments.AsNoTracking().FirstOrDefaultAsync(d => d.Name == "reference", ct);
        return row is null ? BundledReference.Value.Library.DeepClone().AsObject() : JsonNode.Parse(row.Json)!.AsObject();
    }

    private static readonly ConcurrentDictionary<string, Dictionary<string, Dictionary<string, object?>>> Historical = new();

    /// <summary>Definitions from every retired SoD dataset (older first, a later one wins), the .NET counterpart of v1's sod_history snapshots.</summary>
    public static async Task<Dictionary<string, Dictionary<string, object?>>> HistoricalAsync(AuthLensDb db, CancellationToken ct)
    {
        var ids = await db.Datasets.AsNoTracking().Where(d => d.Source == Sources.Sod && d.Status == DatasetStatus.Retired).OrderBy(d => d.Id).Select(d => d.Id).ToListAsync(ct);
        var key = string.Join(',', ids);
        if (Historical.TryGetValue(key, out var cached)) return cached;
        var result = new Dictionary<string, Dictionary<string, object?>>(StringComparer.Ordinal);
        foreach (var id in ids)
            foreach (var risk in SodSource.Build(await SnapshotService.RecordsAsync(db, id, ct)).Risks) result[(string)risk["risk_id"]!] = risk;
        if (Historical.Count > 8) Historical.Clear();
        return Historical[key] = result;
    }

    public sealed record Context(Snapshot Snapshot, JsonObject Settings, JsonObject Storage, int Revision, JsonObject Reference, Dictionary<string, Dictionary<string, object?>> Historical);

    public static async Task<Context> ContextAsync(IServiceProvider services, CancellationToken ct)
    {
        var snapshot = await services.GetRequiredService<SnapshotService>().GetAsync(ct);
        var settings = await services.GetRequiredService<V1Settings>().GetAsync(ct);
        await using var db = await services.GetRequiredService<IDbContextFactory<AuthLensDb>>().CreateDbContextAsync(ct);
        var (storage, revision) = await ReadAsync(db, ct);
        return new Context(snapshot, settings, storage, revision, await ReferenceAsync(db, ct), await HistoricalAsync(db, ct));
    }

    // ---- sod_metadata.lookup

    internal static Dictionary<string, object?> Resolve(string? imported, string? local, string? reference)
    {
        var values = new[] { ("local", local), ("imported", imported), ("reference", reference) }.Select(v => (v.Item1, Value: (v.Item2 ?? "").Trim())).Where(v => v.Value.Length > 0).ToList();
        if (values.Count == 0) return new() { ["value"] = "", ["origin"] = null, ["alternate"] = "", ["alternate_origin"] = null };
        var (origin, value) = values[0];
        var alternate = values.Skip(1).FirstOrDefault(v => v.Value != value);
        return new() { ["value"] = value, ["origin"] = origin, ["alternate"] = alternate.Value ?? "", ["alternate_origin"] = alternate.Value is null ? null : alternate.Item1 };
    }

    private static JsonObject Entry((string Name, string Imported, string Local)[] fields, IReadOnlyDictionary<string, string>? imported, JsonObject? local, JsonObject? reference)
    {
        string? Imported(string key) => imported is not null && imported.TryGetValue(key, out var v) ? v : null;
        var resolved = fields.ToDictionary(f => f.Name, f => Resolve(Imported(f.Imported), local is null ? "" : (string?)local[f.Local] ?? "", (string?)reference?[f.Local] ?? ""));
        var entry = new JsonObject();
        foreach (var (name, item) in resolved) if ((string)item["value"]! != "") entry[name] = (string)item["value"]!;
        var origins = new JsonObject();
        foreach (var (name, item) in resolved) if ((string)item["value"]! != "") origins[name] = (string?)item["origin"];
        entry["origin"] = origins;
        var inherited = fields.ToDictionary(f => f.Name, f => Resolve(Imported(f.Imported), "", (string?)reference?[f.Local] ?? ""));
        if (inherited.Values.Any(i => (string)i["value"]! != ""))
        {
            entry["inherited"] = new JsonObject(inherited.Where(p => (string)p.Value["value"]! != "").Select(p => KeyValuePair.Create(p.Key, (JsonNode?)(string)p.Value["value"]!)));
            entry["inherited_origin"] = new JsonObject(inherited.Where(p => (string)p.Value["value"]! != "").Select(p => KeyValuePair.Create(p.Key, (JsonNode?)(string?)p.Value["origin"])));
        }
        if (reference is not null && reference.Count > 0)
            entry["reference"] = new JsonObject(fields.Where(f => !string.IsNullOrEmpty((string?)reference[f.Local])).Select(f => KeyValuePair.Create(f.Name, (JsonNode?)(string)reference[f.Local]!)));
        var differing = resolved.Where(p => (string)p.Value["alternate"]! != "").ToList();
        if (differing.Count > 0)
            entry["alternate"] = new JsonObject(differing.Select(p => KeyValuePair.Create(p.Key, (JsonNode?)new JsonObject { ["value"] = (string)p.Value["alternate"]!, ["origin"] = (string?)p.Value["alternate_origin"] })));
        return entry;
    }

    public static JsonObject Lookup(Context c)
    {
        var importedRisks = c.Snapshot.Sod?.Metadata?.Risks ?? [];
        var importedActivities = c.Snapshot.Sod?.Metadata?.Activities ?? [];
        var definitions = (c.Snapshot.Sod?.Risks ?? []).ToDictionary(r => (string)r["risk_id"]!, StringComparer.Ordinal);
        var activities = new SortedDictionary<string, SortedSet<string>>(StringComparer.Ordinal);
        foreach (var risk in definitions.Values)
            foreach (var mapping in Mappings(risk))
            {
                if (!activities.TryGetValue(mapping.Activity, out var set)) activities[mapping.Activity] = set = new SortedSet<string>(StringComparer.Ordinal);
                set.Add((string)risk["risk_id"]!);
            }
        var entries = c.Storage["entries"]!.AsObject();
        var storedActivities = c.Storage["activities"]!.AsObject();
        var referenceRisks = c.Reference["risks"]?.AsObject();
        var referenceActivities = c.Reference["activities"]?.AsObject();
        var risksOut = new JsonObject();
        foreach (var id in definitions.Keys.Concat(entries.Select(p => p.Key)).Concat(importedRisks.Keys).Distinct().Order(StringComparer.Ordinal))
        {
            var entry = Entry(RiskFields, importedRisks.GetValueOrDefault(id), entries[id]?["metadata"]?.AsObject(), definitions.ContainsKey(id) ? referenceRisks?[id]?.AsObject() : null);
            if (definitions.TryGetValue(id, out var definition))
            {
                entry["criticality"] = (string)definition["criticality"]!;
                entry["type"] = (string)definition["risk_type"]!;
                entry["activities"] = new JsonArray([.. Mappings(definition).Select(m => m.Activity).Distinct().Order(StringComparer.Ordinal).Select(a => (JsonNode?)a)]);
            }
            if (definition is not null || new[] { "name", "description", "impact", "business_process" }.Any(entry.ContainsKey)) risksOut[id] = entry;
        }
        var activitiesOut = new JsonObject();
        foreach (var name in activities.Keys.Concat(storedActivities.Select(p => p.Key)).Concat(importedActivities.Keys).Distinct().Order(StringComparer.Ordinal))
        {
            var imported = importedActivities.GetValueOrDefault(name);
            var entry = Entry(ActivityFields, imported, storedActivities[name]?["metadata"]?.AsObject(), activities.ContainsKey(name) ? referenceActivities?[name]?.AsObject() : null);
            if (imported is not null && imported.TryGetValue("type", out var type) && type.Length > 0)
            {
                entry["type"] = type;
                entry["origin"]!["type"] = "imported";
            }
            if (activities.TryGetValue(name, out var ids))
            {
                entry["risks"] = ids.Count;
                entry["risk_ids"] = new JsonArray([.. ids.Select(i => (JsonNode?)i)]);
            }
            if (activities.ContainsKey(name) || new[] { "name", "description", "business_process", "type" }.Any(entry.ContainsKey)) activitiesOut[name] = entry;
        }
        return new JsonObject { ["risks"] = risksOut, ["activities"] = activitiesOut, ["active_activities"] = new JsonArray([.. activities.Keys.Select(a => (JsonNode?)a)]) };
    }

    public static IEnumerable<(string Slot, string Activity, string Tcode, string Ttext)> Mappings(Dictionary<string, object?> risk)
    {
        var sides = (Dictionary<string, object?>)risk["activities"]!;
        foreach (var slot in new[] { "ACTVT1", "ACTVT2" })
            foreach (var m in ((List<object?>)sides[slot]!).Cast<Dictionary<string, object?>>())
                yield return (slot, (string)m["activity"]!, (string)m["tcode"]!, (string?)m["ttext"] ?? "");
    }

    // ---- catalogue (sod_catalogue.catalogue / activity_catalogue / appearance)

    public static JsonObject Catalogue(Context c)
    {
        var definitions = new SortedDictionary<string, Dictionary<string, object?>>(c.Historical, StringComparer.Ordinal);
        var current = (c.Snapshot.Sod?.Risks ?? []).ToDictionary(r => (string)r["risk_id"]!, StringComparer.Ordinal);
        foreach (var (id, risk) in current) definitions[id] = risk;
        var names = Lookup(c)["risks"]!.AsObject();
        var entries = c.Storage["entries"]!.AsObject();
        var items = new JsonArray();
        foreach (var (id, source) in definitions)
        {
            var stored = entries[id]?.AsObject();
            var metadata = stored?["metadata"]?.DeepClone().AsObject() ?? DefaultRiskMetadata();
            var version = SodCatalogueFingerprint.Of(source);
            var changed = stored is not null && (string?)stored["observed_definition"] != version;
            var reviewed = stored is not null && (string?)stored["reviewed_definition"] == version && (string?)metadata["description_review_status"] == "Reviewed";
            items.Add(new JsonObject
            {
                ["risk_id"] = id, ["source"] = ToNode(source), ["local"] = metadata, ["display_name"] = (string?)names[id]?["name"] ?? "", ["current"] = current.ContainsKey(id),
                ["new"] = current.ContainsKey(id) && stored is null, ["source_changed"] = changed, ["description_review_status"] = reviewed ? "Reviewed" : "Needs description review",
                ["definition_version"] = version, ["modified"] = stored?["modified"]?.DeepClone(),
            });
        }
        var rows = items.Select(i => i!.AsObject()).ToList();
        var reference = c.Settings["data_lifecycle"]?["sources"]?["sod"];
        return new JsonObject
        {
            ["items"] = items, ["revision"] = c.Revision,
            ["summary"] = new JsonObject
            {
                ["total"] = rows.Count, ["current"] = current.Count, ["enabled"] = rows.Count(i => (bool)i["current"]! && (bool)i["local"]!["enabled"]!),
                ["new"] = rows.Count(i => (bool)i["new"]!), ["needs_description_review"] = rows.Count(i => (bool)i["current"]! && (string)i["description_review_status"]! != "Reviewed"),
                ["unsupported"] = rows.Count(i => (bool)i["current"]! && !(bool)i["source"]!["supported"]!),
            },
            ["source"] = new JsonObject
            {
                ["loaded"] = c.Snapshot.Sod is not null, ["records"] = c.Snapshot.Sod?.Records.Count ?? 0, ["risks"] = current.Count, ["version"] = c.Snapshot.Sod?.ContentHash,
                ["imported_at"] = (string?)reference?["imported_at"], ["checked_at"] = (string?)reference?["checked_at"],
            },
        };
    }

    public static JsonObject ActivityCatalogue(Context c)
    {
        var definitions = new Dictionary<string, Dictionary<string, object?>>(c.Historical, StringComparer.Ordinal);
        var current = (c.Snapshot.Sod?.Risks ?? []).ToDictionary(r => (string)r["risk_id"]!, StringComparer.Ordinal);
        foreach (var (id, risk) in current) definitions[id] = risk;
        var found = new SortedDictionary<string, (SortedSet<string> Risks, SortedSet<string> Current, SortedSet<string> Tcodes, Dictionary<string, string> Texts, bool IsCurrent)>(StringComparer.Ordinal);
        foreach (var (id, risk) in definitions)
            foreach (var m in Mappings(risk))
            {
                if (!found.TryGetValue(m.Activity, out var e)) e = (new SortedSet<string>(StringComparer.Ordinal), new SortedSet<string>(StringComparer.Ordinal), new SortedSet<string>(StringComparer.Ordinal), new Dictionary<string, string>(StringComparer.Ordinal), false);
                e.Risks.Add(id);
                if (current.ContainsKey(id)) e.Current.Add(id);
                e.Tcodes.Add(m.Tcode);
                if (m.Ttext.Length > 0) e.Texts.TryAdd(m.Tcode, m.Ttext);
                found[m.Activity] = e with { IsCurrent = e.IsCurrent || current.ContainsKey(id) };
            }
        var names = Lookup(c)["activities"]!.AsObject();
        var stored = c.Storage["activities"]!.AsObject();
        var items = new JsonArray();
        foreach (var (name, e) in found)
        {
            var s = stored[name]?.AsObject();
            items.Add(new JsonObject
            {
                ["activity"] = name, ["display_name"] = (string?)names[name]?["name"] ?? "", ["risks"] = new JsonArray([.. e.Risks.Select(r => (JsonNode?)r)]),
                ["current_risks"] = new JsonArray([.. e.Current.Select(r => (JsonNode?)r)]), ["tcodes"] = new JsonArray([.. e.Tcodes.Select(t => (JsonNode?)t)]),
                ["mappings"] = new JsonArray([.. e.Tcodes.Select(t => (JsonNode?)new JsonObject { ["tcode"] = t, ["ttext"] = e.Texts.GetValueOrDefault(t, "") })]),
                ["current"] = e.IsCurrent, ["local"] = s?["metadata"]?.DeepClone() ?? DefaultActivityMetadata(), ["modified"] = s?["modified"]?.DeepClone(),
            });
        }
        return new JsonObject { ["items"] = items, ["revision"] = c.Revision };
    }

    public static JsonObject Appearance(JsonObject storage)
    {
        JsonObject Of(JsonObject map)
        {
            var result = new JsonObject();
            foreach (var (key, entry) in map)
            {
                var m = entry!["metadata"]!;
                var (name, color) = ((string?)m["display_name"] ?? "", (string?)m["color"] ?? "");
                if (name.Length > 0 || color.Length > 0) result[key] = new JsonObject { ["name"] = name, ["color"] = color };
            }
            return result;
        }
        return new JsonObject { ["risks"] = Of(storage["entries"]!.AsObject()), ["activities"] = Of(storage["activities"]!.AsObject()) };
    }

    /// <summary>sod_reference.status: library summary and how its identifiers match the current SoD source (exact identifiers only).</summary>
    public static JsonObject ReferenceStatus(Context c)
    {
        var library = c.Reference;
        var bundled = BundledReference.Value.Library;
        var risks = c.Snapshot.Sod?.Risks ?? [];
        var riskIds = risks.Select(r => (string)r["risk_id"]!).ToHashSet(StringComparer.Ordinal);
        var activityIds = risks.SelectMany(Mappings).Select(m => m.Activity).ToHashSet(StringComparer.Ordinal);
        var libraryRisks = library["risks"]?.AsObject().Select(p => p.Key).ToHashSet(StringComparer.Ordinal) ?? [];
        var libraryActivities = library["activities"]?.AsObject().Select(p => p.Key).ToHashSet(StringComparer.Ordinal) ?? [];
        static JsonArray Sorted(IEnumerable<string> values) => new([.. values.Order(StringComparer.Ordinal).Select(v => (JsonNode?)v)]);
        return new JsonObject
        {
            ["origin"] = (string?)library["origin"] ?? "custom", ["library_version"] = (string?)library["library_version"] ?? "", ["source"] = (string?)library["source"] ?? "",
            ["version"] = (int?)library["version"] ?? 1, ["revision"] = (int?)library["revision"] ?? 0, ["digest"] = (string?)library["digest"] ?? "", ["imported_at"] = (string?)library["imported_at"] ?? "",
            ["risks"] = libraryRisks.Count, ["activities"] = libraryActivities.Count, ["terms"] = library["terms"]?.AsObject().Count ?? 0,
            ["defaults_available"] = true, ["default_version"] = (string?)bundled["library_version"], ["warning"] = "", ["installed"] = !string.IsNullOrEmpty((string?)library["digest"]),
            ["matched_risks"] = riskIds.Count(libraryRisks.Contains), ["matched_activities"] = activityIds.Count(libraryActivities.Contains),
            ["unmatched_risks"] = Sorted(libraryRisks.Except(riskIds)), ["unmatched_activities"] = Sorted(libraryActivities.Except(activityIds)),
            ["missing_risks"] = Sorted(riskIds.Except(libraryRisks)), ["missing_activities"] = Sorted(activityIds.Except(libraryActivities)),
        };
    }

    // ---- validation (LocalMetadata / ActivityMetadata, StrictModel)

    private static JsonObject? ValidateMetadata(JsonNode? node, bool risk, List<object> errors)
    {
        object[] path = ["metadata"];
        if (node is not JsonObject body) { errors.Add(V1Validation.At("model_type", "Input should be a valid dictionary", "body", "metadata")); return null; }
        var text = risk ? RiskText : ActivityText;
        var allowed = text.Select(t => t.Name).Append("color").Concat(risk ? ["enabled", "description_review_status"] : []).ToArray();
        V1Validation.Extra(body, allowed, errors, path);
        var result = risk ? DefaultRiskMetadata() : DefaultActivityMetadata();
        foreach (var (name, max) in text.Append(("color", 7)))
        {
            if (!body.ContainsKey(name)) continue;
            var value = V1Validation.Text(body, name, 0, max, false, errors, path);
            if (value is null) continue;
            if (value.Any(c => c < 32 && c is not ('\n' or '\r' or '\t'))) { errors.Add(V1Validation.Error("value_error", name, "Value error, Metadata contains unsupported control characters.", path)); continue; }
            value = value.Trim();
            if (name == "color")
            {
                value = value.PyLower();
                if (value.Length > 0 && !System.Text.RegularExpressions.Regex.IsMatch(value, "^#[0-9a-f]{6}$")) { errors.Add(V1Validation.Error("value_error", name, "Value error, Color must be empty or a #rrggbb value.", path)); continue; }
            }
            result[name] = value;
        }
        if (risk && body.TryGetPropertyValue("enabled", out var enabled))
        {
            if (enabled?.GetValueKind() is JsonValueKind.True or JsonValueKind.False) result["enabled"] = enabled.GetValue<bool>();
            else errors.Add(V1Validation.Error("bool_type", "enabled", "Input should be a valid boolean", path));
        }
        if (risk && body.TryGetPropertyValue("description_review_status", out var status))
        {
            if (status?.GetValueKind() == JsonValueKind.String && ReviewStatuses.Contains(status.GetValue<string>())) result["description_review_status"] = status.GetValue<string>();
            else errors.Add(V1Validation.Error("literal_error", "description_review_status", "Input should be 'Needs description review' or 'Reviewed'", path));
        }
        return result;
    }

    private static int? Revision(JsonObject body, List<object> errors)
    {
        if (!body.TryGetPropertyValue("expected_revision", out var node)) { errors.Add(V1Validation.Error("missing", "expected_revision", "Field required")); return null; }
        if (node?.GetValueKind() != JsonValueKind.Number || !int.TryParse(node.ToJsonString(), out var value) || value < 0) { errors.Add(V1Validation.Error("int_type", "expected_revision", "Input should be a valid integer greater than or equal to 0")); return null; }
        return value;
    }

    private sealed class Refusal(int status, string detail) : Exception(detail) { public int Status { get; } = status; }

    /// <summary>Writes the catalogue document inside the shared write transaction, refusing when another save happened (optimistic revision).</summary>
    private static Task<JsonObject> SaveAsync(IServiceProvider services, int expected, string actor, Func<JsonObject, JsonObject> mutate, CancellationToken ct) =>
        services.GetRequiredService<WriteCoordinator>().WriteAsync(async (db, token) =>
        {
            var row = await db.SodDocuments.FirstOrDefaultAsync(d => d.Name == "catalogue", token);
            var storage = row is null ? new JsonObject { ["version"] = 1, ["revision"] = 0, ["entries"] = new JsonObject(), ["activities"] = new JsonObject() } : JsonNode.Parse(row.Json)!.AsObject();
            if (((int?)storage["revision"] ?? 0) != expected) throw new Refusal(409, "SoD catalogue changed. Reload before saving your edits.");
            var result = mutate(storage);
            storage["revision"] = expected + 1;
            if (row is null) db.SodDocuments.Add(row = new SodDocument { Name = "catalogue", Json = "{}" });
            (row.Revision, row.Json, row.UpdatedUtc, row.UpdatedBy) = (expected + 1, storage.ToJsonString(), DateTime.UtcNow, actor);
            return result;
        }, ct);

    private static bool SearchFields(string term, params string?[] fields) =>
        term.Contains('*') ? fields.Any(f => TextMatching.TextMatches(f, term)) : TextMatching.TextMatches(string.Join(' ', fields.Select(f => f ?? "")), term);

    private static List<JsonObject> Filtered(JsonObject result, IQueryCollection q)
    {
        string Q(string name) => q[name].FirstOrDefault() ?? "";
        var (search, enabled, current, status, criticality, type, category, sort) = (Q("search").Trim(), Q("enabled"), Q("current"), Q("status"), Q("criticality"), Q("type"), Q("category"), Q("sort") is { Length: > 0 } s ? s : "risk_id");
        var descending = Q("descending") is "true" or "1";
        var items = result["items"]!.AsArray().Select(i => i!.AsObject()).Where(item =>
        {
            var (local, source) = (item["local"]!, item["source"]!);
            return (search.Length == 0 || SearchFields(search, (string?)item["risk_id"], (string?)source["source_text"], (string?)item["display_name"], (string?)local["business_category"], (string?)local["explanation_en"], (string?)local["explanation_no"]))
                && (enabled.Length == 0 || (bool)local["enabled"]! == (enabled == "enabled")) && (current.Length == 0 || (bool)item["current"]! == (current == "current"))
                && (criticality.Length == 0 || (string?)source["criticality"] == criticality) && (type.Length == 0 || (string?)source["risk_type"] == type)
                && (category.Length == 0 || (string?)local["business_category"] == category)
                && (status.Length == 0 || status == "new" && (bool)item["new"]! || status == "changed" && (bool)item["source_changed"]!
                    || status == "needs_review" && (string)item["description_review_status"]! != "Reviewed" || status == "reviewed" && (string)item["description_review_status"]! == "Reviewed"
                    || status == "unsupported" && !(bool)source["supported"]!);
        }).ToList();
        string Value(JsonObject item) => sort switch
        {
            "risk_id" => (string)item["risk_id"]!, "criticality" => (string?)item["source"]!["criticality"] ?? "", "modified" => (string?)item["modified"] ?? "",
            "display_name" => (string?)item["display_name"] ?? "", _ => (string?)item["local"]![sort] ?? "",
        };
        var ordered = items.OrderBy(i => Fold(Value(i)), StringComparer.Ordinal).ThenBy(i => (string)i["risk_id"]!, StringComparer.Ordinal).ToList();
        if (descending) ordered.Reverse();
        return ordered;
    }

    private static string? QueryError(IQueryCollection q)
    {
        string Q(string name) => q[name].FirstOrDefault() ?? "";
        return Q("search").Length > 256 || Q("enabled") is not ("" or "enabled" or "disabled") || Q("current") is not ("" or "current" or "historical")
            || Q("status") is not ("" or "new" or "changed" or "needs_review" or "reviewed" or "unsupported") || Q("criticality").Length > 64 || Q("type").Length > 64 || Q("category").Length > 120
            || Q("sort") is not ("" or "risk_id" or "display_name" or "criticality" or "business_category" or "modified") ? "Invalid catalogue query." : null;
    }

    public static void Map(RouteGroupBuilder api)
    {
        api.MapGet("/sod/catalogue", async (HttpContext http, IServiceProvider services, CancellationToken ct) =>
        {
            if (QueryError(http.Request.Query) is { } error) return Detail(422, error);
            var offset = int.TryParse(http.Request.Query["offset"].FirstOrDefault() ?? "0", out var o) ? o : -1;
            var limit = int.TryParse(http.Request.Query["limit"].FirstOrDefault() ?? "25", out var l) ? l : -1;
            if (offset < 0 || limit is < 1 or > 100) return Detail(422, "Invalid paging parameters.");
            var result = Catalogue(await ContextAsync(services, ct));
            var items = Filtered(result, http.Request.Query);
            result["items"] = new JsonArray([.. items.Skip(offset).Take(limit).Select(i => (JsonNode?)i.DeepClone())]);
            (result["total"], result["offset"], result["limit"]) = (items.Count, offset, limit);
            return Json(result);
        });

        api.MapGet("/sod/catalogue/export", async (HttpContext http, IServiceProvider services, CancellationToken ct) =>
        {
            if (QueryError(http.Request.Query) is { } error) return Detail(422, error);
            var items = Filtered(Catalogue(await ContextAsync(services, ct)), http.Request.Query);
            string[] columns = ["RISK_ID", "DISPLAY_NAME", "SOURCE_DESCRIPTION", "CRITICITY", "TYPE", "CURRENT", "ENABLED", "DESCRIPTION_REVIEW_STATUS", "BUSINESS_CATEGORY", "EXPLANATION_EN", "EXPLANATION_NO",
                "CONSEQUENCE_EN", "CONSEQUENCE_NO", "MITIGATING_CONTROLS_EN", "MITIGATING_CONTROLS_NO", "REVIEW_GUIDANCE_EN", "REVIEW_GUIDANCE_NO", "NOTES", "ACTIVITY_1", "ACTIVITY_2", "ACTIVITY_1_TCODES",
                "ACTIVITY_2_TCODES", "DEFINITION_VERSION", "MODIFIED"];
            var csv = new StringBuilder("﻿");
            V1Csv.Line(csv, columns, cells: false);
            foreach (var row in items)
            {
                var (source, local) = (row["source"]!, row["local"]!);
                var values = new List<string?> { (string?)row["risk_id"], (string?)row["display_name"], (string?)source["source_text"], (string?)source["criticality"], (string?)source["risk_type"],
                    (bool)row["current"]! ? "Yes" : "No", (bool)local["enabled"]! ? "Yes" : "No", (string?)row["description_review_status"], (string?)local["business_category"] };
                values.AddRange(new[] { "explanation_en", "explanation_no", "consequence_en", "consequence_no", "mitigating_controls_en", "mitigating_controls_no", "review_guidance_en", "review_guidance_no", "notes" }.Select(k => (string?)local[k]));
                values.AddRange([(string?)source["activity1"], (string?)source["activity2"], V1SavedFilters.PyJson(source["activities"]!["ACTVT1"], ensureAscii: false),
                    V1SavedFilters.PyJson(source["activities"]!["ACTVT2"], ensureAscii: false), (string?)row["definition_version"], (string?)row["modified"] ?? ""]);
                V1Csv.Line(csv, values, cells: true);
            }
            http.Response.Headers.CacheControl = "no-store";
            http.Response.Headers.ContentDisposition = $"attachment; filename=\"authlens-sod-catalogue-{DateTime.Now.ToString("yyyy-MM-dd", CultureInfo.InvariantCulture)}.csv\"";
            return Results.Text(csv.ToString(), "text/csv; charset=utf-8", Encoding.UTF8);
        });

        api.MapGet("/sod/appearance", async (IDbContextFactory<AuthLensDb> factory, CancellationToken ct) =>
        {
            await using var db = await factory.CreateDbContextAsync(ct);
            return Json(Appearance((await ReadAsync(db, ct)).Storage));
        });

        // sod_reference: status, reset to the bundled library, workbook upload, template download.
        api.MapGet("/sod/reference", async (IServiceProvider services, CancellationToken ct) => Json(ReferenceStatus(await ContextAsync(services, ct))));

        api.MapPost("/sod/reference/reset", async (HttpContext http, IServiceProvider services, CancellationToken ct) =>
        {
            var (body, invalid) = await V1Validation.ReadBody(http, ct);
            if (invalid is not null) return invalid;
            var errors = new List<object>();
            V1Validation.Extra(body!, ["expected_revision"], errors);
            var expected = Revision(body!, errors);
            if (errors.Count > 0) return Results.Json(new { detail = errors }, statusCode: 422);
            try
            {
                await services.GetRequiredService<WriteCoordinator>().WriteAsync(async (db, token) =>
                {
                    var row = await db.SodDocuments.FirstOrDefaultAsync(d => d.Name == "reference", token);
                    var previous = row is null ? BundledReference.Value.Library.DeepClone().AsObject() : JsonNode.Parse(row.Json)!.AsObject();
                    if (((int?)previous["revision"] ?? 0) != expected) throw new Refusal(409, "Reference library changed. Reload before resetting defaults.");
                    var bundled = BundledReference.Value.Library;
                    if ((string?)previous["origin"] == "bundled" && (string?)previous["digest"] == (string?)bundled["digest"]) return true;
                    var value = bundled.DeepClone().AsObject();
                    value["revision"] = expected + 1;
                    value["imported_at"] = Stamp(services.GetRequiredService<TimeProvider>());
                    if (row is null) db.SodDocuments.Add(row = new SodDocument { Name = "reference", Json = "{}" });
                    (row.Revision, row.Json, row.UpdatedUtc, row.UpdatedBy) = (expected!.Value + 1, value.ToJsonString(), DateTime.UtcNow, Actors.Name(http));
                    return true;
                }, ct);
            }
            catch (Refusal refusal) { return Detail(refusal.Status, refusal.Message); }
            return Json(ReferenceStatus(await ContextAsync(services, ct)));
        });

        // sod_reference.install: refuse a stale revision, keep an identical library unchanged, otherwise store the new one with revision + 1.
        // Local catalogue annotations live in their own document and are never touched by a reference replacement.
        async Task<IResult> Install(HttpContext http, IServiceProvider services, byte[] raw, int expected, CancellationToken ct)
        {
            ReferenceLibrary candidate;
            try { candidate = SodReferenceWorkbook.Parse(raw); }
            catch (ReferenceWorkbookException error) { return Detail(422, error.Message); }
            try
            {
                await services.GetRequiredService<WriteCoordinator>().WriteAsync(async (db, token) =>
                {
                    var row = await db.SodDocuments.FirstOrDefaultAsync(d => d.Name == "reference", token);
                    var previous = row is null ? BundledReference.Value.Library.DeepClone().AsObject() : JsonNode.Parse(row.Json)!.AsObject();
                    var revision = (int?)previous["revision"] ?? 0;
                    if (revision != expected) throw new Refusal(409, "Reference library changed. Reload before replacing it.");
                    if ((string?)previous["digest"] == candidate.Digest) return true;
                    static JsonObject Records(SortedDictionary<string, SortedDictionary<string, string>> map) =>
                        new(map.Select(p => KeyValuePair.Create(p.Key, (JsonNode?)new JsonObject(p.Value.Select(v => KeyValuePair.Create(v.Key, (JsonNode?)v.Value))))));
                    var library = new JsonObject
                    {
                        ["origin"] = "custom", ["library_version"] = "", ["source"] = "", ["version"] = 1, ["revision"] = revision + 1, ["digest"] = candidate.Digest,
                        ["imported_at"] = Stamp(services.GetRequiredService<TimeProvider>()), ["risks"] = Records(candidate.Risks), ["activities"] = Records(candidate.Activities),
                        ["terms"] = new JsonObject(candidate.Terms.Select(t => KeyValuePair.Create(t.Key, (JsonNode?)t.Value))),
                    };
                    var encoded = library.ToJsonString();
                    if (Encoding.UTF8.GetByteCount(encoded) > SodReferenceWorkbook.MaxExpanded) throw new Refusal(422, "Reference library exceeds its storage limit.");
                    if (row is null) db.SodDocuments.Add(row = new SodDocument { Name = "reference", Json = "{}" });
                    (row.Revision, row.Json, row.UpdatedUtc, row.UpdatedBy) = (revision + 1, encoded, DateTime.UtcNow, Actors.Name(http));
                    return true;
                }, ct);
            }
            catch (Refusal refusal) { return Detail(refusal.Status, refusal.Message); }
            return Json(ReferenceStatus(await ContextAsync(services, ct)));
        }

        api.MapPost("/sod/reference/upload", async (HttpContext http, IServiceProvider services, CancellationToken ct) =>
        {
            var limit = http.Features.Get<Microsoft.AspNetCore.Http.Features.IHttpMaxRequestBodySizeFeature>();
            if (limit is { IsReadOnly: false }) limit.MaxRequestBodySize = SodReferenceWorkbook.MaxBytes + 64 * 1024;
            if (!http.Request.HasFormContentType) return Detail(422, "Choose one reference workbook and its current revision.");
            IFormCollection form;
            try { form = await http.Request.ReadFormAsync(ct); }
            catch (Exception error) when (error is InvalidDataException or IOException or BadHttpRequestException) { return Detail(422, "Choose one reference workbook and its current revision."); }
            var keys = form.Keys.Concat(form.Files.Select(f => f.Name)).ToList();
            if (!keys.ToHashSet().SetEquals(["file", "revision"]) || keys.Count != 2 || form.Files.Count != 1 || form["revision"].Count != 1) return Detail(422, "Choose one reference workbook and its current revision.");
            var file = form.Files[0];
            if (file.Name != "file") return Detail(422, "Choose an XLSX reference workbook.");
            var name = file.FileName ?? "";
            if (!name.EndsWith(".xlsx", StringComparison.OrdinalIgnoreCase) || Encoding.UTF8.GetByteCount(name) > 200 || name.Contains("..", StringComparison.Ordinal)
                || name.IndexOfAny(['/', '\\', '\0', '<', '>', ':', '"', '|', '?', '*']) >= 0 || name.Any(c => c < 32))
                return Detail(422, "Choose an XLSX filename without path components.");
            if (file.Length == 0 || file.Length > SodReferenceWorkbook.MaxBytes) return Detail(file.Length == 0 ? 422 : 413, "Choose a non-empty reference workbook up to 2 MB.");
            if (!int.TryParse(form["revision"].ToString(), out var revision)) return Detail(422, "Choose the current reference revision.");
            using var memory = new MemoryStream();
            await file.CopyToAsync(memory, ct);
            return await Install(http, services, memory.ToArray(), revision, ct);
        });

        api.MapPut("/sod/reference", async (HttpContext http, IServiceProvider services, CancellationToken ct) =>
        {
            var limit = http.Features.Get<Microsoft.AspNetCore.Http.Features.IHttpMaxRequestBodySizeFeature>();
            if (limit is { IsReadOnly: false }) limit.MaxRequestBodySize = 2_800_000 + 64 * 1024;
            var (body, invalid) = await V1Validation.ReadBody(http, ct);
            if (invalid is not null) return invalid;
            var errors = new List<object>();
            V1Validation.Extra(body!, ["expected_revision", "workbook_base64"], errors);
            var expected = Revision(body!, errors);
            var encoded = V1Validation.Text(body!, "workbook_base64", 0, 2_800_000, true, errors);
            if (errors.Count > 0) return Results.Json(new { detail = errors }, statusCode: 422);
            byte[] raw;
            try { raw = Convert.FromBase64String(encoded!); }
            catch (FormatException) { return Detail(422, "Workbook must be valid base64."); }
            return await Install(http, services, raw, expected!.Value, ct);
        });

        api.MapGet("/sod/reference/template", (HttpContext http) =>
        {
            using var stream = Assembly.GetExecutingAssembly().GetManifestResourceStream("V1Reference.sod-reference-template.xlsx");
            if (stream is null) return Detail(503, "Reference template is unavailable; repair the application package.");
            using var memory = new MemoryStream();
            stream.CopyTo(memory);
            http.Response.Headers.CacheControl = "no-store";
            return Results.File(memory.ToArray(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "authlens-sod-reference-template.xlsx");
        });

        api.MapGet("/sod/metadata", async (IServiceProvider services, CancellationToken ct) => Json(Lookup(await ContextAsync(services, ct))));

        api.MapPost("/sod/catalogue/bulk", async (HttpContext http, IServiceProvider services, CancellationToken ct) =>
        {
            var (body, invalid) = await V1Validation.ReadBody(http, ct);
            if (invalid is not null) return invalid;
            var errors = new List<object>();
            V1Validation.Extra(body!, ["expected_revision", "enabled", "confirm"], errors);
            var revision = Revision(body!, errors);
            bool? enabled = body!["enabled"]?.GetValueKind() is JsonValueKind.True or JsonValueKind.False ? body["enabled"]!.GetValue<bool>() : null;
            if (enabled is null) errors.Add(V1Validation.Error(body.ContainsKey("enabled") ? "bool_type" : "missing", "enabled", body.ContainsKey("enabled") ? "Input should be a valid boolean" : "Field required"));
            var confirm = body["confirm"]?.GetValueKind() == JsonValueKind.True;
            if (body.ContainsKey("confirm") && body["confirm"]?.GetValueKind() is not (JsonValueKind.True or JsonValueKind.False)) errors.Add(V1Validation.Error("bool_type", "confirm", "Input should be a valid boolean"));
            if (errors.Count > 0) return Results.Json(new { detail = errors }, statusCode: 422);
            if (enabled == false && !confirm) return Detail(422, "Confirm disabling all current SoD risks. Historical findings and reviews will be retained.");
            var c = await ContextAsync(services, ct);
            var current = Catalogue(c);
            try
            {
                var result = await SaveAsync(services, revision!.Value, Actors.Name(http), storage =>
                {
                    var entries = storage["entries"]!.AsObject();
                    var identifiers = current["items"]!.AsArray().Where(i => (bool)i!["current"]!).Select(i => (string)i!["risk_id"]!).ToHashSet();
                    if (entries.Select(p => p.Key).Union(identifiers).Count() > MaxRisks) throw new Refusal(409, "SoD catalogue capacity is reached. Existing annotations are retained.");
                    var stamp = Stamp(services.GetRequiredService<TimeProvider>());
                    foreach (var item in current["items"]!.AsArray().Select(i => i!.AsObject()).Where(i => (bool)i["current"]!))
                    {
                        var id = (string)item["risk_id"]!;
                        var previous = entries[id]?.AsObject();
                        var metadata = item["local"]!.DeepClone().AsObject();
                        metadata["enabled"] = enabled;
                        entries[id] = new JsonObject
                        {
                            ["metadata"] = metadata, ["observed_definition"] = (string?)previous?["observed_definition"] ?? (string)item["definition_version"]!,
                            ["reviewed_definition"] = previous?["reviewed_definition"]?.DeepClone(), ["modified"] = stamp,
                        };
                    }
                    return new JsonObject { ["revision"] = revision + 1, ["updated"] = (int)current["summary"]!["current"]!, ["enabled"] = enabled };
                }, ct);
                return Json(result);
            }
            catch (Refusal refusal) { return Detail(refusal.Status, refusal.Message); }
        });

        api.MapGet("/sod/catalogue/{riskId}", async (string riskId, IServiceProvider services, CancellationToken ct) =>
        {
            var result = Catalogue(await ContextAsync(services, ct));
            var item = result["items"]!.AsArray().FirstOrDefault(i => (string)i!["risk_id"]! == riskId);
            return item is null ? Detail(404, "Risk is not available in the retained source definitions.") : Json(new JsonObject { ["item"] = item.DeepClone(), ["revision"] = result["revision"]!.DeepClone() });
        });

        api.MapPost("/sod/catalogue/{**riskId}", async (string riskId, HttpContext http, IServiceProvider services, CancellationToken ct) =>
        {
            var (body, invalid) = await V1Validation.ReadBody(http, ct);
            if (invalid is not null) return invalid;
            var errors = new List<object>();
            V1Validation.Extra(body!, ["expected_revision", "definition_version", "metadata"], errors);
            var revision = Revision(body!, errors);
            var definition = V1Validation.Text(body!, "definition_version", 64, 64, true, errors);
            if (definition is not null && !System.Text.RegularExpressions.Regex.IsMatch(definition, "^[a-f0-9]{64}$")) errors.Add(V1Validation.Error("string_pattern_mismatch", "definition_version", "String should match pattern '^[a-f0-9]{64}$'"));
            JsonObject? metadata = null;
            if (!body!.ContainsKey("metadata")) errors.Add(V1Validation.Error("missing", "metadata", "Field required"));
            else metadata = ValidateMetadata(body["metadata"], risk: true, errors);
            if (errors.Count > 0) return Results.Json(new { detail = errors }, statusCode: 422);
            var c = await ContextAsync(services, ct);
            if (c.Revision != revision) return Detail(409, "SoD catalogue changed. Reload before saving your edits.");
            var item = Catalogue(c)["items"]!.AsArray().FirstOrDefault(i => (string)i!["risk_id"]! == riskId);
            if (item is null) return Detail(404, "SoD risk is not present in the current or retained source history.");
            if ((string)item["definition_version"]! != definition) return Detail(409, "The SoD source definition changed. Reload before saving metadata.");
            try
            {
                var saved = await SaveAsync(services, revision!.Value, Actors.Name(http), storage =>
                {
                    var entries = storage["entries"]!.AsObject();
                    if (!entries.ContainsKey(riskId) && entries.Count >= MaxRisks) throw new Refusal(409, "SoD catalogue capacity is reached. Existing annotations are retained.");
                    entries[riskId] = new JsonObject
                    {
                        ["metadata"] = metadata!.DeepClone(), ["observed_definition"] = definition,
                        ["reviewed_definition"] = (string?)metadata!["description_review_status"] == "Reviewed" ? definition : null, ["modified"] = Stamp(services.GetRequiredService<TimeProvider>()),
                    };
                    return storage.DeepClone().AsObject();
                }, ct);
                var after = Catalogue(c with { Storage = saved, Revision = revision!.Value + 1 });
                return Json(new JsonObject { ["item"] = after["items"]!.AsArray().First(i => (string)i!["risk_id"]! == riskId)!.DeepClone(), ["revision"] = revision + 1 });
            }
            catch (Refusal refusal) { return Detail(refusal.Status, refusal.Message); }
        });

        api.MapGet("/sod/catalogue-activities", async (HttpContext http, IServiceProvider services, CancellationToken ct) =>
        {
            string Q(string name) => http.Request.Query[name].FirstOrDefault() ?? "";
            var (search, current, sort) = (Q("search").Trim(), Q("current"), Q("sort") is { Length: > 0 } s ? s : "activity");
            var offset = int.TryParse(Q("offset") is { Length: > 0 } of ? of : "0", out var o) ? o : -1;
            var limit = int.TryParse(Q("limit") is { Length: > 0 } li ? li : "25", out var l) ? l : -1;
            if (Q("search").Length > 256 || current is not ("" or "current" or "historical") || sort is not ("activity" or "display_name" or "business_category" or "risks") || offset < 0 || limit is < 1 or > 100)
                return Detail(422, "Invalid activity query.");
            var c = await ContextAsync(services, ct);
            var result = ActivityCatalogue(c);
            var items = result["items"]!.AsArray().Select(i => i!.AsObject()).Where(i => (current.Length == 0 || (bool)i["current"]! == (current == "current"))
                && (search.Length == 0 || SearchFields(search, [(string?)i["activity"], (string?)i["display_name"], (string?)i["local"]!["business_category"], (string?)i["local"]!["explanation_en"],
                    .. i["risks"]!.AsArray().Select(r => (string?)r), .. i["tcodes"]!.AsArray().Select(t => (string?)t)]))).ToList();
            IEnumerable<JsonObject> ordered = sort switch
            {
                "risks" => items.OrderBy(i => i["risks"]!.AsArray().Count).ThenBy(i => Fold((string)i["activity"]!), StringComparer.Ordinal),
                "display_name" => items.OrderBy(i => Fold((string?)i["display_name"]), StringComparer.Ordinal).ThenBy(i => Fold((string)i["activity"]!), StringComparer.Ordinal),
                "business_category" => items.OrderBy(i => Fold((string?)i["local"]!["business_category"]), StringComparer.Ordinal).ThenBy(i => Fold((string)i["activity"]!), StringComparer.Ordinal),
                _ => items.OrderBy(i => Fold((string)i["activity"]!), StringComparer.Ordinal),
            };
            var list = ordered.ToList();
            if (Q("descending") is "true" or "1") list.Reverse();
            return Json(new JsonObject
            {
                ["items"] = new JsonArray([.. list.Skip(offset).Take(limit).Select(i => (JsonNode?)i.DeepClone())]), ["total"] = list.Count, ["offset"] = offset, ["limit"] = limit,
                ["revision"] = c.Revision, ["source_version"] = c.Snapshot.Sod?.ContentHash,
            });
        });

        api.MapGet("/sod/catalogue-activities/{**activity}", async (string activity, IServiceProvider services, CancellationToken ct) =>
        {
            var result = ActivityCatalogue(await ContextAsync(services, ct));
            var item = result["items"]!.AsArray().FirstOrDefault(i => (string)i!["activity"]! == activity);
            return item is null ? Detail(404, "Activity is not available in the retained source definitions.") : Json(new JsonObject { ["item"] = item.DeepClone(), ["revision"] = result["revision"]!.DeepClone() });
        });

        api.MapPost("/sod/catalogue-activities/{**activity}", async (string activity, HttpContext http, IServiceProvider services, CancellationToken ct) =>
        {
            var (body, invalid) = await V1Validation.ReadBody(http, ct);
            if (invalid is not null) return invalid;
            var errors = new List<object>();
            V1Validation.Extra(body!, ["expected_revision", "metadata"], errors);
            var revision = Revision(body!, errors);
            JsonObject? metadata = null;
            if (!body!.ContainsKey("metadata")) errors.Add(V1Validation.Error("missing", "metadata", "Field required"));
            else metadata = ValidateMetadata(body["metadata"], risk: false, errors);
            if (errors.Count > 0) return Results.Json(new { detail = errors }, statusCode: 422);
            var c = await ContextAsync(services, ct);
            if (c.Revision != revision) return Detail(409, "SoD catalogue changed. Reload before saving your edits.");
            if (!ActivityCatalogue(c)["items"]!.AsArray().Any(i => (string)i!["activity"]! == activity)) return Detail(404, "SoD activity is not present in the current or retained source history.");
            try
            {
                var saved = await SaveAsync(services, revision!.Value, Actors.Name(http), storage =>
                {
                    var stored = storage["activities"]!.AsObject();
                    if (!stored.ContainsKey(activity) && stored.Count >= MaxRisks) throw new Refusal(409, "SoD catalogue capacity is reached. Existing annotations are retained.");
                    stored[activity] = new JsonObject { ["metadata"] = metadata!.DeepClone(), ["modified"] = Stamp(services.GetRequiredService<TimeProvider>()) };
                    return storage.DeepClone().AsObject();
                }, ct);
                var after = ActivityCatalogue(c with { Storage = saved, Revision = revision!.Value + 1 });
                return Json(new JsonObject { ["item"] = after["items"]!.AsArray().First(i => (string)i!["activity"]! == activity)!.DeepClone(), ["revision"] = revision + 1 });
            }
            catch (Refusal refusal) { return Detail(refusal.Status, refusal.Message); }
        });
    }
}
