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
    public static readonly string[] Names = ["--schema-info", "--backup-local", "--backup-verify"];

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
            if (args.Contains("--schema-info")) result = SchemaInfo(data);
            else if (Value("--backup-local") is { } folder) result = BackupLocal(data, folder, DateTimeOffset.UtcNow);
            else if (Value("--backup-verify") is { } file) result = BackupVerify(data, file);
            else throw new InvalidOperationException("--backup-local and --backup-verify need a path.");
            Console.Out.WriteLine(result.ToJsonString(new System.Text.Json.JsonSerializerOptions { WriteIndented = true }));
            return 0;
        }
        catch (Exception error) when (error is InvalidOperationException or BackupException or IOException or UnauthorizedAccessException or SqliteException)
        {
            Console.Error.WriteLine($"maintenance refused: {error.Message}");
            return 3;
        }
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
