using System.Text.Json.Nodes;
using Microsoft.Data.Sqlite;
using Microsoft.EntityFrameworkCore;
using SapLens.Application.Backups;
using SapLens.Domain.Json;
using SapLens.Persistence;

namespace SapLens.Api;

/// <summary>Local, non-listening maintenance commands of the server binary for operators and the deployment script. None of them starts the server or
/// changes application data; output is one JSON document on standard output, refusals go to standard error with exit code 3.
///
/// <list type="bullet">
/// <item><c>--schema-info --data-dir D</c>: migrations this build knows, migrations the database applied, and whether this build can open it
/// (opened read-only; a missing database is reported, never created).</item>
/// <item><c>--backup-local DIR --data-dir D</c>: a verified, host-key encrypted archive of the data directory (online SQLite copies, so the running
/// service keeps serving), written to DIR. Needs the configured host backup key.</item>
/// <item><c>--backup-verify FILE --data-dir D</c>: decrypts an archive with the host key and runs the full restore validation (manifest hashes,
/// SQLite integrity, known migrations, an enabled administrator if accounts are included) in a temporary folder that is removed afterwards.</item>
/// </list></summary>
public static class MaintenanceCommands
{
    public static readonly string[] Names = ["--schema-info", "--inspect-data", "--backup-local", "--backup-verify", "--accounts-code"];

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
            if (args.Contains("--accounts-code"))
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
        catch (Exception error) when (error is InvalidOperationException or BackupException or IOException or UnauthorizedAccessException or SqliteException or SapLens.Application.Accounts.AuthException)
        {
            Console.Error.WriteLine($"maintenance refused: {error.Message}");
            return 3;
        }
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
            return new JsonObject { ["ok"] = results.All(r => (bool)r!["ok"]!), ["databases"] = results, ["schema"] = schema, ["source_paths"] = sourcePaths };
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
