using System.ComponentModel;
using System.Net;
using System.Net.Security;
using System.Net.Sockets;
using System.Runtime.Versioning;
using System.Security.Authentication;
using System.Runtime.CompilerServices;
using System.Security.Cryptography;
using System.Security.Cryptography.X509Certificates;

[assembly: InternalsVisibleTo("SapLens.Tests")]

namespace SapLens.Api;

public enum HostMode { Server, Desktop }

/// <summary>Hosting policy shared by Desktop and Server (one place, like backend/deployment.py in v1). Secure by default and fail closed:
/// loopback unless network access is enabled explicitly; network access needs one specific private LAN address, HTTPS with a valid certificate and
/// an explicit list of host names clients use. The Desktop is loopback-only, always.</summary>
public sealed class HostSettings
{
    public required string DataDirectory { get; init; }
    public HostMode Mode { get; init; } = HostMode.Server;
    public IPAddress ListenAddress { get; init; } = IPAddress.Loopback;
    public int Port { get; init; } = 18790;
    public bool NetworkAccess { get; init; }
    public X509Certificate2? Certificate { get; init; }
    public IReadOnlyList<string> AllowedHosts { get; init; } = [];
    public required string AccessToken { get; init; }
    public string PrincipalName { get; init; } = "local-user";
    /// <summary>Server only. Accounts: v1 local accounts with server sessions and roles (the default for a deployed Server). SharedToken: one
    /// operator identity for everyone holding the access token (Desktop, tests, API clients).</summary>
    public AuthenticationMode Authentication { get; init; } = AuthenticationMode.SharedToken;
    public bool WorkerEnabled { get; init; } = true;
    public bool JsonConsoleLogging { get; init; } = true;

    /// <summary>Which addresses network access may use. Not configurable by operators (no option or environment variable sets it); tests replace it
    /// only to bind the container's documentation-range interface.</summary>
    internal Func<IPAddress, bool> PermittedNetworkAddress { get; init; } = NetworkPolicy.IsPrivate;

    public const int MinimumTokenLength = 32;
    public bool Https => Certificate is not null;

    public static string NewToken() => Convert.ToBase64String(RandomNumberGenerator.GetBytes(32)).TrimEnd('=').Replace('+', '-').Replace('/', '_');

    public void Validate(DateTimeOffset? now = null)
    {
        if (AccessToken.Length < MinimumTokenLength) throw new InvalidOperationException($"The API access token must have at least {MinimumTokenLength} characters.");
        if (Port is < 0 or > 65535) throw new InvalidOperationException("The port must be between 1 and 65535.");
        if (Mode == HostMode.Desktop && Authentication != AuthenticationMode.SharedToken)
            throw new InvalidOperationException("The Desktop has one local user; account sign-in is a Server feature.");
        if (Mode == HostMode.Desktop)
        {
            if (NetworkAccess || !IPAddress.IsLoopback(ListenAddress) || Certificate is not null || AllowedHosts.Count > 0)
                throw new InvalidOperationException("The Desktop is loopback-only; network access, certificates and extra host names are refused.");
            return;
        }
        if (!NetworkAccess)
        {
            if (!IPAddress.IsLoopback(ListenAddress))
                throw new InvalidOperationException($"Listening on {ListenAddress} needs network access to be enabled explicitly (--network) with HTTPS.");
        }
        else
        {
            if (ListenAddress.Equals(IPAddress.Any) || ListenAddress.Equals(IPAddress.IPv6Any))
                throw new InvalidOperationException("Network access needs one specific LAN address; all interfaces (0.0.0.0, ::) are never used.");
            if (IPAddress.IsLoopback(ListenAddress)) throw new InvalidOperationException("Network access needs a LAN address, not loopback.");
            if (!PermittedNetworkAddress(ListenAddress))
                throw new InvalidOperationException($"{ListenAddress} is not a private LAN address (10/8, 172.16/12, 192.168/16, 169.254/16, fc00::/7, fe80::/10); exposure beyond the local network is refused.");
            if (Port == 0) throw new InvalidOperationException("Network access needs a fixed port.");
            if (Certificate is null) throw new InvalidOperationException("Network access requires HTTPS: configure a certificate (--cert).");
            if (AllowedHosts.Count == 0) throw new InvalidOperationException("Network access needs the host names or addresses clients use (--allowed-hosts).");
            foreach (var host in AllowedHosts)
                if (host.Length == 0 || host.Contains('*') || host.Contains('/') || host.Contains(':') && !IPAddress.TryParse(host, out _))
                    throw new InvalidOperationException($"'{host}' is not a valid host name or address for --allowed-hosts.");
        }
        if (Certificate is not null)
        {
            var problems = CertificatePolicy.Validate(Certificate, NetworkAccess ? AllowedHosts : [], now ?? DateTimeOffset.UtcNow).Problems;
            if (problems.Count > 0) throw new InvalidOperationException("The TLS certificate is not usable: " + string.Join(" ", problems));
        }
    }

    /// <summary>Host header check (DNS-rebinding and misdirected-request defence): loopback names always, plus the configured names in network mode.</summary>
    public bool HostAllowed(string host)
    {
        if (host is "127.0.0.1" or "localhost" or "[::1]" or "::1") return true;
        return NetworkAccess && AllowedHosts.Any(h => string.Equals(h, host.Trim('[', ']'), StringComparison.OrdinalIgnoreCase));
    }
}

public static class NetworkPolicy
{
    /// <summary>Private or link-local unicast addresses: never routed on the public internet.</summary>
    public static bool IsPrivate(IPAddress address)
    {
        if (address.IsIPv4MappedToIPv6) address = address.MapToIPv4();
        var b = address.GetAddressBytes();
        return address.AddressFamily switch
        {
            AddressFamily.InterNetwork => b[0] == 10 || (b[0] == 172 && b[1] >= 16 && b[1] <= 31) || (b[0] == 192 && b[1] == 168) || (b[0] == 169 && b[1] == 254),
            AddressFamily.InterNetworkV6 => (b[0] & 0xFE) == 0xFC || address.IsIPv6LinkLocal,
            _ => false,
        };
    }
}

public sealed record CertificateCheck(IReadOnlyList<string> Problems, IReadOnlyList<string> Warnings);

/// <summary>Startup validation of the server certificate. Chain trust is the clients' decision (an internal CA is expected); the server refuses
/// certificates that cannot work: no private key, not yet or no longer valid, not for server authentication, weak key, or names that do not cover the
/// configured host names (browsers ignore the subject CN).</summary>
public static class CertificatePolicy
{
    private const string ServerAuth = "1.3.6.1.5.5.7.3.1";

    public static CertificateCheck Validate(X509Certificate2 certificate, IReadOnlyList<string> hosts, DateTimeOffset now)
    {
        var problems = new List<string>();
        var warnings = new List<string>();
        if (!certificate.HasPrivateKey) problems.Add("It has no private key.");
        if (now < certificate.NotBefore) problems.Add($"It is not valid before {certificate.NotBefore:u}.");
        if (now > certificate.NotAfter) problems.Add($"It expired on {certificate.NotAfter:u}.");
        else if (certificate.NotAfter - now < TimeSpan.FromDays(30)) warnings.Add($"It expires on {certificate.NotAfter:u}.");
        var eku = certificate.Extensions.OfType<X509EnhancedKeyUsageExtension>().FirstOrDefault();
        if (eku is not null && !eku.EnhancedKeyUsages.Cast<System.Security.Cryptography.Oid>().Any(o => o.Value == ServerAuth))
            problems.Add("It is not issued for server authentication.");
        using (var rsa = certificate.GetRSAPublicKey()) if (rsa is not null && rsa.KeySize < 2048) problems.Add("Its RSA key is shorter than 2048 bits.");
        var san = certificate.Extensions.OfType<X509SubjectAlternativeNameExtension>().FirstOrDefault();
        var dns = san?.EnumerateDnsNames().ToList() ?? [];
        var ips = san?.EnumerateIPAddresses().ToList() ?? [];
        foreach (var host in hosts)
        {
            var covered = IPAddress.TryParse(host, out var ip) ? ips.Any(a => a.Equals(ip)) : dns.Any(d => DnsMatches(d, host));
            if (!covered) problems.Add($"Its subject alternative names do not include '{host}'.");
        }
        return new CertificateCheck(problems, warnings);
    }

    private static bool DnsMatches(string pattern, string host)
    {
        if (string.Equals(pattern, host, StringComparison.OrdinalIgnoreCase)) return true;
        if (!pattern.StartsWith("*.", StringComparison.Ordinal)) return false;
        var dot = host.IndexOf('.');
        return dot > 0 && string.Equals(pattern[1..], host[dot..], StringComparison.OrdinalIgnoreCase);
    }

    /// <summary>Loads a PFX/PKCS#12 (Windows and Linux) or a PEM certificate with its key. The password never appears in messages.</summary>
    public static X509Certificate2 Load(string path, string? keyPath, string? password)
    {
        if (!File.Exists(path)) throw new InvalidOperationException($"The certificate file '{path}' does not exist.");
        if (keyPath is not null && !File.Exists(keyPath)) throw new InvalidOperationException($"The certificate key file '{keyPath}' does not exist.");
        try
        {
            var extension = Path.GetExtension(path).ToLowerInvariant();
            if (extension is ".pfx" or ".p12")
                // Windows SChannel cannot use ephemeral keys; on Linux nothing is written to a key store.
                return X509CertificateLoader.LoadPkcs12FromFile(path, password, OperatingSystem.IsWindows() ? X509KeyStorageFlags.UserKeySet : X509KeyStorageFlags.EphemeralKeySet);
            var pem = password is null ? X509Certificate2.CreateFromPemFile(path, keyPath) : X509Certificate2.CreateFromEncryptedPemFile(path, password, keyPath);
            var prepared = PrepareForServer(pem);
            if (!ReferenceEquals(prepared, pem)) pem.Dispose();
            return prepared;
        }
        catch (CryptographicException)
        {
            throw new InvalidOperationException($"The certificate '{path}' could not be opened (wrong password, missing key or damaged file).");
        }
    }

    public static readonly SslProtocols ServerProtocols = SslProtocols.Tls12 | SslProtocols.Tls13;

    /// <summary>Windows SChannel cannot use a private key that exists only in memory (an ephemeral CNG key, which CertificateRequest.CreateSelfSigned and
    /// X509Certificate2.CreateFromPemFile produce): the server handshake is aborted and clients only see an EOF. Such certificates are re-imported through
    /// PKCS#12 so the key lives in a key container for this process (removed when the certificate is disposed). Other platforms and certificates whose key
    /// is already stored are returned unchanged.</summary>
    public static X509Certificate2 PrepareForServer(X509Certificate2 certificate)
    {
        if (!OperatingSystem.IsWindows() || !certificate.HasPrivateKey || !HasEphemeralKey(certificate)) return certificate;
        var transfer = Convert.ToBase64String(RandomNumberGenerator.GetBytes(18)); // protects the in-memory PKCS#12 blob only
        return X509CertificateLoader.LoadPkcs12(certificate.Export(X509ContentType.Pkcs12, transfer), transfer, X509KeyStorageFlags.UserKeySet);
    }

    [SupportedOSPlatform("windows")]
    public static bool HasEphemeralKey(X509Certificate2 certificate)
    {
        using (var rsa = certificate.GetRSAPrivateKey()) if (rsa is RSACng rsaCng) return rsaCng.Key.IsEphemeral;
        using (var ec = certificate.GetECDsaPrivateKey()) if (ec is ECDsaCng ecCng) return ecCng.Key.IsEphemeral;
        return false;
    }

    /// <summary>Startup self-check: a real TLS handshake with this certificate through the operating system's TLS stack over a private loopback socket.
    /// Returns null when it works, otherwise the server-side error (never a password). The self-check client pins the certificate's own thumbprint; it
    /// is not how LAN clients validate the server.</summary>
    public static async Task<string?> VerifyTlsHandshakeAsync(X509Certificate2 certificate, TimeSpan timeout)
    {
        using var cts = new CancellationTokenSource(timeout);
        using var listener = new TcpListener(IPAddress.Loopback, 0);
        listener.Start();
        using var client = new TcpClient();
        var accept = listener.AcceptTcpClientAsync(cts.Token).AsTask();
        await client.ConnectAsync(IPAddress.Loopback, ((IPEndPoint)listener.LocalEndpoint).Port, cts.Token);
        using var serverSocket = await accept;
        var thumbprint = certificate.GetCertHashString();
        await using var server = new SslStream(serverSocket.GetStream(), leaveInnerStreamOpen: false);
        await using var clientTls = new SslStream(client.GetStream(), leaveInnerStreamOpen: false);
        var clientTask = clientTls.AuthenticateAsClientAsync(new SslClientAuthenticationOptions
        {
            TargetHost = "localhost", EnabledSslProtocols = ServerProtocols, RemoteCertificateValidationCallback = (_, c, _, _) => c?.GetCertHashString() == thumbprint,
        }, cts.Token);
        try
        {
            await server.AuthenticateAsServerAsync(new SslServerAuthenticationOptions { ServerCertificate = certificate, EnabledSslProtocols = ServerProtocols }, cts.Token);
        }
        catch (Exception error) when (error is AuthenticationException or IOException or Win32Exception or CryptographicException or NotSupportedException or OperationCanceledException)
        {
            serverSocket.Dispose(); // release the client side at once
            try { await clientTask; } catch (Exception) { /* the server error is the cause */ }
            return Describe(error);
        }
        try { await clientTask; }
        catch (Exception error) when (error is AuthenticationException or IOException or OperationCanceledException) { return "client side: " + Describe(error); }
        return null;
    }

    private static string Describe(Exception error)
    {
        var text = $"{error.GetType().Name}: {error.Message}";
        for (var inner = error.InnerException; inner is not null; inner = inner.InnerException) text += $" <- {inner.GetType().Name}: {inner.Message}";
        return text;
    }
}
