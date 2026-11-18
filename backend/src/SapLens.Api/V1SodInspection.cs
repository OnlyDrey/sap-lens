using System.Text.Json.Nodes;
using Microsoft.EntityFrameworkCore;
using SapLens.Application;
using SapLens.Domain.Csv;
using SapLens.Domain.Roles;
using SapLens.Domain.Sod;
using SapLens.Persistence;

namespace SapLens.Api;

/// <summary>Port of routers/data_sources.py sod_snapshot_inspection and inspect_sod_file with sod_import.inspection, inspect_file and
/// sod_metadata.coverage: read-only inspection of the active SoD snapshot and of a candidate SoD CSV. Nothing is imported, saved or cached.</summary>
public static class V1SodInspection
{
    private static readonly Dictionary<string, string> Meaning = new(StringComparer.Ordinal)
    {
        ["RISK"] = "Risk identifier (case-sensitive); groups the rows of one risk definition", ["CRITICITY"] = "Source criticality label, kept and shown literally as evidence",
        ["TYPE"] = "Risk type; only S risks are evaluated, others are kept but not evaluated", ["TEXT"] = "Source description of the risk",
        ["ACTVT1"] = "Name of the first required activity of the risk", ["ACTVT2"] = "Name of the second required activity of the risk",
        ["ACTIVITY_SLOT"] = "ACTVT1 or ACTVT2: the activity side this transaction mapping belongs to", ["ACTIVITY"] = "Activity that the transaction supplies on that side",
        ["TCODE"] = "Transaction code that supplies the activity", ["TTEXT"] = "Transaction description (optional; an empty value is only a warning)",
    };
    private static readonly Dictionary<string, string> SourceMetadata = new(StringComparer.Ordinal)
    {
        ["RULESET_ID"] = "ruleset_ids", ["RULESET_VERSION"] = "ruleset_versions", ["SOURCE_SYSTEM"] = "source_systems", ["LANGUAGE"] = "languages", ["LAST_CHANGED"] = "last_changed",
    };

    private static JsonArray Strings(IEnumerable<string> values) => new([.. values.Select(v => (JsonNode?)v)]);

    /// <summary>inspection: counts, column interpretation, validation checks and quality warnings of a parsed SoD dataset.</summary>
    public static JsonObject Inspection(SodDataset sod, IReadOnlyList<string> detected, IReadOnlyDictionary<string, string?> mapping, int parsedRows, string fileName,
        IEnumerable<IReadOnlyDictionary<string, string>> samples, JsonNode? descriptions)
    {
        var headers = CsvSpec.SodHeaders;
        var columns = headers.Select(f => (JsonNode?)new JsonObject
        {
            ["column"] = f, ["detected"] = mapping.GetValueOrDefault(f) is { Length: > 0 } m ? m : detected.Contains(f) ? f : "", ["meaning"] = Meaning[f], ["required"] = f != "TTEXT",
        }).ToList();
        var mappings = sod.Risks.SelectMany(V1SodCatalogue.Mappings).ToList();
        var unsupported = sod.Risks.Count(r => !((bool?)r["supported"] ?? false));
        var overlapping = sod.Risks.Count(r =>
        {
            var m = V1SodCatalogue.Mappings(r).ToList();
            return m.Where(x => x.Slot == "ACTVT1").Select(x => x.Tcode).Intersect(m.Where(x => x.Slot == "ACTVT2").Select(x => x.Tcode)).Any();
        });
        var missingText = sod.Records.Count(r => string.IsNullOrEmpty(r.GetValueOrDefault("TTEXT") as string));
        var duplicates = sod.DuplicateRows;
        var present = columns.Count(c => ((string)c!["detected"]!).Length > 0);
        JsonObject Check(string name, bool warning, string detail) => new() { ["name"] = name, ["status"] = warning ? "warning" : "passed", ["detail"] = detail };
        var checks = new JsonArray(
            Check("Documented columns", false, $"{present} of {headers.Length} documented columns were found; the schema is fixed; a mapping only chooses the source header of each column."),
            Check("Required values", false, "Every row has RISK, CRITICITY, TYPE, TEXT, ACTVT1, ACTVT2, ACTIVITY_SLOT, ACTIVITY and TCODE."),
            Check("Activity sides", false, "Every risk has transaction mappings for both activity sides."),
            Check("Evaluated risk types", unsupported > 0, unsupported > 0 ? $"{unsupported} risks have a TYPE other than S and are kept but not evaluated." : "Every risk has an evaluated TYPE (S)."),
            Check("Duplicate rows", duplicates > 0, duplicates > 0 ? $"{duplicates} identical rows were deduplicated." : "No duplicate rows."),
            Check("Transaction descriptions", missingText > 0, missingText > 0 ? $"{missingText} mappings have no TTEXT." : "Every mapping has a TTEXT."),
            Check("Overlapping transactions", overlapping > 0, overlapping > 0 ? $"{overlapping} risks share a transaction code between their two activity sides; the definition needs review." : "No risk shares a transaction code between its activity sides."));
        JsonObject Counter(IEnumerable<string> values)
        {
            var result = new JsonObject();
            foreach (var g in values.GroupBy(v => v, StringComparer.Ordinal).OrderBy(g => g.Key, StringComparer.Ordinal)) result[g.Key] = g.Count();
            return result;
        }
        return new JsonObject
        {
            ["columns"] = new JsonArray([.. columns]),
            ["counts"] = new JsonObject
            {
                ["parsed_rows"] = parsedRows > 0 ? parsedRows : sod.Records.Count, ["records"] = sod.Records.Count, ["duplicate_rows"] = duplicates, ["risks"] = sod.Risks.Count,
                ["evaluated_risks"] = sod.Risks.Count - unsupported, ["unsupported_risks"] = unsupported, ["activities"] = mappings.Select(m => m.Activity).Distinct().Count(),
                ["transactions"] = mappings.Select(m => m.Tcode).Distinct().Count(),
            },
            ["criticality"] = Counter(sod.Risks.Select(r => (string)r["criticality"]!)), ["types"] = Counter(sod.Risks.Select(r => (string)r["risk_type"]!)),
            ["checks"] = checks, ["warnings"] = Strings(sod.Warnings), ["file_name"] = fileName, ["descriptions"] = descriptions,
            ["samples"] = new JsonArray([.. samples.Take(20).Select(r => (JsonNode?)new JsonObject(headers.Select(h => KeyValuePair.Create(h, (JsonNode?)(r.GetValueOrDefault(h) ?? "")))))]),
        };
    }

    private static JsonObject Indicator(int total, int imported, int local, bool columnPresent, int differing = 0)
    {
        var missing = total - imported - local;
        var available = imported + local;
        var state = total > 0 && missing == 0 ? "complete" : !columnPresent && imported == 0 ? "column_absent" : total > 0 ? "values_missing" : "empty";
        var sourceState = total > 0 && imported == total ? "complete" : !columnPresent && imported == 0 ? "column_absent" : total > 0 ? "values_missing" : "empty";
        return new JsonObject
        {
            ["label"] = "", ["total"] = total, ["imported"] = imported, ["local_fallback"] = local, ["available"] = available, ["missing"] = missing,
            ["percent"] = total > 0 ? Math.Round(100.0 * available / total, 1) : 0.0, ["imported_percent"] = total > 0 ? Math.Round(100.0 * imported / total, 1) : 0.0,
            ["column_present"] = columnPresent, ["state"] = state, ["source_state"] = sourceState, ["differing"] = differing,
        };
    }

    /// <summary>sod_metadata.coverage: completeness of descriptions over distinct risks, activities and transaction codes, and the optional columns found.</summary>
    public static JsonObject Coverage(V1SodCatalogue.Context c, SodDataset sod, IReadOnlyCollection<string> detected)
    {
        var importedRisks = sod.Metadata?.Risks ?? [];
        var importedActivities = sod.Metadata?.Activities ?? [];
        var riskIds = sod.Risks.Select(r => (string)r["risk_id"]!).ToHashSet(StringComparer.Ordinal);
        var activityIds = new HashSet<string>(StringComparer.Ordinal);
        var transactions = new Dictionary<string, bool>(StringComparer.Ordinal);
        foreach (var m in sod.Risks.SelectMany(V1SodCatalogue.Mappings)) { activityIds.Add(m.Activity); transactions[m.Tcode] = transactions.GetValueOrDefault(m.Tcode) || m.Ttext.Length > 0; }
        var entries = c.Storage["entries"]!.AsObject();
        var stored = c.Storage["activities"]!.AsObject();
        var referenceRisks = c.Reference["risks"] as JsonObject ?? [];
        var referenceActivities = c.Reference["activities"] as JsonObject ?? [];
        JsonObject Over(IEnumerable<string> ids, SortedDictionary<string, SortedDictionary<string, string>> imported, JsonObject local, JsonObject library, string sourceKey, string attribute, string column, string id, string label)
        {
            var list = ids.ToList();
            var origins = list.Select(k => (string?)V1SodCatalogue.Resolve(imported.GetValueOrDefault(k)?.GetValueOrDefault(sourceKey), (string?)local[k]?["metadata"]?[attribute] ?? "", (string?)library[k]?[attribute] ?? "")["origin"]).ToList();
            var differing = list.Count(k => (string?)local[k]?["metadata"]?[attribute] is { Length: > 0 } l && imported.GetValueOrDefault(k)?.GetValueOrDefault(sourceKey) is { Length: > 0 } i && l != i);
            var (importedCount, localCount, referenceCount) = (origins.Count(o => o == "imported"), origins.Count(o => o == "local"), origins.Count(o => o == "reference"));
            var result = Indicator(list.Count, importedCount, localCount + referenceCount, detected.Contains(column), differing);
            result["local_fallback"] = localCount; result["reference"] = referenceCount; result["id"] = id; result["label"] = label; result["column"] = column;
            return result;
        }
        var transactionIndicator = Indicator(transactions.Count, transactions.Values.Count(v => v), 0, true);
        transactionIndicator["id"] = "transaction_descriptions"; transactionIndicator["label"] = "Transaction descriptions"; transactionIndicator["column"] = "TTEXT";
        var resolved = V1SodCatalogue.Lookup(c);
        var reference = c.Reference;
        return new JsonObject
        {
            ["indicators"] = new JsonArray(
                Over(riskIds, importedRisks, entries, referenceRisks, "name", "display_name", "RISK_NAME", "risk_names", "Risk display names"),
                Over(riskIds, importedRisks, entries, referenceRisks, "description", "explanation_en", "RISK_DESCRIPTION", "risk_descriptions", "Risk descriptions"),
                Over(activityIds, importedActivities, stored, referenceActivities, "name", "display_name", "ACTIVITY_NAME", "activity_names", "Activity display names"),
                Over(activityIds, importedActivities, stored, referenceActivities, "description", "explanation_en", "ACTIVITY_DESCRIPTION", "activity_descriptions", "Activity descriptions"),
                transactionIndicator),
            ["reference"] = new JsonObject
            {
                ["origin"] = reference["origin"]?.DeepClone(), ["library_version"] = reference["library_version"]?.DeepClone(), ["source"] = reference["source"]?.DeepClone(),
                ["version"] = reference["version"]?.DeepClone(), ["revision"] = reference["revision"]?.DeepClone(), ["digest"] = reference["digest"]?.DeepClone(),
                ["imported_at"] = reference["imported_at"]?.DeepClone(), ["risks"] = referenceRisks.Count, ["activities"] = referenceActivities.Count,
                ["terms"] = (reference["terms"] as JsonObject)?.Count ?? (reference["terms"] as JsonArray)?.Count ?? 0,
                ["matched_risks"] = riskIds.Count(referenceRisks.ContainsKey), ["matched_activities"] = activityIds.Count(referenceActivities.ContainsKey),
                ["unmatched_risks"] = Strings(referenceRisks.Select(p => p.Key).Where(k => !riskIds.Contains(k)).Order(StringComparer.Ordinal)),
                ["unmatched_activities"] = Strings(referenceActivities.Select(p => p.Key).Where(k => !activityIds.Contains(k)).Order(StringComparer.Ordinal)),
            },
            ["optional_columns"] = new JsonObject { ["detected"] = Strings(CsvSpec.SodOptional.Where(detected.Contains)), ["missing"] = Strings(CsvSpec.SodOptional.Where(f => !detected.Contains(f))) },
            ["source_facts"] = new JsonArray([.. SourceMetadata.Select(p => (JsonNode?)new JsonObject
            {
                ["field"] = p.Key, ["detected"] = detected.Contains(p.Key), ["values"] = Strings(sod.Metadata?.Source.GetValueOrDefault(p.Value) ?? []),
            })]),
            ["sample"] = new JsonArray([.. resolved["risks"]!.AsObject().Where(p => p.Value!["name"] is not null || p.Value!["description"] is not null).Take(5).Select(p =>
            {
                var item = new JsonObject { ["id"] = p.Key, ["kind"] = "risk" };
                foreach (var name in new[] { "name", "description" }) if (p.Value![name] is { } v) item[name] = v.DeepClone();
                item["origin"] = p.Value!["origin"]?.DeepClone();
                return (JsonNode?)item;
            })]),
            ["note"] = "Counts use distinct risks, activities and transaction codes. Priority: non-empty local overrides, imported metadata, then curated reference definitions. Reference records never activate risks or activities; no description is generated.",
        };
    }

    private static JsonObject Metadata(JsonObject settings)
    {
        var reference = settings["data_lifecycle"]?["sources"]?["sod"];
        var format = settings["sod_import"] as JsonObject ?? [];
        return new JsonObject
        {
            ["path"] = settings["sod_csv_path"]?.DeepClone(), ["mode"] = settings["source_modes"]?["sod"]?.DeepClone(), ["feature_enabled"] = settings["features"]?["sod"]?.DeepClone(),
            ["format"] = new JsonObject { ["delimiter"] = format["delimiter"]?.DeepClone(), ["encoding"] = format["encoding"]?.DeepClone(), ["mapping"] = format["mapping"]?.DeepClone() },
            ["imported_at"] = reference?["imported_at"]?.DeepClone(), ["checked_at"] = reference?["checked_at"]?.DeepClone(), ["snapshot"] = reference?["snapshot"]?.DeepClone(),
        };
    }

    public static void Map(RouteGroupBuilder api)
    {
        api.MapGet("/data-sources/sod/inspection", async (HttpContext http, CancellationToken ct) =>
        {
            var services = http.RequestServices;
            var c = await V1SodCatalogue.ContextAsync(services, ct);
            var metadata = Metadata(c.Settings);
            if (c.Snapshot.Sod is not { } sod) return Results.Content(new JsonObject { ["loaded"] = false, ["metadata"] = metadata }.ToJsonString(), "application/json");
            await using var db = await services.GetRequiredService<IDbContextFactory<SapLensDb>>().CreateDbContextAsync(ct);
            var dataset = await db.Datasets.AsNoTracking().FirstAsync(d => d.Id == c.Snapshot.Ids.Sod, ct);
            var report = dataset.ReportJson is null ? new JsonObject() : JsonNode.Parse(dataset.ReportJson) as JsonObject ?? [];
            var detected = (report["detected_columns"] as JsonArray ?? []).Select(v => (string)v!).ToList();
            var mapping = (report["resolved_mapping"] as JsonObject ?? []).ToDictionary(p => p.Key, p => (string?)p.Value, StringComparer.Ordinal);
            var records = await SnapshotService.RecordsAsync(db, dataset.Id, ct);
            if (detected.Count == 0 && records.Count > 0) detected = [.. records[0].Keys];
            var result = new JsonObject { ["loaded"] = true, ["metadata"] = metadata };
            foreach (var (k, v) in Inspection(sod, detected, mapping, (int?)report["parsed_rows"] ?? 0, (string?)report["file_name"] ?? dataset.FileName ?? "", records, Coverage(c, sod, detected))) result[k] = v?.DeepClone();
            return Results.Content(result.ToJsonString(), "application/json");
        });

        api.MapPost("/data-sources/sod/inspect", async (HttpContext http, CancellationToken ct) =>
        {
            var (body, invalid) = await V1Validation.ReadBody(http, ct);
            if (invalid is not null) return invalid;
            var errors = new List<object>();
            V1Validation.Extra(body!, ["path", "delimiter", "encoding", "mapping"], errors);
            var path = V1Validation.Text(body!, "path", 1, 4096, true, errors)?.Trim() ?? "";
            var delimiter = (string?)body!["delimiter"] ?? "auto";
            var encoding = (string?)body["encoding"] ?? "auto";
            if (delimiter is not ("auto" or "," or ";" or "\t" or "|")) errors.Add(V1Validation.Error("literal_error", "delimiter", "Input should be 'auto', ',', ';', '\\t' or '|'"));
            if (encoding is not ("auto" or "utf-8-sig" or "utf-16" or "cp1252")) errors.Add(V1Validation.Error("literal_error", "encoding", "Input should be 'auto', 'utf-8-sig', 'utf-16' or 'cp1252'"));
            var manual = new Dictionary<string, string>(StringComparer.Ordinal);
            if (body["mapping"] is JsonObject m)
            {
                if (m.Count > 40) errors.Add(V1Validation.Error("too_long", "mapping", "Dictionary should have at most 40 items"));
                foreach (var (k, v) in m) if (v is JsonValue value && value.TryGetValue<string>(out var text)) manual[k] = text; else errors.Add(V1Validation.Error("string_type", "mapping", "Input should be a valid string"));
            }
            if (errors.Count > 0) return Results.Json(new { detail = errors }, statusCode: 422);
            string file;
            try { file = V1ImportPreview.Confine(http, path); }
            catch (ArgumentException error) { return SodScope.Problem(400, error.Message); }
            var profile = new CsvProfile("default", 1, delimiter, encoding, manual);
            var result = new JsonObject
            {
                ["valid"] = false, ["errors"] = new JsonArray(), ["format"] = new JsonObject { ["delimiter"] = delimiter, ["encoding"] = encoding }, ["headers"] = new JsonArray(), ["issues"] = new JsonArray(),
                ["file_name"] = Path.GetFileName(file),
            };
            HeaderInspection? head = null;
            CsvImport import;
            try { import = new CsvImport(file, profile, CsvSpec.Sod); }
            catch (Exception error) when (error is ArgumentException or DomainValidationException) { return SodScope.Problem(400, error.Message); }
            catch (Exception error) when (error is IOException or UnauthorizedAccessException) { return SodScope.Problem(400, "The CSV could not be opened. Check the path and file permissions."); }
            try { head = import.InspectHeader(); }
            catch (DomainValidationException error) { result["errors"]!.AsArray().Add(error.Message); }
            catch (Exception error) when (error is IOException or UnauthorizedAccessException or InvalidDataException or System.Text.DecoderFallbackException)
            { result["errors"]!.AsArray().Add("The CSV header could not be read. Check the path, encoding and delimiter."); }
            var proposed = head?.ProposedMapping ?? new Dictionary<string, string>();
            if (head is not null)
            {
                result["headers"] = Strings(head.DetectedColumns);
                result["issues"] = JsonSerializerNode(head.Issues);
                result["format"] = new JsonObject { ["delimiter"] = head.Delimiter, ["encoding"] = head.Encoding };
            }
            result["columns"] = new JsonArray([.. CsvSpec.SodHeaders.Select(f =>
            {
                var hand = manual.GetValueOrDefault(f, "");
                var found = hand.Length > 0 ? hand : proposed.GetValueOrDefault(f, "");
                return (JsonNode?)new JsonObject { ["column"] = f, ["detected"] = found, ["state"] = hand.Length > 0 ? "manual" : found.Length > 0 ? "detected" : "missing", ["meaning"] = Meaning[f], ["required"] = f != "TTEXT" };
            })]);
            result["proposed_mapping"] = new JsonObject(proposed.Select(p => KeyValuePair.Create(p.Key, (JsonNode?)p.Value)));
            if (head is null) return Results.Content(result.ToJsonString(), "application/json");
            try
            {
                var records = import.Records(ct).ToList();
                var sod = SodSource.Build(records, import.Report.Warnings);
                var c = await V1SodCatalogue.ContextAsync(http.RequestServices, ct);
                var detail = Inspection(sod, head.DetectedColumns, new Dictionary<string, string?>(), import.Report.ParsedRows, Path.GetFileName(file), records, null);
                result["valid"] = true;
                foreach (var key in new[] { "counts", "criticality", "types", "checks", "warnings", "samples" }) result[key] = detail[key]!.DeepClone();
                result["descriptions"] = Coverage(c, sod, head.DetectedColumns);
            }
            catch (DomainValidationException error) { result["errors"]!.AsArray().Add(error.Message); }
            catch (Exception error) when (error is IOException or UnauthorizedAccessException or InvalidDataException or System.Text.DecoderFallbackException)
            { result["errors"]!.AsArray().Add("The CSV could not be parsed. Check the delimiter, encoding, mapping and that every row has the header width."); }
            return Results.Content(result.ToJsonString(), "application/json");
        });
    }

    private static JsonNode? JsonSerializerNode(object value) => System.Text.Json.JsonSerializer.SerializeToNode(value, new System.Text.Json.JsonSerializerOptions { PropertyNamingPolicy = System.Text.Json.JsonNamingPolicy.SnakeCaseLower });
}
