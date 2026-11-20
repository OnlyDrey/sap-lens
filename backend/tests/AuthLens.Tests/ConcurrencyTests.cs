using System.Diagnostics;
using Microsoft.EntityFrameworkCore;
using AuthLens.Application;
using AuthLens.Persistence;

namespace AuthLens.Tests;

[CollectionDefinition("process-concurrency", DisableParallelization = true)]
public sealed class ProcessConcurrencyCollection;

/// <summary>Several OS processes against one SQLite file: the single-writer guarantee must not depend on the in-process semaphore.</summary>
// The latency bound measures writer admission, not competition with unrelated publish/build fixtures.
[Collection("process-concurrency")]
public sealed class ConcurrencyTests(Xunit.Abstractions.ITestOutputHelper output)
{
    private static Process Cli(params string[] args)
    {
        var info = new ProcessStartInfo("dotnet") { RedirectStandardOutput = true, RedirectStandardError = true, UseShellExecute = false };
        info.ArgumentList.Add(CliPath());
        foreach (var a in args) info.ArgumentList.Add(a);
        return Process.Start(info)!;
    }

    /// <summary>The CLI from its own build output (its deps.json), same configuration as the tests.</summary>
    private static string CliPath()
    {
        var baseDir = new DirectoryInfo(AppContext.BaseDirectory.TrimEnd(Path.DirectorySeparatorChar));
        var (framework, configuration) = (baseDir.Name, baseDir.Parent!.Name);
        var root = baseDir;
        while (root is not null && !File.Exists(Path.Combine(root.FullName, "AuthLens.slnx"))) root = root.Parent;
        return Path.Combine(root!.FullName, "src", "AuthLens.Cli", "bin", configuration, framework, "AuthLens.Cli.dll");
    }

    private static async Task<string> Finish(Process p)
    {
        var output = await p.StandardOutput.ReadToEndAsync();
        var error = await p.StandardError.ReadToEndAsync();
        await p.WaitForExitAsync();
        Assert.True(p.ExitCode == 0, error);
        return output;
    }

    [Fact]
    public async Task Concurrent_writers_in_separate_processes_lose_no_writes()
    {
        await using var env = await CoreEnv.StartAsync();
        var processes = Enumerable.Range(0, 4).Select(i => Cli("db-enqueue", "--data", env.Options.DataDirectory, "--count", "60", "--tag", $"p{i}")).ToList();
        var local = Task.Run(async () => { for (var i = 0; i < 60; i++) await env.Queue.EnqueueAsync("probe", "{}", null); });
        foreach (var p in processes) await Finish(p);
        await local;
        Assert.Equal(300, await env.QueryAsync(db => db.Jobs.CountAsync()));
        Assert.True((await env.Maintenance.VerifyAsync()).Ok);
    }

    [Fact]
    public async Task Competing_worker_processes_claim_every_job_exactly_once()
    {
        await using var env = await CoreEnv.StartAsync();
        for (var i = 0; i < 150; i++) await env.Queue.EnqueueAsync("probe", "{}", null);
        var outputs = await Task.WhenAll(Enumerable.Range(0, 4).Select(i => Finish(Cli("db-claim", "--data", env.Options.DataDirectory, "--owner", $"proc{i}"))));
        var claimed = outputs.SelectMany(o => o.Split('\n', StringSplitOptions.RemoveEmptyEntries)).Select(long.Parse).ToList();
        Assert.Equal(150, claimed.Count);
        Assert.Equal(150, claimed.Distinct().Count());
        var jobs = await env.QueryAsync(db => db.Jobs.ToListAsync());
        Assert.All(jobs, j => { Assert.Equal(JobStatus.Completed, j.Status); Assert.Equal(1, j.Attempts); });
    }

    [Fact]
    public async Task Reviews_commit_while_a_large_import_is_staging()
    {
        await using var env = await CoreEnv.StartAsync();
        await env.RunImportAsync("users", Csv.Users(Csv.Assignments(200, 1, 200)));
        var import = Task.Run(() => env.RunImportAsync("roles", Csv.Roles(8000, 3))); // 24 000 rows, five staging batches
        var latencies = new List<double>();
        var watch = Stopwatch.StartNew();
        for (var i = 0; i < 40 && !import.IsCompleted; i++)
        {
            var started = watch.Elapsed.TotalMilliseconds;
            await env.Reviews.RecordAsync("assignment", $"USER{i:D4}\u001fZC:FI:ROLE_{i:D4}", null, "approved", "r", null);
            latencies.Add(watch.Elapsed.TotalMilliseconds - started);
        }
        await import;
        Assert.NotEmpty(latencies);
        output.WriteLine($"{latencies.Count} review writes; maximum latency {latencies.Max():0} ms while staging 24,000 rows.");
        Assert.True(latencies.Max() < 5000, $"a review waited {latencies.Max():0} ms behind the import");
    }
}
