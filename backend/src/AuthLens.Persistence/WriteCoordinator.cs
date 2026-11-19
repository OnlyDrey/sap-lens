using Microsoft.EntityFrameworkCore;

namespace AuthLens.Persistence;

/// <summary>Single-writer discipline. In this process, writes are serialized by a semaphore (no busy-wait between our own writers); across processes,
/// each write runs in a BEGIN IMMEDIATE transaction, so SQLite's own file lock admits one writer and others wait up to the busy timeout. The
/// in-process lock is an optimization, never the only guarantee.</summary>
public sealed class WriteCoordinator(IDbContextFactory<AuthLensDb> factory)
{
    private readonly SemaphoreSlim _gate = new(1, 1);

    public async Task<T> WriteAsync<T>(Func<AuthLensDb, CancellationToken, Task<T>> work, CancellationToken cancellation = default)
    {
        await _gate.WaitAsync(cancellation);
        try
        {
            await using var db = await factory.CreateDbContextAsync(cancellation);
            // Microsoft.Data.Sqlite opens non-deferred transactions as BEGIN IMMEDIATE: the write lock is taken at the start, not at the first write.
            await using var transaction = await db.Database.BeginTransactionAsync(cancellation);
            var result = await work(db, cancellation);
            await db.SaveChangesAsync(cancellation);
            await transaction.CommitAsync(cancellation);
            return result;
        }
        finally
        {
            _gate.Release();
        }
    }

    public Task WriteAsync(Func<AuthLensDb, CancellationToken, Task> work, CancellationToken cancellation = default) =>
        WriteAsync<bool>(async (db, ct) => { await work(db, ct); return true; }, cancellation);
}
