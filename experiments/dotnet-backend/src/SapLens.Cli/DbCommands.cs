using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Infrastructure;
using SapLens.Application;
using SapLens.Persistence;

namespace SapLens.Cli;

/// <summary>Cross-process probes for the SQLite tests: several OS processes write to and claim from the same database at the same time.</summary>
public static class DbCommands
{
    private static (WriteCoordinator Writer, IDbContextFactory<SapLensDb> Factory) Open(string data)
    {
        var options = new DatabaseOptions { DataDirectory = data };
        var builder = new DbContextOptionsBuilder<SapLensDb>();
        options.Configure(builder);
        var factory = new PooledDbContextFactory<SapLensDb>(builder.Options);
        return (new WriteCoordinator(factory), factory);
    }

    public static async Task<int> EnqueueAsync(string data, int count, string tag)
    {
        var (writer, factory) = Open(data);
        var queue = new JobQueue(writer, factory, TimeProvider.System);
        for (var i = 0; i < count; i++) await queue.EnqueueAsync("probe", $"{{\"tag\":\"{tag}\",\"n\":{i}}}", null);
        return 0;
    }

    public static async Task<int> ClaimAllAsync(string data, string owner)
    {
        var (writer, factory) = Open(data);
        var queue = new JobQueue(writer, factory, TimeProvider.System);
        while (await queue.ClaimAsync(owner) is { } job)
        {
            await queue.CompleteAsync(job.Id, owner, $"{{\"owner\":\"{owner}\"}}", null);
            Console.WriteLine(job.Id);
        }
        return 0;
    }
}
