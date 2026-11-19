using System.Text.Json.Nodes;
using Microsoft.EntityFrameworkCore;
using AuthLens.Domain.Directory;
using Microsoft.Extensions.Logging;
using AuthLens.Persistence;

namespace AuthLens.Application;

/// <summary>MIG-003, the private position-change evidence (v1 position-changes.json, format 1) kept as the "position-changes" document. After every committed
/// import it compares the active Employee Directory with the one it observed last and records Department/Job Title and Manager changes, idempotent per
/// (identity, directory generation), at most 5000 of each. Never fails an import: detection is advisory evidence.</summary>
public sealed class PositionChangeStore(WriteCoordinator writer, IDbContextFactory<AuthLensDb> factory, TimeProvider clock,
    Microsoft.Extensions.Logging.ILogger<PositionChangeStore>? logger = null) : IImportCommitted
{
    public const string Document = "position-changes";
    private readonly SemaphoreSlim _lock = new(1, 1);

    public async Task<JsonObject> ReadAsync(CancellationToken ct)
    {
        await using var db = await factory.CreateDbContextAsync(ct);
        var row = await db.SodDocuments.AsNoTracking().FirstOrDefaultAsync(d => d.Name == Document, ct);
        try
        {
            if (row is not null && JsonNode.Parse(row.Json) is JsonObject data && (int?)data["format"] == 1 && data["events"] is JsonArray && data["manager_events"] is JsonArray) return data;
        }
        catch (System.Text.Json.JsonException) { logger?.LogWarning("Position change records could not be read; none are shown until the next directory replacement."); }
        return new JsonObject { ["format"] = 1, ["events"] = new JsonArray(), ["manager_events"] = new JsonArray(), ["notice"] = null, ["observed"] = null };
    }

    private static async Task<EmployeeDirectory?> DirectoryAsync(AuthLensDb db, long? id, CancellationToken ct)
    {
        if (id is null) return null;
        var dataset = await db.Datasets.AsNoTracking().FirstOrDefaultAsync(d => d.Id == id, ct);
        if (dataset is null) return null;
        return new EmployeeDirectory(await SnapshotService.RecordsAsync(db, id, ct), dataset.FileName ?? "", dataset.ContentHash ?? "",
            (dataset.ActivatedUtc ?? dataset.CreatedUtc).ToString("yyyy-MM-dd'T'HH:mm:ss.ffffff'+00:00'", System.Globalization.CultureInfo.InvariantCulture));
    }

    public async Task CommittedAsync(CancellationToken ct)
    {
        await _lock.WaitAsync(ct);
        try
        {
            await using var db = await factory.CreateDbContextAsync(ct);
            var active = await db.Datasets.AsNoTracking().Where(d => d.Source == Sources.Employees && d.Status == DatasetStatus.Active).Select(d => (long?)d.Id).FirstOrDefaultAsync(ct);
            var data = await ReadAsync(ct);
            var observed = (long?)data["observed"];
            if (active is null || active == observed) return;
            // The first observed directory has nothing to compare with (v1: no previous directory).
            if (observed is not null)
            {
                var previous = await DirectoryAsync(db, observed, ct);
                var current = await DirectoryAsync(db, active, ct);
                var stamp = clock.GetUtcNow().UtcDateTime.ToString("yyyy-MM-dd'T'HH:mm:ss.ffffff'+00:00'", System.Globalization.CultureInfo.InvariantCulture);
                var (events, notices) = PositionChanges.Detect(previous, current, stamp);
                var managers = PositionChanges.DetectManagers(previous, current, stamp);
                if (previous is not null && current is not null && previous.Digest != current.Digest)
                {
                    data["events"] = Merge(data["events"]!.AsArray(), events);
                    data["manager_events"] = Merge(data["manager_events"]!.AsArray(), managers);
                    data["notice"] = notices.Count > 0 ? string.Join(' ', notices) : null;
                }
            }
            data["observed"] = active;
            var json = data.ToJsonString();
            await writer.WriteAsync(async (w, token) =>
            {
                var row = await w.SodDocuments.FirstOrDefaultAsync(d => d.Name == Document, token);
                if (row is null) w.SodDocuments.Add(row = new SodDocument { Name = Document, Json = "{}" });
                (row.Json, row.Revision, row.UpdatedUtc, row.UpdatedBy) = (json, row.Revision + 1, clock.GetUtcNow().UtcDateTime, "directory-import");
            }, ct);
        }
        catch (Exception error) when (error is not OperationCanceledException)
        { logger?.LogWarning("Position changes could not be recorded ({Type}); the directory import is unaffected.", error.GetType().Name); }
        finally { _lock.Release(); }
    }

    private static JsonArray Merge(JsonArray stored, List<JsonObject> found)
    {
        var known = stored.Select(e => (string?)e!["id"]).ToHashSet();
        return new JsonArray([.. stored.Select(e => e!.DeepClone()).Concat(found.Where(e => !known.Contains((string?)e["id"])))
            .OrderBy(e => (string)e!["detected_at"]!, StringComparer.Ordinal).TakeLast(PositionChanges.MaxEvents)]);
    }
}
