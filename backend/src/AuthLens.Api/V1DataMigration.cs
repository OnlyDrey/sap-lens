using System.IO.Compression;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;
using Microsoft.Data.Sqlite;
using Microsoft.EntityFrameworkCore;
using AuthLens.Application;
using AuthLens.Application.Accounts;
using AuthLens.Application.Backups;
using AuthLens.Domain.Json;
using AuthLens.Persistence;

namespace AuthLens.Api;

/// <summary>SAP Lens 1 to AuthLens data migration, a LOCAL administrator operation of the server binary (--migrate-v1). The v1 data directory (or a
/// v1 .slbak/.tar.gz backup of it) is only ever read. Steps, each explicit:
///
/// 1. preview: inventory with SHA-256 per file, validation of every store, what is imported, preserved or unsupported, blockers, and a digest. Nothing is
///    written outside migration/&lt;id&gt;/ in the v2 data directory.
/// 2. run (needs the preview digest as approval): the source must be unchanged; a verified copy and an encrypted migration backup of it are made, then a
///    separate candidate database is built and verified (integrity, counts, hash chains, content addresses). Active v2 data is not touched.
/// 3. activate (needs the digest again): the candidate replaces the active data at the next start, before anything opens the database. The previous v2
///    files are kept under migration/&lt;id&gt;/previous; any failure rolls back. Existing v2 data is replaced only when the preview was made with
///    --replace-existing, never silently.
/// 4. rollback: puts the previous v2 files back at the next start.
///
/// The migration backup is a BackupKind.Migration record in the migrated database: Settings, Storage shows it until an administrator confirms the upgrade,
/// and no retention ever removes it.</summary>
public static partial class V1DataMigration
{
    [GeneratedRegex("^[a-f0-9]{64}$")] private static partial Regex Hex64();
    [GeneratedRegex("^[a-f0-9]{32}$")] private static partial Regex Hex32();

    private static readonly string[] SourceKinds = ["roles", "users", "sod"];
    /// <summary>v1 JSON stores copied into AuthLens documents of the same v1 shape (v1 file, v2 document).</summary>
    private static readonly (string File, string Document)[] Documents =
    [
        ("functional-groups.json", FunctionalGroupStore.Document), ("report-branding.json", "report-branding"), ("reviewer-profile.json", "reviewer-profile"),
        ("sod-periods.json", SodPeriodStore.Document), ("sod-reviews.json", SodReviewStore.Document), ("sod-catalogue.json", "catalogue"), ("sod-reference.json", "reference"),
        ("assignment-lifecycle.json", AssignmentLifecycle.Document), ("position-changes.json", PositionChangeStore.Document), ("sod-observations.json", "sod-observations"),
    ];
    private static readonly string[] Copied = ["refresh-schedule.json"];
    private static readonly string[] Ignored = ["sap-lens.log", ".key", "data-retention.json", "settings.json.tmp"];
    private const long MaxSource = 2L * 1024 * 1024 * 1024;

    private static string Root(string data) => Path.Combine(data, "migration");
    private static string Folder(string data, string id) => Path.Combine(Root(data), id);
    private static string PendingActivation(string data) => Path.Combine(Root(data), "pending-activation.json");
    private static string PendingRollback(string data) => Path.Combine(Root(data), "pending-rollback.json");
    private static string Stamp(DateTimeOffset now) => now.UtcDateTime.ToString("yyyy-MM-dd'T'HH:mm:ss.ffffff'+00:00'");
    private static string Sha(string path) => Digests.File(path);
    private static string Sha(byte[] bytes) => Digests.Bytes(bytes);
    private static void Save(string path, JsonNode value) { Directory.CreateDirectory(Path.GetDirectoryName(path)!); BackupKeys.WriteAtomic(path, value.ToJsonString(new JsonSerializerOptions { WriteIndented = true, Encoder = System.Text.Encodings.Web.JavaScriptEncoder.UnsafeRelaxedJsonEscaping })); }
    private static JsonObject Load(string path) => JsonNode.Parse(File.ReadAllText(path)) as JsonObject ?? throw new MigrationException("A migration record is unreadable.");

    // ---- source

    /// <summary>Every regular file under the v1 directory (links refused), with size and SHA-256, ordered by path.</summary>
    public static JsonArray Inventory(string root)
    {
        var files = new JsonArray();
        long total = 0;
        foreach (var path in Directory.EnumerateFiles(root, "*", new EnumerationOptions { RecurseSubdirectories = true, AttributesToSkip = 0 }).Order(StringComparer.Ordinal))
        {
            var info = new FileInfo(path);
            if (info.LinkTarget is not null) throw new MigrationException($"The v1 directory contains a link ({Path.GetRelativePath(root, path)}); copy the data without links first.");
            for (var dir = info.Directory; dir is not null && dir.FullName.Length > root.TrimEnd(Path.DirectorySeparatorChar).Length; dir = dir.Parent)
                if (dir.LinkTarget is not null) throw new MigrationException("The v1 directory contains a linked folder; copy the data without links first.");
            total += info.Length;
            if (total > MaxSource) throw new MigrationException("The v1 data exceeds 2 GiB; migrate from a copy without logs and old backups.");
            files.Add(new JsonObject { ["path"] = Path.GetRelativePath(root, path).Replace('\\', '/'), ["size"] = info.Length, ["sha256"] = Sha(path) });
        }
        return files;
    }

    private static string Fingerprint(JsonArray inventory) => Sha(Encoding.UTF8.GetBytes(string.Join('\n', inventory.Select(f => $"{f!["path"]}:{f["size"]}:{f["sha256"]}"))));

    // ---- reading v1 stores

    /// <summary>A v1 source revision. Its records are read from the content-addressed file only while that revision is imported or verified (one at a
    /// time), and the file is re-verified against its address each time, so a large installation never holds all revisions in memory.</summary>
    private sealed record SourceRevision(string Snapshot, string Kind, string File, int Count, JsonNode? Report, bool Active, DateTime When, string FileName)
    {
        public IEnumerable<Dictionary<string, string>> Records()
        {
            var bytes = System.IO.File.ReadAllBytes(File);
            if (Sha(bytes) != Snapshot) throw new MigrationException($"The {Kind} snapshot {Snapshot} changed during the migration.");
            // A read-only document over the file bytes; one record object at a time (no DOM of the whole revision).
            using var document = JsonDocument.Parse(bytes);
            if (!document.RootElement.TryGetProperty("records", out var records) || records.ValueKind != JsonValueKind.Array) yield break;
            foreach (var record in records.EnumerateArray()) yield return Row(record);
        }
    }

    private sealed class V1Data
    {
        public required string Root;
        public JsonObject Settings = [];
        public List<SourceRevision> Revisions = [];
        public List<(string Id, string File)> Evidence = [];
        public List<(string Name, JsonObject Value)> Documents = [];
        public JsonArray SavedFilters = [];
        public JsonObject AccountReview = [];
        public JsonObject? SodDecisions;
        public List<(string Id, JsonObject Report)> Reports = [];
        public List<string> Branding = [];
        public string? Accounts;
        public List<string> Copied = [];
        public JsonArray Stores = [];
        public JsonArray Blockers = [];
        public JsonArray Warnings = [];
    }

    private static JsonObject? ReadJson(V1Data v1, string relative, bool required = false)
    {
        var path = Path.Combine(v1.Root, relative);
        if (!File.Exists(path)) { if (required) v1.Blockers.Add($"{relative} is missing: this does not look like a SAP Lens 1 data directory."); return null; }
        try { return JsonNode.Parse(File.ReadAllText(path, Encoding.UTF8)) as JsonObject ?? throw new JsonException(); }
        catch (JsonException) { v1.Blockers.Add($"{relative} is not valid JSON; repair it in SAP Lens 1 or restore a v1 backup first."); return null; }
    }

    private static void Store(V1Data v1, string store, string file, string handling, int count, string note = "") =>
        v1.Stores.Add(new JsonObject { ["store"] = store, ["file"] = file, ["handling"] = handling, ["count"] = count, ["note"] = note });

    private static V1Data Read(string root)
    {
        var v1 = new V1Data { Root = root };
        var settings = ReadJson(v1, "settings.json", required: true);
        if (settings is null) return v1;
        v1.Settings = settings;
        var defaults = V1Compatibility.DefaultSettingsDocument();
        var unknown = settings.Select(p => p.Key).Where(k => !defaults.ContainsKey(k)).ToList();
        if (unknown.Count > 0) v1.Warnings.Add($"Settings fields not known to this AuthLens build are kept only in the migration backup: {string.Join(", ", unknown)}.");
        Store(v1, "Settings", "settings.json", "import", 1, unknown.Count > 0 ? $"{unknown.Count} unknown field(s) not imported" : "");

        // Source revisions: every content-addressed v1 snapshot of a known source kind; the ones settings point at are active.
        var lifecycle = settings["data_lifecycle"] as JsonObject;
        var active = new Dictionary<string, (string Snapshot, string When, string Path)>();
        foreach (var kind in SourceKinds)
            if (lifecycle?["sources"]?[kind] is JsonObject s && (string?)s["snapshot"] is { } id) active[kind] = (id, (string?)s["imported_at"] ?? "", (string?)s["path"] ?? "");
        var history = (lifecycle?["sod_history"] as JsonArray ?? []).OfType<JsonObject>().ToDictionary(h => (string?)h["snapshot"] ?? "", h => (string?)h["imported_at"] ?? "");
        var snapshots = Path.Combine(root, "csv-data", "snapshots");
        var evidence = 0;
        if (Directory.Exists(snapshots))
            foreach (var file in Directory.GetFiles(snapshots, "*.json").Order(StringComparer.Ordinal))
            {
                var id = Path.GetFileNameWithoutExtension(file);
                var bytes = File.ReadAllBytes(file);
                if (!Hex64().IsMatch(id) || Sha(bytes) != id) { v1.Blockers.Add($"csv-data/snapshots/{Path.GetFileName(file)} does not match its content address (damaged evidence)."); continue; }
                JsonObject value;
                try { value = JsonNode.Parse(bytes) as JsonObject ?? throw new JsonException(); }
                catch (JsonException) { v1.Blockers.Add($"csv-data/snapshots/{id}.json is not valid JSON."); continue; }
                var kind = (string?)value["source"];
                if (kind is not null && SourceKinds.Contains(kind) && value["records"] is JsonArray records)
                {
                    var isActive = active.TryGetValue(kind, out var a) && a.Snapshot == id;
                    var when = isActive ? a.When : history.GetValueOrDefault(id, "");
                    var stamp = DateTimeOffset.TryParse(when, System.Globalization.CultureInfo.InvariantCulture, System.Globalization.DateTimeStyles.AssumeUniversal, out var t) ? t.UtcDateTime : File.GetLastWriteTimeUtc(file);
                    v1.Revisions.Add(new SourceRevision(id, kind, file, records.Count, value["report"]?.DeepClone(), isActive, stamp, isActive ? Path.GetFileName(a.Path) : ""));
                }
                else { v1.Evidence.Add((id, file)); evidence++; }
            }
        foreach (var kind in SourceKinds)
            if (active.TryGetValue(kind, out var a) && v1.Revisions.All(r => r.Snapshot != a.Snapshot)) v1.Blockers.Add($"The active {kind} snapshot {a.Snapshot} referenced by settings is missing.");
        foreach (var kind in SourceKinds)
            Store(v1, $"Source revisions ({kind})", "csv-data/snapshots", "import", v1.Revisions.Count(r => r.Kind == kind),
                v1.Revisions.Count(r => r.Kind == kind && !r.Active) is var retired and > 0 ? $"{retired} superseded revision(s) kept as retired" : "");
        Store(v1, "Evidence snapshots (SoD decisions, periods, reviews)", "csv-data/snapshots", "import", evidence, "content addresses re-verified");

        // Employee Directory: the active snapshot (settings.employee_snapshot_id) and earlier ones.
        var directory = Path.Combine(root, "employee-directory");
        var employeeActive = (string?)settings["employee_snapshot_id"];
        var employees = 0;
        if (Directory.Exists(directory))
            foreach (var file in Directory.GetFiles(directory, "*.json").Order(StringComparer.Ordinal))
            {
                var id = Path.GetFileNameWithoutExtension(file);
                var bytes = File.ReadAllBytes(file);
                if (!Hex64().IsMatch(id) || Sha(bytes) != id) { v1.Blockers.Add($"employee-directory/{Path.GetFileName(file)} does not match its content address."); continue; }
                var value = JsonNode.Parse(bytes) as JsonObject;
                if (value?["records"] is not JsonArray records) { v1.Warnings.Add($"employee-directory/{id}.json has no records and is kept only in the migration backup."); continue; }
                v1.Revisions.Add(new SourceRevision(id, Sources.Employees, file, records.Count, null, id == employeeActive, File.GetLastWriteTimeUtc(file), (string?)value["file_name"] ?? ""));
                employees++;
            }
        if (employeeActive is not null && v1.Revisions.All(r => r.Snapshot != employeeActive)) v1.Blockers.Add($"The active Employee Directory snapshot {employeeActive} is missing.");
        Store(v1, "Employee Directory revisions", "employee-directory", "import", employees);

        foreach (var (file, document) in Documents)
            if (ReadJson(v1, file) is { } value)
            {
                if (document == FunctionalGroupStore.Document)
                    try { value = FunctionalGroupStore.Validate(value); }
                    catch (FormatException) { v1.Blockers.Add("functional-groups.json failed the v1 storage contract."); continue; }
                v1.Documents.Add((document, value));
                Store(v1, document, file, "import", 1);
            }
        if (ReadJson(v1, "saved-filters.json") is { } filters)
        {
            v1.SavedFilters = filters["items"] as JsonArray ?? [];
            Store(v1, "Saved filters", "saved-filters.json", "import", v1.SavedFilters.Count);
        }
        if (ReadJson(v1, "account-review.json") is { } review)
        {
            if ((int?)review["format"] is not (1 or 2) || review["decisions"] is not JsonObject decisions) v1.Blockers.Add("account-review.json has an unsupported format.");
            else { v1.AccountReview = decisions; Store(v1, "Account review decisions", "account-review.json", "import", decisions.Count, $"{decisions.Sum(d => (d.Value?["history"] as JsonArray)?.Count ?? 0)} earlier event(s)"); }
        }
        if (ReadJson(v1, "sod-decisions.json") is { } sod)
        {
            v1.SodDecisions = sod;
            var events = (sod["contexts"] as JsonObject ?? []).Sum(c => (c.Value as JsonObject ?? []).Sum(k => (k.Value as JsonObject ?? []).Sum(e => (e.Value as JsonArray)?.Count ?? 0)));
            Store(v1, "SoD decision events, remediation actions, report log", "sod-decisions.json", "import", events,
                $"{(sod["actions"] as JsonObject)?.Count ?? 0} action(s), {(sod["reports"] as JsonArray)?.Count ?? 0} report entr(ies)");
        }
        var reports = Path.Combine(root, "csv-data", "reports");
        if (Directory.Exists(reports))
            foreach (var file in Directory.GetFiles(reports, "*.json").Order(StringComparer.Ordinal))
                if (JsonNode.Parse(File.ReadAllText(file)) is JsonObject report) v1.Reports.Add((Path.GetFileNameWithoutExtension(file), report));
        Store(v1, "Refresh and import reports", "csv-data/reports", "import", v1.Reports.Count);
        var branding = Path.Combine(root, "branding");
        if (Directory.Exists(branding)) v1.Branding.AddRange(Directory.GetFiles(branding, "*.png").Where(p => Hex64().IsMatch(Path.GetFileNameWithoutExtension(p))));
        Store(v1, "Branding images", "branding", "import", v1.Branding.Count);
        var accounts = Path.Combine(root, "security", "accounts.sqlite3");
        if (File.Exists(accounts)) { v1.Accounts = accounts; Store(v1, "Accounts (Server mode)", "security/accounts.sqlite3", "import", 1, "sessions are not carried over"); }
        foreach (var name in Copied.Where(n => File.Exists(Path.Combine(root, n)))) { v1.Copied.Add(name); Store(v1, name, name, "import", 1); }
        Store(v1, "Data retention approvals", "data-retention.json", "not migrated", File.Exists(Path.Combine(root, "data-retention.json")) ? 1 : 0, "approvals are bound to the installation; approve again in AuthLens");
        Store(v1, "Application backups of SAP Lens 1", ".application-backups", "not migrated", Directory.Exists(Path.Combine(root, ".application-backups")) ? 1 : 0, "they stay in the SAP Lens 1 directory");
        Store(v1, "Derived SQLite cache", "store/", "not migrated", Directory.Exists(Path.Combine(root, "store")) ? 1 : 0, "rebuilt from the imported data");
        return v1;
    }

    private static Dictionary<string, string> Row(JsonElement record)
    {
        var row = new Dictionary<string, string>(StringComparer.Ordinal);
        if (record.ValueKind != JsonValueKind.Object) return row;
        foreach (var p in record.EnumerateObject()) row[p.Name] = p.Value.ValueKind == JsonValueKind.String ? p.Value.GetString()! : p.Value.ValueKind == JsonValueKind.Null ? "" : p.Value.GetRawText();
        return row;
    }

    /// <summary>The files the stores above cover; everything else in the source is only preserved in the migration backup.</summary>
    private static bool Covered(string path) =>
        path == "settings.json" || path.StartsWith("csv-data/snapshots/", StringComparison.Ordinal) || path.StartsWith("csv-data/reports/", StringComparison.Ordinal) ||
        path.StartsWith("employee-directory/", StringComparison.Ordinal) || path.StartsWith("branding/", StringComparison.Ordinal) || path == "security/accounts.sqlite3" ||
        Documents.Any(d => d.File == path) || Copied.Contains(path) || path is "saved-filters.json" or "account-review.json" or "sod-decisions.json" or "data-retention.json" ||
        path.StartsWith("configuration-backups/", StringComparison.Ordinal) || path.StartsWith("store/", StringComparison.Ordinal) || path.StartsWith(".application-backups/", StringComparison.Ordinal) ||
        Ignored.Contains(path) || path.EndsWith(".log", StringComparison.Ordinal);

    // ---- target

    private static JsonObject TargetState(string data)
    {
        var database = Path.Combine(data, ApplicationBackups.DatabaseEntry);
        var state = new JsonObject { ["database_exists"] = File.Exists(database), ["has_data"] = false, ["accounts_exist"] = File.Exists(AccountStore.For(data)) };
        if (!File.Exists(database)) return state;
        using var db = new SqliteConnection(new SqliteConnectionStringBuilder { DataSource = database, Mode = SqliteOpenMode.ReadOnly, Pooling = false }.ToString());
        db.Open();
        long Count(string table)
        {
            using var c = db.CreateCommand();
            c.CommandText = $"SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='{table}'";
            if (Convert.ToInt64(c.ExecuteScalar(), System.Globalization.CultureInfo.InvariantCulture) == 0) return 0;
            c.CommandText = $"SELECT COUNT(*) FROM \"{table}\"";
            return Convert.ToInt64(c.ExecuteScalar(), System.Globalization.CultureInfo.InvariantCulture);
        }
        var counts = new JsonObject();
        foreach (var table in new[] { "Datasets", "ReviewDecisions", "SodDecisionEvents", "SodDocuments", "SavedFilters", "Settings", "RefreshReports" }) counts[table] = Count(table);
        state["counts"] = counts;
        state["has_data"] = counts.Any(c => (long)c.Value! > 0);
        return state;
    }

    // ---- preview

    /// <summary>Dry run: reads the source, validates every store and describes the result. Writes only migration/&lt;id&gt;/preview.json (and, for an
    /// archive source, its unpacked copy). Returns the preview, whose digest is the approval token for run and activate.</summary>
    public static JsonObject Preview(string source, string data, string secret, bool replaceExisting, DateTimeOffset now)
    {
        if (!Path.IsPathFullyQualified(source) || !Path.IsPathFullyQualified(data)) throw new MigrationException("Use absolute paths for the source and the data directory.");
        var full = Path.GetFullPath(data);
        var id = Guid.NewGuid().ToString("N");
        var folder = Folder(full, id);
        // Unpacked v1 data, copies and candidates are private: owner-only on Unix (Windows inherits the data directory's ACL).
        if (OperatingSystem.IsWindows()) Directory.CreateDirectory(folder);
        else { Directory.CreateDirectory(Root(full), UnixFileMode.UserRead | UnixFileMode.UserWrite | UnixFileMode.UserExecute); Directory.CreateDirectory(folder, UnixFileMode.UserRead | UnixFileMode.UserWrite | UnixFileMode.UserExecute); }
        string root;
        string kind;
        JsonObject? archiveManifest = null;
        if (Directory.Exists(source)) { root = Path.GetFullPath(source); kind = "directory"; }
        else if (File.Exists(source))
        {
            JsonObject header;
            try { (root, header) = V1BackupArchive.Unpack(source, secret, Path.Combine(folder, "unpacked")); }
            catch (BackupException error) { throw new MigrationException(error.Message); }
            kind = "archive";
            archiveManifest = new JsonObject { ["mode"] = header["mode"]?.DeepClone(), ["application_version"] = header["application_version"]?.DeepClone(), ["created_at"] = header["created_at"]?.DeepClone(),
                ["files"] = header["files"]!.AsObject().Count, ["portable"] = header["portable"]?.DeepClone() };
        }
        else throw new MigrationException("The source does not exist.");
        var comparison = OperatingSystem.IsWindows() ? StringComparison.OrdinalIgnoreCase : StringComparison.Ordinal;
        if (kind == "directory" && (full.StartsWith(root.TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar, comparison) || root.StartsWith(full + Path.DirectorySeparatorChar, comparison) || full.Equals(root, comparison)))
            throw new MigrationException("The AuthLens .NET data directory and the SAP Lens 1 source must be separate directories.");
        var inventory = Inventory(root);
        var v1 = Read(root);
        var uncovered = inventory.Select(f => (string)f!["path"]!).Where(p => !Covered(p)).ToList();
        if (uncovered.Count > 0) v1.Warnings.Add($"{uncovered.Count} file(s) are not used by the .NET application and are kept only in the migration backup: {string.Join(", ", uncovered.Take(10))}{(uncovered.Count > 10 ? ", ..." : "")}.");
        var target = TargetState(full);
        if ((bool)target["has_data"]! && !replaceExisting)
            v1.Blockers.Add("The .NET application data directory already contains data. Use an empty data directory, or preview again with --replace-existing to replace it at activation (the current data is kept for rollback).");
        if ((bool)target["accounts_exist"]! && v1.Accounts is not null && !replaceExisting)
            v1.Blockers.Add("The .NET application already has an account store and the source has one too; preview again with --replace-existing to replace it.");
        if (BackupKeys.Host(full) is null) v1.Warnings.Add("No host backup key is configured: the migration backup is stored unencrypted in the private data directory. Configure one first (--backup-key create) to encrypt it.");
        var fingerprint = source.Length > 0 && kind == "archive" ? Sha(source) : Fingerprint(inventory);
        var preview = new JsonObject
        {
            ["id"] = id, ["created"] = Stamp(now), ["status"] = v1.Blockers.Count == 0 ? "previewed" : "blocked", ["source"] = new JsonObject { ["path"] = source, ["kind"] = kind, ["root"] = root, ["fingerprint"] = fingerprint, ["files"] = inventory.Count, ["bytes"] = inventory.Sum(f => (long)f!["size"]!), ["archive"] = archiveManifest },
            ["v1_version"] = (int?)v1.Settings["schema_version"] is { } schema ? $"settings schema {schema}" : "unknown",
            ["target"] = target, ["replace_existing"] = replaceExisting, ["stores"] = v1.Stores.DeepClone(), ["blockers"] = v1.Blockers.DeepClone(), ["warnings"] = v1.Warnings.DeepClone(),
            ["inventory"] = inventory,
        };
        preview["digest"] = Sha(Encoding.UTF8.GetBytes(CanonicalJson.Serialize(new JsonObject
        {
            ["id"] = id, ["fingerprint"] = fingerprint, ["stores"] = preview["stores"]!.DeepClone(), ["blockers"] = preview["blockers"]!.DeepClone(), ["replace_existing"] = replaceExisting,
        })));
        Save(Path.Combine(folder, "preview.json"), preview);
        return preview;
    }

    // ---- run

    /// <summary>Builds and verifies the candidate. Needs the preview digest (administrator approval) and an unchanged source.</summary>
    public static async Task<JsonObject> RunAsync(string data, string id, string digest, string actor, DateTimeOffset now, CancellationToken ct = default)
    {
        data = Path.GetFullPath(data);
        var folder = CheckId(data, id);
        var preview = Load(Path.Combine(folder, "preview.json"));
        if ((string?)preview["digest"] != digest) throw new MigrationException("The approval does not match the preview. Review the preview and pass its digest.");
        if ((string?)preview["status"] != "previewed") throw new MigrationException($"This migration is {(string?)preview["status"]}; only a previewed migration without blockers can run.");
        if (File.Exists(Path.Combine(folder, "report.json"))) throw new MigrationException("This migration already ran. Preview again for a new attempt.");
        var root = (string)preview["source"]!["root"]!;
        var inventory = Inventory(root);
        var fingerprint = (string?)preview["source"]!["kind"] == "archive" ? Sha((string)preview["source"]!["path"]!) : Fingerprint(inventory);
        if (fingerprint != (string?)preview["source"]!["fingerprint"]) throw new MigrationException("The SAP Lens 1 data changed after the preview. Preview again.");
        var report = new JsonObject { ["id"] = id, ["started"] = Stamp(now), ["actor"] = actor, ["status"] = "running" };
        Save(Path.Combine(folder, "report.json"), report);
        try
        {
            // 1. A verified private copy of the source: everything after this reads the copy, never the v1 directory.
            var copy = Path.Combine(folder, "source");
            if (Directory.Exists(copy)) Directory.Delete(copy, true);
            foreach (var file in inventory)
            {
                var relative = (string)file!["path"]!;
                var target = Path.Combine(copy, relative);
                Directory.CreateDirectory(Path.GetDirectoryName(target)!);
                File.Copy(Path.Combine(root, relative), target);
                if (Sha(target) != (string?)file["sha256"]) throw new MigrationException($"{relative} changed while it was copied.");
            }
            // 2. The migration backup of the source: a zip with the inventory, sealed with the host key when one is configured, verified after writing.
            var (backupName, backupSha, backupSize, encrypted) = WriteBackup(data, copy, inventory, id);
            // 3. The candidate database, separate from the active data.
            var candidate = Path.Combine(folder, "candidate");
            if (Directory.Exists(candidate)) Directory.Delete(candidate, true);
            Directory.CreateDirectory(candidate);
            var v1 = Read(copy);
            if (v1.Blockers.Count > 0) throw new MigrationException("Validation failed: " + string.Join(" ", v1.Blockers.Select(b => (string)b!)));
            var counts = await BuildAsync(v1, candidate, actor, now, backupName, backupSha, backupSize, ct);
            // 4. Verification of the candidate.
            var verification = await VerifyAsync(v1, candidate, counts, ct);
            report["status"] = "verified";
            report["finished"] = Stamp(DateTimeOffset.UtcNow);
            report["counts"] = counts;
            report["verification"] = verification;
            report["backup"] = new JsonObject { ["file"] = backupName, ["sha256"] = backupSha, ["size"] = backupSize, ["encrypted"] = encrypted };
            report["candidate_sha256"] = Sha(Path.Combine(candidate, ApplicationBackups.DatabaseEntry));
            report["digest"] = digest;
            Save(Path.Combine(folder, "report.json"), report);
            // An archive source was unpacked for the preview; the verified copy in source/ replaces it, so no second plaintext copy is kept.
            if ((string?)preview["source"]!["kind"] == "archive" && Directory.Exists(Path.Combine(folder, "unpacked"))) Directory.Delete(Path.Combine(folder, "unpacked"), true);
            return report;
        }
        catch (Exception error) when (error is MigrationException or IOException or JsonException or SqliteException or DbUpdateException or InvalidOperationException or FormatException or BackupException)
        {
            report["status"] = "failed";
            report["error"] = error.Message;
            Save(Path.Combine(folder, "report.json"), report);
            try { if (Directory.Exists(Path.Combine(folder, "candidate"))) Directory.Delete(Path.Combine(folder, "candidate"), true); } catch (IOException) { }
            throw new MigrationException("The migration failed and nothing was activated: " + error.Message);
        }
    }

    private static (string Name, string Sha, long Size, bool Encrypted) WriteBackup(string data, string copy, JsonArray inventory, string id)
    {
        var backups = Path.Combine(data, "backups");
        Directory.CreateDirectory(backups);
        var zip = Path.Combine(Folder(data, id), "v1-source.zip");
        if (File.Exists(zip)) File.Delete(zip);
        using (var archive = ZipFile.Open(zip, ZipArchiveMode.Create))
        {
            foreach (var file in inventory) archive.CreateEntryFromFile(Path.Combine(copy, (string)file!["path"]!), "data/" + (string)file["path"]!, CompressionLevel.Optimal);
            using var manifest = new StreamWriter(archive.CreateEntry("inventory.json").Open(), new UTF8Encoding(false));
            manifest.Write(inventory.ToJsonString());
        }
        var host = BackupKeys.Host(data);
        string name;
        if (host is not null)
        {
            name = $"v1-migration-{id}.slbak";
            var target = Path.Combine(backups, name);
            using (var input = File.OpenRead(zip)) using (var output = new FileStream(target, FileMode.CreateNew, FileAccess.Write)) BackupArchive.Seal(input, output, "", host);
            using (var check = File.OpenRead(target)) using (var plain = new MemoryStream())
            {
                BackupArchive.Unseal(check, plain, "", host);
                if (Sha(plain.ToArray()) != Sha(zip)) throw new MigrationException("The migration backup could not be verified.");
            }
            File.Delete(zip);
        }
        else
        {
            name = $"v1-migration-{id}.zip";
            File.Move(zip, Path.Combine(backups, name));
            using var verify = ZipFile.OpenRead(Path.Combine(backups, name));
            if (verify.Entries.Count != inventory.Count + 1) throw new MigrationException("The migration backup could not be verified.");
        }
        var path = Path.Combine(backups, name);
        return (name, Sha(path), new FileInfo(path).Length, host is not null);
    }

    private static string AccountDigest(string username) => Sha(Encoding.UTF8.GetBytes(PythonJson.Dumps(JsonValue.Create(username.Trim().PyUpper()))));

    /// <summary>A context on the candidate database whose connection is NOT pooled. The candidate is hashed, moved at activation and deleted on
    /// failure; a pooled connection would keep SQLite's file handle open after the context is disposed, and Windows refuses to open (for the hash),
    /// move or delete a file another handle holds with write access ("being used by another process"). Without pooling, disposing the context
    /// closes the handle. Only this private file is affected: the server's pools and the active data are untouched (no ClearAllPools).</summary>
    private static AuthLensDb CandidateDb(string candidate)
    {
        var options = new DatabaseOptions { DataDirectory = candidate };
        var connection = new SqliteConnectionStringBuilder(options.ConnectionString) { Pooling = false }.ToString();
        var builder = new DbContextOptionsBuilder<AuthLensDb>().UseSqlite(connection).AddInterceptors(new SqlitePragmas(options.BusyTimeoutMs));
        return new AuthLensDb(builder.Options);
    }

    private static async Task<JsonObject> BuildAsync(V1Data v1, string candidate, string actor, DateTimeOffset now, string backupName, string backupSha, long backupSize, CancellationToken ct)
    {
        var counts = new JsonObject();
        await using (var db = CandidateDb(candidate))
        {
            await db.Database.MigrateAsync(ct);
            await using var tx = await db.Database.BeginTransactionAsync(ct);
            var utc = now.UtcDateTime;

            // Settings: the known v1 fields; server-managed source pointers are kept for reference.
            var defaults = V1Compatibility.DefaultSettingsDocument();
            var settings = new JsonObject(v1.Settings.Where(p => defaults.ContainsKey(p.Key) && p.Key != "revision").Select(p => KeyValuePair.Create(p.Key, p.Value?.DeepClone())));
            db.Settings.Add(new SettingsDocument { Revision = 1, Json = settings.ToJsonString(), UpdatedUtc = utc, UpdatedBy = "v1-migration" });
            counts["settings"] = 1;

            // Source revisions, oldest first per source; the active one last. The v1 snapshot id stays in the report as an alias (retention protection).
            var datasets = new Dictionary<string, Dataset>(StringComparer.Ordinal);
            foreach (var group in v1.Revisions.GroupBy(r => r.Kind))
            {
                var revision = 0;
                foreach (var r in group.OrderBy(r => r.Active).ThenBy(r => r.When).ThenBy(r => r.Snapshot, StringComparer.Ordinal))
                {
                    using var hasher = new ContentHasher();
                    var dataset = new Dataset
                    {
                        Source = r.Kind, Revision = ++revision, Status = DatasetStatus.Staged, RecordCount = r.Count, FileName = r.FileName,
                        CreatedUtc = r.When, ConfirmedBy = "v1-migration",
                        ReportJson = new JsonObject { ["migrated_from_v1"] = new JsonObject { ["snapshot"] = r.Snapshot, ["active"] = r.Active }, ["v1_report"] = r.Report?.DeepClone() }.ToJsonString(),
                    };
                    db.Datasets.Add(dataset);
                    await db.SaveChangesAsync(ct);
                    var ordinal = 0;
                    foreach (var record in r.Records())
                    {
                        var json = Sources.Serialize(record);
                        hasher.Add(json);
                        db.DatasetRecords.Add(new DatasetRecord { DatasetId = dataset.Id, Ordinal = ordinal++, Payload = json });
                        if (ordinal % 5000 == 0) { await db.SaveChangesAsync(ct); db.ChangeTracker.Clear(); }      // bounded change tracking
                    }
                    await db.SaveChangesAsync(ct);
                    db.ChangeTracker.Clear();
                    if (ordinal != r.Count) throw new MigrationException($"The {r.Kind} snapshot {r.Snapshot} changed during the migration.");
                    db.Datasets.Attach(dataset);
                    (dataset.ContentHash, dataset.Status, dataset.ActivatedUtc) = (hasher.Finish(), r.Active ? DatasetStatus.Active : DatasetStatus.Retired, r.Active ? r.When : null);
                    await db.SaveChangesAsync(ct);
                    db.ChangeTracker.Clear();
                    datasets[r.Snapshot] = dataset;
                }
                counts[$"datasets_{group.Key}"] = group.Count();
            }

            foreach (var (eid, path) in v1.Evidence)
            {
                var bytes = File.ReadAllBytes(path);
                if (Sha(bytes) != eid) throw new MigrationException($"Evidence snapshot {eid} changed during the migration.");
                db.SodEvidenceSnapshots.Add(new SodEvidenceSnapshot { Sha256 = eid, Json = Encoding.UTF8.GetString(bytes) });
            }
            counts["evidence_snapshots"] = v1.Evidence.Count;

            foreach (var (name, value) in v1.Documents)
            {
                var revision = value["revision"] is JsonValue rv && rv.TryGetValue<int>(out var r) ? r : 0;
                db.SodDocuments.Add(new SodDocument { Name = name, Revision = revision, Json = value.ToJsonString(), UpdatedUtc = utc, UpdatedBy = "v1-migration" });
                if (name == AssignmentLifecycle.Document) db.SodDocuments.Add(new SodDocument { Name = AssignmentLifecycle.Meta, Revision = revision, Json = "{}", UpdatedUtc = utc, UpdatedBy = "v1-migration" });
            }
            counts["documents"] = v1.Documents.Count;

            var sequence = 0L;
            foreach (var f in v1.SavedFilters.OfType<JsonObject>())
            {
                var name = (string?)f["name"] ?? "";
                db.SavedFilters.Add(new SavedFilter
                {
                    Id = (string?)f["id"] ?? Guid.NewGuid().ToString("N"), Name = name, NameKey = V1SavedFilters.Fold(name), View = (string?)f["view"] ?? "users",
                    FiltersJson = f["filters"]?.ToJsonString() ?? "{}", FilterSchema = (int?)f["filter_schema"] ?? 1, Created = (string?)f["created"] ?? Stamp(now), Modified = (string?)f["modified"] ?? Stamp(now),
                    Sequence = ++sequence, CreatedBy = "v1-migration", ModifiedBy = "v1-migration",
                });
            }
            counts["saved_filters"] = v1.SavedFilters.Count;

            foreach (var (rid, value) in v1.Reports.OrderBy(r => (string?)r.Report["timestamp"], StringComparer.Ordinal))
            {
                value["v1_report_id"] = rid;
                var when = DateTimeOffset.TryParse((string?)value["timestamp"], System.Globalization.CultureInfo.InvariantCulture, System.Globalization.DateTimeStyles.AssumeUniversal, out var t) ? t.UtcDateTime : utc;
                db.RefreshReports.Add(new RefreshReport { Id = rid[..32], TimestampUtc = when, Operation = (string?)value["operation"] ?? "import", Status = (string?)value["status"] ?? "unknown", Json = value.ToJsonString() });
            }
            counts["reports"] = v1.Reports.Count;
            await db.SaveChangesAsync(ct);

            // Account review: v1 keys are SHA-256 of the user name; the user names come from every migrated users revision. Decisions are appended to the
            // review hash chain in their original order with their original times. A decision for a user no longer in any revision is kept in a document.
            var usersActive = datasets.Values.FirstOrDefault(d => d.Source == Sources.Users && d.Status == DatasetStatus.Active);
            var names = new Dictionary<string, string>(StringComparer.Ordinal);
            foreach (var r in v1.Revisions.Where(r => r.Kind == Sources.Users))
                foreach (var record in r.Records()) if (record.GetValueOrDefault("USERNAME") is { Length: > 0 } u) names.TryAdd(AccountDigest(u), u.Trim().PyUpper());
            var unmatched = new JsonObject();
            var events = new List<(DateTime When, ReviewDecision Decision)>();
            foreach (var (key, item) in v1.AccountReview)
            {
                if (item is not JsonObject decision) continue;
                if (usersActive is null || !names.TryGetValue(key, out var username)) { unmatched[key] = decision.DeepClone(); continue; }
                foreach (var e in (decision["history"] as JsonArray ?? []).OfType<JsonObject>().Append(decision))
                {
                    var details = new JsonObject(e.Where(p => p.Key is not ("state" or "reviewer" or "rationale" or "evidence_version" or "timestamp" or "history")).Select(p => KeyValuePair.Create(p.Key, p.Value?.DeepClone())));
                    var when = DateTimeOffset.Parse((string)e["timestamp"]!, System.Globalization.CultureInfo.InvariantCulture).UtcDateTime;
                    events.Add((when, new ReviewDecision
                    {
                        SubjectType = "account", SubjectKey = Sources.AccountKey(username), EvidenceVersion = (string?)e["evidence_version"], Decision = (string)e["state"]!, Reviewer = (string?)e["reviewer"] ?? "",
                        Comment = (string?)e["rationale"] ?? "", DetailsJson = details.Count > 0 ? details.ToJsonString() : null, DatasetId = usersActive.Id, DecidedUtc = when, Hash = "",
                    }));
                }
            }
            string? previous = null;
            foreach (var (_, d) in events.OrderBy(e => e.When))
            {
                d.PreviousHash = previous;
                d.Hash = ReviewService.HashOf(d, previous);
                previous = d.Hash;
                db.ReviewDecisions.Add(d);
            }
            if (unmatched.Count > 0) db.SodDocuments.Add(new SodDocument { Name = "v1-account-review-unmatched", Json = unmatched.ToJsonString(), UpdatedUtc = utc, UpdatedBy = "v1-migration" });
            counts["account_review_events"] = events.Count;
            counts["account_review_unmatched"] = unmatched.Count;

            // SoD 2.0 decisions: events in timestamp order on the event hash chain; actions and the report log as documents.
            if (v1.SodDecisions is { } sod)
            {
                var all = new List<JsonObject>();
                foreach (var (_, kinds) in sod["contexts"] as JsonObject ?? [])
                    foreach (var (_, keys) in kinds as JsonObject ?? [])
                        foreach (var (_, list) in keys as JsonObject ?? [])
                            all.AddRange((list as JsonArray ?? []).OfType<JsonObject>());
                string? chain = null;
                foreach (var e in all.OrderBy(e => (string?)e["timestamp"], StringComparer.Ordinal).ThenBy(e => (string?)e["event_id"], StringComparer.Ordinal))
                {
                    var json = CanonicalJson.Serialize(e);
                    var hash = Sha(Encoding.UTF8.GetBytes((chain ?? "") + "\n" + json));
                    db.SodDecisionEvents.Add(new SodDecisionRecord { EventId = (string)e["event_id"]!, Context = (string)e["context"]!, Kind = (string)e["kind"]!, Key = (string)e["key"]!, Json = json, PreviousHash = chain, Hash = hash });
                    chain = hash;
                }
                var revision = sod["revision"] is JsonValue rv && rv.TryGetValue<int>(out var r) ? r : 0;
                db.SodDocuments.Add(new SodDocument { Name = "sod-decisions", Revision = revision, Json = "{}", UpdatedUtc = utc, UpdatedBy = "v1-migration" });
                if (sod["actions"] is JsonObject actions && actions.Count > 0) db.SodDocuments.Add(new SodDocument { Name = "sod-remediation-actions", Json = actions.ToJsonString(), UpdatedUtc = utc, UpdatedBy = "v1-migration" });
                if (sod["reports"] is JsonArray log && log.Count > 0) db.SodDocuments.Add(new SodDocument { Name = SodDecisionStore.ReportLog, Json = new JsonObject { ["reports"] = log.DeepClone() }.ToJsonString(), UpdatedUtc = utc, UpdatedBy = "v1-migration" });
                counts["sod_decision_events"] = all.Count;
            }

            db.Backups.Add(new BackupRecord { Kind = BackupKind.Migration, FileName = backupName, Sha256 = backupSha, SizeBytes = backupSize, Reason = $"SAP Lens 1 data before migration (migrated by {actor})", CreatedUtc = utc });
            await db.SaveChangesAsync(ct);
            await tx.CommitAsync(ct);
            await db.Database.ExecuteSqlRawAsync("PRAGMA journal_mode = DELETE;", ct);
        }

        // Files next to the database: accounts (sessions removed), branding, copied state files.
        if (v1.Accounts is not null)
        {
            var target = Path.Combine(candidate, "security", "accounts.sqlite3");
            Directory.CreateDirectory(Path.GetDirectoryName(target)!);
            File.Copy(v1.Accounts, target);
            using (var accounts = new SqliteConnection(new SqliteConnectionStringBuilder { DataSource = target, Pooling = false }.ToString()))
            {
                accounts.Open();
                using var command = accounts.CreateCommand();
                command.CommandText = "DELETE FROM sessions; VACUUM;";
                command.ExecuteNonQuery();
            }
            new AccountStore(target, TimeProvider.System).Prepare();             // the AuthLens account store accepts the v1 schema
            counts["accounts"] = 1;
        }
        foreach (var image in v1.Branding)
        {
            Directory.CreateDirectory(Path.Combine(candidate, "branding"));
            File.Copy(image, Path.Combine(candidate, "branding", Path.GetFileName(image)));
        }
        foreach (var name in v1.Copied) File.Copy(Path.Combine(v1.Root, name), Path.Combine(candidate, name));
        return counts;
    }

    private static async Task<JsonObject> VerifyAsync(V1Data v1, string candidate, JsonObject counts, CancellationToken ct)
    {
        var database = Path.Combine(candidate, ApplicationBackups.DatabaseEntry);
        var integrity = await DatabaseMaintenance.VerifyFileAsync(database, ct);
        if (!integrity.Ok) throw new MigrationException("The migrated database failed its integrity check: " + string.Join("; ", integrity.Problems.Take(3)));
        await using var db = CandidateDb(candidate);
        var result = new JsonObject { ["integrity"] = "ok" };
        // Every source revision: record count and the content of each record as in v1.
        foreach (var r in v1.Revisions)
        {
            var dataset = (await db.Datasets.AsNoTracking().Where(d => d.Source == r.Kind).ToListAsync(ct)).First(d => d.ReportJson!.Contains(r.Snapshot, StringComparison.Ordinal));
            // Streamed pairwise: every stored record, in order, equals the v1 record (same fields and values); same count on both sides.
            using (var expected = r.Records().GetEnumerator())
            {
                var count = 0;
                await foreach (var payload in db.DatasetRecords.AsNoTracking().Where(x => x.DatasetId == dataset.Id).OrderBy(x => x.Ordinal).Select(x => x.Payload).AsAsyncEnumerable().WithCancellation(ct))
                {
                    var stored = Sources.Deserialize(payload);
                    if (!expected.MoveNext() || stored.Count != expected.Current.Count || expected.Current.Any(f => !stored.TryGetValue(f.Key, out var v) || v != f.Value))
                        throw new MigrationException($"The {r.Kind} revision {r.Snapshot} differs after migration.");
                    count++;
                }
                if (expected.MoveNext() || count != r.Count) throw new MigrationException($"The {r.Kind} revision {r.Snapshot} differs after migration.");
            }
            if ((dataset.Status == DatasetStatus.Active) != r.Active) throw new MigrationException($"The {r.Kind} revision {r.Snapshot} has the wrong state after migration.");
        }
        result["source_revisions"] = v1.Revisions.Count;
        foreach (var (id, _) in v1.Evidence)
            if (await PrivateSnapshots.ReadAsync(db, id, ct) is null) throw new MigrationException($"Evidence snapshot {id} does not match its address after migration.");
        result["evidence_snapshots"] = v1.Evidence.Count;
        string? previous = null;
        var chain = 0;
        foreach (var d in await db.ReviewDecisions.AsNoTracking().OrderBy(d => d.Id).ToListAsync(ct))
        {
            if (d.PreviousHash != previous || ReviewService.HashOf(d, previous) != d.Hash) throw new MigrationException("The review decision chain does not verify after migration.");
            previous = d.Hash;
            chain++;
        }
        result["review_chain"] = chain;
        string? sodPrevious = null;
        foreach (var e in await db.SodDecisionEvents.AsNoTracking().OrderBy(e => e.Seq).ToListAsync(ct))
        {
            if (e.PreviousHash != sodPrevious || Sha(Encoding.UTF8.GetBytes((sodPrevious ?? "") + "\n" + e.Json)) != e.Hash) throw new MigrationException("The SoD decision chain does not verify after migration.");
            sodPrevious = e.Hash;
        }
        result["sod_chain"] = await db.SodDecisionEvents.CountAsync(ct);
        if (await db.SavedFilters.CountAsync(ct) != v1.SavedFilters.Count) throw new MigrationException("Saved filters differ after migration.");
        if (await db.RefreshReports.CountAsync(ct) != v1.Reports.Count) throw new MigrationException("Reports differ after migration.");
        if (chain != (int)counts["account_review_events"]!) throw new MigrationException("Account review decisions differ after migration.");
        result["counts"] = counts.DeepClone();
        return result;
    }

    // ---- activation and rollback

    private static string CheckId(string data, string id)
    {
        if (!Hex32().IsMatch(id)) throw new MigrationException("Unknown migration identifier.");
        var folder = Folder(data, id);
        if (!File.Exists(Path.Combine(folder, "preview.json"))) throw new MigrationException("Unknown migration identifier.");
        return folder;
    }

    /// <summary>Requests activation at the next start. Needs a verified run, the digest again, and (for a directory source) an unchanged source.</summary>
    public static JsonObject RequestActivation(string data, string id, string digest, string actor, DateTimeOffset now)
    {
        data = Path.GetFullPath(data);
        var folder = CheckId(data, id);
        var preview = Load(Path.Combine(folder, "preview.json"));
        var report = File.Exists(Path.Combine(folder, "report.json")) ? Load(Path.Combine(folder, "report.json")) : throw new MigrationException("Run the migration before activating it.");
        if ((string?)report["status"] != "verified") throw new MigrationException($"Only a verified migration can be activated (this one is {(string?)report["status"]}).");
        if ((string?)preview["digest"] != digest) throw new MigrationException("The approval does not match the preview.");
        if ((string?)preview["source"]!["kind"] == "directory" && Directory.Exists((string)preview["source"]!["root"]!) &&
            Fingerprint(Inventory((string)preview["source"]!["root"]!)) != (string?)preview["source"]!["fingerprint"])
            throw new MigrationException("The SAP Lens 1 data changed after the migration ran (for example new decisions). Preview and run again so nothing is lost.");
        if (File.Exists(PendingActivation(data)) || File.Exists(PendingRollback(data))) throw new MigrationException("Another migration step is already waiting for the next start.");
        if (File.Exists(Path.Combine(data, "restore", "pending.json"))) throw new MigrationException("A restore is waiting for the next start; cancel it first.");
        Save(PendingActivation(data), new JsonObject { ["id"] = id, ["requested"] = Stamp(now), ["actor"] = actor, ["candidate_sha256"] = report["candidate_sha256"]?.DeepClone() });
        report["status"] = "activation_requested";
        Save(Path.Combine(folder, "report.json"), report);
        return report;
    }

    /// <summary>Requests a rollback of an activated migration at the next start: the previous AuthLens files return.</summary>
    public static JsonObject RequestRollback(string data, string id, string actor, DateTimeOffset now)
    {
        data = Path.GetFullPath(data);
        var folder = CheckId(data, id);
        var report = Load(Path.Combine(folder, "report.json"));
        if ((string?)report["status"] != "activated") throw new MigrationException("Only an activated migration can be rolled back.");
        if (File.Exists(PendingActivation(data)) || File.Exists(PendingRollback(data))) throw new MigrationException("Another migration step is already waiting for the next start.");
        Save(PendingRollback(data), new JsonObject { ["id"] = id, ["requested"] = Stamp(now), ["actor"] = actor });
        report["status"] = "rollback_requested";
        Save(Path.Combine(folder, "report.json"), report);
        return report;
    }

    public static JsonObject Status(string data, string id) => Load(Path.Combine(CheckId(Path.GetFullPath(data), id), "report.json"));

    private static readonly string[] Sidecars = ["", "-wal", "-shm", "-journal"];

    /// <summary>The files a migration replaces, relative to the data directory.</summary>
    private static IEnumerable<string> Managed()
    {
        foreach (var s in Sidecars) yield return ApplicationBackups.DatabaseEntry + s;
        foreach (var s in Sidecars) yield return Path.Combine("security", "accounts.sqlite3" + s);
        yield return "branding";
        foreach (var name in Copied) yield return name;
    }

    private static void MoveAll(string from, string to, List<(string From, string To)> moved)
    {
        foreach (var relative in Managed())
        {
            var source = Path.Combine(from, relative);
            var target = Path.Combine(to, relative);
            if (!File.Exists(source) && !Directory.Exists(source)) continue;
            Directory.CreateDirectory(Path.GetDirectoryName(target)!);
            if (Directory.Exists(source)) Directory.Move(source, target); else File.Move(source, target);
            moved.Add((source, target));
        }
    }

    private static void Undo(List<(string From, string To)> moved)
    {
        for (var i = moved.Count - 1; i >= 0; i--)
        {
            var (from, to) = moved[i];
            try { if (Directory.Exists(to)) Directory.Move(to, from); else if (File.Exists(to)) File.Move(to, from, overwrite: true); } catch (IOException) { }
        }
    }

    /// <summary>Applies a requested activation or rollback before the database opens. Returns a log line, or null when nothing was pending.</summary>
    public static string? ApplyPending(string data, DateTimeOffset now)
    {
        data = Path.GetFullPath(data);
        if (File.Exists(PendingActivation(data))) return Activate(data, now);
        if (File.Exists(PendingRollback(data))) return Rollback(data, now);
        return null;
    }

    private static string Activate(string data, DateTimeOffset now)
    {
        var pending = Load(PendingActivation(data));
        var id = (string?)pending["id"] ?? "";
        var moved = new List<(string From, string To)>();
        JsonObject? report = null;
        try
        {
            var folder = CheckId(data, id);
            report = Load(Path.Combine(folder, "report.json"));
            var candidate = Path.Combine(folder, "candidate");
            if (!File.Exists(Path.Combine(candidate, ApplicationBackups.DatabaseEntry)) || Sha(Path.Combine(candidate, ApplicationBackups.DatabaseEntry)) != (string?)pending["candidate_sha256"])
                throw new MigrationException("The migrated database changed after verification.");
            var previous = Path.Combine(folder, "previous");
            if (Directory.Exists(previous)) throw new MigrationException("A previous activation of this migration left files behind; resolve them first.");
            MoveAll(data, previous, moved);
            MoveAll(candidate, data, moved);
            var integrity = DatabaseMaintenance.VerifyFileAsync(Path.Combine(data, ApplicationBackups.DatabaseEntry)).GetAwaiter().GetResult();
            if (!integrity.Ok) throw new MigrationException("The activated database failed its integrity check.");
            File.Delete(PendingActivation(data));
            report["status"] = "activated";
            report["activated"] = Stamp(now);
            Save(Path.Combine(folder, "report.json"), report);
            Application.Retention.DataRetention.AfterRestore(data, now);       // no automatic cleanup right after the data changed
            return $"SAP Lens 1 migration {id} activated; the previous .NET application files are kept in migration/{id}/previous";
        }
        catch (Exception error) when (error is MigrationException or IOException or UnauthorizedAccessException or JsonException or SqliteException)
        {
            Undo(moved);
            try { File.Delete(PendingActivation(data)); } catch (IOException) { }
            if (report is not null && Hex32().IsMatch(id))
            {
                report["status"] = "verified";
                report["activation_error"] = error.Message;
                try { Save(Path.Combine(Folder(data, id), "report.json"), report); } catch (IOException) { }
            }
            return $"SAP Lens 1 migration {id} was NOT activated and the current data is unchanged: {error.Message}";
        }
    }

    private static string Rollback(string data, DateTimeOffset now)
    {
        var pending = Load(PendingRollback(data));
        var id = (string?)pending["id"] ?? "";
        var moved = new List<(string From, string To)>();
        try
        {
            var folder = CheckId(data, id);
            var report = Load(Path.Combine(folder, "report.json"));
            var previous = Path.Combine(folder, "previous");
            var rolledBack = Path.Combine(folder, "rolled-back");
            MoveAll(data, rolledBack, moved);
            MoveAll(previous, data, moved);
            File.Delete(PendingRollback(data));
            report["status"] = "rolled_back";
            report["rolled_back"] = Stamp(now);
            Save(Path.Combine(folder, "report.json"), report);
            return $"SAP Lens 1 migration {id} rolled back; the migrated files are kept in migration/{id}/rolled-back";
        }
        catch (Exception error) when (error is MigrationException or IOException or UnauthorizedAccessException or JsonException)
        {
            Undo(moved);
            try { File.Delete(PendingRollback(data)); } catch (IOException) { }
            return $"Rollback of migration {id} failed; the current data is unchanged: {error.Message}";
        }
    }
}

public sealed class MigrationException(string message) : Exception(message);
