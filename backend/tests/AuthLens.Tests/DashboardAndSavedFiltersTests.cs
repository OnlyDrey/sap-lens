using System.Net;
using System.Net.Http.Json;
using System.Text;
using System.Text.Json.Nodes;
using Microsoft.AspNetCore.Builder;
using AuthLens.Api;

namespace AuthLens.Tests;

/// <summary>GET /api/dashboard and /api/saved-filters in the v1 shapes: real snapshot aggregates (null with a reason when a source is missing or not
/// migrated, never zero-filled) and saved-filter CRUD with v1 validation, optimistic concurrency and persistence across restarts.</summary>
public sealed class DashboardAndSavedFiltersTests : IAsyncLifetime
{
    private readonly string _root = Directory.CreateTempSubdirectory("saplens-dash-").FullName;
    private readonly string _token = HostSettings.NewToken();
    private WebApplication _app = null!;
    private HttpClient _client = null!;

    public Task InitializeAsync() => Start();

    private async Task Start()
    {
        _app = AuthLensHost.Build(new HostSettings { DataDirectory = Path.Combine(_root, "data"), Port = 0, AccessToken = _token, JsonConsoleLogging = false });
        await _app.StartAsync();
        _client = new HttpClient { BaseAddress = new Uri(_app.Urls.First()) };
        _client.DefaultRequestHeaders.Add(RequestBoundary.TokenHeader, _token);
    }

    private async Task Stop()
    {
        _client.Dispose();
        await _app.StopAsync();
        await _app.DisposeAsync();
        Microsoft.Data.Sqlite.SqliteConnection.ClearAllPools();
    }

    public async Task DisposeAsync()
    {
        await Stop();
        try { Directory.Delete(_root, true); } catch (IOException) { }
    }

    private async Task Import(string source, string csv)
    {
        var job = JsonNode.Parse(await (await _client.PostAsync($"/api/v1/imports/{source}", new StringContent(csv, Encoding.UTF8, "text/csv"))).Content.ReadAsStringAsync())!;
        for (var i = 0; i < 200 && (string)JsonNode.Parse(await _client.GetStringAsync($"/api/v1/jobs/{(long)job["id"]!}"))!["status"]! != "Completed"; i++) await Task.Delay(50);
    }

    private static JsonNode Metric(JsonNode dashboard, string id) => dashboard["metrics"]!.AsArray().Single(m => (string)m!["id"]! == id)!;

    [Fact]
    public async Task Dashboard_reports_unavailable_sources_as_null_with_a_reason_and_counts_the_active_snapshots()
    {
        var empty = JsonNode.Parse(await _client.GetStringAsync("/api/dashboard"))!;
        Assert.Null((int?)Metric(empty, "roles")["value"]);
        Assert.Equal("Source not loaded", (string?)Metric(empty, "roles")["unavailable_reason"]);
        Assert.Equal("User Access CSV not loaded", (string?)Metric(empty, "users")["unavailable_reason"]);
        Assert.Null(empty["role_distribution"]);
        Assert.Null(empty["assignment_distribution"]);
        Assert.Null(empty["review_population"]);

        await Import("roles", Csv.Roles(10));
        const string active = "20000101;99991231";
        var lines = Enumerable.Range(0, 7).Select(r => $"USER0001;ZC:FI:ROLE_{r:D4};GRP_FIN;First;Last;;;;{active};;A")
            .Append("USER0001;ZC:FI:ROLE_0007;GRP_FIN;First;Last;;;;20000101;20010101;;A")   // expired
            .Append("USER0001;ZC:FI:ROLE_0008;GRP_FIN;First;Last;;;;20990101;99991231;;A")   // future
            .Append($"USER0002;ZC:FI:ROLE_0001;GRP_FIN;First;Last;;;;{active};;A");
        await Import("users", Csv.UsersHeader + "\n" + string.Join("\n", lines) + "\n");
        var dashboard = JsonNode.Parse(await _client.GetStringAsync("/api/dashboard"))!;
        Assert.Equal(10, (int)Metric(dashboard, "roles")["value"]!);
        Assert.Equal(30, (int)Metric(dashboard, "mappings")["value"]!);
        Assert.Equal(1, (int)Metric(dashboard, "areas")["value"]!);
        Assert.Equal(2, (int)Metric(dashboard, "users")["value"]!);
        Assert.Equal(10, (int)Metric(dashboard, "assignments")["value"]!);
        Assert.Equal(2, (int)Metric(dashboard, "assigned_users")["value"]!);
        Assert.Equal(1, (int)Metric(dashboard, "expired")["value"]!);
        Assert.Equal(1, (int)Metric(dashboard, "future")["value"]!);
        Assert.Null(Metric(dashboard, "expired")["unavailable_reason"]);
        Assert.Equal(10, (int)dashboard["role_distribution"]!["FI"]!);
        Assert.Equal(1, (int)dashboard["assignment_distribution"]!["0–5"]!);
        Assert.Equal(1, (int)dashboard["assignment_distribution"]!["6–10"]!);
        Assert.Equal(0, (int)dashboard["assignment_distribution"]!["31+"]!);
        Assert.Equal(2, (int)dashboard["review_population"]!);
        // Not migrated yet: explicit null with a reason, never an estimate.
        Assert.Equal((0, 0, 2, 0), ((int)Metric(dashboard, "account_review")["value"]!, (int)Metric(dashboard, "reviewed")["value"]!, (int)Metric(dashboard, "pending")["value"]!, (int)Metric(dashboard, "outdated")["value"]!));
        Assert.Null((int?)Metric(dashboard, "position_changes")["value"]);
        Assert.Equal("Employee Directory not loaded", (string?)Metric(dashboard, "position_changes")["unavailable_reason"]);
        Assert.Equal("Employee Directory disabled", (string?)Metric(dashboard, "employees")["unavailable_reason"]);
        Assert.Equal("Enable Employee Directory in Feature Settings.", (string?)Metric(dashboard, "email_matches")["unavailable_reason"]);
        Assert.Equal("Current local snapshots only; no historical trends or effective-authorization claims.", (string)dashboard["notice"]!);
        Assert.Equal(3, dashboard["sources"]!.AsArray().Count);
    }

    [Theory]
    [InlineData(0, "0–5")]
    [InlineData(5, "0–5")]
    [InlineData(6, "6–10")]
    [InlineData(20, "11–20")]
    [InlineData(21, "21–30")]
    [InlineData(31, "31+")]
    public void Assignment_bands_match_v1(int count, string band) => Assert.Equal(band, V1Dashboard.Band(count));

    private async Task<(HttpStatusCode Status, JsonNode? Body)> Save(object body)
    {
        var response = await _client.PostAsJsonAsync("/api/saved-filters", body);
        return (response.StatusCode, JsonNode.Parse(await response.Content.ReadAsStringAsync()));
    }

    [Fact]
    public async Task Saved_filters_create_update_rename_delete_and_survive_a_restart()
    {
        Assert.Empty(JsonNode.Parse(await _client.GetStringAsync("/api/saved-filters"))!["items"]!.AsArray());
        var (status, created) = await Save(new { name = "  Finance users ", view = "users", filters = new { search = "FI", groups = new[] { "GRP_FIN" }, descending = true, expired = 1 } });
        Assert.Equal(HttpStatusCode.OK, status);
        Assert.Equal("Finance users", (string)created!["name"]!);
        Assert.Matches("^[a-f0-9]{32}$", (string)created["id"]!);
        Assert.Equal(1, (int)created["filter_schema"]!);
        Assert.Equal((string)created["created"]!, (string)created["modified"]!);
        var id = (string)created["id"]!;
        var (_, second) = await Save(new { name = "Roles", view = "roles", filters = new { search = "X" } });

        // Duplicate names are compared case-insensitively per view; the same name in another view is allowed.
        Assert.Equal(HttpStatusCode.Conflict, (await Save(new { name = "FINANCE USERS", view = "users", filters = new { } })).Status);
        Assert.Equal(HttpStatusCode.OK, (await Save(new { name = "Finance users", view = "review", filters = new { } })).Status);

        // Updates need the current modified stamp; a stale one is refused.
        var (updatedStatus, updated) = await Save(new { name = "Finance users", view = "users", filters = new { search = "CO" }, id, expected = (string)created["modified"]! });
        Assert.Equal(HttpStatusCode.OK, updatedStatus);
        Assert.Equal("CO", (string)updated!["filters"]!["search"]!);
        Assert.Equal((string)created["created"]!, (string)updated["created"]!);
        var stale = await Save(new { name = "Finance users", view = "users", filters = new { }, id, expected = (string)created["modified"]! });
        Assert.Equal(HttpStatusCode.Conflict, stale.Status);
        Assert.Equal("Saved filter changed. Reload before updating.", (string)stale.Body!["detail"]!);
        Assert.Equal(HttpStatusCode.UnprocessableEntity, (await Save(new { name = "Moved", view = "roles", filters = new { }, id, expected = (string)updated["modified"]! })).Status);
        Assert.Equal(HttpStatusCode.NotFound, (await Save(new { name = "Ghost", view = "users", filters = new { }, id = "0123", expected = "x" })).Status);

        // Rename keeps the filters and ignores the allow-list.
        var (_, renamed) = await Save(new { name = "Renamed", view = "users", filters = new { anything = "x" }, id, expected = (string)updated["modified"]!, rename = true });
        Assert.Equal("Renamed", (string)renamed!["name"]!);
        Assert.Equal("CO", (string)renamed["filters"]!["search"]!);

        // v1 order: a saved entry moves to the end.
        var names = JsonNode.Parse(await _client.GetStringAsync("/api/saved-filters"))!["items"]!.AsArray().Select(i => (string)i!["name"]!).ToList();
        Assert.Equal(["Roles", "Finance users", "Renamed"], names);

        await Stop();
        await Start();
        var items = JsonNode.Parse(await _client.GetStringAsync("/api/saved-filters"))!["items"]!.AsArray();
        Assert.Equal(3, items.Count);
        Assert.Equal((string)renamed["modified"]!, (string)items.Single(i => (string)i!["id"]! == id)!["modified"]!);

        var staleDelete = await _client.PostAsJsonAsync("/api/saved-filters/delete", new { id, expected = (string)created["modified"]! });
        Assert.Equal(HttpStatusCode.Conflict, staleDelete.StatusCode);
        var delete = await _client.PostAsJsonAsync("/api/saved-filters/delete", new { id, expected = (string)renamed["modified"]! });
        Assert.Equal("deleted", (string)JsonNode.Parse(await delete.Content.ReadAsStringAsync())!["status"]!);
        Assert.Equal(HttpStatusCode.NotFound, (await _client.PostAsJsonAsync("/api/saved-filters/delete", new { id, expected = "x" })).StatusCode);
        Assert.Equal(2, JsonNode.Parse(await _client.GetStringAsync("/api/saved-filters"))!["items"]!.AsArray().Count);
        Assert.NotNull(second);
    }

    [Fact]
    public async Task Saved_filter_validation_matches_v1()
    {
        async Task<JsonNode> Refused(object body)
        {
            var (status, detail) = await Save(body);
            Assert.Equal(HttpStatusCode.UnprocessableEntity, status);
            return detail!["detail"]!;
        }
        Assert.Equal("Unsupported filter fields; result datasets cannot be saved.", (string)(await Refused(new { name = "A", view = "roles", filters = new { rows = new[] { "x" } } }))!);
        Assert.Equal("extra_forbidden", (string)(await Refused(new { name = "A", view = "roles", filters = new { }, extra = 1 }))[0]!["type"]!);
        Assert.Equal("literal_error", (string)(await Refused(new { name = "A", view = "unknown", filters = new { } }))[0]!["type"]!);
        Assert.Contains("nonempty readable name", (string)(await Refused(new { name = "   ", view = "roles", filters = new { } }))[0]!["msg"]!);
        Assert.Equal("string_too_long", (string)(await Refused(new { name = new string('a', 81), view = "roles", filters = new { } }))[0]!["type"]!);
        Assert.Contains("bounded scalar", (string)(await Refused(new { name = "A", view = "roles", filters = new { search = 1.5 } }))[0]!["msg"]!);
        Assert.Contains("bounded scalar", (string)(await Refused(new { name = "A", view = "roles", filters = new { search = new { nested = 1 } } }))[0]!["msg"]!);
        Assert.Contains("too long", (string)(await Refused(new { name = "A", view = "roles", filters = new { search = new string('x', 513) } }))[0]!["msg"]!);
        Assert.Contains("too large", (string)(await Refused(new { name = "A", view = "users", filters = new { usernames = new string('é', 3000) } }))[0]!["msg"]!);
        Assert.Equal("too_long", (string)(await Refused(new { name = "A", view = "roles", filters = Enumerable.Range(0, 41).ToDictionary(i => $"k{i}", _ => "v") }))[0]!["type"]!);
        // 12 000 characters are allowed for usernames only.
        Assert.Equal(HttpStatusCode.OK, (await Save(new { name = "Many users", view = "users", filters = new { usernames = new string('U', 12000) } })).Status);
        Assert.DoesNotContain(JsonNode.Parse(await _client.GetStringAsync("/api/saved-filters"))!["items"]!.AsArray(), i => (string)i!["name"]! == "A");
    }

    [Fact]
    public async Task Python_json_length_matches_json_dumps()
    {
        // json.dumps({"a": [1, "é\n"], "b": true}) == '{"a": [1, "\\u00e9\\n"], "b": true}'
        Assert.Equal("{\"a\": [1, \"\\u00e9\\n\"], \"b\": true}", V1SavedFilters.PyJson(JsonNode.Parse("{\"a\":[1,\"é\\n\"],\"b\":true}"), ensureAscii: true));
        Assert.Equal("{\"a\": \"é\"}", V1SavedFilters.PyJson(JsonNode.Parse("{\"a\":\"é\"}"), ensureAscii: false));
        await Task.CompletedTask;
    }
}
