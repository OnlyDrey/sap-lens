using System.Security.Cryptography;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;
using Microsoft.AspNetCore.Http.Features;
using Microsoft.EntityFrameworkCore;
using SapLens.Application;
using SapLens.Domain.Csv;
using SapLens.Persistence;

namespace SapLens.Api;

/// <summary>v1 Data Sources contract (Phase 2A): source selection, browser upload activation, held-import confirmation, import history, previews and
/// settings saves. Every import runs through the staged ImportService (bounded batches, validation by construction, suspicious-change gate, atomic
/// activation), synchronously from the caller's point of view, like v1's loader. Employee Directory sources are not migrated yet (501).</summary>
public static partial class V1DataSources
{
    public static readonly Dictionary<string, string> Names = new()
    {
        ["roles"] = "Role Catalogue", ["users"] = "User–Role Mapping", ["employees"] = "Employee Directory", ["sod"] = "SoD Matrix",
    };
    private static readonly Dictionary<string, string> PathField = new()
    {
        ["roles"] = "data_csv_path", ["users"] = "user_csv_path", ["employees"] = "employee_csv_path", ["sod"] = "sod_csv_path",
    };
    private static readonly SemaphoreSlim Loading = new(1, 1);
    private static long _currentJob;

    [GeneratedRegex("^[A-Za-z0-9_-]{1,40}$")]
    private static partial Regex ProfileId();

    public static void Map(RouteGroupBuilder api)
    {
        api.MapPost("/configuration", async (HttpContext http, V1Settings store, IDbContextFactory<SapLensDb> factory, HostSettings host, CancellationToken ct) =>
        {
            var body = await JsonNode.ParseAsync(http.Request.Body, cancellationToken: ct) as JsonObject;
            if (body is null || body["revision"] is not JsonValue revisionValue || !revisionValue.TryGetValue<int>(out var revision)) return Detail(422, "A settings document with its revision is required.");
            var current = await store.GetAsync(ct);
            if (V1Settings.Validate(body, current) is { } problem) return Detail(problem.StartsWith("Source files", StringComparison.Ordinal) ? 400 : 422, problem);
            await store.UpdateAsync(revision, settings =>
            {
                foreach (var (key, value) in body)
                    if (!V1Settings.ServerManaged.Contains(key)) settings[key] = value?.DeepClone();
            }, Actors.Name(http), ct);
            return Results.Content((await V1Compatibility.ConfigurationResponse(store, factory, ct)).ToJsonString(), "application/json");
        });
        api.MapPost("/configuration/theme", async (HttpContext http, V1Settings store, IDbContextFactory<SapLensDb> factory, HostSettings host, CancellationToken ct) =>
        {
            var theme = (await JsonNode.ParseAsync(http.Request.Body, cancellationToken: ct))?["theme"]?.GetValue<string>();
            if (theme is not ("system" or "dark" or "light")) return Detail(400, "Choose a supported theme.");
            await store.UpdateAsync(null, settings => settings["theme"] = theme, Actors.Name(http), ct);
            return Results.Content((await V1Compatibility.ConfigurationResponse(store, factory, ct)).ToJsonString(), "application/json");
        });

        api.MapGet("/data-sources/history", async (IDbContextFactory<SapLensDb> factory, CancellationToken ct) =>
        {
            await using var db = await factory.CreateDbContextAsync(ct);
            var rows = await db.RefreshReports.AsNoTracking().OrderByDescending(r => r.TimestampUtc).Take(5).ToListAsync(ct);
            var items = rows.Select(r =>
            {
                var report = JsonNode.Parse(r.Json)!.AsObject();
                var item = new JsonObject { ["id"] = r.Id };
                foreach (var key in new[] { "timestamp", "operation", "status", "checked", "updated", "unchanged", "failed", "skipped" }) item[key] = report[key]?.DeepClone();
                return item;
            });
            return Results.Content(new JsonObject { ["items"] = new JsonArray([.. items]), ["retention"] = 5, ["privacy"] = "Private local records; excluded from diagnostic exports." }.ToJsonString(), "application/json");
        });

        api.MapGet("/data-sources/{source}/preview", async (string source, SnapshotService snapshots, IDbContextFactory<SapLensDb> factory, int? offset, int? limit, CancellationToken ct) =>
        {
            if (source == "employees") return V1Compatibility.NotMigrated(null!, "data-sources/employees/preview");
            if (source is not ("roles" or "users" or "sod")) return Detail(422, "Unknown source.");
            var (o, l) = (offset ?? 0, limit ?? 20);
            if (o < 0 || l is < 1 or > 100) return Detail(422, "offset must be ≥ 0 and limit between 1 and 100.");
            await using var db = await factory.CreateDbContextAsync(ct);
            var ids = await SnapshotService.ActiveAsync(db, ct);
            var id = source switch { "roles" => ids.Roles, "users" => ids.Users, _ => ids.Sod };
            var columns = source switch { "roles" => CsvSpec.Roles.Fields, "users" => CsvSpec.Users.Fields, _ => (IReadOnlyList<string>)CsvSpec.SodHeaders };
            var total = id is null ? 0 : await db.DatasetRecords.CountAsync(r => r.DatasetId == id, ct);
            var page = id is null ? [] : await db.DatasetRecords.AsNoTracking().Where(r => r.DatasetId == id).OrderBy(r => r.Ordinal).Skip(o).Take(l).Select(r => r.Payload).ToListAsync(ct);
            var items = page.Select(p => { var row = Sources.Deserialize(p); return columns.ToDictionary(c => c, c => row.GetValueOrDefault(c, "")); }).ToList();
            return Results.Ok(new { source, loaded = id is not null, columns, items, total, offset = o, limit = l });
        });

        api.MapPost("/data/cancel", async (JobQueue queue, CancellationToken ct) =>
        {
            if (Interlocked.Read(ref _currentJob) is var job and > 0) await queue.RequestCancelAsync(job, ct);
            return Results.Ok(new { status = "canceled" });
        });

        api.MapPost("/data-sources/{source}/select", async (string source, HttpContext http, HostSettings host, IServiceProvider services, CancellationToken ct) =>
        {
            if (source == "employees") return V1Compatibility.NotMigrated(http, "data-sources/employees/select");
            if (!Names.ContainsKey(source)) return Detail(422, "Unknown source.");
            var body = await JsonNode.ParseAsync(http.Request.Body, cancellationToken: ct) as JsonObject;
            var path = ((string?)body?["path"])?.Trim();
            if (body?["revision"] is not JsonValue rv || !rv.TryGetValue<int>(out var revision) || (string?)body["mode"] is not ("static" or "dynamic") || path is null)
                return Detail(422, "path, revision and mode (static or dynamic) are required.");
            if (path.Length == 0) return Detail(400, "Choose a CSV file. Use Clear source data to remove a dataset intentionally.");
            // A browser on another device must never name files on the server: the server accepts uploads only.
            if (host.Mode == HostMode.Server) return Detail(400, "On the server, upload the CSV file; server file paths are not accepted.");
            if (!Path.IsPathFullyQualified(path) || !File.Exists(path)) return Detail(400, "CSV file not found. Choose an existing file or reconnect the network share.");
            return await ActivateAsync(services, http, source, path, path, Path.GetFileName(path), (string)body["mode"]!, body["profile"] as JsonObject,
                (bool?)body["confirm_anomalies"] ?? false, revision, ct);
        });

        api.MapPost("/server/uploads/{source}/activate", async (string source, HttpContext http, IServiceProvider services, DatabaseOptions database, CancellationToken ct) =>
        {
            if (source == "employees") return V1Compatibility.NotMigrated(http, "server/uploads/employees/activate");
            if (!Names.ContainsKey(source)) return Detail(422, "Unknown source.");
            var limit = http.Features.Get<IHttpMaxRequestBodySizeFeature>();
            if (limit is { IsReadOnly: false }) limit.MaxRequestBodySize = Endpoints.MaxUploadBytes + 64 * 1024;
            if (!http.Request.HasFormContentType) return Detail(400, "Invalid or interrupted multipart upload. Choose one CSV file and retry.");
            IFormCollection form;
            try { form = await http.Request.ReadFormAsync(ct); }
            catch (Exception error) when (error is InvalidDataException or IOException or BadHttpRequestException)
            { return Detail(400, "Invalid or interrupted multipart upload. Choose one CSV file and retry."); }
            if (form.Files.Count != 1 || !int.TryParse(form["revision"], out var revision)) return Detail(400, "The upload revision or import profile is invalid.");
            JsonObject? profile = null;
            if (form["profile"].ToString() is { Length: > 0 } profileText)
                try { profile = JsonNode.Parse(profileText) as JsonObject; } catch (JsonException) { return Detail(400, "The upload revision or import profile is invalid."); }
            var file = form.Files[0];
            var name = Path.GetFileName(file.FileName);
            if (name.Length is 0 or > 200 || !name.EndsWith(".csv", StringComparison.OrdinalIgnoreCase)) return Detail(400, "Choose one .csv file.");
            // The uploaded file is kept as this source's private copy (like v1's uploads directory); the previous copy is removed after activation.
            var stored = Path.Combine(database.DataDirectory, "sources");
            Directory.CreateDirectory(stored);
            var target = Path.Combine(stored, $"{source}-{Convert.ToHexStringLower(RandomNumberGenerator.GetBytes(8))}.csv");
            await using (var output = new FileStream(target, FileMode.CreateNew, FileAccess.Write, FileShare.None, 81920, true)) await file.CopyToAsync(output, ct);
            var result = await ActivateAsync(services, http, source, target, target, name, "static", profile, form["confirm_anomalies"] == "true", revision, ct);
            if (http.Response.StatusCode >= 400 || result is not IStatusCodeHttpResult { StatusCode: null or 200 }) TryDelete(target);
            return result;
        });
    }

    private static IResult Detail(int status, object detail) => Results.Json(new { detail }, statusCode: status);

    private static void TryDelete(string path) { try { File.Delete(path); } catch (IOException) { } catch (UnauthorizedAccessException) { } }

    /// <summary>v1 ImportProfile (or SoD profile) → the CSV profile the parser uses. Null when the profile is invalid.</summary>
    private static CsvProfile? Profile(JsonObject profile, IReadOnlyList<string> fields)
    {
        var id = (string?)profile["id"] ?? "default";
        var delimiter = (string?)profile["delimiter"] ?? "auto";
        var encoding = (string?)profile["encoding"] ?? "auto";
        if (!ProfileId().IsMatch(id) || delimiter is not ("auto" or "," or ";" or "\t" or "|") || encoding is not ("auto" or "utf-8-sig" or "utf-16" or "cp1252")) return null;
        var mapping = new Dictionary<string, string>(StringComparer.Ordinal);
        foreach (var (field, column) in profile["mapping"] as JsonObject ?? [])
        {
            var text = (string?)column;
            if (!fields.Contains(field) || string.IsNullOrWhiteSpace(text) || text.Length > 120) return null;
            mapping[field] = text;
        }
        return new CsvProfile(id, (int?)profile["version"] ?? 1, delimiter, encoding, mapping);
    }

    private static async Task<IResult> ActivateAsync(IServiceProvider services, HttpContext http, string source, string importPath, string recordedPath, string fileName,
        string mode, JsonObject? requestedProfile, bool confirm, int revision, CancellationToken ct)
    {
        var store = services.GetRequiredService<V1Settings>();
        var queue = services.GetRequiredService<JobQueue>();
        var imports = services.GetRequiredService<ImportService>();
        var factory = services.GetRequiredService<IDbContextFactory<SapLensDb>>();
        var database = services.GetRequiredService<DatabaseOptions>();
        var host = services.GetRequiredService<HostSettings>();
        var clock = services.GetRequiredService<TimeProvider>();
        if (!await Loading.WaitAsync(0, ct)) return Detail(409, "A CSV is already loading. Wait or cancel it before trying another file.");
        try
        {
            var settings = await store.GetAsync(ct);
            if ((int)settings["revision"]! != revision) return Detail(409, "Settings changed. Reload this source before selecting it again.");

            // The profile that applies: the active profile of the source, or the one sent with the selection (stored with a higher version when it changed).
            var (profilesField, activeField) = source switch { "roles" => ("import_profiles", "active_import"), "users" => ("user_import_profiles", "active_user_import"), _ => ("", "") };
            var fields = source switch { "roles" => CsvSpec.Roles.Fields, "users" => CsvSpec.Users.Fields, _ => CsvSpec.Sod.Fields };
            JsonObject activeProfile = source == "sod"
                ? settings["sod_import"]!.AsObject()
                : settings[profilesField]!.AsArray().Select(p => p!.AsObject()).First(p => (string?)p["id"] == (string?)settings[activeField]);
            var chosen = requestedProfile ?? activeProfile;
            var csvProfile = Profile(chosen, fields);
            if (csvProfile is null) return Detail(400, "The source import profile is invalid. Review its column mapping and format.");

            // Import a private copy: the job removes its input when it finishes, the recorded source file stays.
            var uploads = Path.Combine(database.DataDirectory, "uploads");
            Directory.CreateDirectory(uploads);
            var working = Path.Combine(uploads, $"{Guid.NewGuid():N}.csv");
            try { File.Copy(importPath, working); }
            catch (Exception error) when (error is IOException or UnauthorizedAccessException)
            { return Detail(400, error is UnauthorizedAccessException ? "Cannot read the CSV. Check your account permissions and network-share access." : "CSV file not found. Choose an existing file or reconnect the network share."); }
            var job = await queue.EnqueueAsync(ImportService.JobKind, JsonSerializer.Serialize(new ImportPayload(source, working, fileName, csvProfile), Sources.Json), null, ct);
            Interlocked.Exchange(ref _currentJob, job.Id);
            var finished = await WaitAsync(queue, job.Id, ct);
            Interlocked.Exchange(ref _currentJob, 0);
            if (finished.Status == JobStatus.Cancelled) return Detail(409, "Data load canceled. Previous data and settings were retained.");
            if (finished.Status != JobStatus.Completed) return Detail(400, finished.Error ?? "The CSV could not be imported. Previous data is retained.");
            var result = JsonNode.Parse(finished.ResultJson!)!.AsObject();
            var datasetId = (long)result["dataset_id"]!;
            await using var db = await factory.CreateDbContextAsync(ct);
            var dataset = await db.Datasets.AsNoTracking().FirstAsync(d => d.Id == datasetId, ct);
            var evaluation = JsonNode.Parse(dataset.EvaluationJson ?? "{}")!.AsObject();
            JsonObject? confirmation = null;
            if (dataset.Status == DatasetStatus.Held)
            {
                if (!confirm)
                    return Detail(409, new JsonObject
                    {
                        ["code"] = "import_needs_confirmation", ["source"] = source,
                        ["message"] = "The new file differs sharply from the active data and needs explicit confirmation. Previous data is retained.",
                        ["anomalies"] = Anomalies(evaluation), ["old"] = evaluation["old"]?.DeepClone(), ["new"] = evaluation["new"]?.DeepClone(),
                    });
                await imports.ConfirmAsync(datasetId, Actors.Name(http), ct);
                confirmation = new JsonObject
                {
                    ["source"] = source, ["confirmed_at"] = Stamp(clock), ["actor"] = Actors.Name(http),
                    ["anomalies"] = new JsonArray([.. Anomalies(evaluation).Select(a => (JsonNode?)JsonValue.Create((string?)a!["message"]))]),
                    ["old_records"] = (int?)evaluation["old"]?["records"] ?? 0, ["new_records"] = (int?)evaluation["new"]?["records"] ?? dataset.RecordCount,
                };
            }

            // The refresh report, as v1 writes it for an import.
            var stamp = Stamp(clock);
            var diff = evaluation["diff"]?.AsObject();
            var unchanged = (string?)evaluation["previous_content_hash"] == dataset.ContentHash;
            var sourceResult = new JsonObject
            {
                ["source"] = source, ["name"] = Names[source], ["mode"] = mode, ["checked_at"] = stamp, ["status"] = unchanged ? "unchanged" : "updated",
                ["records"] = dataset.RecordCount, ["added"] = (int?)diff?["added"] ?? 0, ["removed"] = (int?)diff?["removed"] ?? 0,
                ["modified"] = (int?)diff?["modified"] ?? 0, ["unchanged"] = (int?)diff?["unchanged"] ?? 0,
            };
            var reportId = Convert.ToHexStringLower(RandomNumberGenerator.GetBytes(32));
            var refresh = new JsonObject
            {
                ["operation"] = "import", ["id"] = reportId, ["timestamp"] = stamp, ["status"] = unchanged ? "unchanged" : "changed", ["checked"] = 1,
                ["updated"] = unchanged ? 0 : 1, ["unchanged"] = unchanged ? 1 : 0, ["failed"] = 0, ["skipped"] = 0, ["sources"] = new JsonArray(sourceResult),
            };
            await services.GetRequiredService<WriteCoordinator>().WriteAsync((w, _) =>
            {
                w.RefreshReports.Add(new RefreshReport { Id = reportId, TimestampUtc = clock.GetUtcNow().UtcDateTime, Operation = "import", Status = (string)refresh["status"]!, Json = refresh.ToJsonString() });
                return Task.CompletedTask;
            }, ct);

            string? previousPath = null;
            var saved = await store.UpdateAsync(null, s =>
            {
                previousPath = (string?)s[PathField[source]];
                s[PathField[source]] = recordedPath;
                s["source_modes"]![source] = mode;
                if (requestedProfile is not null)
                {
                    var stored = Profile(requestedProfile, fields)!;
                    var node = JsonNode.Parse(JsonSerializer.Serialize(new { id = stored.Id, name = (string?)requestedProfile["name"] ?? stored.Id, version = stored.Version,
                        mapping = stored.Columns, delimiter = stored.Delimiter, encoding = stored.Encoding }))!.AsObject();
                    if (source == "sod") { node["id"] = "default"; node["name"] = "Standard SoD matrix"; s["sod_import"] = Versioned(node, s["sod_import"]!.AsObject()); }
                    else
                    {
                        var list = s[profilesField]!.AsArray();
                        var previous = list.Select(p => p!.AsObject()).FirstOrDefault(p => (string?)p["id"] == stored.Id);
                        if (previous is null) list.Add(node);
                        else list[list.IndexOf(previous)] = Versioned(node, previous);
                        s[activeField] = stored.Id;
                    }
                }
                var lifecycle = s["data_lifecycle"]!.AsObject();
                lifecycle["sources"]![source] = new JsonObject { ["snapshot"] = dataset.ContentHash, ["path"] = recordedPath, ["imported_at"] = stamp, ["checked_at"] = stamp };
                var history = lifecycle["history"]!.AsArray();
                history.Insert(0, reportId);
                var metadata = lifecycle["history_metadata"]!.AsObject();
                metadata[reportId] = new JsonObject { ["timestamp"] = stamp, ["operation"] = "import", ["status"] = refresh["status"]!.DeepClone(), ["checked"] = 1,
                    ["updated"] = refresh["updated"]!.DeepClone(), ["unchanged"] = refresh["unchanged"]!.DeepClone(), ["failed"] = 0, ["skipped"] = 0 };
                while (history.Count > 5) { metadata.Remove((string)history[^1]!); history.RemoveAt(history.Count - 1); }
                if (confirmation is not null)
                {
                    var confirmations = lifecycle["confirmations"]!.AsArray();
                    confirmations.Add(confirmation);
                    while (confirmations.Count > 100) confirmations.RemoveAt(0);
                }
            }, Actors.Name(http), ct);
            // Only a previous private upload copy of this source is removed, never a file the user chose on disk.
            try
            {
                var sourcesDirectory = Path.GetFullPath(Path.Combine(database.DataDirectory, "sources")) + Path.DirectorySeparatorChar;
                if (!string.IsNullOrEmpty(previousPath) && previousPath != recordedPath && Path.GetFullPath(previousPath).StartsWith(sourcesDirectory, StringComparison.Ordinal)) TryDelete(previousPath);
            }
            catch (Exception error) when (error is ArgumentException or NotSupportedException or PathTooLongException) { /* cleanup only; the import is complete */ }
            return Results.Content(new JsonObject
            {
                ["settings"] = saved, ["refresh"] = refresh, ["source"] = source, ["records"] = dataset.RecordCount, ["file_name"] = fileName,
            }.ToJsonString(), "application/json");
        }
        finally
        {
            Loading.Release();
        }
    }

    private static JsonObject Versioned(JsonObject next, JsonObject previous)
    {
        static string Comparable(JsonObject o) { var copy = o.DeepClone().AsObject(); copy.Remove("version"); return copy.ToJsonString(); }
        if (Comparable(next) != Comparable(previous)) next["version"] = Math.Max((int?)next["version"] ?? 1, ((int?)previous["version"] ?? 1) + 1);
        else next["version"] = (int?)previous["version"] ?? 1;
        return next;
    }

    private static JsonArray Anomalies(JsonObject evaluation)
    {
        // The v1 shape: rule, metric, old, new, message, plus group/percent only where they apply.
        var list = new JsonArray();
        foreach (var anomaly in evaluation["anomalies"]?.AsArray() ?? [])
        {
            var copy = anomaly!.DeepClone().AsObject();
            foreach (var key in new[] { "group", "percent" }) if (copy[key] is null) copy.Remove(key);
            list.Add(copy);
        }
        return list;
    }

    private static string Stamp(TimeProvider clock) => clock.GetUtcNow().UtcDateTime.ToString("yyyy-MM-dd'T'HH:mm:ss.ffffff'+00:00'");

    private static async Task<Job> WaitAsync(JobQueue queue, long id, CancellationToken ct)
    {
        while (true)
        {
            var job = await queue.GetAsync(id, ct);
            if (job is not null && job.Status is JobStatus.Completed or JobStatus.Failed or JobStatus.Cancelled) return job;
            await Task.Delay(100, ct);
        }
    }
}
