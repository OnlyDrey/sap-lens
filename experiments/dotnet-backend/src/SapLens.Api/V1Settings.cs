using System.Text.Json.Nodes;
using Microsoft.EntityFrameworkCore;
using SapLens.Application;
using SapLens.Persistence;

namespace SapLens.Api;

/// <summary>The v1 settings document (AppConfig JSON) persisted in SQLite with an optimistic-concurrency revision, like v1's revisioned settings file.
/// Starts from v1's defaults (exported from Python v1). Source paths, data_lifecycle and the revision are server-managed: they change only through
/// imports, never through a settings save.</summary>
public sealed class V1Settings(WriteCoordinator writer, IDbContextFactory<SapLensDb> factory, TimeProvider clock)
{
    public static readonly string[] ServerManaged = ["revision", "schema_version", "data_lifecycle", "data_csv_path", "user_csv_path", "employee_csv_path", "sod_csv_path", "employee_snapshot_id"];
    public static readonly string[] PathFields = ["data_csv_path", "user_csv_path", "employee_csv_path", "sod_csv_path"];

    public async Task<JsonObject> GetAsync(CancellationToken cancellation)
    {
        await using var db = await factory.CreateDbContextAsync(cancellation);
        var row = await db.Settings.AsNoTracking().FirstOrDefaultAsync(cancellation);
        return Materialize(row);
    }

    private static JsonObject Materialize(SettingsDocument? row)
    {
        var settings = row is null ? V1Compatibility.DefaultSettingsDocument() : JsonNode.Parse(row.Json)!.AsObject();
        settings["revision"] = row?.Revision ?? 0;
        return settings;
    }

    /// <summary>Applies <paramref name="mutate"/> to the current document inside one write transaction. With an expected revision the save is refused when
    /// another save happened in between (409); the stored revision then increases by one.</summary>
    public Task<JsonObject> UpdateAsync(int? expectedRevision, Action<JsonObject> mutate, string actor, CancellationToken cancellation) =>
        UpdateAsync(expectedRevision, mutate, actor, null, cancellation);

    /// <summary>As above, with <paramref name="alsoInTransaction"/> applied in the same SQLite write transaction (all or nothing).</summary>
    public Task<JsonObject> UpdateAsync(int? expectedRevision, Action<JsonObject> mutate, string actor, Func<SapLensDb, CancellationToken, Task>? alsoInTransaction, CancellationToken cancellation) =>
        writer.WriteAsync(async (db, ct) =>
        {
            var row = await db.Settings.FirstOrDefaultAsync(ct);
            var current = Materialize(row);
            if (expectedRevision is { } expected && (int)current["revision"]! != expected)
                throw new ImportConflictException("Settings changed. Reload this page before saving again.");
            mutate(current);
            if (alsoInTransaction is not null) await alsoInTransaction(db, ct);
            var revision = (row?.Revision ?? 0) + 1;
            current["revision"] = revision;
            if (row is null) db.Settings.Add(row = new SettingsDocument { Json = "{}" });
            (row.Revision, row.Json, row.UpdatedUtc, row.UpdatedBy) = (revision, current.ToJsonString(), clock.GetUtcNow().UtcDateTime, actor);
            return current;
        }, cancellation);

    /// <summary>Validation of a settings save from the UI (v1 AppConfig is a strict model): no unknown fields, the same JSON kinds as the v1 defaults,
    /// and no attempt to change server-managed fields such as source paths. Returns the error or null.</summary>
    public static string? Validate(JsonObject candidate, JsonObject current)
    {
        var defaults = V1Compatibility.DefaultSettingsDocument();
        foreach (var (key, value) in candidate)
        {
            if (!defaults.ContainsKey(key)) return $"Unknown settings field '{key}'.";
            var expected = defaults[key]?.GetValueKind();
            var actual = value?.GetValueKind();
            if (expected is not null && actual is not null && actual != System.Text.Json.JsonValueKind.Null && Kind(expected.Value) != Kind(actual.Value))
                return $"Settings field '{key}' has the wrong type.";
        }
        // The RefreshSchedule model (a readable daily time or cron expression, a valid zone name pattern).
        if (candidate["refresh_schedule"] is JsonObject schedule && V1RefreshSchedule.Parse(schedule.DeepClone().AsObject()).Error is { } scheduleError)
            return $"refresh_schedule: {scheduleError}";
        foreach (var field in PathFields)
            if (candidate.ContainsKey(field) && (string?)candidate[field] != (string?)current[field])
                return "Source files change through Data Sources (choose or upload a file), not through a settings save.";
        return null;
    }

    private static string Kind(System.Text.Json.JsonValueKind kind) => kind is System.Text.Json.JsonValueKind.True or System.Text.Json.JsonValueKind.False ? "bool" : kind.ToString();
}
