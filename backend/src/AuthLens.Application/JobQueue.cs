using Microsoft.EntityFrameworkCore;
using AuthLens.Persistence;

namespace AuthLens.Application;

public sealed class LeaseLostException() : Exception("The job lease was lost to another worker; this worker stops without writing.");

public sealed record Heartbeat(bool LeaseHeld, bool CancelRequested);

/// <summary>Persistent SQLite job queue. Claiming, heartbeats and completion are conditional updates inside BEGIN IMMEDIATE transactions, so they are
/// atomic across processes, not only across threads. Every state change after claiming is fenced on (Id, LeaseOwner, Running): a worker whose lease expired
/// and was re-claimed elsewhere cannot complete, fail or extend the job.</summary>
public sealed class JobQueue(WriteCoordinator writer, IDbContextFactory<AuthLensDb> factory, TimeProvider clock)
{
    public static readonly TimeSpan Lease = TimeSpan.FromSeconds(30);
    public event Action? Enqueued;

    public async Task<Job> EnqueueAsync(string kind, string payloadJson, string? idempotencyKey, CancellationToken cancellation = default)
    {
        var job = await writer.WriteAsync(async (db, ct) =>
        {
            if (idempotencyKey is not null && await db.Jobs.FirstOrDefaultAsync(j => j.IdempotencyKey == idempotencyKey, ct) is { } existing) return existing;
            var now = clock.GetUtcNow().UtcDateTime;
            var created = new Job { Kind = kind, Status = JobStatus.Queued, PayloadJson = payloadJson, IdempotencyKey = idempotencyKey, CreatedUtc = now, NotBeforeUtc = now };
            db.Jobs.Add(created);
            return created;
        }, cancellation);
        Enqueued?.Invoke();
        return job;
    }

    public async Task<Job?> GetAsync(long id, CancellationToken cancellation = default)
    {
        await using var db = await factory.CreateDbContextAsync(cancellation);
        return await db.Jobs.AsNoTracking().FirstOrDefaultAsync(j => j.Id == id, cancellation);
    }

    public Task<Job?> ClaimAsync(string owner, CancellationToken cancellation = default) => writer.WriteAsync<Job?>(async (db, ct) =>
    {
        var now = clock.GetUtcNow().UtcDateTime;
        var candidate = await db.Jobs.Where(j => j.Status == JobStatus.Queued && j.NotBeforeUtc <= now).OrderBy(j => j.Id).Select(j => j.Id).FirstOrDefaultAsync(ct);
        if (candidate == 0) return null;
        var claimed = await db.Jobs.Where(j => j.Id == candidate && j.Status == JobStatus.Queued).ExecuteUpdateAsync(s => s
            .SetProperty(j => j.Status, JobStatus.Running).SetProperty(j => j.LeaseOwner, owner).SetProperty(j => j.LeaseExpiresUtc, now + Lease)
            .SetProperty(j => j.Attempts, j => j.Attempts + 1).SetProperty(j => j.StartedUtc, now).SetProperty(j => j.Error, (string?)null), ct);
        return claimed == 1 ? await db.Jobs.AsNoTracking().FirstAsync(j => j.Id == candidate, ct) : null;
    }, cancellation);

    public Task<Heartbeat> HeartbeatAsync(long id, string owner, double? progress, string? text, CancellationToken cancellation = default) => writer.WriteAsync(async (db, ct) =>
    {
        var now = clock.GetUtcNow().UtcDateTime;
        var query = db.Jobs.Where(j => j.Id == id && j.LeaseOwner == owner && j.Status == JobStatus.Running);
        var updated = progress is null
            ? await query.ExecuteUpdateAsync(s => s.SetProperty(j => j.LeaseExpiresUtc, now + Lease), ct)
            : await query.ExecuteUpdateAsync(s => s.SetProperty(j => j.LeaseExpiresUtc, now + Lease).SetProperty(j => j.Progress, progress.Value).SetProperty(j => j.ProgressText, text), ct);
        if (updated == 0) return new Heartbeat(false, false);
        return new Heartbeat(true, await db.Jobs.Where(j => j.Id == id).Select(j => j.CancelRequested).FirstAsync(ct));
    }, cancellation);

    /// <summary>Completes the job and runs <paramref name="atomic"/> in the SAME transaction (for example dataset activation). If the lease is no longer
    /// held, nothing is written: the activation and the completion commit together or not at all.</summary>
    public Task CompleteAsync(long id, string owner, string? resultJson, Func<AuthLensDb, CancellationToken, Task>? atomic, CancellationToken cancellation = default) =>
        writer.WriteAsync(async (db, ct) =>
        {
            var now = clock.GetUtcNow().UtcDateTime;
            var fenced = await db.Jobs.Where(j => j.Id == id && j.LeaseOwner == owner && j.Status == JobStatus.Running).ExecuteUpdateAsync(s => s
                .SetProperty(j => j.Status, JobStatus.Completed).SetProperty(j => j.Progress, 1.0).SetProperty(j => j.ResultJson, resultJson)
                .SetProperty(j => j.FinishedUtc, now).SetProperty(j => j.LeaseOwner, (string?)null).SetProperty(j => j.LeaseExpiresUtc, (DateTime?)null), ct);
            if (fenced == 0) throw new LeaseLostException();
            if (atomic is not null) await atomic(db, ct);
        }, cancellation);

    /// <summary>A failed attempt: retried with exponential backoff while attempts remain and the error is transient, otherwise Failed. Staging of the job is
    /// discarded in the same transaction, so a retry starts clean.</summary>
    public Task FailAsync(long id, string owner, string error, bool transient, CancellationToken cancellation = default) => writer.WriteAsync(async (db, ct) =>
    {
        var job = await db.Jobs.FirstOrDefaultAsync(j => j.Id == id && j.LeaseOwner == owner && j.Status == JobStatus.Running, ct) ?? throw new LeaseLostException();
        var now = clock.GetUtcNow().UtcDateTime;
        var retry = transient && job.Attempts < job.MaxAttempts;
        job.Status = retry ? JobStatus.Queued : JobStatus.Failed;
        job.NotBeforeUtc = retry ? now + TimeSpan.FromSeconds(Math.Pow(2, job.Attempts)) : job.NotBeforeUtc;
        job.FinishedUtc = retry ? null : now;
        (job.Error, job.LeaseOwner, job.LeaseExpiresUtc) = (error, null, null);
        await DiscardStagingAsync(db, id, ct);
    }, cancellation);

    public Task CancelledAsync(long id, string owner, CancellationToken cancellation = default) => writer.WriteAsync(async (db, ct) =>
    {
        var job = await db.Jobs.FirstOrDefaultAsync(j => j.Id == id && j.LeaseOwner == owner && j.Status == JobStatus.Running, ct) ?? throw new LeaseLostException();
        (job.Status, job.FinishedUtc, job.LeaseOwner, job.LeaseExpiresUtc, job.Error) = (JobStatus.Cancelled, clock.GetUtcNow().UtcDateTime, null, null, "Cancelled by request.");
        await DiscardStagingAsync(db, id, ct);
    }, cancellation);

    /// <summary>Graceful shutdown: the attempt is handed back (not counted) and its staging discarded; another start resumes it from the beginning.</summary>
    public Task ReleaseAsync(long id, string owner, CancellationToken cancellation = default) => writer.WriteAsync(async (db, ct) =>
    {
        var job = await db.Jobs.FirstOrDefaultAsync(j => j.Id == id && j.LeaseOwner == owner && j.Status == JobStatus.Running, ct);
        if (job is null) return;
        (job.Status, job.LeaseOwner, job.LeaseExpiresUtc, job.Attempts, job.ProgressText) = (JobStatus.Queued, null, null, Math.Max(0, job.Attempts - 1), "Interrupted by shutdown; queued again.");
        await DiscardStagingAsync(db, id, ct);
    }, cancellation);

    /// <summary>Request cancellation. A queued job is cancelled at once; a running job is cancelled by its worker at the next heartbeat.</summary>
    public Task<Job?> RequestCancelAsync(long id, CancellationToken cancellation = default) => writer.WriteAsync<Job?>(async (db, ct) =>
    {
        var job = await db.Jobs.FirstOrDefaultAsync(j => j.Id == id, ct);
        if (job is null) return null;
        if (job.Status == JobStatus.Queued) (job.Status, job.FinishedUtc, job.Error) = (JobStatus.Cancelled, clock.GetUtcNow().UtcDateTime, "Cancelled before it started.");
        else if (job.Status == JobStatus.Running) job.CancelRequested = true;
        return job;
    }, cancellation);

    /// <summary>Crash recovery: Running jobs whose lease expired (their worker died or the process restarted) are queued again with staging discarded.
    /// A job is never re-run while its lease is live, and an attempt that already committed its activation is Completed in the same transaction, so a
    /// restart cannot execute a finished import twice.</summary>
    public Task<int> RecoverExpiredAsync(CancellationToken cancellation = default) => writer.WriteAsync(async (db, ct) =>
    {
        var now = clock.GetUtcNow().UtcDateTime;
        var stale = await db.Jobs.Where(j => j.Status == JobStatus.Running && j.LeaseExpiresUtc < now).ToListAsync(ct);
        foreach (var job in stale)
        {
            var retry = job.Attempts < job.MaxAttempts;
            (job.Status, job.LeaseOwner, job.LeaseExpiresUtc, job.Error) = (retry ? JobStatus.Queued : JobStatus.Failed, null, null, "The worker stopped without finishing (lease expired).");
            if (!retry) job.FinishedUtc = now;
            await DiscardStagingAsync(db, job.Id, ct);
        }
        return stale.Count;
    }, cancellation);

    private static async Task DiscardStagingAsync(AuthLensDb db, long jobId, CancellationToken ct)
    {
        var staged = await db.Datasets.Where(d => d.JobId == jobId && d.Status == DatasetStatus.Staged).Select(d => d.Id).ToListAsync(ct);
        if (staged.Count == 0) return;
        await db.DatasetRecords.Where(r => staged.Contains(r.DatasetId)).ExecuteDeleteAsync(ct);
        await db.Datasets.Where(d => staged.Contains(d.Id)).ExecuteUpdateAsync(s => s.SetProperty(d => d.Status, DatasetStatus.Discarded), ct);
    }
}
