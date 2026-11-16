using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;
using Microsoft.EntityFrameworkCore;
using SapLens.Application;
using SapLens.Domain.Csv;
using SapLens.Domain.Imports;
using SapLens.Domain.Roles;
using SapLens.Domain.Scheduling;
using SapLens.Persistence;

namespace SapLens.Api;

/// <summary>MIG-008, port of `POST /api/refresh` (csv_lifecycle.load with operation "refresh"): every configured Dynamic source with a path is read
/// again with its active import profile. A file whose records equal the active revision is reported unchanged without a new revision (v1 compares a
/// file fingerprint; this compares the parsed records' content hash). Otherwise it is imported through the normal import job: a suspicious change is
/// never activated by a refresh (it needs an explicit import and confirmation), a failure keeps the previous data. Static, disabled and unconfigured
/// sources are skipped. One immutable report covers all sources; its changed records stay private (detail and export routes).</summary>
public static class V1Refresh
{
    private static readonly string[] Order = ["roles", "users", "employees", "sod"];
    private static readonly Dictionary<string, string> PathField = new() { ["roles"] = "data_csv_path", ["users"] = "user_csv_path", ["employees"] = "employee_csv_path", ["sod"] = "sod_csv_path" };

    public static void Map(RouteGroupBuilder api)
    {
        api.MapPost("/refresh", async (HttpContext http, IServiceProvider services, CancellationToken ct) =>
        {
            var (report, busy) = await RunAsync(services, Actors.Name(http), ct);
            if (busy) return Results.Json(new { detail = "A CSV is already loading. Wait or cancel it before trying another file." }, statusCode: 409);
            var health = await HealthAsync(services, ct);
            health["refresh"] = report;
            return Results.Content(health.ToJsonString(), "application/json");
        });
    }

    /// <summary>The v1 `/health` body the refresh response extends.</summary>
    private static async Task<JsonObject> HealthAsync(IServiceProvider services, CancellationToken ct)
    {
        var snapshot = await services.GetRequiredService<SnapshotService>().GetAsync(ct);
        await using var db = await services.GetRequiredService<IDbContextFactory<SapLensDb>>().CreateDbContextAsync(ct);
        var loaded = await db.Datasets.AsNoTracking().Where(d => d.Status == DatasetStatus.Active && (d.Source == Sources.Roles || d.Source == Sources.Users))
            .Select(d => d.ActivatedUtc ?? d.CreatedUtc).ToListAsync(ct);
        var last = loaded.Count > 0 ? loaded.Max() : (DateTime?)null;
        return new JsonObject
        {
            ["app"] = "sap-lens", ["version"] = V1Compatibility.Version, ["instance_id"] = V1Compatibility.Boot,
            ["status"] = last is null ? "needs_configuration" : "ok", ["cached_roles"] = snapshot.Catalogue.Roles.Count,
            ["last_loaded"] = last?.ToString("yyyy-MM-dd'T'HH:mm:ss.ffffff'+00:00'"),
        };
    }

    /// <summary>Runs one refresh. Returns the report summary, or busy when another CSV load holds the loader (v1 409).</summary>
    public static async Task<(JsonObject? Report, bool Busy)> RunAsync(IServiceProvider services, string actor, CancellationToken ct)
    {
        var gate = services.GetRequiredService<DataLoadGate>();
        if (!await gate.Loading.WaitAsync(0, ct)) return (null, true);
        try { return (await RefreshAsync(services, actor, ct), false); }
        finally { gate.Loading.Release(); }
    }

    private static async Task<JsonObject> RefreshAsync(IServiceProvider services, string actor, CancellationToken ct)
    {
        var store = services.GetRequiredService<V1Settings>();
        var factory = services.GetRequiredService<IDbContextFactory<SapLensDb>>();
        var clock = services.GetRequiredService<TimeProvider>();
        var settings = await store.GetAsync(ct);
        var stamp = V1DataSources.Stamp(clock);
        var lifecycle = settings["data_lifecycle"]!.AsObject();
        var features = settings["features"] as JsonObject ?? [];
        var modes = settings["source_modes"] as JsonObject ?? [];
        await using var db = await factory.CreateDbContextAsync(ct);
        var active = await db.Datasets.AsNoTracking().Where(d => d.Status == DatasetStatus.Active).ToDictionaryAsync(d => d.Source, ct);
        var results = new List<JsonObject>();
        var changes = new Dictionary<string, JsonArray>();
        var references = new Dictionary<string, JsonObject>();
        var successful = 0;
        foreach (var source in Order)
        {
            var path = (string?)settings[PathField[source]] ?? "";
            if (source == "sod" && path.Length == 0 && !active.ContainsKey("sod") && lifecycle["sources"]?["sod"] is null) continue;
            var enabled = source switch
            {
                "roles" => true, "users" => (bool?)features["user_role_mapping"] ?? true, "sod" => (bool?)features["sod"] ?? true,
                _ => (bool?)features["employee_directory"] ?? true,
            };
            var mode = (string?)modes[source] ?? (source is "roles" or "users" ? "dynamic" : "static");
            var result = new JsonObject { ["source"] = source, ["name"] = V1DataSources.Names[source], ["mode"] = mode, ["checked_at"] = stamp };
            results.Add(result);
            if (path.Length == 0 || !enabled || mode == "static")
            {
                var reason = path.Length == 0 ? "unconfigured" : !enabled ? "disabled" : "static";
                result["status"] = "skipped"; result["reason"] = reason; result["message"] = $"Source skipped: {reason}.";
                continue;
            }
            active.TryGetValue(source, out var current);
            try
            {
                var profile = V1DataSources.ActiveProfile(settings, source) ?? throw new DomainValidationException("The source import profile is invalid. Review its column mapping and format.");
                // Fast path: the file's records equal the active revision; nothing is staged.
                var (rows, hash) = await Task.Run(() => Read(source, path, profile, ct), ct);
                if (current is not null && current.ContentHash == hash)
                {
                    var same = RecordDiff.Compare(source, rows, rows, includeChanges: false);
                    result["status"] = "unchanged";
                    result["records"] = same.Records;
                    V1DataSources.Counts(result, same with { Counts = new DiffCounts(0, 0, 0, same.Records, 0) });
                    result["fast_path"] = true;
                    references[source] = Reference(lifecycle, source, current.ContentHash, path, stamp, imported: false);
                    successful++;
                    continue;
                }
                var finished = await V1DataSources.RunImportJobAsync(services, source, path, Path.GetFileName(path), profile, ct);
                if (finished.Status == JobStatus.Cancelled) throw new OperationCanceledException("Data load canceled. Previous data and settings were retained.");
                if (finished.Status != JobStatus.Completed) throw new DomainValidationException(finished.Error ?? "The CSV could not be imported.");
                var (dataset, evaluation) = await V1DataSources.DatasetOfAsync(db, finished, ct);
                if (dataset.Status == DatasetStatus.Held)
                {
                    // v1 ImportHeld: a refresh never activates a suspicious replacement; the held revision waits for an explicit import and confirmation.
                    result["status"] = "failed"; result["category"] = "needs_confirmation"; result["severity"] = "suspicious"; result["confirmable"] = true;
                    result["previous_preserved"] = true; result["anomalies"] = evaluation["anomalies"]?.DeepClone() ?? new JsonArray();
                    result["old"] = evaluation["old"]?.DeepClone(); result["new"] = evaluation["new"]?.DeepClone();
                    result["message"] = "The new file differs sharply from the active data and needs explicit confirmation. Previous data is retained.";
                    result["recovery"] = "Review the change report. If the smaller file is correct, import it again and confirm; otherwise export the complete source again.";
                    continue;
                }
                changes[source] = await V1DataSources.CompareAsync(db, result, dataset, evaluation, ct);
                references[source] = Reference(lifecycle, source, dataset.ContentHash, path, stamp, imported: true);
                successful++;
            }
            catch (OperationCanceledException) when (!ct.IsCancellationRequested)
            {
                Failure(result, "read_failed", "The source could not be prepared. Check source access and retry.");
                result["previous_preserved"] = current is not null;
            }
            catch (Exception error) when (error is not OperationCanceledException)
            {
                var (category, message) = Category(error);
                Failure(result, category, message);
                result["severity"] = "invalid"; result["confirmable"] = false; result["previous_preserved"] = current is not null;
            }
        }

        int Count(string status) => results.Count(r => (string?)r["status"] == status);
        var failed = Count("failed");
        var updated = Count("updated");
        var reportId = V1DataSources.NewReportId();
        var report = new JsonObject
        {
            ["version"] = 1, ["timestamp"] = stamp, ["operation"] = "refresh", ["sources"] = new JsonArray([.. results]),
            ["checked"] = results.Count - Count("skipped"), ["updated"] = updated, ["unchanged"] = Count("unchanged"), ["failed"] = failed, ["skipped"] = Count("skipped"),
            ["status"] = failed > 0 && successful > 0 ? "partial" : failed > 0 ? "failed" : updated > 0 ? "changed" : "unchanged", ["id"] = reportId,
        };
        var stored = report.DeepClone().AsObject();
        foreach (var result in stored["sources"]!.AsArray().OfType<JsonObject>())
            if (changes.TryGetValue((string)result["source"]!, out var list)) result["changes"] = list;
        await services.GetRequiredService<WriteCoordinator>().WriteAsync((w, _) =>
        {
            w.RefreshReports.Add(new RefreshReport { Id = reportId, TimestampUtc = clock.GetUtcNow().UtcDateTime, Operation = "refresh", Status = (string)report["status"]!, Json = stored.ToJsonString() });
            return Task.CompletedTask;
        }, ct);
        await store.UpdateAsync(null, s =>
        {
            var lifecycleNow = s["data_lifecycle"]!.AsObject();
            if ((int)report["checked"]! > 0) lifecycleNow[failed > 0 ? "last_failed_refresh" : "last_successful_refresh"] = stamp;
            foreach (var (source, reference) in references)
            {
                lifecycleNow["sources"]![source] = reference.DeepClone();
                if (source == "employees") s["employee_snapshot_id"] = (string?)reference["snapshot"];
            }
            V1DataSources.RecordHistory(lifecycleNow, reportId, report);
        }, actor, ct);
        return report;
    }

    private static void Failure(JsonObject result, string category, string message)
    {
        result["status"] = "failed"; result["category"] = category; result["message"] = message; result["previous_preserved"] = true;
        result["recovery"] = "Review this source under Settings → Data Sources. Previous validated records remain available.";
    }

    /// <summary>The source reference in data_lifecycle; an unchanged source keeps its import time and records the check.</summary>
    private static JsonObject Reference(JsonObject lifecycle, string source, string snapshot, string path, string stamp, bool imported)
    {
        var previous = lifecycle["sources"]?[source] as JsonObject;
        return new JsonObject
        {
            ["snapshot"] = snapshot, ["path"] = path,
            ["imported_at"] = imported ? stamp : previous?["imported_at"]?.DeepClone() ?? stamp, ["checked_at"] = stamp,
        };
    }

    /// <summary>Reads the file with the active profile and hashes its records exactly as the import job does (same order, same serialization).</summary>
    private static (List<IReadOnlyDictionary<string, string>> Rows, string Hash) Read(string source, string path, CsvProfile profile, CancellationToken ct)
    {
        var (records, _) = Sources.Read(source, path, ct, profile);
        using var hasher = new ContentHasher();
        var rows = new List<IReadOnlyDictionary<string, string>>();
        foreach (var record in records)
        {
            hasher.Add(Sources.Serialize(record));
            rows.Add(record);
        }
        return (rows, hasher.Finish());
    }

    /// <summary>csv_lifecycle.error_result: the category and safe message of a failed source (never the path or record values).</summary>
    internal static (string Category, string Message) Category(Exception error)
    {
        switch (error)
        {
            case FileNotFoundException or DirectoryNotFoundException: return ("missing", "The configured CSV is missing. Reconnect the share or choose an existing file.");
            case UnauthorizedAccessException: return ("access_denied", "The CSV could not be read. Check file and network-share permissions.");
            case System.Text.DecoderFallbackException: return ("encoding", "The CSV encoding is invalid. Review the source encoding and import format.");
            case CsvFormatException: return ("malformed_csv", "The CSV has malformed quoting or records. Correct the export and validate it again.");
            case DomainValidationException or ArgumentException or InvalidDataException:
                var text = error.Message.ToLowerInvariant();
                if (text.Contains("changed while being read")) return ("source_changed", "The CSV changed during validation. Wait for the external export to finish, then retry.");
                if (text.Contains("row width") || text.Contains("malformed")) return ("malformed_csv", "CSV records do not match the expected structure. Review quoting, delimiters and row widths.");
                if (new[] { "header", "mapped", "column" }.Any(text.Contains)) return ("headers", "Required headers or column mappings are invalid. Review this source’s CSV import format.");
                if (text.Contains("utf") || text.Contains("encoding")) return ("encoding", "The CSV encoding is invalid. Review the source encoding and import format.");
                if (text.Contains("date") || text.Contains("validity")) return ("dates", "Assignment or account dates are invalid. Review date formats and reversed validity intervals.");
                return ("validation", "The CSV failed validation. Review identifiers, field lengths and import settings before retrying.");
            default: return ("read_failed", "The source could not be prepared. Check source access and retry.");
        }
    }
}

/// <summary>MIG-008, port of routers/refresh_schedule.py and the RefreshSchedule settings model: the schedule's status (definition, last outcome, next
/// runs) and the validation of an unsaved draft.</summary>
public static partial class V1RefreshSchedule
{
    [GeneratedRegex(@"^(local|UTC|[A-Za-z0-9_+\-]{1,32}(/[A-Za-z0-9_+\-]{1,32}){0,2})$")]
    private static partial Regex ZonePattern();

    public sealed record Schedule(bool Enabled, string Mode, string Time, string Cron, string Timezone)
    {
        public string Expression => Mode == "daily" ? CronSchedule.DailyCron(Time) : Cron.Trim();
        public JsonObject ToJson() => new() { ["enabled"] = Enabled, ["mode"] = Mode, ["time"] = Time, ["cron"] = Cron, ["timezone"] = Timezone };
    }

    /// <summary>The RefreshSchedule model (strict): its first error as v1's preview reports it ("field: message", or the message alone for the schedule
    /// itself and cron errors).</summary>
    public static (Schedule? Schedule, string? Error) Parse(JsonObject draft)
    {
        string? Field(string name, string message) => message.Contains("cron", StringComparison.OrdinalIgnoreCase) ? message : $"{name}: {message}";
        var enabled = false;
        if (draft["enabled"] is { } e)
        {
            // Pydantic's lax boolean: true/false, 0/1 and the usual words.
            var kind = e.GetValueKind();
            var word = kind == JsonValueKind.String ? e.GetValue<string>().ToLowerInvariant() : kind == JsonValueKind.Number ? e.ToJsonString() : null;
            if (kind is JsonValueKind.True or JsonValueKind.False) enabled = e.GetValue<bool>();
            else if (word is "1" or "true" or "t" or "yes" or "y" or "on") enabled = true;
            else if (word is "0" or "false" or "f" or "no" or "n" or "off") enabled = false;
            else return (null, Field("enabled", word is null ? "Input should be a valid boolean" : "Input should be a valid boolean, unable to interpret input"));
        }
        string? Text(string name, string fallback, int max, out string? error)
        {
            error = null;
            if (draft[name] is not { } node) return fallback;
            if (node.GetValueKind() != JsonValueKind.String) { error = Field(name, "Input should be a valid string"); return null; }
            var value = node.GetValue<string>();
            if (V1Validation.Length(value) > max) { error = Field(name, $"String should have at most {max} characters"); return null; }
            return value;
        }
        var mode = Text("mode", "daily", int.MaxValue, out var problem);
        if (problem is not null) return (null, problem);
        if (mode is not ("daily" or "cron")) return (null, Field("mode", "Input should be 'daily' or 'cron'"));
        var time = Text("time", "06:00", 5, out problem);
        if (problem is not null) return (null, problem);
        var cron = Text("cron", "0 6 * * *", 100, out problem);
        if (problem is not null) return (null, problem);
        var zone = Text("timezone", "local", 64, out problem);
        if (problem is not null) return (null, problem);
        if (!ZonePattern().IsMatch(zone!)) return (null, Field("timezone", @"String should match pattern '^(local|UTC|[A-Za-z0-9_+\-]{1,32}(/[A-Za-z0-9_+\-]{1,32}){0,2})$'"));
        var extra = draft.Select(p => p.Key).FirstOrDefault(k => k is not ("enabled" or "mode" or "time" or "cron" or "timezone"));
        if (extra is not null) return (null, Field(extra, "Extra inputs are not permitted"));
        var schedule = new Schedule(enabled, mode!, time!, cron!, zone!);
        try { CronSchedule.Parse(schedule.Expression); }        // the model validator: a readable expression
        catch (ArgumentException error) { return (null, error.Message); }
        return (schedule, null);
    }

    public static void Map(RouteGroupBuilder api)
    {
        api.MapGet("/refresh-schedule", async (V1Settings settings, HostSettings host, RefreshScheduleState state, TimeProvider clock, CancellationToken ct) =>
            Results.Content(Status(await settings.GetAsync(ct), host, state, clock.GetUtcNow()).ToJsonString(), "application/json"));

        api.MapPost("/refresh-schedule/preview", async (HttpContext http, TimeProvider clock, CancellationToken ct) =>
        {
            var (body, invalid) = await V1Validation.ReadBody(http, ct);
            if (invalid is not null) return invalid;
            var (schedule, error) = Parse(body!);
            JsonObject Invalid(string message) => new() { ["valid"] = false, ["expression"] = null, ["description"] = null, ["next_runs"] = new JsonArray(), ["error"] = message };
            if (schedule is null) return Results.Content(Invalid(error!).ToJsonString(), "application/json");
            try
            {
                var runs = CronSchedule.Check(schedule.Expression, schedule.Timezone, clock.GetUtcNow());
                return Results.Content(new JsonObject
                {
                    ["valid"] = true, ["expression"] = schedule.Expression, ["description"] = CronSchedule.Describe(schedule.Expression, schedule.Timezone),
                    ["next_runs"] = new JsonArray([.. runs.Select(r => (JsonNode)Iso(r))]), ["error"] = null,
                }.ToJsonString(), "application/json");
            }
            catch (ArgumentException failure) { return Results.Content(Invalid(failure.Message).ToJsonString(), "application/json"); }
        });
    }

    internal static string Iso(DateTimeOffset value) => value.ToUniversalTime().ToString("yyyy-MM-dd'T'HH:mm:ss'+00:00'");

    /// <summary>Scheduler.status: the saved definition, the last outcome, what the deployment needs, and the next runs (or why there are none).</summary>
    public static JsonObject Status(JsonObject settings, HostSettings host, RefreshScheduleState state, DateTimeOffset now)
    {
        var saved = settings["refresh_schedule"] as JsonObject ?? [];
        var (schedule, parseError) = Parse(saved.DeepClone().AsObject());
        var server = host.Mode == HostMode.Server;
        var info = new JsonObject
        {
            ["schedule"] = schedule?.ToJson() ?? saved.DeepClone(), ["state"] = state.Read(),
            ["runtime"] = new JsonObject { ["deployment_mode"] = server ? "server" : "desktop", ["requires_running_application"] = !server },
            ["expression"] = null, ["description"] = null, ["next_runs"] = new JsonArray(), ["error"] = parseError,
        };
        if (schedule is not null)
            try
            {
                info["expression"] = schedule.Expression;
                info["description"] = CronSchedule.Describe(schedule.Expression, schedule.Timezone);
                info["next_runs"] = new JsonArray([.. CronSchedule.Check(schedule.Expression, schedule.Timezone, now).Select(r => (JsonNode)Iso(r))]);
            }
            catch (ArgumentException error) { info["error"] = error.Message; }
        var runs = info["next_runs"]!.AsArray();
        info["next_run"] = schedule?.Enabled == true && runs.Count > 0 ? runs[0]!.DeepClone() : null;
        return info;
    }
}

/// <summary>The scheduler's last outcome (v1 refresh-schedule.json): attempt, success and failure times, status, message and consecutive failures.
/// A small file in the data directory, written atomically; an unreadable file reads as "never attempted".</summary>
public sealed class RefreshScheduleState(DatabaseOptions options)
{
    private static readonly string[] Fields = ["last_attempt", "last_success", "last_failure", "last_status", "last_message", "consecutive_failures"];
    private readonly Lock _gate = new();
    private string FilePath => Path.Combine(options.DataDirectory, "refresh-schedule.json");

    public JsonObject Read()
    {
        lock (_gate)
        {
            var empty = new JsonObject(Fields.Select(f => KeyValuePair.Create(f, (JsonNode?)null)));
            try
            {
                if (!File.Exists(FilePath)) return empty;
                if (JsonNode.Parse(File.ReadAllText(FilePath)) is not JsonObject data) return empty;
                var state = new JsonObject(Fields.Select(f => KeyValuePair.Create(f, data[f]?.DeepClone())));
                foreach (var key in new[] { "last_attempt", "last_success", "last_failure" })
                    if (state[key] is { } value && !DateTimeOffset.TryParse((string?)value, System.Globalization.CultureInfo.InvariantCulture, System.Globalization.DateTimeStyles.None, out _)) return empty;
                if ((string?)state["last_status"] is not (null or "succeeded" or "partial" or "failed" or "skipped")) return empty;
                if (state["consecutive_failures"] is { } failures && failures.GetValueKind() != JsonValueKind.Number) return empty;
                return state;
            }
            catch (Exception error) when (error is IOException or UnauthorizedAccessException or JsonException or InvalidOperationException or FormatException) { return empty; }
        }
    }

    public void Write(JsonObject state)
    {
        lock (_gate)
        {
            var temporary = FilePath + ".tmp";
            File.WriteAllText(temporary, new JsonObject(Fields.Select(f => KeyValuePair.Create(f, state[f]?.DeepClone()))).ToJsonString());
            File.Move(temporary, FilePath, overwrite: true);
        }
    }
}

/// <summary>MIG-008, port of scheduler.py: the scheduled refresh inside the server process (no browser needed). Evaluated every 20 seconds; a changed
/// definition starts from now; missed slots (application stopped or busy) are skipped, never replayed; a refresh that is still running is skipped; a
/// failed refresh keeps the previous data. A refresh is cancelled after 30 minutes (an unreachable share) and the schedule keeps running.</summary>
public sealed class RefreshScheduler(IServiceProvider services, RefreshScheduleState state, TimeProvider clock, ILogger<RefreshScheduler> logger) : BackgroundService
{
    public static readonly TimeSpan Tick = TimeSpan.FromSeconds(20);
    public TimeSpan Deadline { get; set; } = TimeSpan.FromMinutes(30);
    private DateTimeOffset _cursor = clock.GetUtcNow();
    private string? _signature;

    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        while (!stoppingToken.IsCancellationRequested)
        {
            try { await TickAsync(clock.GetUtcNow(), stoppingToken); }
            catch (OperationCanceledException) when (stoppingToken.IsCancellationRequested) { return; }
            catch (Exception error) { logger.LogWarning("Scheduler evaluation failed ({Type}).", error.GetType().Name); }
            try { await Task.Delay(Tick, clock, stoppingToken); }
            catch (OperationCanceledException) { return; }
        }
    }

    /// <summary>Evaluates once: "idle", "skipped", "succeeded", "partial" or "failed".</summary>
    public async Task<string> TickAsync(DateTimeOffset now, CancellationToken ct)
    {
        var settings = await services.GetRequiredService<V1Settings>().GetAsync(ct);
        var saved = settings["refresh_schedule"] as JsonObject ?? [];
        var signature = saved.ToJsonString();
        if (signature != _signature) (_signature, _cursor) = (signature, now);   // a changed definition starts from now
        var (schedule, _) = V1RefreshSchedule.Parse(saved.DeepClone().AsObject());
        if (schedule is null || !schedule.Enabled) { _cursor = now; return "idle"; }
        List<DateTimeOffset> due;
        try { due = CronSchedule.NextRuns(schedule.Expression, schedule.Timezone, _cursor, 1); }
        catch (ArgumentException) { _cursor = now; return "idle"; }
        _cursor = now;   // slots missed while stopped or busy are skipped, never replayed in a burst
        if (due.Count == 0 || due[0] > now) return "idle";
        return await RunAsync(now, ct);
    }

    private async Task<string> RunAsync(DateTimeOffset now, CancellationToken ct)
    {
        var current = state.Read();
        current["last_attempt"] = V1RefreshSchedule.Iso(now);
        string outcome, message;
        using var deadline = CancellationTokenSource.CreateLinkedTokenSource(ct);
        deadline.CancelAfter(Deadline);
        try
        {
            var (report, busy) = await V1Refresh.RunAsync(services, "scheduled-refresh", deadline.Token);
            if (busy)
            {
                current["last_status"] = "skipped"; current["last_message"] = "Skipped: another load or refresh was already running.";
                Save(current);
                return "skipped";
            }
            var status = (string)report!["status"]!;
            outcome = status is "changed" or "unchanged" ? "succeeded" : status == "partial" ? "partial" : "failed";
            message = outcome switch
            {
                "succeeded" => "Refresh completed.", "partial" => "Some sources failed; their previous validated data was kept.",
                _ => "The refresh failed; previous validated data was kept.",
            };
        }
        catch (OperationCanceledException) when (!ct.IsCancellationRequested)
        {
            var minutes = Math.Max(1, (int)Math.Round(Deadline.TotalMinutes));
            (outcome, message) = ("failed", $"The refresh did not finish within {minutes} minutes and was cancelled (a source may be unreachable); previous validated data was kept.");
            logger.LogWarning("Scheduled refresh exceeded its deadline and was cancelled; previous data retained.");
        }
        catch (Exception error) when (error is not OperationCanceledException)
        {
            (outcome, message) = ("failed", "The refresh could not run; previous validated data was kept.");
            logger.LogWarning("Scheduled refresh failed ({Type}); previous data retained.", error.GetType().Name);
        }
        var stamp = V1RefreshSchedule.Iso(now);
        if (outcome == "failed") { current["last_failure"] = stamp; current["consecutive_failures"] = ((int?)current["consecutive_failures"] ?? 0) + 1; }
        else
        {
            current["last_success"] = stamp; current["consecutive_failures"] = 0;
            if (outcome == "partial") current["last_failure"] = stamp;
        }
        current["last_status"] = outcome; current["last_message"] = message;
        Save(current);
        logger.LogInformation("Scheduled refresh finished (status={Status}).", outcome);
        return outcome;
    }

    private void Save(JsonObject current)
    {
        try { state.Write(current); }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException) { logger.LogWarning("Scheduled refresh status could not be saved; the schedule keeps running."); }
    }
}
