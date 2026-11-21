using System.Diagnostics;
using System.Net;
using System.Net.Sockets;
using System.Security.Cryptography.X509Certificates;
using System.Text;
using AuthLens.Api;

namespace AuthLens.Tests;

[CollectionDefinition("publish", DisableParallelization = true)]
public sealed class PublishCollection : ICollectionFixture<PublishFixture>;

/// <summary>Publishes each (project, runtime) once per test run into one isolated temporary directory.</summary>
public sealed class PublishFixture : IDisposable
{
    public string Root { get; } = Directory.CreateTempSubdirectory("saplens-publish-").FullName;
    private readonly Dictionary<string, string> _outputs = new();

    public string Get(string project, string rid, params string[] properties)
    {
        lock (_outputs)
        {
            var key = project + rid + string.Join(";", properties);
            if (!_outputs.TryGetValue(key, out var output)) _outputs[key] = output = PublishTests.PublishTo(Root, project, rid, properties);
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

    private string Publish(string project, string rid, params string[] properties) => fixture.Get(project, rid, properties);

    private static string RepoProject(string name)
    {
        var dir = new DirectoryInfo(AppContext.BaseDirectory);
        while (dir is not null && !File.Exists(Path.Combine(dir.FullName, "AuthLens.slnx"))) dir = dir.Parent;
        return Path.Combine(dir!.FullName, "src", name, name + ".csproj");
    }

    internal static string PublishTo(string root, string project, string rid, params string[] properties)
    {
        var variant = properties.Length == 0 ? "" : "-" + Convert.ToHexStringLower(System.Security.Cryptography.SHA256.HashData(Encoding.UTF8.GetBytes(string.Join(";", properties))))[..8];
        var output = Path.Combine(root, $"{project}-{rid}{variant}");
        var info = new ProcessStartInfo("dotnet") { RedirectStandardOutput = true, RedirectStandardError = true, UseShellExecute = false, WorkingDirectory = root };
        foreach (var arg in new[] { "publish", RepoProject(project), "-c", "Release", "-r", rid, "--self-contained", "true", "-o", output,
                     "--artifacts-path", Path.Combine(root, "artifacts-" + project + "-" + rid + variant), "-nologo",
                     // No long-lived MSBuild nodes or compiler server: they would inherit the redirected pipes and keep them open after publish exits.
                     "-nodeReuse:false", "-p:UseSharedCompilation=false" })
            info.ArgumentList.Add(arg);
        foreach (var property in properties) info.ArgumentList.Add("-p:" + property);
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

    private static bool Contains(string file, string text) => Contains(file, Encoding.UTF8.GetBytes(text));

    private static bool Contains(string file, byte[] needle) => File.ReadAllBytes(file).AsSpan().IndexOf(needle) >= 0;

    /// <summary>The largest image of the official icon, assets/branding/app.ico (ICONDIR, then 16-byte entries with size at +8 and offset at +12).</summary>
    private static byte[] LargestIconImage()
    {
        var ico = File.ReadAllBytes(Path.GetFullPath(Path.Combine(Path.GetDirectoryName(RepoProject("AuthLens.Api"))!, "..", "..", "..", "assets", "branding", "app.ico")));
        var (size, offset) = Enumerable.Range(0, BitConverter.ToUInt16(ico, 4)).Select(i => (BitConverter.ToInt32(ico, 14 + 16 * i), BitConverter.ToInt32(ico, 18 + 16 * i))).MaxBy(e => e.Item1);
        return ico[offset..(offset + size)];
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
        var output = Publish("AuthLens.Api", "linux-x64");
        Assert.False(Directory.Exists(Path.Combine(output, "wwwroot")), "the UI must be embedded, not loose files");
        Assert.True(Contains(Path.Combine(output, "AuthLens.Api.dll"), UiAssets.Marker));
        Assert.True(Contains(Path.Combine(output, "AuthLens.Api.dll"), "AuthLensUi/assets")); // the React build output

        var elsewhere = Directory.CreateDirectory(Path.Combine(_root, "unrelated-cwd")).FullName;
        var token = HostSettings.NewToken();
        var port = FreePort();
        var info = new ProcessStartInfo(Path.Combine(output, "AuthLens.Api")) { WorkingDirectory = elsewhere, UseShellExecute = false, RedirectStandardOutput = true, RedirectStandardError = true };
        foreach (var arg in new[] { "--data-dir", Path.Combine(_root, "data"), "--port", port.ToString() }) info.ArgumentList.Add(arg);
        info.Environment["AUTHLENS_TOKEN"] = token;
        info.Environment.Remove("DOTNET_ROOT"); // self-contained: must not need an installed runtime
        using var server = Process.Start(info)!;
        _ = server.StandardOutput.ReadToEndAsync();
        _ = server.StandardError.ReadToEndAsync();
        try
        {
            using var http = new HttpClient(new HttpClientHandler { UseProxy = false }) { BaseAddress = new Uri($"http://127.0.0.1:{port}") };
            var probe = await StartupProbe.WaitAsync(http.BaseAddress, TimeSpan.FromSeconds(30), token: token); // "/" served the React application
            Assert.True(probe.Ok, probe.Problem);
            foreach (var (path, type) in new[] { ("/theme.js", "text/javascript"), ("/logo.png", "image/png"), ("/login.html", "text/html"), ("/login.css", "text/css") })
            {
                var response = await http.GetAsync(path);
                Assert.Equal(HttpStatusCode.OK, response.StatusCode);
                Assert.Equal(type, response.Content.Headers.ContentType!.MediaType);
            }
            Assert.Equal(HttpStatusCode.Unauthorized, (await http.GetAsync("/api/v1/roles")).StatusCode);
            using var authorized = new HttpRequestMessage(HttpMethod.Get, "/api/v1/roles");
            authorized.Headers.Add(RequestBoundary.TokenHeader, token);
            Assert.Equal(HttpStatusCode.OK, (await http.SendAsync(authorized)).StatusCode);
            Assert.True(File.Exists(Path.Combine(_root, "data", "authlens.sqlite3")));
            Assert.Empty(Directory.GetFiles(elsewhere, "*", SearchOption.AllDirectories)); // nothing written to the working directory
        }
        finally
        {
            server.Kill(entireProcessTree: true);
            server.WaitForExit(10000);
        }
    }

    private static string[] Files(string output) =>
        [.. Directory.GetFiles(output, "*", SearchOption.AllDirectories).Select(f => Path.GetRelativePath(output, f).Replace('\\', '/')).Order(StringComparer.Ordinal)];

    [Fact]
    public void Published_windows_server_is_one_single_file_exe_with_sqlite_beside_it()
    {
        var output = Publish("AuthLens.Api", "win-x64");
        // Everything managed (the server, the embedded React UI, ASP.NET Core, the Windows service host) is inside AuthLens.Api.exe; the only other
        // runtime file is SQLite's native library, deliberately not self-extracted to %TEMP%. Symbols are collected separately by the release scripts.
        Assert.Equal(["AuthLens.Api.exe", "e_sqlite3.dll", "libSkiaSharp.dll"], Files(output).Where(f => !f.EndsWith(".pdb", StringComparison.Ordinal)));
        var exe = Path.Combine(output, "AuthLens.Api.exe");
        Assert.True(Contains(exe, UiAssets.Marker));
        Assert.True(Contains(exe, "AuthLensUi/index.html"));
        Assert.True(Contains(exe, "AuthLensUi/assets")); // the React build output
        Assert.True(Contains(exe, "Microsoft.Extensions.Hosting.WindowsServices.dll")); // runs as a Windows service
        Assert.True(Contains(exe, "System.Private.CoreLib.dll"));                         // self-contained
        Assert.True(Contains(exe, "AuthLens.Api.runtimeconfig.json"));
        Assert.True(new FileInfo(exe).Length > 50_000_000);
        // The official icon is embedded as the application icon: its largest image (the 256 px entry of assets/branding/app.ico) is in the exe's resources.
        Assert.True(Contains(exe, LargestIconImage()));
    }

    [Fact]
    public async Task Single_file_server_runs_without_extraction_and_keeps_data_outside_the_application()
    {
        if (!OperatingSystem.IsLinux() && !OperatingSystem.IsWindows()) return;
        var windows = OperatingSystem.IsWindows();
        var executable = windows ? "AuthLens.Api.exe" : "AuthLens.Api";
        var expected = windows ? new[] { executable, "e_sqlite3.dll", "libSkiaSharp.dll" } : [executable, "libSkiaSharp.so", "libe_sqlite3.so"];
        var output = windows ? Publish("AuthLens.Api", "win-x64") : Publish("AuthLens.Api", "linux-x64", "PublishSingleFile=true", "IncludeNativeLibrariesForSelfExtract=false");
        Assert.Equal(expected, Files(output).Where(f => !f.EndsWith(".pdb", StringComparison.Ordinal)));
        var extract = Directory.CreateDirectory(Path.Combine(_root, "extract")).FullName;
        async Task<(int Code, string Out, string Error)> Run(params string[] args)
        {
            var info = new ProcessStartInfo(Path.Combine(output, executable)) { WorkingDirectory = _root, UseShellExecute = false, RedirectStandardOutput = true, RedirectStandardError = true, CreateNoWindow = true };
            foreach (var arg in args) info.ArgumentList.Add(arg);
            info.Environment["DOTNET_BUNDLE_EXTRACT_BASE_DIR"] = extract;
            info.Environment["AUTHLENS_TOKEN"] = HostSettings.NewToken();
            using var process = Process.Start(info)!;
            var stdout = process.StandardOutput.ReadToEndAsync();
            var stderr = process.StandardError.ReadToEndAsync();
            Assert.True(process.WaitForExit(30000));
            return (process.ExitCode, await stdout, await stderr);
        }
        var version = await Run("--version");
        Assert.Equal(0, version.Code);
        Assert.StartsWith("AuthLens server ", version.Out);
        Assert.Contains("--trusted-proxies", (await Run("--help")).Out);
        var inside = await Run("--data-dir", Path.Combine(output, "data"), "--port", FreePort().ToString());
        Assert.Equal(3, inside.Code);
        Assert.Contains("outside the application directory", inside.Error);

        var token = HostSettings.NewToken();
        var port = FreePort();
        var info = new ProcessStartInfo(Path.Combine(output, executable)) { WorkingDirectory = _root, UseShellExecute = false, RedirectStandardOutput = true, RedirectStandardError = true, CreateNoWindow = true };
        foreach (var arg in new[] { "--data-dir", Path.Combine(_root, "single-file-data"), "--port", port.ToString() }) info.ArgumentList.Add(arg);
        info.Environment["AUTHLENS_TOKEN"] = token;
        info.Environment["DOTNET_BUNDLE_EXTRACT_BASE_DIR"] = extract;
        using var server = Process.Start(info)!;
        _ = server.StandardOutput.ReadToEndAsync();
        _ = server.StandardError.ReadToEndAsync();
        try
        {
            using var http = new HttpClient(new HttpClientHandler { UseProxy = false }) { BaseAddress = new Uri($"http://127.0.0.1:{port}") };
            var probe = await StartupProbe.WaitAsync(http.BaseAddress, TimeSpan.FromSeconds(30), token: token);   // readiness (SQLite migrated) and the UI at "/"
            Assert.True(probe.Ok, probe.Problem);
            var index = await http.GetStringAsync("/");
            var script = System.Text.RegularExpressions.Regex.Match(index, "src=\"(/assets/[^\"]+\\.js)\"").Groups[1].Value;
            Assert.NotEmpty(script);
            var asset = await http.GetAsync(script);
            Assert.Equal(HttpStatusCode.OK, asset.StatusCode);
            Assert.Equal("text/javascript", asset.Content.Headers.ContentType!.MediaType);
            using var authorized = new HttpRequestMessage(HttpMethod.Get, "/api/v1/roles");
            authorized.Headers.Add(RequestBoundary.TokenHeader, token);
            Assert.Equal(HttpStatusCode.OK, (await http.SendAsync(authorized)).StatusCode);       // SQLite through the native library beside the exe
            Assert.True(File.Exists(Path.Combine(_root, "single-file-data", "authlens.sqlite3")));
            Assert.Empty(Directory.GetFileSystemEntries(extract));                                // nothing extracted
            Assert.Equal(expected, Files(output).Where(f => !f.EndsWith(".pdb", StringComparison.Ordinal)));   // nothing written next to the exe
        }
        finally
        {
            server.Kill(entireProcessTree: true);
            server.WaitForExit(10000);
        }
    }

    [Fact]
    public async Task Published_windows_desktop_self_check_uses_only_its_explicit_fixture()
    {
        if (!OperatingSystem.IsWindows()) return;
        var output = Publish("AuthLens.Desktop", "win-x64");
        var data = Path.Combine(_root, "desktop-self-check");
        var info = new ProcessStartInfo(Path.Combine(output, "AuthLens.exe"))
        { WorkingDirectory = _root, UseShellExecute = false, RedirectStandardOutput = true, RedirectStandardError = true, CreateNoWindow = true };
        foreach (var arg in new[] { "--data-dir", data, "--self-check" }) info.ArgumentList.Add(arg);
        using var process = Process.Start(info)!;
        var stdout = process.StandardOutput.ReadToEndAsync();
        var stderr = process.StandardError.ReadToEndAsync();
        try
        {
            Assert.True(process.WaitForExit(60000), "Isolated Desktop self-check did not exit.");
            Assert.True(process.ExitCode == 0, await stdout + await stderr);
            Assert.True(File.Exists(Path.Combine(data, "authlens.sqlite3")));
            Assert.False(File.Exists(Path.Combine(data, "sap-lens-v2.sqlite3")));
            var log = Assert.Single(Directory.GetFiles(Path.Combine(data, ".desktop", "logs"), "self-check-*.log"));
            Assert.Contains("Self-check passed", await File.ReadAllTextAsync(log));
        }
        finally { if (!process.HasExited) { process.Kill(entireProcessTree: true); process.WaitForExit(10000); } }
    }

    private async Task<(int? ExitCode, string Error)> RunServer(string output, string[] args, Func<HttpClient, Task>? whileRunning = null, Func<HttpMessageHandler>? handler = null, Uri? baseAddress = null)
    {
        var info = new ProcessStartInfo(Path.Combine(output, "AuthLens.Api")) { WorkingDirectory = Directory.CreateDirectory(Path.Combine(_root, "cwd-" + Guid.NewGuid().ToString("N"))).FullName,
            UseShellExecute = false, RedirectStandardOutput = true, RedirectStandardError = true };
        foreach (var arg in args) info.ArgumentList.Add(arg);
        info.Environment["AUTHLENS_TOKEN"] = HostSettings.NewToken();
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
        var output = Publish("AuthLens.Api", "linux-x64");
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
        var output = Publish("AuthLens.Desktop", "win-x64");
        var exe = Path.Combine(output, "AuthLens.exe");
        Assert.True(File.Exists(exe));
        Assert.False(Directory.Exists(Path.Combine(output, "frontend")));
        Assert.False(Directory.Exists(Path.Combine(output, "wwwroot")));
        // The single-file bundle stores AuthLens.Api.dll uncompressed: its embedded UI files are present byte for byte, as are the WebView2 loader and the
        // runtime (no installed .NET needed).
        Assert.True(Contains(exe, UiAssets.Marker));
        Assert.True(Contains(exe, "AuthLensUi/assets")); // the React build output inside the bundled AuthLens.Api.dll
        Assert.True(Contains(exe, "WebView2Loader.dll"));
        Assert.True(Contains(exe, "System.Private.CoreLib.dll"));
        Assert.True(new FileInfo(exe).Length > 50_000_000);
        Assert.True(Contains(exe, LargestIconImage()));   // the official icon (assets/branding/app.ico) is the application icon
        Assert.Equal(["AuthLens.exe"], Files(output).Where(f => !f.EndsWith(".pdb", StringComparison.Ordinal)));   // no loose server host, docs or settings
    }
}
