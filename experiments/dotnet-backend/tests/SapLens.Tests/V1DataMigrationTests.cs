using System.Net;
using System.Security.Cryptography;
using System.Text.Json.Nodes;
using Microsoft.AspNetCore.Builder;
using SapLens.Api;
using SapLens.Application.Backups;

namespace SapLens.Tests;

/// <summary>SAP Lens 1 to SAP Lens 2 data migration on a v1 data directory written by the real v1 application (Fixtures/v1-data, tools/v1_data_fixture.py):
/// dry run, approval, separate candidate with a verified migration backup, activation at the next start, the migrated data through the v1 routes, source
/// immutability, change detection, refusal to overwrite existing data, failed activation rollback, and rollback after activation.</summary>
public sealed class V1DataMigrationTests : IAsyncLifetime
{
    private static readonly string Fixture = Path.Combine(AppContext.BaseDirectory, "Fixtures", "v1-data");
    private static readonly JsonObject Expected = JsonNode.Parse(File.ReadAllText(Path.Combine(Fixture, "expected.json")))!.AsObject();
    private readonly string _root = Directory.CreateTempSubdirectory("saplens-v1migration-").FullName;
    private readonly string _token = HostSettings.NewToken();
    private WebApplication? _app;
    private HttpClient _client = null!;
    private string Source => Path.Combine(_root, "v1");
    private string Data => Path.Combine(_root, "v2");
    private static readonly DateTimeOffset Now = new(2026, 11, 17, 15, 0, 0, TimeSpan.Zero);

    public Task InitializeAsync()
    {
        foreach (var file in Directory.GetFiles(Path.Combine(Fixture, "data"), "*", SearchOption.AllDirectories))
        {
            var target = Path.Combine(Source, Path.GetRelativePath(Path.Combine(Fixture, "data"), file));
            Directory.CreateDirectory(Path.GetDirectoryName(target)!);
            File.Copy(file, target);
        }
        File.WriteAllText(Path.Combine(Source, "notes.txt"), "an unrelated file");
        Directory.CreateDirectory(Data);
        return Task.CompletedTask;
    }

    private async Task Start()
    {
        _app = SapLensHost.Build(new HostSettings { DataDirectory = Data, Port = 0, AccessToken = _token, JsonConsoleLogging = false, PrincipalName = "operator", Mode = HostMode.Desktop });
        await _app.StartAsync();
        _client = new HttpClient { BaseAddress = new Uri(_app.Urls.First()) };
        _client.DefaultRequestHeaders.Add(RequestBoundary.TokenHeader, _token);
        _client.DefaultRequestHeaders.Add("Origin", _client.BaseAddress.GetLeftPart(UriPartial.Authority));
    }

    private async Task Stop()
    {
        if (_app is null) return;
        _client.Dispose();
        await _app.StopAsync();
        await _app.DisposeAsync();
        _app = null;
        Microsoft.Data.Sqlite.SqliteConnection.ClearAllPools();
    }

    public async Task DisposeAsync()
    {
        await Stop();
        try { Directory.Delete(_root, true); } catch (IOException) { }
    }

    private Dictionary<string, string> Hashes(string root) => Directory.GetFiles(root, "*", SearchOption.AllDirectories)
        .ToDictionary(f => Path.GetRelativePath(root, f), f => Convert.ToHexStringLower(SHA256.HashData(File.ReadAllBytes(f))));

    private async Task<JsonNode> Get(string path) => JsonNode.Parse(await _client.GetStringAsync(path))!;

    private void HostKey()
    {
        Directory.CreateDirectory(Path.Combine(_root, "keys"));
        BackupKeys.Create(Path.Combine(_root, "keys", "host.key"), Data);
    }

    [Fact]
    public async Task Preview_run_activate_carries_v1_data_into_sap_lens_2_without_touching_the_source()
    {
        HostKey();
        var before = Hashes(Source);
        var preview = V1DataMigration.Preview(Source, Data, "", replaceExisting: false, Now);
        Assert.Equal("previewed", (string)preview["status"]!);
        Assert.Empty(preview["blockers"]!.AsArray());
        Assert.Contains(preview["warnings"]!.AsArray(), w => ((string)w!).Contains("notes.txt"));
        var stores = preview["stores"]!.AsArray().ToDictionary(s => (string)s!["store"]!, s => (int)s!["count"]!);
        Assert.Equal((2, 2, 2, 1), (stores["Source revisions (roles)"], stores["Source revisions (users)"], stores["Account review decisions"], stores["Saved filters"]));
        Assert.False(File.Exists(Path.Combine(Data, ApplicationBackups.DatabaseEntry)));                    // a dry run writes no database

        var id = (string)preview["id"]!;
        var digest = (string)preview["digest"]!;
        await Assert.ThrowsAsync<MigrationException>(() => V1DataMigration.RunAsync(Data, id, new string('0', 64), "admin", Now));   // approval required
        var report = await V1DataMigration.RunAsync(Data, id, digest, "admin", Now);
        Assert.Equal("verified", (string)report["status"]!);
        Assert.True((bool)report["backup"]!["encrypted"]!);
        Assert.Equal(3, (int)report["verification"]!["review_chain"]!);                                       // KARI: history + latest, OLA: latest
        Assert.False(File.Exists(Path.Combine(Data, ApplicationBackups.DatabaseEntry)));                    // still nothing active
        Assert.Throws<MigrationException>(() => V1DataMigration.RequestActivation(Data, id, new string('1', 64), "admin", Now));

        V1DataMigration.RequestActivation(Data, id, digest, "admin", Now);
        await Start();
        Assert.Equal("activated", (string)V1DataMigration.Status(Data, id)["status"]!);
        Assert.Equal(before, Hashes(Source));                                                                // the v1 directory was only read

        var users = (await Get("/api/access/users?show_expired=true"))["items"]!.AsArray().Select(i => (string)i!["username"]!).Order(StringComparer.Ordinal).ToList();
        Assert.Equal(Expected["users"]!.AsArray().Select(u => (string)u!).Order(StringComparer.Ordinal), users);
        Assert.Equal(["Økonomi brukere"], (await Get("/api/saved-filters"))["items"]!.AsArray().Select(i => (string)i!["name"]!));
        var review = (await Get("/api/account-review"))["items"]!.AsArray().ToDictionary(i => (string)i!["username"]!, i => i);
        Assert.Equal("No action required", (string)review["KARI"]!["decision"]!["state"]!);
        Assert.Equal("Investigating", (string)review["OLA"]!["decision"]!["state"]!);
        var expectedHistory = Expected["account_review"]!.AsObject().Select(p => (int)p.Value!["history"]!).Max();
        Assert.Equal(expectedHistory, (int)(await Get("/api/account-review/history/KARI"))["total"]!);       // earlier events, as in v1

        // The migration backup waits for the administrator's confirmation, like a schema-migration backup.
        var storage = await Get("/api/storage/status");
        Assert.True((bool)storage["requires_confirmation"]!);
        Assert.True(File.Exists(Path.Combine(Data, "backups", (string)report["backup"]!["file"]!)));
    }

    [Fact]
    public async Task Changed_sources_existing_data_and_a_damaged_candidate_are_refused_and_rollback_restores_the_previous_data()
    {
        // Existing SAP Lens 2 data is never replaced silently.
        await Start();
        Assert.Equal(HttpStatusCode.OK, (await _client.PostAsync("/api/saved-filters", System.Net.Http.Json.JsonContent.Create(new { name = "Existing v2 filter", view = "users", filters = new { search = "x" } }))).StatusCode);
        await Stop();
        var blocked = V1DataMigration.Preview(Source, Data, "", replaceExisting: false, Now);
        Assert.Equal("blocked", (string)blocked["status"]!);
        await Assert.ThrowsAsync<MigrationException>(() => V1DataMigration.RunAsync(Data, (string)blocked["id"]!, (string)blocked["digest"]!, "admin", Now));

        // A source changed after the preview is refused.
        var preview = V1DataMigration.Preview(Source, Data, "", replaceExisting: true, Now);
        Assert.Contains(preview["warnings"]!.AsArray(), w => ((string)w!).Contains("unencrypted"));
        File.AppendAllText(Path.Combine(Source, "notes.txt"), " changed");
        await Assert.ThrowsAsync<MigrationException>(() => V1DataMigration.RunAsync(Data, (string)preview["id"]!, (string)preview["digest"]!, "admin", Now));

        preview = V1DataMigration.Preview(Source, Data, "", replaceExisting: true, Now);
        var id = (string)preview["id"]!;
        var digest = (string)preview["digest"]!;
        await V1DataMigration.RunAsync(Data, id, digest, "admin", Now);

        // A candidate damaged after verification is not activated; the current data stays.
        V1DataMigration.RequestActivation(Data, id, digest, "admin", Now);
        var candidate = Path.Combine(Data, "migration", id, "candidate", ApplicationBackups.DatabaseEntry);
        var original = File.ReadAllBytes(candidate);
        File.AppendAllText(candidate, "x");
        await Start();
        Assert.Equal(["Existing v2 filter"], (await Get("/api/saved-filters"))["items"]!.AsArray().Select(i => (string)i!["name"]!));
        Assert.Contains("changed after verification", (string)V1DataMigration.Status(Data, id)["activation_error"]!);
        await Stop();

        File.WriteAllBytes(candidate, original);
        V1DataMigration.RequestActivation(Data, id, digest, "admin", Now);
        await Start();
        Assert.Equal(["Økonomi brukere"], (await Get("/api/saved-filters"))["items"]!.AsArray().Select(i => (string)i!["name"]!));
        await Stop();

        V1DataMigration.RequestRollback(Data, id, "admin", Now);
        await Start();
        Assert.Equal("rolled_back", (string)V1DataMigration.Status(Data, id)["status"]!);
        Assert.Equal(["Existing v2 filter"], (await Get("/api/saved-filters"))["items"]!.AsArray().Select(i => (string)i!["name"]!));
    }

    [Fact]
    public void A_v1_backup_archive_is_accepted_as_source()
    {
        // The v1 data directory as SAP Lens 1 archives it: a gzip tar with the data under data/.
        var archive = Path.Combine(_root, "v1-backup.tar.gz");
        using (var output = File.Create(archive))
        using (var gzip = new System.IO.Compression.GZipStream(output, System.IO.Compression.CompressionLevel.Fastest))
        using (var tar = new System.Formats.Tar.TarWriter(gzip))
            foreach (var file in Directory.GetFiles(Source, "*", SearchOption.AllDirectories))
                tar.WriteEntry(file, "data/" + Path.GetRelativePath(Source, file).Replace('\\', '/'));
        var preview = V1DataMigration.Preview(archive, Data, "", replaceExisting: false, Now);
        Assert.Equal(("previewed", "archive"), ((string)preview["status"]!, (string)preview["source"]!["kind"]!));
        Assert.Equal(2, preview["stores"]!.AsArray().First(s => (string)s!["store"]! == "Source revisions (users)")!["count"]!.GetValue<int>());
    }
}
