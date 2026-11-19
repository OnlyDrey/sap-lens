using System.Data.Common;
using Microsoft.Data.Sqlite;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Diagnostics;

namespace AuthLens.Persistence;

public sealed class DatabaseOptions
{
    public required string DataDirectory { get; init; }
    public int BusyTimeoutMs { get; init; } = 15000;
    public string DatabasePath => Path.Combine(DataDirectory, "sap-lens-v2.sqlite3");
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
