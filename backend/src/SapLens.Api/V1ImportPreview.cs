using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;
using SapLens.Domain.Catalogue;
using SapLens.Domain.Csv;
using SapLens.Domain.Roles;
using SapLens.Domain.Users;

namespace SapLens.Api;

/// <summary>MIG-009, port of configuration_routes.import_headers / preview_import / user_headers / user_preview: header inspection and a full parse
/// of a CSV with an import profile, before the source is chosen. Nothing is imported or stored. The same CSV readers as the real import are used
/// (CsvImport, CatalogueBuilder, UserDirectoryBuilder), so a preview reports exactly what an import would do.
/// Paths: on the Desktop any absolute .csv path (v1); on a Server only files inside the server's own source folder (`data/sources`, where uploads are
/// kept), never a path a browser names elsewhere (v1 confines Server paths to its configured source root and uploads).</summary>
public static partial class V1ImportPreview
{
    [GeneratedRegex("^[A-Za-z0-9_-]{1,40}$")]
    private static partial Regex ProfileId();

    private const string RoleHeadersFailed = "Could not inspect the CSV header. Check path, encoding and delimiter.";
    private const string RolePreviewFailed = "Import preview failed. Check the absolute path, encoding, delimiter, mappings and required AGR_NAME column.";
    private const string UserHeadersFailed = "Could not inspect user CSV. Check path, encoding and delimiter.";
    private const string UserPreviewFailed = "User CSV preview failed. Check USERNAME, mappings, row widths and YYYY-MM-DD/YYYYMMDD dates.";
    private static readonly string[] UserSampleKeys = ["USERNAME", "ROLE_NAME", "USER_GROUP", "FIRST_NAME", "LAST_NAME", "EMAIL", "ROLE_VALID_FROM", "ROLE_VALID_TO"];

    public static void Map(RouteGroupBuilder api)
    {
        api.MapPost("/import/headers", (HttpContext http, CancellationToken ct) => Run(http, CsvSpec.Roles, headers: true, ct));
        api.MapPost("/import/preview", (HttpContext http, CancellationToken ct) => Run(http, CsvSpec.Roles, headers: false, ct));
        api.MapPost("/user-import/headers", (HttpContext http, CancellationToken ct) => Run(http, CsvSpec.Users, headers: true, ct));
        api.MapPost("/user-import/preview", (HttpContext http, CancellationToken ct) => Run(http, CsvSpec.Users, headers: false, ct));
    }

    private static IResult Detail(int status, object detail) => Results.Json(new { detail }, statusCode: status);

    private static async Task<IResult> Run(HttpContext http, CsvSpec spec, bool headers, CancellationToken ct)
    {
        var (body, invalid) = await V1Validation.ReadBody(http, ct);
        if (invalid is not null) return invalid;
        var errors = new List<object>();
        V1Validation.Extra(body!, ["data_csv_path", "profile"], errors);
        var path = V1Validation.Text(body!, "data_csv_path", 1, 4096, required: true, errors);
        CsvProfile? requested = null;
        if (body!["profile"] is JsonObject profile) requested = Profile(profile, spec.Fields, errors);
        else if (body.ContainsKey("profile") && body["profile"] is not null) errors.Add(V1Validation.Error("model_type", "profile", "Input should be a valid dictionary or instance of ImportProfile"));
        if (errors.Count > 0) return Results.Json(new { detail = errors }, statusCode: 422);

        var users = spec == CsvSpec.Users;
        var settings = await http.RequestServices.GetRequiredService<V1Settings>().GetAsync(ct);
        var csvProfile = requested ?? Active(settings, users);
        var failure = headers ? users ? UserHeadersFailed : RoleHeadersFailed : users ? UserPreviewFailed : RolePreviewFailed;
        try
        {
            var import = new CsvImport(Confine(http, path!), csvProfile, spec);
            if (headers)
            {
                var inspection = import.InspectHeader();
                return Json(new Dictionary<string, object?>
                {
                    ["detected_columns"] = inspection.DetectedColumns, ["delimiter"] = inspection.Delimiter, ["encoding"] = inspection.Encoding,
                    ["proposed_mapping"] = inspection.ProposedMapping, ["issues"] = inspection.Issues,
                });
            }
            var records = import.Records(ct).ToList();
            var report = BaseReport(import.Report);
            if (users)
            {
                var snapshot = await http.RequestServices.GetRequiredService<SapLens.Application.SnapshotService>().GetAsync(ct);
                var directory = UserDirectoryBuilder.Build(records, snapshot.Catalogue);
                report["unique_users"] = directory.Users.Count;
                report["assignments"] = directory.Assignments.Count;
                report["relevant_assignments"] = directory.RelevantAssignments;
                report["directory_only_users"] = directory.DirectoryOnlyUsers;
                report["invalid_catalogue_patterns"] = directory.InvalidCataloguePatterns;
                // Bounded response-only evidence (v1: the first 20 source records, eight columns); never stored.
                report["samples"] = records.Take(20).Select(row => UserSampleKeys.ToDictionary(key => key, key => row.GetValueOrDefault(key, ""))).ToList();
                return Json(report);
            }
            var catalogue = CatalogueBuilder.Build(records);
            report["unique_roles"] = catalogue.Ordered.Count;
            report["unique_transactions"] = catalogue.UniqueTransactions;
            report["transaction_assignments"] = catalogue.TransactionAssignments;
            report["relationship_count"] = catalogue.RelationshipCount;
            report["analysis"] = new Dictionary<string, object?>
            {
                ["module_source"] = "CSV FUNCTION_KEY", ["import_profile_id"] = csvProfile.Id, ["import_profile_version"] = csvProfile.Version,
                ["configuration_revision"] = (int?)settings["revision"] ?? 0,
            };
            report["warnings"] = import.Report.Warnings.Concat(catalogue.Warnings).Distinct().ToList();
            report["count_definitions"] = new Dictionary<string, string>
            {
                ["parsed_rows"] = "Logical CSV records before blank/duplicate filtering", ["transaction_assignments"] = "Distinct composite/child/parent/effective-role/T-code tuples",
                ["unique_transactions"] = "Distinct source transaction spellings; search remains case-insensitive", ["unique_roles"] = "Distinct AGR_NAME composites",
            };
            return Json(report);
        }
        // v1: the user preview names CSV validation failures; every other failure (and every failure of the other routes) is the route's fixed message.
        catch (DomainValidationException error) when (users && !headers) { return Detail(400, error.Message); }
        catch (Exception error) when (error is DomainValidationException or IOException or UnauthorizedAccessException or InvalidDataException
                                      or ArgumentException or NotSupportedException or System.Text.DecoderFallbackException or CsvFormatException)
        { return Detail(400, failure); }
    }

    /// <summary>parser.report(): the import report as v1 returns it before the catalogue or directory counts are added.</summary>
    private static Dictionary<string, object?> BaseReport(ImportReport report) => new()
    {
        ["file_name"] = report.FileName, ["import_profile"] = report.ImportProfile, ["import_version"] = report.ImportVersion,
        ["detected_columns"] = report.DetectedColumns, ["resolved_mapping"] = report.ResolvedMapping, ["parsed_rows"] = report.ParsedRows,
        ["unique_records"] = report.UniqueRecords, ["duplicate_rows"] = report.DuplicateRows, ["warnings"] = report.Warnings, ["errors"] = Array.Empty<string>(),
        ["samples"] = report.Samples,
    };

    private static IResult Json(object value) => Results.Content(JsonSerializer.Serialize(value), "application/json");

    /// <summary>The source's active profile from the settings (v1: `request.profile or` the active one).</summary>
    private static CsvProfile Active(JsonObject settings, bool users)
    {
        var (list, active) = users ? ("user_import_profiles", "active_user_import") : ("import_profiles", "active_import");
        var profile = settings[list]!.AsArray().Select(p => p!.AsObject()).First(p => (string?)p["id"] == (string?)settings[active]);
        return Profile(profile, users ? CsvSpec.Users.Fields : CsvSpec.Roles.Fields, []) ?? new CsvProfile();
    }

    /// <summary>The v1 ImportProfile / UserImportProfile model: id pattern, name 1-100, version >= 1, at most 12 mappings onto supported fields with
    /// distinct nonempty source headers (120 characters), the documented delimiters and encodings. Errors are Pydantic-shaped (422).</summary>
    internal static CsvProfile? Profile(JsonObject profile, IReadOnlyList<string> fields, List<object> errors)
    {
        var before = errors.Count;
        object[] at = ["profile"];
        V1Validation.Extra(profile, ["id", "name", "version", "mapping", "delimiter", "encoding"], errors, at);
        var id = V1Validation.Text(profile, "id", 1, 40, required: true, errors, at);
        if (id is not null && !ProfileId().IsMatch(id)) errors.Add(V1Validation.Error("string_pattern_mismatch", "id", "String should match pattern '^[A-Za-z0-9_-]{1,40}$'", at));
        V1Validation.Text(profile, "name", 1, 100, required: true, errors, at);
        var version = 1;
        if (profile["version"] is { } versionNode && (versionNode.GetValueKind() != JsonValueKind.Number || !versionNode.AsValue().TryGetValue(out version) || version < 1))
            errors.Add(V1Validation.Error("greater_than_equal", "version", "Input should be greater than or equal to 1", at));
        var delimiter = (string?)(profile["delimiter"] as JsonValue) ?? "auto";
        if (delimiter is not ("auto" or "," or ";" or "\t" or "|")) errors.Add(V1Validation.Error("literal_error", "delimiter", "Input should be 'auto', ',', ';', '\\t' or '|'", at));
        var encoding = (string?)(profile["encoding"] as JsonValue) ?? "auto";
        if (encoding is not ("auto" or "utf-8-sig" or "utf-16" or "cp1252")) errors.Add(V1Validation.Error("literal_error", "encoding", "Input should be 'auto', 'utf-8-sig', 'utf-16' or 'cp1252'", at));
        var mapping = new Dictionary<string, string>(StringComparer.Ordinal);
        if (profile["mapping"] is JsonObject map)
        {
            if (map.Count > 12) errors.Add(V1Validation.Error("too_long", "mapping", "Dictionary should have at most 12 items", at));
            foreach (var (field, column) in map)
            {
                var text = column is JsonValue value && value.GetValueKind() == JsonValueKind.String ? value.GetValue<string>() : null;
                if (!fields.Contains(field) || string.IsNullOrWhiteSpace(text) || text.Length > 120)
                { errors.Add(V1Validation.Error("value_error", "mapping", "Value error, Column mappings must use supported canonical fields and nonempty source headers.", at)); break; }
                mapping[field] = text;
            }
            if (mapping.Values.Distinct().Count() != mapping.Count) errors.Add(V1Validation.Error("value_error", "mapping", "Value error, Each source column can map to only one field.", at));
        }
        else if (profile.ContainsKey("mapping")) errors.Add(V1Validation.Error("dict_type", "mapping", "Input should be a valid dictionary", at));
        return errors.Count > before ? null : new CsvProfile(id!, version, delimiter, encoding, mapping);
    }

    /// <summary>Desktop: the path as given (CsvImport requires an absolute .csv path). Server: only a file inside the server's own source folder, after
    /// resolving links, so a browser can never make the server read another file.</summary>
    internal static string Confine(HttpContext http, string path)
    {
        var host = http.RequestServices.GetRequiredService<HostSettings>();
        if (host.Mode != HostMode.Server) return path;
        if (!Path.IsPathFullyQualified(path)) throw new ArgumentException("Use a server-visible absolute source path.");
        var root = Path.GetFullPath(Path.Combine(host.DataDirectory, "sources")) + Path.DirectorySeparatorChar;
        var full = Path.GetFullPath(path);
        var info = new FileInfo(full);
        var resolved = info.LinkTarget is not null ? info.ResolveLinkTarget(returnFinalTarget: true)?.FullName ?? full : full;
        var comparison = OperatingSystem.IsWindows() ? StringComparison.OrdinalIgnoreCase : StringComparison.Ordinal;
        if (!full.StartsWith(root, comparison) || !resolved.StartsWith(root, comparison)) throw new ArgumentException("CSV source is outside the configured source directory.");
        return full;
    }
}
