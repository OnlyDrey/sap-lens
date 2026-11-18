using System.Net.Http.Json;
using System.Text.Json.Nodes;
using Microsoft.AspNetCore.Builder;
using SapLens.Api;
using SapLens.Application.Backups;

namespace SapLens.Tests;

/// <summary>The local maintenance commands the Windows deployment relies on: schema compatibility (decides whether a rollback to the previous release
/// is safe) and the encrypted pre-deployment backup taken while the server keeps running, with its independent verification.</summary>
public sealed class MaintenanceCommandsTests : IAsyncLifetime
{
    private readonly string _root = Directory.CreateTempSubdirectory("saplens-maintenance-").FullName;
    private readonly string _token = HostSettings.NewToken();
    private WebApplication _app = null!;
    private string Data => Path.Combine(_root, "data");

    public async Task InitializeAsync()
    {
        _app = SapLensHost.Build(new HostSettings { DataDirectory = Data, Port = 0, AccessToken = _token, JsonConsoleLogging = false, PrincipalName = "operator", Mode = HostMode.Desktop });
        await _app.StartAsync();
    }

    public async Task DisposeAsync()
    {
        await _app.StopAsync();
        await _app.DisposeAsync();
        Microsoft.Data.Sqlite.SqliteConnection.ClearAllPools();
        try { Directory.Delete(_root, true); } catch (IOException) { }
    }

    [Fact]
    public void Schema_info_reports_known_applied_and_newer_migrations_without_writing()
    {
        var missing = MaintenanceCommands.SchemaInfo(Path.Combine(_root, "nothing"));
        Assert.False((bool)missing["database_exists"]!);
        Assert.False(Directory.Exists(Path.Combine(_root, "nothing")));                          // never creates anything
        var info = MaintenanceCommands.SchemaInfo(Data);
        Assert.True((bool)info["compatible"]!);
        Assert.Equal(info["known"]!.ToJsonString(), info["applied"]!.ToJsonString());
        Assert.Empty(info["pending"]!.AsArray());

        // A database a newer build migrated: this build reports it as incompatible (a rollback to it would be unsafe).
        using (var db = new Microsoft.Data.Sqlite.SqliteConnection($"Data Source={Path.Combine(Data, ApplicationBackups.DatabaseEntry)};Pooling=False"))
        {
            db.Open();
            using var command = db.CreateCommand();
            command.CommandText = "INSERT INTO __EFMigrationsHistory VALUES ('29991231000000_FromTheFuture', '99.0')";
            command.ExecuteNonQuery();
        }
        var newer = MaintenanceCommands.SchemaInfo(Data);
        Assert.False((bool)newer["compatible"]!);
        Assert.Equal(["29991231000000_FromTheFuture"], newer["unknown_applied"]!.AsArray().Select(m => (string)m!));
    }

    [Fact]
    public void Inspection_checks_private_copies_and_leaves_source_files_unchanged()
    {
        var files = Directory.GetFiles(Data, "*", SearchOption.AllDirectories);
        static string Hash(string path)
        {
            using var stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete);
            return Convert.ToHexString(System.Security.Cryptography.SHA256.HashData(stream));
        }
        var before = files.Where(f => !f.EndsWith("-shm", StringComparison.Ordinal)).ToDictionary(f => f, Hash);
        var shmBefore = files.Where(f => f.EndsWith("-shm", StringComparison.Ordinal)).ToDictionary(f => f, File.GetLastWriteTimeUtc);
        var inspection = MaintenanceCommands.InspectData(Data);
        Assert.True((bool)inspection["ok"]!);
        Assert.NotEmpty(inspection["databases"]!.AsArray());
        Assert.Equal(files.Order(), Directory.GetFiles(Data, "*", SearchOption.AllDirectories).Order());
        foreach (var file in before.Keys) Assert.Equal(before[file], Hash(file));
        foreach (var file in shmBefore.Keys) Assert.Equal(shmBefore[file], File.GetLastWriteTimeUtc(file));
        Assert.Throws<InvalidOperationException>(() => MaintenanceCommands.InspectData(Path.Combine(_root, "missing")));
        Assert.False(Directory.Exists(Path.Combine(_root, "missing")));
        var bad = Path.Combine(Data, "broken.sqlite3");
        File.WriteAllText(bad, "not SQLite");
        Assert.Throws<Microsoft.Data.Sqlite.SqliteException>(() => MaintenanceCommands.InspectData(Data));
    }

    [Fact]
    public async Task A_pre_deployment_backup_is_encrypted_verified_and_taken_while_the_server_runs()
    {
        var folder = Path.Combine(_root, "predeploy");
        Assert.Throws<BackupException>(() => MaintenanceCommands.BackupLocal(Data, folder, DateTimeOffset.UtcNow));    // never unencrypted
        Directory.CreateDirectory(Path.Combine(_root, "keys"));
        BackupKeys.Create(Path.Combine(_root, "keys", "host.key"), Data);
        using (var client = new HttpClient { BaseAddress = new Uri(_app.Urls.First()) })
        {
            client.DefaultRequestHeaders.Add(RequestBoundary.TokenHeader, _token);
            client.DefaultRequestHeaders.Add("Origin", client.BaseAddress.GetLeftPart(UriPartial.Authority));
            Assert.True((await client.PostAsJsonAsync("/api/saved-filters", new { name = "Before deployment", view = "users", filters = new { search = "x" } })).IsSuccessStatusCode);
        }
        var backup = MaintenanceCommands.BackupLocal(Data, folder, DateTimeOffset.UtcNow);
        var file = (string)backup["file"]!;
        Assert.True(BackupArchive.IsV2(File.ReadAllBytes(file).AsSpan(0, 8)));
        var verified = MaintenanceCommands.BackupVerify(Data, file);
        Assert.True((bool)verified["verified"]!);
        Assert.Equal((string)backup["sha256"]!, (string)verified["sha256"]!);

        var damaged = file + ".damaged";
        var bytes = File.ReadAllBytes(file);
        bytes[^10] ^= 1;
        File.WriteAllBytes(damaged, bytes);
        Assert.Throws<BackupException>(() => MaintenanceCommands.BackupVerify(Data, damaged));
    }
}
