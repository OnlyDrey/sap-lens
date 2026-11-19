using System.IO.Compression;
using System.Net.Http.Json;
using System.Text.Json.Nodes;
using AuthLens.Api;
using AuthLens.Application.Backups;
using AuthLens.Persistence;
using Microsoft.AspNetCore.Builder;
using Microsoft.Data.Sqlite;

namespace AuthLens.Tests;

/// <summary>AuthLens acceptance for the database name and SAP Lens backups: a new installation uses authlens.sqlite3; a SAP Lens data directory is
/// never opened implicitly and is converted only explicitly; a SAP Lens .slbak backup restores into a clean AuthLens installation on another
/// machine (no access to the original paths) and fails safely with a wrong key, a corrupted archive, an incompatible schema or an interrupted
/// activation. Synthetic data only.</summary>
public sealed class LegacyRestoreTests : IAsyncLifetime
{
    private readonly string _root = Directory.CreateTempSubdirectory("authlens-legacy-").FullName;
    private readonly string _token = HostSettings.NewToken();

    public Task InitializeAsync() => Task.CompletedTask;
    public Task DisposeAsync() { SqliteConnection.ClearAllPools(); try { Directory.Delete(_root, true); } catch (IOException) { } return Task.CompletedTask; }

    private async Task<T> WithHost<T>(string data, Func<HttpClient, Task<T>> body)
    {
        var app = AuthLensHost.Build(new HostSettings { DataDirectory = data, Port = 0, AccessToken = _token, JsonConsoleLogging = false, PrincipalName = "operator", Mode = HostMode.Desktop });
        await app.StartAsync();
        try
        {
            using var client = new HttpClient { BaseAddress = new Uri(app.Urls.First()) };
            client.DefaultRequestHeaders.Add(RequestBoundary.TokenHeader, _token);
            client.DefaultRequestHeaders.Add("Origin", client.BaseAddress.GetLeftPart(UriPartial.Authority));
            return await body(client);
        }
        finally { await app.StopAsync(); await app.DisposeAsync(); SqliteConnection.ClearAllPools(); }
    }

    private static async Task<string[]> Filters(HttpClient client) =>
        [.. JsonNode.Parse(await client.GetStringAsync("/api/saved-filters"))!["items"]!.AsArray().Select(i => (string)i!["name"]!).Order(StringComparer.Ordinal)];

    /// <summary>Migration history and the row count of every table: what a restore must reproduce exactly.</summary>
    private static JsonObject Shape(string database)
    {
        using var c = new SqliteConnection(new SqliteConnectionStringBuilder { DataSource = database, Mode = SqliteOpenMode.ReadOnly, Pooling = false }.ToString());
        c.Open();
        List<string> Strings(string sql) { using var cmd = c.CreateCommand(); cmd.CommandText = sql; using var r = cmd.ExecuteReader(); var l = new List<string>(); while (r.Read()) l.Add(r.GetString(0)); return l; }
        var tables = new JsonObject();
        foreach (var table in Strings("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"))
        {
            using var cmd = c.CreateCommand(); cmd.CommandText = $"SELECT COUNT(*) FROM \"{table}\""; tables[table] = Convert.ToInt64(cmd.ExecuteScalar());
        }
        return new JsonObject { ["migrations"] = new JsonArray([.. Strings("SELECT MigrationId FROM __EFMigrationsHistory ORDER BY 1").Select(m => (JsonNode)m)]), ["tables"] = tables };
    }

    /// <summary>A SAP Lens installation with a host key and three saved filters; returns its data directory, key file and an archive of it.</summary>
    private async Task<(string Data, string Key, string Archive)> SourceInstallation(string name)
    {
        var data = Path.Combine(_root, name, "data"); var key = Path.Combine(_root, name, "keys", "host.key");
        Directory.CreateDirectory(Path.GetDirectoryName(key)!);
        await WithHost(data, async client =>
        {
            BackupKeys.Create(key, data);
            foreach (var filter in new[] { "Finance", "Purchasing", "Æøå review" })
                Assert.True((await client.PostAsJsonAsync("/api/saved-filters", new { name = filter, view = "users", filters = new { search = filter } })).IsSuccessStatusCode);
            return 0;
        });
        var archive = Path.Combine(_root, name, "source.slbak");
        ApplicationBackups.WriteArchive(data, archive, "", BackupKeys.Host(data)!, "manual", DateTimeOffset.UtcNow);
        return (data, key, archive);
    }

    /// <summary>The same archive as SAP Lens wrote it: the database entry sap-lens-v2.sqlite3 and the manifest product "SAP Lens 2" (the only
    /// differences of the SAP Lens format), sealed with the same host key.</summary>
    private static byte[] AsSapLensArchive(string archive, byte[] host, string product = "SAP Lens 2", Action<string>? changeDatabase = null)
    {
        using var plain = new MemoryStream();
        using (var input = File.OpenRead(archive)) BackupArchive.Unseal(input, plain, "", host);
        using (var zip = new ZipArchive(plain, ZipArchiveMode.Update, leaveOpen: true))
        {
            var database = zip.GetEntry(ApplicationBackups.DatabaseEntry)!;
            var scratch = Path.GetTempFileName();
            using (var s = database.Open()) using (var f = File.Create(scratch)) s.CopyTo(f);
            changeDatabase?.Invoke(scratch);
            database.Delete();
            using (var s = zip.CreateEntry(ApplicationBackups.LegacyDatabaseEntry).Open()) using (var f = File.OpenRead(scratch)) f.CopyTo(s);
            var manifestEntry = zip.GetEntry(ApplicationBackups.ManifestEntry)!;
            JsonObject manifest;
            using (var reader = new StreamReader(manifestEntry.Open())) manifest = JsonNode.Parse(reader.ReadToEnd())!.AsObject();
            manifestEntry.Delete();
            manifest["product"] = product;
            foreach (var file in manifest["files"]!.AsArray().OfType<JsonObject>().Where(f => (string)f["path"]! == ApplicationBackups.DatabaseEntry))
            {
                file["path"] = ApplicationBackups.LegacyDatabaseEntry;
                file["sha256"] = Convert.ToHexStringLower(System.Security.Cryptography.SHA256.HashData(File.ReadAllBytes(scratch)));
                file["bytes"] = new FileInfo(scratch).Length;
            }
            using var writer = new StreamWriter(zip.CreateEntry(ApplicationBackups.ManifestEntry).Open());
            writer.Write(manifest.ToJsonString());
            File.Delete(scratch);
        }
        plain.Position = 0;
        using var sealedArchive = new MemoryStream();
        BackupArchive.Seal(plain, sealedArchive, "", host);
        return sealedArchive.ToArray();
    }

    [Fact]
    public async Task A_new_installation_uses_authlens_sqlite3_and_never_creates_the_SAP_Lens_file()
    {
        var data = Path.Combine(_root, "fresh");
        await WithHost(data, async client => { Assert.Empty(await Filters(client)); return 0; });
        Assert.True(File.Exists(Path.Combine(data, "authlens.sqlite3")));
        Assert.False(File.Exists(Path.Combine(data, "sap-lens-v2.sqlite3")));
        Assert.Equal("authlens.sqlite3", Path.GetFileName(new DatabaseOptions { DataDirectory = data }.DatabasePath));
    }

    [Fact]
    public async Task A_SAP_Lens_data_directory_is_refused_until_it_is_converted_explicitly_and_then_keeps_its_data()
    {
        var (data, _, _) = await SourceInstallation("sap-lens");
        File.Move(Path.Combine(data, "authlens.sqlite3"), Path.Combine(data, "sap-lens-v2.sqlite3"));   // the data directory as SAP Lens left it
        var before = Shape(Path.Combine(data, "sap-lens-v2.sqlite3"));
        var refusal = Assert.Throws<InvalidOperationException>(() => AuthLensHost.Build(new HostSettings { DataDirectory = data, Port = 0, AccessToken = _token, Mode = HostMode.Desktop }));
        Assert.Contains("--adopt-legacy-database", refusal.Message);
        Assert.False(File.Exists(Path.Combine(data, "authlens.sqlite3")));                                  // no empty replacement database

        // Refused while anything holds the SAP Lens database; nothing is created.
        using (var holder = new SqliteConnection($"Data Source={Path.Combine(data, "sap-lens-v2.sqlite3")};Pooling=False"))
        {
            holder.Open();
            using var read = holder.BeginTransaction();
            using (var cmd = holder.CreateCommand()) { cmd.Transaction = read; cmd.CommandText = "SELECT COUNT(*) FROM __EFMigrationsHistory"; cmd.ExecuteScalar(); }
            Assert.Contains("in use", Assert.Throws<InvalidOperationException>(() => MaintenanceCommands.AdoptLegacyDatabase(data)).Message);
        }
        Assert.False(File.Exists(Path.Combine(data, "authlens.sqlite3")));
        Assert.False(File.Exists(Path.Combine(data, "authlens.sqlite3.adopting")));

        var adopted = MaintenanceCommands.AdoptLegacyDatabase(data);
        Assert.True((bool)adopted["adopted"]!);
        Assert.True(File.Exists(Path.Combine(data, "sap-lens-v2.sqlite3")));                                // kept
        Assert.True(JsonNode.DeepEquals(before, Shape(Path.Combine(data, "authlens.sqlite3"))));
        Assert.Equal(["Finance", "Purchasing", "Æøå review"], await WithHost(data, Filters));
        Assert.Contains("already exists", Assert.Throws<InvalidOperationException>(() => MaintenanceCommands.AdoptLegacyDatabase(data)).Message);
    }

    [Fact]
    public async Task A_SAP_Lens_backup_restores_into_a_clean_AuthLens_installation_on_another_machine()
    {
        var (sourceData, sourceKey, archive) = await SourceInstallation("old-machine");
        var host = BackupKeys.Host(sourceData)!;
        var legacy = AsSapLensArchive(archive, host);
        var expected = Shape(Path.Combine(sourceData, "authlens.sqlite3"));
        // The new machine receives only the backup and the recovery key; the original installation is gone.
        var machine = Path.Combine(_root, "new-machine"); Directory.CreateDirectory(Path.Combine(machine, "keys"));
        File.WriteAllBytes(Path.Combine(machine, "SAP-Lens-manual.slbak"), legacy);
        File.Copy(sourceKey, Path.Combine(machine, "keys", "recovery.key"));
        Directory.Delete(Path.Combine(_root, "old-machine"), true);
        var data = Path.Combine(machine, "AuthLens", "data");
        Directory.CreateDirectory(data);
        BackupKeys.Use(Path.Combine(machine, "keys", "recovery.key"), data);

        var restore = MaintenanceCommands.RestoreArchive(data, Path.Combine(machine, "SAP-Lens-manual.slbak"), replaceAll: true, passphrase: "");
        Assert.Equal("SAP Lens", (string)restore["staged"]!["preview"]!["source_mode"]!);
        Assert.Equal("SAP Lens 2", (string)restore["staged"]!["preview"]!["source_product"]!);
        Assert.Equal("waiting_for_restart", (string)restore["status"]!["status"]!);
        Assert.False(File.Exists(Path.Combine(data, "authlens.sqlite3")));                                  // nothing is active before the start

        Assert.StartsWith("Restore ", ApplicationBackups.ApplyPending(data, DateTimeOffset.UtcNow));
        Assert.True(JsonNode.DeepEquals(expected, Shape(Path.Combine(data, "authlens.sqlite3"))), Shape(Path.Combine(data, "authlens.sqlite3")).ToJsonString());
        Assert.False(File.Exists(Path.Combine(data, "sap-lens-v2.sqlite3")));
        Assert.Equal(["Finance", "Purchasing", "Æøå review"], await WithHost(data, Filters));
        Assert.Contains("--replace-all-data", Assert.Throws<InvalidOperationException>(() => MaintenanceCommands.RestoreArchive(data, Path.Combine(machine, "SAP-Lens-manual.slbak"), false, "")).Message);
    }

    [Fact]
    public async Task A_restore_fails_safely_without_the_right_key_with_a_corrupted_archive_or_an_incompatible_schema()
    {
        var (sourceData, _, archive) = await SourceInstallation("source");
        var host = BackupKeys.Host(sourceData)!;
        var data = Path.Combine(_root, "target", "data"); Directory.CreateDirectory(data);
        string Write(string name, byte[] bytes) { var path = Path.Combine(_root, "target", name); File.WriteAllBytes(path, bytes); return path; }
        void Refused(string archivePath)
        {
            Assert.ThrowsAny<Exception>(() => MaintenanceCommands.RestoreArchive(data, archivePath, true, ""));
            Assert.False(File.Exists(Path.Combine(data, "authlens.sqlite3")));
            Assert.False(File.Exists(Path.Combine(data, "restore", "pending.json")));
            Assert.Null(ApplicationBackups.ApplyPending(data, DateTimeOffset.UtcNow));
        }
        var legacy = Write("legacy.slbak", AsSapLensArchive(archive, host));

        Refused(legacy);                                                                                   // no key configured
        BackupKeys.Create(Path.Combine(_root, "target", "other.key"), data);
        Refused(legacy);                                                                                   // another key
        var corrupted = AsSapLensArchive(archive, host); corrupted[corrupted.Length / 2] ^= 0x5A;
        Refused(Write("corrupted.slbak", corrupted));                                                      // authenticated encryption fails
        var newer = Write("newer.slbak", AsSapLensArchive(archive, host, changeDatabase: db =>
        {
            using var c = new SqliteConnection($"Data Source={db};Pooling=False"); c.Open();
            using var cmd = c.CreateCommand(); cmd.CommandText = "INSERT INTO __EFMigrationsHistory VALUES ('29991231000000_FromTheFuture', '99.0.0')"; cmd.ExecuteNonQuery();
        }));
        File.Delete(Path.Combine(data, "backup-key-location.json"));
        BackupKeys.Use(Path.Combine(_root, "source", "keys", "host.key"), data);
        var error = Assert.Throws<BackupException>(() => MaintenanceCommands.RestoreArchive(data, newer, true, ""));
        Assert.Contains("newer", error.Message);                                                           // incompatible schema
        Refused(newer);
        Refused(Write("unknown.slbak", AsSapLensArchive(archive, host, product: "Another product")));      // unknown product with the SAP Lens entry
        Assert.Equal("waiting_for_restart", (string)MaintenanceCommands.RestoreArchive(data, legacy, true, "")["status"]!["status"]!);   // the right archive and key
    }

    [Fact]
    public async Task An_interrupted_activation_never_leaves_partial_data_active()
    {
        var (sourceData, sourceKey, archive) = await SourceInstallation("source");
        var legacy = Path.Combine(_root, "legacy.slbak"); File.WriteAllBytes(legacy, AsSapLensArchive(archive, BackupKeys.Host(sourceData)!));
        // A clean installation: the staged database is damaged after confirmation, before the start applies it.
        var data = Path.Combine(_root, "clean", "data"); Directory.CreateDirectory(data);
        BackupKeys.Use(sourceKey, data);
        var id = (string)MaintenanceCommands.RestoreArchive(data, legacy, true, "")["staged"]!["id"]!;
        File.AppendAllText(Path.Combine(data, "restore", id, "staged", "authlens.sqlite3"), "damaged");
        Assert.Contains("rolled back", ApplicationBackups.ApplyPending(data, DateTimeOffset.UtcNow) ?? "");
        Assert.False(File.Exists(Path.Combine(data, "authlens.sqlite3")));
        Assert.False(File.Exists(Path.Combine(data, "restore", "pending.json")));
        // An installation with data keeps it unchanged.
        var current = Shape(Path.Combine(sourceData, "authlens.sqlite3"));
        id = (string)MaintenanceCommands.RestoreArchive(sourceData, legacy, true, "")["staged"]!["id"]!;
        File.AppendAllText(Path.Combine(sourceData, "restore", id, "staged", "authlens.sqlite3"), "damaged");
        Assert.Contains("rolled back", ApplicationBackups.ApplyPending(sourceData, DateTimeOffset.UtcNow) ?? "");
        Assert.True(JsonNode.DeepEquals(current, Shape(Path.Combine(sourceData, "authlens.sqlite3"))));
        Assert.Equal(["Finance", "Purchasing", "Æøå review"], await WithHost(sourceData, Filters));
    }
}
