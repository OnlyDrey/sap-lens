using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;
using AuthLens.Persistence;

namespace AuthLens.Application;

public static class CoreServices
{
    /// <summary>Registers the core shared by Desktop and Server: SQLite, the write coordinator, initialization, snapshot, import, reviews and the job worker.</summary>
    public static IServiceCollection AddAuthLensCore(this IServiceCollection services, DatabaseOptions database, WorkerOptions? worker = null)
    {
        services.AddSingleton(database);
        services.AddSingleton(worker ?? new WorkerOptions());
        services.AddSingleton(TimeProvider.System);
        services.AddPooledDbContextFactory<AuthLensDb>(database.Configure);
        services.AddSingleton<WriteCoordinator>();
        services.AddSingleton<DatabaseMaintenance>();
        services.AddSingleton<JobQueue>();
        services.AddSingleton<SnapshotService>();
        services.AddSingleton<ReviewService>();
        services.AddSingleton<SodDecisionStore>();
        services.AddSingleton<AssignmentLifecycle>();
        services.AddSingleton<IImportCommitted>(sp => sp.GetRequiredService<AssignmentLifecycle>());
        services.AddSingleton<PositionChangeStore>();
        services.AddSingleton<IImportCommitted>(sp => sp.GetRequiredService<PositionChangeStore>());
        services.AddSingleton<ImportService>();
        services.AddSingleton<IJobHandler>(sp => sp.GetRequiredService<ImportService>());
        services.AddHostedService<DatabaseInitializer>();
        services.AddSingleton<JobWorker>();
        services.AddHostedService(sp => sp.GetRequiredService<JobWorker>());
        return services;
    }
}

/// <summary>Runs before the worker (hosted services start in registration order): safe initialization, never a silent repair.</summary>
public sealed class DatabaseInitializer(DatabaseMaintenance maintenance) : IHostedService
{
    public Task StartAsync(CancellationToken cancellationToken) => maintenance.InitializeAsync(cancellationToken);
    public Task StopAsync(CancellationToken cancellationToken) => Task.CompletedTask;
}
