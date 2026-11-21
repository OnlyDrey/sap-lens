using System.Net;
using System.Net.NetworkInformation;
using System.Net.Security;
using System.Net.Sockets;
using System.Security.Cryptography.X509Certificates;
using System.Text;
using Microsoft.AspNetCore.Builder;
using Microsoft.AspNetCore.Http;
using Microsoft.Extensions.Logging;
using AuthLens.Api;

namespace AuthLens.Tests;

/// <summary>Origin comparison and trusted-proxy configuration (no listener).</summary>
public sealed class OriginPolicyTests
{
    [Theory]
    [InlineData("https://lens.proxy.test", "https", "lens.proxy.test", OriginPolicy.Result.Match)]
    [InlineData("https://lens.proxy.test", "https", "lens.proxy.test:443", OriginPolicy.Result.Match)]
    [InlineData("https://lens.proxy.test:443", "https", "lens.proxy.test", OriginPolicy.Result.Match)]
    [InlineData("HTTPS://LENS.Proxy.Test", "https", "lens.proxy.test", OriginPolicy.Result.Match)]
    [InlineData("https://lens.proxy.test", "https", "lens.proxy.test:18795", OriginPolicy.Result.PortMismatch)]   // the observed refusal
    [InlineData("https://lens.proxy.test:8443", "https", "lens.proxy.test:8443", OriginPolicy.Result.Match)]
    [InlineData("https://lens.proxy.test:8443", "https", "lens.proxy.test", OriginPolicy.Result.PortMismatch)]
    [InlineData("http://lens.proxy.test", "https", "lens.proxy.test", OriginPolicy.Result.SchemeMismatch)]
    [InlineData("https://lens.proxy.test", "http", "lens.proxy.test", OriginPolicy.Result.SchemeMismatch)]
    [InlineData("https://evil.lens.proxy.test", "https", "lens.proxy.test", OriginPolicy.Result.HostMismatch)]
    [InlineData("https://lens.proxy.test.evil.example", "https", "lens.proxy.test", OriginPolicy.Result.HostMismatch)]
    [InlineData("https://proxy.test", "https", "lens.proxy.test", OriginPolicy.Result.HostMismatch)]
    [InlineData("https://192.168.10.20:18795", "https", "192.168.10.20:18795", OriginPolicy.Result.Match)]
    [InlineData("https://[fd00::5]:18795", "https", "[fd00::5]:18795", OriginPolicy.Result.Match)]
    [InlineData("https://[fd00:0:0::5]:18795", "https", "[FD00::5]:18795", OriginPolicy.Result.Match)]
    [InlineData("https://[fd00::6]:18795", "https", "[fd00::5]:18795", OriginPolicy.Result.HostMismatch)]
    [InlineData("https://[fd00::5]", "https", "[fd00::5]:18795", OriginPolicy.Result.PortMismatch)]
    [InlineData("", "https", "lens.proxy.test", OriginPolicy.Result.Absent)]
    [InlineData("null", "https", "lens.proxy.test", OriginPolicy.Result.Invalid)]
    [InlineData("https://lens.proxy.test/", "https", "lens.proxy.test", OriginPolicy.Result.Invalid)]
    [InlineData("https://lens.proxy.test/login", "https", "lens.proxy.test", OriginPolicy.Result.Invalid)]
    [InlineData("https://user@lens.proxy.test", "https", "lens.proxy.test", OriginPolicy.Result.Invalid)]
    [InlineData("https://lens.proxy.test?x=1", "https", "lens.proxy.test", OriginPolicy.Result.Invalid)]
    [InlineData("ftp://lens.proxy.test", "https", "lens.proxy.test", OriginPolicy.Result.Invalid)]
    public void Origins_are_compared_by_scheme_host_and_port_exactly(string origin, string scheme, string host, OriginPolicy.Result expected) =>
        Assert.Equal(expected, OriginPolicy.Compare(origin, scheme, new HostString(host)));

    [Fact]
    public void Origins_are_described_without_echoing_unparsed_input()
    {
        Assert.Equal("https://lens.proxy.test:443", OriginPolicy.Describe("https://LENS.proxy.test"));
        Assert.Equal("https://[fd00::5]:8443", OriginPolicy.Describe("https://[fd00::5]:8443"));
        Assert.Equal("(invalid, 31 characters)", OriginPolicy.Describe("https://x/secret-token-value-00"));
        Assert.Equal("(none)", OriginPolicy.Describe(null));
    }

    [Fact]
    public void Forwarded_diagnostics_never_echo_unparsed_header_values()
    {
        var request = new DefaultHttpContext().Request;
        request.Headers["X-Forwarded-Host"] = "lens.proxy.test,secret@example.test/path";
        request.Headers["X-Forwarded-Proto"] = "https,secret";
        request.Headers["X-Forwarded-For"] = "198.51.100.7,secret";
        Assert.Equal("host=https://lens.proxy.test:443,(invalid); proto=https,(invalid); for=198.51.100.7,(invalid)", ProxyTrust.DescribeForwarded(request));
    }

    private readonly string _root = Directory.CreateTempSubdirectory("saplens-proxy-config-").FullName;
    private Func<string, string?> Env(params (string Key, string Value)[] values) =>
        key => key == "AUTHLENS_TOKEN" ? new string('t', 40) : values.FirstOrDefault(v => v.Key == key).Value;

    [Fact]
    public void Trusted_proxies_are_opt_in_explicit_and_narrow()
    {
        var none = ServerConfiguration.Parse(["--data-dir", _root], Env());
        Assert.Empty(none.TrustedProxies);
        var settings = ServerConfiguration.Parse(["--data-dir", _root, "--trusted-proxies", "192.168.10.10, 192.168.20.0/24,fd00::10,::ffff:192.168.10.11"], Env());
        Assert.Equal(["192.168.10.10/32", "192.168.20.0/24", "fd00::10/128", "192.168.10.11/32"], settings.TrustedProxies.Select(n => n.ToString()));
        Assert.Equal(1, settings.TrustedProxyHops);
        var fromEnvironment = ServerConfiguration.Parse(["--data-dir", _root], Env(("AUTHLENS_TRUSTED_PROXIES", "192.168.10.10"), ("AUTHLENS_TRUSTED_PROXY_HOPS", "2")));
        Assert.Equal(2, fromEnvironment.TrustedProxyHops);
        Assert.Single(fromEnvironment.TrustedProxies);

        foreach (var bad in new[] { "lens.proxy.test", "192.168.10.10/33", "192.168.10.300", "*" })
            Assert.Throws<InvalidOperationException>(() => ServerConfiguration.Parse(["--data-dir", _root, "--trusted-proxies", bad], Env()));
        foreach (var hops in new[] { "0", "6", "x" })
            Assert.Throws<InvalidOperationException>(() => ServerConfiguration.Parse(["--data-dir", _root, "--trusted-proxies", "192.168.10.10", "--trusted-proxy-hops", hops], Env()));
        Assert.Contains("needs --trusted-proxies", Assert.Throws<InvalidOperationException>(() => ServerConfiguration.Parse(["--data-dir", _root, "--trusted-proxy-hops", "2"], Env())).Message);
    }

    [Theory]
    [InlineData("10.0.0.0/8", "too wide")]
    [InlineData("192.168.0.0/16", "too wide")]
    [InlineData("fd00::/48", "too wide")]
    [InlineData("0.0.0.0/24", "cannot be a trusted proxy")]
    [InlineData("127.0.0.1", "cannot be a trusted proxy")]
    [InlineData("::1", "cannot be a trusted proxy")]
    [InlineData("224.0.0.1", "cannot be a trusted proxy")]
    public void Unbounded_loopback_and_unspecified_proxy_networks_are_refused(string network, string message)
    {
        using var cert = TestCertificates.Create(["lens.proxy.test"], [IPAddress.Parse("192.168.10.5")]);
        var settings = new HostSettings
        {
            DataDirectory = _root, AccessToken = new string('t', 40), ListenAddress = IPAddress.Parse("192.168.10.5"), Port = 18795, NetworkAccess = true,
            Certificate = cert, AllowedHosts = ["lens.proxy.test"], TrustedProxies = [ProxyTrust.ParseNetwork(network)],
        };
        Assert.Contains(message, Assert.Throws<InvalidOperationException>(() => settings.Validate()).Message);
    }

    [Fact]
    public void Trusted_proxies_need_network_access_and_are_refused_on_the_desktop()
    {
        var loopback = new HostSettings { DataDirectory = _root, AccessToken = new string('t', 40), TrustedProxies = [ProxyTrust.ParseNetwork("192.168.10.10")] };
        Assert.Contains("need network access", Assert.Throws<InvalidOperationException>(() => loopback.Validate()).Message);
        var desktop = new HostSettings { DataDirectory = _root, AccessToken = new string('t', 40), Mode = HostMode.Desktop, TrustedProxies = [ProxyTrust.ParseNetwork("192.168.10.10")] };
        Assert.Contains("trusted proxies", Assert.Throws<InvalidOperationException>(() => desktop.Validate()).Message);
    }

    [Fact]
    public void Proxy_hosts_are_explicit_and_do_not_replace_backend_certificate_validation()
    {
        var parsed = ServerConfiguration.Parse(["--data-dir", _root, "--proxy-hosts", "lens.proxy.test"], Env());
        Assert.Equal(["lens.proxy.test"], parsed.ProxyHosts);
        Assert.Equal(["lens.proxy.test"], ServerConfiguration.Parse(["--data-dir", _root], Env(("AUTHLENS_PROXY_HOSTS", "lens.proxy.test"))).ProxyHosts);
        Assert.Contains("need explicit trusted proxies", Assert.Throws<InvalidOperationException>(() => parsed.Validate()).Message);
        using var cert = TestCertificates.Create([], [IPAddress.Parse("192.168.10.5")]);
        HostSettings Settings(string backend, string proxy) => new()
        {
            DataDirectory = _root, AccessToken = new string('t', 40), ListenAddress = IPAddress.Parse("192.168.10.5"), Port = 18795,
            NetworkAccess = true, Certificate = cert, AllowedHosts = [backend], ProxyHosts = [proxy], TrustedProxies = [ProxyTrust.ParseNetwork("192.168.10.10")],
        };
        Settings("192.168.10.5", "lens.proxy.test").Validate(); // public name deliberately absent from backend SAN
        Assert.Contains("subject alternative names", Assert.Throws<InvalidOperationException>(() => Settings("wrong.example", "lens.proxy.test").Validate()).Message);
        foreach (var invalid in new[] { "*", "*.example", "https://lens.proxy.test", "lens.proxy.test:443", "bad host" })
            Assert.Contains("--proxy-hosts", Assert.Throws<InvalidOperationException>(() => Settings("192.168.10.5", invalid).Validate()).Message);
    }
}

/// <summary>Reverse-proxy behaviour through the real pipeline: Kestrel with TLS on this machine's LAN interface, ProxyTrust and ForwardedHeadersMiddleware,
/// the request boundary and the sign-in endpoints. The test client connects from the LAN address, so that address is "the proxy" when trusted.
/// Boundary success is told apart from authentication: a request that passes the boundary reaches the sign-in handler and gets its own answer
/// ("Invalid access token." / "invalid_credentials"), never a boundary title.</summary>
public sealed class ReverseProxyTests : IAsyncDisposable
{
    private const string Public = "lens.proxy.test";             // stands for the public name (lens.example.com in the reported deployment)
    private static readonly IPAddress Ipv6Name = IPAddress.Parse("fd00::5");
    private readonly string _root = Directory.CreateTempSubdirectory("saplens-proxy-").FullName;
    private readonly string _token = HostSettings.NewToken();
    private X509Certificate2 _cert;
    private readonly CollectingLoggerProvider _log = new();
    private readonly IPAddress? _lan = NetworkInterface.GetAllNetworkInterfaces()
        .Where(n => n.OperationalStatus == OperationalStatus.Up && n.NetworkInterfaceType != NetworkInterfaceType.Loopback)
        .SelectMany(n => n.GetIPProperties().UnicastAddresses).Select(a => a.Address)
        .FirstOrDefault(a => a.AddressFamily == AddressFamily.InterNetwork && !IPAddress.IsLoopback(a));
    private readonly int _port;
    private WebApplication? _app;

    public ReverseProxyTests()
    {
        _cert = TestCertificates.Create([Public], _lan is null ? [Ipv6Name] : [_lan, Ipv6Name]);
        using var probe = new TcpListener(IPAddress.Loopback, 0);
        probe.Start();
        _port = ((IPEndPoint)probe.LocalEndpoint).Port;
    }

    public async ValueTask DisposeAsync()
    {
        if (_app is not null) { await _app.StopAsync(); await _app.DisposeAsync(); }
        _cert.Dispose();
        Microsoft.Data.Sqlite.SqliteConnection.ClearAllPools();
        try { Directory.Delete(_root, true); } catch (IOException) { }
    }

    private async Task StartAsync(string[] trusted, int hops = 1, AuthenticationMode auth = AuthenticationMode.SharedToken, bool proxyOnly = false)
    {
        if (proxyOnly) { _cert.Dispose(); _cert = TestCertificates.Create([], [_lan!]); }
        _app = AuthLensHost.Build(new HostSettings
        {
            DataDirectory = Path.Combine(_root, "data"), AccessToken = _token, ListenAddress = _lan!, Port = _port, NetworkAccess = true, Certificate = _cert,
            AllowedHosts = proxyOnly ? [_lan!.ToString()] : [Public, _lan!.ToString(), Ipv6Name.ToString()],
            ProxyHosts = proxyOnly ? [Public] : [], JsonConsoleLogging = false, PermittedNetworkAddress = a => a.Equals(_lan),
            TrustedProxies = [.. trusted.Select(ProxyTrust.ParseNetwork)], TrustedProxyHops = hops, Authentication = auth,
        }, null, b => b.Logging.AddProvider(_log));
        await _app.StartAsync();
    }

    private HttpClient Client() => new(new SocketsHttpHandler
    {
        UseProxy = false, AllowAutoRedirect = false, UseCookies = false,
        SslOptions = new SslClientAuthenticationOptions { RemoteCertificateValidationCallback = (_, c, _, _) => c?.GetCertHashString() == _cert.GetCertHashString() },
    }) { BaseAddress = new Uri($"https://{_lan}:{_port}") };

    private string Internal => $"{_lan}:{_port}";

    /// <summary>The shared-token sign-in form with a wrong token: past the boundary it answers 401 "Invalid access token.".</summary>
    private async Task<(int Status, string Body, HttpResponseMessage Response)> Login(string host, string? origin, IDictionary<string, string>? headers = null, string token = "wrong")
    {
        using var http = Client();
        var request = new HttpRequestMessage(HttpMethod.Post, "/auth/login") { Content = new FormUrlEncodedContent([new("token", token)]) };
        request.Headers.Host = host;
        if (origin is not null) request.Headers.Add("Origin", origin);
        foreach (var (name, value) in headers ?? new Dictionary<string, string>()) request.Headers.TryAddWithoutValidation(name, value);
        var response = await http.SendAsync(request);
        return ((int)response.StatusCode, await response.Content.ReadAsStringAsync(), response);
    }

    private static void PassedBoundary((int Status, string Body, HttpResponseMessage _) r) { Assert.Equal(401, r.Status); Assert.Contains("Invalid access token.", r.Body); }
    private static void Refused((int Status, string Body, HttpResponseMessage _) r, int status, string title) { Assert.Equal(status, r.Status); Assert.Contains(title, r.Body); }

    private static Dictionary<string, string> Forwarded(string host, string proto = "https", string @for = "198.51.100.7") =>
        new() { ["X-Forwarded-Host"] = host, ["X-Forwarded-Proto"] = proto, ["X-Forwarded-For"] = @for };

    [Theory]
    [InlineData(true)]
    [InlineData(false)]
    public async Task Proxy_only_public_host_needs_the_verified_peer_and_keeps_origin_and_csrf_checks(bool trusted)
    {
        if (_lan is null) return;
        await StartAsync([trusted ? _lan.ToString() : "192.0.2.10"], proxyOnly: true);
        PassedBoundary(await Login(Internal, $"https://{Internal}"));
        var publicRequest = await Login(Internal, $"https://{Public}", Forwarded(Public));
        if (trusted) PassedBoundary(publicRequest);
        else Refused(publicRequest, 403, "Cross-origin request refused.");
        var rawPublic = await Login(Public, $"https://{Public}");
        if (trusted) PassedBoundary(rawPublic);
        else Refused(rawPublic, 421, "Unexpected host.");
        Refused(await Login(Internal, "https://evil.example", Forwarded(Public)), 403, "Cross-origin request refused.");
        Refused(await Login(Internal, null, Forwarded(Public)), 403, "State-changing requests need a same-origin signal.");
        if (trusted) Refused(await Login(Internal, $"http://{Public}", Forwarded(Public, "http")), 403, "HTTPS is required.");
    }

    [Fact]
    public async Task Direct_lan_access_without_proxy_configuration_keeps_the_existing_boundary()
    {
        if (_lan is null) return;
        await StartAsync([]);
        PassedBoundary(await Login(Internal, $"https://{Internal}"));                                     // direct HTTPS, matching Host and Origin
        PassedBoundary(await Login(Public, $"https://{Public}"));                                        // public name without port, default 443 origin
        Refused(await Login(Internal, "https://evil.example"), 403, "Cross-origin request refused.");
        Refused(await Login("other.example", "https://other.example"), 421, "Unexpected host.");
        Refused(await Login(Internal, null), 403, "State-changing requests need a same-origin signal."); // missing Origin: CSRF rule kept
        PassedBoundary(await Login(Internal, null, new Dictionary<string, string> { ["Sec-Fetch-Site"] = "same-origin" }));

        // The reported failure, reproduced: Host carries the internal port, Origin is the public origin. Without a trusted proxy this stays refused.
        var observed = await Login($"{Public}:{_port}", $"https://{Public}");
        Refused(observed, 403, "Cross-origin request refused.");
        Assert.Contains("comparison PortMismatch", _log.Text);
        Assert.Contains("trusted proxy False", _log.Text);
        Assert.DoesNotContain("wrong", _log.Text);                                                         // the submitted token is never logged

        // Forwarded headers from an untrusted peer are ignored: neither the spoofed host nor the spoofed scheme is applied.
        Refused(await Login(Internal, $"https://{Public}", Forwarded(Public)), 403, "Cross-origin request refused.");
        PassedBoundary(await Login(Internal, $"https://{Internal}", Forwarded(Public, proto: "http")));
        Assert.Contains("forwarded headers present True applied False", _log.Text);
    }

    [Fact]
    public async Task A_trusted_proxy_establishes_the_public_origin_and_wrong_origins_stay_refused()
    {
        if (_lan is null) return;
        await StartAsync([_lan.ToString()]);
        // The fix for the reported failure: the upstream Host keeps the internal port, the proxy forwards the public host and scheme.
        PassedBoundary(await Login($"{Public}:{_port}", $"https://{Public}", Forwarded(Public)));
        PassedBoundary(await Login(Internal, $"https://{Public}", Forwarded(Public)));                    // upstream Host is the internal IP
        Refused(await Login(Internal, "https://evil.example", Forwarded(Public)), 403, "Cross-origin request refused.");
        Refused(await Login(Internal, $"https://{Public}:{_port}", Forwarded(Public)), 403, "Cross-origin request refused.");   // internal port is not the public origin
        Refused(await Login(Internal, $"http://{Public}", Forwarded(Public)), 403, "Cross-origin request refused.");
        // Explicit external non-default port.
        PassedBoundary(await Login(Internal, $"https://{Public}:8443", Forwarded($"{Public}:8443")));
        Refused(await Login(Internal, $"https://{Public}", Forwarded($"{Public}:8443")), 403, "Cross-origin request refused.");
        // IPv6 public authority.
        PassedBoundary(await Login(Internal, "https://[fd00::5]:8443", Forwarded("[fd00::5]:8443")));
        // A plain-HTTP client behind the proxy is refused, never served with insecure cookies.
        Refused(await Login(Internal, $"http://{Public}", Forwarded(Public, proto: "http")), 403, "HTTPS is required.");
        // A forwarded host outside the allowed hosts is not applied; the request is judged on its own Host.
        Refused(await Login(Internal, "https://evil.example", Forwarded("evil.example")), 403, "Cross-origin request refused.");
        Refused(await Login("other.example", "https://evil.example", Forwarded("evil.example")), 421, "Unexpected host.");
        // Missing Origin keeps the CSRF rule behind the proxy too.
        Refused(await Login(Internal, null, Forwarded(Public)), 403, "State-changing requests need a same-origin signal.");
        // Malformed forwarding values are ignored safely (no 500, nothing applied).
        var malformed = await Login(Internal, $"https://{Public}", new Dictionary<string, string> { ["X-Forwarded-Host"] = Public, ["X-Forwarded-Proto"] = "https", ["X-Forwarded-For"] = "not-an-address" });
        Assert.True(malformed.Status is 401 or 403, $"{malformed.Status} {malformed.Body}");
        Refused(await Login(Internal, $"https://{Public}", new Dictionary<string, string> { ["X-Forwarded-Host"] = "lens proxy test", ["X-Forwarded-Proto"] = "https" }), 403, "Cross-origin request refused.");
        Assert.Contains("trusted proxy True", _log.Text);
    }

    [Fact]
    public async Task Proxy_hops_are_walked_only_through_trusted_addresses()
    {
        if (_lan is null) return;
        await StartAsync([_lan.ToString()], hops: 2);
        // The second hop (198.51.100.7) is not trusted, so the client address stops there; the earlier, client-supplied entry is never used.
        Refused(await Login(Internal, "https://evil.example", Forwarded(Public, @for: "203.0.113.9, 198.51.100.7")), 403, "Cross-origin request refused.");
        Assert.Contains("client 198.51.100.7", _log.Text);
        Assert.DoesNotContain("client 203.0.113.9", _log.Text);
        await _app!.StopAsync(); await _app.DisposeAsync(); _app = null;

        await StartAsync([_lan.ToString(), "198.51.100.7"], hops: 2);
        Refused(await Login(Internal, "https://evil.example", Forwarded(Public, @for: "203.0.113.9, 198.51.100.7")), 403, "Cross-origin request refused.");
        Assert.Contains("client 203.0.113.9", _log.Text);
    }

    [Fact]
    public async Task Sign_in_works_through_a_trusted_proxy_with_secure_cookies()
    {
        if (_lan is null) return;
        await StartAsync([_lan.ToString()]);
        var signedIn = await Login(Internal, $"https://{Public}", Forwarded(Public), token: _token);
        Assert.Equal(302, signedIn.Status);
        var cookie = Assert.Single(signedIn.Response.Headers.GetValues("Set-Cookie"));
        Assert.StartsWith(SessionStore.SecureCookieName + "=", cookie);
        Assert.Contains("secure", cookie, StringComparison.OrdinalIgnoreCase);
        Assert.Contains("samesite=strict", cookie, StringComparison.OrdinalIgnoreCase);
        Assert.Equal("max-age=31536000", signedIn.Response.Headers.GetValues("Strict-Transport-Security").Single());

        using var http = Client();
        var session = new HttpRequestMessage(HttpMethod.Get, "/api/v1/session");
        session.Headers.Host = Internal;
        foreach (var (name, value) in Forwarded(Public)) session.Headers.TryAddWithoutValidation(name, value);
        session.Headers.Add("Cookie", cookie.Split(';')[0]);
        var response = await http.SendAsync(session);
        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        Assert.Contains("\"authentication\":\"session\"", await response.Content.ReadAsStringAsync());
        Assert.True(response.Headers.Contains(RequestBoundary.CorrelationHeader));
    }

    [Fact]
    public async Task Accounts_sign_in_through_a_trusted_proxy_reaches_authentication()
    {
        if (_lan is null) return;
        await StartAsync([_lan.ToString()], auth: AuthenticationMode.Accounts);
        using var http = Client();
        async Task<(int, string)> Post(string origin)
        {
            var request = new HttpRequestMessage(HttpMethod.Post, "/api/auth/login") { Content = new StringContent("{\"username\":\"nobody\",\"password\":\"not-the-password\"}", Encoding.UTF8, "application/json") };
            request.Headers.Host = $"{Public}:{_port}";
            request.Headers.Add("Origin", origin);
            foreach (var (name, value) in Forwarded(Public)) request.Headers.TryAddWithoutValidation(name, value);
            var response = await http.SendAsync(request);
            return ((int)response.StatusCode, await response.Content.ReadAsStringAsync());
        }
        var (status, body) = await Post($"https://{Public}");
        Assert.DoesNotContain("Cross-origin", body);                    // past the boundary: the account store answered, the sign-in itself failed
        Assert.DoesNotContain("same-origin signal", body);
        Assert.True(status is 401 or 403 or 409, $"{status} {body}");
        Assert.Contains("\"code\"", body);
        var (refused, refusal) = await Post("https://evil.example");
        Assert.Equal(403, refused);
        Assert.Contains("Cross-origin request refused.", refusal);
        Assert.DoesNotContain("not-the-password", _log.Text);
    }
}
