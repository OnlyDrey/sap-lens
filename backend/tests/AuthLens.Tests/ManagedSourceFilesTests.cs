using System.Text.Json.Nodes;
using AuthLens.Application;
using AuthLens.Application.Backups;
using AuthLens.Domain.Roles;
using Microsoft.EntityFrameworkCore;

namespace AuthLens.Tests;

public sealed class ManagedSourceFilesTests
{
    [Fact]
    public async Task Successful_imports_keep_one_immutable_copy_and_failed_imports_preserve_it()
    {
        await using var env = await CoreEnv.StartAsync();
        const string first = "FUNCTION_KEY,AGR_NAME,TCODE\nFI,Z_FIRST,FB03\n";
        const string next = "FUNCTION_KEY,AGR_NAME,TCODE\nFI,Z_NEXT,FB02\n";
        await env.RunImportAsync(Sources.Roles, first);
        var original = Assert.Single(ManagedSourceFiles.References(env.Options.DatabasePath)).Key;
        Assert.Equal(first, File.ReadAllText(ManagedSourceFiles.Resolve(env.Options.DataDirectory, original)));
        await Assert.ThrowsAsync<DomainValidationException>(() => env.RunImportAsync(Sources.Roles, "INVALID,HEADER\n"));
        Assert.Equal(original, Assert.Single(ManagedSourceFiles.References(env.Options.DatabasePath)).Key);
        Assert.Equal(first, File.ReadAllText(ManagedSourceFiles.Resolve(env.Options.DataDirectory, original)));
        // The deliberately failed manual worker retains its lease; fail that test job before claiming the next one.
        await using (var db = await env.Factory.CreateDbContextAsync())
        {
            var job = await db.Jobs.SingleAsync(job => job.Status == "Running");
            await env.Queue.FailAsync(job.Id, "test-worker", "synthetic invalid file", false);
        }
        await env.RunImportAsync(Sources.Roles, next);
        ManagedSourceFiles.Prune(env.Options.DatabasePath);
        var current = Assert.Single(ManagedSourceFiles.References(env.Options.DatabasePath)).Key;
        Assert.NotEqual(original, current);
        Assert.Equal(next, File.ReadAllText(ManagedSourceFiles.Resolve(env.Options.DataDirectory, current)));
        Assert.Single(Directory.GetFiles(Path.Combine(env.Options.DataDirectory, "sources"), "*.csv"));
        await env.RunImportAsync(Sources.Roles, next);
        ManagedSourceFiles.Prune(env.Options.DatabasePath);
        Assert.Equal(current, Assert.Single(ManagedSourceFiles.References(env.Options.DatabasePath)).Key);
        Assert.Single(Directory.GetFiles(Path.Combine(env.Options.DataDirectory, "sources"), "*.csv"));
    }

    [Fact]
    public async Task Traversal_and_corrupted_managed_files_are_refused_before_a_backup_is_published()
    {
        await using var env = await CoreEnv.StartAsync();
        Assert.Throws<IOException>(() => ManagedSourceFiles.Resolve(env.Options.DataDirectory, "sources/../secret.csv"));
        Assert.Throws<IOException>(() => ManagedSourceFiles.Resolve(env.Options.DataDirectory, "C:/outside.csv"));
        await env.RunImportAsync(Sources.Roles, "FUNCTION_KEY,AGR_NAME,TCODE\nFI,Z_FIRST,FB03\n");
        var copy = ManagedSourceFiles.Resolve(env.Options.DataDirectory, Assert.Single(ManagedSourceFiles.References(env.Options.DatabasePath)).Key);
        File.WriteAllText(copy, "deliberately corrupted synthetic file");
        var archive = Path.Combine(env.Root, "refused.slbak");
        Assert.Throws<IOException>(() => ApplicationBackups.WriteArchive(env.Options.DataDirectory, archive, "synthetic test passphrase", null, "manual", DateTimeOffset.UtcNow));
        Assert.False(File.Exists(archive));
    }
}
