using System.Text.Json.Nodes;
using Microsoft.EntityFrameworkCore;
using AuthLens.Application;
using AuthLens.Persistence;

namespace AuthLens.Api;

/// <summary>The v1 settings document (AppConfig JSON) persisted in SQLite with an optimistic-concurrency revision, like v1's revisioned settings file.
/// Starts from v1's defaults (exported from Python v1). Source paths, data_lifecycle and the revision are server-managed: they change only through
/// imports, never through a settings save.</summary>
public sealed class V1Settings(WriteCoordinator writer, IDbContextFactory<AuthLensDb> factory, TimeProvider clock)
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
    public Task<JsonObject> UpdateAsync(int? expectedRevision, Action<JsonObject> mutate, string actor, Func<AuthLensDb, CancellationToken, Task>? alsoInTransaction, CancellationToken cancellation) =>
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
        if (candidate["module_overrides"] is JsonObject overrides && ValidateModuleOverrides(overrides) is { } moduleError) return moduleError;
        if (candidate.ContainsKey("import_checks"))
        {
            if (candidate["import_checks"] is not JsonObject checks || checks.Any(p => p.Key is not ("enabled" or "max_drop_percent" or "min_previous_records")))
                return "import_checks: only enabled, max_drop_percent and min_previous_records are supported.";
            if (checks["enabled"] is not JsonValue enabled || !enabled.TryGetValue<bool>(out _)
                || checks["max_drop_percent"] is not JsonValue drop || !drop.TryGetValue<int>(out var percent) || percent is < 1 or > 95
                || checks["min_previous_records"] is not JsonValue minimum || !minimum.TryGetValue<int>(out var records) || records is < 0 or > 1_000_000)
                return "import_checks: enabled must be boolean, reduction 1-95 percent and minimum 0-1000000 records.";
        }
        foreach (var field in PathFields)
            if (candidate.ContainsKey(field) && (string?)candidate[field] != (string?)current[field])
                return "Source files change through Data Sources (choose or upload a file), not through a settings save.";
        return null;
    }

    /// <summary>v1 AppConfig.module_overrides: at most 100 entries keyed by a stable registry id; ModuleOverride fields only (display_name up to 100
    /// characters, a supported icon, a #rrggbb colour, enabled).</summary>
    private static string? ValidateModuleOverrides(JsonObject overrides)
    {
        if (overrides.Count > 100) return "module_overrides: at most 100 entries.";
        var icons = V1Compatibility.RegistryIcons().ToHashSet(StringComparer.Ordinal);
        foreach (var (id, value) in overrides)
        {
            if (!V1Compatibility.IsRegistryId(id)) return "Module overrides must use a stable registry identifier.";
            if (value is not JsonObject entry) return $"module_overrides.{id}: an object is required.";
            foreach (var (field, item) in entry)
            {
                if (item is null) { if (field is "display_name" or "icon" or "color") continue; return $"module_overrides.{id}.{field}: a value is required."; }
                var kind = item.GetValueKind();
                var ok = field switch
                {
                    "display_name" => kind == System.Text.Json.JsonValueKind.String && ((string)item!).Length <= 100,
                    "icon" => kind == System.Text.Json.JsonValueKind.String && icons.Contains((string)item!),
                    "color" => kind == System.Text.Json.JsonValueKind.String && System.Text.RegularExpressions.Regex.IsMatch((string)item!, "^#[0-9a-fA-F]{6}$"),
                    "enabled" => kind is System.Text.Json.JsonValueKind.True or System.Text.Json.JsonValueKind.False,
                    _ => false,
                };
                if (!ok) return field == "icon" && kind == System.Text.Json.JsonValueKind.String ? "Choose a supported icon." : $"module_overrides.{id}.{field} is not valid.";
            }
        }
        return null;
    }

    private static string Kind(System.Text.Json.JsonValueKind kind) => kind is System.Text.Json.JsonValueKind.True or System.Text.Json.JsonValueKind.False ? "bool" : kind.ToString();
}
