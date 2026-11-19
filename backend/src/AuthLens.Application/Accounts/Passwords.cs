using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using Konscious.Security.Cryptography;

namespace AuthLens.Application.Accounts;

/// <summary>Password verifiers compatible with SAP Lens v1 (auth_store.py): Argon2id in the PHC string format argon2-cffi writes
/// (<c>$argon2id$v=19$m=65536,t=3,p=2$salt$hash</c>, unpadded base64, 16-byte salt, 32-byte hash), and v1's legacy
/// <c>pbkdf2:{json}</c> verifiers (SHA-256, 600 000 iterations), which are only verified and replaced by Argon2id at the next sign-in.</summary>
public static class Passwords
{
    public const int TimeCost = 3, MemoryCost = 65536, Parallelism = 2, HashLength = 32, SaltLength = 16;
    public const int MinLength = 12, MaxLength = 1024, MaxBytes = 4096;

    public static int Length(string value) => value.EnumerateRunes().Count();

    public static bool Acceptable(string? password) =>
        password is not null && Length(password) is >= MinLength and <= MaxLength && Encoding.UTF8.GetByteCount(password) <= MaxBytes;

    public static string Hash(string password)
    {
        if (!Acceptable(password)) throw new AuthException("password_length");
        var salt = RandomNumberGenerator.GetBytes(SaltLength);
        var hash = Derive(password, salt, TimeCost, MemoryCost, Parallelism, HashLength);
        return $"$argon2id$v=19$m={MemoryCost},t={TimeCost},p={Parallelism}${B64(salt)}${B64(hash)}";
    }

    public static bool Verify(string? verifier, string? password)
    {
        if (verifier is null || password is null || Length(password) > MaxLength || Encoding.UTF8.GetByteCount(password) > MaxBytes) return false;
        try
        {
            if (verifier.StartsWith("$argon2id$", StringComparison.Ordinal))
            {
                if (Parse(verifier) is not { } p) return false;
                return CryptographicOperations.FixedTimeEquals(p.Hash, Derive(password, p.Salt, p.Time, p.Memory, p.Lanes, p.Hash.Length));
            }
            if (verifier.StartsWith("pbkdf2:", StringComparison.Ordinal))
            {
                using var row = JsonDocument.Parse(verifier[7..]);
                if (row.RootElement.GetProperty("iterations").GetInt32() != 600_000) return false;
                var expected = Convert.FromBase64String(row.RootElement.GetProperty("hash").GetString()!);
                var salt = Convert.FromBase64String(row.RootElement.GetProperty("salt").GetString()!);
                if (expected.Length != 32 || salt.Length != 32) return false;
                return CryptographicOperations.FixedTimeEquals(expected, Rfc2898DeriveBytes.Pbkdf2(Encoding.UTF8.GetBytes(password), salt, 600_000, HashAlgorithmName.SHA256, 32));
            }
        }
        catch (Exception error) when (error is FormatException or JsonException or KeyNotFoundException or InvalidOperationException or ArgumentException or OverflowException) { }
        return false;
    }

    /// <summary>argon2-cffi check_needs_rehash: any parameter, length or type differs from the current policy.</summary>
    public static bool NeedsRehash(string verifier) =>
        Parse(verifier) is not { } p || (p.Time, p.Memory, p.Lanes, p.Hash.Length, p.Salt.Length) != (TimeCost, MemoryCost, Parallelism, HashLength, SaltLength);

    private sealed record Parsed(int Memory, int Time, int Lanes, byte[] Salt, byte[] Hash);

    private static Parsed? Parse(string verifier)
    {
        var parts = verifier.Split('$');
        if (parts.Length != 6 || parts[0] != "" || parts[1] != "argon2id" || parts[2] != "v=19") return null;
        var values = parts[3].Split(',').Select(p => p.Split('=')).Where(p => p.Length == 2).ToDictionary(p => p[0], p => int.Parse(p[1], System.Globalization.CultureInfo.InvariantCulture));
        if (!values.TryGetValue("m", out var m) || !values.TryGetValue("t", out var t) || !values.TryGetValue("p", out var l)) return null;
        if (m is < 8 or > 4 * 1024 * 1024 || t is < 1 or > 64 || l is < 1 or > 64) return null; // bounded: a stored verifier cannot make sign-in unbounded
        var salt = Unb64(parts[4]);
        var hash = Unb64(parts[5]);
        return salt.Length >= 8 && hash.Length is >= 16 and <= 128 ? new Parsed(m, t, l, salt, hash) : null;
    }

    private static byte[] Derive(string password, byte[] salt, int time, int memory, int lanes, int length)
    {
        using var argon = new Argon2id(Encoding.UTF8.GetBytes(password)) { Salt = salt, Iterations = time, MemorySize = memory, DegreeOfParallelism = lanes };
        return argon.GetBytes(length);
    }

    private static string B64(byte[] value) => Convert.ToBase64String(value).TrimEnd('=');

    private static byte[] Unb64(string value) => Convert.FromBase64String(value + new string('=', (4 - value.Length % 4) % 4));
}

/// <summary>A refused authentication or account operation. <see cref="Code"/> is the stable v1 code the React client maps to a message.</summary>
public sealed class AuthException(string code, int status = 400) : Exception(code)
{
    public string Code { get; } = code;
    public int Status { get; } = status;
}
