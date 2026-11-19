using Microsoft.Data.Sqlite;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;
using AuthLens.Domain.Csv;
using AuthLens.Domain.Roles;
using AuthLens.Persistence;

namespace AuthLens.Application;

public sealed class WorkerOptions
{
    public bool Enabled { get; init; } = true;
    public TimeSpan PollInterval { get; init; } = TimeSpan.FromSeconds(1);
    public TimeSpan HeartbeatInterval { get; init; } = TimeSpan.FromSeconds(5);
}

/// <summary>One job at a time per process. Recovery of expired leases runs before every claim; a lease heartbeat runs beside the handler; shutdown hands an
/// unfinished job back (Queued) instead of marking it failed.</summary>
public sealed class JobWorker(JobQueue queue, IEnumerable<IJobHandler> handlers, DatabaseMaintenance database, WorkerOptions options, ILogger<JobWorker> logger,
    IEnumerable<IImportCommitted> committed) : BackgroundService
{
    private readonly string _owner = $"{Environment.MachineName}:{Environment.ProcessId}:{Guid.NewGuid():N}";
    private readonly Dictionary<string, IJobHandler> _handlers = handlers.ToDictionary(h => h.Kind, StringComparer.Ordinal);
    private readonly SemaphoreSlim _signal = new(0);
    public string Owner => _owner;

    protected override async Task ExecuteAsync(CancellationToken stopping)
    {
        if (!options.Enabled || !database.Ready) { logger.LogInformation("Job worker not started (enabled={Enabled}, database ready={Ready})", options.Enabled, database.Ready); return; }
        queue.Enqueued += () => { if (_signal.CurrentCount == 0) _signal.Release(); };
        while (!stopping.IsCancellationRequested)
        {
            try
            {
                var recovered = await queue.RecoverExpiredAsync(stopping);
                if (recovered > 0) logger.LogWarning("Recovered {Count} jobs whose worker stopped without finishing", recovered);
                var job = await queue.ClaimAsync(_owner, stopping);
                if (job is null) { await _signal.WaitAsync(options.PollInterval, stopping); continue; }
                await RunAsync(job, stopping);
            }
            catch (OperationCanceledException) when (stopping.IsCancellationRequested) { break; }
            catch (Exception error)
            {
                logger.LogError(error, "Job worker loop error");
                await Task.Delay(options.PollInterval, stopping).ContinueWith(_ => { }, CancellationToken.None);
            }
        }
    }

    private async Task RunAsync(Persistence.Job job, CancellationToken stopping)
    {
        using var scope = logger.BeginScope(new Dictionary<string, object> { ["JobId"] = job.Id, ["JobKind"] = job.Kind, ["Attempt"] = job.Attempts });
        if (!_handlers.TryGetValue(job.Kind, out var handler)) { await queue.FailAsync(job.Id, _owner, "Unknown job kind.", transient: false, CancellationToken.None); return; }
        using var work = CancellationTokenSource.CreateLinkedTokenSource(stopping);
        var heartbeat = HeartbeatAsync(job.Id, work);
        var terminal = true;
        try
        {
            logger.LogInformation("Job started");
            var outcome = await handler.RunAsync(new JobContext(job, _owner, queue, work.Token));
            await queue.CompleteAsync(job.Id, _owner, outcome.ResultJson, outcome.Atomic, CancellationToken.None);
            logger.LogInformation("Job completed");
            if (handler is ImportService) await ImportService.NotifyCommittedAsync(committed, logger);
        }
        catch (LeaseLostException) { terminal = false; logger.LogWarning("Job lease lost; stopped without writing"); }
        catch (OperationCanceledException) when (stopping.IsCancellationRequested)
        {
            terminal = false;
            await queue.ReleaseAsync(job.Id, _owner, CancellationToken.None);
            logger.LogInformation("Job handed back at shutdown");
        }
        catch (Exception error) when (error is JobCancelRequestedException || (error is OperationCanceledException && work.IsCancellationRequested))
        {
            await queue.CancelledAsync(job.Id, _owner, CancellationToken.None);
            logger.LogInformation("Job cancelled");
        }
        catch (Exception error)
        {
            var transient = IsTransient(error);
            await queue.FailAsync(job.Id, _owner, Describe(error), transient, CancellationToken.None);
            var after = await queue.GetAsync(job.Id, CancellationToken.None);
            terminal = after?.Status != JobStatus.Queued;
            logger.LogWarning("Job attempt failed ({Transient}): {Error}", transient ? "transient" : "permanent", Describe(error));
        }
        finally
        {
            await work.CancelAsync();
            await heartbeat;
        }
        if (terminal && await queue.GetAsync(job.Id, CancellationToken.None) is { } final) handler.Finished(final);
    }

    private async Task HeartbeatAsync(long id, CancellationTokenSource work)
    {
        try
        {
            while (!work.IsCancellationRequested)
            {
                await Task.Delay(options.HeartbeatInterval, work.Token);
                var beat = await queue.HeartbeatAsync(id, _owner, null, null, work.Token);
                if (!beat.LeaseHeld || beat.CancelRequested) { await work.CancelAsync(); return; }
            }
        }
        catch (OperationCanceledException) { }
    }

    /// <summary>Only infrastructure contention is retried; bad input fails at once with its message (retrying cannot fix it).</summary>
    public static bool IsTransient(Exception error) => error switch
    {
        DomainValidationException or CsvFormatException or ImportConflictException or FileNotFoundException => false,
        SqliteException { SqliteErrorCode: 5 or 6 } => true, // SQLITE_BUSY, SQLITE_LOCKED
        IOException => true,
        _ => false,
    };

    public static string Describe(Exception error) => error is DomainValidationException or CsvFormatException or ImportConflictException or FileNotFoundException
        ? error.Message
        : $"{error.GetType().Name}: the import could not be completed.";
}
