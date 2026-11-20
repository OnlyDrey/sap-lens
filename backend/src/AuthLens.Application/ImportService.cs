using System.Text.Json;
using System.Text.Json.Nodes;
using Microsoft.EntityFrameworkCore;
using AuthLens.Domain.Catalogue;
using AuthLens.Domain.Imports;
using AuthLens.Domain.Roles;
using AuthLens.Domain.Sod;
using AuthLens.Domain.Users;
using AuthLens.Persistence;

namespace AuthLens.Application;

/// <summary>An import request. Profile carries the v1 import profile (column mapping, delimiter, encoding); null means the documented defaults.</summary>
public sealed record ImportPayload(string Source, string UploadPath, string FileName, AuthLens.Domain.Csv.CsvProfile? Profile = null, ImportCheckSettings? Checks = null);

public sealed class ImportConflictException(string message) : Exception(message);

public sealed record ImportResult(long DatasetId, string Status, string ContentHash, int Records, bool Suspicious, IReadOnlyList<string> Anomalies, DiffCounts Diff, int Invalidated);

public sealed record JobOutcome(string? ResultJson, Func<AuthLensDb, CancellationToken, Task>? Atomic);

public sealed class JobContext(Job job, string owner, JobQueue queue, CancellationToken cancellation)
{
    public Job Job => job;
    public string Owner => owner;
    public CancellationToken Cancellation => cancellation;

    /// <summary>Progress and lease extension. A lost lease or a cancel request stops the work here.</summary>
    public async Task ReportAsync(double progress, string text)
    {
        var beat = await queue.HeartbeatAsync(job.Id, owner, progress, text, cancellation);
        if (!beat.LeaseHeld) throw new LeaseLostException();
        if (beat.CancelRequested) throw new JobCancelRequestedException();
        cancellation.ThrowIfCancellationRequested();
    }
}

public sealed class JobCancelRequestedException() : OperationCanceledException("Cancelled by request.");

public interface IJobHandler
{
    string Kind { get; }
    Task<JobOutcome> RunAsync(JobContext context);
    void Finished(Job job) { }
}

/// <summary>Import pipeline: stream the CSV into a Staged dataset in bounded batches (each its own short write transaction, so reviews and other writers
/// interleave), validate it by building the domain model, evaluate the change against the active revision, then either hold it for explicit confirmation
/// (suspicious change) or activate it in the same transaction that completes the job. Activation retires the previous revision, keeps it as evidence, and
/// records review invalidations for every assignment that disappeared.</summary>
public sealed class ImportService(WriteCoordinator writer, IDbContextFactory<AuthLensDb> factory, SnapshotService snapshots, TimeProvider clock,
    IEnumerable<IImportCommitted>? committed = null, Microsoft.Extensions.Logging.ILogger<ImportService>? logger = null) : IJobHandler
{
    public const string JobKind = "import";
    public const int BatchSize = 5000;
    public string Kind => JobKind;

    public void Finished(Job job)
    {
        var payload = JsonSerializer.Deserialize<ImportPayload>(job.PayloadJson, Sources.Json);
        if (payload is not null && File.Exists(payload.UploadPath)) File.Delete(payload.UploadPath);
        PruneManagedCopies();
    }

    private void PruneManagedCopies()
    {
        try
        {
            using var db = factory.CreateDbContext();
            ManagedSourceFiles.Prune(db.Database.GetDbConnection().DataSource);
        }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException or Microsoft.Data.Sqlite.SqliteException)
        {
            if (logger is not null) Microsoft.Extensions.Logging.LoggerExtensions.LogWarning(logger, "Managed source cleanup deferred ({ErrorType}).", error.GetType().Name);
        }
    }

    public async Task<JobOutcome> RunAsync(JobContext context)
    {
        var ct = context.Cancellation;
        var payload = JsonSerializer.Deserialize<ImportPayload>(context.Job.PayloadJson, Sources.Json) ?? throw new DomainValidationException("Invalid import payload.");
        if (!Sources.IsKnown(payload.Source)) throw new DomainValidationException("Unknown import source.");
        var (records, report) = Sources.Read(payload.Source, payload.UploadPath, ct, payload.Profile);
        // A file without records (empty, header only, blank lines) never replaces or removes an active snapshot, not even with a confirmed
        // anomaly: removing a dataset is the explicit Clear source data action (v1 csv_lifecycle). Checked before anything is staged.
        using var enumerator = records.GetEnumerator();
        if (!enumerator.MoveNext())
            throw new DomainValidationException("The CSV contains no usable records. Previous data is retained; use Clear source data to remove it intentionally.");

        var dataset = await writer.WriteAsync(async (db, c) =>
        {
            var revision = (await db.Datasets.Where(d => d.Source == payload.Source).MaxAsync(d => (int?)d.Revision, c) ?? 0) + 1;
            var created = new Dataset { Source = payload.Source, Revision = revision, Status = DatasetStatus.Staged, FileName = payload.FileName, JobId = context.Job.Id, CreatedUtc = clock.GetUtcNow().UtcDateTime };
            db.Datasets.Add(created);
            return created;
        }, ct);

        using var hasher = new ContentHasher();
        var staged = new List<IReadOnlyDictionary<string, string>>();
        var batch = new List<DatasetRecord>(BatchSize);
        async Task FlushAsync()
        {
            if (batch.Count == 0) return;
            var rows = batch.ToList();
            batch.Clear();
            await writer.WriteAsync((db, _) => { db.DatasetRecords.AddRange(rows); return Task.CompletedTask; }, ct);
            await context.ReportAsync(0.05 + 0.75 * Math.Min(1, staged.Count / (double)Math.Max(1, report.ParsedRows + 1)), $"Staged {staged.Count} records");
        }
        do
        {
            var record = enumerator.Current;
            var json = Sources.Serialize(record);
            hasher.Add(json);
            batch.Add(new DatasetRecord { DatasetId = dataset.Id, Ordinal = staged.Count, Payload = json });
            staged.Add(record);
            if (batch.Count == BatchSize) await FlushAsync();
        }
        while (enumerator.MoveNext());
        await FlushAsync();
        var contentHash = hasher.Finish();
        await context.ReportAsync(0.85, "Validating");

        // Validation by construction: the staged records must build the domain model the API will serve.
        var current = await snapshots.GetAsync(ct);
        HashSet<string>? newKeys = null;
        switch (payload.Source)
        {
            case Sources.Roles: CatalogueBuilder.Build(staged); break;
            case Sources.Users: newKeys = Sources.ReviewKeys(UserDirectoryBuilder.Build(staged, current.Catalogue)); break;
            case Sources.Sod: SodSource.Build(staged, report.Warnings.Where(w => !w.StartsWith("Optional field ", StringComparison.Ordinal))); break;
            case Sources.Employees: _ = new Domain.Directory.EmployeeDirectory(staged, payload.FileName, contentHash, ""); break;
        }

        await using var read = await factory.CreateDbContextAsync(ct);
        var active = await read.Datasets.AsNoTracking().FirstOrDefaultAsync(d => d.Source == payload.Source && d.Status == DatasetStatus.Active, ct);
        var previous = await SnapshotService.RecordsAsync(read, active?.Id, ct);
        // Freeze the operator's policy with the durable job; never share mutable policy across hosts or queued imports.
        var evaluation = ImportChecks.Evaluate(payload.Source, previous, staged, payload.Checks ?? new ImportCheckSettings());
        var diff = ImportChecks.Diff(payload.Source, previous, staged);
        var held = evaluation.Suspicious;
        var removed = newKeys is null ? [] : Sources.ReviewKeys(current.Users).Where(k => !newKeys.Contains(k)).Order(StringComparer.Ordinal).ToList();
        var evaluationJson = JsonSerializer.Serialize(new { evaluated_against = active?.Id, previous_content_hash = active?.ContentHash, evaluation.Suspicious, anomalies = evaluation.Anomalies, old = evaluation.Old, @new = evaluation.New, diff }, Sources.Json);
        var reportJson = JsonSerializer.Serialize(report, Sources.Json);
        var result = new ImportResult(dataset.Id, held ? DatasetStatus.Held : DatasetStatus.Active, contentHash, staged.Count, held, evaluation.Anomalies.Select(a => a.Message).ToList(), diff, held ? 0 : removed.Count);

        return new JobOutcome(JsonSerializer.Serialize(result, Sources.Json), async (db, c) =>
        {
            var target = await db.Datasets.FirstAsync(d => d.Id == dataset.Id, c);
            (target.ContentHash, target.RecordCount, target.ReportJson, target.EvaluationJson) = (contentHash, staged.Count, reportJson, evaluationJson);
            var managed = ManagedSourceFiles.Capture(Path.GetDirectoryName(db.Database.GetDbConnection().DataSource)!, payload.Source, payload.UploadPath, payload.FileName);
            var storedReport = JsonNode.Parse(reportJson)!.AsObject(); storedReport["managed_source"] = managed;
            target.ReportJson = storedReport.ToJsonString();
            if (held) { target.Status = DatasetStatus.Held; return; }
            await ActivateAsync(db, target, active?.Id, removed, c);
        });
    }

    /// <summary>Activation inside the caller's write transaction. Refuses if another revision was activated after this one was evaluated.</summary>
    private async Task ActivateAsync(AuthLensDb db, Dataset target, long? evaluatedAgainst, IReadOnlyList<string> removedKeys, CancellationToken ct)
    {
        var now = clock.GetUtcNow().UtcDateTime;
        var active = await db.Datasets.FirstOrDefaultAsync(d => d.Source == target.Source && d.Status == DatasetStatus.Active, ct);
        if (active?.Id != evaluatedAgainst) throw new ImportConflictException("Another revision was activated after this import was evaluated; import the file again.");
        if (active is not null) { active.Status = DatasetStatus.Retired; await db.SaveChangesAsync(ct); }
        (target.Status, target.ActivatedUtc) = (DatasetStatus.Active, now);
        await db.SaveChangesAsync(ct);
        foreach (var key in removedKeys) db.ReviewInvalidations.Add(new ReviewInvalidation { AssignmentKey = key, DatasetId = target.Id, CreatedUtc = now });
    }

    /// <summary>Explicit confirmation of a held (suspicious) import by a named person. The removed assignment keys are computed now, against the current state.</summary>
    public async Task<Dataset> ConfirmAsync(long datasetId, string confirmedBy, CancellationToken cancellation = default)
    {
        await using var read = await factory.CreateDbContextAsync(cancellation);
        var held = await read.Datasets.AsNoTracking().FirstOrDefaultAsync(d => d.Id == datasetId, cancellation) ?? throw new Domain.Analysis.NotFoundException("Dataset not found.");
        if (held.Status != DatasetStatus.Held) throw new ImportConflictException("Only a held import can be confirmed.");
        if (held.RecordCount == 0) throw new ImportConflictException("An empty source cannot be confirmed. Previous data is retained.");
        var evaluatedAgainst = JsonDocument.Parse(held.EvaluationJson ?? "{}").RootElement.TryGetProperty("evaluated_against", out var e) && e.ValueKind == JsonValueKind.Number ? e.GetInt64() : (long?)null;
        IReadOnlyList<string> removed = [];
        if (held.Source == Sources.Users)
        {
            var current = await snapshots.GetAsync(cancellation);
            var keys = Sources.ReviewKeys(UserDirectoryBuilder.Build(await SnapshotService.RecordsAsync(read, held.Id, cancellation), current.Catalogue));
            removed = Sources.ReviewKeys(current.Users).Where(k => !keys.Contains(k)).Order(StringComparer.Ordinal).ToList();
        }
        var confirmed = await writer.WriteAsync(async (db, ct) =>
        {
            var target = await db.Datasets.FirstAsync(d => d.Id == datasetId && d.Status == DatasetStatus.Held, ct);
            (target.ConfirmedBy, target.ConfirmedUtc) = (confirmedBy, clock.GetUtcNow().UtcDateTime);
            await ActivateAsync(db, target, evaluatedAgainst, removed, ct);
            return target;
        }, cancellation);
        await NotifyCommittedAsync(committed ?? [], logger);
        PruneManagedCopies();
        return confirmed;
    }

    /// <summary>After a committed activation: observers (the assignment lifecycle memory) run best effort; a failure never fails the import, and the next
    /// review read observes again.</summary>
    public static async Task NotifyCommittedAsync(IEnumerable<IImportCommitted> observers, Microsoft.Extensions.Logging.ILogger? logger)
    {
        foreach (var observer in observers)
            try { await observer.CommittedAsync(CancellationToken.None); }
            catch (Exception error) when (error is not OperationCanceledException)
            {
                if (logger is not null) Microsoft.Extensions.Logging.LoggerExtensions.LogWarning(logger, error, "Assignment lifecycle observation failed and will be retried at the next read.");
            }
    }
}
