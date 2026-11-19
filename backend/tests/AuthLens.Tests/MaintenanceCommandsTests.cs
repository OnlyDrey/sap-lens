using System.Net.Http.Json;
using System.Text.Json.Nodes;
using Microsoft.AspNetCore.Builder;
using Microsoft.Extensions.DependencyInjection;
using AuthLens.Api;
using AuthLens.Application.Backups;
using AuthLens.Persistence;

namespace AuthLens.Tests;

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
        _app = AuthLensHost.Build(new HostSettings { DataDirectory = Data, Port = 0, AccessToken = _token, JsonConsoleLogging = false, PrincipalName = "operator", Mode = HostMode.Desktop });
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
    public async Task Packaged_server_issues_local_activation_and_recovery_codes_without_starting_a_host()
    {
        var data = Directory.CreateDirectory(Path.Combine(_root, "local-admin")).FullName;
        Assert.True(MaintenanceCommands.Handles(["--accounts-code"]));
        var activation = MaintenanceCommands.AdministratorCode(data, null);
        Assert.Equal("bootstrap", (string)activation["purpose"]!);
        var store = new AuthLens.Application.Accounts.AccountStore(AuthLens.Application.Accounts.AccountStore.For(data), TimeProvider.System);
        await store.CompleteAsync((string)activation["code"]!, "admin", "Synthetic administrator", "Synthetic local password 123!", false);
        Assert.Throws<AuthLens.Application.Accounts.AuthException>(() => MaintenanceCommands.AdministratorCode(data, null));
        Assert.Equal("recovery", (string)MaintenanceCommands.AdministratorCode(data, "admin")["purpose"]!);
        var missing = Path.Combine(_root, "unselected-data");
        Assert.Throws<InvalidOperationException>(() => MaintenanceCommands.AdministratorCode(missing, null));
        Assert.False(Directory.Exists(missing));
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
    public async Task Directory_migration_rebases_only_verified_private_upload_copies_and_preserves_original_data()
    {
        var name = "roles-0123456789abcdef.csv";
        var upload = Path.Combine(Data, "sources", name);
        Directory.CreateDirectory(Path.GetDirectoryName(upload)!);
        File.WriteAllText(upload, "AGR_NAME,TEXT,CHILD_AGR,TCODE\nZC:SYN,Synthetic,ZS:SYN,MIGO\n");
        var external = Path.Combine(_root, "external-users.csv");
        File.WriteAllText(external, "USERNAME,ROLE_NAME\nSYNTHETIC,ZC:SYN\n");
        var settings = _app.Services.GetRequiredService<V1Settings>();
        using var client = new HttpClient { BaseAddress = new Uri(_app.Urls.First()) };
        client.DefaultRequestHeaders.Add(RequestBoundary.TokenHeader, _token);
        client.DefaultRequestHeaders.Add("Origin", client.BaseAddress.GetLeftPart(UriPartial.Authority));
        foreach (var (source, file) in new[] { ("roles", upload), ("users", external) })
        {
            var revision = (int)(await settings.GetAsync(default))["revision"]!;
            var selected = await client.PostAsJsonAsync($"/api/data-sources/{source}/select", new { path = file, mode = "static", revision });
            Assert.True(selected.IsSuccessStatusCode, await selected.Content.ReadAsStringAsync());
        }
        var original = await settings.GetAsync(default);
        var backup = await _app.Services.GetRequiredService<DatabaseMaintenance>().BackupAsync(BackupKind.Manual, "synthetic offline copy", recordInDatabase: false);
        var archive = Path.Combine(_app.Services.GetRequiredService<DatabaseOptions>().BackupDirectory, backup.FileName);
        string Copy(string label, string bytes)
        {
            var copy = Directory.CreateDirectory(Path.Combine(_root, label)).FullName;
            Directory.CreateDirectory(Path.Combine(copy, "sources"));
            File.Copy(archive, Path.Combine(copy, ApplicationBackups.DatabaseEntry));
            File.WriteAllText(Path.Combine(copy, "sources", name), bytes);
            return copy;
        }
        static string Hash(string data) => Convert.ToHexStringLower(System.Security.Cryptography.SHA256.HashData(File.ReadAllBytes(Path.Combine(data, ApplicationBackups.DatabaseEntry))));
        static (JsonObject Settings, int Revision, long Records) Read(string data)
        {
            using var connection = new Microsoft.Data.Sqlite.SqliteConnection($"Data Source={Path.Combine(data, ApplicationBackups.DatabaseEntry)};Mode=ReadOnly;Pooling=False");
            connection.Open(); using var command = connection.CreateCommand();
            command.CommandText = "SELECT Json,Revision FROM Settings WHERE Id=1";
            JsonObject json; int revision;
            using (var reader = command.ExecuteReader()) { Assert.True(reader.Read()); json = JsonNode.Parse(reader.GetString(0))!.AsObject(); revision = reader.GetInt32(1); }
            command.CommandText = "SELECT COUNT(*) FROM DatasetRecords";
            return (json, revision, (long)command.ExecuteScalar()!);
        }
        var copy = Copy("copy", File.ReadAllText(upload));
        var before = Read(copy); Assert.True(before.Records > 0);
        Assert.True(MaintenanceCommands.Handles(["--rebase-upload-paths"]));
        Assert.Equal(0, MaintenanceCommands.Run(["--rebase-upload-paths", Data, "--data-dir", copy, "--migration-copy", "--expected-db-sha", Hash(copy)]));
        var after = Read(copy);
        Assert.Equal(Path.Combine(copy, "sources", name), (string)after.Settings["data_csv_path"]!);
        Assert.Equal(external, (string)after.Settings["user_csv_path"]!);
        Assert.Equal((before.Revision + 1, before.Records), (after.Revision, after.Records));
        Assert.Equal(original.ToJsonString(), (await settings.GetAsync(default)).ToJsonString());
        var unchanged = Hash(copy);
        Assert.Equal(0, (int)MaintenanceCommands.RebaseUploadedPaths(copy, Data, unchanged)["rebased"]!);
        Assert.Equal(unchanged, Hash(copy));
        Assert.Throws<InvalidOperationException>(() => MaintenanceCommands.RebaseUploadedPaths(Data, Data, unchanged));
        Assert.Throws<InvalidOperationException>(() => MaintenanceCommands.RebaseUploadedPaths(copy, Data, new string('0', 64)));
        Assert.Equal(unchanged, Hash(copy));
        var tampered = Copy("tampered", "different copied bytes"); var tamperedHash = Hash(tampered);
        Assert.Throws<InvalidOperationException>(() => MaintenanceCommands.RebaseUploadedPaths(tampered, Data, tamperedHash));
        Assert.Equal(tamperedHash, Hash(tampered));
        Assert.Equal(upload, (string)Read(tampered).Settings["data_csv_path"]!);
        Assert.Equal(3, MaintenanceCommands.Run(["--rebase-upload-paths", Data, "--data-dir", tampered, "--expected-db-sha", tamperedHash]));
        var missing = Copy("missing-source-copy", File.ReadAllText(upload));
        File.Delete(upload); File.Delete(Path.Combine(missing, "sources", name));
        Assert.Equal(1, (int)MaintenanceCommands.RebaseUploadedPaths(missing, Data, Hash(missing))["rebased"]!);
        Assert.Equal(before.Records, Read(missing).Records); // missing CSVs never erase immutable imported records
    }

    [Fact]
    public async Task Inspection_checks_private_copies_and_leaves_source_files_unchanged()
    {
        // Quiesce this fixture's background retention/jobs before asserting an exact inventory.
        // The leased SQLite connection below still reproduces live WAL/SHM locking on Windows.
        await _app.StopAsync();
        // Other parallel host fixtures clear pooled SQLite connections on shutdown. Keep a leased,
        // non-pooled source connection alive so that their cleanup cannot checkpoint away our WAL/SHM.
        using var sourceConnection = new Microsoft.Data.Sqlite.SqliteConnection($"Data Source={Path.Combine(Data, ApplicationBackups.DatabaseEntry)};Pooling=False");
        sourceConnection.Open();
        using (var settings = sourceConnection.CreateCommand())
        {
            settings.CommandText = "INSERT OR REPLACE INTO Settings (Id,Revision,Json,UpdatedUtc,UpdatedBy) VALUES (1,1,$json,'2026-11-18','synthetic')";
            settings.Parameters.AddWithValue("$json", new JsonObject { ["data_csv_path"] = Path.Combine(_root, "external", "roles.csv") }.ToJsonString());
            settings.ExecuteNonQuery();
        }
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
        Assert.Contains("rebase-upload-paths-v1", inspection["capabilities"]!.AsArray().Select(c => (string)c!));
        Assert.Equal(Path.Combine(_root, "external", "roles.csv"), (string)inspection["source_paths"]!["data_csv_path"]!);
        Assert.Equal(files.Select(f => Path.GetRelativePath(Data, f)).Order(), Directory.GetFiles(Data, "*", SearchOption.AllDirectories).Select(f => Path.GetRelativePath(Data, f)).Order());
        foreach (var file in before.Keys) Assert.Equal(before[file], Hash(file));
        foreach (var file in shmBefore.Keys) Assert.Equal(shmBefore[file], File.GetLastWriteTimeUtc(file));
        Assert.Throws<InvalidOperationException>(() => MaintenanceCommands.InspectData(Path.Combine(_root, "missing")));
        Assert.False(Directory.Exists(Path.Combine(_root, "missing")));
        var bad = AuthLens.Application.Accounts.AccountStore.For(Data);
        Directory.CreateDirectory(Path.GetDirectoryName(bad)!);
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
