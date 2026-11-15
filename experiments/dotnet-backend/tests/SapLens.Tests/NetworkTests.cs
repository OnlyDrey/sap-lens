using System.Net;
using System.Net.NetworkInformation;
using System.Net.Security;
using System.Net.Sockets;
using System.Security.Cryptography;
using System.Security.Cryptography.X509Certificates;
using System.Text;
using System.Text.Json;
using Microsoft.AspNetCore.Builder;
using SapLens.Api;

namespace SapLens.Tests;

public static class TestCertificates
{
    public static X509Certificate2 Create(string[] dns, IPAddress[] ips, DateTimeOffset? from = null, DateTimeOffset? to = null, string eku = "1.3.6.1.5.5.7.3.1", int keySize = 2048)
    {
        using var rsa = RSA.Create(keySize);
        var request = new CertificateRequest("CN=SAP Lens 2 test", rsa, HashAlgorithmName.SHA256, RSASignaturePadding.Pkcs1);
        var san = new SubjectAlternativeNameBuilder();
        foreach (var name in dns) san.AddDnsName(name);
        foreach (var ip in ips) san.AddIpAddress(ip);
        request.CertificateExtensions.Add(san.Build());
        request.CertificateExtensions.Add(new X509EnhancedKeyUsageExtension([new Oid(eku)], false));
        return request.CreateSelfSigned(from ?? DateTimeOffset.UtcNow.AddDays(-1), to ?? DateTimeOffset.UtcNow.AddDays(365));
    }
}

/// <summary>Network exposure policy: loopback by default, LAN only when explicitly enabled with HTTPS, a valid certificate, one private address and
/// explicit host names; Desktop never; configuration fails closed.</summary>
public sealed class NetworkPolicyTests : IDisposable
{
    private readonly string _root = Directory.CreateTempSubdirectory("saplens-net-").FullName;
    private readonly string _token = HostSettings.NewToken();
    public void Dispose() { try { Directory.Delete(_root, true); } catch (IOException) { } }

    private Func<string, string?> Env(params (string Key, string Value)[] values) => key => key == "SAP_LENS_V2_TOKEN" ? _token : values.FirstOrDefault(v => v.Key == key).Value;

    [Fact]
    public void Default_configuration_is_loopback_http_without_network_access()
    {
        var settings = ServerConfiguration.Parse(["--data-dir", _root], Env());
        Assert.Equal(IPAddress.Loopback, settings.ListenAddress);
        Assert.Equal(18790, settings.Port);
        Assert.False(settings.NetworkAccess);
        Assert.False(settings.Https);
        settings.Validate();
    }

    [Theory]
    [InlineData("--listen", "server.lan")]
    [InlineData("--port", "70000")]
    [InlineData("--bind", "0.0.0.0")]
    [InlineData("--cert-password", "secret")]
    [InlineData("--token", "x")]
    public void Invalid_or_secret_bearing_options_are_refused(string option, string value) =>
        Assert.Throws<InvalidOperationException>(() => ServerConfiguration.Parse(["--data-dir", _root, option, value], Env()));

    [Fact]
    public void Environment_configures_the_same_settings_as_options()
    {
        var settings = ServerConfiguration.Parse([], Env(("SAP_LENS_V2_DATA_DIR", _root), ("SAP_LENS_V2_LISTEN", "192.168.10.5"), ("SAP_LENS_V2_PORT", "18791"),
            ("SAP_LENS_V2_NETWORK", "true"), ("SAP_LENS_V2_ALLOWED_HOSTS", "saplens.corp.example, 192.168.10.5")));
        Assert.Equal(IPAddress.Parse("192.168.10.5"), settings.ListenAddress);
        Assert.True(settings.NetworkAccess);
        Assert.Equal(["saplens.corp.example", "192.168.10.5"], settings.AllowedHosts);
        Assert.Contains("HTTPS", Assert.Throws<InvalidOperationException>(() => settings.Validate()).Message); // no certificate configured
    }

    private HostSettings Network(string address, X509Certificate2? cert, params string[] hosts) => new()
    {
        DataDirectory = _root, AccessToken = _token, ListenAddress = IPAddress.Parse(address), Port = 18791, NetworkAccess = true, Certificate = cert, AllowedHosts = hosts,
    };

    [Theory]
    [InlineData("0.0.0.0", "all interfaces")]
    [InlineData("::", "all interfaces")]
    [InlineData("8.8.8.8", "not a private LAN address")]
    [InlineData("192.0.2.2", "not a private LAN address")]
    [InlineData("127.0.0.1", "not loopback")]
    public void Network_access_refuses_wildcard_public_and_loopback_addresses(string address, string message)
    {
        using var cert = TestCertificates.Create(["saplens.corp.example"], [IPAddress.Parse("192.168.10.5")]);
        Assert.Contains(message, Assert.Throws<InvalidOperationException>(() => Network(address, cert, "saplens.corp.example").Validate()).Message);
    }

    [Fact]
    public void Lan_binding_without_explicit_network_access_or_without_https_or_hosts_is_refused()
    {
        using var cert = TestCertificates.Create(["saplens.corp.example"], [IPAddress.Parse("192.168.10.5")]);
        var noNetwork = new HostSettings { DataDirectory = _root, AccessToken = _token, ListenAddress = IPAddress.Parse("192.168.10.5"), Certificate = cert };
        Assert.Contains("--network", Assert.Throws<InvalidOperationException>(() => noNetwork.Validate()).Message);
        Assert.Contains("HTTPS", Assert.Throws<InvalidOperationException>(() => Network("192.168.10.5", null, "saplens.corp.example").Validate()).Message);
        Assert.Contains("--allowed-hosts", Assert.Throws<InvalidOperationException>(() => Network("192.168.10.5", cert).Validate()).Message);
        Assert.Throws<InvalidOperationException>(() => Network("192.168.10.5", cert, "*.corp.example").Validate());
        Network("192.168.10.5", cert, "saplens.corp.example", "192.168.10.5").Validate(); // the valid combination
    }

    [Fact]
    public void Desktop_is_loopback_only_whatever_is_configured()
    {
        using var cert = TestCertificates.Create(["localhost"], [IPAddress.Loopback]);
        HostSettings Desktop(IPAddress address, bool network = false, X509Certificate2? c = null, string[]? hosts = null) => new()
        {
            DataDirectory = _root, AccessToken = _token, Mode = HostMode.Desktop, ListenAddress = address, Port = 0, NetworkAccess = network, Certificate = c, AllowedHosts = hosts ?? [],
            PermittedNetworkAddress = _ => true,
        };
        Desktop(IPAddress.Loopback).Validate();
        Assert.Throws<InvalidOperationException>(() => Desktop(IPAddress.Parse("192.168.10.5")).Validate());
        Assert.Throws<InvalidOperationException>(() => Desktop(IPAddress.Loopback, network: true).Validate());
        Assert.Throws<InvalidOperationException>(() => Desktop(IPAddress.Loopback, c: cert).Validate());
        Assert.Throws<InvalidOperationException>(() => Desktop(IPAddress.Loopback, hosts: ["saplens.corp.example"]).Validate());
        Assert.False(Desktop(IPAddress.Loopback).HostAllowed("saplens.corp.example"));
    }

    [Fact]
    public void Certificate_validation_rejects_unusable_certificates()
    {
        var ip = IPAddress.Parse("192.168.10.5");
        string[] hosts = ["saplens.corp.example", "192.168.10.5"];
        IReadOnlyList<string> Problems(X509Certificate2 c) => CertificatePolicy.Validate(c, hosts, DateTimeOffset.UtcNow).Problems;
        using var good = TestCertificates.Create(["saplens.corp.example"], [ip]);
        Assert.Empty(Problems(good));
        using var wildcard = TestCertificates.Create(["*.corp.example"], [ip]);
        Assert.Empty(Problems(wildcard));
        using var expired = TestCertificates.Create(["saplens.corp.example"], [ip], DateTimeOffset.UtcNow.AddDays(-30), DateTimeOffset.UtcNow.AddDays(-1));
        Assert.Contains(Problems(expired), p => p.Contains("expired"));
        using var future = TestCertificates.Create(["saplens.corp.example"], [ip], DateTimeOffset.UtcNow.AddDays(2), DateTimeOffset.UtcNow.AddDays(30));
        Assert.Contains(Problems(future), p => p.Contains("not valid before"));
        using var client = TestCertificates.Create(["saplens.corp.example"], [ip], eku: "1.3.6.1.5.5.7.3.2");
        Assert.Contains(Problems(client), p => p.Contains("server authentication"));
        using var otherName = TestCertificates.Create(["other.corp.example"], []);
        Assert.Equal(2, Problems(otherName).Count(p => p.Contains("subject alternative names")));
        using var weak = TestCertificates.Create(["saplens.corp.example"], [ip], keySize: 1024);
        Assert.Contains(Problems(weak), p => p.Contains("2048"));
        using var publicOnly = X509CertificateLoader.LoadCertificate(good.Export(X509ContentType.Cert));
        Assert.Contains(Problems(publicOnly), p => p.Contains("private key"));
        using var soon = TestCertificates.Create(["saplens.corp.example"], [ip], to: DateTimeOffset.UtcNow.AddDays(10));
        Assert.Single(CertificatePolicy.Validate(soon, hosts, DateTimeOffset.UtcNow).Warnings);
        Assert.Contains("expired", Assert.Throws<InvalidOperationException>(() => Network("192.168.10.5", expired, hosts).Validate()).Message);
    }

    [Fact]
    public void Pfx_and_pem_certificates_load_and_a_wrong_password_never_appears_in_the_message()
    {
        using var cert = TestCertificates.Create(["saplens.corp.example"], [IPAddress.Parse("192.168.10.5")]);
        var pfx = Path.Combine(_root, "server.pfx");
        File.WriteAllBytes(pfx, cert.Export(X509ContentType.Pkcs12, "correct horse battery"));
        using (var loaded = CertificatePolicy.Load(pfx, null, "correct horse battery")) Assert.True(loaded.HasPrivateKey);
        var error = Assert.Throws<InvalidOperationException>(() => CertificatePolicy.Load(pfx, null, "wrong-password-value"));
        Assert.DoesNotContain("wrong-password-value", error.Message);

        var pem = Path.Combine(_root, "server.crt");
        var key = Path.Combine(_root, "server.key");
        File.WriteAllText(pem, cert.ExportCertificatePem());
        File.WriteAllText(key, cert.GetRSAPrivateKey()!.ExportPkcs8PrivateKeyPem());
        using (var loaded = CertificatePolicy.Load(pem, key, null)) Assert.True(loaded.HasPrivateKey);
        Assert.Contains("does not exist", Assert.Throws<InvalidOperationException>(() => CertificatePolicy.Load(Path.Combine(_root, "missing.pfx"), null, null)).Message);

        var passwordFile = Path.Combine(_root, "cert-password");
        File.WriteAllText(passwordFile, "correct horse battery\n");
        var settings = ServerConfiguration.Parse(["--data-dir", _root, "--cert", pfx, "--cert-password-file", passwordFile], Env());
        Assert.True(settings.Https);
    }
}

/// <summary>A real HTTPS listener on this machine's non-loopback interface. The container's only interface is in a documentation range, which the
/// product policy correctly refuses; this test alone widens PermittedNetworkAddress to that one address (an internal hook, not an option).</summary>
public sealed class LanHttpsTests : IAsyncDisposable
{
    private readonly string _root = Directory.CreateTempSubdirectory("saplens-lan-").FullName;
    private readonly string _token = HostSettings.NewToken();
    private const string HostName = "saplens.lan.test";
    private readonly X509Certificate2 _cert;
    private readonly IPAddress? _lan = NetworkInterface.GetAllNetworkInterfaces()
        .Where(n => n.OperationalStatus == OperationalStatus.Up && n.NetworkInterfaceType != NetworkInterfaceType.Loopback)
        .SelectMany(n => n.GetIPProperties().UnicastAddresses).Select(a => a.Address)
        .FirstOrDefault(a => a.AddressFamily == AddressFamily.InterNetwork && !IPAddress.IsLoopback(a));
    private readonly int _port;

    public LanHttpsTests()
    {
        _cert = TestCertificates.Create([HostName], _lan is null ? [] : [_lan]);
        using var probe = new TcpListener(IPAddress.Loopback, 0);
        probe.Start();
        _port = ((IPEndPoint)probe.LocalEndpoint).Port;
    }

    public ValueTask DisposeAsync()
    {
        _cert.Dispose();
        Microsoft.Data.Sqlite.SqliteConnection.ClearAllPools();
        try { Directory.Delete(_root, true); } catch (IOException) { }
        return ValueTask.CompletedTask;
    }

    private async Task<WebApplication> StartAsync()
    {
        var app = SapLensHost.Build(new HostSettings
        {
            DataDirectory = Path.Combine(_root, "data"), AccessToken = _token, ListenAddress = _lan!, Port = _port, NetworkAccess = true, Certificate = _cert,
            AllowedHosts = [HostName, _lan!.ToString()], JsonConsoleLogging = false, PermittedNetworkAddress = a => a.Equals(_lan),
        });
        await app.StartAsync();
        return app;
    }

    /// <summary>Trusts exactly this certificate (pinned thumbprint), the way a LAN client trusts the internal CA. Validation is never switched off.</summary>
    private HttpClient Client(bool cookies = false) => new(new SocketsHttpHandler
    {
        UseProxy = false, AllowAutoRedirect = false, UseCookies = cookies,
        SslOptions = new SslClientAuthenticationOptions { RemoteCertificateValidationCallback = (_, c, _, _) => c?.GetCertHashString() == _cert.GetCertHashString() },
    }) { BaseAddress = new Uri($"https://{_lan}:{_port}") };

    [Fact]
    public async Task Lan_https_serves_ui_enforces_token_hosts_cookies_csrf_and_persists_across_restart()
    {
        if (_lan is null) return; // no non-loopback interface on this machine
        Console.WriteLine($"LAN-HTTPS-TEST bound {_lan}:{_port}");
        var app = await StartAsync();
        try
        {
            using var http = Client();
            var page = await http.GetAsync("/");
            Assert.Equal(HttpStatusCode.OK, page.StatusCode);
            Assert.Equal("max-age=31536000", page.Headers.GetValues("Strict-Transport-Security").Single());
            Assert.Equal(HttpStatusCode.Unauthorized, (await http.GetAsync("/api/v1/roles")).StatusCode);

            using (var named = new HttpRequestMessage(HttpMethod.Get, "/")) { named.Headers.Host = $"{HostName}:{_port}"; Assert.Equal(HttpStatusCode.OK, (await http.SendAsync(named)).StatusCode); }
            using (var foreign = new HttpRequestMessage(HttpMethod.Get, "/")) { foreign.Headers.Host = "attacker.example"; Assert.Equal((HttpStatusCode)421, (await http.SendAsync(foreign)).StatusCode); }

            // Plain HTTP on the HTTPS port never yields a page; the loopback interface is not bound at all.
            using (var plain = new HttpClient(new SocketsHttpHandler { UseProxy = false }) { Timeout = TimeSpan.FromSeconds(5) })
            {
                var plainOk = false;
                try { plainOk = (await plain.GetAsync($"http://{_lan}:{_port}/")).IsSuccessStatusCode; } catch (HttpRequestException) { } catch (TaskCanceledException) { }
                Assert.False(plainOk);
                await Assert.ThrowsAsync<HttpRequestException>(() => plain.GetAsync($"http://127.0.0.1:{_port}/"));
            }

            // Sign-in over HTTPS: __Host- cookie, Secure, HttpOnly, SameSite=Strict, no token inside.
            var origin = $"https://{_lan}:{_port}";
            using var login = new HttpRequestMessage(HttpMethod.Post, "/auth/login") { Content = new FormUrlEncodedContent([new KeyValuePair<string, string>("token", _token)]) };
            login.Headers.Add("Origin", origin);
            var signedIn = await http.SendAsync(login);
            Assert.Equal(HttpStatusCode.Redirect, signedIn.StatusCode);
            var cookie = signedIn.Headers.GetValues("Set-Cookie").Single();
            Assert.StartsWith(SessionStore.SecureCookieName + "=", cookie);
            foreach (var attribute in new[] { "secure", "httponly", "samesite=strict", "path=/" }) Assert.Contains(attribute, cookie, StringComparison.OrdinalIgnoreCase);
            Assert.DoesNotContain("domain=", cookie, StringComparison.OrdinalIgnoreCase);
            Assert.DoesNotContain(_token, cookie);
            var pair = cookie.Split(';')[0];

            async Task<HttpStatusCode> CookiePost(string? requestOrigin, string? fetchSite)
            {
                using var request = new HttpRequestMessage(HttpMethod.Post, "/api/v1/admin/backups");
                request.Headers.Add("Cookie", pair);
                if (requestOrigin is not null) request.Headers.Add("Origin", requestOrigin);
                if (fetchSite is not null) request.Headers.Add("Sec-Fetch-Site", fetchSite);
                return (await http.SendAsync(request)).StatusCode;
            }
            Assert.Equal(HttpStatusCode.Forbidden, await CookiePost(null, null));
            Assert.Equal(HttpStatusCode.Forbidden, await CookiePost("https://evil.example", null));
            Assert.Equal(HttpStatusCode.Forbidden, await CookiePost(null, "cross-site"));
            Assert.Equal(HttpStatusCode.OK, await CookiePost(origin, null));
            using (var plainCookie = new HttpRequestMessage(HttpMethod.Get, "/api/v1/session"))
            {
                plainCookie.Headers.Add("Cookie", SessionStore.CookieName + "=" + pair.Split('=', 2)[1]); // the non-__Host name is not accepted over HTTPS
                Assert.Equal(HttpStatusCode.Unauthorized, (await http.SendAsync(plainCookie)).StatusCode);
            }

            // Data written over the LAN endpoint survives a restart.
            using var upload = new HttpRequestMessage(HttpMethod.Post, "/api/v1/imports/roles") { Content = new StringContent(Csv.Roles(40), Encoding.UTF8, "text/csv") };
            upload.Headers.Add(RequestBoundary.TokenHeader, _token);
            var job = JsonDocument.Parse(await (await http.SendAsync(upload)).Content.ReadAsStringAsync()).RootElement.GetProperty("id").GetInt64();
            for (var i = 0; i < 100; i++)
            {
                using var poll = new HttpRequestMessage(HttpMethod.Get, $"/api/v1/jobs/{job}");
                poll.Headers.Add(RequestBoundary.TokenHeader, _token);
                if (JsonDocument.Parse(await (await http.SendAsync(poll)).Content.ReadAsStringAsync()).RootElement.GetProperty("status").GetString() == "Completed") break;
                await Task.Delay(50);
            }
        }
        finally
        {
            await LocalStartup.StopQuietlyAsync(app);
        }

        app = await StartAsync();
        try
        {
            using var http = Client();
            using var roles = new HttpRequestMessage(HttpMethod.Get, "/api/v1/roles?limit=1");
            roles.Headers.Add(RequestBoundary.TokenHeader, _token);
            var page = JsonDocument.Parse(await (await http.SendAsync(roles)).Content.ReadAsStringAsync()).RootElement;
            Assert.Equal(40, page.GetProperty("total").GetInt32());
            using var session = new HttpRequestMessage(HttpMethod.Get, "/api/v1/session");
            session.Headers.Add("Cookie", SessionStore.SecureCookieName + "=stale");
            Assert.Equal(HttpStatusCode.Unauthorized, (await http.SendAsync(session)).StatusCode); // sessions do not survive a restart
        }
        finally
        {
            await LocalStartup.StopQuietlyAsync(app);
        }
    }
}
