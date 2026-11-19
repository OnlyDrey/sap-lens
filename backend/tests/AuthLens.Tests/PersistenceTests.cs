using Microsoft.Data.Sqlite;
using Microsoft.EntityFrameworkCore;
using AuthLens.Persistence;

namespace AuthLens.Tests;

public sealed class PersistenceTests
{
    private static async Task<string> Scalar(string path, string sql)
    {
        await using var c = new SqliteConnection($"Data Source={path};Pooling=False");
        await c.OpenAsync();
        await using var cmd = c.CreateCommand();
        cmd.CommandText = sql;
        return Convert.ToString(await cmd.ExecuteScalarAsync())!;
    }

    [Fact]
    public async Task Initialization_enables_wal_foreign_keys_busy_timeout_and_passes_integrity()
    {
        await using var env = await CoreEnv.StartAsync();
        Assert.Equal("wal", await Scalar(env.Options.DatabasePath, "PRAGMA journal_mode;"));
        await using var db = await env.Factory.CreateDbContextAsync();
        await db.Database.OpenConnectionAsync();
        var conn = db.Database.GetDbConnection();
        await using var cmd = conn.CreateCommand();
        cmd.CommandText = "PRAGMA foreign_keys;";
        Assert.Equal(1L, await cmd.ExecuteScalarAsync());
        cmd.CommandText = "PRAGMA busy_timeout;";
        Assert.Equal(15000L, await cmd.ExecuteScalarAsync());
        Assert.True((await env.Maintenance.VerifyAsync()).Ok);
    }

    [Fact]
    public async Task Review_decisions_and_invalidations_cannot_be_updated_or_deleted_even_with_raw_sql()
    {
        await using var env = await CoreEnv.StartAsync();
        await env.RunImportAsync("roles", Csv.Roles(3));
        await env.RunImportAsync("users", Csv.Users(Csv.Assignments(3, 1, 3)));
        var decision = await env.Reviews.RecordAsync("assignment", "USER0000\u001fZC:FI:ROLE_0000", null, "approved", "reviewer", "ok");
        await using var db = await env.Factory.CreateDbContextAsync();
        var update = await Assert.ThrowsAsync<SqliteException>(() => db.Database.ExecuteSqlRawAsync("UPDATE ReviewDecisions SET Decision = 'rejected' WHERE Id = {0}", decision.Id));
        Assert.Contains("immutable", update.Message);
        await Assert.ThrowsAsync<SqliteException>(() => db.Database.ExecuteSqlRawAsync("DELETE FROM ReviewDecisions"));
        await Assert.ThrowsAsync<SqliteException>(() => db.Database.ExecuteSqlRawAsync("UPDATE DatasetRecords SET Payload = ''"));
        await Assert.ThrowsAsync<SqliteException>(() => db.Database.ExecuteSqlRawAsync("DELETE FROM Datasets WHERE Status = 'Active'"));
        await Assert.ThrowsAsync<SqliteException>(() => db.Database.ExecuteSqlRawAsync("UPDATE Datasets SET ContentHash = 'x' WHERE Status = 'Active'"));
    }

    [Fact]
    public async Task At_most_one_active_revision_per_source_is_enforced_by_the_database()
    {
        await using var env = await CoreEnv.StartAsync();
        await env.RunImportAsync("roles", Csv.Roles(3));
        await using var db = await env.Factory.CreateDbContextAsync();
        db.Datasets.Add(new Dataset { Source = "roles", Revision = 99, Status = DatasetStatus.Active, CreatedUtc = DateTime.UtcNow });
        await Assert.ThrowsAsync<DbUpdateException>(() => db.SaveChangesAsync());
    }

    [Fact]
    public async Task Online_backup_is_consistent_hashed_and_recorded()
    {
        await using var env = await CoreEnv.StartAsync();
        await env.RunImportAsync("roles", Csv.Roles(20));
        var backup = await env.Maintenance.BackupAsync(BackupKind.Manual, "test");
        var path = Path.Combine(env.Options.BackupDirectory, backup.FileName);
        Assert.True((await DatabaseMaintenance.VerifyFileAsync(path)).Ok);
        Assert.Equal("60", await Scalar(path, "SELECT COUNT(*) FROM DatasetRecords;"));
        Assert.Equal(1, await env.QueryAsync(db => db.Backups.CountAsync()));
        Assert.Equal(64, backup.Sha256.Length);
    }

    [Fact]
    public async Task Backup_retention_offers_only_old_automatic_archives()
    {
        await using var env = await CoreEnv.StartAsync();
        var now = env.Clock.GetUtcNow().UtcDateTime;
        BackupRecord B(string kind, int ageDays, bool confirmed = false) => new()
        {
            Kind = kind, FileName = $"archives/{Guid.NewGuid():N}.slbak", Sha256 = new string('0', 64), CreatedUtc = now.AddDays(-ageDays), AdminConfirmedUtc = confirmed ? now : null,
        };
        await env.QueryAsync(db => { db.Backups.AddRange(B("automatic", 89), B("automatic", 91), B("manual", 900), B("migration", 900), B("migration", 1, confirmed: true)); return db.SaveChangesAsync(); });
        var plan = await new AuthLens.Application.Retention.DataRetention(env.Options, env.Factory, env.Clock).PreviewAsync("backup", default);
        Assert.Equal(1, (int)plan["count"]!);                                       // the 91-day automatic archive; a confirmed migration backup is kept too
        Assert.Equal(91, (int)plan["sample"]![0]!["age_days"]!);
        Assert.Equal((2, 1, 2), ((int)plan["counts"]!["automatic"]!, (int)plan["counts"]!["manual"]!, (int)plan["counts"]!["migration"]!));
    }

    [Theory]
    [InlineData(@"\\server\share\saplens")]
    [InlineData("//server/share/saplens")]
    [InlineData("relative/path")]
    public void Network_and_relative_database_paths_are_refused(string path) =>
        Assert.Throws<InvalidOperationException>(() => DatabaseOptions.ValidateLocal(path));

    [Fact]
    public async Task A_database_from_a_newer_version_is_left_unchanged_and_not_ready()
    {
        await using var env = await CoreEnv.StartAsync();
        await using (var c = new SqliteConnection($"Data Source={env.Options.DatabasePath};Pooling=False"))
        {
            await c.OpenAsync();
            await using var cmd = c.CreateCommand();
            cmd.CommandText = "INSERT INTO __EFMigrationsHistory VALUES ('29991231000000_FromTheFuture', '99.0');";
            await cmd.ExecuteNonQueryAsync();
        }
        SqliteConnection.ClearAllPools();
        var before = await File.ReadAllBytesAsync(env.Options.DatabasePath);
        var again = new CoreEnvView(env);
        await again.Maintenance.InitializeAsync();
        Assert.False(again.Maintenance.Ready);
        Assert.Contains("newer version", again.Maintenance.NotReadyReason);
        SqliteConnection.ClearAllPools();
        Assert.Equal(before, await File.ReadAllBytesAsync(env.Options.DatabasePath));
        Assert.False(Directory.Exists(env.Options.BackupDirectory));
    }

    [Fact]
    public async Task Pending_migrations_take_a_protected_migration_backup_first()
    {
        await using var env = await CoreEnv.StartAsync();
        await env.RunImportAsync("roles", Csv.Roles(3));
        // Simulate an older schema version: forget the last migration (its tables stay; the re-applied migration must not run on a live file without a backup).
        await using (var c = new SqliteConnection($"Data Source={env.Options.DatabasePath};Pooling=False"))
        {
            await c.OpenAsync();
            await using var cmd = c.CreateCommand();
            cmd.CommandText = "PRAGMA writable_schema = 0; DELETE FROM __EFMigrationsHistory; " +
                              "DROP TABLE SodEvidenceSnapshots; DROP TABLE SodDecisionEvents; DROP TABLE SodDocuments; DROP TABLE SavedFilters; DROP TABLE RefreshReports; DROP TABLE Settings; DROP TABLE Backups; DROP TABLE ReviewInvalidations; DROP TABLE ReviewDecisions; DROP TABLE DatasetRecords; DROP TABLE Datasets; DROP TABLE Jobs;";
            await cmd.ExecuteNonQueryAsync();
        }
        SqliteConnection.ClearAllPools();
        var again = new CoreEnvView(env);
        await again.Maintenance.InitializeAsync();
        Assert.True(again.Maintenance.Ready, again.Maintenance.NotReadyReason);
        var backups = await env.QueryAsync(db => db.Backups.ToListAsync());
        var migration = Assert.Single(backups);
        Assert.Equal(BackupKind.Migration, migration.Kind);
        Assert.Null(migration.AdminConfirmedUtc);
        var plan = await new AuthLens.Application.Retention.DataRetention(env.Options, env.Factory, new ManualClock(DateTimeOffset.UtcNow.AddYears(5))).PreviewAsync("backup", default);
        Assert.Equal((0, 1), ((int)plan["count"]!, (int)plan["counts"]!["migration"]!));        // never a retention candidate
        Assert.True(File.Exists(Path.Combine(env.Options.BackupDirectory, migration.FileName)));
    }

    /// <summary>A second instance over the same directory (a process restart).</summary>
    private sealed class CoreEnvView(CoreEnv env)
    {
        public DatabaseMaintenance Maintenance { get; } = new(env.Options, env.Factory, Microsoft.Extensions.Logging.Abstractions.NullLogger<DatabaseMaintenance>.Instance);
    }
}
