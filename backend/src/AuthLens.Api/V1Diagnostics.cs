using System.Runtime.InteropServices;
using System.Text.Json.Nodes;
using Microsoft.EntityFrameworkCore;
using AuthLens.Application;
using AuthLens.Persistence;

namespace AuthLens.Api;

/// <summary>Port of diagnostics.py: an allowlisted status report. The export and the Server view never contain paths, the data directory or refresh-history
/// identifiers. In this build every activated dataset is durable SQLite data, so "snapshot available" means the dataset is active; imports run as jobs,
/// so the backend is "loading" while one is queued or running.</summary>
public static class V1Diagnostics
{
    private static string Platform() =>
        RuntimeInformation.IsOSPlatform(OSPlatform.Windows) ? "Windows" : RuntimeInformation.IsOSPlatform(OSPlatform.OSX) ? "Darwin" : RuntimeInformation.IsOSPlatform(OSPlatform.Linux) ? "Linux" : "";

    private static string? Iso(DateTime? value) => value is { } v ? DateTime.SpecifyKind(v, DateTimeKind.Utc).ToString("yyyy-MM-dd'T'HH:mm:ss.ffffff'+00:00'") : null;

    public static async Task<JsonObject> SnapshotAsync(IServiceProvider services, bool @private, CancellationToken ct)
    {
        var host = services.GetRequiredService<HostSettings>();
        var settings = await services.GetRequiredService<V1Settings>().GetAsync(ct);
        var snapshot = await services.GetRequiredService<SnapshotService>().GetAsync(ct);
        await using var db = await services.GetRequiredService<IDbContextFactory<AuthLensDb>>().CreateDbContextAsync(ct);
        var active = await db.Datasets.AsNoTracking().Where(d => d.Status == DatasetStatus.Active).ToListAsync(ct);
        var busy = await db.Jobs.AsNoTracking().AnyAsync(j => j.Status == JobStatus.Queued || j.Status == JobStatus.Running, ct);
        var chain = await services.GetRequiredService<ReviewService>().VerifyChainAsync(ct);
        var sodChain = await services.GetRequiredService<SodDecisionStore>().VerifyChainAsync(ct);
        var lifecycleState = (await AssignmentLifecycle.LoadAsync(db, ct)).State;
        var lifecycle = settings["data_lifecycle"] as JsonObject ?? [];
        var references = lifecycle["sources"] as JsonObject ?? [];
        var features = settings["features"] as JsonObject ?? [];
        var modes = settings["source_modes"] as JsonObject ?? [];
        var schedule = settings["refresh_schedule"] as JsonObject ?? [];
        var scheduleState = services.GetRequiredService<RefreshScheduleState>().Read();
        var lastLoad = active.Where(d => d.Source != Sources.Employees).Select(d => d.ActivatedUtc ?? d.CreatedUtc).DefaultIfEmpty().Max();

        var result = new JsonObject
        {
            ["application"] = "SAP Lens", ["version"] = V1Compatibility.Version, ["generated_at"] = DateTimeOffset.UtcNow.ToString("yyyy-MM-dd'T'HH:mm:ss.ffffff'+00:00'"),
            ["platform"] = Platform(), ["python_version"] = null, ["runtime"] = $".NET {Environment.Version}",
            ["configuration_schema"] = settings["schema_version"]?.DeepClone(), ["configuration_revision"] = settings["revision"]?.DeepClone(),
            ["last_failed_load"] = lifecycle["last_failed_refresh"]?.DeepClone(),
            ["storage_available"] = Directory.Exists(host.DataDirectory),
            ["backend_status"] = busy ? "loading" : "running",
            ["data_source_configured"] = active.Any(d => d.Source is Sources.Roles or Sources.Users),
            ["cached_roles"] = snapshot.Catalogue.Roles.Count,
            ["last_successful_load"] = lastLoad == default ? null : Iso(lastLoad),
            ["last_successful_refresh"] = lifecycle["last_successful_refresh"]?.DeepClone(),
            // Account Review continuity rests on the hash-chained decision store here: "ok" only while the chain verifies.
            // v1: the assignment lifecycle memory state (ok, corrupt, missing, stale); a broken decision hash chain also reads corrupt.
            ["review_continuity"] = lifecycleState != "ok" ? lifecycleState : chain.Ok && sodChain.Ok ? "ok" : "corrupt",
            ["deployment_mode"] = host.Mode == HostMode.Server ? "server" : "desktop",
            // The refresh scheduler is not migrated: the configured schedule is reported, and no attempt has been made by this build.
            ["scheduled_refresh"] = new JsonObject
            {
                ["enabled"] = schedule["enabled"]?.DeepClone() ?? false, ["mode"] = schedule["mode"]?.DeepClone(), ["timezone"] = schedule["timezone"]?.DeepClone(),
                // MIG-019: the scheduler's recorded outcome (null until the first scheduled attempt, as v1).
                ["last_attempt"] = scheduleState["last_attempt"]?.DeepClone(), ["last_success"] = scheduleState["last_success"]?.DeepClone(),
                ["last_failure"] = scheduleState["last_failure"]?.DeepClone(), ["last_status"] = scheduleState["last_status"]?.DeepClone(),
                ["consecutive_failures"] = scheduleState["consecutive_failures"]?.DeepClone(),
            },
        };

        var sources = new JsonArray();
        foreach (var (key, name, pathField, records, assignments) in new[]
                 {
                     (Sources.Roles, "Role Catalogue CSV", "data_csv_path", snapshot.Catalogue.Roles.Count, snapshot.Catalogue.TransactionAssignments),
                     (Sources.Users, "User Access CSV", "user_csv_path", snapshot.Users.Users.Count, snapshot.Users.Assignments.Count),
                     (Sources.Sod, "SoD Matrix CSV", "sod_csv_path", snapshot.Sod?.Records.Count ?? 0, 0),
                 })
        {
            var path = (string?)settings[pathField] ?? "";
            var dataset = active.FirstOrDefault(d => d.Source == key);
            var reference = references[key] as JsonObject;
            var enabled = key == Sources.Users ? (bool?)features["user_role_mapping"] ?? true : key == Sources.Sod ? (bool?)features["sod"] ?? true : true;
            var source = new JsonObject
            {
                ["enabled"] = enabled, ["id"] = key, ["name"] = name, ["configured"] = path.Length > 0 || dataset is not null, ["loaded"] = dataset is not null,
                ["records"] = records, ["assignments"] = assignments,
                ["last_successful_load"] = reference?["imported_at"]?.DeepClone() ?? (dataset is null ? null : Iso(dataset.ActivatedUtc ?? dataset.CreatedUtc)),
                ["availability"] = dataset is not null ? "available_at_last_load" : "not_checked", ["error"] = null, ["loading"] = busy && path.Length > 0,
                ["mode"] = modes[key]?.DeepClone(), ["snapshot_available"] = dataset is not null, ["last_checked"] = reference?["checked_at"]?.DeepClone(),
            };
            if (@private) { source["configured_path"] = path; source["loaded_path"] = dataset is null ? "" : (string?)reference?["path"] ?? path; source["attempted_path"] = ""; }
            sources.Add(source);
        }

        var directory = V1Employees.Status(snapshot, settings, @private);
        result["employee_directory"] = System.Text.Json.JsonSerializer.SerializeToNode(directory);
        var report = directory.GetValueOrDefault("report") as IDictionary<string, object?>;
        var employeeReference = references[Sources.Employees] as JsonObject;
        var employees = new JsonObject
        {
            ["id"] = "employees", ["name"] = "Employee Directory CSV", ["enabled"] = System.Text.Json.JsonSerializer.SerializeToNode(directory.GetValueOrDefault("enabled")),
            ["mode"] = modes["employees"]?.DeepClone(), ["configured"] = System.Text.Json.JsonSerializer.SerializeToNode(directory.GetValueOrDefault("configured")),
            ["loaded"] = System.Text.Json.JsonSerializer.SerializeToNode(directory.GetValueOrDefault("loaded")),
            ["records"] = System.Text.Json.JsonSerializer.SerializeToNode(report?.TryGetValue("records", out var count) == true ? count : 0), ["assignments"] = 0,
            ["snapshot_available"] = System.Text.Json.JsonSerializer.SerializeToNode(directory.GetValueOrDefault("persisted")),
            ["last_successful_load"] = System.Text.Json.JsonSerializer.SerializeToNode(report?.TryGetValue("imported_at", out var imported) == true ? imported : null),
            ["availability"] = directory.GetValueOrDefault("loaded") is true ? "available_at_last_load" : "not_checked", ["error"] = null,
            ["loading"] = busy && ((string?)settings["employee_csv_path"] ?? "").Length > 0,
            ["dependency"] = System.Text.Json.JsonSerializer.SerializeToNode(directory.GetValueOrDefault("operational_status")),
            ["last_checked"] = employeeReference is not null && (string?)employeeReference["path"] == (string?)settings["employee_csv_path"] ? employeeReference["checked_at"]?.DeepClone() : null,
        };
        if (@private)
        {
            employees["configured_path"] = (string?)settings["employee_csv_path"] ?? "";
            employees["loaded_path"] = directory.GetValueOrDefault("loaded") is true ? (string?)settings["employee_csv_path"] ?? "" : "";
            employees["attempted_path"] = "";
        }
        sources.Add(employees);
        result["sources"] = sources;

        // csv_lifecycle.history: the retained refresh reports, newest first; identifiers only in the private view.
        var history = new JsonArray();
        foreach (var row in await db.RefreshReports.AsNoTracking().OrderByDescending(r => r.TimestampUtc).Take(5).ToListAsync(ct))
        {
            var stored = JsonNode.Parse(row.Json)!.AsObject();
            var item = new JsonObject();
            if (@private) item["id"] = row.Id;
            foreach (var field in new[] { "timestamp", "operation", "status", "checked", "updated", "unchanged", "failed", "skipped" }) item[field] = stored[field]?.DeepClone();
            history.Add(item);
        }
        result["refresh_history"] = history;
        if (@private)
        {
            result["data_source"] = (string?)settings["data_csv_path"] ?? "";
            result["application_directory"] = host.DataDirectory;
        }
        return result;
    }

    public static void Map(RouteGroupBuilder api)
    {
        api.MapGet("/diagnostics", async (HttpContext http, HostSettings host, CancellationToken ct) =>
            Results.Content((await SnapshotAsync(http.RequestServices, @private: host.Mode != HostMode.Server, ct)).ToJsonString(), "application/json"));
        api.MapGet("/diagnostics/export", async (HttpContext http, CancellationToken ct) =>
            Results.Content((await SnapshotAsync(http.RequestServices, @private: false, ct)).ToJsonString(), "application/json"));
    }
}
