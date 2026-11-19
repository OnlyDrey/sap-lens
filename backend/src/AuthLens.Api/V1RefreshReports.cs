using System.Text;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;
using Microsoft.EntityFrameworkCore;
using AuthLens.Domain.Imports;
using AuthLens.Persistence;

namespace AuthLens.Api;

/// <summary>MIG-010, port of routers/data_sources.py `details` and `export`: the per-record changes of a retained refresh report, filtered by source,
/// change type and text, as a bounded page or as a CSV (every field quoted, spreadsheet formulas neutralized). Reports are private local records:
/// only the five retained ones (settings `data_lifecycle.history`) are served, and they are never part of diagnostics.</summary>
public static partial class V1RefreshReports
{
    [GeneratedRegex("^(roles|users|employees|sod)?$")]
    private static partial Regex SourcePattern();
    [GeneratedRegex("^(added|removed|modified)?$")]
    private static partial Regex KindPattern();

    public static void Map(RouteGroupBuilder api)
    {
        api.MapGet("/data-sources/reports/{identity}", async (string identity, HttpContext http, V1Settings settings, IDbContextFactory<AuthLensDb> factory, CancellationToken ct) =>
        {
            var (filter, invalid) = Query(http, paged: true);
            if (invalid is not null) return invalid;
            var (data, missing) = await ReportAsync(identity, settings, factory, ct);
            if (missing is not null) return missing;
            var page = new JsonArray();
            var total = 0;
            foreach (var row in Rows(data!, filter))
            {
                if (filter.Offset <= total && total < filter.Offset + filter.Limit) page.Add(row);
                total++;
            }
            var sources = new JsonArray([.. data!["sources"]!.AsArray().Select(result =>
            {
                var copy = result!.DeepClone().AsObject();
                copy.Remove("changes");
                return (JsonNode)copy;
            })]);
            return Results.Content(new JsonObject
            {
                ["id"] = identity, ["timestamp"] = data["timestamp"]?.DeepClone(), ["status"] = data["status"]?.DeepClone(), ["sources"] = sources,
                ["items"] = page, ["total"] = total, ["offset"] = filter.Offset, ["limit"] = filter.Limit,
            }.ToJsonString(), "application/json");
        });

        api.MapGet("/data-sources/reports/{identity}/export", async (string identity, HttpContext http, V1Settings settings, IDbContextFactory<AuthLensDb> factory, CancellationToken ct) =>
        {
            var (filter, invalid) = Query(http, paged: false);
            if (invalid is not null) return invalid;
            var (data, missing) = await ReportAsync(identity, settings, factory, ct);
            if (missing is not null) return missing;
            var csv = new StringBuilder("﻿");
            Line(csv, ["Timestamp", "Source", "Change", "Identifier", "Field", "Before", "After"]);
            var timestamp = (string?)data!["timestamp"] ?? "";
            foreach (var row in Rows(data, filter))
            {
                var fields = row["fields"]!.AsArray();
                IEnumerable<(string Field, string Before, string After)> lines = fields.Count > 0
                    ? fields.Select(f => ((string)f!["field"]!, (string?)f["before"] ?? "", (string?)f["after"] ?? ""))
                    : Keys(row).Select(key => (key, (string?)row["before"]?[key] ?? "", (string?)row["after"]?[key] ?? ""));
                foreach (var (field, before, after) in lines)
                    Line(csv, [timestamp, (string?)row["source_name"], (string?)row["type"], (string?)row["identifier"], field, before, after]);
            }
            http.Response.Headers.ContentDisposition = "attachment; filename=\"AuthLens-refresh-changes.csv\"";
            return Results.Text(csv.ToString(), "text/csv; charset=utf-8", Encoding.UTF8);
        });
    }

    /// <summary>The stored form of diff_records `changes`: added rows keep `after`, removed rows `before`, modifications both and the changed fields.</summary>
    public static JsonArray Changes(IEnumerable<RecordChange> changes) => new([.. changes.Select(change =>
    {
        var node = new JsonObject
        {
            ["type"] = change.Type, ["identifier"] = change.Identifier,
            ["fields"] = new JsonArray([.. change.Fields.Select(f => (JsonNode)new JsonObject { ["field"] = f.Field, ["before"] = f.Before, ["after"] = f.After })]),
        };
        if (change.Before is not null) node["before"] = Row(change.Before);
        if (change.After is not null) node["after"] = Row(change.After);
        return (JsonNode)node;
    })]);

    private static JsonObject Row(IReadOnlyDictionary<string, string> row) => new(row.Select(p => KeyValuePair.Create(p.Key, (JsonNode?)JsonValue.Create(p.Value))));

    private sealed record Filter(string Source, string Kind, string Search, int Offset, int Limit);

    /// <summary>The v1 query model: source and change-type patterns, search at most 256 characters, offset >= 0, limit 1-100 (default 25). Pydantic 422.</summary>
    private static (Filter Filter, IResult? Invalid) Query(HttpContext http, bool paged)
    {
        var q = http.Request.Query;
        var errors = new List<object>();
        string Text(string name) => q.TryGetValue(name, out var value) ? value.ToString() : "";
        var source = Text("source");
        var kind = Text("kind");
        var search = Text("search");
        if (!SourcePattern().IsMatch(source)) errors.Add(V1Validation.At("string_pattern_mismatch", "String should match pattern '^(roles|users|employees|sod)?$'", "query", "source"));
        if (!KindPattern().IsMatch(kind)) errors.Add(V1Validation.At("string_pattern_mismatch", "String should match pattern '^(added|removed|modified)?$'", "query", "kind"));
        if (V1Validation.Length(search) > 256) errors.Add(V1Validation.At("string_too_long", "String should have at most 256 characters", "query", "search"));
        int Number(string name, int fallback, int min, int? max)
        {
            if (!paged || !q.TryGetValue(name, out var raw)) return fallback;
            if (!int.TryParse(raw.ToString().Trim(), System.Globalization.NumberStyles.AllowLeadingSign, System.Globalization.CultureInfo.InvariantCulture, out var value))
            { errors.Add(V1Validation.At("int_parsing", "Input should be a valid integer, unable to parse string as an integer", "query", name)); return fallback; }
            if (value < min) errors.Add(V1Validation.At("greater_than_equal", $"Input should be greater than or equal to {min}", "query", name));
            else if (max is not null && value > max) errors.Add(V1Validation.At("less_than_equal", $"Input should be less than or equal to {max}", "query", name));
            return value;
        }
        var offset = Number("offset", 0, 0, null);
        var limit = Number("limit", 25, 1, 100);
        return (new Filter(source, kind, search, offset, limit), errors.Count > 0 ? Results.Json(new { detail = errors }, statusCode: 422) : null);
    }

    /// <summary>v1 `report`: only a report still listed in the retained history is served (404 otherwise); a listed report that cannot be read is a 409.</summary>
    private static async Task<(JsonObject? Data, IResult? Error)> ReportAsync(string identity, V1Settings settings, IDbContextFactory<AuthLensDb> factory, CancellationToken ct)
    {
        var current = await settings.GetAsync(ct);
        var retained = current["data_lifecycle"]?["history"]?.AsArray().Any(id => (string?)id == identity) ?? false;
        if (!retained) return (null, Results.Json(new { detail = "Refresh report is no longer retained." }, statusCode: 404));
        await using var db = await factory.CreateDbContextAsync(ct);
        var stored = await db.RefreshReports.AsNoTracking().FirstOrDefaultAsync(r => r.Id == identity, ct);
        try
        {
            if (stored is not null && JsonNode.Parse(stored.Json) is JsonObject data && data["sources"] is JsonArray) return (data, null);
        }
        catch (System.Text.Json.JsonException) { }
        return (null, Results.Json(new { detail = "The private refresh report is unavailable. Check local storage." }, statusCode: 409));
    }

    /// <summary>v1 `changes`: the changes of updated or unchanged sources, filtered by source, type and a case-insensitive term over the identifier and
    /// every before/after value, each with its source and source name.</summary>
    private static IEnumerable<JsonObject> Rows(JsonObject data, Filter filter)
    {
        var term = Fold(filter.Search.Trim());
        foreach (var result in data["sources"]!.AsArray().OfType<JsonObject>())
        {
            if ((string?)result["status"] is not ("updated" or "unchanged") || filter.Source.Length > 0 && (string?)result["source"] != filter.Source) continue;
            foreach (var change in (result["changes"] as JsonArray ?? []).OfType<JsonObject>())
            {
                if (filter.Kind.Length > 0 && (string?)change["type"] != filter.Kind) continue;
                if (term.Length > 0)
                {
                    var values = new[] { "before", "after" }.SelectMany(side => (change[side] as JsonObject ?? []).Select(p => p.Value?.ToString() ?? "None"));
                    if (!Fold((string?)change["identifier"] + " " + string.Join(' ', values)).Contains(term, StringComparison.Ordinal)) continue;
                }
                var row = new JsonObject { ["source"] = result["source"]?.DeepClone(), ["source_name"] = result["name"]?.DeepClone() };
                foreach (var (key, value) in change) row[key] = value?.DeepClone();
                yield return row;
            }
        }
    }

    private static IEnumerable<string> Keys(JsonObject row) =>
        new[] { "before", "after" }.SelectMany(side => (row[side] as JsonObject ?? []).Select(p => p.Key)).Distinct().Order(StringComparer.Ordinal);

    /// <summary>str.casefold for the identifiers and values of SAP exports.</summary>
    private static string Fold(string text) => AuthLens.Domain.Text.PythonText.Casefold(text);

    /// <summary>csv.writer(quoting=QUOTE_ALL): comma, every field quoted, quotes doubled, CRLF; each cell through spreadsheet_cell.</summary>
    private static void Line(StringBuilder csv, IEnumerable<string?> values) =>
        csv.Append(string.Join(',', values.Select(v => "\"" + V1Csv.Cell(v).Replace("\"", "\"\"", StringComparison.Ordinal) + "\""))).Append("\r\n");
}
