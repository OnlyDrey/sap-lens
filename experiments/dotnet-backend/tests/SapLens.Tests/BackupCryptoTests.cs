using System.Security.Cryptography;
using System.Text;
using System.Text.Json.Nodes;
using SapLens.Application.Backups;

namespace SapLens.Tests;

/// <summary>Backup cryptography: scrypt against RFC 7914, the SLBAK3 segmented AES-256-GCM envelope (boundaries, tampering, truncation, wrong keys), and
/// decryption of SAP Lens 1 SLBAK2 archives written by v1 backup_crypto (Fixtures/backups, tools/backup_v1_reference.py).</summary>
public sealed class BackupCryptoTests
{
    private static string Fixture(string name) => Path.Combine(AppContext.BaseDirectory, "Fixtures", "backups", name);

    [Theory]
    [InlineData("", "", 16, 1, 1, "77d6576238657b203b19ca42c18a0497f16b4844e3074ae8dfdffa3fede21442fcd0069ded0948f8326a753a0fc81f17e8d3e0fb2e0d3628cf35e20c38d18906")]
    [InlineData("password", "NaCl", 1024, 8, 16, "fdbabe1c9d3472007856e7190d01e9fe7c6ad7cbc8237830e77376634b3731622eaf30d92e22a3886ff109279d9830dac727afb94a83ee6d8360cbdfa2cc0640")]
    public void Scrypt_matches_rfc_7914(string password, string salt, int n, int r, int p, string expected) =>
        Assert.Equal(expected, Convert.ToHexStringLower(Scrypt.Derive(Encoding.ASCII.GetBytes(password), Encoding.ASCII.GetBytes(salt), n, r, p, 64)));

    private static byte[] Seal(byte[] plain, string passphrase, byte[]? host)
    {
        using var output = new MemoryStream();
        BackupArchive.Seal(new MemoryStream(plain), output, passphrase, host);
        return output.ToArray();
    }

    private static byte[] Unseal(byte[] archive, string secret, byte[]? host)
    {
        using var output = new MemoryStream();
        BackupArchive.Unseal(new MemoryStream(archive), output, secret, host);
        return output.ToArray();
    }

    [Theory]
    [InlineData(0)]
    [InlineData(1)]
    [InlineData(BackupArchive.Segment - 1)]
    [InlineData(BackupArchive.Segment)]
    [InlineData(BackupArchive.Segment + 1)]
    [InlineData(2 * BackupArchive.Segment)]
    public void Host_key_archives_round_trip_at_segment_boundaries(int size)
    {
        var host = RandomNumberGenerator.GetBytes(32);
        var plain = RandomNumberGenerator.GetBytes(size);
        Assert.Equal(plain, Unseal(Seal(plain, "", host), "", host));
    }

    [Fact]
    public void Passphrase_archives_round_trip_and_wrong_secrets_tampering_and_truncation_fail()
    {
        var plain = RandomNumberGenerator.GetBytes(BackupArchive.Segment + 5000);
        const string passphrase = "Synthetic backup passphrase æøå";
        var archive = Seal(plain, passphrase, null);
        Assert.Equal(plain, Unseal(archive, passphrase, null));
        Assert.Throws<BackupException>(() => Unseal(archive, "Wrong backup passphrase!!", null));
        Assert.Throws<BackupException>(() => Unseal(archive, "short", null));
        var tampered = (byte[])archive.Clone();
        tampered[^100] ^= 1;
        Assert.Throws<BackupException>(() => Unseal(tampered, passphrase, null));
        var header = (byte[])archive.Clone();
        header[20] ^= 1;                                                              // inside the authenticated header
        Assert.Throws<BackupException>(() => Unseal(header, passphrase, null));
        // Dropping the final segment leaves a non-final segment last: refused, never accepted as a shorter archive.
        Assert.Throws<BackupException>(() => Unseal(archive[..(archive.Length - (5000 + BackupArchive.Tag))], passphrase, null));
        Assert.Throws<BackupException>(() => Unseal(archive[..30], passphrase, null));
    }

    [Fact]
    public void A_host_key_archive_needs_the_matching_key_or_its_recovery_copy()
    {
        var host = RandomNumberGenerator.GetBytes(32);
        var archive = Seal([1, 2, 3], "", host);
        Assert.Throws<BackupException>(() => Unseal(archive, "", RandomNumberGenerator.GetBytes(32)));
        Assert.Equal([1, 2, 3], Unseal(archive, Convert.ToBase64String(host), null));     // the escrowed recovery copy on another host
    }

    [Theory]
    [InlineData("v1-host.slbak")]
    [InlineData("v1-passphrase.slbak")]
    public void Sap_lens_1_archives_decrypt(string name)
    {
        var keys = JsonNode.Parse(File.ReadAllText(Fixture("keys.json")))!;
        var host = Convert.FromBase64String((string)keys["host_key"]!);
        using var stream = File.OpenRead(Fixture(name));
        var plain = name.Contains("host") ? BackupArchive.UnsealV1(stream, "", host) : BackupArchive.UnsealV1(stream, (string)keys["passphrase"]!, null);
        Assert.Equal(File.ReadAllBytes(Fixture("payload.bin")), plain);
        using var again = File.OpenRead(Fixture(name));
        Assert.Throws<BackupException>(() => BackupArchive.UnsealV1(again, "Wrong v1 backup passphrase", RandomNumberGenerator.GetBytes(32)));
    }
}
