using System.Security.Cryptography;
using System.Text.Json.Nodes;
using Microsoft.Data.Sqlite;
using Microsoft.EntityFrameworkCore;
using AuthLens.Api;
using AuthLens.Application.Accounts;
using AuthLens.Application.Backups;
using AuthLens.Persistence;

namespace AuthLens.Tests;

/// <summary>Real SQLite/WAL fixtures only; no application host or installed service is started.</summary>
public sealed class MaintenanceInspectionTests : IDisposable
{
    private readonly string _root = Directory.CreateTempSubdirectory("saplens-inspection-test-").FullName;
    private string Data => Path.Combine(_root, "active data");

    private SqliteConnection CreateActiveStore()
    {
        Directory.CreateDirectory(Data);
        var options = new DatabaseOptions { DataDirectory = Data };
        var builder = new DbContextOptionsBuilder<AuthLensDb>();
        options.Configure(builder);
        using (var db = new AuthLensDb(builder.Options)) db.Database.Migrate();
        var connection = new SqliteConnection(new SqliteConnectionStringBuilder { DataSource = options.DatabasePath, Pooling = false }.ToString());
        connection.Open();
        using var command = connection.CreateCommand();
        command.CommandText = "PRAGMA journal_mode=WAL; PRAGMA wal_autocheckpoint=0;";
        command.ExecuteNonQuery();
        // Keep this committed setting in WAL, with the connection leased throughout inspection.
        command.CommandText = "INSERT OR REPLACE INTO Settings (Id,Revision,Json,UpdatedUtc,UpdatedBy) VALUES (1,1,$json,'2026-11-19','synthetic')";
        command.Parameters.AddWithValue("$json", new JsonObject { ["data_csv_path"] = Path.Combine(_root, "external", "roles.csv") }.ToJsonString());
        command.ExecuteNonQuery();
        return connection;
    }

    private static string Hash(string file)
    {
        using var input = new FileStream(file, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete);
        return Convert.ToHexString(SHA256.HashData(input));
    }

    [Fact]
    public void Inspection_uses_the_canonical_live_store_and_committed_WAL_without_changing_source_files()
    {
        using var source = CreateActiveStore();
        new AccountStore(AccountStore.For(Data), TimeProvider.System).Prepare();
        var database = new DatabaseOptions { DataDirectory = Data }.DatabasePath;
        Assert.Equal(Path.Combine(Data, ApplicationBackups.DatabaseEntry), database);
        Assert.True(File.Exists(database + "-wal"));
        Assert.True(File.Exists(database + "-shm"));
        var files = Directory.GetFiles(Data, "*", SearchOption.AllDirectories);
        var before = files.Where(file => !file.EndsWith("-shm", StringComparison.Ordinal)).ToDictionary(file => file, Hash);
        // SHM contains Windows lock bytes and is not read/copied; neither its content nor timestamps are written by inspection.
        var shmTimes = files.Where(file => file.EndsWith("-shm", StringComparison.Ordinal)).ToDictionary(file => file, File.GetLastWriteTimeUtc);
        var result = MaintenanceCommands.InspectData(Data);
        Assert.True((bool)result["ok"]!);
        Assert.True((bool)result["schema"]!["database_exists"]!);
        Assert.Equal(database, (string)result["database_path"]!);
        Assert.Equal(Data, (string)result["data_directory"]!);
        Assert.Equal("stable-private-copy", (string)result["inspection_mode"]!);
        Assert.Equal(Path.Combine(_root, "external", "roles.csv"), (string)result["source_paths"]!["data_csv_path"]!);
        Assert.Contains("canonical-sqlite-stores-v1", result["capabilities"]!.AsArray().Select(node => (string)node!));
        Assert.Equal(new[] { "application", "security" }, result["databases"]!.AsArray().Select(node => (string)node!["role"]!));
        Assert.Contains(ApplicationBackups.DatabaseEntry + "-wal", result["databases"]![0]!["sidecars"]!.AsArray().Select(node => (string)node!));
        Assert.Equal(files.Order(), Directory.GetFiles(Data, "*", SearchOption.AllDirectories).Order());
        foreach (var (file, hash) in before) Assert.Equal(hash, Hash(file));
        foreach (var (file, time) in shmTimes) Assert.Equal(time, File.GetLastWriteTimeUtc(file));
    }

    [Fact]
    public void Historical_migration_databases_and_unrelated_files_are_not_adopted_or_opened_as_active_stores()
    {
        using var source = CreateActiveStore();
        var previous = Directory.CreateDirectory(Path.Combine(Data, "migration", new string('a', 32), "previous")).FullName;
        var historical = Path.Combine(previous, ApplicationBackups.DatabaseEntry);
        File.WriteAllText(historical, "retained synthetic historical evidence, deliberately not SQLite");
        var unrelated = Path.Combine(Data, "unrelated.db");
        File.WriteAllText(unrelated, "retained synthetic unrelated evidence");
        var original = Hash(historical);
        var result = MaintenanceCommands.InspectData(Data);
        Assert.True((bool)result["ok"]!);
        Assert.Single(result["databases"]!.AsArray());
        Assert.Equal(2, (int)result["ignored_historical_databases"]!);
        Assert.Equal(original, Hash(historical));
        Assert.Equal("retained synthetic unrelated evidence", File.ReadAllText(unrelated));
    }

    [Fact]
    public void Security_and_historical_stores_cannot_substitute_for_a_missing_application_database()
    {
        Directory.CreateDirectory(Data);
        new AccountStore(AccountStore.For(Data), TimeProvider.System).Prepare();
        var history = Directory.CreateDirectory(Path.Combine(Data, "migration", "previous")).FullName;
        File.WriteAllText(Path.Combine(history, ApplicationBackups.DatabaseEntry), "retained history");
        var files = Directory.GetFiles(Data, "*", SearchOption.AllDirectories);
        var error = Assert.Throws<InvalidOperationException>(() => MaintenanceCommands.InspectData(Data));
        Assert.Contains("active AuthLens database is missing", error.Message);
        Assert.False(File.Exists(new DatabaseOptions { DataDirectory = Data }.DatabasePath));
        Assert.Equal(files.Order(), Directory.GetFiles(Data, "*", SearchOption.AllDirectories).Order());
    }

    [Theory]
    [InlineData("")]
    [InlineData(" ")]
    [InlineData("relative-data")]
    public void Empty_and_relative_paths_are_refused_before_initialization(string data)
    {
        Assert.Throws<InvalidOperationException>(() => MaintenanceCommands.InspectData(data));
        Assert.Throws<InvalidOperationException>(() => MaintenanceCommands.SchemaInfo(data));
    }

    [Fact]
    public void Missing_data_is_not_created_and_corrupt_active_security_is_not_ignored()
    {
        Assert.Throws<InvalidOperationException>(() => MaintenanceCommands.InspectData(Data));
        Assert.False(Directory.Exists(Data));
        using var source = CreateActiveStore();
        var security = AccountStore.For(Data);
        Directory.CreateDirectory(Path.GetDirectoryName(security)!);
        File.WriteAllText(security, "invalid synthetic SQLite");
        Assert.Throws<SqliteException>(() => MaintenanceCommands.InspectData(Data));
        Assert.Equal("invalid synthetic SQLite", File.ReadAllText(security));
    }

    public void Dispose()
    {
        SqliteConnection.ClearAllPools();
        Directory.Delete(_root, true);
    }
}
