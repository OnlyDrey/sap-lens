using System.Net;
using System.Security.Cryptography;

namespace SapLens.Api;

public enum HostMode { Server, Desktop }

/// <summary>Hosting policy shared by Desktop and Server (one place, like backend/deployment.py in v1).</summary>
public sealed class HostSettings
{
    public required string DataDirectory { get; init; }
    public HostMode Mode { get; init; } = HostMode.Server;
    public string Url { get; init; } = "http://127.0.0.1:18790";
    public required string AccessToken { get; init; }
    public string? FrontendDirectory { get; init; }
    public string PrincipalName { get; init; } = "local-user";
    public bool WorkerEnabled { get; init; } = true;
    public bool JsonConsoleLogging { get; init; } = true;

    public const int MinimumTokenLength = 32;

    public static string NewToken() => Convert.ToBase64String(RandomNumberGenerator.GetBytes(32)).TrimEnd('=').Replace('+', '-').Replace('/', '_');

    /// <summary>The prototype has no TLS and no identity provider, so it never listens beyond loopback. A non-loopback bind is refused, not warned about.</summary>
    public void Validate()
    {
        if (AccessToken.Length < MinimumTokenLength) throw new InvalidOperationException($"The API access token must have at least {MinimumTokenLength} characters.");
        var uri = new Uri(Url);
        if (uri.Scheme != Uri.UriSchemeHttp) throw new InvalidOperationException("Only http on loopback is supported by the prototype.");
        if (!IPAddress.TryParse(uri.Host, out var address) || !IPAddress.IsLoopback(address))
            throw new InvalidOperationException("The prototype binds only to a loopback IP address (127.0.0.1 or ::1); remote access needs TLS and real authentication first.");
    }
}
