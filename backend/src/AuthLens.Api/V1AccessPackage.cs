using System.Globalization;
using System.Text;
using System.Text.Json.Nodes;
using AuthLens.Application;
using AuthLens.Domain.Roles;

namespace AuthLens.Api;

/// <summary>Port of the routers/roles.py access-package routes: organizational suffix evidence, the package preview and its CSV export.
/// Pure derivations over the active snapshots; nothing changes SAP access or stored data.</summary>
public static class V1AccessPackage
{
    public static readonly string[] Columns = ["Generated SAP Role Name", "Role Description", "Suffix", "Validation"];

    public static void Map(RouteGroupBuilder api)
    {
        api.MapGet("/roles/naming", async (SnapshotService snapshots, CancellationToken ct) =>
        {
            var state = await snapshots.GetAsync(ct);
            var names = state.Catalogue.Ordered.Select(r => r.AgrName).Concat(state.Users.Assignments.Select(a => a.RoleName)).ToList();
            var evidence = AccessPackage.NamingEvidence(names);
            return Results.Ok(new
            {
                suffixes = evidence.OrderByDescending(p => p.Value).ThenBy(p => p.Key, StringComparer.Ordinal).Select(p => new { value = p.Key, roles = p.Value }).ToList(),
                evidence_roles = names.Count,
            });
        });

        api.MapPost("/roles/package/preview", async (HttpContext http, SnapshotService snapshots, CancellationToken ct) =>
        {
            var (rows, invalid) = await Rows(http, snapshots, ct);
            if (invalid is not null) return invalid;
            return Results.Content(new JsonObject { ["items"] = new JsonArray([.. rows!.Select(Row)]), ["exportable"] = AccessPackage.CsvRows(rows!).Count }.ToJsonString(), "application/json");
        });

        api.MapPost("/roles/package/export", async (HttpContext http, SnapshotService snapshots, CancellationToken ct) =>
        {
            var (rows, invalid) = await Rows(http, snapshots, ct);
            if (invalid is not null) return invalid;
            var lines = AccessPackage.CsvRows(rows!);
            if (lines.Count == 0) return Results.Json(new { detail = "No valid generated role names to export." }, statusCode: 422);
            var csv = new StringBuilder("﻿");
            V1Csv.Line(csv, Columns, cells: false);
            foreach (var line in lines) V1Csv.Line(csv, line, cells: true);
            http.Response.Headers.CacheControl = "no-store";
            http.Response.Headers.ContentDisposition = $"attachment; filename=\"authlens-access-package-{DateTime.Now.ToString("yyyy-MM-dd", CultureInfo.InvariantCulture)}.csv\"";
            return Results.Text(csv.ToString(), "text/csv; charset=utf-8", Encoding.UTF8);
        });
    }

    private static JsonObject Row(PackageRow r) => new()
    {
        ["role"] = r.Role, ["description"] = r.Description, ["suffix"] = r.Suffix, ["suffix_source"] = r.SuffixSource, ["suffix_eligible"] = r.SuffixEligible,
        ["suffix_note"] = r.SuffixNote, ["name"] = r.Name, ["status"] = r.Status, ["validation"] = r.Validation, ["exportable"] = r.Exportable,
        ["messages"] = new JsonArray([.. r.Messages.Select(m => (JsonNode?)m)]),
        ["catalogue"] = r.Catalogue is null ? null : new JsonObject { ["status"] = r.Catalogue.Status, ["candidates"] = new JsonArray([.. r.Catalogue.Candidates.Select(c => (JsonNode?)c)]) },
        ["source"] = r.Source,
    };

    /// <summary>PackageBody (StrictModel): default_suffix (max 64) and items [{role 1..512, suffix max 64, source catalogue|release}].</summary>
    private static async Task<(List<PackageRow>?, IResult?)> Rows(HttpContext http, SnapshotService snapshots, CancellationToken ct)
    {
        var (body, invalid) = await V1Validation.ReadBody(http, ct);
        if (invalid is not null) return (null, invalid);
        var errors = new List<object>();
        V1Validation.Extra(body!, ["default_suffix", "items"], errors);
        var fallback = V1Validation.Text(body!, "default_suffix", 0, 64, false, errors);
        var items = new List<PackageItem>();
        if (!body!.TryGetPropertyValue("items", out var itemsNode)) errors.Add(V1Validation.Error("missing", "items", "Field required"));
        else if (itemsNode is not JsonArray list) errors.Add(V1Validation.Error("list_type", "items", "Input should be a valid list"));
        else
            for (var i = 0; i < list.Count; i++)
            {
                object[] path = ["items", i];
                if (list[i] is not JsonObject item) { errors.Add(V1Validation.At("model_type", "Input should be a valid dictionary or instance of PackageItem", "body", "items", i)); continue; }
                V1Validation.Extra(item, ["role", "suffix", "source"], errors, path);
                var role = V1Validation.Text(item, "role", 1, 512, true, errors, path);
                var suffix = V1Validation.Text(item, "suffix", 0, 64, false, errors, path);
                var source = "catalogue";
                if (item.TryGetPropertyValue("source", out var sourceNode))
                {
                    if (sourceNode?.GetValueKind() == System.Text.Json.JsonValueKind.String && (string)sourceNode! is "catalogue" or "release") source = (string)sourceNode!;
                    else errors.Add(V1Validation.Error("literal_error", "source", "Input should be 'catalogue' or 'release'", path));
                }
                if (role is not null && suffix is not null) items.Add(new PackageItem(role, suffix, source));
            }
        if (errors.Count > 0) return (null, Results.Json(new { detail = errors }, statusCode: 422));

        var state = await snapshots.GetAsync(ct);
        var catalogue = new Dictionary<string, string>(StringComparer.Ordinal);
        foreach (var r in state.Catalogue.Ordered) catalogue[r.AgrName] = r.Text ?? "";
        var release = items.Any(i => i.Source == "release")
            ? state.Users.Assignments.Where(a => a.Scope == "release").Select(a => RoleNames.Normalize(a.RoleName)).ToHashSet(StringComparer.Ordinal)
            : [];
        return (AccessPackage.Preview(fallback, items, catalogue, release, state.Users.Assignments.Select(a => a.RoleName)), null);
    }
}

/// <summary>v1 CSV conventions: semicolon, every field quoted, CRLF, and spreadsheet formula neutralization (csv_exports.spreadsheet_cell).</summary>
public static class V1Csv
{
    public static string Cell(string? value)
    {
        var text = value ?? "";
        var i = 0;
        while (i < text.Length && (char.IsWhiteSpace(text[i]) || text[i] < 0x20 || text[i] == '﻿')) i++;
        var formula = i < text.Length && text[i] is '=' or '+' or '@' or '-';
        return formula || text.StartsWith('\t') || text.StartsWith('\r') || text.StartsWith('\n') ? "'" + text : text;
    }

    public static void Line(StringBuilder csv, IEnumerable<string?> values, bool cells)
    {
        csv.Append(string.Join(';', values.Select(v => "\"" + (cells ? Cell(v) : v ?? "").Replace("\"", "\"\"", StringComparison.Ordinal) + "\""))).Append("\r\n");
    }
}
