using System.Net;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json.Nodes;
using Microsoft.AspNetCore.Builder;
using AuthLens.Api;

namespace AuthLens.Tests;

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
        _app = AuthLensHost.Build(new HostSettings { DataDirectory = Path.Combine(_root, "data"), Port = 0, AccessToken = _token, JsonConsoleLogging = false });
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

    private static string Value(JsonNode value) => value.GetValueKind() switch
    {
        System.Text.Json.JsonValueKind.True => "true", System.Text.Json.JsonValueKind.False => "false", System.Text.Json.JsonValueKind.String => (string)value!, _ => value.ToJsonString(),
    };

    private static string QueryString(JsonObject spec) => string.Join('&', spec.Where(p => p.Key != "name").SelectMany(p => p.Value is JsonArray values
        ? values.Select(v => $"{p.Key}={Uri.EscapeDataString(Value(v!))}")
        : [$"{p.Key}={Uri.EscapeDataString(Value(p.Value!))}"]));

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
            var selectionResponse = await _client.GetAsync("/api/access/users-selection?" + query);
            var selectionText = await selectionResponse.Content.ReadAsStringAsync();
            if (!selectionResponse.IsSuccessStatusCode) { failures.Add($"{name}: selection {(int)selectionResponse.StatusCode} {selectionText}"); continue; }
            var selection = JsonNode.Parse(selectionText)!;
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
    public async Task Release_roles_routes_equal_python_v1()
    {
        var expected = JsonNode.Parse(File.ReadAllText(Fixture("access", "release-expected.python.json")))!.AsObject();
        var failures = new List<string>();
        foreach (var spec in JsonNode.Parse(File.ReadAllText(Fixture("access", "release-queries.json")))!.AsArray().Select(s => s!.AsObject()))
        {
            var name = (string)spec["name"]!;
            var route = (string)spec["route"]!;
            var parameters = spec.DeepClone().AsObject();
            parameters.Remove("route");
            var response = await _client.GetAsync($"/api/access/{route}?{QueryString(parameters)}");
            var text = Encoding.UTF8.GetString(await response.Content.ReadAsByteArrayAsync());
            if (response.StatusCode != HttpStatusCode.OK) { failures.Add($"{name}: {response.StatusCode} {text}"); continue; }
            var want = expected[name]!;
            if (route.StartsWith("exports/", StringComparison.Ordinal))
            {
                if (Convert.ToHexStringLower(SHA256.HashData(Encoding.UTF8.GetBytes(text))) != (string)want["csv_sha256"]!)
                    failures.Add($"{name}: CSV differs; head {string.Join(" | ", text.Split("\r\n").Take(3))} vs {string.Join(" | ", want["csv_head"]!.AsArray().Select(v => (string)v!))}");
                continue;
            }
            var actual = JsonNode.Parse(text)!.AsObject();
            actual.Remove("as_of");
            actual.Remove("data_revision");
            if (!JsonNode.DeepEquals(want, actual))
            {
                var keys = want.AsObject().Select(p => p.Key).Union(actual.Select(p => p.Key)).Where(k => !JsonNode.DeepEquals(want[k], actual[k]));
                failures.Add($"{name}: differs in {string.Join(", ", keys.Select(k => $"{k}: {Short(want[k])} vs {Short(actual[k])}"))}");
            }
        }
        Assert.True(failures.Count == 0, string.Join("\n", failures));
    }

    [Fact]
    public async Task Legacy_role_comparison_equals_python_v1_and_validates_like_v1()
    {
        var expected = JsonNode.Parse(File.ReadAllText(Fixture("access", "compare-expected.python.json")))!.AsObject();
        foreach (var spec in JsonNode.Parse(File.ReadAllText(Fixture("access", "compare-queries.json")))!.AsArray())
        {
            var response = await Post("/api/compare", new JsonObject { ["roles"] = spec!["roles"]!.DeepClone() });
            Assert.Equal(HttpStatusCode.OK, response.Status);
            var actual = response.Body!.AsObject();
            Assert.NotNull(actual["analysis"]);
            actual.Remove("analysis");
            Assert.True(JsonNode.DeepEquals(expected[(string)spec["name"]!], actual), $"{spec["name"]}: {Short(actual)}");
        }
        Assert.Equal((HttpStatusCode)422, (await Post("/api/compare", new JsonObject { ["roles"] = new JsonArray("ZC:FI:ROLE_00012") })).Status);
        Assert.Equal((HttpStatusCode)422, (await Post("/api/compare", new JsonObject { ["roles"] = new JsonArray("A", "B", "C", "D", "E", "F") })).Status);
        Assert.Equal(HttpStatusCode.BadRequest, (await Post("/api/compare", new JsonObject { ["roles"] = new JsonArray("ZC:FI:ROLE_00012", "ZC:FI:ROLE_00012") })).Status);
        Assert.Equal(HttpStatusCode.NotFound, (await Post("/api/compare", new JsonObject { ["roles"] = new JsonArray("ZC:FI:ROLE_00012", "NOPE") })).Status);
    }

    private async Task<(HttpStatusCode Status, JsonNode? Body)> Post(string path, JsonNode body)
    {
        var request = new HttpRequestMessage(HttpMethod.Post, path) { Content = new StringContent(body.ToJsonString(), Encoding.UTF8, "application/json") };
        request.Headers.Add("Origin", _client.BaseAddress!.GetLeftPart(UriPartial.Authority));
        var response = await _client.SendAsync(request);
        return (response.StatusCode, JsonNode.Parse(await response.Content.ReadAsStringAsync()));
    }

    private static string Short(JsonNode? node) { var text = node?.ToJsonString() ?? "null"; return text.Length > 300 ? text[..300] : text; }

    [Fact]
    public async Task Export_headers_formula_cells_and_refusals()
    {
        var response = await _client.GetAsync("/api/access/exports/users?show_expired=true");
        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        Assert.StartsWith("text/csv", response.Content.Headers.ContentType!.ToString());
        Assert.Matches("attachment; filename=\"authlens-user-directory-review-\\d{4}-\\d{2}-\\d{2}\\.csv\"", response.Content.Headers.ContentDisposition?.ToString() ?? string.Join("", response.Headers.GetValues("Content-Disposition")));
        Assert.Equal("no-store", response.Headers.CacheControl!.ToString());
        var tooMany = Uri.EscapeDataString(string.Join(',', Enumerable.Range(0, 501).Select(i => $"U{i:000}")));
        Assert.Equal((HttpStatusCode)422, (await _client.GetAsync("/api/access/exports/users?usernames=" + tooMany)).StatusCode);   // v1: at most 500 names
        Assert.Equal((HttpStatusCode)422, (await _client.GetAsync("/api/access/users-selection?sort=password")).StatusCode);
        Assert.Equal("'=cmd", V1Csv.Cell("=cmd"));
    }
}
