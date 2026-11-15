using Microsoft.EntityFrameworkCore;
using SapLens.Domain.Catalogue;
using SapLens.Domain.Sod;
using SapLens.Domain.Users;
using SapLens.Persistence;

namespace SapLens.Application;

public sealed record ActiveIds(long? Roles, long? Users, long? Sod);

public sealed class Snapshot
{
    public required ActiveIds Ids { get; init; }
    public required RoleCatalogue Catalogue { get; init; }
    public required UserDirectory Users { get; init; }
    public SodDataset? Sod { get; init; }
    public required HashSet<string> AssignmentKeys { get; init; }
}

/// <summary>The in-memory analysis snapshot (like the v1 cache), rebuilt from the ACTIVE datasets in SQLite when another process or job changed them.
/// Readers share one immutable snapshot; a rebuild never blocks readers of the previous one.</summary>
public sealed class SnapshotService(IDbContextFactory<SapLensDb> factory)
{
    private readonly SemaphoreSlim _rebuild = new(1, 1);
    private Snapshot? _current;

    public static async Task<ActiveIds> ActiveAsync(SapLensDb db, CancellationToken ct)
    {
        var active = await db.Datasets.AsNoTracking().Where(d => d.Status == DatasetStatus.Active).Select(d => new { d.Source, d.Id }).ToListAsync(ct);
        long? Of(string source) => active.FirstOrDefault(a => a.Source == source)?.Id;
        return new ActiveIds(Of(Sources.Roles), Of(Sources.Users), Of(Sources.Sod));
    }

    public static async Task<List<IReadOnlyDictionary<string, string>>> RecordsAsync(SapLensDb db, long? datasetId, CancellationToken ct)
    {
        if (datasetId is null) return [];
        var payloads = await db.DatasetRecords.AsNoTracking().Where(r => r.DatasetId == datasetId).OrderBy(r => r.Ordinal).Select(r => r.Payload).ToListAsync(ct);
        return payloads.Select(p => (IReadOnlyDictionary<string, string>)Sources.Deserialize(p)).ToList();
    }

    public async Task<Snapshot> GetAsync(CancellationToken cancellation = default)
    {
        await using var db = await factory.CreateDbContextAsync(cancellation);
        var ids = await ActiveAsync(db, cancellation);
        if (_current is { } cached && cached.Ids == ids) return cached;
        await _rebuild.WaitAsync(cancellation);
        try
        {
            if (_current is { } again && again.Ids == ids) return again;
            var catalogue = CatalogueBuilder.Build(await RecordsAsync(db, ids.Roles, cancellation));
            var users = UserDirectoryBuilder.Build(await RecordsAsync(db, ids.Users, cancellation), catalogue);
            var sodRecords = await RecordsAsync(db, ids.Sod, cancellation);
            var sod = ids.Sod is null ? null : SodSource.Build(sodRecords);
            return _current = new Snapshot { Ids = ids, Catalogue = catalogue, Users = users, Sod = sod, AssignmentKeys = Sources.AssignmentKeys(users) };
        }
        finally
        {
            _rebuild.Release();
        }
    }
}
