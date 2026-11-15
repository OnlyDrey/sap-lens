using System.Diagnostics;
using System.Net;
using System.Net.Sockets;
using System.Text;
using SapLens.Api;

namespace SapLens.Tests;

[CollectionDefinition("publish", DisableParallelization = true)]
public sealed class PublishCollection;

/// <summary>Publish acceptance: real `dotnet publish` into an isolated temporary directory (own artifacts path, outside the repository), then the
/// published Server is run from a different working directory and must serve the UI entry point, its JavaScript and CSS, and still enforce the token.
/// Windows packages are cross-published and inspected (they cannot run here). Slow: filter with `--filter Category!=Publish` during development.</summary>
[Collection("publish")]
[Trait("Category", "Publish")]
public sealed class PublishTests : IDisposable
{
    private readonly string _root = Directory.CreateTempSubdirectory("saplens-publish-").FullName;

    public void Dispose()
    {
        try { Directory.Delete(_root, true); } catch (IOException) { } catch (UnauthorizedAccessException) { }
    }

    private static string RepoProject(string name)
    {
        var dir = new DirectoryInfo(AppContext.BaseDirectory);
        while (dir is not null && !File.Exists(Path.Combine(dir.FullName, "SapLens.slnx"))) dir = dir.Parent;
        return Path.Combine(dir!.FullName, "src", name, name + ".csproj");
    }

    private string Publish(string project, string rid)
    {
        var output = Path.Combine(_root, $"{project}-{rid}");
        var info = new ProcessStartInfo("dotnet") { RedirectStandardOutput = true, RedirectStandardError = true, UseShellExecute = false, WorkingDirectory = _root };
        foreach (var arg in new[] { "publish", RepoProject(project), "-c", "Release", "-r", rid, "--self-contained", "true", "-o", output,
                     "--artifacts-path", Path.Combine(_root, "artifacts-" + project + "-" + rid), "-nologo",
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
            var probe = await StartupProbe.WaitAsync(http.BaseAddress, TimeSpan.FromSeconds(30));
            Assert.True(probe.Ok, probe.Problem);
            foreach (var (path, type) in new[] { ("/", "text/html"), ("/app.js", "text/javascript"), ("/app.css", "text/css"), ("/login.html", "text/html") })
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
        Assert.True(Contains(exe, "WebView2Loader.dll"));
        Assert.True(Contains(exe, "System.Private.CoreLib.dll"));
        Assert.True(new FileInfo(exe).Length > 50_000_000);
    }
}
