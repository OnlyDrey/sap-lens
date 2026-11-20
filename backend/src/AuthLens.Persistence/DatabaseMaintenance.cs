using System.Security.Cryptography;
using Microsoft.Data.Sqlite;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Logging;

namespace AuthLens.Persistence;

public sealed record IntegrityReport(bool Ok, IReadOnlyList<string> Problems);

/// <summary>Initialization (WAL, controlled migrations with a protected migration backup first), integrity verification and online backups.</summary>
public sealed class DatabaseMaintenance(DatabaseOptions options, IDbContextFactory<AuthLensDb> factory, ILogger<DatabaseMaintenance> logger)
{
    public bool Ready { get; private set; }
    public string? NotReadyReason { get; private set; }

    public async Task InitializeAsync(CancellationToken cancellation = default)
    {
        DatabaseOptions.ValidateLocal(options.DataDirectory);
        DatabaseOptions.RefuseUnadoptedLegacy(options.DataDirectory);
        if (File.Exists(options.DatabasePath) && File.Exists(options.LegacyDatabasePath))
            logger.LogWarning("Both AuthLens and SAP Lens database files exist. The existing authlens.sqlite3 is selected; the legacy file is preserved. Verify the explicit adoption/recovery record before removing anything.");
        Directory.CreateDirectory(options.DataDirectory);
        var existed = File.Exists(options.DatabasePath);
        await using var db = await factory.CreateDbContextAsync(cancellation);
        var known = db.Database.GetMigrations().ToHashSet(StringComparer.Ordinal);
        if (existed)
        {
            var applied = (await db.Database.GetAppliedMigrationsAsync(cancellation)).ToList();
            var unknown = applied.Where(m => !known.Contains(m)).ToList();
            if (unknown.Count > 0)
            {
                // A database written by a newer AuthLens is never downgraded or modified.
                (Ready, NotReadyReason) = (false, "The database was written by a newer version and was left unchanged.");
                logger.LogError("Database has unknown migrations {Migrations}; left unchanged", unknown);
                return;
            }
            var pending = (await db.Database.GetPendingMigrationsAsync(cancellation)).ToList();
            if (pending.Count > 0)
            {
                var backup = await BackupAsync(BackupKind.Migration, $"before migrations {string.Join(", ", pending)}", recordInDatabase: false, cancellation);
                logger.LogInformation("Migration backup {File} created before applying {Count} migrations", backup.FileName, pending.Count);
                await db.Database.MigrateAsync(cancellation);
                await db.Backups.AddAsync(backup, cancellation);
                await db.SaveChangesAsync(cancellation);
            }
        }
        else
        {
            await db.Database.MigrateAsync(cancellation);
        }
        await db.Database.ExecuteSqlRawAsync("PRAGMA journal_mode = WAL;", cancellation);
        var integrity = await VerifyAsync(cancellation);
        (Ready, NotReadyReason) = integrity.Ok ? (true, null) : (false, "Integrity check failed: " + string.Join("; ", integrity.Problems.Take(5)));
    }

    public async Task<IntegrityReport> VerifyAsync(CancellationToken cancellation = default) => await VerifyFileAsync(options.DatabasePath, cancellation);

    public static async Task<IntegrityReport> VerifyFileAsync(string path, CancellationToken cancellation = default)
    {
        await using var connection = new SqliteConnection(new SqliteConnectionStringBuilder { DataSource = path, Mode = SqliteOpenMode.ReadOnly, Pooling = false }.ToString());
        await connection.OpenAsync(cancellation);
        var problems = new List<string>();
        await using (var command = connection.CreateCommand())
        {
            command.CommandText = "PRAGMA integrity_check;";
            await using var reader = await command.ExecuteReaderAsync(cancellation);
            while (await reader.ReadAsync(cancellation)) if (reader.GetString(0) != "ok") problems.Add(reader.GetString(0));
        }
        await using (var command = connection.CreateCommand())
        {
            command.CommandText = "PRAGMA foreign_key_check;";
            await using var reader = await command.ExecuteReaderAsync(cancellation);
            while (await reader.ReadAsync(cancellation)) problems.Add($"foreign key violation in {reader.GetString(0)} row {reader.GetValue(1)}");
        }
        return new IntegrityReport(problems.Count == 0, problems);
    }

    /// <summary>SQLite Online Backup API: a consistent copy while readers and writers continue. The copy is integrity-checked before it is recorded.</summary>
    public async Task<BackupRecord> BackupAsync(string kind, string? reason, bool recordInDatabase = true, CancellationToken cancellation = default)
    {
        Directory.CreateDirectory(options.BackupDirectory);
        var name = $"authlens-{kind}-{DateTime.UtcNow:yyyyMMddTHHmmssfffZ}.sqlite3";
        var target = Path.Combine(options.BackupDirectory, name);
        var temporary = target + ".partial";
        await using (var source = new SqliteConnection(new SqliteConnectionStringBuilder { DataSource = options.DatabasePath, Mode = SqliteOpenMode.ReadOnly, Pooling = false }.ToString()))
        await using (var destination = new SqliteConnection(new SqliteConnectionStringBuilder { DataSource = temporary, Pooling = false }.ToString()))
        {
            await source.OpenAsync(cancellation);
            await destination.OpenAsync(cancellation);
            source.BackupDatabase(destination);
        }
        var integrity = await VerifyFileAsync(temporary, cancellation);
        if (!integrity.Ok) { File.Delete(temporary); throw new InvalidOperationException("The backup failed its integrity check and was discarded."); }
        File.Move(temporary, target);
        await using var stream = File.OpenRead(target);
        var record = new BackupRecord
        {
            Kind = kind, FileName = name, Sha256 = Convert.ToHexStringLower(await SHA256.HashDataAsync(stream, cancellation)), SizeBytes = new FileInfo(target).Length,
            Reason = reason, CreatedUtc = DateTime.UtcNow,
        };
        if (recordInDatabase)
        {
            await using var db = await factory.CreateDbContextAsync(cancellation);
            db.Backups.Add(record);
            await db.SaveChangesAsync(cancellation);
        }
        return record;
    }
}
