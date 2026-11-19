using System.Net;
using System.Text;
using System.Text.Json.Nodes;
using Microsoft.AspNetCore.Builder;
using AuthLens.Api;

namespace AuthLens.Tests;

/// <summary>MIG-010: the per-record changes of a refresh report (GET /api/data-sources/reports/{id} and its CSV export) equal Python v1
/// (tools/refresh_report_reference.py) for roles, users, the Employee Directory and the SoD matrix: modified, removed, added, ambiguous and
/// unidentified records, filters, paging, formula neutralization and quoting.</summary>
public sealed class RefreshReportTests : IAsyncLifetime
{
    private static readonly string Fixtures = Path.Combine(AppContext.BaseDirectory, "Fixtures", "imports");
    private readonly string _root = Directory.CreateTempSubdirectory("saplens-reports-").FullName;
    private readonly string _token = HostSettings.NewToken();
    private WebApplication _app = null!;
    private HttpClient _client = null!;

    public async Task InitializeAsync()
    {
        _app = AuthLensHost.Build(new HostSettings { DataDirectory = Path.Combine(_root, "data"), Port = 0, AccessToken = _token, JsonConsoleLogging = false, PrincipalName = "importer", Mode = HostMode.Server });
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

    private async Task<int> Revision() => (int)JsonNode.Parse(await _client.GetStringAsync("/api/configuration"))!["settings"]!["revision"]!;

    private async Task<JsonObject> Upload(string source, string file)
    {
        var form = new MultipartFormDataContent
        {
            { new ByteArrayContent(File.ReadAllBytes(Path.Combine(Fixtures, file))), "file", $"{source}.csv" },
            { new StringContent((await Revision()).ToString()), "revision" },
            { new StringContent("true"), "confirm_anomalies" },
        };
        var request = new HttpRequestMessage(HttpMethod.Post, $"/api/server/uploads/{source}/activate") { Content = form };
        request.Headers.Add("Origin", _client.BaseAddress!.GetLeftPart(UriPartial.Authority));
        var response = await _client.SendAsync(request);
        var text = await response.Content.ReadAsStringAsync();
        Assert.True(response.IsSuccessStatusCode, $"{source} {file}: {(int)response.StatusCode} {text}");
        return JsonNode.Parse(text)!.AsObject();
    }

    private static string Query(JsonObject query) => string.Join('&', query.Select(p => $"{p.Key}={Uri.EscapeDataString(p.Value!.ToString())}"));

    [Fact]
    public async Task Report_details_and_exports_equal_python_v1_for_every_source()
    {
        var expected = JsonNode.Parse(File.ReadAllText(Path.Combine(Fixtures, "reports.python.json")))!.AsObject();
        var compared = 0;
        foreach (var source in new[] { "roles", "users", "employees", "sod" })
        {
            await Upload(source, $"report_{source}_before.txt");
            var after = await Upload(source, $"report_{source}_after.txt");
            var refresh = after["refresh"]!.AsObject();
            // The import response and the history carry the summary only; the changed records stay in the private report.
            Assert.Null(refresh["sources"]![0]!["changes"]);
            var id = (string)refresh["id"]!;
            Assert.Equal(id, (string)JsonNode.Parse(await _client.GetStringAsync("/api/data-sources/history"))!["items"]![0]!["id"]!);
            foreach (var run in expected[source]!["pages"]!.AsArray())
            {
                var query = run!["query"]!.AsObject();
                var page = JsonNode.Parse(await _client.GetStringAsync($"/api/data-sources/reports/{id}?{Query(query)}"))!.AsObject();
                var label = $"{source} {query.ToJsonString()}";
                Assert.True(JsonNode.DeepEquals(run["items"], page["items"]), $"{label}\nexpected {run["items"]!.ToJsonString()}\nactual   {page["items"]!.ToJsonString()}");
                foreach (var key in new[] { "total", "offset", "limit" }) Assert.True(JsonNode.DeepEquals(run[key], page[key]), $"{label} {key}");
                Assert.Equal(id, (string)page["id"]!);
                Assert.Equal((string)refresh["timestamp"]!, (string)page["timestamp"]!);
                var result = page["sources"]![0]!.AsObject();
                Assert.Null(result["changes"]);
                foreach (var (key, value) in run["source"]!.AsObject().Where(p => p.Key != "changes"))
                    Assert.True(JsonNode.DeepEquals(value, result[key]), $"{label} source.{key}: expected {value?.ToJsonString()} actual {result[key]?.ToJsonString()}");
                compared++;
            }
            foreach (var run in expected[source]!["exports"]!.AsArray())
            {
                var query = run!["query"]!.AsObject();
                var response = await _client.GetAsync($"/api/data-sources/reports/{id}/export?{Query(query)}");
                Assert.Equal("text/csv; charset=utf-8", response.Content.Headers.ContentType!.ToString());
                Assert.Equal("attachment; filename=\"AuthLens-refresh-changes.csv\"", response.Content.Headers.ContentDisposition!.ToString());
                var csv = Encoding.UTF8.GetString(await response.Content.ReadAsByteArrayAsync());
                Assert.Equal((string)run["csv"]!, csv.Replace($"\"{(string)refresh["timestamp"]!}\"", "\"T\"", StringComparison.Ordinal));
                compared++;
            }
        }
        Assert.Equal(60, compared);
    }

    [Fact]
    public async Task Only_retained_reports_are_served_and_queries_are_validated_like_pydantic()
    {
        Assert.Equal(HttpStatusCode.NotFound, (await _client.GetAsync("/api/data-sources/reports/" + new string('a', 64))).StatusCode);
        var body = JsonNode.Parse(await (await _client.GetAsync("/api/data-sources/reports/x")).Content.ReadAsStringAsync())!;
        Assert.Equal("Refresh report is no longer retained.", (string)body["detail"]!);

        var id = (string)(await Upload("roles", "report_roles_before.txt"))["refresh"]!["id"]!;
        var response = await _client.GetAsync($"/api/data-sources/reports/{id}?source=other&kind=gone&search={new string('x', 257)}&offset=-1&limit=101");
        Assert.Equal(HttpStatusCode.UnprocessableEntity, response.StatusCode);
        var errors = JsonNode.Parse(await response.Content.ReadAsStringAsync())!["detail"]!.AsArray();
        Assert.Equal(["source", "kind", "search", "offset", "limit"], errors.Select(e => (string)e!["loc"]![1]!));
        Assert.Equal(["string_pattern_mismatch", "string_pattern_mismatch", "string_too_long", "greater_than_equal", "less_than_equal"], errors.Select(e => (string)e!["type"]!));
        Assert.Equal(HttpStatusCode.UnprocessableEntity, (await _client.GetAsync($"/api/data-sources/reports/{id}?limit=abc")).StatusCode);
        Assert.Equal(HttpStatusCode.UnprocessableEntity, (await _client.GetAsync($"/api/data-sources/reports/{id}/export?kind=x")).StatusCode);

        // The first import of a source: every record is added, nothing removed or modified.
        var page = JsonNode.Parse(await _client.GetStringAsync($"/api/data-sources/reports/{id}?limit=1"))!;
        Assert.Equal(400, (int)page["total"]!);
        Assert.Equal("added", (string)page["items"]![0]!["type"]!);
        Assert.Equal("Role Catalogue", (string)page["items"]![0]!["source_name"]!);

        // Reports beyond the five retained ones are no longer served, even though the stored record is immutable.
        for (var i = 0; i < 5; i++) await Upload("roles", i % 2 == 0 ? "report_roles_after.txt" : "report_roles_before.txt");
        Assert.Equal(HttpStatusCode.NotFound, (await _client.GetAsync($"/api/data-sources/reports/{id}")).StatusCode);
        Assert.Equal(HttpStatusCode.NotFound, (await _client.GetAsync($"/api/data-sources/reports/{id}/export")).StatusCode);
    }
}
