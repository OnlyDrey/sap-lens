using System.Text;
using System.Text.Json.Nodes;
using Microsoft.AspNetCore.Builder;
using AuthLens.Api;

namespace AuthLens.Tests;

/// <summary>GET /api/diagnostics and /api/diagnostics/export: the v1 allowlist (Fixtures/diagnostics/expected.python.json from
/// tools/diagnostics_reference.py), private fields only in the Desktop view, and values that follow the imported datasets.</summary>
public sealed class DiagnosticsTests : IAsyncLifetime
{
    private readonly string _root = Directory.CreateTempSubdirectory("saplens-diag-").FullName;
    private readonly string _token = HostSettings.NewToken();
    private WebApplication _app = null!;
    private HttpClient _client = null!;

    public Task InitializeAsync() => StartAsync(HostMode.Desktop);

    private async Task StartAsync(HostMode mode)
    {
        _app = AuthLensHost.Build(new HostSettings { DataDirectory = Path.Combine(_root, "data"), Port = 0, AccessToken = _token, JsonConsoleLogging = false, Mode = mode });
        await _app.StartAsync();
        _client = new HttpClient { BaseAddress = new Uri(_app.Urls.First()) };
        _client.DefaultRequestHeaders.Add(RequestBoundary.TokenHeader, _token);
    }

    public async Task DisposeAsync()
    {
        _client.Dispose();
        await _app.StopAsync();
        await _app.DisposeAsync();
        Microsoft.Data.Sqlite.SqliteConnection.ClearAllPools();
        try { Directory.Delete(_root, true); } catch (IOException) { }
    }

    private static HashSet<string> Keys(JsonNode node) => node.AsObject().Select(p => p.Key).ToHashSet();
    private static HashSet<string> Set(JsonNode node) => node.AsArray().Select(v => (string)v!).ToHashSet();

    [Fact]
    public async Task Diagnostics_follow_the_v1_allowlist_and_redact_the_export()
    {
        var expected = JsonNode.Parse(File.ReadAllText(Path.Combine(AppContext.BaseDirectory, "Fixtures", "diagnostics", "expected.python.json")))!;
        var job = JsonNode.Parse(await (await _client.PostAsync("/api/v1/imports/roles", new StringContent(Csv.Roles(5), Encoding.UTF8, "text/csv"))).Content.ReadAsStringAsync())!;
        for (var i = 0; i < 200 && (string)JsonNode.Parse(await _client.GetStringAsync($"/api/v1/jobs/{(long)job["id"]!}"))!["status"]! != "Completed"; i++) await Task.Delay(50);

        foreach (var (path, name) in new[] { ("/api/diagnostics", "private"), ("/api/diagnostics/export", "export") })
        {
            var report = JsonNode.Parse(await _client.GetStringAsync(path))!;
            var want = expected[name]!;
            // .NET adds "runtime" (python_version is null); every v1 key is present and no private key leaks into the export.
            Assert.Equal(Set(want["top"]!), Keys(report).Where(k => k != "runtime").ToHashSet());
            Assert.Equal(want["source_order"]!.AsArray().Select(v => (string)v!), report["sources"]!.AsArray().Select(s => (string)s!["id"]!));
            foreach (var source in report["sources"]!.AsArray()) Assert.Equal(Set(want["sources"]![(string)source!["id"]!]!), Keys(source));
            Assert.Equal(Set(want["scheduled_refresh"]!), Keys(report["scheduled_refresh"]!));
            Assert.Equal("ok", (string)report["review_continuity"]!);
            Assert.Equal("desktop", (string)report["deployment_mode"]!);
            var roles = report["sources"]![0]!;
            Assert.True((bool)roles["loaded"]!);
            Assert.Equal(5, (int)roles["records"]!);
            Assert.Equal(5, (int)report["cached_roles"]!);
            Assert.True((bool)report["data_source_configured"]!);
            Assert.NotNull(report["last_successful_load"]);
        }
        var export = await _client.GetStringAsync("/api/diagnostics/export");
        Assert.DoesNotContain(_root.Replace("\\", "\\\\"), export);
    }

    [Fact]
    public async Task Server_diagnostics_never_include_private_fields()
    {
        _client.Dispose();
        await _app.StopAsync();
        await _app.DisposeAsync();
        await StartAsync(HostMode.Server);
        var report = JsonNode.Parse(await _client.GetStringAsync("/api/diagnostics"))!;
        Assert.False(report.AsObject().ContainsKey("application_directory"));
        Assert.False(report["sources"]![0]!.AsObject().ContainsKey("configured_path"));
        Assert.Equal("server", (string)report["deployment_mode"]!);
    }
}
