using System.Formats.Tar;
using System.IO.Compression;
using System.Net;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json.Nodes;
using Microsoft.AspNetCore.Builder;
using Microsoft.Data.Sqlite;
using AuthLens.Api;
using AuthLens.Application.Backups;

namespace AuthLens.Tests;

/// <summary>SAP Lens 1 to AuthLens data migration on a v1 installation written by the real v1 application and its backup engine (Fixtures/v1-data,
/// tools/v1_data_fixture.py): the data directory and the encrypted .slbak application backups of it (host key with the escrowed recovery key, and
/// passphrase), with SoD 2.0 decisions, remediation, an approved and a draft review period with frozen evidence, legacy reviews and Account Review
/// history. Every expectation about SoD comes from what v1 itself reported for that installation (expected.json).</summary>
public sealed class V1DataMigrationTests : IAsyncLifetime
{
    private static readonly string Fixture = Path.Combine(AppContext.BaseDirectory, "Fixtures", "v1-data");
    private static readonly JsonObject Expected = JsonNode.Parse(File.ReadAllText(Path.Combine(Fixture, "expected.json")))!.AsObject();
    private static readonly JsonObject Sod = Expected["sod"]!.AsObject();
    private readonly string _root = Directory.CreateTempSubdirectory("saplens-v1migration-").FullName;
    private readonly string _token = HostSettings.NewToken();
    private WebApplication? _app;
    private HttpClient _client = null!;
    private string Source => Path.Combine(_root, "v1");
    private string? _restoredData;
    private string Data => _restoredData ?? Path.Combine(_root, "v2");
    private static string RecoveryKey => (string)Expected["recovery_key"]!;
    private static string Passphrase => (string)Expected["passphrase"]!;
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
        _app = AuthLensHost.Build(new HostSettings { DataDirectory = Data, Port = 0, AccessToken = _token, JsonConsoleLogging = false, PrincipalName = "operator", Mode = HostMode.Desktop });
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
        SqliteConnection.ClearAllPools();
    }

    public async Task DisposeAsync()
    {
        await Stop();
        try { Directory.Delete(_root, true); } catch (IOException) { }
    }

    private static Dictionary<string, string> Hashes(string root) => Directory.GetFiles(root, "*", SearchOption.AllDirectories)
        .ToDictionary(f => Path.GetRelativePath(root, f), f => Convert.ToHexStringLower(SHA256.HashData(File.ReadAllBytes(f))));

    private async Task<JsonNode> Get(string path) => JsonNode.Parse(await _client.GetStringAsync(path))!;

    private void HostKey()
    {
        Directory.CreateDirectory(Path.Combine(_root, "keys"));
        BackupKeys.Create(Path.Combine(_root, "keys", "host.key"), Data);
    }

    private static Dictionary<string, int> Stores(JsonObject preview) => preview["stores"]!.AsArray().ToDictionary(s => (string)s!["store"]!, s => (int)s!["count"]!);

    /// <summary>Runs preview, run and activation for a source and starts AuthLens on the result.</summary>
    private async Task<(JsonObject Preview, JsonObject Report)> MigrateAsync(string source, string secret)
    {
        var preview = V1DataMigration.Preview(source, Data, secret, replaceExisting: false, Now);
        Assert.True((string)preview["status"]! == "previewed", preview["blockers"]!.ToJsonString());
        var report = await V1DataMigration.RunAsync(Data, (string)preview["id"]!, (string)preview["digest"]!, "admin", Now);
        Assert.Equal("verified", (string)report["status"]!);
        // The run holds no file of the migration folder open afterwards: Windows refuses to hash, move or delete a file another handle holds
        // (the candidate database was left open by a pooled connection; see V1DataMigration.CandidateDb).
        Assert.Empty(OpenFilesUnder(Path.Combine(Data, "migration")));
        V1DataMigration.RequestActivation(Data, (string)preview["id"]!, (string)preview["digest"]!, "admin", Now);
        await Start();
        Assert.Equal("activated", (string)V1DataMigration.Status(Data, (string)preview["id"]!)["status"]!);
        return (preview, report);
    }

    /// <summary>Files under <paramref name="folder"/> this process still has open. Linux lists every open descriptor in /proc/self/fd (SQLite keeps a
    /// descriptor per open connection, pooled or not), so a leaked handle is visible here although Linux itself would still allow the hash and move.
    /// Elsewhere the list is empty and the migration's own hash and move fail instead (as they did on Windows).</summary>
    private static List<string> OpenFilesUnder(string folder)
    {
        if (!Directory.Exists("/proc/self/fd")) return [];
        var prefix = Path.GetFullPath(folder) + Path.DirectorySeparatorChar;
        var open = new List<string>();
        foreach (var fd in Directory.GetFiles("/proc/self/fd"))
        {
            try { if (new FileInfo(fd).LinkTarget is { } target && target.StartsWith(prefix, StringComparison.Ordinal)) open.Add(target); }
            catch (IOException) { }               // a descriptor closed while listing
        }
        return open;
    }

    /// <summary>Everything the fixture's v1 installation holds, read back through the AuthLens routes.</summary>
    private async Task AssertMigratedAsync(JsonObject report)
    {
        var users = (await Get("/api/access/users?show_expired=true"))["items"]!.AsArray().Select(i => (string)i!["username"]!).Order(StringComparer.Ordinal).ToList();
        Assert.Equal(Expected["users"]!.AsArray().Select(u => (string)u!).Order(StringComparer.Ordinal), users);
        Assert.Equal(["Økonomi brukere"], (await Get("/api/saved-filters"))["items"]!.AsArray().Select(i => (string)i!["name"]!));
        // Current V1 decisions now retain completion and are hidden from the default pending queue.
        var review = (await Get("/api/account-review?include_completed=true"))["items"]!.AsArray().ToDictionary(i => (string)i!["username"]!, i => i);
        Assert.Equal("No action required", (string)review["KARI"]!["decision"]!["state"]!);
        Assert.False((bool)review["KARI"]!["stale"]!);
        Assert.Equal("completed", (string)review["KARI"]!["workflow_status"]!);
        Assert.Equal("Investigating", (string)review["OLA"]!["decision"]!["state"]!);
        Assert.Equal(1, (int)(await Get("/api/account-review/history/KARI"))["total"]!);

        // SoD 2.0 decision events: every v1 event, on a verified hash chain.
        Assert.Equal((int)Sod["events"]!, (int)report["verification"]!["sod_chain"]!);
        Assert.Equal(Expected["evidence_snapshots"]!.AsArray().Count, (int)report["verification"]!["evidence_snapshots"]!);
        using (var db = new SqliteConnection($"Data Source={Path.Combine(Data, ApplicationBackups.DatabaseEntry)};Mode=ReadOnly;Pooling=False"))
        {
            db.Open();
            using var command = db.CreateCommand();
            command.CommandText = "SELECT EventId FROM SodDecisionEvents ORDER BY EventId";
            var ids = new List<string>();
            using (var reader = command.ExecuteReader()) while (reader.Read()) ids.Add(reader.GetString(0));
            Assert.Equal(Sod["event_ids"]!.AsArray().Select(i => (string)i!), ids);
            command.CommandText = "SELECT Sha256 FROM SodEvidenceSnapshots ORDER BY Sha256";
            var evidence = new List<string>();
            using (var reader = command.ExecuteReader()) while (reader.Read()) evidence.Add(reader.GetString(0));
            Assert.Equal(Expected["evidence_snapshots"]!.AsArray().Select(i => (string)i!), evidence);
        }

        // The live context recomputed from the migrated sources and decisions equals v1's queue; remediation keeps its action and history.
        var queue = (await Get("/api/sod/queue?context=current&limit=100"))["counts"]!.AsObject();
        Assert.True(JsonNode.DeepEquals(Sod["queue_current"], queue), $"v1 {Sod["queue_current"]!.ToJsonString()}\nv2 {queue.ToJsonString()}");
        var remediation = await Get("/api/sod/remediation");
        var action = remediation["actions"]!.AsArray().Single()!;
        var expectedAction = Sod["actions"]!.AsObject().Single();
        Assert.Equal((expectedAction.Key, (string)expectedAction.Value!["status"]!, (int)expectedAction.Value["history"]!), ((string)action["id"]!, (string)action["status"]!, action["history"]!.AsArray().Count));
        Assert.Contains(remediation["items"]!.AsArray(), i => (string)i!["user"]! == "KARI" && (string)i["role"]! == "ZC:FI:ROLE_A2" && (string)i["action_status"]! == "In progress");

        // Review periods: states, frozen snapshots and transition history; the approved period still reads its frozen evidence.
        var periods = (await Get("/api/sod/periods"))["items"]!.AsArray().ToDictionary(p => (string)p!["id"]!, p => p!);
        foreach (var (id, value) in Sod["periods"]!.AsObject())
        {
            Assert.Equal(((string)value!["state"]!, (string)value["snapshot"]!), ((string)periods[id]["state"]!, (string)periods[id]["snapshot"]!));
            var details = await Get($"/api/sod/periods/{id}");
            Assert.Equal((int)value["history"]!, details["period"]!["history"]?.AsArray().Count ?? 0);
        }
        var approved = (string)Sod["approved"]!;
        var frozen = await Get($"/api/sod/matrix/risk?context={approved}");
        Assert.True((bool)frozen["frozen"]!);
        Assert.True(JsonNode.DeepEquals(Sod["matrix_approved"], frozen["totals"]), $"v1 {Sod["matrix_approved"]!.ToJsonString()}\nv2 {frozen["totals"]!.ToJsonString()}");

        // Legacy SoD 1.0 reviews with their history and the evidence of each event.
        var finding = (string)Sod["legacy_finding"]!;
        var history = await Get($"/api/sod/reviews/{finding}/history");
        Assert.Equal((int)Sod["legacy"]!["current"]![finding]!, (int)history["total"]!);
        foreach (var e in history["items"]!.AsArray())
            Assert.Equal(HttpStatusCode.OK, (await _client.GetAsync($"/api/sod/reviews/{finding}/history/{(string)e!["event_id"]!}/evidence")).StatusCode);
    }

    [Fact]
    public async Task A_v1_data_directory_migrates_completely_without_touching_the_source()
    {
        HostKey();
        var before = Hashes(Source);
        var preview = V1DataMigration.Preview(Source, Data, "", replaceExisting: false, Now);
        Assert.Contains(preview["warnings"]!.AsArray(), w => ((string)w!).Contains("notes.txt"));
        var stores = Stores(preview);
        Assert.Equal((2, 2, 2, 2, 1), (stores["Source revisions (roles)"], stores["Source revisions (users)"], stores["Source revisions (sod)"], stores["Account review decisions"], stores["Saved filters"]));
        Assert.Equal((int)Sod["events"]!, stores["SoD decision events, remediation actions, report log"]);
        Assert.False(File.Exists(Path.Combine(Data, ApplicationBackups.DatabaseEntry)));                    // a dry run writes no database
        await Assert.ThrowsAsync<MigrationException>(() => V1DataMigration.RunAsync(Data, (string)preview["id"]!, new string('0', 64), "admin", Now));
        Assert.Throws<MigrationException>(() => V1DataMigration.RequestActivation(Data, (string)preview["id"]!, (string)preview["digest"]!, "admin", Now));   // not run yet

        var (_, report) = await MigrateAsync(Source, "");
        Assert.True((bool)report["backup"]!["encrypted"]!);
        Assert.Equal(3, (int)report["verification"]!["review_chain"]!);
        Assert.Equal(before, Hashes(Source));                                                                // the v1 directory was only read
        await AssertMigratedAsync(report);
        Assert.True((bool)(await Get("/api/storage/status"))["requires_confirmation"]!);
    }

    [Fact]
    public async Task A_portable_backup_restores_migrated_review_history_and_frozen_SoD_evidence_into_fresh_canonical_storage()
    {
        HostKey();
        var (_, report) = await MigrateAsync(Source, "");
        await AssertMigratedAsync(report);
        await Stop();
        var original = Data;
        var archive = Path.Combine(_root, "portable.slbak");
        const string passphrase = "Synthetic portable review recovery 2026";
        ApplicationBackups.WriteArchive(original, archive, passphrase, null, "manual", Now);

        _restoredData = Path.Combine(_root, "fresh-authlens", "data");
        var destinationKeys = Path.Combine(_root, "fresh-authlens", "keys");
        Directory.CreateDirectory(destinationKeys);
        BackupKeys.Create(Path.Combine(destinationKeys, "host.key"), Data);
        MaintenanceCommands.RestoreArchive(Data, archive, replaceAll: true, passphrase);
        Assert.StartsWith("Restore ", ApplicationBackups.ApplyPending(Data, Now));
        Assert.True(File.Exists(Path.Combine(Data, "authlens.sqlite3")));
        Assert.False(File.Exists(Path.Combine(Data, "sap-lens-v2.sqlite3")));
        // Read the restored records through the same public routes and compare every fixture decision,
        // review history, remediation event, period state and content-addressed evidence snapshot again.
        await Start();
        await AssertMigratedAsync(report);
    }

    [Theory]
    [InlineData("v1-host.slbak", "recovery-key")]
    [InlineData("v1-passphrase.slbak", "passphrase")]
    public async Task An_encrypted_v1_backup_migrates_completely(string archive, string secretKind)
    {
        var source = Path.Combine(_root, archive);
        File.Copy(Path.Combine(Fixture, archive), source);
        var hash = Convert.ToHexStringLower(SHA256.HashData(File.ReadAllBytes(source)));
        using (var probe = File.OpenRead(source)) Assert.Equal(secretKind == "passphrase" ? "passphrase" : "host-key", BackupArchive.V1KeyMode(probe));
        var refused = Assert.Throws<MigrationException>(() => V1DataMigration.Preview(source, Data, secretKind == "passphrase" ? "Wrong synthetic passphrase" : Convert.ToBase64String(new byte[32]), false, Now));
        Assert.DoesNotContain(Passphrase, refused.Message);
        Assert.Empty(Directory.GetDirectories(Path.Combine(Data, "migration")).SelectMany(d => Directory.GetDirectories(d, "unpacked")));   // nothing unpacked on failure

        var (preview, report) = await MigrateAsync(source, secretKind == "passphrase" ? Passphrase : RecoveryKey);
        Assert.Equal("archive", (string)preview["source"]!["kind"]!);
        Assert.Equal("desktop", (string)preview["source"]!["archive"]!["mode"]!);
        Assert.False((bool)report["backup"]!["encrypted"]!);                                                 // no AuthLens host key configured in this test
        Assert.Equal(hash, Convert.ToHexStringLower(SHA256.HashData(File.ReadAllBytes(source))));           // the archive was only read
        await AssertMigratedAsync(report);
    }

    /// <summary>The plaintext tar.gz inside the host-key fixture archive, rebuilt with one change, to prove each v1 manifest check refuses it.</summary>
    private string Rebuilt(string name, Action<List<(string Name, byte[] Content)>> change)
    {
        byte[] plain;
        using (var input = File.OpenRead(Path.Combine(Fixture, "v1-host.slbak"))) plain = BackupArchive.UnsealV1(input, RecoveryKey, null);
        var entries = new List<(string Name, byte[] Content)>();
        using (var gzip = new GZipStream(new MemoryStream(plain), CompressionMode.Decompress))
        using (var reader = new TarReader(gzip))
            while (reader.GetNextEntry() is { } entry)
            {
                using var buffer = new MemoryStream();
                entry.DataStream?.CopyTo(buffer);
                entries.Add((entry.Name, buffer.ToArray()));
            }
        change(entries);
        var path = Path.Combine(_root, name);
        using (var output = File.Create(path))
        using (var gzip = new GZipStream(output, CompressionLevel.Fastest))
        using (var writer = new TarWriter(gzip, TarEntryFormat.Pax))
            foreach (var (entryName, content) in entries)
                writer.WriteEntry(new PaxTarEntry(TarEntryType.RegularFile, entryName) { DataStream = new MemoryStream(content) });
        return path;
    }

    [Fact]
    public void A_v1_backup_is_checked_against_its_manifest_like_v1_maintenance_verify()
    {
        // Unchanged content repacked as a legacy .tar.gz is accepted.
        var intact = V1DataMigration.Preview(Rebuilt("intact.tar.gz", _ => { }), Data, "", false, Now);
        Assert.Equal("previewed", (string)intact["status"]!);

        void Refused(string name, Action<List<(string Name, byte[] Content)>> change, string message)
        {
            var error = Assert.Throws<MigrationException>(() => V1DataMigration.Preview(Rebuilt(name, change), Data, "", false, Now));
            Assert.Contains(message, error.Message);
        }
        Refused("altered.tar.gz", e => { var i = e.FindIndex(x => x.Name == "data/sod-decisions.json"); e[i] = (e[i].Name, Encoding.UTF8.GetBytes("{}")); }, "checksum");
        Refused("extra.tar.gz", e => e.Add(("data/extra.json", "{}"u8.ToArray())), "unexpected or missing");
        Refused("missing.tar.gz", e => e.RemoveAll(x => x.Name == "data/sod-periods.json"), "unexpected or missing");
        Refused("unsafe.tar.gz", e => e.Add(("data/../escape.json", "{}"u8.ToArray())), "unsafe member");
        Refused("reserved.tar.gz", e => e.Add(("data/CON.json", "{}"u8.ToArray())), "non-portable");
        Refused("nomanifest.tar.gz", e => e.RemoveAll(x => x.Name == "manifest.json"), "manifest");
        Refused("case.tar.gz", e => e.Add(("data/Settings.json", "{}"u8.ToArray())), "duplicate");

        // A damaged encrypted archive fails authentication before anything is unpacked.
        var damaged = Path.Combine(_root, "damaged.slbak");
        var bytes = File.ReadAllBytes(Path.Combine(Fixture, "v1-host.slbak"));
        bytes[^40] ^= 1;
        File.WriteAllBytes(damaged, bytes);
        Assert.Contains("authentication failed", Assert.Throws<MigrationException>(() => V1DataMigration.Preview(damaged, Data, RecoveryKey, false, Now)).Message);
    }

    [Fact]
    public async Task Changed_sources_existing_data_and_a_damaged_candidate_are_refused_and_rollback_restores_the_previous_data()
    {
        // Existing AuthLens data is never replaced silently.
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
        Assert.Empty(OpenFilesUnder(Path.Combine(Data, "migration")));

        // A v1 change after the run (for example a new decision) is refused at activation, so nothing made in v1 meanwhile is lost.
        var settings = Path.Combine(Source, "saved-filters.json");
        var original = File.ReadAllBytes(settings);
        File.AppendAllText(settings, " ");
        Assert.Contains("changed after the migration ran", Assert.Throws<MigrationException>(() => V1DataMigration.RequestActivation(Data, id, digest, "admin", Now)).Message);
        File.WriteAllBytes(settings, original);

        // A candidate damaged after verification is not activated; the current data stays.
        V1DataMigration.RequestActivation(Data, id, digest, "admin", Now);
        var candidate = Path.Combine(Data, "migration", id, "candidate", ApplicationBackups.DatabaseEntry);
        var candidateBytes = File.ReadAllBytes(candidate);
        File.AppendAllText(candidate, "x");
        await Start();
        Assert.Equal(["Existing v2 filter"], (await Get("/api/saved-filters"))["items"]!.AsArray().Select(i => (string)i!["name"]!));
        Assert.Contains("changed after verification", (string)V1DataMigration.Status(Data, id)["activation_error"]!);
        await Stop();

        File.WriteAllBytes(candidate, candidateBytes);
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
    public async Task A_large_revision_is_imported_in_batches_and_verified_record_by_record()
    {
        // Replace the active users revision with 12,345 records (more than two 5,000-record batches), content-addressed like v1.
        var settingsPath = Path.Combine(Source, "settings.json");
        var settings = JsonNode.Parse(File.ReadAllText(settingsPath))!.AsObject();
        var active = (string)settings["data_lifecycle"]!["sources"]!["users"]!["snapshot"]!;
        var snapshot = JsonNode.Parse(File.ReadAllText(Path.Combine(Source, "csv-data", "snapshots", active + ".json")))!.AsObject();
        var template = snapshot["records"]![0]!.AsObject();
        var records = new JsonArray();
        for (var i = 0; i < 12_345; i++)
        {
            var record = template.DeepClone().AsObject();
            record["USERNAME"] = $"SYNTH{i:D6}";
            record["LAST_NAME"] = i % 2 == 0 ? "Ødegård" : "Nordmann";
            records.Add(record);
        }
        snapshot["records"] = records;
        var bytes = Encoding.UTF8.GetBytes(snapshot.ToJsonString());
        var id = Convert.ToHexStringLower(SHA256.HashData(bytes));
        File.WriteAllBytes(Path.Combine(Source, "csv-data", "snapshots", id + ".json"), bytes);
        settings["data_lifecycle"]!["sources"]!["users"]!["snapshot"] = id;
        File.WriteAllText(settingsPath, settings.ToJsonString());

        var preview = V1DataMigration.Preview(Source, Data, "", replaceExisting: false, Now);
        var report = await V1DataMigration.RunAsync(Data, (string)preview["id"]!, (string)preview["digest"]!, "admin", Now);
        Assert.Equal("verified", (string)report["status"]!);
        // The run holds no file of the migration folder open afterwards: Windows refuses to hash, move or delete a file another handle holds
        // (the candidate database was left open by a pooled connection; see V1DataMigration.CandidateDb).
        Assert.Empty(OpenFilesUnder(Path.Combine(Data, "migration")));
        V1DataMigration.RequestActivation(Data, (string)preview["id"]!, (string)preview["digest"]!, "admin", Now);
        await Start();
        var page = await Get("/api/access/users?show_expired=true&search=SYNTH01234");
        Assert.Equal(["SYNTH012340", "SYNTH012341", "SYNTH012342", "SYNTH012343", "SYNTH012344"], page["items"]!.AsArray().Select(u => (string)u!["username"]!).Take(5));
        Assert.Equal(12_345, (int)(await Get("/api/access/users?show_expired=true&search=SYNTH&limit=1"))["total"]!);
    }
}
