using System.Formats.Tar;
using System.IO.Compression;
using System.Security.Cryptography;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;
using AuthLens.Domain.Text;

namespace AuthLens.Application.Backups;

/// <summary>SAP Lens 1 application backups (`.slbak` SLBAK2, or a legacy `.tar.gz`): authenticated decryption and the checks of v1
/// maintenance.verify before anything is used. Read-only for the archive; used by the SAP Lens 1 data migration.</summary>
public static partial class V1BackupArchive
{
    [GeneratedRegex("^[a-f0-9]{64}$")] private static partial Regex Hex64();

    private const int V1MaxFiles = 100_000;
    private const long V1MaxBytes = 4L * 1024 * 1024 * 1024 + 16 * 1024 * 1024;
    private static readonly HashSet<string> Reserved = ["CON", "PRN", "AUX", "NUL", .. Enumerable.Range(1, 9).SelectMany(i => new[] { $"COM{i}", $"LPT{i}" })];

    /// <summary>maintenance.safe_member: relative POSIX names under data/ or config/ (or manifest.json), no traversal, no Windows-reserved or trailing
    /// space/dot names.</summary>
    private static void SafeMember(string name)
    {
        var parts = name.Split('/');
        if (name.Length == 0 || name.Contains('\\') || name.Contains(':') || name.StartsWith('/') || parts.Any(p => p is "" or "." or "..")
            || (parts[0] is not ("data" or "config") && name != "manifest.json"))
            throw new BackupException("The SAP Lens 1 backup contains an unsafe member name.", 422);
        if (parts.Any(p => p.EndsWith(' ') || p.EndsWith('.') || Reserved.Contains(p.Split('.')[0].ToUpperInvariant())))
            throw new BackupException("The SAP Lens 1 backup contains non-portable path names.", 422);
    }

    /// <summary>A SAP Lens 1 application backup unpacked into a private folder, with the checks of v1 maintenance.verify: SLBAK2 authentication first (an
    /// unencrypted .tar.gz is accepted only as a legacy archive), then only regular files with safe, case-unique names, within v1's file and size
    /// limits, a schema 1 manifest whose file list equals the members exactly, and every member's SHA-256 equal to the manifest. Returns the data root
    /// (the archive's data/ folder) and the manifest; anything that fails leaves no unpacked file behind.</summary>
    public static (string Root, JsonObject Manifest) Unpack(string archive, string secret, string target)
    {
        if (new FileInfo(archive).LinkTarget is not null) throw new BackupException("SAP Lens 1 backups may not be links.", 422);
        Directory.CreateDirectory(target);
        try
        {
            byte[] head = new byte[8];
            using (var probe = File.OpenRead(archive)) _ = probe.Read(head);
            byte[] tarGz;
            if (BackupArchive.IsV1(head))
            {
                using var input = File.OpenRead(archive);
                tarGz = BackupArchive.UnsealV1(input, secret, null, BackupArchive.V1MigrationLimit);
            }
            else if (head[0] == 0x1f && head[1] == 0x8b) tarGz = File.ReadAllBytes(archive);
            else throw new BackupException("Select a SAP Lens 1 data directory or a SAP Lens 1 .slbak or .tar.gz backup.", 422);
            var hashes = new Dictionary<string, string>(StringComparer.Ordinal);
            var folded = new HashSet<string>(StringComparer.Ordinal);
            JsonObject? manifest = null;
            long total = 0;
            var full = Path.GetFullPath(target) + Path.DirectorySeparatorChar;
            using (var gzip = new GZipStream(new MemoryStream(tarGz), CompressionMode.Decompress))
            using (var reader = new TarReader(gzip))
                while (reader.GetNextEntry() is { } entry)
                {
                    if (entry.EntryType is not (TarEntryType.RegularFile or TarEntryType.V7RegularFile)) throw new BackupException("SAP Lens 1 backup links and non-regular members are forbidden.", 422);
                    var name = entry.Name;
                    SafeMember(name);
                    if (!folded.Add(name.PyCasefold()) || hashes.Count >= V1MaxFiles + 1) throw new BackupException("SAP Lens 1 backup limits or duplicate paths are invalid.", 422);
                    total += entry.Length;
                    if (entry.Length < 0 || total > V1MaxBytes) throw new BackupException("The SAP Lens 1 backup exceeds the supported limits.", 422);
                    using var content = entry.DataStream ?? Stream.Null;
                    if (name == "manifest.json")
                    {
                        if (entry.Length > 16 * 1024 * 1024) throw new BackupException("The SAP Lens 1 backup manifest is too large.", 422);
                        using var buffer = new MemoryStream();
                        content.CopyTo(buffer);
                        try { manifest = JsonNode.Parse(buffer.ToArray()) as JsonObject; } catch (JsonException) { manifest = null; }
                        hashes[name] = "";
                        continue;
                    }
                    var path = Path.GetFullPath(Path.Combine(target, name));
                    if (!path.StartsWith(full, StringComparison.Ordinal)) throw new BackupException("The SAP Lens 1 backup contains an unsafe member name.", 422);
                    Directory.CreateDirectory(Path.GetDirectoryName(path)!);
                    using var output = new FileStream(path, FileMode.CreateNew, FileAccess.Write);
                    using var hash = IncrementalHash.CreateHash(HashAlgorithmName.SHA256);
                    var block = new byte[81920];
                    int read;
                    while ((read = content.Read(block)) > 0) { hash.AppendData(block, 0, read); output.Write(block, 0, read); }
                    hashes[name] = Convert.ToHexStringLower(hash.GetHashAndReset());
                }
            if (manifest is null || (int?)manifest["schema"] != 1 || manifest["mode"] is not JsonValue || manifest["files"] is not JsonObject files || manifest["application_version"] is not JsonValue)
                throw new BackupException("The SAP Lens 1 backup manifest is missing or invalid.", 422);
            if (files.Any(f => f.Value is not JsonValue v || !v.TryGetValue<string>(out var digest) || !Hex64().IsMatch(digest)))
                throw new BackupException("The SAP Lens 1 backup has an invalid digest manifest.", 422);
            if (!hashes.Keys.Where(k => k != "manifest.json").ToHashSet(StringComparer.Ordinal).SetEquals(files.Select(f => f.Key)) || !hashes.ContainsKey("manifest.json"))
                throw new BackupException("The SAP Lens 1 backup has unexpected or missing members.", 422);
            foreach (var (name, digest) in files)
                if (hashes[name] != (string)digest!) throw new BackupException("A SAP Lens 1 backup member does not match its checksum.", 422);
            var data = Path.Combine(target, "data");
            if (!File.Exists(Path.Combine(data, "settings.json"))) throw new BackupException("The SAP Lens 1 backup contains no application data (data/settings.json).", 422);
            return (data, manifest);
        }
        catch (Exception error) when (error is BackupException or InvalidDataException or IOException or FormatException)
        {
            try { Directory.Delete(target, true); } catch (IOException) { }
            if (error is InvalidDataException or FormatException) throw new BackupException("The SAP Lens 1 backup is damaged (invalid compressed archive).", 422);
            throw;
        }
    }
}
