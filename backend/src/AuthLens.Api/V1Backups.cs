using System.Text.Json;
using System.Text.Json.Nodes;
using Microsoft.AspNetCore.Http.Features;
using AuthLens.Application.Backups;
using AuthLens.Domain.Scheduling;
using AuthLens.Persistence;

namespace AuthLens.Api;

/// <summary>Port of routers/backups.py and backup_schedule.py: administrator-only application backups (create, history, download, delete), the host
/// key status and escrow verification, the backup schedule, and restore (upload, preview, confirm for the next restart, cancel). On a Server, v1 requires
/// an authenticated administrator account; a shared access token is refused (403), so an anonymous token holder never restores or exports all data.</summary>
public static class V1Backups
{
    public static void Map(RouteGroupBuilder api)
    {
        var group = api.MapGroup("/backups");

        group.MapGet("", (HttpContext http, ApplicationBackups backups, HostSettings host) =>
        {
            if (Guard(http) is { } refused) return refused;
            var status = backups.Status(); status["reauthentication_required"] = host.Mode == HostMode.Server && host.Authentication == AuthenticationMode.Accounts;
            return Json(status);
        });

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
            if (Extra(body!, "recovery_key", "reauth_code") is { } extra) return extra;
            if (body!["recovery_key"] is not { } key || key.GetValueKind() != JsonValueKind.String || key.GetValue<string>().Length > 96) return Invalid("recovery_key", "Field required (a string of at most 96 characters)");
            if (http.RequestServices.GetRequiredService<HostSettings>().Mode == HostMode.Server)
            {
                if (body["reauth_code"] is not JsonValue proof || !proof.TryGetValue<string>(out var code)) return Results.Json(new { detail = "Confirm your current administrator password before verifying a recovery copy." }, statusCode: 403);
                try { await http.RequestServices.GetRequiredService<AuthLens.Application.Accounts.AccountStore>().ConsumeBackupVerificationAsync(Actors.Current(http), code); }
                catch (AuthLens.Application.Accounts.AuthException error) { return Results.Json(new { detail = error.Message }, statusCode: error.Status); }
            }
            return Run(() => BackupKeys.VerifyEscrow(key.GetValue<string>(), options.DataDirectory, Actors.Name(http), clock.GetUtcNow()));
        });

        group.MapPost("/cancel", (HttpContext http, ApplicationBackups backups) => Guard(http) ?? Run(backups.Cancel));

        group.MapGet("/schedule", async (HttpContext http, DatabaseOptions options, ApplicationBackups backups, TimeProvider clock, CancellationToken ct) =>
            Guard(http) ?? await Run(async () => await BackupSchedule.StatusAsync(options.DataDirectory, backups, clock.GetUtcNow(), ct, clock.LocalTimeZone)));

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
                return await BackupSchedule.StatusAsync(options.DataDirectory, backups, clock.GetUtcNow(), ct, clock.LocalTimeZone);
            });
        });

        group.MapGet("/history", async (HttpContext http, ApplicationBackups backups, CancellationToken ct) => Guard(http) ?? await Run(() => backups.HistoryAsync(ct)));

        group.MapPost("/{identity}/verify", async (HttpContext http, string identity, ApplicationBackups backups, CancellationToken ct) =>
        {
            if (Guard(http) is { } refused) return refused;
            var (body, invalid) = await Body(http, ct);
            if (invalid is not null) return invalid;
            if (Extra(body!, "secret") is { } extra) return extra;
            var secret = "";
            if (body!["secret"] is { } value && (value is not JsonValue text || !text.TryGetValue<string>(out secret) || secret.Length > 1024)) return Invalid("secret", "Use a passphrase or recovery copy of at most 1024 characters");
            return await Run(() => backups.VerifyAsync(identity, secret, ct));
        });

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
                // Open before returning the result: a concurrent deletion is a meaningful refusal,
                // and a successful response retains one stable stream until the download completes.
                return Results.File(File.OpenRead(path), "application/octet-stream", $"AuthLens-{kind}-{identity}.slbak");
            }
            catch (BackupException error) { return Results.Json(new { detail = error.Message }, statusCode: error.Status); }
            catch (Exception error) when (error is IOException or UnauthorizedAccessException) { return Results.Json(new { detail = "The archive is unavailable or in use. Retry after the active archive operation finishes." }, statusCode: 409); }
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
    public sealed record Definition(V1RefreshSchedule.Schedule Schedule, int Keep, int? Weekday = null)
    {
        public JsonObject ToJson() { var value = Schedule.ToJson(); value["keep"] = Keep; if (Weekday is not null) { value["mode"] = "weekly"; value["weekday"] = Weekday; } return value; }
    }

    private static readonly Lock Gate = new();
    private static readonly SemaphoreSlim Evaluations = new(1, 1);
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
        int? weekday = null;
        if (copy["mode"] is JsonValue mode && mode.TryGetValue<string>(out var selected) && selected == "weekly")
        {
            var day = 1;
            if (copy["weekday"] is { } node && (node is not JsonValue dayValue || !dayValue.TryGetValue<int>(out day) || day is < 0 or > 6)) return (null, "weekday: Choose Sunday (0) through Saturday (6).");
            if (copy["time"] is not JsonValue time || !time.TryGetValue<string>(out var hour)) return (null, "time: A weekly execution time is required.");
            try { var fields = CronSchedule.DailyCron(hour).Split(' '); copy["cron"] = $"{fields[0]} {fields[1]} * * {day}"; }
            catch (ArgumentException problem) { return (null, problem.Message); }
            copy["mode"] = "cron"; copy.Remove("weekday"); weekday = day;
        }
        var (schedule, error) = V1RefreshSchedule.Parse(copy);
        if (schedule is null) return (null, error);
        try { CronSchedule.Check(schedule.Expression, schedule.Timezone, DateTimeOffset.UtcNow); }
        catch (ArgumentException problem) { return (null, problem.Message); }
        return (new Definition(schedule, keep, weekday), null);
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
                if (JsonNode.Parse(File.ReadAllText(file)) is JsonObject value && value["revision"] is JsonValue revision && revision.TryGetValue<long>(out var number) && number >= 0 && value["schedule"] is JsonObject definition && Parse(definition).Value is not null) return value;
                empty["configuration_error"] = "The stored backup schedule is invalid. Automatic backups are disabled until an administrator reviews and saves it.";
                return empty;
            }
            catch (Exception error) when (error is IOException or JsonException) { empty["configuration_error"] = "The backup schedule could not be read. Check its protected storage and host logs."; return empty; }
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

    public static async Task<JsonObject> StatusAsync(string data, ApplicationBackups backups, DateTimeOffset now, CancellationToken ct, TimeZoneInfo? localZone = null)
    {
        var value = Read(data);
        var definition = Parse(value["schedule"]!.AsObject()).Value!;
        var schedule = definition.Schedule;
        var items = (await backups.HistoryAsync(ct))["items"]!.AsArray();
        value["next_runs"] = schedule.Enabled ? new JsonArray([.. CronSchedule.Check(schedule.Expression, schedule.Timezone, now, localZone).Select(r => (JsonNode)V1RefreshSchedule.Iso(r))]) : new JsonArray();
        value["description"] = CronSchedule.Describe(schedule.Expression, schedule.Timezone);
        value["requires_restart"] = false;
        value["last_success"] ??= items.FirstOrDefault(r => (string?)r!["origin"] == "scheduled" && (string?)r["status"] == "ready")?["created_at"]?.DeepClone();
        value["last_failure"] = value["last_failure"]?.DeepClone();
        value["encryption_ready"] = BackupKeys.Status(data)["escrow_verified"]?.GetValue<bool>() == true;
        value["attempts"] ??= new JsonArray();
        value["last_outcome"] ??= null;
        return value;
    }

    /// <summary>One evaluation: claims the first due occurrence after the cursor once; returns idle, skipped, or the outcome.</summary>
    public static async Task<string> TickAsync(string data, ApplicationBackups backups, DataLoadGate loader, DateTimeOffset now, DateTimeOffset cursor, CancellationToken ct, TimeZoneInfo? localZone = null)
    {
        if (!await Evaluations.WaitAsync(0, ct)) return "skipped: another scheduler evaluation is running";
        try
        {
            var value = Read(data);
            var schedule = Parse(value["schedule"]!.AsObject()).Value!.Schedule;
            if (!schedule.Enabled && value["running"] is null) return "idle";
            Directory.CreateDirectory(Path.Combine(data, "backups"));
            FileStream processLease;
            try { processLease = new FileStream(Path.Combine(data, "backups", "schedule-execution.lock"), FileMode.OpenOrCreate, FileAccess.ReadWrite, FileShare.None); }
            catch (IOException) { return "skipped: another scheduler process is running"; }
            using (processLease)
            {
                value = Read(data);
                schedule = Parse(value["schedule"]!.AsObject()).Value!.Schedule;
                if (!schedule.Enabled && value["running"] is null) return "idle";
                if (value["running"] is JsonObject interrupted)
                {
                    var claimedId = (string?)interrupted["backup_id"] ?? "";
                    var items = (await backups.HistoryAsync(ct))["items"]!.AsArray();
                    var completed = items.Any(item => (string?)item!["id"] == claimedId && (bool?)item["verified"] == true);
                    var recovered = completed ? "ready: completed archive recovered after interruption" : "failed: interrupted backup; retained partial files require operator review, and this occurrence will not be replayed";
                    CompleteAttempt(data, (string?)interrupted["occurrence"] ?? "", claimedId, recovered, now);
                    return recovered;
                }
                var runs = CronSchedule.NextRuns(schedule.Expression, schedule.Timezone, cursor, 1, localZone);
                if (runs.Count == 0 || runs[0] > now) return "idle";
                var occurrence = V1RefreshSchedule.Iso(runs[0]);
                if ((string?)value["last_occurrence"] == occurrence) return "skipped";
                var id = Guid.NewGuid().ToString("N");
                lock (Gate)
                {
                    var current = Read(data);
                    if ((long)current["revision"]! != (long)value["revision"]!) return "idle";
                    current["last_occurrence"] = occurrence;
                    current["running"] = new JsonObject { ["backup_id"] = id, ["occurrence"] = occurrence, ["started_at"] = V1RefreshSchedule.Iso(now) };
                    Write(data, current); // flushed before any archive write: interruption cannot duplicate this claim
                }
                string outcome;
                if (BackupKeys.Status(data)["escrow_verified"]?.GetValue<bool>() != true) outcome = "skipped: recovery key copy not verified";
                else if (loader.Loading.CurrentCount == 0 || backups.Busy) outcome = "skipped: another operation is running";
                else
                    try { await backups.CreateAsync(BackupKind.Automatic, "", "scheduler", ct, id); outcome = "ready"; }
                    catch (BackupException error) { outcome = "failed: " + error.Message; }
                CompleteAttempt(data, occurrence, id, outcome, now);
                return outcome;
            }
        }
        finally { Evaluations.Release(); }
    }

    private static void CompleteAttempt(string data, string occurrence, string id, string outcome, DateTimeOffset now)
    {
        lock (Gate)
        {
            // Save may change/disable the schedule while an archive is written. Merge runtime state into
            // the latest revision; never overwrite the administrator's new configuration with a stale copy.
            var value = Read(data);
            value["running"] = null; value["last_occurrence"] = occurrence;
            value["last_attempt"] = V1RefreshSchedule.Iso(now); value["last_outcome"] = outcome;
            if (outcome.StartsWith("failed:", StringComparison.Ordinal)) value["last_failure"] = V1RefreshSchedule.Iso(now);
            if (outcome.StartsWith("ready", StringComparison.Ordinal)) value["last_success"] = V1RefreshSchedule.Iso(now);
            var attempts = value["attempts"] as JsonArray ?? [];
            attempts.Add(new JsonObject { ["at"] = V1RefreshSchedule.Iso(now), ["occurrence"] = occurrence, ["backup_id"] = id, ["status"] = outcome });
            while (attempts.Count > 50) attempts.RemoveAt(0);
            value["attempts"] = attempts.DeepClone(); Write(data, value);
        }
    }
}

/// <summary>Runs the backup schedule inside the server process (every 20 seconds) and the daily data retention check.</summary>
public sealed class BackupScheduler(DatabaseOptions options, ApplicationBackups backups, AuthLens.Application.Retention.DataRetention retention, DataLoadGate loader, TimeProvider clock, ILogger<BackupScheduler> logger) : BackgroundService
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
                var outcome = await BackupSchedule.TickAsync(options.DataDirectory, backups, loader, now, _cursor, stoppingToken, clock.LocalTimeZone);
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
