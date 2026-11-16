using System.Text.Json;
using System.Text.Json.Nodes;
using Microsoft.EntityFrameworkCore;
using SapLens.Application;
using SapLens.Domain.Directory;
using SapLens.Domain.Imports;
using SapLens.Domain.Roles;
using SapLens.Domain.Text;
using SapLens.Persistence;

namespace SapLens.Api;

/// <summary>Port of routers/employees.py and employee_preview.py. The directory is a versioned dataset (source <c>employees</c>) in the same
/// staged, validated, atomically activated pipeline as the SAP sources, so every import is kept as history and a failed import never replaces the
/// active directory. Employee Directory and User–Role Mapping feature switches gate enrichment exactly as in v1. Server file paths are never read
/// on behalf of a browser: the directory arrives through the upload, like the other sources.</summary>
public static class V1Employees
{
    private static readonly string[] Filters = ["", "missing_email", "duplicate_email", "missing_identifier", "duplicate_identifier", "missing_manager", "ambiguous_manager", "matched", "unmatched"];
    private static readonly Dictionary<string, string> Reasons = new()
    {
        ["matched"] = "One directory record matches the SAP email exactly after trimming whitespace and normalizing case.",
        ["duplicate_email"] = "Multiple Employee Directory records share an email used for SAP identity matching. No candidate is selected.",
        ["ambiguous_sap_email"] = "SAP email evidence is shared or conflicting. A unique person cannot be established safely.",
        ["missing_email"] = "The SAP source does not provide an email usable for identity matching.",
        ["unmatched"] = "No Employee Directory record matches the supplied SAP email. Names and AD usernames are not used as substitutes.",
    };

    private static IResult Detail(int status, string detail) => Results.Json(new { detail }, statusCode: status);
    private static IResult Json(object? value) => Results.Content(JsonSerializer.Serialize(value), "application/json");

    /// <summary>The directory callers may use: only with the Employee Directory feature enabled (v1 <c>available</c>).</summary>
    public static EmployeeDirectory? Available(Snapshot snapshot, JsonObject settings) =>
        (bool?)settings["features"]?["employee_directory"] == true ? snapshot.Directory : null;

    /// <summary>v1 directory_status. Coverage counts SAP users by identity-match status when the directory and the User Access data are both usable.</summary>
    public static Dictionary<string, object?> Status(Snapshot snapshot, JsonObject settings, bool @private)
    {
        var enabled = (bool?)settings["features"]?["employee_directory"] == true;
        var mappingEnabled = (bool?)settings["features"]?["user_role_mapping"] ?? true;
        var mappingData = snapshot.Ids.Users is not null;
        var mappingAvailable = mappingEnabled && mappingData;
        var directory = snapshot.Directory;
        var configured = !string.IsNullOrEmpty((string?)settings["employee_csv_path"]) || !string.IsNullOrEmpty((string?)settings["employee_snapshot_id"]);
        var status = !enabled ? "disabled" : !configured ? "not_configured" : directory is not null ? "healthy" : "warning";
        var report = directory is not null && configured ? directory.Report() : [];
        var coverage = new Dictionary<string, int>(StringComparer.Ordinal);
        if (enabled && directory is not null && mappingAvailable)
        {
            var owners = EmployeeDirectory.SapEmailOwners(snapshot.Users.Users.Values);
            foreach (var user in snapshot.Users.Users.Values)
            {
                var match = directory.MatchSapIdentity(user, owners).Status;
                coverage[match] = coverage.GetValueOrDefault(match) + 1;
            }
        }
        if (status == "healthy" && directory is not null)
        {
            var r = directory.Report();
            var managers = (Dictionary<string, int>)r["managers"]!;
            var duplicates = (Dictionary<string, int>)r["duplicate_identifiers"]!;
            if ((int)r["duplicate_emails"]! > 0 || (int)r["missing_emails"]! > 0 || (int)r["missing_identifiers"]! > 0 || duplicates.Values.Any(v => v > 0)
                || new[] { "ambiguous", "unresolved", "self_reference" }.Any(k => managers.GetValueOrDefault(k) > 0))
                status = "warning";
        }
        if (!@private) report.Remove("file_name");
        var loaded = directory is not null && configured;
        return new()
        {
            ["enabled"] = enabled, ["configured"] = !string.IsNullOrEmpty((string?)settings["employee_csv_path"]), ["loaded"] = loaded, ["status"] = status, ["error"] = null,
            ["report"] = report, ["coverage"] = coverage, ["persisted"] = !string.IsNullOrEmpty((string?)settings["employee_snapshot_id"]) && directory is not null,
            ["operational_status"] = !enabled ? "disabled" : directory is null ? "data_unavailable" : !mappingAvailable ? "dependency_unavailable" : "ready",
            ["digest"] = @private ? directory?.Digest : null,
            ["storage"] = !string.IsNullOrEmpty((string?)settings["employee_snapshot_id"]) ? "persisted_snapshot" : !string.IsNullOrEmpty((string?)settings["employee_csv_path"]) ? "legacy_path_only" : "none",
            ["coverage_reason"] = !enabled ? "Enable Employee Directory in Feature Settings." : directory is null ? "Import directory records first." : !mappingEnabled ? "Enable User–Role Mapping in Feature Settings to evaluate SAP email matches."
                : !mappingAvailable ? "Load the User Access CSV to evaluate SAP email matches." : coverage.Count == 0 ? "The User Access CSV contains no SAP users." : "",
            ["coverage_total"] = coverage.Values.Sum(), ["dependency_satisfied"] = mappingAvailable, ["user_mapping_enabled"] = mappingEnabled, ["mapping_data_available"] = mappingData,
            ["user_mapping_available"] = mappingAvailable, ["directory_operational"] = enabled && directory is not null,
            ["enrichment"] = new Dictionary<string, object?>
            {
                ["enabled"] = enabled && mappingEnabled, ["available"] = directory is not null && mappingData, ["operational"] = enabled && directory is not null && mappingAvailable,
                ["dependencies"] = new[] { "user_role_mapping", "employee_directory" },
            },
            ["action"] = "Settings → Data Sources → Employee Directory",
        };
    }

    private sealed record PreviewRequest(int Offset, int Limit, string Search, string Filter, string Sort, bool Descending, string? Digest);

    private static PreviewRequest? ParsePreview(JsonObject body)
    {
        var offset = (int?)body["offset"] ?? 0;
        var limit = (int?)body["limit"] ?? 25;
        var search = (string?)body["search"] ?? "";
        var filter = (string?)body["filter"] ?? "";
        var sort = (string?)body["sort"] ?? "name";
        var digest = (string?)body["digest"];
        if (offset < 0 || limit is < 1 or > 100 || search.Length > 256 || !Filters.Contains(filter) || sort is not ("name" or "email" or "department" or "manager")
            || digest is not null && !System.Text.RegularExpressions.Regex.IsMatch(digest, "^[a-f0-9]{64}$")) return null;
        return new PreviewRequest(offset, limit, search, filter, sort, (bool?)body["descending"] ?? false, digest);
    }

    /// <summary>employee_preview.preview_page: replacement delta against the previous directory, per-row quality and SAP match, filtered, sorted page.</summary>
    private static Dictionary<string, object?> PreviewPage(EmployeeDirectory directory, EmployeeDirectory? previous, Snapshot snapshot, JsonObject settings, PreviewRequest request)
    {
        var delta = ImportChecks.Diff("employees", previous?.Rows ?? [], directory.Rows);
        var matching = ((bool?)settings["features"]?["user_role_mapping"] ?? true) && snapshot.Ids.Users is not null;
        var owners = matching ? EmployeeDirectory.SapEmailOwners(snapshot.Users.Users.Values) : [];
        (string Match, List<string> Warnings) Quality(int id)
        {
            var row = directory.Rows[id];
            var email = EmployeeDirectory.Normalized(row["Mail"]);
            var duplicate = email.Length > 0 && directory.Indexes["Mail"][email].Count > 1;
            var match = !matching ? "unavailable" : duplicate || owners.GetValueOrDefault(email) > 1 ? "ambiguous" : email.Length > 0 && owners.GetValueOrDefault(email) == 1 ? "matched" : "unmatched";
            var manager = directory.Manager(id).Status;
            var warnings = new List<string>();
            if (email.Length == 0) warnings.Add("missing_email");
            if (duplicate) warnings.Add("duplicate_email");
            if (row["DistinguishedName"].Length == 0 && row["SamAccountName"].Length == 0) warnings.Add("missing_identifier");
            if (new[] { "DistinguishedName", "SamAccountName" }.Any(f => row[f].Length > 0 && (directory.Indexes[f].GetValueOrDefault(EmployeeDirectory.Normalized(row[f]))?.Count ?? 0) > 1)) warnings.Add("duplicate_identifier");
            if (manager is "missing" or "unresolved") warnings.Add("missing_manager");
            if (manager == "ambiguous") warnings.Add("ambiguous_manager");
            return (match, warnings);
        }
        var term = request.Search.Trim();
        var ids = Enumerable.Range(0, directory.Rows.Count).Where(id =>
        {
            var row = directory.Rows[id];
            string[] fields = [row["Name"], row["Mail"], row["Department"], row["ManagerName"]];
            if (term.Length > 0 && !(term.Contains('*') ? fields.Any(f => TextMatching.TextMatches(f, term)) : TextMatching.TextMatches(string.Join(' ', fields), term))) return false;
            if (request.Filter.Length == 0) return true;
            var (match, warnings) = Quality(id);
            return warnings.Contains(request.Filter) || request.Filter == match;
        }).ToList();
        var field = request.Sort switch { "email" => "Mail", "department" => "Department", "manager" => "ManagerName", _ => "Name" };
        var ordered = ids.OrderBy(id => EmployeeDirectory.Normalized(directory.Rows[id][field]), StringComparer.Ordinal).ThenBy(id => id).ToList();
        if (request.Descending) ordered.Reverse();
        var result = directory.Report();
        result["digest"] = directory.Digest;
        result["samples"] = Enumerable.Range(0, Math.Min(5, directory.Rows.Count)).Select(directory.View).ToList();
        result["items"] = ordered.Skip(request.Offset).Take(request.Limit).Select(id =>
        {
            var (match, warnings) = Quality(id);
            var view = directory.View(id);
            view["sap_match"] = match;
            view["validation"] = warnings;
            return view;
        }).ToList();
        (result["total"], result["offset"], result["limit"]) = (ids.Count, request.Offset, request.Limit);
        result["replacement"] = JsonSerializer.SerializeToNode(delta, Sources.Json);
        result["current_records"] = previous?.Rows.Count ?? 0;
        return result;
    }

    public static void Map(RouteGroupBuilder api)
    {
        api.MapGet("/employees/status", async (SnapshotService snapshots, V1Settings store, CancellationToken ct) =>
            Json(Status(await snapshots.GetAsync(ct), await store.GetAsync(ct), @private: true)));

        api.MapGet("/employees", async (HttpContext http, SnapshotService snapshots, V1Settings store, CancellationToken ct) =>
        {
            var q = http.Request.Query;
            var search = q["search"].FirstOrDefault() ?? "";
            var offset = int.TryParse(q["offset"].FirstOrDefault() ?? "0", out var o) ? o : -1;
            var limit = int.TryParse(q["limit"].FirstOrDefault() ?? "25", out var l) ? l : -1;
            if (search.Length > 256 || offset < 0 || limit is < 1 or > 100) return Detail(422, "Invalid search or paging parameters.");
            var directory = Available(await snapshots.GetAsync(ct), await store.GetAsync(ct));
            if (directory is null) return Json(new { items = Array.Empty<object>(), total = 0, offset, limit });
            var term = search.Trim();
            string[] fields = ["Name", "Mail", "Department", "Title", "Site", "ManagerName", "ManagerMail"];
            var ids = Enumerable.Range(0, directory.Rows.Count).Where(id => term.Length == 0 || fields.Any(f => TextMatching.TextMatches(directory.Rows[id][f], term)))
                .OrderBy(id => EmployeeDirectory.Normalized(directory.Rows[id]["Name"]), StringComparer.Ordinal)
                .ThenBy(id => EmployeeDirectory.Normalized(directory.Rows[id]["Mail"]), StringComparer.Ordinal).ThenBy(id => id).ToList();
            return Json(new { items = ids.Skip(offset).Take(limit).Select(directory.View).ToList(), total = ids.Count, offset, limit, generation = directory.Digest });
        });

        api.MapGet("/employees/record/{employeeId}", async (string employeeId, HttpContext http, SnapshotService snapshots, V1Settings store, CancellationToken ct) =>
        {
            var generation = http.Request.Query["generation"].FirstOrDefault() ?? "";
            if (!int.TryParse(employeeId, out var id) || !System.Text.RegularExpressions.Regex.IsMatch(generation, "^[a-f0-9]{64}$")) return Detail(422, "Invalid employee or generation.");
            var directory = Available(await snapshots.GetAsync(ct), await store.GetAsync(ct));
            if (directory is null) return Detail(404, "Employee Directory unavailable.");
            if (directory.Digest != generation) return Detail(409, "Directory changed. Search again.");
            if (id < 0 || id >= directory.Rows.Count) return Detail(404, "Employee not found.");
            return Json(directory.View(id));
        });

        api.MapGet("/employees/match/{**username}", async (string username, SnapshotService snapshots, V1Settings store, CancellationToken ct) =>
        {
            var snapshot = await snapshots.GetAsync(ct);
            var settings = await store.GetAsync(ct);
            var directory = Available(snapshot, settings);
            if (directory is null) return Json(new { status = "directory_unavailable", employee = (object?)null });
            if (!((bool?)settings["features"]?["user_role_mapping"] ?? true) || snapshot.Ids.Users is null) return Json(new { status = "mapping_unavailable", employee = (object?)null });
            if (!snapshot.Users.Users.TryGetValue(RoleNames.NormalizeUsername(username), out var user)) return Detail(404, "SAP user not found.");
            var (status, employee) = directory.MatchSapIdentity(user, EmployeeDirectory.SapEmailOwners(snapshot.Users.Users.Values));
            var managerSap = new Dictionary<string, object?> { ["status"] = "missing_email", ["username"] = null };
            if (employee is not null && EmployeeDirectory.Normalized((string?)((Dictionary<string, object?>)employee["manager"]!)["email"]) is { Length: > 0 } managerEmail)
            {
                var matches = snapshot.Users.Users.Values.Where(u => u.Emails.Select(EmployeeDirectory.Normalized).Contains(managerEmail)).Select(u => u.Username).ToList();
                managerSap = new() { ["status"] = matches.Count == 1 ? "matched" : matches.Count > 1 ? "ambiguous" : "unmatched", ["username"] = matches.Count == 1 ? matches[0] : null };
                if (matches.Count == 1 && snapshot.Users.Users.TryGetValue(RoleNames.NormalizeUsername(matches[0]), out var manager))
                {
                    var names = manager.Names.Where(n => n.First.Length > 0 || n.Last.Length > 0).Select(n => $"{n.First} {n.Last}".Trim()).ToList();
                    if (names.Count == 1) managerSap["display_name"] = names[0];
                }
            }
            var keys = user.Emails.Where(e => e.Trim().Length > 0).Select(EmployeeDirectory.Normalized).Distinct(StringComparer.Ordinal).Order(StringComparer.Ordinal).ToList();
            var pools = keys.Select(k => directory.Indexes["Mail"].GetValueOrDefault(k) ?? []).ToList();
            var diagnostics = new Dictionary<string, object?>
            {
                ["source"] = "Employee Directory CSV", ["sap_source"] = "User Access CSV", ["source_file"] = directory.FileName, ["matching_method"] = "Normalized exact email",
                ["sap_username"] = user.Username, ["explanation"] = Reasons.GetValueOrDefault(status, "Identity evidence is unavailable."), ["candidate_count"] = pools.Sum(p => p.Count),
                ["candidates"] = pools.SelectMany(p => p).Take(25).Select(id => new Dictionary<string, object?>
                {
                    ["id"] = id.ToString(System.Globalization.CultureInfo.InvariantCulture), ["name"] = directory.Rows[id]["Name"], ["email"] = directory.Rows[id]["Mail"],
                    ["username"] = directory.Rows[id]["SamAccountName"], ["account_status"] = EmployeeDirectory.AccountStatus(directory.Rows[id]["Enabled"]),
                }).ToList(),
            };
            return Json(new Dictionary<string, object?> { ["status"] = status, ["employee"] = employee, ["manager_sap"] = managerSap, ["generation"] = directory.Digest, ["diagnostics"] = diagnostics });
        });

        // Desktop three-step import (v1): validate and preview a local CSV, then import exactly the previewed content (digest of the file bytes).
        // A Server never reads server paths for a browser; there the directory arrives through the upload, like every other source.
        static async Task<(EmployeeDirectory? Directory, string Path, IResult? Refusal)> ReadLocal(HttpContext http, JsonObject body)
        {
            if (http.RequestServices.GetRequiredService<HostSettings>().Mode == HostMode.Server)
                return (null, "", Detail(400, "On the server, upload the Employee Directory CSV; server file paths are not accepted."));
            var path = ((string?)body["path"])?.Trim() ?? "";
            if (path.Length is 0 or > 4096 || !Path.IsPathFullyQualified(path)) return (null, path, Detail(400, "Choose an absolute Employee Directory CSV path."));
            try
            {
                if (new FileInfo(path).Length > EmployeeDirectory.MaxBytes) return (null, path, Detail(400, "Employee Directory CSV exceeds the 50 MB limit."));
                var raw = await File.ReadAllBytesAsync(path, http.RequestAborted);
                var rows = EmployeeDirectory.Parse(raw);
                return (new EmployeeDirectory(rows, Path.GetFileName(path), EmployeeDirectory.Sha256(raw), DateTime.UtcNow.ToString("yyyy-MM-dd'T'HH:mm:ss.ffffff'+00:00'")), path, null);
            }
            catch (SapLens.Domain.Csv.CsvFormatException error) { return (null, path, Detail(400, error.Message)); }
            catch (Exception error) when (error is IOException or UnauthorizedAccessException)
            { return (null, path, Detail(400, "Cannot read Employee Directory CSV. Check the absolute path and file permissions.")); }
        }

        api.MapPost("/employees/preview", async (HttpContext http, SnapshotService snapshots, V1Settings store, CancellationToken ct) =>
        {
            if (await JsonNode.ParseAsync(http.Request.Body, cancellationToken: ct) is not JsonObject body || ParsePreview(body) is not { } request || body["revision"] is null) return Detail(422, "Invalid preview request.");
            var (directory, _, refusal) = await ReadLocal(http, body);
            if (refusal is not null) return refusal;
            if (request.Digest is not null && directory!.Digest != request.Digest) return Detail(409, "Preview source changed. Validate the CSV again.");
            var snapshot = await snapshots.GetAsync(ct);
            return Json(PreviewPage(directory!, snapshot.Directory, snapshot, await store.GetAsync(ct), request));
        });

        api.MapPost("/employees/import", async (HttpContext http, IServiceProvider services, CancellationToken ct) =>
        {
            if (await JsonNode.ParseAsync(http.Request.Body, cancellationToken: ct) is not JsonObject body || body["revision"] is not JsonValue rv || !rv.TryGetValue<int>(out var revision)) return Detail(422, "Invalid import request.");
            var (directory, path, refusal) = await ReadLocal(http, body);
            if (refusal is not null) return refusal;
            if ((string?)body["digest"] is not { } digest || directory!.Digest != digest) return Detail(409, "The CSV changed or has not been previewed. Preview it again before confirmation.");
            var mode = (string?)body["mode"] is "dynamic" ? "dynamic" : "static";
            var result = await V1DataSources.ActivateAsync(services, http, Sources.Employees, path, path, Path.GetFileName(path), mode, null, false, revision, ct);
            if (result is IStatusCodeHttpResult { StatusCode: >= 400 }) return result;
            return Json(Status(await services.GetRequiredService<SnapshotService>().GetAsync(ct), await services.GetRequiredService<V1Settings>().GetAsync(ct), @private: true));
        });

        api.MapPost("/data-sources/employees/inspect", async (HttpContext http, SnapshotService snapshots, V1Settings store, CancellationToken ct) =>
        {
            if (await JsonNode.ParseAsync(http.Request.Body, cancellationToken: ct) is not JsonObject body || ParsePreview(body) is not { } request) return Detail(422, "Invalid preview request.");
            var snapshot = await snapshots.GetAsync(ct);
            var settings = await store.GetAsync(ct);
            if (snapshot.Directory is not { } directory) return Detail(409, "No loaded Employee Directory snapshot is available.");
            if (request.Digest is not null && request.Digest != directory.Digest && request.Digest != (string?)settings["employee_snapshot_id"])
                return Detail(409, "The directory snapshot changed. Close and reopen Preview data.");
            return Json(PreviewPage(directory, directory, snapshot, settings, request));
        });

        api.MapPost("/employees/clear", async (HttpContext http, V1Settings store, CancellationToken ct) =>
        {
            if (await JsonNode.ParseAsync(http.Request.Body, cancellationToken: ct) is not JsonObject body || body["revision"] is not JsonValue rv || !rv.TryGetValue<int>(out var revision) || revision < 0)
                return Detail(422, "revision is required.");
            try
            {
                // The active directory dataset is retired (kept as history), never deleted; settings and dataset change in one transaction.
                await store.UpdateAsync(revision, s => { s["employee_csv_path"] = ""; s["employee_snapshot_id"] = null; }, Actors.Name(http), async (db, token) =>
                {
                    foreach (var active in await db.Datasets.Where(d => d.Source == Sources.Employees && d.Status == DatasetStatus.Active).ToListAsync(token)) active.Status = DatasetStatus.Retired;
                }, ct);
            }
            catch (ImportConflictException) { return Detail(409, "Settings changed. Reload before clearing."); }
            return Json(new { status = "cleared", cleanup_warning = (string?)null });
        });

        // v1 recovers a legacy in-memory directory into a durable snapshot. Every .NET directory is a durable dataset from the moment it is active.
        api.MapPost("/employees/persist", async (HttpContext http, SnapshotService snapshots, V1Settings store, CancellationToken ct) =>
        {
            if (await JsonNode.ParseAsync(http.Request.Body, cancellationToken: ct) is not JsonObject body || body["revision"] is not JsonValue rv || !rv.TryGetValue<int>(out var revision) || (string?)body["digest"] is not { } digest)
                return Detail(422, "revision and digest are required.");
            var snapshot = await snapshots.GetAsync(ct);
            var settings = await store.GetAsync(ct);
            if ((int)settings["revision"]! != revision || snapshot.Directory?.Digest != digest) return Detail(409, "Directory or settings changed. Review Data Sources before saving records.");
            return Json(Status(snapshot, settings, @private: true));
        });
    }
}
