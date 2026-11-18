using System.Text.Json;
using System.Text.Json.Nodes;
using Microsoft.AspNetCore.Http.Features;
using SapLens.Application.Backups;
using SapLens.Domain.Scheduling;
using SapLens.Persistence;

namespace SapLens.Api;

/// <summary>Port of routers/backups.py and backup_schedule.py: administrator-only application backups (create, history, download, delete), the host
/// key status and escrow verification, the backup schedule, and restore (upload, preview, confirm for the next restart, cancel). On a Server, v1 requires
/// an authenticated administrator account; a shared access token is refused (403), so an anonymous token holder never restores or exports all data.</summary>
public static class V1Backups
{
    public static void Map(RouteGroupBuilder api)
    {
        var group = api.MapGroup("/backups");

        group.MapGet("", (HttpContext http, ApplicationBackups backups) => Guard(http) ?? Json(backups.Status()));

        group.MapPost("/create", async (HttpContext http, ApplicationBackups backups, CancellationToken ct) =>
        {
            if (Guard(http) is { } refused) return refused;
            var (body, invalid) = await Body(http, ct);
            if (invalid is not null) return invalid;
            if (Extra(body!, "passphrase") is { } extra) return extra;
            var passphrase = body!["passphrase"] is { } p ? p.GetValueKind() == JsonValueKind.String ? p.GetValue<string>() : null : "";
            if (passphrase is null || passphrase.Length > 1024) return Invalid("passphrase", "Input should be a valid string of at most 1024 characters");
            if (passphrase.Length is > 0 and < 12) return Results.Json(new { detail = "Backup passphrases need at least 12 characters." }, statusCode: 409);
            return await Run(() => backups.CreateAsync(BackupKind.Manual, passphrase, Actors.Name(http), ct));
        });

        group.MapPost("/key/verify", async (HttpContext http, DatabaseOptions options, TimeProvider clock, CancellationToken ct) =>
        {
            if (Guard(http) is { } refused) return refused;
            var (body, invalid) = await Body(http, ct);
            if (invalid is not null) return invalid;
            if (Extra(body!, "recovery_key") is { } extra) return extra;
            if (body!["recovery_key"] is not { } key || key.GetValueKind() != JsonValueKind.String || key.GetValue<string>().Length > 96) return Invalid("recovery_key", "Field required (a string of at most 96 characters)");
            return Run(() => BackupKeys.VerifyEscrow(key.GetValue<string>(), options.DataDirectory, Actors.Name(http), clock.GetUtcNow()));
        });

        group.MapPost("/cancel", (HttpContext http, ApplicationBackups backups) => Guard(http) ?? Run(backups.Cancel));

        group.MapGet("/schedule", async (HttpContext http, DatabaseOptions options, ApplicationBackups backups, TimeProvider clock, CancellationToken ct) =>
            Guard(http) ?? await Run(async () => await BackupSchedule.StatusAsync(options.DataDirectory, backups, clock.GetUtcNow(), ct)));

        group.MapPost("/schedule", async (HttpContext http, DatabaseOptions options, ApplicationBackups backups, TimeProvider clock, CancellationToken ct) =>
        {
            if (Guard(http) is { } refused) return refused;
            var (body, invalid) = await Body(http, ct);
            if (invalid is not null) return invalid;
            if (Extra(body!, "revision", "schedule") is { } extra) return extra;
            if (body!["revision"] is not { } r || r.GetValueKind() != JsonValueKind.Number || !r.AsValue().TryGetValue<long>(out var revision) || revision < 0) return Invalid("revision", "Input should be a non-negative integer");
            if (body["schedule"] is not JsonObject draft) return Invalid("schedule", "Input should be a valid dictionary");
            var (schedule, error) = BackupSchedule.Parse(draft);
            if (schedule is null) return Results.Json(new { detail = error }, statusCode: 422);
            return await Run(async () =>
            {
                BackupSchedule.Save(options.DataDirectory, schedule, revision);
                return await BackupSchedule.StatusAsync(options.DataDirectory, backups, clock.GetUtcNow(), ct);
            });
        });

        group.MapGet("/history", async (HttpContext http, ApplicationBackups backups, CancellationToken ct) => Guard(http) ?? await Run(() => backups.HistoryAsync(ct)));

        group.MapPost("/{identity}/delete", async (HttpContext http, string identity, ApplicationBackups backups, CancellationToken ct) =>
        {
            if (Guard(http) is { } refused) return refused;
            var (body, invalid) = await Body(http, ct);
            if (invalid is not null) return invalid;
            if (Extra(body!, "confirm") is { } extra) return extra;
            return await Run(() => backups.DeleteAsync(identity, body!["confirm"] is { } c && c.GetValueKind() == JsonValueKind.True, Actors.Name(http), ct));
        });

        group.MapPost("/upload", async (HttpContext http, ApplicationBackups backups, CancellationToken ct) =>
        {
            if (Guard(http) is { } refused) return refused;
            if (http.Request.ContentType?.Split(';')[0].Trim().ToLowerInvariant() is not ("application/octet-stream" or "application/gzip"))
                return Results.Json(new { detail = "Select an encrypted .slbak backup." }, statusCode: 415);
            if (http.Request.ContentLength > ApplicationBackups.MaxUpload) return Results.Json(new { detail = "Settings uploads support up to 256 MiB." }, statusCode: 413);
            var limit = http.Features.Get<IHttpMaxRequestBodySizeFeature>();
            if (limit is { IsReadOnly: false }) limit.MaxRequestBodySize = ApplicationBackups.MaxUpload + 1;
            var secret = "";
            if (http.Request.Headers["X-SAP-Lens-Backup-Secret"].ToString() is { Length: > 0 } encoded)
            {
                if (encoded.Length > 2048) return Results.Json(new { detail = "The backup secret header is invalid." }, statusCode: 422);
                try { secret = System.Text.Encoding.UTF8.GetString(Convert.FromBase64String(encoded)); }
                catch (FormatException) { return Results.Json(new { detail = "The backup secret header is invalid." }, statusCode: 422); }
            }
            try { return Json(await backups.StageAsync(http.Request.Body, secret, ct)); }
            catch (BackupException error) { return Results.Json(new { detail = error.Message }, statusCode: error.Status == 409 && error.Message.Contains("restore", StringComparison.Ordinal) ? 409 : error.Status == 413 ? 413 : 422); }
        });

        group.MapPost("/uploads/{identity}/cancel", (HttpContext http, string identity, ApplicationBackups backups) => Guard(http) ?? Run(() => backups.Discard(identity)));

        group.MapPost("/restore", async (HttpContext http, ApplicationBackups backups, CancellationToken ct) =>
        {
            if (Guard(http) is { } refused) return refused;
            var (body, invalid) = await Body(http, ct);
            if (invalid is not null) return invalid;
            if (Extra(body!, "id", "sha256", "confirm", "confirm_accounts") is { } extra) return extra;
            string Text(string name) => body![name] is { } v && v.GetValueKind() == JsonValueKind.String ? v.GetValue<string>() : "";
            bool Flag(string name) => body![name] is { } v && v.GetValueKind() == JsonValueKind.True;
            if (!ApplicationBackups.Identity().IsMatch(Text("id")) || !ApplicationBackups.Identity().IsMatch(Text("sha256")[..Math.Min(32, Text("sha256").Length)]) || Text("sha256").Length != 64)
                return Invalid("id", "A staged restore identifier and its archive SHA-256 are required");
            return Run(() => backups.Confirm(Text("id"), Text("sha256"), Flag("confirm"), Flag("confirm_accounts"), Actors.Name(http)));
        });

        group.MapGet("/{identity}/download", async (HttpContext http, string identity, string? kind, ApplicationBackups backups, CancellationToken ct) =>
        {
            if (Guard(http) is { } refused) return refused;
            kind ??= "backup";
            try
            {
                var path = await backups.DownloadAsync(identity, kind, ct);
                http.Response.Headers.CacheControl = "no-store";
                return Results.File(path, "application/octet-stream", $"SAP-Lens-{kind}-{identity}.slbak");
            }
            catch (BackupException error) { return Results.Json(new { detail = error.Message }, statusCode: error.Status); }
        });
    }

    /// <summary>v1 admin() for backups, storage and retention: Server deployments need an authenticated administrator account (a shared access token is
    /// refused); Desktop is the local operator.</summary>
    internal static IResult? Guard(HttpContext http)
    {
        var host = http.RequestServices.GetRequiredService<HostSettings>();
        if (host.Mode != HostMode.Server) return null;
        if (host.Authentication == AuthenticationMode.Accounts && Actors.Current(http).Role == "administrator") return null;
        return Results.Json(new { detail = "Application backups require an authenticated administrator account. Other deployments can use stopped host maintenance." }, statusCode: 403);
    }

    private static IResult Json(JsonNode value) => Results.Content(value.ToJsonString(), "application/json");

    private static IResult Invalid(string field, string message) =>
        Results.Json(new { detail = new[] { new { type = "value_error", loc = new[] { "body", field }, msg = message } } }, statusCode: 422);

    private static IResult? Extra(JsonObject body, params string[] allowed) =>
        body.Select(p => p.Key).FirstOrDefault(k => !allowed.Contains(k)) is { } extra
            ? Results.Json(new { detail = new[] { new { type = "extra_forbidden", loc = new[] { "body", extra }, msg = "Extra inputs are not permitted" } } }, statusCode: 422) : null;

    /// <summary>A JSON object body; an empty body reads as {} (v1 default models).</summary>
    private static async Task<(JsonObject?, IResult?)> Body(HttpContext http, CancellationToken ct)
    {
        if (http.Request.ContentLength is 0 or null && !http.Request.Headers.ContainsKey("Transfer-Encoding")) return ([], null);
        return await V1Validation.ReadBody(http, ct);
    }

    private static IResult Run(Func<JsonObject> action)
    {
        try { return Json(action()); }
        catch (BackupException error) { return Results.Json(new { detail = error.Message }, statusCode: error.Status); }
    }

    private static async Task<IResult> Run(Func<Task<JsonObject>> action)
    {
        try { return Json(await action()); }
        catch (BackupException error) { return Results.Json(new { detail = error.Message }, statusCode: error.Status); }
    }
}

/// <summary>backup_schedule.py: the schedule (the refresh schedule's fields plus keep 1..100) in backups/schedule.json with an optimistic revision, its
/// status, and one evaluation per tick. Automatic backups need a verified recovery-key copy. Missed slots are skipped, never replayed. Automatic archives
/// are removed by the approved backup retention (default 90 days), not by the keep count (v1: the legacy count limit cannot remove recent backups ahead of retention).</summary>
public static class BackupSchedule
{
    public sealed record Definition(V1RefreshSchedule.Schedule Schedule, int Keep)
    {
        public JsonObject ToJson() { var value = Schedule.ToJson(); value["keep"] = Keep; return value; }
    }

    private static readonly Lock Gate = new();
    private static string FileOf(string data) => Path.Combine(data, "backups", "schedule.json");

    public static (Definition? Value, string? Error) Parse(JsonObject draft)
    {
        var copy = draft.DeepClone().AsObject();
        var keep = 7;
        if (copy["keep"] is { } k)
        {
            if (k.GetValueKind() != JsonValueKind.Number || !k.AsValue().TryGetValue<int>(out keep) || keep is < 1 or > 100) return (null, "keep: Input should be an integer from 1 to 100");
            copy.Remove("keep");
        }
        var (schedule, error) = V1RefreshSchedule.Parse(copy);
        return schedule is null ? (null, error) : (new Definition(schedule, keep), null);
    }

    public static JsonObject Read(string data)
    {
        lock (Gate)
        {
            var empty = new JsonObject { ["revision"] = 0, ["schedule"] = new Definition(V1RefreshSchedule.Parse([]).Schedule!, 7).ToJson() };
            try
            {
                var file = FileOf(data);
                if (!File.Exists(file)) return empty;
                if (new FileInfo(file).Length > 32000) throw new BackupException("Backup schedule metadata exceeds its limit.");
                return JsonNode.Parse(File.ReadAllText(file)) is JsonObject value && Parse((value["schedule"] as JsonObject) ?? []).Value is not null ? value : empty;
            }
            catch (Exception error) when (error is IOException or JsonException) { return empty; }
        }
    }

    public static void Save(string data, Definition definition, long revision)
    {
        if (definition.Schedule.Enabled && BackupKeys.Status(data)["escrow_verified"]?.GetValue<bool>() != true)
            throw new BackupException("Verify a separately stored recovery key before enabling automatic backups.");
        lock (Gate)
        {
            var current = Read(data);
            if (long.Parse(current["revision"]!.ToJsonString(), System.Globalization.CultureInfo.InvariantCulture) != revision) throw new BackupException("Backup schedule changed; reload before saving.");
            current["revision"] = revision + 1;
            current["schedule"] = definition.ToJson();
            Write(data, current);
        }
    }

    private static void Write(string data, JsonObject value)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(FileOf(data))!);
        BackupKeys.WriteAtomic(FileOf(data), value.ToJsonString());
    }

    public static async Task<JsonObject> StatusAsync(string data, ApplicationBackups backups, DateTimeOffset now, CancellationToken ct)
    {
        var value = Read(data);
        var definition = Parse(value["schedule"]!.AsObject()).Value!;
        var schedule = definition.Schedule;
        var items = (await backups.HistoryAsync(ct))["items"]!.AsArray();
        value["next_runs"] = schedule.Enabled ? new JsonArray([.. CronSchedule.Check(schedule.Expression, schedule.Timezone, now).Select(r => (JsonNode)V1RefreshSchedule.Iso(r))]) : new JsonArray();
        value["description"] = CronSchedule.Describe(schedule.Expression, schedule.Timezone);
        value["requires_restart"] = false;
        value["last_success"] = items.FirstOrDefault(r => (string?)r!["origin"] == "scheduled" && (string?)r["status"] == "ready")?["created_at"]?.DeepClone();
        value["last_failure"] = value["last_failure"]?.DeepClone();
        value["encryption_ready"] = BackupKeys.Status(data)["escrow_verified"]?.GetValue<bool>() == true;
        value["attempts"] ??= new JsonArray();
        value["last_outcome"] ??= null;
        return value;
    }

    /// <summary>One evaluation: claims the first due occurrence after the cursor once; returns idle, skipped, or the outcome.</summary>
    public static async Task<string> TickAsync(string data, ApplicationBackups backups, DataLoadGate loader, DateTimeOffset now, DateTimeOffset cursor, CancellationToken ct)
    {
        var value = Read(data);
        var schedule = Parse(value["schedule"]!.AsObject()).Value!.Schedule;
        if (!schedule.Enabled) return "idle";
        var runs = CronSchedule.NextRuns(schedule.Expression, schedule.Timezone, cursor, 1);
        if (runs.Count == 0 || runs[0] > now) return "idle";
        var occurrence = V1RefreshSchedule.Iso(runs[0]);
        if ((string?)value["last_occurrence"] == occurrence) return "skipped";
        value["last_occurrence"] = occurrence;
        string outcome;
        if (BackupKeys.Status(data)["escrow_verified"]?.GetValue<bool>() != true) outcome = "skipped: recovery key copy not verified";
        else if (loader.Loading.CurrentCount == 0) outcome = "skipped: another operation is running";
        else
            try { await backups.CreateAsync(BackupKind.Automatic, "", "scheduler", ct); outcome = "ready"; }
            catch (BackupException error) { outcome = "failed: " + error.Message; value["last_failure"] = V1RefreshSchedule.Iso(now); }
        value["last_attempt"] = V1RefreshSchedule.Iso(now);
        value["last_outcome"] = outcome;
        var attempts = value["attempts"] as JsonArray ?? [];
        attempts.Add(new JsonObject { ["at"] = V1RefreshSchedule.Iso(now), ["occurrence"] = occurrence, ["status"] = outcome });
        while (attempts.Count > 50) attempts.RemoveAt(0);
        value["attempts"] = attempts.DeepClone();
        lock (Gate) Write(data, value);
        return outcome;
    }
}

/// <summary>Runs the backup schedule inside the server process (every 20 seconds) and the daily data retention check.</summary>
public sealed class BackupScheduler(DatabaseOptions options, ApplicationBackups backups, SapLens.Application.Retention.DataRetention retention, DataLoadGate loader, TimeProvider clock, ILogger<BackupScheduler> logger) : BackgroundService
{
    private DateTimeOffset _cursor = clock.GetUtcNow();
    private string? _signature;

    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        while (!stoppingToken.IsCancellationRequested)
        {
            var now = clock.GetUtcNow();
            try
            {
                var signature = BackupSchedule.Read(options.DataDirectory)["schedule"]!.ToJsonString();
                if (signature != _signature) (_signature, _cursor) = (signature, now);     // a changed definition starts from now
                var outcome = await BackupSchedule.TickAsync(options.DataDirectory, backups, loader, now, _cursor, stoppingToken);
                if (outcome != "idle") { _cursor = now; logger.LogInformation("Scheduled backup: {Outcome}", outcome.Split(':')[0]); }
                // The daily retention check (all categories); skipped while a restore waits or a load runs, never disturbs the application.
                if (retention.Due() && loader.Loading.CurrentCount > 0 && !File.Exists(Path.Combine(options.DataDirectory, "restore", "pending.json")))
                    logger.LogInformation("Data retention check: {Outcome}", await retention.CheckAsync("automatic", stoppingToken));
            }
            catch (OperationCanceledException) when (stoppingToken.IsCancellationRequested) { return; }
            catch (Exception error) { logger.LogWarning("Backup scheduler evaluation failed ({Type}).", error.GetType().Name); }
            try { await Task.Delay(RefreshScheduler.Tick, clock, stoppingToken); }
            catch (OperationCanceledException) { return; }
        }
    }
}
