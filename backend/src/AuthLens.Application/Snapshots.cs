using Microsoft.EntityFrameworkCore;
using System.Globalization;
using AuthLens.Domain.Catalogue;
using AuthLens.Domain.Directory;
using AuthLens.Domain.Sod;
using AuthLens.Domain.Users;
using AuthLens.Persistence;

namespace AuthLens.Application;

public sealed record ActiveIds(long? Roles, long? Users, long? Sod, long? Employees = null);

public sealed class Snapshot
{
    public required ActiveIds Ids { get; init; }
    public required RoleCatalogue Catalogue { get; init; }
    public required UserDirectory Users { get; init; }
    public SodDataset? Sod { get; init; }
    /// <summary>The active Employee Directory dataset, when one was imported (independent of the feature switch, which callers apply).</summary>
    public EmployeeDirectory? Directory { get; init; }
    public required HashSet<string> AssignmentKeys { get; init; }
    /// <summary>The module display-name overrides the catalogue was built with (canonical JSON), so a settings change rebuilds it as v1 does.</summary>
    public string ModuleNames { get; init; } = "{}";
}

/// <summary>The in-memory analysis snapshot (like the v1 cache), rebuilt from the ACTIVE datasets in SQLite when another process or job changed them.
/// Readers share one immutable snapshot; a rebuild never blocks readers of the previous one.</summary>
public sealed class SnapshotService(IDbContextFactory<AuthLensDb> factory)
{
    private readonly SemaphoreSlim _rebuild = new(1, 1);
    private Snapshot? _current;

    public static async Task<ActiveIds> ActiveAsync(AuthLensDb db, CancellationToken ct)
    {
        var active = await db.Datasets.AsNoTracking().Where(d => d.Status == DatasetStatus.Active).Select(d => new { d.Source, d.Id }).ToListAsync(ct);
        long? Of(string source) => active.FirstOrDefault(a => a.Source == source)?.Id;
        return new ActiveIds(Of(Sources.Roles), Of(Sources.Users), Of(Sources.Sod), Of(Sources.Employees));
    }

    public static async Task<List<IReadOnlyDictionary<string, string>>> RecordsAsync(AuthLensDb db, long? datasetId, CancellationToken ct)
    {
        if (datasetId is null) return [];
        var payloads = await db.DatasetRecords.AsNoTracking().Where(r => r.DatasetId == datasetId).OrderBy(r => r.Ordinal).Select(r => r.Payload).ToListAsync(ct);
        return payloads.Select(p => (IReadOnlyDictionary<string, string>)Sources.Deserialize(p)).ToList();
    }

    /// <summary>Non-empty <c>display_name</c> values of the saved <c>module_overrides</c> (v1 module_definition), keyed by registry id.</summary>
    private static async Task<(string Key, Dictionary<string, string> Map)> ModuleNamesAsync(AuthLensDb db, CancellationToken ct)
    {
        var json = await db.Settings.AsNoTracking().Select(s => s.Json).FirstOrDefaultAsync(ct);
        var map = new SortedDictionary<string, string>(StringComparer.Ordinal);
        if (json is not null && System.Text.Json.Nodes.JsonNode.Parse(json)?["module_overrides"] is System.Text.Json.Nodes.JsonObject overrides)
            foreach (var (id, value) in overrides)
                if (value?["display_name"] is System.Text.Json.Nodes.JsonValue name && name.TryGetValue<string>(out var text) && text.Length > 0) map[id] = text;
        return (System.Text.Json.JsonSerializer.Serialize(map), new Dictionary<string, string>(map, StringComparer.Ordinal));
    }

    public async Task<Snapshot> GetAsync(CancellationToken cancellation = default)
    {
        await using var db = await factory.CreateDbContextAsync(cancellation);
        var ids = await ActiveAsync(db, cancellation);
        var names = await ModuleNamesAsync(db, cancellation);
        if (_current is { } cached && cached.Ids == ids && cached.ModuleNames == names.Key) return cached;
        await _rebuild.WaitAsync(cancellation);
        try
        {
            if (_current is { } again && again.Ids == ids && again.ModuleNames == names.Key) return again;
            EmployeeDirectory? directory = null;
            if (ids.Employees is { } employees)
            {
                var dataset = await db.Datasets.AsNoTracking().FirstAsync(d => d.Id == employees, cancellation);
                directory = new EmployeeDirectory(await RecordsAsync(db, employees, cancellation), dataset.FileName ?? "", dataset.ContentHash ?? "",
                    (dataset.ActivatedUtc ?? dataset.CreatedUtc).ToString("yyyy-MM-dd'T'HH:mm:ss.ffffff'+00:00'", CultureInfo.InvariantCulture));
            }
            // A directory-only change keeps the SAP analysis objects (and the SAP data revision), as v1 does.
            if (_current is { } previous && previous.Ids with { Employees = ids.Employees } == ids && previous.ModuleNames == names.Key)
                return _current = new Snapshot { Ids = ids, Catalogue = previous.Catalogue, Users = previous.Users, Sod = previous.Sod, AssignmentKeys = previous.AssignmentKeys, Directory = directory, ModuleNames = names.Key };
            var catalogue = CatalogueBuilder.Build(await RecordsAsync(db, ids.Roles, cancellation), id => names.Map.GetValueOrDefault(id) ?? ModuleRegistry.Name(id));
            var users = UserDirectoryBuilder.Build(await RecordsAsync(db, ids.Users, cancellation), catalogue);
            var sodRecords = await RecordsAsync(db, ids.Sod, cancellation);
            var sod = ids.Sod is null ? null : SodSource.Build(sodRecords);
            return _current = new Snapshot { Ids = ids, Catalogue = catalogue, Users = users, Sod = sod, AssignmentKeys = Sources.AssignmentKeys(users), Directory = directory, ModuleNames = names.Key };
        }
        finally
        {
            _rebuild.Release();
        }
    }
}
