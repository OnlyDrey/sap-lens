using System.IO.Compression;
using System.Reflection;
using System.Security.Cryptography;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;
using Microsoft.Data.Sqlite;
using Microsoft.EntityFrameworkCore;
using AuthLens.Persistence;

namespace AuthLens.Application.Backups;

/// <summary>Application backups and restore (v1 application_backups.py on the AuthLens storage). An archive holds consistent online copies of the SQLite
/// database and the account store (active sessions removed), the branding images and a manifest with SHA-256 per file, encrypted as SLBAK3. Restore is a
/// restart handoff: an upload is decrypted, checked and previewed without touching active data; a confirmed restore is applied at the next start, before
/// the database opens, after an encrypted destination recovery backup of the current data, and is rolled back if anything fails.</summary>
public sealed partial class ApplicationBackups(DatabaseOptions options, IDbContextFactory<AuthLensDb> factory, TimeProvider clock, WriteCoordinator? writer = null)
{
    /// <summary>Record changes go through the process-wide write coordinator (one SQLite writer, BEGIN IMMEDIATE), like every other write.</summary>
    private readonly WriteCoordinator _writer = writer ?? new WriteCoordinator(factory);

    public const long MaxUpload = 256L * 1024 * 1024;
    /// <summary>Archive entries. The database is written as <see cref="DatabaseEntry"/>; archives written by SAP Lens carry it as
    /// <see cref="LegacyDatabaseEntry"/> and are restored to the AuthLens file name (the entry is verified under its own name first).</summary>
    public const string DatabaseEntry = DatabaseOptions.DatabaseFileName, LegacyDatabaseEntry = DatabaseOptions.LegacyDatabaseFileName,
        AccountsEntry = "security/accounts.sqlite3", ManifestEntry = "manifest.json";

    /// <summary>The archive manifest's "product" names the writing product. AuthLens writes "AuthLens"; archives written by SAP Lens
    /// ("SAP Lens 2", later "SAP Lens") are accepted. SAP Lens builds do not accept AuthLens archives (restore is forward only).</summary>
    public const string ManifestProduct = "AuthLens";
    public static readonly string[] LegacyManifestProducts = ["SAP Lens 2", "SAP Lens"];
    private static readonly string[] AcceptedManifestProducts = [ManifestProduct, .. LegacyManifestProducts];

    /// <summary>Where an archive entry is staged: a SAP Lens database entry under the AuthLens database name, every other entry under its own name.</summary>
    private static string StagedPath(string root, string entry) => Path.Combine(root, entry == LegacyDatabaseEntry ? DatabaseEntry : entry);
    [GeneratedRegex("\\A[a-f0-9]{32}\\z")] public static partial Regex Identity();
    [GeneratedRegex("^branding/[a-f0-9]{64}\\.png$")] private static partial Regex BrandingEntry();
    private static readonly SemaphoreSlim Gate = new(1, 1);
    public bool Busy => Gate.CurrentCount == 0;

    // Take SQLite write reservations in one order. Readers keep serving; all database writers are
    // excluded only while the database/branding copies are made, before compression and encryption.
    private sealed class SnapshotLocks : IDisposable
    {
        private readonly List<SqliteConnection> _connections = [];
        private readonly List<SqliteTransaction> _transactions = [];
        public SnapshotLocks(params string[] databases)
        {
            try
            {
                foreach (var database in databases.Where(File.Exists))
                {
                    var connection = new SqliteConnection(new SqliteConnectionStringBuilder { DataSource = database, Mode = SqliteOpenMode.ReadWrite, Pooling = false }.ToString());
                    _connections.Add(connection); connection.Open();
                    _transactions.Add(connection.BeginTransaction(deferred: false));
                }
            }
            catch { Dispose(); throw; }
        }
        public void Dispose()
        {
            foreach (var transaction in _transactions.AsEnumerable().Reverse()) transaction.Dispose();
            foreach (var connection in _connections.AsEnumerable().Reverse()) connection.Dispose();
        }
    }

    /// <summary>Product version recorded in manifests (set by the host).</summary>
    public static string ProductVersion { get; set; } = typeof(ApplicationBackups).Assembly.GetCustomAttribute<AssemblyInformationalVersionAttribute>()?.InformationalVersion.Split('+')[0] ?? "0.0.0";

    private string Data => options.DataDirectory;
    private static string OperationFile(string data) => Path.Combine(data, "backups", "operation.json");
    private static string RestoreRoot(string data) => Path.Combine(data, "restore");
    private static string PendingFile(string data) => Path.Combine(RestoreRoot(data), "pending.json");
    private static string Stamp(DateTimeOffset now) => now.UtcDateTime.ToString("yyyy-MM-dd'T'HH:mm:ss.ffffff'+00:00'");
    public static string ArchiveName(string id) => $"archives/{id}.slbak";
    public static string DestinationName(string id) => $"archives/destination-{id}.slbak";

    // ---- operation state (one JSON file, readable before the database opens)

    public static JsonObject ReadOperation(string data)
    {
        try { return File.Exists(OperationFile(data)) ? JsonNode.Parse(File.ReadAllText(OperationFile(data))) as JsonObject ?? Idle() : Idle(); }
        catch (Exception error) when (error is IOException or System.Text.Json.JsonException) { return Idle(); }
    }

    private static JsonObject Idle() => new() { ["status"] = "idle" };

    private static void WriteOperation(string data, JsonObject value)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(OperationFile(data))!);
        BackupKeys.WriteAtomic(OperationFile(data), value.ToJsonString());
    }

    public JsonObject Status()
    {
        var result = ReadOperation(Data);
        if (File.Exists(PendingFile(Data))) { result["status"] = "waiting_for_restart"; result["kind"] = "restore"; }
        result["key_provider"] = BackupKeys.Status(Data);
        result["recovery_required"] = false;
        return result;
    }

    // ---- creating archives

    private static string Sha(string path) => AuthLens.Domain.Json.Digests.File(path);

    private static void OnlineCopy(string source, string target)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(target)!);
        using var from = new SqliteConnection(new SqliteConnectionStringBuilder { DataSource = source, Mode = SqliteOpenMode.ReadOnly, Pooling = false }.ToString());
        using var to = new SqliteConnection(new SqliteConnectionStringBuilder { DataSource = target, Pooling = false }.ToString());
        from.Open();
        to.Open();
        from.BackupDatabase(to);
    }

    private static void Execute(string path, string sql)
    {
        using var db = new SqliteConnection(new SqliteConnectionStringBuilder { DataSource = path, Pooling = false }.ToString());
        db.Open();
        using var command = db.CreateCommand();
        command.CommandText = sql;
        command.ExecuteNonQuery();
    }

    private static long Count(string path, string sql)
    {
        using var db = new SqliteConnection(new SqliteConnectionStringBuilder { DataSource = path, Mode = SqliteOpenMode.ReadOnly, Pooling = false }.ToString());
        db.Open();
        using var command = db.CreateCommand();
        command.CommandText = sql;
        return Convert.ToInt64(command.ExecuteScalar(), System.Globalization.CultureInfo.InvariantCulture);
    }

    private static List<string> Migrations(string path)
    {
        using var db = new SqliteConnection(new SqliteConnectionStringBuilder { DataSource = path, Mode = SqliteOpenMode.ReadOnly, Pooling = false }.ToString());
        db.Open();
        using var command = db.CreateCommand();
        command.CommandText = "SELECT MigrationId FROM __EFMigrationsHistory ORDER BY MigrationId";
        var result = new List<string>();
        using var reader = command.ExecuteReader();
        while (reader.Read()) result.Add(reader.GetString(0));
        return result;
    }

    private static void Integrity(string path)
    {
        var report = DatabaseMaintenance.VerifyFileAsync(path).GetAwaiter().GetResult();
        if (!report.Ok) throw new BackupException("A database in the archive failed its integrity check.", 422);
    }

    /// <summary>Writes an encrypted archive of the data directory; returns (archive SHA-256, size, manifest). Works without the DI container (restore uses it
    /// before the database opens).</summary>
    public static (string Sha256, long Size, JsonObject Manifest) WriteArchive(string data, string target, string passphrase, byte[]? host, string kind, DateTimeOffset now)
    {
        var work = Path.Combine(data, "backups", "work-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(work);
        try
        {
            var files = new JsonArray();
            void Add(string entry) { var path = Path.Combine(work, entry); files.Add(new JsonObject { ["path"] = entry, ["sha256"] = Sha(path), ["size"] = new FileInfo(path).Length }); }
            var database = Path.Combine(data, DatabaseEntry);
            if (!File.Exists(database)) throw new BackupException("There is no application database to back up yet.");
            JsonNode? accounts = null;
            var accountStore = Path.Combine(data, "security", "accounts.sqlite3");
            using (var consistent = new SnapshotLocks(database, accountStore))
            {
            OnlineCopy(database, Path.Combine(work, DatabaseEntry));
            Integrity(Path.Combine(work, DatabaseEntry));
            Add(DatabaseEntry);
            ManagedSourceFiles.CopyForBackup(data, Path.Combine(work, DatabaseEntry), work, Add);
            if (File.Exists(accountStore))
            {
                var copy = Path.Combine(work, AccountsEntry);
                OnlineCopy(accountStore, copy);
                Execute(copy, "DELETE FROM sessions; DELETE FROM one_time; VACUUM;"); // sessions and live one-use credentials never leave the host
                Integrity(copy);
                var accountCount = Count(copy, "SELECT COUNT(*) FROM users");
                if (accountCount > 0)
                {
                    accounts = new JsonObject { ["accounts"] = accountCount, ["administrators"] = Count(copy, "SELECT COUNT(*) FROM users WHERE role='administrator' AND enabled=1") };
                    if ((long)accounts["administrators"]! == 0) throw new BackupException("The account store has no enabled administrator. Complete local activation or recovery before creating an account-bearing archive.");
                    Add(AccountsEntry);
                }
            }
            var branding = Path.Combine(data, "branding");
            if (Directory.Exists(branding))
                foreach (var image in Directory.GetFiles(branding, "*.png").Order(StringComparer.Ordinal))
                {
                    var entry = "branding/" + Path.GetFileName(image);
                    if (!BrandingEntry().IsMatch(entry)) continue;
                    Directory.CreateDirectory(Path.Combine(work, "branding"));
                    File.Copy(image, Path.Combine(work, entry));
                    Add(entry);
                }
            }
            var manifest = new JsonObject
            {
                ["format"] = 1, ["product"] = ManifestProduct, ["version"] = ProductVersion, ["kind"] = kind, ["created"] = Stamp(now), ["files"] = files,
                ["migrations"] = new JsonArray([.. Migrations(Path.Combine(work, DatabaseEntry)).Select(m => (JsonNode?)m)]), ["accounts"] = accounts,
            };
            File.WriteAllText(Path.Combine(work, ManifestEntry), manifest.ToJsonString());
            var zip = Path.Combine(work, "payload.zip");
            using (var archive = ZipFile.Open(zip, ZipArchiveMode.Create))
                foreach (var entry in files.Select(f => (string)f!["path"]!).Append(ManifestEntry))
                    archive.CreateEntryFromFile(Path.Combine(work, entry), entry, CompressionLevel.Optimal);
            Directory.CreateDirectory(Path.GetDirectoryName(target)!);
            var partial = target + ".partial";
            using (var input = File.OpenRead(zip))
            using (var output = new FileStream(partial, FileMode.CreateNew, FileAccess.Write))
                BackupArchive.Seal(input, output, passphrase, host);
            // Verified before it is kept: the archive authenticates and decrypts to the payload that was written.
            using (var check = File.OpenRead(partial))
            using (var decrypted = new MemoryStream())
            {
                BackupArchive.Unseal(check, decrypted, passphrase, host);
                if (!decrypted.ToArray().AsSpan().SequenceEqual(File.ReadAllBytes(zip))) throw new BackupException("The archive could not be verified after writing.");
            }
            File.Move(partial, target);
            return (Sha(target), new FileInfo(target).Length, manifest);
        }
        finally { try { Directory.Delete(work, true); } catch (IOException) { } }
    }

    /// <summary>Creates a verified manual or automatic archive and records it. Needs the host key (the restore handoff and automatic backups depend on it).</summary>
    public async Task<JsonObject> CreateAsync(string kind, string passphrase, string actor, CancellationToken ct, string? operationId = null)
    {
        var host = BackupKeys.Host(Data) ?? throw new BackupException("Configure a protected host backup key before creating backups.");
        if (File.Exists(PendingFile(Data))) throw new BackupException("A restore is waiting for the next restart. Cancel it before creating a backup.");
        await Gate.WaitAsync(ct);
        try
        {
            var id = operationId ?? Guid.NewGuid().ToString("N");
            if (!Identity().IsMatch(id)) throw new BackupException("Invalid backup operation identifier.");
            var now = clock.GetUtcNow();
            var (sha, size, manifest) = await Task.Run(() => WriteArchive(Data, Path.Combine(Data, "backups", ArchiveName(id)), passphrase, host, kind, now), ct);
            await _writer.WriteAsync((db, _) =>
            {
                db.Backups.Add(new BackupRecord { Kind = kind, FileName = ArchiveName(id), Sha256 = sha, SizeBytes = size, Reason = $"{(passphrase.Length > 0 ? "passphrase" : "host-key")};{actor}", CreatedUtc = now.UtcDateTime });
                return Task.CompletedTask;
            }, ct);
            var operation = new JsonObject
            {
                ["id"] = id, ["kind"] = "backup", ["status"] = "ready", ["completed_at"] = Stamp(clock.GetUtcNow()), ["archive_sha256"] = sha,
                ["message"] = $"Encrypted backup is ready ({(passphrase.Length > 0 ? "separate passphrase" : "host recovery key")}). Download it and store it separately.",
            };
            WriteOperation(Data, operation);
            return Status();
        }
        catch (Exception error) when (error is not (BackupException or OperationCanceledException))
        {
            WriteOperation(Data, new JsonObject { ["kind"] = "backup", ["status"] = "failed", ["completed_at"] = Stamp(clock.GetUtcNow()), ["message"] = "Backup failed. Existing data is preserved." });
            throw new BackupException("Backup operation could not be completed. Check storage and the host key. Existing data is preserved.");
        }
        finally { Gate.Release(); }
    }

    public static string? IdOf(BackupRecord record) =>
        record.FileName.StartsWith("archives/", StringComparison.Ordinal) && record.FileName.EndsWith(".slbak", StringComparison.Ordinal) && Identity().IsMatch(record.FileName[9..^6]) ? record.FileName[9..^6] : null;

    public async Task<JsonObject> HistoryAsync(CancellationToken ct)
    {
        await using var db = await factory.CreateDbContextAsync(ct);
        var rows = (await db.Backups.AsNoTracking().Where(b => b.DeletedUtc == null && (b.Kind == BackupKind.Manual || b.Kind == BackupKind.Automatic)).ToListAsync(ct))
            .Where(b => IdOf(b) is not null).OrderByDescending(b => b.CreatedUtc).ToList();
        var items = new JsonArray();
        foreach (var b in rows.Take(200))
        {
            var path = Path.Combine(Data, "backups", b.FileName);
            var verified = false;
            try { verified = File.Exists(path) && new FileInfo(path).Length == b.SizeBytes && Sha(path) == b.Sha256; }
            catch (IOException) { } catch (UnauthorizedAccessException) { }
            items.Add(new JsonObject
            {
                ["id"] = IdOf(b), ["created_at"] = DateTime.SpecifyKind(b.CreatedUtc, DateTimeKind.Utc).ToString("yyyy-MM-dd'T'HH:mm:ss'+00:00'"), ["origin"] = b.Kind == BackupKind.Automatic ? "scheduled" : "manual",
                ["status"] = verified ? "ready" : "failed", ["size"] = b.SizeBytes, ["verified"] = verified,
            });
        }
        return new JsonObject { ["items"] = items, ["total"] = rows.Count, ["storage_bytes"] = rows.Sum(b => b.SizeBytes), ["destination"] = "Private application data / backups / archives" };
    }

    /// <summary>The archive file of a backup (kind backup) or the destination recovery backup of a restore operation; the file must still match its record.</summary>
    public async Task<string> DownloadAsync(string id, string kind, CancellationToken ct)
    {
        if (!Identity().IsMatch(id) || kind is not ("backup" or "destination-before-restore")) throw new BackupException("Backup download is unavailable.", 404);
        if (kind == "destination-before-restore")
        {
            var operation = ReadOperation(Data);
            var file = Path.Combine(Data, "backups", DestinationName(id));
            if ((string?)operation["id"] != id || !File.Exists(file) || Sha(file) != (string?)operation["destination_sha256"]) throw new BackupException("Backup download is unavailable.", 404);
            return file;
        }
        await using var db = await factory.CreateDbContextAsync(ct);
        var name = ArchiveName(id);
        var record = await db.Backups.AsNoTracking().FirstOrDefaultAsync(b => b.FileName == name && b.DeletedUtc == null, ct) ?? throw new BackupException("Backup download is unavailable.", 404);
        var path = Path.Combine(Data, "backups", name);
        if (!File.Exists(path) || Sha(path) != record.Sha256) throw new BackupException("The archive is missing or was altered; it is not offered for download.", 409);
        return path;
    }

    /// <summary>Independently authenticates, decrypts and validates an existing archive without restoring data.</summary>
    public async Task<JsonObject> VerifyAsync(string id, string secret, CancellationToken ct)
    {
        await Gate.WaitAsync(ct);
        string? work = null;
        try
        {
            var archive = await DownloadAsync(id, "backup", ct);
            work = Path.Combine(Data, "backups", "verify-" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(work);
            var payload = Path.Combine(work, "payload.zip");
            await Task.Run(() =>
            {
                using var input = File.OpenRead(archive);
                using var output = new FileStream(payload, FileMode.CreateNew, FileAccess.Write);
                BackupArchive.Unseal(input, output, secret, BackupKeys.Host(Data));
            }, ct);
            await using var db = await factory.CreateDbContextAsync(ct);
            Extract(payload, Path.Combine(work, "checked"), db.Database.GetMigrations().ToList());
            return new JsonObject { ["id"] = id, ["verified"] = true, ["sha256"] = Sha(archive), ["checked_at"] = Stamp(clock.GetUtcNow()) };
        }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException or SqliteException)
        { throw new BackupException("Archive verification could not finish. Check archive availability, storage and the recovery key."); }
        finally
        {
            try { if (work is not null) Directory.Delete(work, true); }
            catch (Exception error) when (error is IOException or UnauthorizedAccessException) { }
            finally { Gate.Release(); }
        }
    }

    /// <summary>Deletes a manual or automatic archive on explicit request. Migration backups are released through the storage routes only.</summary>
    public async Task<JsonObject> DeleteAsync(string id, bool confirm, string actor, CancellationToken ct)
    {
        if (!confirm) throw new BackupException("Confirm backup deletion.", 422);
        await Gate.WaitAsync(ct);
        try
        {
        if (File.Exists(PendingFile(Data))) throw new BackupException("An active operation prevents archive deletion.");
        var name = Identity().IsMatch(id) ? ArchiveName(id) : "";
        await _writer.WriteAsync(async (db, token) =>
        {
            var record = await db.Backups.FirstOrDefaultAsync(b => b.FileName == name && b.DeletedUtc == null && (b.Kind == BackupKind.Manual || b.Kind == BackupKind.Automatic), token)
                ?? throw new BackupException("Only inactive backup archives can be deleted.");
            foreach (var staged in Directory.Exists(RestoreRoot(Data)) ? Directory.GetDirectories(RestoreRoot(Data)) : [])
                if (File.Exists(Path.Combine(staged, "preview.json")) && (string?)JsonNode.Parse(File.ReadAllText(Path.Combine(staged, "preview.json")))?["archive_sha256"] == record.Sha256)
                    throw new BackupException("A staged restore protects this archive.");
            // The file goes first: if the commit then failed, the record stays and history shows the archive as missing, never a silent leftover.
            File.Delete(Path.Combine(Data, "backups", name));
            record.DeletedUtc = clock.GetUtcNow().UtcDateTime;
            record.Reason = (record.Reason ?? "") + $";deleted by {actor}";
        }, ct);
        var operation = ReadOperation(Data);
        if ((string?)operation["id"] == id) { operation["status"] = "cancelled"; operation["message"] = "Backup archive deleted by request."; WriteOperation(Data, operation); }
        return await HistoryAsync(ct);
        }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException)
        { throw new BackupException("The archive is in use or cannot be removed. Retry after active downloads or verification finish; existing records were preserved."); }
        finally { Gate.Release(); }
    }

    // ---- restore: staging, validation, preview

    private static string Staging(string data, string id) => Path.Combine(RestoreRoot(data), id);

    /// <summary>Stores an uploaded archive privately, decrypts and validates it, and returns the preview. Active data is never touched.</summary>
    public async Task<JsonObject> StageAsync(Stream upload, string secret, CancellationToken ct)
    {
        if (File.Exists(PendingFile(Data))) throw new BackupException("A restore is already waiting for restart. Cancel it first.");
        var id = Guid.NewGuid().ToString("N");
        var folder = Staging(Data, id);
        Directory.CreateDirectory(folder);
        try
        {
            var archive = Path.Combine(folder, "upload.slbak");
            long size = 0;
            await using (var output = new FileStream(archive, FileMode.CreateNew, FileAccess.Write))
            {
                var buffer = new byte[81920];
                int read;
                while ((read = await upload.ReadAsync(buffer, ct)) > 0)
                {
                    size += read;
                    if (size > MaxUpload) throw new BackupException("Settings uploads support up to 256 MiB.", 413);
                    await output.WriteAsync(buffer.AsMemory(0, read), ct);
                }
            }
            if (size == 0) throw new BackupException("The archive is empty.", 422);
            var head = new byte[8];
            await using (var probe = File.OpenRead(archive)) _ = await probe.ReadAsync(head, ct);
            if (BackupArchive.IsV1(head) || head[0] == 0x1f)
                throw new BackupException("This is a SAP Lens 1 backup. Import it through the separate v1 data migration (AuthLens.Api --migrate-v1 preview), never by replacing data here.", 422);
            if (!BackupArchive.IsV2(head)) throw new BackupException("Select an encrypted AuthLens .slbak backup.", 422);
            var host = BackupKeys.Host(Data);
            var payload = Path.Combine(folder, "payload.zip");
            await Task.Run(() =>
            {
                using var input = File.OpenRead(archive);
                using var output = new FileStream(payload, FileMode.CreateNew, FileAccess.Write);
                BackupArchive.Unseal(input, output, secret, host);
            }, ct);
            var staged = Path.Combine(folder, "staged");
            IReadOnlyCollection<string> known;
            await using (var db = await factory.CreateDbContextAsync(ct)) known = db.Database.GetMigrations().ToList();
            var manifest = Extract(payload, staged, known);
            File.Delete(payload);
            var preview = new JsonObject
            {
                ["id"] = id, ["kind"] = "restore", ["status"] = "ready", ["archive_sha256"] = Sha(archive),
                ["preview"] = new JsonObject
                {
                    ["source_mode"] = LegacyManifestProducts.Contains((string?)manifest["product"]) ? "SAP Lens" : "AuthLens", ["source_product"] = manifest["product"]?.DeepClone(), ["source_version"] = manifest["version"]?.DeepClone(), ["created_at"] = manifest["created"]?.DeepClone(),
                    ["files"] = manifest["files"]!.AsArray().Count, ["snapshots"] = 0,
                    ["categories"] = new JsonArray([.. new[] { "application database", manifest["accounts"] is JsonObject ? "accounts" : null, manifest["files"]!.AsArray().Any(f => ManagedSourceFiles.EntryPattern().IsMatch((string)f!["path"]!)) ? "managed import files" : null, manifest["files"]!.AsArray().Any(f => ((string)f!["path"]!).StartsWith("branding/", StringComparison.Ordinal)) ? "branding" : null }
                        .Where(c => c is not null).Select(c => (JsonNode?)c)]),
                    ["warning"] = "Restore replaces all application data, review history and settings after the next restart. Histories are not merged. An encrypted recovery backup of the current data is created first.",
                    ["encrypted"] = true, ["accounts"] = manifest["accounts"]?.DeepClone(),
                },
            };
            File.WriteAllText(Path.Combine(folder, "preview.json"), preview.ToJsonString());
            return preview;
        }
        catch (Exception error) when (error is not OperationCanceledException)
        {
            try { Directory.Delete(folder, true); } catch (IOException) { }
            if (error is BackupException) throw;
            throw new BackupException("Archive validation failed. No active data was changed. Use a compatible application-data backup.", 422);
        }
    }

    /// <summary>Extracts and validates a payload: only expected entries, no path escapes, size-bounded, hashes as in the manifest, intact databases from no newer build.</summary>
    public static JsonObject Extract(string zip, string target, IReadOnlyCollection<string> knownMigrations)
    {
        Directory.CreateDirectory(target);
        using var archive = ZipFile.OpenRead(zip);
        if (archive.Entries.Count > 1000) throw new BackupException("The archive has too many entries.", 422);
        long total = 0;
        foreach (var entry in archive.Entries)
        {
            var name = entry.FullName;
            if (name != DatabaseEntry && name != LegacyDatabaseEntry && name != AccountsEntry && name != ManifestEntry && !BrandingEntry().IsMatch(name) && !ManagedSourceFiles.EntryPattern().IsMatch(name)) throw new BackupException("The archive contains unexpected files.", 422);
            total += entry.Length;
            if (entry.Length > BackupArchive.MaxArchive || total > BackupArchive.MaxArchive) throw new BackupException("The archive content is too large.", 422);
            var path = Path.GetFullPath(StagedPath(target, name));
            if (!path.StartsWith(Path.GetFullPath(target) + Path.DirectorySeparatorChar, StringComparison.Ordinal)) throw new BackupException("The archive contains unexpected files.", 422);
            Directory.CreateDirectory(Path.GetDirectoryName(path)!);
            entry.ExtractToFile(path, overwrite: false);
        }
        JsonObject manifest;
        try { manifest = JsonNode.Parse(File.ReadAllText(Path.Combine(target, ManifestEntry))) as JsonObject ?? throw new FormatException(); }
        catch (Exception error) when (error is IOException or System.Text.Json.JsonException or FormatException) { throw new BackupException("The archive manifest is missing or invalid.", 422); }
        if ((int?)manifest["format"] != 1 || !AcceptedManifestProducts.Contains((string?)manifest["product"] ?? "") || manifest["files"] is not JsonArray files) throw new BackupException("Unsupported archive manifest.", 422);
        var listed = files.Select(f => (string)f!["path"]!).ToHashSet(StringComparer.Ordinal);
        var present = archive.Entries.Select(e => e.FullName).Where(n => n != ManifestEntry).ToHashSet(StringComparer.Ordinal);
        // Exactly one database: the AuthLens entry, or (only in a SAP Lens archive) the SAP Lens entry.
        if (!listed.SetEquals(present) || listed.Contains(DatabaseEntry) == listed.Contains(LegacyDatabaseEntry)) throw new BackupException("The archive does not match its manifest.", 422);
        if (listed.Contains(LegacyDatabaseEntry) && !LegacyManifestProducts.Contains((string?)manifest["product"])) throw new BackupException("The archive does not match its manifest.", 422);
        foreach (var file in files)
            if (Sha(StagedPath(target, (string)file!["path"]!)) != (string?)file["sha256"]) throw new BackupException("A file in the archive does not match its checksum.", 422);
        Integrity(Path.Combine(target, DatabaseEntry));
        var sourceReferences = ManagedSourceFiles.References(Path.Combine(target, DatabaseEntry));
        if (!listed.Where(entry => ManagedSourceFiles.EntryPattern().IsMatch(entry)).ToHashSet(StringComparer.Ordinal).SetEquals(sourceReferences.Keys))
            throw new BackupException("The archive's managed sources do not match its database.", 422);
        foreach (var (entry, hash) in sourceReferences)
            if (Sha(ManagedSourceFiles.Resolve(target, entry)) != hash) throw new BackupException("A managed source differs from its database metadata.", 422);
        var known = knownMigrations.ToHashSet(StringComparer.Ordinal);
        if (Migrations(Path.Combine(target, DatabaseEntry)).Any(m => !known.Contains(m)))
            throw new BackupException("The archive was written by a newer AuthLens version and cannot be restored here.", 422);
        if (listed.Contains(AccountsEntry))
        {
            var accounts = Path.Combine(target, AccountsEntry);
            Integrity(accounts);
            if (Count(accounts, "SELECT COUNT(*) FROM users WHERE role='administrator' AND enabled=1") < 1) throw new BackupException("The archive has no enabled administrator account.", 422);
        }
        return manifest;
    }

    public JsonObject Discard(string id)
    {
        if (!Identity().IsMatch(id) || !Directory.Exists(Staging(Data, id))) throw new BackupException("No staged restore with this identifier.", 404);
        if (File.Exists(PendingFile(Data)) && (string?)JsonNode.Parse(File.ReadAllText(PendingFile(Data)))?["id"] == id) throw new BackupException("This restore is already confirmed; cancel the pending operation instead.");
        Directory.Delete(Staging(Data, id), true);
        return Status();
    }

    /// <summary>Schedules a confirmed restore for the next start. Needs the host key, because the current data is first saved as an encrypted recovery backup.</summary>
    public JsonObject Confirm(string id, string sha256, bool confirm, bool confirmAccounts, string actor)
    {
        if (!confirm) throw new BackupException("Confirm full replacement after restart.", 422);
        var folder = Identity().IsMatch(id) ? Staging(Data, id) : "";
        if (folder.Length == 0 || !File.Exists(Path.Combine(folder, "preview.json"))) throw new BackupException("No staged restore with this identifier.", 404);
        var preview = JsonNode.Parse(File.ReadAllText(Path.Combine(folder, "preview.json")))!;
        if ((string?)preview["archive_sha256"] != sha256 || Sha(Path.Combine(folder, "upload.slbak")) != sha256) throw new BackupException("The staged archive changed. Upload it again.");
        if (preview["preview"]?["accounts"] is JsonObject && !confirmAccounts) throw new BackupException("Acknowledge the account and password rollback and the sign-out of all sessions.", 422);
        if (BackupKeys.Host(Data) is null) throw new BackupException("Configure a protected host backup key first: the current data is saved as an encrypted recovery backup before restore.");
        if (File.Exists(PendingFile(Data))) throw new BackupException("A restore is already waiting for restart.");
        BackupKeys.WriteAtomic(PendingFile(Data), new JsonObject { ["id"] = id, ["sha256"] = sha256, ["requested_at"] = Stamp(clock.GetUtcNow()), ["actor"] = actor }.ToJsonString());
        WriteOperation(Data, new JsonObject
        {
            ["id"] = id, ["kind"] = "restore", ["status"] = "waiting_for_restart", ["archive_sha256"] = sha256,
            ["message"] = "Restore confirmed. Restart the service or application to apply it; an encrypted recovery backup of the current data is created first.",
        });
        return Status();
    }

    /// <summary>Cancels a confirmed restore that has not been applied yet; the staged copy stays until discarded.</summary>
    public JsonObject Cancel()
    {
        if (!File.Exists(PendingFile(Data))) throw new BackupException("No pending operation to cancel.");
        File.Delete(PendingFile(Data));
        var operation = ReadOperation(Data);
        operation["status"] = "cancelled";
        operation["message"] = "Pending restore cancelled. No application data was changed.";
        WriteOperation(Data, operation);
        return Status();
    }

    // ---- restore: applied at start, before the database opens

    private static readonly string[] Sidecars = ["", "-wal", "-shm", "-journal"];

    /// <summary>Applies a confirmed restore. Order: re-verify the staged copy, write the encrypted destination recovery backup, move the current files aside,
    /// move the staged files in, verify; on any failure the current files are moved back and the operation is reported as failed. Returns a log message.</summary>
    public static string? ApplyPending(string data, DateTimeOffset now)
    {
        var pendingPath = PendingFile(data);
        if (!File.Exists(pendingPath)) return null;
        JsonObject pending;
        try { pending = JsonNode.Parse(File.ReadAllText(pendingPath)) as JsonObject ?? throw new FormatException(); }
        catch (Exception error) when (error is IOException or System.Text.Json.JsonException or FormatException) { return Fail(data, null, "The pending restore record is unreadable; nothing was changed."); }
        var id = (string?)pending["id"] ?? "";
        if (!Identity().IsMatch(id)) return Fail(data, null, "The pending restore record is invalid; nothing was changed.");
        var folder = Staging(data, id);
        var staged = Path.Combine(folder, "staged");
        var previous = Path.Combine(folder, "previous");
        var moved = new List<(string From, string To)>();
        try
        {
            if (!File.Exists(Path.Combine(folder, "upload.slbak")) || Sha(Path.Combine(folder, "upload.slbak")) != (string?)pending["sha256"]) throw new BackupException("The staged archive changed after confirmation.");
            var manifest = JsonNode.Parse(File.ReadAllText(Path.Combine(staged, ManifestEntry)))!.AsObject();
            foreach (var file in manifest["files"]!.AsArray())
                if (Sha(StagedPath(staged, (string)file!["path"]!)) != (string?)file["sha256"]) throw new BackupException("A staged file changed after confirmation.");
            // A fresh installation has no data to protect; otherwise the current data is first saved as an encrypted recovery backup.
            var fresh = !File.Exists(Path.Combine(data, DatabaseEntry)) && !File.Exists(Path.Combine(data, LegacyDatabaseEntry)) && !File.Exists(Path.Combine(data, AccountsEntry));
            string? destinationSha = null;
            if (!fresh)
            {
                var host = BackupKeys.Host(data) ?? throw new BackupException("The host backup key is not available, so no recovery backup can be written.");
                (destinationSha, _, _) = WriteArchive(data, Path.Combine(data, "backups", DestinationName(id)), "", host, "destination-before-restore", now);
            }
            Directory.CreateDirectory(previous);
            void Move(string from, string to) { Directory.CreateDirectory(Path.GetDirectoryName(to)!); if (Directory.Exists(from)) Directory.Move(from, to); else File.Move(from, to); moved.Add((from, to)); }
            foreach (var suffix in Sidecars)
                if (File.Exists(Path.Combine(data, DatabaseEntry + suffix))) Move(Path.Combine(data, DatabaseEntry + suffix), Path.Combine(previous, DatabaseEntry + suffix));
            foreach (var suffix in Sidecars)
                if (File.Exists(Path.Combine(data, AccountsEntry + suffix))) Move(Path.Combine(data, AccountsEntry + suffix), Path.Combine(previous, AccountsEntry + suffix));
            if (Directory.Exists(Path.Combine(data, "branding"))) Move(Path.Combine(data, "branding"), Path.Combine(previous, "branding"));
            if (Directory.Exists(Path.Combine(data, "sources"))) Move(Path.Combine(data, "sources"), Path.Combine(previous, "sources"));
            Move(Path.Combine(staged, DatabaseEntry), Path.Combine(data, DatabaseEntry));
            if (File.Exists(Path.Combine(staged, AccountsEntry))) Move(Path.Combine(staged, AccountsEntry), Path.Combine(data, AccountsEntry));
            else if (File.Exists(Path.Combine(previous, AccountsEntry))) { File.Copy(Path.Combine(previous, AccountsEntry), Path.Combine(data, AccountsEntry)); Execute(Path.Combine(data, AccountsEntry), "DELETE FROM sessions;"); }
            if (Directory.Exists(Path.Combine(staged, "branding"))) Move(Path.Combine(staged, "branding"), Path.Combine(data, "branding"));
            if (Directory.Exists(Path.Combine(staged, "sources"))) Move(Path.Combine(staged, "sources"), Path.Combine(data, "sources"));
            ManagedSourceFiles.RestorePaths(data);
            Integrity(Path.Combine(data, DatabaseEntry));
            File.Delete(pendingPath);
            WriteOperation(data, new JsonObject
            {
                ["id"] = id, ["kind"] = "restore", ["status"] = "completed", ["completed_at"] = Stamp(now), ["destination_sha256"] = destinationSha, ["archive_sha256"] = pending["sha256"]?.DeepClone(),
                ["message"] = fresh ? "Restore completed into a new installation. All sessions were signed out." : "Restore completed. All sessions were signed out. The previous data is kept as an encrypted destination recovery backup.",
            });
            Retention.DataRetention.AfterRestore(data, now);
            return fresh ? $"Restore {id} applied to a new installation" : $"Restore {id} applied; destination recovery backup {DestinationName(id)}";
        }
        catch (Exception error) when (error is BackupException or IOException or UnauthorizedAccessException or SqliteException or System.Text.Json.JsonException or InvalidOperationException)
        {
            // Roll back in reverse order: the current data returns exactly as it was.
            for (var i = moved.Count - 1; i >= 0; i--)
            {
                var (from, to) = moved[i];
                try { if (Directory.Exists(to)) Directory.Move(to, from); else if (File.Exists(to)) File.Move(to, from, overwrite: true); } catch (IOException) { }
            }
            try { File.Delete(pendingPath); } catch (IOException) { }
            return Fail(data, id, "Restore failed and was rolled back; the current data is unchanged. " + (error is BackupException ? error.Message : "Check storage and the staged archive."));
        }
    }

    private static string Fail(string data, string? id, string message)
    {
        try { File.Delete(PendingFile(data)); } catch (IOException) { }
        WriteOperation(data, new JsonObject { ["id"] = id, ["kind"] = "restore", ["status"] = "failed", ["completed_at"] = Stamp(DateTimeOffset.UtcNow), ["message"] = message });
        return message;
    }
}
