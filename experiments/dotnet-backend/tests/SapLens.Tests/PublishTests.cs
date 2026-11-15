using System.Diagnostics;
using System.Net;
using System.Net.Sockets;
using System.Security.Cryptography.X509Certificates;
using System.Text;
using SapLens.Api;

namespace SapLens.Tests;

[CollectionDefinition("publish", DisableParallelization = true)]
public sealed class PublishCollection : ICollectionFixture<PublishFixture>;

/// <summary>Publishes each (project, runtime) once per test run into one isolated temporary directory.</summary>
public sealed class PublishFixture : IDisposable
{
    public string Root { get; } = Directory.CreateTempSubdirectory("saplens-publish-").FullName;
    private readonly Dictionary<string, string> _outputs = new();

    public string Get(string project, string rid)
    {
        lock (_outputs)
        {
            if (!_outputs.TryGetValue(project + rid, out var output)) _outputs[project + rid] = output = PublishTests.Publish(Root, project, rid);
            return output;
        }
    }

    public void Dispose()
    {
        try { Directory.Delete(Root, true); } catch (IOException) { } catch (UnauthorizedAccessException) { }
    }
}

/// <summary>Publish acceptance: real `dotnet publish` into an isolated temporary directory (own artifacts path, outside the repository), then the
/// published Server is run from a different working directory and must serve the UI entry point, its JavaScript and CSS, and still enforce the token.
/// Windows packages are cross-published and inspected (they cannot run here). Slow: filter with `--filter Category!=Publish` during development.</summary>
[Collection("publish")]
[Trait("Category", "Publish")]
public sealed class PublishTests(PublishFixture fixture) : IDisposable
{
    private readonly string _root = Directory.CreateTempSubdirectory("saplens-publish-run-").FullName;

    public void Dispose()
    {
        try { Directory.Delete(_root, true); } catch (IOException) { } catch (UnauthorizedAccessException) { }
    }

    private string Publish(string project, string rid) => fixture.Get(project, rid);

    private static string RepoProject(string name)
    {
        var dir = new DirectoryInfo(AppContext.BaseDirectory);
        while (dir is not null && !File.Exists(Path.Combine(dir.FullName, "SapLens.slnx"))) dir = dir.Parent;
        return Path.Combine(dir!.FullName, "src", name, name + ".csproj");
    }

    internal static string Publish(string root, string project, string rid)
    {
        var output = Path.Combine(root, $"{project}-{rid}");
        var info = new ProcessStartInfo("dotnet") { RedirectStandardOutput = true, RedirectStandardError = true, UseShellExecute = false, WorkingDirectory = root };
        foreach (var arg in new[] { "publish", RepoProject(project), "-c", "Release", "-r", rid, "--self-contained", "true", "-o", output,
                     "--artifacts-path", Path.Combine(root, "artifacts-" + project + "-" + rid), "-nologo",
                     // No long-lived MSBuild nodes or compiler server: they would inherit the redirected pipes and keep them open after publish exits.
                     "-nodeReuse:false", "-p:UseSharedCompilation=false" })
            info.ArgumentList.Add(arg);
        info.Environment["MSBUILDDISABLENODEREUSE"] = "1";
        info.Environment["DOTNET_CLI_TELEMETRY_OPTOUT"] = "1";
        using var process = Process.Start(info)!;
        var stdout = process.StandardOutput.ReadToEndAsync();
        var stderr = process.StandardError.ReadToEndAsync();
        Assert.True(process.WaitForExit(TimeSpan.FromMinutes(10)), "publish timed out");
        var log = (stdout.Wait(TimeSpan.FromSeconds(30)) ? stdout.Result : "") + (stderr.Wait(TimeSpan.FromSeconds(30)) ? stderr.Result : "");
        Assert.True(process.ExitCode == 0, log);
        return output;
    }

    private static bool Contains(string file, string text)
    {
        var needle = Encoding.UTF8.GetBytes(text);
        return File.ReadAllBytes(file).AsSpan().IndexOf(needle) >= 0;
    }

    private static int FreePort()
    {
        using var listener = new TcpListener(IPAddress.Loopback, 0);
        listener.Start();
        return ((IPEndPoint)listener.LocalEndpoint).Port;
    }

    [Fact]
    public async Task Published_linux_server_runs_outside_the_repository_from_another_working_directory()
    {
        if (!OperatingSystem.IsLinux()) return; // the Windows counterpart is the documented manual run
        var output = Publish("SapLens.Api", "linux-x64");
        Assert.False(Directory.Exists(Path.Combine(output, "wwwroot")), "the UI must be embedded, not loose files");
        Assert.True(Contains(Path.Combine(output, "SapLens.Api.dll"), UiAssets.Marker));
        Assert.True(Contains(Path.Combine(output, "SapLens.Api.dll"), "SapLens.Api.wwwroot.assets.")); // the React build output

        var elsewhere = Directory.CreateDirectory(Path.Combine(_root, "unrelated-cwd")).FullName;
        var token = HostSettings.NewToken();
        var port = FreePort();
        var info = new ProcessStartInfo(Path.Combine(output, "SapLens.Api")) { WorkingDirectory = elsewhere, UseShellExecute = false, RedirectStandardOutput = true, RedirectStandardError = true };
        foreach (var arg in new[] { "--data-dir", Path.Combine(_root, "data"), "--port", port.ToString() }) info.ArgumentList.Add(arg);
        info.Environment["SAP_LENS_V2_TOKEN"] = token;
        info.Environment.Remove("DOTNET_ROOT"); // self-contained: must not need an installed runtime
        using var server = Process.Start(info)!;
        _ = server.StandardOutput.ReadToEndAsync();
        _ = server.StandardError.ReadToEndAsync();
        try
        {
            using var http = new HttpClient(new HttpClientHandler { UseProxy = false }) { BaseAddress = new Uri($"http://127.0.0.1:{port}") };
            var probe = await StartupProbe.WaitAsync(http.BaseAddress, TimeSpan.FromSeconds(30), token: token); // "/" served the React application
            Assert.True(probe.Ok, probe.Problem);
            foreach (var (path, type) in new[] { ("/theme.js", "text/javascript"), ("/sap-lens.png", "image/png"), ("/login.html", "text/html"), ("/login.css", "text/css") })
            {
                var response = await http.GetAsync(path);
                Assert.Equal(HttpStatusCode.OK, response.StatusCode);
                Assert.Equal(type, response.Content.Headers.ContentType!.MediaType);
            }
            Assert.Equal(HttpStatusCode.Unauthorized, (await http.GetAsync("/api/v1/roles")).StatusCode);
            using var authorized = new HttpRequestMessage(HttpMethod.Get, "/api/v1/roles");
            authorized.Headers.Add(RequestBoundary.TokenHeader, token);
            Assert.Equal(HttpStatusCode.OK, (await http.SendAsync(authorized)).StatusCode);
            Assert.True(File.Exists(Path.Combine(_root, "data", "sap-lens-v2.sqlite3")));
            Assert.Empty(Directory.GetFiles(elsewhere, "*", SearchOption.AllDirectories)); // nothing written to the working directory
        }
        finally
        {
            server.Kill(entireProcessTree: true);
            server.WaitForExit(10000);
        }
    }

    [Fact]
    public void Published_windows_server_contains_the_embedded_ui()
    {
        var output = Publish("SapLens.Api", "win-x64");
        Assert.True(File.Exists(Path.Combine(output, "SapLens.Api.exe")));
        Assert.False(Directory.Exists(Path.Combine(output, "wwwroot")));
        Assert.True(Contains(Path.Combine(output, "SapLens.Api.dll"), UiAssets.Marker));
        Assert.True(Contains(Path.Combine(output, "SapLens.Api.dll"), "Microsoft.Extensions.FileProviders.Embedded.Manifest.xml"));
        Assert.True(Contains(Path.Combine(output, "SapLens.Api.dll"), "SapLens.Api.wwwroot.assets.")); // the React build output
        Assert.True(File.Exists(Path.Combine(output, "Microsoft.Extensions.Hosting.WindowsServices.dll"))); // runs as a Windows service
    }

    private async Task<(int? ExitCode, string Error)> RunServer(string output, string[] args, Func<HttpClient, Task>? whileRunning = null, Func<HttpMessageHandler>? handler = null, Uri? baseAddress = null)
    {
        var info = new ProcessStartInfo(Path.Combine(output, "SapLens.Api")) { WorkingDirectory = Directory.CreateDirectory(Path.Combine(_root, "cwd-" + Guid.NewGuid().ToString("N"))).FullName,
            UseShellExecute = false, RedirectStandardOutput = true, RedirectStandardError = true };
        foreach (var arg in args) info.ArgumentList.Add(arg);
        info.Environment["SAP_LENS_V2_TOKEN"] = HostSettings.NewToken();
        using var server = Process.Start(info)!;
        _ = server.StandardOutput.ReadToEndAsync();
        var error = server.StandardError.ReadToEndAsync();
        if (whileRunning is null)
        {
            Assert.True(server.WaitForExit(30000), "the server did not refuse the configuration");
            return (server.ExitCode, error.Wait(5000) ? error.Result : "");
        }
        try
        {
            using var http = new HttpClient(handler!()) { BaseAddress = baseAddress, Timeout = TimeSpan.FromSeconds(5) };
            await whileRunning(http);
            return (null, "");
        }
        finally
        {
            server.Kill(entireProcessTree: true);
            server.WaitForExit(10000);
        }
    }

    [Fact]
    public async Task Published_linux_server_refuses_insecure_network_configurations_and_serves_https_from_a_pem_certificate()
    {
        if (!OperatingSystem.IsLinux()) return;
        var output = Publish("SapLens.Api", "linux-x64");
        var data = Path.Combine(_root, "data-tls");
        foreach (var (args, message) in new[]
                 {
                     (new[] { "--data-dir", data, "--listen", "0.0.0.0" }, "--network"),
                     (new[] { "--data-dir", data, "--network", "--listen", "0.0.0.0", "--allowed-hosts", "x" }, "all interfaces"),
                     (new[] { "--data-dir", data, "--network", "--listen", "192.168.10.5", "--allowed-hosts", "saplens.corp.example" }, "HTTPS"),
                     (new[] { "--data-dir", data, "--network", "--listen", "8.8.8.8", "--allowed-hosts", "x" }, "not a private LAN address"),
                     (new[] { "--data-dir", data, "--cert-password", "x" }, "not accepted on the command line"),
                 })
        {
            var (code, error) = await RunServer(output, args);
            Assert.Equal(3, code);
            Assert.Contains(message, error);
        }

        using var cert = TestCertificates.Create(["localhost"], [IPAddress.Loopback]);
        var pem = Path.Combine(_root, "server.crt");
        var key = Path.Combine(_root, "server.key");
        await File.WriteAllTextAsync(pem, cert.ExportCertificatePem());
        await File.WriteAllTextAsync(key, cert.GetRSAPrivateKey()!.ExportPkcs8PrivateKeyPem());
        var expired = TestCertificates.Create(["localhost"], [IPAddress.Loopback], DateTimeOffset.UtcNow.AddDays(-10), DateTimeOffset.UtcNow.AddDays(-1));
        var expiredPem = Path.Combine(_root, "expired.crt");
        var expiredKey = Path.Combine(_root, "expired.key");
        await File.WriteAllTextAsync(expiredPem, expired.ExportCertificatePem());
        await File.WriteAllTextAsync(expiredKey, expired.GetRSAPrivateKey()!.ExportPkcs8PrivateKeyPem());
        var (expiredCode, expiredError) = await RunServer(output, ["--data-dir", data, "--port", FreePort().ToString(), "--cert", expiredPem, "--cert-key", expiredKey]);
        Assert.Equal(3, expiredCode);
        Assert.Contains("expired", expiredError);

        var port = FreePort();
        await RunServer(output, ["--data-dir", data, "--port", port.ToString(), "--cert", pem, "--cert-key", key], async http =>
        {
            HttpResponseMessage? page = null;
            for (var i = 0; i < 100 && page is null; i++)
            {
                try { page = await http.GetAsync("/"); } catch (HttpRequestException) { await Task.Delay(100); }
            }
            Assert.NotNull(page);
            Assert.Equal(HttpStatusCode.OK, page!.StatusCode);
            Assert.True(page.Headers.Contains("Strict-Transport-Security"));
            Assert.Equal(HttpStatusCode.Unauthorized, (await http.GetAsync("/api/v1/roles")).StatusCode);
        }, () => new SocketsHttpHandler
        {
            UseProxy = false,
            SslOptions = new System.Net.Security.SslClientAuthenticationOptions { RemoteCertificateValidationCallback = (_, c, _, _) => c?.GetCertHashString() == cert.GetCertHashString() },
        }, new Uri($"https://127.0.0.1:{port}"));
    }

    [Fact]
    public void Published_windows_desktop_is_one_self_contained_exe_with_the_embedded_ui()
    {
        var output = Publish("SapLens.Desktop", "win-x64");
        var exe = Path.Combine(output, "SapLens2Prototype.exe");
        Assert.True(File.Exists(exe));
        Assert.False(Directory.Exists(Path.Combine(output, "frontend")));
        Assert.False(Directory.Exists(Path.Combine(output, "wwwroot")));
        // The single-file bundle stores SapLens.Api.dll uncompressed: its embedded UI files are present byte for byte, as are the WebView2 loader and the
        // runtime (no installed .NET needed).
        Assert.True(Contains(exe, UiAssets.Marker));
        Assert.True(Contains(exe, "SapLens.Api.wwwroot.assets.")); // the React build output inside the bundled SapLens.Api.dll
        Assert.True(Contains(exe, "WebView2Loader.dll"));
        Assert.True(Contains(exe, "System.Private.CoreLib.dll"));
        Assert.True(new FileInfo(exe).Length > 50_000_000);
    }
}
