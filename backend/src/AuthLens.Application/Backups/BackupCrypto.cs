using System.Buffers.Binary;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using Konscious.Security.Cryptography;

namespace AuthLens.Application.Backups;

/// <summary>A refused backup operation; the message is safe to show (it never contains a key, passphrase or path of a secret).</summary>
public sealed class BackupException(string message, int status = 409) : Exception(message)
{
    public int Status { get; } = status;
}

/// <summary>The protected host backup key (v1 backup_crypto key handling): 32 random bytes, base64 in a private file OUTSIDE the data directory, located by
/// AUTHLENS_BACKUP_KEY_FILE or by &lt;data&gt;/backup-key-location.json. Created, selected and exported only by local commands; the API can only verify that
/// a separately stored recovery copy matches (escrow), which is recorded by fingerprint.</summary>
public static class BackupKeys
{
    public const string EnvironmentVariable = "AUTHLENS_BACKUP_KEY_FILE";
    private const string Pointer = "backup-key-location.json", Confirmation = ".backup-key-confirmation.json";

    public static string Fingerprint(byte[] key) => Convert.ToHexStringLower(SHA256.HashData(key))[..16];

    private static bool Linked(string path)
    {
        for (FileSystemInfo? item = new FileInfo(path); item is not null; item = item is FileInfo f ? f.Directory : ((DirectoryInfo)item).Parent)
            if (item.Exists && item.LinkTarget is not null) return true;
        return false;
    }

    /// <summary>An absolute, non-linked key path outside the data directory.</summary>
    public static string Safe(string path, string dataDirectory)
    {
        if (!Path.IsPathFullyQualified(path)) throw new BackupException("Use an absolute, non-linked protected recovery-key file.", 422);
        var full = Path.GetFullPath(path);
        if (Linked(full)) throw new BackupException("Use an absolute, non-linked protected recovery-key file.", 422);
        var data = Path.GetFullPath(dataDirectory).TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar;
        var comparison = OperatingSystem.IsWindows() ? StringComparison.OrdinalIgnoreCase : StringComparison.Ordinal;
        if (full.StartsWith(data, comparison)) throw new BackupException("The recovery-key file must be outside application data and backup archives.", 422);
        return full;
    }

    public static string? Location(string dataDirectory)
    {
        var value = Environment.GetEnvironmentVariable(EnvironmentVariable);
        if (string.IsNullOrWhiteSpace(value))
        {
            var pointer = Path.Combine(dataDirectory, Pointer);
            if (!File.Exists(pointer)) return null;
            try
            {
                if (Linked(pointer) || new FileInfo(pointer).Length > 4096) throw new FormatException();
                var stored = JsonNode.Parse(File.ReadAllText(pointer));
                if ((int?)stored?["schema"] != 1) throw new FormatException();
                value = (string?)stored!["path"];
            }
            catch (Exception error) when (error is FormatException or JsonException or IOException or InvalidOperationException)
            { throw new BackupException("The host backup-key location is unreadable; configure it locally again."); }
        }
        return string.IsNullOrWhiteSpace(value) ? null : Safe(value, dataDirectory);
    }

    public static byte[] Read(string path, string dataDirectory)
    {
        path = Safe(path, dataDirectory);
        try
        {
            if (!OperatingSystem.IsWindows() && (File.GetUnixFileMode(path) & (UnixFileMode.GroupRead | UnixFileMode.GroupWrite | UnixFileMode.OtherRead | UnixFileMode.OtherWrite)) != 0)
                throw new FormatException();
            var raw = File.ReadAllBytes(path);
            if (raw.Length > 96) throw new FormatException();
            var key = Convert.FromBase64String(Encoding.ASCII.GetString(raw).Trim());
            return key.Length == 32 ? key : throw new FormatException();
        }
        catch (Exception error) when (error is FormatException or IOException or UnauthorizedAccessException)
        { throw new BackupException("The protected backup recovery key is unavailable or has unsafe permissions."); }
    }

    /// <summary>The host key, or null when none is configured.</summary>
    public static byte[]? Host(string dataDirectory) => Location(dataDirectory) is { } path ? Read(path, dataDirectory) : null;

    /// <summary>key_status: configured, fingerprint and whether a separately stored recovery copy was verified.</summary>
    public static JsonObject Status(string dataDirectory)
    {
        try
        {
            if (Host(dataDirectory) is not { } key) return new JsonObject { ["configured"] = false, ["escrow_verified"] = false };
            var marker = Path.Combine(dataDirectory, Confirmation);
            var verified = false;
            if (File.Exists(marker) && !Linked(marker) && new FileInfo(marker).Length < 8192)
            {
                var value = JsonNode.Parse(File.ReadAllText(marker));
                verified = (int?)value?["schema"] == 1 && (string?)value!["fingerprint"] == Fingerprint(key);
            }
            return new JsonObject { ["configured"] = true, ["fingerprint"] = Fingerprint(key), ["escrow_verified"] = verified };
        }
        catch (Exception error) when (error is BackupException or JsonException or IOException) { return new JsonObject { ["configured"] = false, ["escrow_verified"] = false }; }
    }

    /// <summary>verify_escrow: the offered recovery copy must equal the host key (constant time); records the fingerprint, never the key.</summary>
    public static JsonObject VerifyEscrow(string offered, string dataDirectory, string actor, DateTimeOffset now)
    {
        using var operation = KeyOperation(dataDirectory);
        var host = Host(dataDirectory) ?? throw new BackupException("Configure a protected host backup key locally first.");
        byte[] copy;
        try { copy = Convert.FromBase64String(offered.Trim()); } catch (FormatException) { copy = []; }
        if (copy.Length != 32 || !CryptographicOperations.FixedTimeEquals(host, copy))
        {
            KeyAudit(dataDirectory, "recovery.verify_failed", actor, Fingerprint(host));
            throw new BackupException("Recovery-key verification failed. Existing keys were not changed.");
        }
        KeyAudit(dataDirectory, "recovery.verified", actor, Fingerprint(host));
        WriteAtomic(Path.Combine(dataDirectory, Confirmation), new JsonObject
        {
            ["schema"] = 1, ["fingerprint"] = Fingerprint(host), ["verified_at"] = now.ToString("O"), ["actor"] = actor,
        }.ToJsonString());
        return Status(dataDirectory);
    }

    /// <summary>LOCAL operation: creates a new key file (never overwrites, never prints the key) and points this data directory at it.</summary>
    public static JsonObject Create(string path, string dataDirectory)
    {
        using var operation = KeyOperation(dataDirectory);
        if (Location(dataDirectory) is not null) throw new BackupException("A host backup key is already configured. Creating another key would make existing archives unreadable.");
        path = Safe(path, dataDirectory);
        if (!Directory.Exists(Path.GetDirectoryName(path))) throw new BackupException("Create a private recovery-key directory first.", 422);
        WritePrivate(path, Encoding.ASCII.GetBytes(Convert.ToBase64String(RandomNumberGenerator.GetBytes(32)) + "\n"));
        KeyAudit(dataDirectory, "key.created", Environment.UserName, Fingerprint(Read(path, dataDirectory)));
        WriteAtomic(Path.Combine(dataDirectory, Pointer), new JsonObject { ["schema"] = 1, ["path"] = path }.ToJsonString());
        return Status(dataDirectory);
    }

    /// <summary>LOCAL operation: uses an existing key file for this data directory.</summary>
    public static JsonObject Use(string path, string dataDirectory)
    {
        using var operation = KeyOperation(dataDirectory);
        path = Safe(path, dataDirectory);
        var offered = Read(path, dataDirectory);
        if (Host(dataDirectory) is { } existing && !CryptographicOperations.FixedTimeEquals(existing, offered))
            throw new BackupException("A different host key is already configured. Existing keys and archives were preserved.");
        KeyAudit(dataDirectory, "key.selected", Environment.UserName, Fingerprint(offered));
        Directory.CreateDirectory(dataDirectory);
        WriteAtomic(Path.Combine(dataDirectory, Pointer), new JsonObject { ["schema"] = 1, ["path"] = path }.ToJsonString());
        return Status(dataDirectory);
    }

    /// <summary>LOCAL operation: writes a recovery copy to a new private file (escrow), which an administrator then verifies through Settings.</summary>
    public static JsonObject Export(string destination, string dataDirectory)
    {
        using var operation = KeyOperation(dataDirectory);
        var key = Host(dataDirectory) ?? throw new BackupException("No host backup key is configured.");
        destination = Safe(destination, dataDirectory);
        KeyAudit(dataDirectory, "recovery.export_requested", Environment.UserName, Fingerprint(key));
        WritePrivate(destination, Encoding.ASCII.GetBytes(Convert.ToBase64String(key) + "\n"));
        KeyAudit(dataDirectory, "recovery.exported", Environment.UserName, Fingerprint(key));
        return new JsonObject { ["exported"] = true, ["fingerprint"] = Fingerprint(key), ["escrow_verification_required"] = true };
    }

    public static JsonObject VerifyFile(string path, string dataDirectory, string actor, DateTimeOffset now) =>
        VerifyEscrow(Convert.ToBase64String(Read(Safe(path, dataDirectory), dataDirectory)), dataDirectory, actor, now);

    private static FileStream KeyOperation(string dataDirectory)
    {
        Directory.CreateDirectory(dataDirectory);
        try { return new FileStream(Path.Combine(dataDirectory, ".backup-key-operation.lock"), FileMode.OpenOrCreate, FileAccess.ReadWrite, FileShare.None); }
        catch (IOException) { throw new BackupException("Another local recovery-key operation is running. Retry after it completes."); }
    }

    private static void KeyAudit(string dataDirectory, string action, string actor, string fingerprint)
    {
        var path = Path.Combine(dataDirectory, "backup-key-audit.jsonl");
        if (!File.Exists(path)) WritePrivate(path, []);
        var line = System.Text.Json.JsonSerializer.Serialize(new { at = DateTimeOffset.UtcNow, action, actor, fingerprint });
        using var stream = new FileStream(path, FileMode.Append, FileAccess.Write, FileShare.Read);
        stream.Write(Encoding.UTF8.GetBytes(line + "\n"));
        stream.Flush(true);
    }

    /// <summary>A new file readable by its owner only (Unix 0600; Windows: inheritance removed, owner, SYSTEM and Administrators).</summary>
    public static void WritePrivate(string path, byte[] content)
    {
        var options = new FileStreamOptions { Mode = FileMode.CreateNew, Access = FileAccess.Write };
        if (!OperatingSystem.IsWindows()) options.UnixCreateMode = UnixFileMode.UserRead | UnixFileMode.UserWrite;
        try
        {
            using var stream = OperatingSystem.IsWindows() ? WindowsPrivate.Create(path) : new FileStream(path, options);
            stream.Write(content); stream.Flush(true);
        }
        catch (IOException) when (File.Exists(path) && new FileInfo(path).Length > 0) { throw new BackupException("The file already exists; keys are never overwritten.", 422); }
    }

    public static void WriteAtomic(string path, string text)
    {
        var temporary = path + "." + Guid.NewGuid().ToString("N") + ".tmp";
        using (var stream = new FileStream(temporary, FileMode.CreateNew, FileAccess.Write, FileShare.None))
        {
            stream.Write(Encoding.UTF8.GetBytes(text));
            stream.Flush(true);
        }
        File.Move(temporary, path, overwrite: true);
    }
}

/// <summary>SAP Lens portable archive (SLBAK3): AES-256-GCM over 1 MiB segments with the streaming nonce layout of Tink's AES-GCM-HKDF streaming AEAD
/// (7-byte random prefix, 32-bit segment counter, final-segment flag); the header is authenticated with every segment, so truncation, reordering, header
/// changes and wrong keys all fail before any content is used. Keys: Argon2id (passphrase) or HKDF-SHA256 (host key). Also decrypts v1 SLBAK2 archives.</summary>
public static class BackupArchive
{
    public static readonly byte[] Magic = "SLBAK3\r\n"u8.ToArray(), V1Magic = "SLBAK2\r\n"u8.ToArray();
    public const int Segment = 1024 * 1024, Tag = 16;
    public const long MaxArchive = 2L * 1024 * 1024 * 1024;
    private static readonly byte[] HostInfo = "SAP Lens 2 portable archive v3"u8.ToArray(), V1HostInfo = "SAP Lens portable archive v2"u8.ToArray();

    public static bool IsV1(ReadOnlySpan<byte> start) => start.StartsWith(V1Magic);
    public static bool IsV2(ReadOnlySpan<byte> start) => start.StartsWith(Magic);

    private static byte[] Argon(string passphrase, byte[] salt)
    {
        using var argon = new Argon2id(Encoding.UTF8.GetBytes(passphrase)) { Salt = salt, Iterations = 3, MemorySize = 65536, DegreeOfParallelism = 2 };
        return argon.GetBytes(32);
    }

    private static void CheckPassphrase(string passphrase)
    {
        if (passphrase.EnumerateRunes().Count() is < 12 or > 1024 || Encoding.UTF8.GetByteCount(passphrase) > 4096)
            throw new BackupException("Use a backup passphrase of 12 to 1024 characters.", 422);
    }

    private static byte[] Canonical(JsonObject header) => Encoding.UTF8.GetBytes(AuthLens.Domain.Json.CanonicalJson.Serialize(header));

    /// <summary>Encrypts <paramref name="source"/> into <paramref name="destination"/>; a passphrase (when given) wins over the host key.</summary>
    public static JsonObject Seal(Stream source, Stream destination, string passphrase, byte[]? host)
    {
        var salt = RandomNumberGenerator.GetBytes(16);
        JsonObject header;
        byte[] key;
        if (passphrase.Length > 0)
        {
            CheckPassphrase(passphrase);
            header = new JsonObject { ["format"] = 3, ["algorithm"] = "AES-256-GCM-SEGMENTED", ["key_mode"] = "passphrase", ["kdf"] = "argon2id-m65536-t3-p2", ["key_id"] = "" };
            key = Argon(passphrase, salt);
        }
        else
        {
            if (host is not { Length: 32 }) throw new BackupException("Configure a protected host backup key, or use a backup passphrase.");
            header = new JsonObject { ["format"] = 3, ["algorithm"] = "AES-256-GCM-SEGMENTED", ["key_mode"] = "host-key", ["kdf"] = "hkdf-sha256", ["key_id"] = BackupKeys.Fingerprint(host) };
            key = HKDF.DeriveKey(HashAlgorithmName.SHA256, host, 32, salt, HostInfo);
        }
        header["salt"] = Convert.ToBase64String(salt);
        header["nonce_prefix"] = Convert.ToBase64String(RandomNumberGenerator.GetBytes(7));
        header["segment"] = Segment;
        var raw = Canonical(header);
        destination.Write(Magic);
        Span<byte> length = stackalloc byte[4];
        BinaryPrimitives.WriteUInt32BigEndian(length, (uint)raw.Length);
        destination.Write(length);
        destination.Write(raw);
        var aad = Magic.Concat(raw).ToArray();
        var prefix = Convert.FromBase64String((string)header["nonce_prefix"]!);
        using var gcm = new AesGcm(key, Tag);
        var current = new byte[Segment];
        var next = new byte[Segment];
        var currentLength = ReadFull(source, current);
        uint counter = 0;
        long total = 0;
        while (true)
        {
            var nextLength = currentLength == Segment ? ReadFull(source, next) : 0;
            var final = currentLength < Segment || nextLength == 0;
            total += currentLength;
            if (total > MaxArchive) throw new BackupException("The archive exceeds the 2 GiB limit.");
            var cipher = new byte[currentLength + Tag];
            gcm.Encrypt(Nonce(prefix, counter, final), current.AsSpan(0, currentLength), cipher.AsSpan(0, currentLength), cipher.AsSpan(currentLength), aad);
            destination.Write(cipher);
            if (final) break;
            (current, next, currentLength) = (next, current, nextLength);
            counter = checked(counter + 1);
        }
        CryptographicOperations.ZeroMemory(key);
        return header;
    }

    private static byte[] Nonce(byte[] prefix, uint counter, bool final)
    {
        var nonce = new byte[12];
        prefix.CopyTo(nonce, 0);
        BinaryPrimitives.WriteUInt32BigEndian(nonce.AsSpan(7), counter);
        nonce[11] = final ? (byte)1 : (byte)0;
        return nonce;
    }

    private static int ReadFull(Stream stream, byte[] buffer) => ReadFull(stream, buffer, 0, buffer.Length);

    private static int ReadFull(Stream stream, byte[] buffer, int offset, int count)
    {
        var read = 0;
        while (read < count) { var n = stream.Read(buffer, offset + read, count - read); if (n == 0) break; read += n; }
        return read;
    }

    /// <summary>The authenticated header of an SLBAK3 archive (format, key mode, key id) without decrypting it.</summary>
    public static (JsonObject Header, byte[] Raw) Envelope(Stream source, byte[] expectedMagic)
    {
        var magic = new byte[expectedMagic.Length];
        if (ReadFull(source, magic) != magic.Length || !magic.AsSpan().SequenceEqual(expectedMagic)) throw new BackupException("Select an encrypted AuthLens backup.", 422);
        var length = new byte[4];
        if (ReadFull(source, length) != 4) throw new BackupException("Truncated encrypted backup.", 422);
        var size = BinaryPrimitives.ReadUInt32BigEndian(length);
        if (size is < 1 or > 4096) throw new BackupException("Invalid encrypted backup header size.", 422);
        var raw = new byte[size];
        if (ReadFull(source, raw) != raw.Length) throw new BackupException("Truncated encrypted backup.", 422);
        try
        {
            var header = JsonNode.Parse(raw) as JsonObject ?? throw new FormatException();
            return (header, raw);
        }
        catch (Exception error) when (error is JsonException or FormatException) { throw new BackupException("Invalid encrypted backup metadata.", 422); }
    }

    /// <summary>Decrypts an SLBAK3 archive into <paramref name="destination"/>; nothing of a segment is written before it authenticates.</summary>
    public static JsonObject Unseal(Stream source, Stream destination, string secret, byte[]? host)
    {
        var (header, raw) = Envelope(source, Magic);
        var expected = new[] { "format", "algorithm", "key_mode", "kdf", "key_id", "salt", "nonce_prefix", "segment" };
        if (header.Count != expected.Length || expected.Any(k => !header.ContainsKey(k)) || (int?)header["format"] != 3 || (string?)header["algorithm"] != "AES-256-GCM-SEGMENTED"
            || (int?)header["segment"] != Segment) throw new BackupException("Unsupported encrypted backup format.", 422);
        byte[] salt, prefix;
        try { (salt, prefix) = (Convert.FromBase64String((string)header["salt"]!), Convert.FromBase64String((string)header["nonce_prefix"]!)); }
        catch (FormatException) { throw new BackupException("Invalid encrypted backup metadata.", 422); }
        if (salt.Length != 16 || prefix.Length != 7) throw new BackupException("Invalid encrypted backup metadata.", 422);
        var key = (string?)header["key_mode"] switch
        {
            "passphrase" when (string?)header["kdf"] == "argon2id-m65536-t3-p2" => DerivePassphrase(secret, salt),
            "host-key" when (string?)header["kdf"] == "hkdf-sha256" => HKDF.DeriveKey(HashAlgorithmName.SHA256, HostKeyFor(header, secret, host), 32, salt, HostInfo),
            _ => throw new BackupException("Unsupported backup key derivation.", 422),
        };
        var aad = Magic.Concat(raw).ToArray();
        using var gcm = new AesGcm(key, Tag);
        // One byte of lookahead tells whether a full segment is the last one (the final flag is part of the nonce).
        var buffer = new byte[Segment + Tag + 1];
        var plain = new byte[Segment];
        var filled = ReadFull(source, buffer, 0, buffer.Length);
        uint counter = 0;
        long total = 0;
        while (true)
        {
            var final = filled <= Segment + Tag;
            var length = final ? filled : Segment + Tag;
            if (length < Tag) throw new BackupException("Truncated encrypted backup.", 422);
            try { gcm.Decrypt(Nonce(prefix, counter, final), buffer.AsSpan(0, length - Tag), buffer.AsSpan(length - Tag, Tag), plain.AsSpan(0, length - Tag), aad); }
            catch (AuthenticationTagMismatchException) { throw new BackupException("Backup authentication failed. Check the passphrase or recovery key and the archive integrity.", 422); }
            total += length - Tag;
            if (total > MaxArchive) throw new BackupException("The archive exceeds the 2 GiB limit.", 422);
            destination.Write(plain, 0, length - Tag);
            if (final) break;
            buffer[0] = buffer[Segment + Tag];
            filled = 1 + ReadFull(source, buffer, 1, Segment + Tag);
            counter = checked(counter + 1);
        }
        CryptographicOperations.ZeroMemory(key);
        return header;
    }

    private static byte[] DerivePassphrase(string passphrase, byte[] salt)
    {
        CheckPassphrase(passphrase);
        return Argon(passphrase, salt);
    }

    /// <summary>The host key that matches the archive's key id: the configured host key, or a recovery key copy offered as the secret.</summary>
    private static byte[] HostKeyFor(JsonObject header, string secret, byte[]? host)
    {
        var id = (string?)header["key_id"];
        if (host is { Length: 32 } && BackupKeys.Fingerprint(host) == id) return host;
        if (secret.Length > 0)
            try { var offered = Convert.FromBase64String(secret.Trim()); if (offered.Length == 32 && BackupKeys.Fingerprint(offered) == id) return offered; }
            catch (FormatException) { }
        throw new BackupException("The matching separately stored recovery key is required.", 422);
    }

    public const long V1MigrationLimit = 1L << 30;

    /// <summary>The key mode of a SAP Lens 1 archive ("passphrase" or "host-key") read from its header, so the right secret can be asked for.</summary>
    public static string V1KeyMode(Stream source)
    {
        var (header, _) = Envelope(source, V1Magic);
        return (string?)header["key_mode"] is "passphrase" or "host-key" ? (string)header["key_mode"]! : throw new BackupException("Unsupported SAP Lens 1 encrypted backup format.", 422);
    }

    /// <summary>Decrypts a SAP Lens 1 SLBAK2 archive (one AES-256-GCM stream, tag at the end; scrypt N=32768 r=8 p=1 or HKDF-SHA256 host key). The whole
    /// ciphertext is authenticated before any plaintext is returned.</summary>
    /// <param name="limit">Largest ciphertext accepted. SAP Lens 1 seals one AES-GCM stream with the tag at the end, so it is authenticated in memory: the
    /// application restore path keeps 256 MiB, the data migration allows <see cref="V1MigrationLimit"/>.</param>
    public static byte[] UnsealV1(Stream source, string secret, byte[]? host, long limit = 256L * 1024 * 1024)
    {
        var (header, raw) = Envelope(source, V1Magic);
        var expected = new[] { "format", "algorithm", "key_mode", "kdf", "salt", "key_id", "nonce" };
        if (header.Count != expected.Length || expected.Any(k => !header.ContainsKey(k)) || (int?)header["format"] != 2 || (string?)header["algorithm"] != "AES-256-GCM")
            throw new BackupException("Unsupported SAP Lens 1 encrypted backup format.", 422);
        byte[] salt, nonce;
        try { (salt, nonce) = (Convert.FromBase64String((string)header["salt"]!), Convert.FromBase64String((string)header["nonce"]!)); }
        catch (FormatException) { throw new BackupException("Invalid encrypted backup metadata.", 422); }
        if (salt.Length != 16 || nonce.Length != 12) throw new BackupException("Invalid encrypted backup metadata.", 422);
        byte[] key = (string?)header["key_mode"] switch
        {
            "passphrase" when (string?)header["kdf"] == "scrypt-32768-8-1" && (string?)header["key_id"] == "" =>
                secret.EnumerateRunes().Count() is >= 12 and <= 1024 ? Scrypt.Derive(Encoding.UTF8.GetBytes(secret), salt, 32768, 8, 1, 32)
                    : throw new BackupException("Use the original backup passphrase (12 to 1024 characters).", 422),
            "host-key" when (string?)header["kdf"] == "hkdf-sha256" => HKDF.DeriveKey(HashAlgorithmName.SHA256, HostKeyFor(header, secret, host), 32, salt, V1HostInfo),
            _ => throw new BackupException("Unsupported backup key derivation.", 422),
        };
        byte[] data;
        if (source.CanSeek)
        {
            var remaining = source.Length - source.Position;
            if (remaining < Tag || remaining - Tag > limit) throw new BackupException(remaining - Tag > limit ? $"The archive exceeds the {limit >> 20} MiB limit of this operation." : "Invalid encrypted backup size.", 422);
            data = new byte[remaining];
            if (ReadFull(source, data, 0, data.Length) != data.Length) throw new BackupException("Truncated encrypted backup.", 422);
        }
        else
        {
            using var rest = new MemoryStream();
            source.CopyTo(rest);
            data = rest.ToArray();
        }
        if (data.Length < Tag || data.Length - Tag > limit) throw new BackupException("Invalid encrypted backup size.", 422);
        var plain = new byte[data.Length - Tag];
        using var gcm = new AesGcm(key, Tag);
        try { gcm.Decrypt(nonce, data.AsSpan(0, plain.Length), data.AsSpan(plain.Length), plain, V1Magic.Concat(raw).ToArray()); }
        catch (AuthenticationTagMismatchException) { throw new BackupException("Backup authentication failed. Check the passphrase or recovery key and the archive integrity.", 422); }
        return plain;
    }
}

/// <summary>scrypt (RFC 7914), used only to open SAP Lens 1 passphrase archives: PBKDF2-HMAC-SHA256 from the base library around ROMix with Salsa20/8
/// BlockMix. Verified against the RFC 7914 test vectors.</summary>
public static class Scrypt
{
    public static byte[] Derive(byte[] password, byte[] salt, int n, int r, int p, int length)
    {
        if (n < 2 || (n & (n - 1)) != 0 || r < 1 || p < 1) throw new ArgumentException("Invalid scrypt parameters.");
        var blockSize = 128 * r;
        var b = Rfc2898DeriveBytes.Pbkdf2(password, salt, 1, HashAlgorithmName.SHA256, p * blockSize);
        var x = new uint[32 * r];
        var v = new uint[32 * r * n];
        var scratch = new uint[32 * r];
        for (var i = 0; i < p; i++)
        {
            var offset = i * blockSize;
            for (var k = 0; k < x.Length; k++) x[k] = BinaryPrimitives.ReadUInt32LittleEndian(b.AsSpan(offset + 4 * k));
            for (var j = 0; j < n; j++) { Array.Copy(x, 0, v, j * x.Length, x.Length); BlockMix(x, scratch, r); }
            for (var j = 0; j < n; j++)
            {
                var index = (int)(x[(2 * r - 1) * 16] & (uint)(n - 1));
                for (var k = 0; k < x.Length; k++) x[k] ^= v[index * x.Length + k];
                BlockMix(x, scratch, r);
            }
            for (var k = 0; k < x.Length; k++) BinaryPrimitives.WriteUInt32LittleEndian(b.AsSpan(offset + 4 * k), x[k]);
        }
        Array.Clear(v);
        return Rfc2898DeriveBytes.Pbkdf2(password, b, 1, HashAlgorithmName.SHA256, length);
    }

    private static void BlockMix(uint[] b, uint[] y, int r)
    {
        Span<uint> x = stackalloc uint[16];
        b.AsSpan((2 * r - 1) * 16, 16).CopyTo(x);
        for (var i = 0; i < 2 * r; i++)
        {
            for (var k = 0; k < 16; k++) x[k] ^= b[i * 16 + k];
            Salsa208(x);
            x.CopyTo(y.AsSpan(i * 16, 16));
        }
        for (var i = 0; i < r; i++) Array.Copy(y, (2 * i) * 16, b, i * 16, 16);
        for (var i = 0; i < r; i++) Array.Copy(y, (2 * i + 1) * 16, b, (r + i) * 16, 16);
    }

    private static uint R(uint a, int b) => (a << b) | (a >> (32 - b));

    private static void Salsa208(Span<uint> b)
    {
        Span<uint> x = stackalloc uint[16];
        b.CopyTo(x);
        for (var i = 0; i < 8; i += 2)
        {
            x[4] ^= R(x[0] + x[12], 7); x[8] ^= R(x[4] + x[0], 9); x[12] ^= R(x[8] + x[4], 13); x[0] ^= R(x[12] + x[8], 18);
            x[9] ^= R(x[5] + x[1], 7); x[13] ^= R(x[9] + x[5], 9); x[1] ^= R(x[13] + x[9], 13); x[5] ^= R(x[1] + x[13], 18);
            x[14] ^= R(x[10] + x[6], 7); x[2] ^= R(x[14] + x[10], 9); x[6] ^= R(x[2] + x[14], 13); x[10] ^= R(x[6] + x[2], 18);
            x[3] ^= R(x[15] + x[11], 7); x[7] ^= R(x[3] + x[15], 9); x[11] ^= R(x[7] + x[3], 13); x[15] ^= R(x[11] + x[7], 18);
            x[1] ^= R(x[0] + x[3], 7); x[2] ^= R(x[1] + x[0], 9); x[3] ^= R(x[2] + x[1], 13); x[0] ^= R(x[3] + x[2], 18);
            x[6] ^= R(x[5] + x[4], 7); x[7] ^= R(x[6] + x[5], 9); x[4] ^= R(x[7] + x[6], 13); x[5] ^= R(x[4] + x[7], 18);
            x[11] ^= R(x[10] + x[9], 7); x[8] ^= R(x[11] + x[10], 9); x[9] ^= R(x[8] + x[11], 13); x[10] ^= R(x[9] + x[8], 18);
            x[12] ^= R(x[15] + x[14], 7); x[13] ^= R(x[12] + x[15], 9); x[14] ^= R(x[13] + x[12], 13); x[15] ^= R(x[14] + x[13], 18);
        }
        for (var i = 0; i < 16; i++) b[i] += x[i];
    }
}

/// <summary>Windows ACL for private files: inheritance removed; full control for the current user, SYSTEM and Administrators only.</summary>
internal static class WindowsPrivate
{
    [System.Runtime.Versioning.SupportedOSPlatform("windows")]
    public static FileStream Create(string path)
    {
        var info = new FileInfo(path);
        var security = new System.Security.AccessControl.FileSecurity();
        security.SetAccessRuleProtection(true, false);
        foreach (var sid in new[] { System.Security.Principal.WindowsIdentity.GetCurrent().User!,
                     new System.Security.Principal.SecurityIdentifier(System.Security.Principal.WellKnownSidType.LocalSystemSid, null),
                     new System.Security.Principal.SecurityIdentifier(System.Security.Principal.WellKnownSidType.BuiltinAdministratorsSid, null) })
            security.AddAccessRule(new System.Security.AccessControl.FileSystemAccessRule(sid, System.Security.AccessControl.FileSystemRights.FullControl, System.Security.AccessControl.AccessControlType.Allow));
        return System.IO.FileSystemAclExtensions.Create(info, FileMode.CreateNew, System.Security.AccessControl.FileSystemRights.Write,
            FileShare.None, 4096, FileOptions.None, security);
    }
}
