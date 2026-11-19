using System.Text.Json;
using System.Text.Json.Nodes;
using Microsoft.EntityFrameworkCore;
using AuthLens.Application;
using AuthLens.Persistence;

namespace AuthLens.Api;

/// <summary>Port of routers/storage.py (status, migration/confirm, migration/delete-backup) on the AuthLens database. The pre-migration backup is the
/// verified SQLite copy DatabaseMaintenance takes before applying schema migrations (BackupKind.Migration). Confirming that the upgrade works keeps it; only
/// an explicit administrator deletion of a confirmed migration backup removes it, and no automatic retention ever does. The identifier is the first 32 hex
/// characters of the copy's SHA-256.</summary>
public static class V1Storage
{
    public static void Map(RouteGroupBuilder api)
    {
        api.MapGet("/storage/status", async (HttpContext http, IServiceProvider services, CancellationToken ct) => Guard(http) ?? Json(await StatusAsync(services, ct)));

        api.MapPost("/storage/migration/confirm", async (HttpContext http, IServiceProvider services, CancellationToken ct) =>
        {
            if (Guard(http) is { } refused) return refused;
            var (body, error) = await Read(http, ct);
            if (error is not null) return error;
            if (!body!.Confirm) return Detail("Confirm that the upgraded installation works to release the pre-migration backup.", 422);
            var maintenance = services.GetRequiredService<DatabaseMaintenance>();
            var integrity = await maintenance.VerifyAsync(ct);
            if (!maintenance.Ready || !integrity.Ok)
                return Detail("The upgraded store is not healthy yet, so the backup is kept: " + string.Join("; ", integrity.Problems.Take(5).DefaultIfEmpty(maintenance.NotReadyReason ?? "not ready")), 409);
            var confirmed = await services.GetRequiredService<WriteCoordinator>().WriteAsync(async (db, token) =>
            {
                var record = (await Migrations(db, token)).FirstOrDefault(r => Id(r) == body.Id && r.AdminConfirmedUtc is null);
                if (record is null) return false;
                record.AdminConfirmedUtc = services.GetRequiredService<TimeProvider>().GetUtcNow().UtcDateTime;
                record.Reason = $"{record.Reason};confirmed by {Actors.Name(http)}";
                return true;
            }, ct);
            return confirmed ? Json(await StatusAsync(services, ct)) : Detail("There is no completed migration with this identifier.", 409);
        });

        api.MapPost("/storage/migration/delete-backup", async (HttpContext http, IServiceProvider services, DatabaseOptions options, CancellationToken ct) =>
        {
            if (Guard(http) is { } refused) return refused;
            var (body, error) = await Read(http, ct);
            if (error is not null) return error;
            if (!body!.Confirm) return Detail("Confirm that the pre-migration backup may be deleted.", 422);
            var refusal = await services.GetRequiredService<WriteCoordinator>().WriteAsync(async (db, token) =>
            {
                var record = (await Migrations(db, token)).FirstOrDefault(r => Id(r) == body.Id && r.AdminConfirmedUtc is not null);
                if (record is null) return "Only the backup of a confirmed migration can be deleted.";
                var file = Path.Combine(options.BackupDirectory, record.FileName);
                if (!File.Exists(file) || new FileInfo(file).LinkTarget is not null) return "The migration backup is not present.";
                File.Delete(file);                                       // file first, as for application backups
                record.DeletedUtc = services.GetRequiredService<TimeProvider>().GetUtcNow().UtcDateTime;
                record.Reason = $"{record.Reason};deleted by {Actors.Name(http)}";
                return null;
            }, ct);
            return refusal is null ? Json(await StatusAsync(services, ct)) : Detail(refusal, 409);
        });
    }

    private sealed record Confirmation(string Id, bool Confirm);

    private static string Id(BackupRecord record) => record.Sha256[..32];

    private static async Task<List<BackupRecord>> Migrations(AuthLensDb db, CancellationToken ct) =>
        (await db.Backups.Where(b => b.Kind == BackupKind.Migration && b.DeletedUtc == null).ToListAsync(ct)).Where(b => b.Sha256.Length == 64).OrderBy(b => b.CreatedUtc).ToList();

    private static string Iso(DateTime value) => DateTime.SpecifyKind(value, DateTimeKind.Utc).ToString("yyyy-MM-dd'T'HH:mm:ss'+00:00'");

    /// <summary>storage_migration.status plus review_continuity: database health, size, schema version, active revisions, and the migration backup that
    /// waits for confirmation (or the confirmed one that is still kept).</summary>
    public static async Task<JsonObject> StatusAsync(IServiceProvider services, CancellationToken ct)
    {
        var options = services.GetRequiredService<DatabaseOptions>();
        var maintenance = services.GetRequiredService<DatabaseMaintenance>();
        await using var db = await services.GetRequiredService<IDbContextFactory<AuthLensDb>>().CreateDbContextAsync(ct);
        var problems = maintenance.Ready ? (await maintenance.VerifyAsync(ct)).Problems : [maintenance.NotReadyReason ?? "The database is not ready."];
        var state = problems.Any(p => p.Contains("newer", StringComparison.Ordinal)) ? "newer" : problems.Count == 0 ? "ready" : "unavailable";
        long size = 0;
        foreach (var suffix in new[] { "", "-wal", "-shm" })
            if (File.Exists(options.DatabasePath + suffix)) size += new FileInfo(options.DatabasePath + suffix).Length;
        var revisions = new JsonArray();
        foreach (var d in await db.Datasets.AsNoTracking().Where(d => d.Status == DatasetStatus.Active).OrderBy(d => d.Source).ToListAsync(ct))
            revisions.Add(new JsonObject { ["source"] = d.Source, ["revision"] = d.Revision, ["rows"] = d.RecordCount, ["entities"] = d.RecordCount, ["activated"] = d.ActivatedUtc is { } a ? Iso(a) : null });
        var records = (await Migrations(db, ct)).Where(r => File.Exists(Path.Combine(options.BackupDirectory, r.FileName))).ToList();
        var waiting = records.LastOrDefault(r => r.AdminConfirmedUtc is null);
        var kept = records.LastOrDefault(r => r.AdminConfirmedUtc is not null);
        string? By(BackupRecord r) => r.Reason?.Split(';').LastOrDefault(p => p.StartsWith("confirmed by ", StringComparison.Ordinal))?[13..];
        var (_, continuity, detail) = await AssignmentLifecycle.LoadAsync(db, ct);
        return new JsonObject
        {
            ["state"] = state, ["schema_version"] = (await db.Database.GetAppliedMigrationsAsync(ct)).Count(), ["size_bytes"] = size, ["problems"] = new JsonArray([.. problems.Take(5).Select(p => (JsonNode?)p)]),
            ["requires_confirmation"] = waiting is not null, ["revisions"] = revisions,
            ["backup"] = waiting is null ? null : new JsonObject
            {
                ["id"] = Id(waiting), ["created"] = Iso(waiting.CreatedUtc), ["sha256"] = waiting.Sha256, ["size_bytes"] = waiting.SizeBytes, ["app_version"] = V1Compatibility.Version, ["reason"] = waiting.Reason,
            },
            ["retained"] = kept is null ? null : new JsonObject
            {
                ["id"] = Id(kept), ["created"] = Iso(kept.CreatedUtc), ["confirmed_at"] = Iso(kept.AdminConfirmedUtc!.Value), ["confirmed_by"] = By(kept), ["size_bytes"] = kept.SizeBytes,
            },
            ["review_continuity"] = new JsonObject { ["state"] = continuity, ["detail"] = detail },
        };
    }

    private static async Task<(Confirmation?, IResult?)> Read(HttpContext http, CancellationToken ct)
    {
        var (body, invalid) = await V1Validation.ReadBody(http, ct);
        if (invalid is not null) return (null, invalid);
        if (body!.Select(p => p.Key).FirstOrDefault(k => k is not ("migration_id" or "confirm")) is { } extra)
            return (null, Results.Json(new { detail = new[] { new { type = "extra_forbidden", loc = new[] { "body", extra }, msg = "Extra inputs are not permitted" } } }, statusCode: 422));
        var id = body!["migration_id"] is { } i && i.GetValueKind() == JsonValueKind.String ? i.GetValue<string>() : "";
        if (!AuthLens.Application.Backups.ApplicationBackups.Identity().IsMatch(id))
            return (null, Results.Json(new { detail = new[] { new { type = "string_pattern_mismatch", loc = new[] { "body", "migration_id" }, msg = "String should match pattern '^[a-f0-9]{32}$'" } } }, statusCode: 422));
        if (body["confirm"] is not { } c || c.GetValueKind() is not (JsonValueKind.True or JsonValueKind.False))
            return (null, Results.Json(new { detail = new[] { new { type = "bool_type", loc = new[] { "body", "confirm" }, msg = "Input should be a valid boolean" } } }, statusCode: 422));
        return (new Confirmation(id, c.GetValue<bool>()), null);
    }

    private static IResult? Guard(HttpContext http) => V1Backups.Guard(http);

    private static IResult Detail(string message, int status) => Results.Json(new { detail = message }, statusCode: status);
    private static IResult Json(JsonNode value) => Results.Content(value.ToJsonString(), "application/json");
}
