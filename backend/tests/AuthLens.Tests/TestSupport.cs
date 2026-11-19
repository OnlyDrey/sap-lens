using System.Text;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Infrastructure;
using Microsoft.Extensions.Logging.Abstractions;
using AuthLens.Application;
using AuthLens.Persistence;

namespace AuthLens.Tests;

public sealed class ManualClock(DateTimeOffset start, TimeZoneInfo? localZone = null) : TimeProvider
{
    public DateTimeOffset Now { get; set; } = start;
    public override DateTimeOffset GetUtcNow() => Now;
    public override TimeZoneInfo LocalTimeZone => localZone ?? base.LocalTimeZone;
    public void Advance(TimeSpan by) => Now += by;
}

/// <summary>A disposable data directory with the full core wired by hand (no host): what Desktop and Server register through AddAuthLensCore.</summary>
public sealed class CoreEnv : IAsyncDisposable
{
    public string Root { get; } = Directory.CreateTempSubdirectory("saplens-test-").FullName;
    public DatabaseOptions Options { get; }
    public IDbContextFactory<AuthLensDb> Factory { get; }
    public WriteCoordinator Writer { get; }
    public DatabaseMaintenance Maintenance { get; }
    public ManualClock Clock { get; } = new(new DateTimeOffset(2026, 11, 15, 12, 0, 0, TimeSpan.Zero));
    public JobQueue Queue { get; }
    public SnapshotService Snapshots { get; }
    public ImportService Imports { get; }
    public ReviewService Reviews { get; }

    public CoreEnv()
    {
        Options = new DatabaseOptions { DataDirectory = Path.Combine(Root, "data"), BusyTimeoutMs = 15000 };
        var builder = new DbContextOptionsBuilder<AuthLensDb>();
        Options.Configure(builder);
        Factory = new PooledDbContextFactory<AuthLensDb>(builder.Options);
        Writer = new WriteCoordinator(Factory);
        Maintenance = new DatabaseMaintenance(Options, Factory, NullLogger<DatabaseMaintenance>.Instance);
        Queue = new JobQueue(Writer, Factory, Clock);
        Snapshots = new SnapshotService(Factory);
        Imports = new ImportService(Writer, Factory, Snapshots, Clock);
        Reviews = new ReviewService(Writer, Factory, Snapshots, Clock);
    }

    public static async Task<CoreEnv> StartAsync()
    {
        var env = new CoreEnv();
        await env.Maintenance.InitializeAsync();
        Assert.True(env.Maintenance.Ready, env.Maintenance.NotReadyReason);
        return env;
    }

    public string WriteCsv(string name, string content)
    {
        var path = Path.Combine(Root, $"{Guid.NewGuid():N}-{name}");
        File.WriteAllText(path, content, new UTF8Encoding(false));
        return path;
    }

    public async Task<Job> EnqueueImportAsync(string source, string csv) =>
        await Queue.EnqueueAsync(ImportService.JobKind, System.Text.Json.JsonSerializer.Serialize(new ImportPayload(source, WriteCsv(source + ".csv", csv), source + ".csv"), Sources.Json), null);

    /// <summary>Claims the next job and runs the import handler to completion the way the worker does (completion and activation in one transaction).</summary>
    public async Task<ImportResult> RunImportAsync(string source, string csv, string owner = "test-worker")
    {
        var job = await EnqueueImportAsync(source, csv);
        var claimed = await Queue.ClaimAsync(owner);
        Assert.NotNull(claimed);
        Assert.Equal(job.Id, claimed!.Id);
        var outcome = await Imports.RunAsync(new JobContext(claimed, owner, Queue, CancellationToken.None));
        await Queue.CompleteAsync(claimed.Id, owner, outcome.ResultJson, outcome.Atomic);
        return System.Text.Json.JsonSerializer.Deserialize<ImportResult>(outcome.ResultJson!, Sources.Json)!;
    }

    public async Task<T> QueryAsync<T>(Func<AuthLensDb, Task<T>> query)
    {
        await using var db = await Factory.CreateDbContextAsync();
        return await query(db);
    }

    public async ValueTask DisposeAsync()
    {
        Microsoft.Data.Sqlite.SqliteConnection.ClearAllPools();
        await Task.Yield();
        try { Directory.Delete(Root, true); } catch (IOException) { }
    }
}

/// <summary>Small synthetic SAP extracts (reserved names only).</summary>
public static class Csv
{
    public const string RolesHeader = "FUNCTION_KEY;AGR_NAME;TEXT;CHILD_AGR;CHILD_AGR_TEXT;PARENT_AGR;Effective_Role;TCODE;TTEXT";
    public const string UsersHeader = "USERNAME;ROLE_NAME;USER_GROUP;FIRST_NAME;LAST_NAME;EMAIL;USER_VALID_FROM;USER_VALID_TO;ROLE_VALID_FROM;ROLE_VALID_TO;USER_LOCKED;USER_TYPE";
    public const string SodHeader = "RISK;CRITICITY;TYPE;TEXT;ACTVT1;ACTVT2;ACTIVITY_SLOT;ACTIVITY;TCODE;TTEXT";

    public static string Roles(int count, int tcodes = 3) => RolesHeader + "\n" + string.Join("\n",
        Enumerable.Range(0, count).SelectMany(r => Enumerable.Range(0, tcodes).Select(t => $"FI;ZC:FI:ROLE_{r:D4};Role {r};;;;;T{(r * tcodes + t) % 50:D3};Transaction {t}"))) + "\n";

    public static string Users(IEnumerable<(string User, string Role)> assignments) => UsersHeader + "\n" + string.Join("\n",
        assignments.Select(a => $"{a.User};{a.Role};GRP_FIN;First;Last;;;;;;;A")) + "\n";

    public static IEnumerable<(string, string)> Assignments(int users, int rolesPerUser, int roleCount) =>
        Enumerable.Range(0, users).SelectMany(u => Enumerable.Range(0, rolesPerUser).Select(k => ($"USER{u:D4}", $"ZC:FI:ROLE_{(u + k) % roleCount:D4}")));

    public static string Sod() => SodHeader + "\nR001;High;SOD;Pay and create vendor;A1;A2;ACTVT1;A1;T001;x\nR001;High;SOD;Pay and create vendor;A1;A2;ACTVT2;A2;T002;y\n";
}
