using System.Net;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json.Nodes;
using Microsoft.AspNetCore.Builder;
using SapLens.Api;

namespace SapLens.Tests;

/// <summary>GET /api/access/users-selection and /api/access/exports/users against Python v1. Fixtures/access/expected.python.json was written by
/// tools/access_reference.py (v1 users_selection and export_users) on the synthetic small dataset in Fixtures/sod/analysis.</summary>
public sealed class AccessExportTests : IAsyncLifetime
{
    private readonly string _root = Directory.CreateTempSubdirectory("saplens-accexp-").FullName;
    private readonly string _token = HostSettings.NewToken();
    private WebApplication _app = null!;
    private HttpClient _client = null!;

    private static string Fixture(params string[] path) => Path.Combine([AppContext.BaseDirectory, "Fixtures", .. path]);

    public async Task InitializeAsync()
    {
        _app = SapLensHost.Build(new HostSettings { DataDirectory = Path.Combine(_root, "data"), Port = 0, AccessToken = _token, JsonConsoleLogging = false });
        await _app.StartAsync();
        _client = new HttpClient { BaseAddress = new Uri(_app.Urls.First()) };
        _client.DefaultRequestHeaders.Add(RequestBoundary.TokenHeader, _token);
        foreach (var source in new[] { "roles", "users" })
        {
            var job = JsonNode.Parse(await (await _client.PostAsync($"/api/v1/imports/{source}", new StringContent(File.ReadAllText(Fixture("sod", "analysis", source + ".sod.txt")), Encoding.UTF8, "text/csv"))).Content.ReadAsStringAsync())!;
            for (var i = 0; i < 400 && (string)JsonNode.Parse(await _client.GetStringAsync($"/api/v1/jobs/{(long)job["id"]!}"))!["status"]! != "Completed"; i++) await Task.Delay(50);
        }
    }

    public async Task DisposeAsync()
    {
        _client.Dispose();
        await _app.StopAsync();
        await _app.DisposeAsync();
        Microsoft.Data.Sqlite.SqliteConnection.ClearAllPools();
        try { Directory.Delete(_root, true); } catch (IOException) { }
    }

    private static string QueryString(JsonObject spec) => string.Join('&', spec.Where(p => p.Key != "name").SelectMany(p => p.Value is JsonArray values
        ? values.Select(v => $"{p.Key}={Uri.EscapeDataString((string)v!)}")
        : [$"{p.Key}={Uri.EscapeDataString(p.Value!.GetValueKind() == System.Text.Json.JsonValueKind.True ? "true" : p.Value.GetValueKind() == System.Text.Json.JsonValueKind.False ? "false" : (string)p.Value!)}"]));

    [Fact]
    public async Task Selection_and_assignment_export_equal_python_v1()
    {
        var expected = JsonNode.Parse(File.ReadAllText(Fixture("access", "expected.python.json")))!.AsObject();
        var failures = new List<string>();
        foreach (var spec in JsonNode.Parse(File.ReadAllText(Fixture("access", "queries.json")))!.AsArray().Select(s => s!.AsObject()))
        {
            var name = (string)spec["name"]!;
            var want = expected[name]!;
            var query = QueryString(spec);
            var selection = JsonNode.Parse(await _client.GetStringAsync("/api/access/users-selection?" + query))!;
            if ((int)selection["total"]! != (int)want["total"]! || !JsonNode.DeepEquals(selection["usernames"], want["usernames"])) failures.Add($"{name}: selection differs ({selection["total"]} vs {want["total"]})");
            var response = await _client.GetAsync("/api/access/exports/users?" + query);
            var bytes = await response.Content.ReadAsByteArrayAsync();
            var text = Encoding.UTF8.GetString(bytes);
            if (Convert.ToHexStringLower(SHA256.HashData(Encoding.UTF8.GetBytes(text))) != (string)want["csv_sha256"]!)
                failures.Add($"{name}: CSV differs; head {string.Join(" | ", text.Split("\r\n").Take(3))} vs {string.Join(" | ", want["csv_head"]!.AsArray().Select(v => (string)v!))}");
            if (response.Headers.GetValues("X-SAP-Lens-Assignment-Count").Single() != ((int)want["count"]!).ToString()) failures.Add($"{name}: count header differs");
        }
        Assert.True(failures.Count == 0, string.Join("\n", failures));
    }

    [Fact]
    public async Task Export_headers_formula_cells_and_refusals()
    {
        var response = await _client.GetAsync("/api/access/exports/users?show_expired=true");
        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        Assert.StartsWith("text/csv", response.Content.Headers.ContentType!.ToString());
        Assert.Matches("attachment; filename=\"sap-lens-user-directory-review-\\d{4}-\\d{2}-\\d{2}\\.csv\"", response.Content.Headers.ContentDisposition?.ToString() ?? string.Join("", response.Headers.GetValues("Content-Disposition")));
        Assert.Equal("no-store", response.Headers.CacheControl!.ToString());
        Assert.Equal((HttpStatusCode)501, (await _client.GetAsync("/api/access/exports/users?missing_roles=X")).StatusCode);
        Assert.Equal((HttpStatusCode)422, (await _client.GetAsync("/api/access/users-selection?sort=password")).StatusCode);
        Assert.Equal("'=cmd", V1Csv.Cell("=cmd"));
    }
}
