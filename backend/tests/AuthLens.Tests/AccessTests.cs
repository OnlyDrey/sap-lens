using System.Net;
using System.Text;
using System.Text.Json.Nodes;
using Microsoft.AspNetCore.Builder;
using AuthLens.Api;

namespace AuthLens.Tests;

/// <summary>Phase 2B contract tests: v1 User Access and Compare Users routes served from the C# domain (equivalence-tested separately against Python).</summary>
public sealed class AccessTests : IAsyncLifetime
{
    private readonly string _root = Directory.CreateTempSubdirectory("saplens-access-").FullName;
    private readonly string _token = HostSettings.NewToken();
    private WebApplication _app = null!;
    private HttpClient _client = null!;

    public async Task InitializeAsync()
    {
        _app = AuthLensHost.Build(new HostSettings { DataDirectory = Path.Combine(_root, "data"), Port = 0, AccessToken = _token, JsonConsoleLogging = false });
        await _app.StartAsync();
        _client = new HttpClient { BaseAddress = new Uri(_app.Urls.First()) };
        _client.DefaultRequestHeaders.Add(RequestBoundary.TokenHeader, _token);
        foreach (var (source, csv) in new[] { ("roles", Csv.Roles(40)), ("users", Csv.Users(Csv.Assignments(25, 3, 40))) })
        {
            var job = JsonNode.Parse(await (await _client.PostAsync($"/api/v1/imports/{source}", new StringContent(csv, Encoding.UTF8, "text/csv"))).Content.ReadAsStringAsync())!;
            for (var i = 0; i < 200 && (string)JsonNode.Parse(await _client.GetStringAsync($"/api/v1/jobs/{(long)job["id"]!}"))!["status"]! != "Completed"; i++) await Task.Delay(50);
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

    private async Task<(HttpStatusCode Status, JsonNode Body)> Get(string path)
    {
        var response = await _client.GetAsync(path);
        return (response.StatusCode, JsonNode.Parse(await response.Content.ReadAsStringAsync())!);
    }

    [Fact]
    public async Task Disabling_user_role_mapping_answers_409_on_every_access_endpoint_and_keeps_the_data()
    {
        async Task SetMapping(bool enabled)
        {
            var settings = JsonNode.Parse(await _client.GetStringAsync("/api/configuration"))!["settings"]!.AsObject();
            settings["features"]!["user_role_mapping"] = enabled;
            var saved = await _client.PostAsync("/api/configuration", new StringContent(settings.ToJsonString(), Encoding.UTF8, "application/json"));
            Assert.True(saved.IsSuccessStatusCode, await saved.Content.ReadAsStringAsync());
        }
        await SetMapping(false);
        foreach (var path in new[] { "/api/access/users", "/api/access/users/user0001", "/api/access/exports/users", "/api/access/release-roles", "/api/access/users-selection" })
            Assert.Equal(HttpStatusCode.Conflict, (await Get(path)).Status);
        Assert.Equal(HttpStatusCode.OK, (await Get("/api/roles")).Status);                                  // Role Lookup stays independent
        await SetMapping(true);
        Assert.Equal(HttpStatusCode.OK, (await Get("/api/access/users?show_expired=true")).Status);        // retained data serves again, no reimport
    }

    [Fact]
    public async Task User_list_follows_the_v1_page_shape_filters_and_navigation()
    {
        var (status, page) = await Get("/api/access/users?limit=10&show_expired=true");
        Assert.Equal(HttpStatusCode.OK, status);
        Assert.Equal(25, (int)page["total"]!);
        Assert.Equal(10, page["items"]!.AsArray().Count);
        Assert.True((bool)page["loaded"]!);
        Assert.True((bool)page["catalogue_loaded"]!);
        Assert.Equal(["GRP_FIN"], page["groups"]!.AsArray().Select(g => (string)g!));
        Assert.Equal(75, (int)page["export_assignments"]!);
        var row = page["items"]![0]!;
        foreach (var key in new[] { "username", "user_key", "groups", "first_name", "last_name", "email", "account_status", "lock_status", "relevant_roles", "directory_status", "functional_groups", "classification_status" })
            Assert.True(row.AsObject().ContainsKey(key), key);
        Assert.Equal("unavailable", (string)row["directory_status"]!);
        Assert.Equal("USER0000", (string)row["username"]!);

        Assert.Equal(3, (int)(await Get("/api/access/users?roles=ZC:FI:ROLE_0002&show_expired=true")).Body["total"]!);
        Assert.Equal(1, (int)(await Get("/api/access/users?search=USER0007&show_expired=true")).Body["total"]!);
        Assert.Equal("USER0024", (string)(await Get("/api/access/users?descending=true&limit=1&show_expired=true")).Body["items"]![0]!["username"]!);
        var navigation = (await Get("/api/access/users?anchor=user0003&show_expired=true")).Body["navigation"]!;
        Assert.Equal(3, (int)navigation["index"]!);
        Assert.Equal("USER0002", (string)navigation["previous"]!);
        Assert.Equal("USER0004", (string)navigation["next"]!);
        Assert.Equal((HttpStatusCode)422, (await Get("/api/access/users?sort=password")).Status);
        Assert.Equal((HttpStatusCode)422, (await Get("/api/access/users?limit=101")).Status);
    }

    [Fact]
    public async Task User_detail_lists_assignments_in_the_v1_shape()
    {
        var (status, detail) = await Get("/api/access/users/user0001?show_expired=true");
        Assert.Equal(HttpStatusCode.OK, status);
        Assert.Equal("USER0001", (string)detail["username"]!);
        Assert.Equal(3, (int)detail["total"]!);
        Assert.Equal(3, (int)detail["retained_assignments"]!);
        Assert.True((bool)detail["mapping_available"]!);
        var assignment = detail["items"]![0]!;
        Assert.Equal("ZC:FI:ROLE_0001", (string)assignment["role_name"]!);
        Assert.Equal("exact", (string)assignment["match_status"]!);
        Assert.Equal("Role 1", (string)assignment["role_description"]!);
        Assert.Equal(3, (int)assignment["tcode_count"]!);
        Assert.Equal("business", (string)assignment["scope"]!);
        Assert.Single(detail["accounts"]!.AsArray());
        var filtered = (await Get($"/api/access/users/USER0001?show_expired=true&tcodes={Uri.EscapeDataString((string)assignment["tcodes"]![0]!)}")).Body;
        Assert.True((int)filtered["total"]! >= 1);
        Assert.NotEmpty(filtered["items"]![0]!["transaction_roles"]!.AsArray());
        Assert.Contains("not found", (string)(await Get("/api/access/users/NOBODY")).Body["detail"]!);
    }

    [Fact]
    public async Task Comparison_returns_rows_summary_users_and_evidence_in_the_v1_shape()
    {
        var (status, result) = await Get("/api/user-comparison?user_a=USER0001&user_b=user0002&validity=all");
        Assert.Equal(HttpStatusCode.OK, status);
        Assert.Equal(4, (int)result["total"]!); // roles 1,2,3 and 2,3,4
        Assert.Equal(2, (int)result["summary"]!["roles"]!["shared"]!);
        Assert.Equal(1, (int)result["summary"]!["roles"]!["a"]!);
        Assert.Equal(["USER0001", "USER0002"], result["users"]!.AsArray().Select(u => (string)u!["username"]!));
        Assert.False((bool)result["users"]![0]!["identity_ambiguous"]!);
        var first = result["items"]![0]!;
        Assert.Equal("ZC:FI:ROLE_0001", (string)first["identifier"]!);
        Assert.Equal("a", (string)first["difference"]!);
        Assert.Equal(1, (int)first["a_total"]!);
        Assert.Equal(["Financial Accounting"], result["areas"]!.AsArray().Select(a => (string)a!));

        var shared = (await Get("/api/user-comparison?user_a=USER0001&user_b=USER0002&validity=all&difference=shared")).Body;
        Assert.Equal(2, (int)shared["total"]!);
        var transactions = (await Get("/api/user-comparison?user_a=USER0001&user_b=USER0002&validity=all&kind=transactions")).Body;
        Assert.True((int)transactions["total"]! > 0);
        Assert.True(transactions["assignment_evidence"]!["a"]!.AsObject().Count > 0);

        var evidence = (await Get("/api/user-comparison/evidence?user_a=USER0001&user_b=USER0002&validity=all&identifier=zc:fi:role_0001&side=a")).Body;
        Assert.Equal(1, (int)evidence["total"]!);
        Assert.Equal("USER0001", (string)evidence["items"]![0]!["username"]!);

        var same = await Get("/api/user-comparison?user_a=USER0001&user_b=user0001");
        Assert.Equal(HttpStatusCode.BadRequest, same.Status);
        Assert.Contains("two different", (string)same.Body["detail"]!);
        Assert.Equal(HttpStatusCode.NotFound, (await Get("/api/user-comparison?user_a=USER0001&user_b=NOBODY")).Status);
        Assert.Equal((HttpStatusCode)422, (await Get("/api/user-comparison?user_a=USER0001&user_b=USER0002&kind=packages")).Status);
    }
}
