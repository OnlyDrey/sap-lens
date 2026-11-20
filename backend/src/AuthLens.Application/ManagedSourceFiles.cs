using System.Security.Cryptography;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;
using Microsoft.Data.Sqlite;
using AuthLens.Persistence;

namespace AuthLens.Application;

/// <summary>Immutable CSV copies referenced by dataset reports. Existing SQLite transactions coordinate their lifetime with backups.</summary>
public static partial class ManagedSourceFiles
{
    [GeneratedRegex("\\Asources/(roles|users|sod|employees)-[a-f0-9]{64}\\.csv\\z")]
    public static partial Regex EntryPattern();

    private static void Plain(string path)
    {
        for (string? item = Path.GetFullPath(path); item is not null; item = Path.GetDirectoryName(item))
            if ((File.Exists(item) || Directory.Exists(item)) && (File.GetAttributes(item) & FileAttributes.ReparsePoint) != 0)
                throw new IOException("Managed source paths must not traverse links.");
    }

    private static string Hash(string path)
    {
        using var input = File.OpenRead(path);
        return Convert.ToHexStringLower(SHA256.HashData(input));
    }

    public static JsonObject Capture(string data, string source, string input, string fileName)
    {
        if (!Sources.IsKnown(source)) throw new InvalidOperationException("Unknown managed source.");
        Plain(data); Plain(input);
        var folder = Path.Combine(data, "sources"); Plain(folder); Directory.CreateDirectory(folder);
        var temporary = Path.Combine(folder, Guid.NewGuid().ToString("N") + ".part");
        try
        {
            File.Copy(input, temporary, overwrite: false);
            var hash = Hash(temporary);
            var entry = $"sources/{source}-{hash}.csv";
            var target = Resolve(data, entry);
            if (File.Exists(target))
            {
                if (Hash(target) != hash) throw new IOException("A managed source copy failed its checksum.");
            }
            else File.Move(temporary, target);
            return new JsonObject { ["path"] = entry, ["sha256"] = hash, ["file_name"] = Path.GetFileName(fileName) };
        }
        finally { if (File.Exists(temporary)) File.Delete(temporary); }
    }

    public static string Resolve(string data, string entry)
    {
        if (!EntryPattern().IsMatch(entry)) throw new IOException("Invalid managed source path.");
        var path = Path.Combine(Path.GetFullPath(data), entry.Replace('/', Path.DirectorySeparatorChar));
        Plain(path);
        return path;
    }

    public static Dictionary<string, string> References(string database)
    {
        using var connection = new SqliteConnection(new SqliteConnectionStringBuilder { DataSource = database, Mode = SqliteOpenMode.ReadOnly, Pooling = false }.ToString());
        connection.Open();
        using var command = connection.CreateCommand();
        command.CommandText = "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='Datasets'";
        if (Convert.ToInt64(command.ExecuteScalar()) == 0) return new Dictionary<string, string>(StringComparer.Ordinal);
        command.CommandText = "SELECT Source,ReportJson FROM Datasets WHERE Status IN ('Active','Held') AND ReportJson IS NOT NULL";
        using var reader = command.ExecuteReader();
        var references = new Dictionary<string, string>(StringComparer.Ordinal);
        while (reader.Read())
        {
            var source = reader.GetString(0);
            var copy = JsonNode.Parse(reader.GetString(1))?["managed_source"];
            if (copy is null) continue; // archives written before managed copies remain supported
            var entry = (string?)copy["path"] ?? ""; var hash = (string?)copy["sha256"] ?? "";
            if (!Sources.IsKnown(source) || !entry.StartsWith("sources/" + source + "-", StringComparison.Ordinal)
                || !EntryPattern().IsMatch(entry) || hash.Length != 64 || !entry.EndsWith(hash + ".csv", StringComparison.Ordinal))
                throw new IOException("Invalid managed source metadata.");
            references[entry] = hash;
        }
        return references;
    }

    public static void CopyForBackup(string data, string databaseCopy, string destination, Action<string> add)
    {
        foreach (var (entry, hash) in References(databaseCopy))
        {
            var original = Resolve(data, entry);
            var target = Resolve(destination, entry);
            Directory.CreateDirectory(Path.GetDirectoryName(target)!);
            File.Copy(original, target);
            if (Hash(target) != hash) throw new IOException("A managed source copy failed its checksum; no backup was published.");
            add(entry);
        }
    }

    public static void Prune(string database)
    {
        // Same main-database write reservation/order as ApplicationBackups.SnapshotLocks: a snapshot's referenced files cannot disappear.
        using var connection = new SqliteConnection(new SqliteConnectionStringBuilder { DataSource = database, Mode = SqliteOpenMode.ReadWrite, Pooling = false, DefaultTimeout = 15 }.ToString());
        connection.Open();
        using var transaction = connection.BeginTransaction(deferred: false);
        var keep = References(database);
        var data = Path.GetDirectoryName(database)!;
        var folder = Path.Combine(data, "sources"); Plain(folder);
        if (!Directory.Exists(folder)) return;
        foreach (var file in Directory.GetFiles(folder, "*.csv"))
        {
            var entry = "sources/" + Path.GetFileName(file);
            if (EntryPattern().IsMatch(entry) && !keep.ContainsKey(entry)) File.Delete(Resolve(data, entry));
        }
        transaction.Commit();
    }

    public static void RestorePaths(string data)
    {
        var database = Path.Combine(data, DatabaseOptions.DatabaseFileName);
        var references = References(database);
        using var connection = new SqliteConnection(new SqliteConnectionStringBuilder { DataSource = database, Mode = SqliteOpenMode.ReadWrite, Pooling = false }.ToString());
        connection.Open(); using var transaction = connection.BeginTransaction(deferred: false);
        using var command = connection.CreateCommand(); command.Transaction = transaction;
        command.CommandText = "SELECT Source,ReportJson FROM Datasets WHERE Status='Active' AND ReportJson IS NOT NULL";
        var active = new Dictionary<string, string>();
        using (var reader = command.ExecuteReader())
            while (reader.Read())
                if (JsonNode.Parse(reader.GetString(1))?["managed_source"]?["path"] is JsonValue value) active[reader.GetString(0)] = (string)value!;
        command.CommandText = "SELECT Json FROM Settings WHERE Id=1";
        if (command.ExecuteScalar() is not string json) return;
        var settings = JsonNode.Parse(json)!.AsObject();
        var fields = new Dictionary<string, string> { [Sources.Roles]="data_csv_path", [Sources.Users]="user_csv_path", [Sources.Sod]="sod_csv_path", [Sources.Employees]="employee_csv_path" };
        foreach (var (source, field) in fields)
        {
            var path = "";
            if (active.TryGetValue(source, out var entry))
            {
                path = Resolve(data, entry);
                if (!File.Exists(path) || Hash(path) != references[entry]) throw new IOException("A restored managed source is missing or differs.");
            }
            // A historical archive has observations but no raw file; never activate the old machine's absolute path.
            settings[field] = path;
            if (settings["source_modes"] is JsonObject modes) modes[source] = "static";
            if (settings["data_lifecycle"]?["sources"]?[source] is JsonObject lifecycle) lifecycle["path"] = path;
        }
        command.CommandText = "UPDATE Settings SET Json=$json,Revision=Revision+1 WHERE Id=1";
        command.Parameters.AddWithValue("$json", settings.ToJsonString()); command.ExecuteNonQuery(); transaction.Commit();
    }
}
