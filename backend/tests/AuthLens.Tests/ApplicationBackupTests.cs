using System.Net;
using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Security.Cryptography;
using System.Text.Json.Nodes;
using Microsoft.AspNetCore.Builder;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;
using AuthLens.Api;
using AuthLens.Application.Backups;
using AuthLens.Persistence;

namespace AuthLens.Tests;

/// <summary>Application backups and restore through the v1 routes: the host key and escrow, verified encrypted archives, history, download and delete,
/// the schedule, staged restore with validation, the restart handoff with a destination recovery backup, rollback, and the Server account boundary.</summary>
public sealed class ApplicationBackupTests : IAsyncLifetime
{
    private readonly string _root = Directory.CreateTempSubdirectory("saplens-backups-").FullName;
    private readonly string _token = HostSettings.NewToken();
    private WebApplication _app = null!;
    private HttpClient _client = null!;
    private string Data => Path.Combine(_root, "data");
    private string KeyFile => Path.Combine(_root, "keys", "host.key");

    public Task InitializeAsync() => Start();

    private async Task Start(HostMode mode = HostMode.Desktop, AuthenticationMode auth = AuthenticationMode.SharedToken)
    {
        _app = AuthLensHost.Build(new HostSettings { DataDirectory = Data, Port = 0, AccessToken = _token, JsonConsoleLogging = false, PrincipalName = "operator", Mode = mode, Authentication = auth });
        await _app.StartAsync();
        _client = new HttpClient { BaseAddress = new Uri(_app.Urls.First()) };
        _client.DefaultRequestHeaders.Add(RequestBoundary.TokenHeader, _token);
        _client.DefaultRequestHeaders.Add("Origin", _client.BaseAddress.GetLeftPart(UriPartial.Authority));
    }

    private async Task Stop()
    {
        _client.Dispose();
        await _app.StopAsync();
        await _app.DisposeAsync();
        Microsoft.Data.Sqlite.SqliteConnection.ClearAllPools();
    }

    public async Task DisposeAsync()
    {
        await Stop();
        try { Directory.Delete(_root, true); } catch (IOException) { }
    }

    private async Task<(HttpStatusCode Status, JsonNode? Body)> Post(string path, object? body = null)
    {
        var response = body is null ? await _client.PostAsync(path, null) : await _client.PostAsJsonAsync(path, body);
        var text = await response.Content.ReadAsStringAsync();
        return (response.StatusCode, text.Length > 0 ? JsonNode.Parse(text) : null);
    }

    private async Task<JsonNode> Get(string path) => JsonNode.Parse(await _client.GetStringAsync(path))!;

    private async Task<(HttpStatusCode Status, JsonNode? Body)> Upload(byte[] archive, string secret = "", string type = "application/octet-stream")
    {
        var content = new ByteArrayContent(archive);
        content.Headers.ContentType = new MediaTypeHeaderValue(type);
        var request = new HttpRequestMessage(HttpMethod.Post, "/api/backups/upload") { Content = content };
        if (secret.Length > 0) request.Headers.Add("X-SAP-Lens-Backup-Secret", Convert.ToBase64String(System.Text.Encoding.UTF8.GetBytes(secret)));
        var response = await _client.SendAsync(request);
        return (response.StatusCode, JsonNode.Parse(await response.Content.ReadAsStringAsync()));
    }

    private void ConfigureKey()
    {
        Directory.CreateDirectory(Path.GetDirectoryName(KeyFile)!);
        BackupKeys.Create(KeyFile, Data);
    }

    private async Task<int> SavedFilters() => (await Get("/api/saved-filters"))["items"]!.AsArray().Count;
    private Task<(HttpStatusCode, JsonNode?)> SaveFilter(string name) => Post("/api/saved-filters", new { name, view = "users", filters = new { search = name } });

    [Fact]
    public async Task Backups_need_a_host_key_and_are_verified_encrypted_listed_downloaded_and_deleted_on_confirmation()
    {
        var status = await Get("/api/backups");
        Assert.Equal("idle", (string)status["status"]!);
        Assert.False((bool)status["key_provider"]!["configured"]!);
        Assert.Equal(HttpStatusCode.Conflict, (await Post("/api/backups/create")).Status);

        ConfigureKey();
        Assert.Equal(HttpStatusCode.Conflict, (await Post("/api/backups/create", new { passphrase = "short" })).Status);
        Assert.Equal(HttpStatusCode.UnprocessableEntity, (await Post("/api/backups/create", new { passphrase = "", extra = 1 })).Status);
        var (code, created) = await Post("/api/backups/create");
        Assert.Equal(HttpStatusCode.OK, code);
        Assert.Equal(("ready", "backup"), ((string)created!["status"]!, (string)created["kind"]!));
        var id = (string)created["id"]!;
        Assert.Matches("^[a-f0-9]{32}$", id);

        var history = await Get("/api/backups/history");
        Assert.Equal(1, (int)history["total"]!);
        Assert.Equal(("manual", "ready", true), ((string)history["items"]![0]!["origin"]!, (string)history["items"]![0]!["status"]!, (bool)history["items"]![0]!["verified"]!));

        var download = await _client.GetAsync($"/api/backups/{id}/download?kind=backup");
        Assert.Equal(HttpStatusCode.OK, download.StatusCode);
        Assert.Equal($"AuthLens-backup-{id}.slbak", download.Content.Headers.ContentDisposition!.FileName!.Trim('"'));
        var bytes = await download.Content.ReadAsByteArrayAsync();
        Assert.Equal((string)created["archive_sha256"]!, Convert.ToHexStringLower(SHA256.HashData(bytes)));
        var downloadedFile = Path.Combine(_root, "downloaded.slbak");
        File.WriteAllBytes(downloadedFile, bytes);
        var independentlyVerified = MaintenanceCommands.BackupVerify(Data, downloadedFile);
        Assert.True((bool)independentlyVerified["verified"]!);
        Assert.Equal((string)created["archive_sha256"]!, (string)independentlyVerified["sha256"]!);
        Assert.True(BackupArchive.IsV2(bytes));
        var (checkedStatus, checkedArchive) = await Post($"/api/backups/{id}/verify");
        Assert.Equal(HttpStatusCode.OK, checkedStatus); Assert.True((bool)checkedArchive!["verified"]!);
        Assert.Equal((string)created["archive_sha256"]!, (string)checkedArchive["sha256"]!);
        // The archive holds the database and account-free payload sealed with the host key; the plaintext is a zip with a manifest.
        using (var plain = new MemoryStream())
        {
            BackupArchive.Unseal(new MemoryStream(bytes), plain, "", BackupKeys.Host(Data));
            plain.Position = 0;
            using var zip = new System.IO.Compression.ZipArchive(plain);
            Assert.Contains(zip.Entries, e => e.FullName == ApplicationBackups.DatabaseEntry);
            Assert.Contains(zip.Entries, e => e.FullName == ApplicationBackups.ManifestEntry);
        }
        Assert.Equal(HttpStatusCode.NotFound, (await _client.GetAsync($"/api/backups/{id}/download?kind=other")).StatusCode);
        Assert.Equal(HttpStatusCode.NotFound, (await _client.GetAsync($"/api/backups/{new string('0', 32)}/download")).StatusCode);

        // An altered archive is not offered for download.
        var file = Path.Combine(Data, "backups", ApplicationBackups.ArchiveName(id));
        var original = File.ReadAllBytes(file);
        var altered = (byte[])original.Clone();
        altered[^1] ^= 1;
        File.WriteAllBytes(file, altered);
        Assert.Equal(HttpStatusCode.Conflict, (await _client.GetAsync($"/api/backups/{id}/download")).StatusCode);
        var alteredHistory = (await Get("/api/backups/history"))["items"]![0]!;
        Assert.Equal("failed", (string)alteredHistory["status"]!);
        Assert.False((bool)alteredHistory["verified"]!);
        File.WriteAllBytes(file, original);

        Assert.Equal(HttpStatusCode.UnprocessableEntity, (await Post($"/api/backups/{id}/delete", new { confirm = false })).Status);
        var (deleted, after) = await Post($"/api/backups/{id}/delete", new { confirm = true });
        Assert.Equal(HttpStatusCode.OK, deleted);
        Assert.Equal(0, (int)after!["total"]!);
        Assert.False(File.Exists(file));
        Assert.Equal(HttpStatusCode.Conflict, (await Post($"/api/backups/{id}/delete", new { confirm = true })).Status);
    }

    [Fact]
    public async Task Restore_is_validated_staged_and_applied_at_restart_with_a_destination_recovery_backup()
    {
        ConfigureKey();
        Assert.Equal(HttpStatusCode.OK, (await SaveFilter("Before backup")).Item1);
        var (_, created) = await Post("/api/backups/create", new { passphrase = "Synthetic restore passphrase" });
        var id = (string)created!["id"]!;
        var archive = await _client.GetByteArrayAsync($"/api/backups/{id}/download");
        Assert.Equal(HttpStatusCode.OK, (await SaveFilter("After backup")).Item1);
        Assert.Equal(2, await SavedFilters());

        // Refusals: content type, an empty or foreign file, a SAP Lens 1 archive, a wrong passphrase, tampering. None changes data.
        Assert.Equal(HttpStatusCode.UnsupportedMediaType, (await Upload(archive, type: "application/json")).Status);
        Assert.Equal(HttpStatusCode.UnprocessableEntity, (await Upload("not an archive"u8.ToArray())).Status);
        var v1 = File.ReadAllBytes(Path.Combine(AppContext.BaseDirectory, "Fixtures", "backups", "v1-passphrase.slbak"));
        var (v1Status, v1Body) = await Upload(v1, "Synthetic v1 backup passphrase");
        Assert.Equal(HttpStatusCode.UnprocessableEntity, v1Status);
        Assert.Contains("migration", (string)v1Body!["detail"]!);
        Assert.Equal(HttpStatusCode.UnprocessableEntity, (await Upload(archive, "Wrong restore passphrase")).Status);
        var tampered = (byte[])archive.Clone();
        tampered[^20] ^= 1;
        Assert.Equal(HttpStatusCode.UnprocessableEntity, (await Upload(tampered, "Synthetic restore passphrase")).Status);
        Assert.Empty(Directory.Exists(Path.Combine(Data, "restore")) ? Directory.GetDirectories(Path.Combine(Data, "restore")) : []);

        var (staged, preview) = await Upload(archive, "Synthetic restore passphrase");
        Assert.Equal(HttpStatusCode.OK, staged);
        Assert.Equal(("restore", "ready", true), ((string)preview!["kind"]!, (string)preview["status"]!, (bool)preview["preview"]!["encrypted"]!));
        Assert.Contains("application database", preview["preview"]!["categories"]!.AsArray().Select(c => (string)c!));
        var restoreId = (string)preview["id"]!;
        var sha = (string)preview["archive_sha256"]!;
        Assert.Equal(2, await SavedFilters());                                              // staging never touches active data

        Assert.Equal(HttpStatusCode.UnprocessableEntity, (await Post("/api/backups/restore", new { id = restoreId, sha256 = sha, confirm = false, confirm_accounts = false })).Status);
        Assert.Equal(HttpStatusCode.Conflict, (await Post("/api/backups/restore", new { id = restoreId, sha256 = new string('a', 64), confirm = true, confirm_accounts = false })).Status);
        var (confirmed, waiting) = await Post("/api/backups/restore", new { id = restoreId, sha256 = sha, confirm = true, confirm_accounts = false });
        Assert.Equal(HttpStatusCode.OK, confirmed);
        Assert.Equal("waiting_for_restart", (string)waiting!["status"]!);
        Assert.Equal(HttpStatusCode.Conflict, (await Post("/api/backups/create")).Status);           // nothing else starts while a restore waits

        await Stop();
        await Start();
        var done = await Get("/api/backups");
        Assert.Equal("completed", (string)done["status"]!);
        Assert.Equal(1, await SavedFilters());                                              // the state of the backup, not merged
        var recovery = await _client.GetAsync($"/api/backups/{restoreId}/download?kind=destination-before-restore");
        Assert.Equal(HttpStatusCode.OK, recovery.StatusCode);
        var recoveryBytes = await recovery.Content.ReadAsByteArrayAsync();
        Assert.Equal((string)done["destination_sha256"]!, Convert.ToHexStringLower(SHA256.HashData(recoveryBytes)));

        // The destination recovery backup restores the pre-restore state (two filters) through the same path.
        var (_, back) = await Upload(recoveryBytes);
        await Post("/api/backups/restore", new { id = (string)back!["id"]!, sha256 = (string)back["archive_sha256"]!, confirm = true, confirm_accounts = false });
        await Stop();
        await Start();
        Assert.Equal(2, await SavedFilters());
    }

    [Fact]
    public async Task The_manifest_product_stays_a_stable_format_identifier_and_both_product_names_restore()
    {
        ConfigureKey();
        var (_, created) = await Post("/api/backups/create");
        var archive = await _client.GetByteArrayAsync($"/api/backups/{(string)created!["id"]!}/download");
        byte[] WithProduct(string product)
        {
            using var plain = new MemoryStream();
            BackupArchive.Unseal(new MemoryStream(archive), plain, "", BackupKeys.Host(Data));
            using (var zip = new System.IO.Compression.ZipArchive(plain, System.IO.Compression.ZipArchiveMode.Update, leaveOpen: true))
            {
                var entry = zip.GetEntry(ApplicationBackups.ManifestEntry)!;
                JsonObject manifest;
                using (var reader = new StreamReader(entry.Open())) manifest = JsonNode.Parse(reader.ReadToEnd())!.AsObject();
                Assert.Equal(ApplicationBackups.ManifestProduct, (string)manifest["product"]!);   // earlier .NET builds can restore it
                manifest["product"] = product;
                entry.Delete();
                using var writer = new StreamWriter(zip.CreateEntry(ApplicationBackups.ManifestEntry).Open());
                writer.Write(manifest.ToJsonString());
            }
            plain.Position = 0;
            using var sealedArchive = new MemoryStream();
            BackupArchive.Seal(plain, sealedArchive, "", BackupKeys.Host(Data));
            return sealedArchive.ToArray();
        }

        var (renamed, preview) = await Upload(WithProduct("AuthLens"));
        Assert.Equal(HttpStatusCode.OK, renamed);
        Assert.Equal("AuthLens", (string)preview!["preview"]!["source_mode"]!);
        Assert.Equal(HttpStatusCode.OK, (await Post($"/api/backups/uploads/{(string)preview["id"]!}/cancel")).Status);
        Assert.Equal(HttpStatusCode.UnprocessableEntity, (await Upload(WithProduct("Another product"))).Status);
    }

    [Fact]
    public async Task A_restore_that_fails_at_restart_is_rolled_back_and_a_pending_restore_can_be_cancelled()
    {
        ConfigureKey();
        await SaveFilter("Kept");
        var (_, created) = await Post("/api/backups/create");
        var archive = await _client.GetByteArrayAsync($"/api/backups/{(string)created!["id"]!}/download");
        await SaveFilter("Also kept");

        var (_, preview) = await Upload(archive);
        var restoreId = (string)preview!["id"]!;
        await Post("/api/backups/restore", new { id = restoreId, sha256 = (string)preview["archive_sha256"]!, confirm = true, confirm_accounts = false });
        Assert.Equal("cancelled", (string)(await Post("/api/backups/cancel")).Body!["status"]!);
        Assert.Equal(HttpStatusCode.Conflict, (await Post("/api/backups/cancel")).Status);
        Assert.Equal(HttpStatusCode.OK, (await Post($"/api/backups/uploads/{restoreId}/cancel")).Status);

        (_, preview) = await Upload(archive);
        restoreId = (string)preview!["id"]!;
        await Post("/api/backups/restore", new { id = restoreId, sha256 = (string)preview["archive_sha256"]!, confirm = true, confirm_accounts = false });
        await Stop();
        // A staged file altered after confirmation: the restart refuses it and rolls back.
        File.AppendAllText(Path.Combine(Data, "restore", restoreId, "staged", ApplicationBackups.DatabaseEntry), "x");
        await Start();
        var status = await Get("/api/backups");
        Assert.Equal("failed", (string)status["status"]!);
        Assert.Contains("rolled back", (string)status["message"]!);
        Assert.Equal(2, await SavedFilters());
    }

    [Fact]
    public async Task The_schedule_needs_a_verified_recovery_copy_uses_revisions_and_creates_automatic_backups()
    {
        var schedule = await Get("/api/backups/schedule");
        Assert.Equal((0, 7, false), ((int)schedule["revision"]!, (int)schedule["schedule"]!["keep"]!, (bool)schedule["encryption_ready"]!));
        var enabled = new { revision = 0, schedule = new { enabled = true, mode = "daily", time = "02:00", cron = "0 2 * * *", timezone = "UTC", keep = 7 } };
        Assert.Equal(HttpStatusCode.Conflict, (await Post("/api/backups/schedule", enabled)).Status);
        Assert.Equal(HttpStatusCode.UnprocessableEntity, (await Post("/api/backups/schedule", new { revision = 0, schedule = new { keep = 0 } })).Status);

        ConfigureKey();
        Assert.Equal(HttpStatusCode.Conflict, (await Post("/api/backups/key/verify", new { recovery_key = Convert.ToBase64String(new byte[32]) })).Status);
        var recovery = Path.Combine(_root, "keys", "recovery-copy.key");
        BackupKeys.Export(recovery, Data);
        var (verified, provider) = await Post("/api/backups/key/verify", new { recovery_key = File.ReadAllText(recovery).Trim() });
        Assert.Equal(HttpStatusCode.OK, verified);
        Assert.True((bool)provider!["escrow_verified"]!);

        var (saved, status) = await Post("/api/backups/schedule", enabled);
        Assert.Equal(HttpStatusCode.OK, saved);
        Assert.Equal((1, true), ((int)status!["revision"]!, (bool)status["schedule"]!["enabled"]!));
        Assert.NotEmpty(status["next_runs"]!.AsArray());
        Assert.Equal(HttpStatusCode.Conflict, (await Post("/api/backups/schedule", enabled)).Status);         // stale revision

        var backups = _app.Services.GetRequiredService<ApplicationBackups>();
        var loader = _app.Services.GetRequiredService<DataLoadGate>();
        var cursor = DateTimeOffset.UtcNow.Date.AddDays(1).AddHours(1);                                         // 01:00 UTC tomorrow
        Assert.Equal("idle", await BackupSchedule.TickAsync(Data, backups, loader, cursor.AddMinutes(30), cursor, default));
        Assert.Equal("ready", await BackupSchedule.TickAsync(Data, backups, loader, cursor.AddHours(2), cursor, default));
        Assert.Equal("skipped", await BackupSchedule.TickAsync(Data, backups, loader, cursor.AddHours(2), cursor, default));  // never twice
        var history = await Get("/api/backups/history");
        Assert.Equal("scheduled", (string)history["items"]![0]!["origin"]!);
        Assert.Equal("ready", (string)(await Get("/api/backups/schedule"))["attempts"]![0]!["status"]!);

        // Backup retention: nothing expires before the period; afterwards an approved preview removes automatic archives only, manual ones stay.
        await Post("/api/backups/create");
        var preview = await Get("/api/retention/preview?category=backup");
        Assert.Equal((0, 1, 1), ((int)preview["count"]!, (int)preview["counts"]!["automatic"]!, (int)preview["counts"]!["manual"]!));
        var factory = _app.Services.GetRequiredService<IDbContextFactory<AuthLensDb>>();
        var later = new AuthLens.Application.Retention.DataRetention(new DatabaseOptions { DataDirectory = Data }, factory, new ManualClock(DateTimeOffset.UtcNow.AddDays(91)));
        var due = await later.PreviewAsync("backup", default);
        Assert.Equal(1, (int)due["count"]!);
        Assert.Equal("awaiting_approval", await later.CheckAsync("automatic", default));                         // measured, not removed
        Assert.Equal(2, (int)(await Get("/api/backups/history"))["total"]!);
        var removed = await later.ApproveAsync("backup", (string)due["digest"]!, "operator", default);
        Assert.Equal(1, (int)removed["removed"]!["automatic backups"]!);
        history = await Get("/api/backups/history");
        Assert.Equal(["manual"], history["items"]!.AsArray().Select(i => (string)i!["origin"]!));
    }

    [Fact]
    public async Task Weekly_schedules_validate_timezones_and_skip_DST_gaps_and_repeated_hours()
    {
        var (definition, error) = BackupSchedule.Parse(new JsonObject { ["enabled"] = false, ["mode"] = "weekly", ["weekday"] = 0, ["time"] = "02:30", ["timezone"] = "Europe/Oslo" });
        Assert.Null(error); Assert.NotNull(definition);
        Assert.Equal("weekly", (string)definition.ToJson()["mode"]!);
        var expression = definition.Schedule.Expression;
        Assert.Equal(DateTimeOffset.Parse("2026-04-05T00:30:00Z"), AuthLens.Domain.Scheduling.CronSchedule.NextRuns(expression, "Europe/Oslo", DateTimeOffset.Parse("2026-03-28T00:00:00Z"), 1)[0]);
        Assert.Equal(DateTimeOffset.Parse("2026-10-25T00:30:00Z"), AuthLens.Domain.Scheduling.CronSchedule.NextRuns(expression, "Europe/Oslo", DateTimeOffset.Parse("2026-10-24T00:00:00Z"), 1)[0]);
        Assert.Equal(DateTimeOffset.Parse("2026-11-01T01:30:00Z"), AuthLens.Domain.Scheduling.CronSchedule.NextRuns(expression, "Europe/Oslo", DateTimeOffset.Parse("2026-10-25T00:31:00Z"), 1)[0]);
        Assert.Null(BackupSchedule.Parse(new JsonObject { ["timezone"] = "Europe/Nowhere" }).Value);
        var instant = DateTimeOffset.Parse("2026-11-16T08:00:00Z");
        Assert.Equal(DateTimeOffset.Parse("2026-11-17T06:00:00Z"), AuthLens.Domain.Scheduling.CronSchedule.NextRuns("0 6 * * *", "local", instant, 1, TimeZoneInfo.Utc)[0]);
        Assert.Equal(DateTimeOffset.Parse("2026-11-17T05:00:00Z"), AuthLens.Domain.Scheduling.CronSchedule.NextRuns("0 6 * * *", "local", instant, 1, TimeZoneInfo.FindSystemTimeZoneById("Europe/Oslo"))[0]);
        var (status, saved) = await Post("/api/backups/schedule", new { revision = 0, schedule = definition.ToJson() });
        Assert.Equal(HttpStatusCode.OK, status); Assert.Equal("weekly", (string)saved!["schedule"]!["mode"]!);
        Assert.False((bool)saved["requires_restart"]!);
        await Stop(); await Start();
        Assert.Equal("weekly", (string)(await Get("/api/backups/schedule"))["schedule"]!["mode"]!);
    }

    [Fact]
    public async Task Interrupted_scheduler_claims_are_reconciled_without_replaying_or_deleting_partial_work()
    {
        ConfigureKey(); BackupKeys.VerifyEscrow(File.ReadAllText(KeyFile), Data, "operator", DateTimeOffset.UtcNow);
        var definition = BackupSchedule.Parse(new JsonObject { ["enabled"] = true, ["time"] = "02:00", ["timezone"] = "UTC" }).Value!;
        BackupSchedule.Save(Data, definition, 0);
        var backups = _app.Services.GetRequiredService<ApplicationBackups>(); var loader = _app.Services.GetRequiredService<DataLoadGate>();
        var cursor = DateTimeOffset.UtcNow.Date.AddDays(1).AddHours(1); var now = cursor.AddHours(2);
        var concurrent = await Task.WhenAll(BackupSchedule.TickAsync(Data, backups, loader, now, cursor, default), BackupSchedule.TickAsync(Data, backups, loader, now, cursor, default));
        Assert.Single(concurrent, value => value == "ready"); Assert.Single(concurrent, value => value.StartsWith("skipped", StringComparison.Ordinal));
        var history = await backups.HistoryAsync(default); var id = (string)history["items"]![0]!["id"]!;
        var state = BackupSchedule.Read(Data);
        state["running"] = new JsonObject { ["backup_id"] = id, ["occurrence"] = state["last_occurrence"]!.DeepClone() };
        var file = Path.Combine(Data, "backups", "schedule.json"); BackupKeys.WriteAtomic(file, state.ToJsonString());
        Assert.StartsWith("ready: completed archive recovered", await BackupSchedule.TickAsync(Data, backups, loader, now, cursor, default));
        Assert.Equal(1, (int)(await backups.HistoryAsync(default))["total"]!);
        state = BackupSchedule.Read(Data);
        var partial = Path.Combine(Data, "backups", "retained-synthetic.partial"); File.WriteAllText(partial, "synthetic incomplete archive");
        state["running"] = new JsonObject { ["backup_id"] = new string('f', 32), ["occurrence"] = state["last_occurrence"]!.DeepClone() };
        BackupKeys.WriteAtomic(file, state.ToJsonString());
        Assert.StartsWith("failed: interrupted", await BackupSchedule.TickAsync(Data, backups, loader, now, cursor, default));
        Assert.True(File.Exists(partial)); Assert.NotNull(BackupSchedule.Read(Data)["last_failure"]);
        Assert.Equal("skipped", await BackupSchedule.TickAsync(Data, backups, loader, now, cursor, default));
    }

    [Fact]
    public async Task A_schedule_edit_during_a_snapshot_is_not_overwritten_by_completion()
    {
        ConfigureKey(); BackupKeys.VerifyEscrow(File.ReadAllText(KeyFile), Data, "operator", DateTimeOffset.UtcNow);
        BackupSchedule.Save(Data, BackupSchedule.Parse(new JsonObject { ["enabled"] = true, ["time"] = "02:00", ["timezone"] = "UTC" }).Value!, 0);
        // Hold the account writer: the snapshot can claim its job, but cannot finish before the policy edit.
        var accounts = Path.Combine(Data, "security", "accounts.sqlite3");
        var store = new AuthLens.Application.Accounts.AccountStore(accounts, TimeProvider.System); store.Prepare();
        var activation = await store.IssueAsync();
        await store.CompleteAsync(activation.Code, "admin", "Synthetic administrator", "Synthetic snapshot password 123!", false);
        using var connection = new Microsoft.Data.Sqlite.SqliteConnection($"Data Source={accounts};Pooling=False"); connection.Open();
        using var reservation = connection.BeginTransaction(deferred: false);
        var cursor = DateTimeOffset.UtcNow.Date.AddDays(1).AddHours(1);
        var task = BackupSchedule.TickAsync(Data, _app.Services.GetRequiredService<ApplicationBackups>(), _app.Services.GetRequiredService<DataLoadGate>(), cursor.AddHours(2), cursor, default);
        while (!task.IsCompleted && BackupSchedule.Read(Data)["running"] is null) await Task.Yield();
        BackupSchedule.Save(Data, BackupSchedule.Parse(new JsonObject { ["enabled"] = false, ["time"] = "04:00", ["timezone"] = "UTC" }).Value!, 1);
        reservation.Rollback();
        Assert.Equal("ready", await task);
        var after = BackupSchedule.Read(Data);
        Assert.Equal(2, (int)after["revision"]!); Assert.False((bool)after["schedule"]!["enabled"]!); Assert.Equal("04:00", (string)after["schedule"]!["time"]!);
    }

    [Fact]
    public async Task A_server_with_a_shared_token_refuses_application_backups()
    {
        await Stop();
        await Start(HostMode.Server, AuthenticationMode.SharedToken);
        var response = await _client.GetAsync("/api/backups");
        Assert.Equal(HttpStatusCode.Forbidden, response.StatusCode);
        Assert.Equal(HttpStatusCode.Forbidden, (await Post("/api/backups/create")).Status);
    }

    [Fact]
    public async Task The_pre_migration_backup_waits_for_confirmation_is_kept_after_it_and_is_deleted_only_explicitly()
    {
        var status = await Get("/api/storage/status");
        Assert.Equal(("ready", false), ((string)status["state"]!, (bool)status["requires_confirmation"]!));
        Assert.True((int)status["schema_version"]! > 0);
        Assert.Null(status["backup"]);

        // A migration backup as DatabaseMaintenance records it before applying schema migrations.
        var maintenance = _app.Services.GetRequiredService<DatabaseMaintenance>();
        var record = await maintenance.BackupAsync(BackupKind.Migration, "before migrations Synthetic", recordInDatabase: true);
        var id = record.Sha256[..32];
        status = await Get("/api/storage/status");
        Assert.True((bool)status["requires_confirmation"]!);
        Assert.Equal(id, (string)status["backup"]!["id"]!);

        Assert.Equal(HttpStatusCode.UnprocessableEntity, (await Post("/api/storage/migration/confirm", new { migration_id = id, confirm = false })).Status);
        Assert.Equal(HttpStatusCode.UnprocessableEntity, (await Post("/api/storage/migration/confirm", new { migration_id = "x", confirm = true })).Status);
        Assert.Equal(HttpStatusCode.Conflict, (await Post("/api/storage/migration/delete-backup", new { migration_id = id, confirm = true })).Status);   // not confirmed yet
        Assert.Equal(HttpStatusCode.Conflict, (await Post("/api/storage/migration/confirm", new { migration_id = new string('0', 32), confirm = true })).Status);
        var (confirmed, after) = await Post("/api/storage/migration/confirm", new { migration_id = id, confirm = true });
        Assert.Equal(HttpStatusCode.OK, confirmed);
        Assert.False((bool)after!["requires_confirmation"]!);
        Assert.Equal(("operator", id), ((string)after["retained"]!["confirmed_by"]!, (string)after["retained"]!["id"]!));
        var file = Path.Combine(Data, "backups", record.FileName);
        Assert.True(File.Exists(file));                                                                  // confirmation keeps the archive

        // Neither automatic-backup retention nor the backup history touches it.
        var factory = _app.Services.GetRequiredService<IDbContextFactory<AuthLensDb>>();
        var retention = new AuthLens.Application.Retention.DataRetention(new DatabaseOptions { DataDirectory = Data }, factory, new ManualClock(DateTimeOffset.UtcNow.AddYears(2)));
        var plan = await retention.PreviewAsync("backup", default);
        Assert.Equal((0, 1), ((int)plan["count"]!, (int)plan["counts"]!["migration"]!));
        await retention.ApproveAsync("backup", (string)plan["digest"]!, "operator", default);
        Assert.True(File.Exists(file));
        Assert.Equal(0, (int)(await Get("/api/backups/history"))["total"]!);

        var (deleted, final) = await Post("/api/storage/migration/delete-backup", new { migration_id = id, confirm = true });
        Assert.Equal(HttpStatusCode.OK, deleted);
        Assert.Null(final!["retained"]);
        Assert.False(File.Exists(file));
    }

    [Fact]
    public async Task Health_legacy_settings_path_and_review_undo_follow_v1()
    {
        var health = await Get("/health");
        Assert.Equal(("sap-lens", "needs_configuration", 0), ((string)health["app"]!, (string)health["status"]!, (int)health["cached_roles"]!));
        Assert.Equal("", (string)(await Get("/api/settings"))["data_csv_path"]!);
        Assert.Equal(HttpStatusCode.BadRequest, (await Post("/api/settings", new { data_csv_path = "relative/roles.csv" })).Status);
        var csv = Path.Combine(_root, "roles.csv");
        File.WriteAllText(csv, Csv.Roles(4));
        var (status, body) = await Post("/api/settings", new { data_csv_path = csv });
        Assert.Equal(HttpStatusCode.OK, status);
        Assert.Equal((csv, (string?)null), ((string)body!["data_csv_path"]!, (string?)body["error"]));
        Assert.Equal(("ok", 4), ((string)(await Get("/health"))["status"]!, (int)(await Get("/health"))["cached_roles"]!));

        Assert.Equal(HttpStatusCode.UnprocessableEntity, (await Post("/api/retention/review/undo", new { operation = "x", confirm = true })).Status);
        var (undo, detail) = await Post("/api/retention/review/undo", new { operation = new string('a', 32), confirm = true });
        Assert.Equal(HttpStatusCode.Conflict, undo);
        Assert.Contains("immutable audit evidence", (string)detail!["detail"]!);
    }
}
