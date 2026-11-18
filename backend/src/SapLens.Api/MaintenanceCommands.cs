using System.Text.Json.Nodes;
using Microsoft.Data.Sqlite;
using Microsoft.EntityFrameworkCore;
using SapLens.Application.Backups;
using SapLens.Domain.Json;
using SapLens.Persistence;

namespace SapLens.Api;

/// <summary>Local, non-listening maintenance commands of the server binary for operators and the deployment script. None starts the server.
/// Inspection/backup commands do not change source data; explicit account administration and copy-only upload rebasing do write
/// their selected local store. Output is one JSON document on standard output, refusals go to standard error with exit code 3.
///
/// <list type="bullet">
/// <item><c>--inspect-data --data-dir D</c>: integrity/schema/source-path inspection of private scratch copies; original SQLite is never opened.</item>
/// <item><c>--rebase-upload-paths OLD --migration-copy --expected-db-sha SHA --data-dir COPY</c>: checked private-upload location changes in a
/// separate offline migration copy; external paths and immutable imported records remain unchanged.</item>
/// <item><c>--schema-info --data-dir D</c>: migrations this build knows, migrations the database applied, and whether this build can open it
/// (opened read-only; a missing database is reported, never created).</item>
/// <item><c>--backup-local DIR --data-dir D</c>: a verified, host-key encrypted archive of the data directory (online SQLite copies, so the running
/// service keeps serving), written to DIR. Needs the configured host backup key.</item>
/// <item><c>--backup-verify FILE --data-dir D</c>: decrypts an archive with the host key and runs the full restore validation (manifest hashes,
/// SQLite integrity, known migrations, an enabled administrator if accounts are included) in a temporary folder that is removed afterwards.</item>
/// </list></summary>
public static class MaintenanceCommands
{
    public static readonly string[] Names = ["--schema-info", "--inspect-data", "--backup-local", "--backup-verify", "--accounts-code", "--rebase-upload-paths"];

    public static bool Handles(string[] args) => Names.Any(args.Contains);

    public static int Run(string[] args)
    {
        try
        {
            string? Value(string name) { var i = Array.IndexOf(args, name); return i >= 0 && i + 1 < args.Length && !args[i + 1].StartsWith("--", StringComparison.Ordinal) ? args[i + 1] : null; }
            var data = Value("--data-dir") ?? Environment.GetEnvironmentVariable("SAP_LENS_V2_DATA_DIR") ?? throw new InvalidOperationException("--data-dir (or SAP_LENS_V2_DATA_DIR) is required.");
            if (!Path.IsPathFullyQualified(data)) throw new InvalidOperationException("--data-dir must be an absolute path.");
            data = Path.GetFullPath(data);
            JsonObject result;
            if (args.Contains("--rebase-upload-paths"))
            {
                if (!args.Contains("--migration-copy") || Names.Count(args.Contains) != 1)
                    throw new InvalidOperationException("Upload rebasing requires --migration-copy and exactly one maintenance command.");
                result = RebaseUploadedPaths(data, Value("--rebase-upload-paths") ?? throw new InvalidOperationException("Select the original data directory."),
                    Value("--expected-db-sha") ?? throw new InvalidOperationException("The verified copy's --expected-db-sha is required."));
            }
            else if (args.Contains("--accounts-code"))
            {
                result = AdministratorCode(data, Value("--recover-administrator"));
            }
            else if (args.Contains("--inspect-data")) result = InspectData(data);
            else if (args.Contains("--schema-info")) result = SchemaInfo(data);
            else if (Value("--backup-local") is { } folder) result = BackupLocal(data, folder, DateTimeOffset.UtcNow);
            else if (Value("--backup-verify") is { } file) result = BackupVerify(data, file);
            else throw new InvalidOperationException("--backup-local and --backup-verify need a path.");
            Console.Out.WriteLine(result.ToJsonString(new System.Text.Json.JsonSerializerOptions { WriteIndented = true }));
            return 0;
        }
        catch (Exception error) when (error is InvalidOperationException or BackupException or IOException or UnauthorizedAccessException or SqliteException or System.Text.Json.JsonException or SapLens.Application.Accounts.AuthException)
        {
            Console.Error.WriteLine($"maintenance refused: {error.Message}");
            return 3;
        }
    }

    /// <summary>Rebase only verified copies of application-managed uploads after a directory move. Never opens the original database.</summary>
    public static JsonObject RebaseUploadedPaths(string data, string sourceData, string expectedHash)
    {
        if (!Path.IsPathFullyQualified(data) || !Path.IsPathFullyQualified(sourceData)) throw new InvalidOperationException("Select absolute source and copy directories.");
        var comparison = OperatingSystem.IsWindows() ? StringComparison.OrdinalIgnoreCase : StringComparison.Ordinal;
        data = Path.GetFullPath(data).TrimEnd(Path.DirectorySeparatorChar);
        sourceData = Path.GetFullPath(sourceData).TrimEnd(Path.DirectorySeparatorChar);
        var oldPrefix = sourceData + Path.DirectorySeparatorChar;
        var newPrefix = data + Path.DirectorySeparatorChar;
        if (data.Equals(sourceData, comparison) || data.StartsWith(oldPrefix, comparison) || sourceData.StartsWith(newPrefix, comparison))
            throw new InvalidOperationException("Upload rebasing requires a separate, disjoint migration copy.");
        void Plain(string path)
        {
            for (string? item = path; item is not null; item = Path.GetDirectoryName(item))
                if ((File.Exists(item) || Directory.Exists(item)) && (File.GetAttributes(item) & FileAttributes.ReparsePoint) != 0)
                    throw new InvalidOperationException("Migration copy paths must not traverse links.");
        }
        Plain(data); Plain(sourceData);
        var database = Path.Combine(data, ApplicationBackups.DatabaseEntry);
        if (expectedHash.Length != 64 || !expectedHash.All(Uri.IsHexDigit) || !File.Exists(database) || !Digests.File(database).Equals(expectedHash, StringComparison.OrdinalIgnoreCase))
            throw new InvalidOperationException("The migration copy does not match its expected database SHA-256.");
        if (!(bool)SchemaInfo(data)["compatible"]! || !DatabaseMaintenance.VerifyFileAsync(database).GetAwaiter().GetResult().Ok)
            throw new InvalidOperationException("The migration copy has incompatible schema or failed integrity checks.");
        using var connection = new SqliteConnection(new SqliteConnectionStringBuilder { DataSource = database, Mode = SqliteOpenMode.ReadWrite, Pooling = false }.ToString());
        connection.Open();
        using var transaction = connection.BeginTransaction(deferred: false);
        using var command = connection.CreateCommand(); command.Transaction = transaction;
        command.CommandText = "SELECT Revision,Json FROM Settings WHERE Id=1";
        JsonObject? settings = null; var revision = 0;
        using (var reader = command.ExecuteReader())
            if (reader.Read()) { revision = reader.GetInt32(0); settings = JsonNode.Parse(reader.GetString(1))!.AsObject(); }
        var changed = new JsonArray();
        foreach (var (field, source) in new[] { ("data_csv_path", "roles"), ("user_csv_path", "users"), ("employee_csv_path", "employees"), ("sod_csv_path", "sod") })
        {
            if ((string?)settings?[field] is not { Length: > 0 } path || !Path.IsPathFullyQualified(path)) continue;
            path = Path.GetFullPath(path);
            if (!path.StartsWith(oldPrefix, comparison)) continue;
            var relative = Path.GetRelativePath(sourceData, path);
            if (!System.Text.RegularExpressions.Regex.IsMatch(relative.Replace('\\', '/'), @"\Asources/" + source + @"-[a-f0-9]{16}\.csv\z"))
                throw new InvalidOperationException("A source inside the old data directory is not an application-managed upload; review it explicitly.");
            var target = Path.Combine(data, relative); Plain(path); Plain(target);
            if (File.Exists(path) != File.Exists(target) || File.Exists(path) && Digests.File(path) != Digests.File(target))
                throw new InvalidOperationException("An application-managed upload differs from its copied source.");
            settings![field] = target; changed.Add(field);
        }
        if (changed.Count > 0)
        {
            command.CommandText = "UPDATE Settings SET Json=$json,Revision=Revision+1,UpdatedUtc=$now,UpdatedBy='directory-migration' WHERE Id=1 AND Revision=$revision";
            command.Parameters.AddWithValue("$json", settings!.ToJsonString());
            command.Parameters.AddWithValue("$now", DateTime.UtcNow);
            command.Parameters.AddWithValue("$revision", revision);
            if (command.ExecuteNonQuery() != 1) throw new InvalidOperationException("Migration copy settings changed during rebasing.");
        }
        transaction.Commit();
        return new JsonObject { ["rebased"] = changed.Count, ["changed_fields"] = changed, ["settings_revision"] = revision + (changed.Count > 0 ? 1 : 0) };
    }

    /// <summary>The migrations compiled into this build.</summary>
    public static JsonObject AdministratorCode(string data, string? username)
    {
        if (!Directory.Exists(data)) throw new InvalidOperationException("Select an existing application data directory.");
        var store = new SapLens.Application.Accounts.AccountStore(SapLens.Application.Accounts.AccountStore.For(data), TimeProvider.System);
        store.Prepare();
        var issued = store.IssueAsync(username).GetAwaiter().GetResult();
        return new JsonObject { ["code"] = issued.Code, ["purpose"] = issued.Purpose, ["expires"] = issued.Expires };
    }

    /// <summary>The migrations compiled into this build.</summary>
    public static List<string> KnownMigrations()
    {
        var builder = new DbContextOptionsBuilder<SapLensDb>();
        builder.UseSqlite("Data Source=:memory:");
        using var db = new SapLensDb(builder.Options);
        return [.. db.Database.GetMigrations()];
    }

    public static JsonObject SchemaInfo(string data)
    {
        var known = KnownMigrations();
        var database = Path.Combine(data, ApplicationBackups.DatabaseEntry);
        var applied = new List<string>();
        if (File.Exists(database))
        {
            using var connection = new SqliteConnection(new SqliteConnectionStringBuilder { DataSource = database, Mode = SqliteOpenMode.ReadOnly, Pooling = false }.ToString());
            connection.Open();
            using var command = connection.CreateCommand();
            command.CommandText = "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='__EFMigrationsHistory'";
            if (Convert.ToInt64(command.ExecuteScalar(), System.Globalization.CultureInfo.InvariantCulture) > 0)
            {
                command.CommandText = "SELECT MigrationId FROM __EFMigrationsHistory ORDER BY MigrationId";
                using var reader = command.ExecuteReader();
                while (reader.Read()) applied.Add(reader.GetString(0));
            }
        }
        var unknown = applied.Where(m => !known.Contains(m)).ToList();
        return new JsonObject
        {
            ["product_version"] = ProductIdentity.Version, ["database_exists"] = File.Exists(database),
            ["known"] = new JsonArray([.. known.Select(m => (JsonNode?)m)]), ["applied"] = new JsonArray([.. applied.Select(m => (JsonNode?)m)]),
            ["unknown_applied"] = new JsonArray([.. unknown.Select(m => (JsonNode?)m)]),
            ["pending"] = new JsonArray([.. known.Where(m => !applied.Contains(m)).Select(m => (JsonNode?)m)]),
            // This build opens the database unchanged or after its own migrations; a database with migrations it does not know was written by a newer build.
            ["compatible"] = unknown.Count == 0,
        };
    }

    /// <summary>Inspect a private scratch copy, including WAL, without opening any source database in SQLite.
    /// A changing source is refused; the final authoritative inspection is repeated after service shutdown.</summary>
    public static JsonObject InspectData(string data)
    {
        if (!Directory.Exists(data)) throw new InvalidOperationException("The data directory does not exist.");
        var files = new List<string>();
        void Visit(string folder)
        {
            foreach (var entry in Directory.EnumerateFileSystemEntries(folder))
            {
                var attributes = File.GetAttributes(entry);
                if ((attributes & FileAttributes.ReparsePoint) != 0) throw new InvalidOperationException("Data contains a reparse point; inspect it manually.");
                if ((attributes & FileAttributes.Directory) != 0) Visit(entry);
                else files.Add(entry);
            }
        }
        Visit(data);
        var databases = files.Where(f => f.EndsWith(".sqlite3", StringComparison.OrdinalIgnoreCase) || f.EndsWith(".db", StringComparison.OrdinalIgnoreCase)).ToArray();
        if (!databases.Contains(Path.Combine(data, ApplicationBackups.DatabaseEntry), StringComparer.OrdinalIgnoreCase))
            throw new InvalidOperationException("The SAP Lens database is missing.");
        var scratch = Directory.CreateTempSubdirectory("saplens-inspect-").FullName;
        static string SharedHash(string path)
        {
            using var input = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete);
            return Convert.ToHexString(System.Security.Cryptography.SHA256.HashData(input));
        }
        try
        {
            var results = new JsonArray();
            foreach (var database in databases)
            {
                var relative = Path.GetRelativePath(data, database);
                var target = Path.Combine(scratch, relative);
                Directory.CreateDirectory(Path.GetDirectoryName(target)!);
                // SHM is a disposable WAL index with Windows byte-range locks, not durable data.
                // SQLite rebuilds it in scratch from the copied database and WAL. Never read the live lock bytes.
                var inputs = new[] { database, database + "-wal", database + "-journal" }.Where(File.Exists).ToArray();
                var sidecars = new[] { database + "-wal", database + "-shm", database + "-journal" }.Where(File.Exists).Select(Path.GetFileName).ToArray();
                var hashes = inputs.ToDictionary(f => f, SharedHash);
                foreach (var input in inputs)
                {
                    using var source = new FileStream(input, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete);
                    using var destination = new FileStream(target + input[database.Length..], FileMode.CreateNew, FileAccess.Write);
                    source.CopyTo(destination);
                }
                if (inputs.Any(f => !File.Exists(f) || hashes[f] != SharedHash(f)) ||
                    new[] { database + "-wal", database + "-journal" }.Any(f => File.Exists(f) && !inputs.Contains(f)))
                    throw new InvalidOperationException("The database changed during inspection. Repeat during a quiet period.");
                var integrity = DatabaseMaintenance.VerifyFileAsync(target).GetAwaiter().GetResult();
                results.Add(new JsonObject { ["file"] = relative, ["ok"] = integrity.Ok, ["sidecars"] = new JsonArray([.. sidecars.Select(f => (JsonNode?)f)]) });
            }
            var schema = SchemaInfo(scratch);
            var sourcePaths = new JsonObject();
            using (var connection = new SqliteConnection(new SqliteConnectionStringBuilder { DataSource = Path.Combine(scratch, ApplicationBackups.DatabaseEntry), Mode = SqliteOpenMode.ReadOnly, Pooling = false }.ToString()))
            {
                connection.Open();
                using var command = connection.CreateCommand();
                command.CommandText = "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='Settings'";
                if (Convert.ToInt64(command.ExecuteScalar(), System.Globalization.CultureInfo.InvariantCulture) > 0)
                {
                    command.CommandText = "SELECT Json FROM Settings WHERE Id=1";
                    if (command.ExecuteScalar() is string json)
                    {
                        var settings = JsonNode.Parse(json)!.AsObject();
                        foreach (var field in V1Settings.PathFields)
                            if ((string?)settings[field] is { Length: > 0 } path) sourcePaths[field] = path;
                    }
                }
            }
            return new JsonObject { ["ok"] = results.All(r => (bool)r!["ok"]!), ["databases"] = results, ["schema"] = schema, ["source_paths"] = sourcePaths,
                ["capabilities"] = new JsonArray("rebase-upload-paths-v1") };
        }
        finally
        {
            Directory.Delete(scratch, true);
        }
    }

    public static JsonObject BackupLocal(string data, string folder, DateTimeOffset now)
    {
        if (!Path.IsPathFullyQualified(folder)) throw new InvalidOperationException("--backup-local needs an absolute folder.");
        var host = BackupKeys.Host(data) ?? throw new BackupException("Configure the host backup key first (--backup-key create|use); pre-deployment backups are always encrypted.");
        Directory.CreateDirectory(folder);
        var target = Path.Combine(folder, $"sap-lens-2-{now.UtcDateTime:yyyyMMdd'T'HHmmss'Z'}-{Guid.NewGuid().ToString("N")[..8]}.slbak");
        var (sha, size, manifest) = ApplicationBackups.WriteArchive(data, target, "", host, "pre-deployment", now);   // verified by decryption before it is kept
        return new JsonObject
        {
            ["file"] = target, ["sha256"] = sha, ["size"] = size, ["key_fingerprint"] = BackupKeys.Fingerprint(host), ["created"] = manifest["created"]?.DeepClone(),
            ["files"] = manifest["files"]!.AsArray().Count, ["migrations"] = manifest["migrations"]?.DeepClone(), ["accounts"] = manifest["accounts"]?.DeepClone(),
        };
    }

    public static JsonObject BackupVerify(string data, string file)
    {
        if (!Path.IsPathFullyQualified(file) || !File.Exists(file)) throw new InvalidOperationException("--backup-verify needs an existing archive path.");
        var host = BackupKeys.Host(data) ?? throw new BackupException("The host backup key is not configured for this data directory.");
        var work = Path.Combine(Path.GetTempPath(), "saplens2-verify-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(work);
        try
        {
            var zip = Path.Combine(work, "payload.zip");
            using (var input = File.OpenRead(file))
            using (var output = new FileStream(zip, FileMode.CreateNew, FileAccess.Write))
                BackupArchive.Unseal(input, output, "", host);
            var manifest = ApplicationBackups.Extract(zip, Path.Combine(work, "staged"), KnownMigrations());
            SqliteConnection.ClearAllPools();
            return new JsonObject
            {
                ["file"] = file, ["sha256"] = Digests.File(file), ["verified"] = true, ["created"] = manifest["created"]?.DeepClone(), ["version"] = manifest["version"]?.DeepClone(),
                ["files"] = manifest["files"]!.AsArray().Count, ["accounts"] = manifest["accounts"]?.DeepClone(),
            };
        }
        finally
        {
            SqliteConnection.ClearAllPools();
            try { Directory.Delete(work, true); } catch (IOException) { }
        }
    }
}
