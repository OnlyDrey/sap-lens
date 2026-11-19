using System.Data.Common;
using Microsoft.Data.Sqlite;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Diagnostics;

namespace AuthLens.Persistence;

public sealed class DatabaseOptions
{
    public required string DataDirectory { get; init; }
    public int BusyTimeoutMs { get; init; } = 15000;
    /// <summary>The one AuthLens database file. The database of SAP Lens (the same schema and migration history) was named
    /// <see cref="LegacyDatabaseFileName"/>; AuthLens never opens, converts or replaces it implicitly (see <see cref="RefuseUnadoptedLegacy"/>).</summary>
    public const string DatabaseFileName = "authlens.sqlite3", LegacyDatabaseFileName = "sap-lens-v2.sqlite3";
    public string DatabasePath => Path.Combine(DataDirectory, DatabaseFileName);
    public string LegacyDatabasePath => Path.Combine(DataDirectory, LegacyDatabaseFileName);

    /// <summary>A data directory with a SAP Lens database and no AuthLens database is refused before anything opens SQLite: starting would otherwise
    /// create an empty authlens.sqlite3 beside the real data. Restore a backup into a new data directory, or convert the copy explicitly with
    /// AuthLens.Api --adopt-legacy-database (verified SQLite backup; the SAP Lens file is kept unchanged).</summary>
    public static void RefuseUnadoptedLegacy(string directory)
    {
        if (File.Exists(Path.Combine(directory, DatabaseFileName)) || !File.Exists(Path.Combine(directory, LegacyDatabaseFileName))) return;
        throw new InvalidOperationException($"{directory} holds a SAP Lens database ({LegacyDatabaseFileName}) and no AuthLens database ({DatabaseFileName}). " +
            "AuthLens does not convert or replace it implicitly. Restore a SAP Lens backup into a new AuthLens data directory, or convert this copy " +
            "explicitly with: AuthLens.Api --adopt-legacy-database --data-dir <this directory> (the SAP Lens file is kept unchanged).");
    }
    public string BackupDirectory => Path.Combine(DataDirectory, "backups");

    /// <summary>The database must be on local, persistent storage: UNC paths, URLs and network drives are refused (SQLite locking is unreliable there).</summary>
    public static void ValidateLocal(string directory)
    {
        if (!Path.IsPathFullyQualified(directory)) throw new InvalidOperationException("The data directory must be an absolute local path.");
        var full = Path.GetFullPath(directory);
        // Checked on the raw value too: on Linux GetFullPath collapses a leading "//" into "/".
        if (directory.StartsWith(@"\\", StringComparison.Ordinal) || directory.StartsWith("//", StringComparison.Ordinal) || full.StartsWith(@"\\", StringComparison.Ordinal) || full.StartsWith("//", StringComparison.Ordinal) || full.Contains("://", StringComparison.Ordinal))
            throw new InvalidOperationException("The SQLite database must not be on a network share.");
        if (OperatingSystem.IsWindows())
        {
            var root = Path.GetPathRoot(full);
            if (root is not null && new DriveInfo(root).DriveType == DriveType.Network) throw new InvalidOperationException("The SQLite database must not be on a network drive.");
        }
    }

    public string ConnectionString => new SqliteConnectionStringBuilder
    {
        DataSource = DatabasePath, Mode = SqliteOpenMode.ReadWriteCreate, ForeignKeys = true, Pooling = true, DefaultTimeout = Math.Max(1, BusyTimeoutMs / 1000),
    }.ToString();

    public void Configure(DbContextOptionsBuilder builder) => builder.UseSqlite(ConnectionString).AddInterceptors(new SqlitePragmas(BusyTimeoutMs));
}

/// <summary>Every opened connection gets the busy timeout in milliseconds and synchronous=NORMAL (safe with WAL). WAL itself is persistent and set at initialization.</summary>
public sealed class SqlitePragmas(int busyTimeoutMs) : DbConnectionInterceptor
{
    public override void ConnectionOpened(DbConnection connection, ConnectionEndEventData eventData) => Apply(connection);

    public override Task ConnectionOpenedAsync(DbConnection connection, ConnectionEndEventData eventData, CancellationToken cancellationToken = default)
    {
        Apply(connection);
        return Task.CompletedTask;
    }

    private void Apply(DbConnection connection)
    {
        using var command = connection.CreateCommand();
        command.CommandText = $"PRAGMA busy_timeout = {busyTimeoutMs}; PRAGMA synchronous = NORMAL;";
        command.ExecuteNonQuery();
    }
}

public sealed class DesignTimeFactory : Microsoft.EntityFrameworkCore.Design.IDesignTimeDbContextFactory<AuthLensDb>
{
    public AuthLensDb CreateDbContext(string[] args)
    {
        var builder = new DbContextOptionsBuilder<AuthLensDb>();
        new DatabaseOptions { DataDirectory = Path.GetTempPath() }.Configure(builder);
        return new AuthLensDb(builder.Options);
    }
}
