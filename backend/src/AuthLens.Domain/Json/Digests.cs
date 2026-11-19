using System.Security.Cryptography;
using System.Text;

namespace AuthLens.Domain.Json;

/// <summary>Lower-case hex SHA-256 of a file (streamed), bytes or UTF-8 text: the content addresses and checksums used throughout AuthLens.</summary>
public static class Digests
{
    public static string File(string path)
    {
        using var stream = System.IO.File.OpenRead(path);
        return Convert.ToHexStringLower(SHA256.HashData(stream));
    }

    public static string Bytes(ReadOnlySpan<byte> bytes) => Convert.ToHexStringLower(SHA256.HashData(bytes));

    public static string Text(string text) => Bytes(Encoding.UTF8.GetBytes(text));
}
