using System.Net;
using System.Net.Http.Json;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;
using Microsoft.AspNetCore.Builder;
using AuthLens.Api;

namespace AuthLens.Tests;

/// <summary>Contract tests for the v1 API the React UI calls: shapes as in the Python v1 models, data from the C# domain, explicit 501 for every route not
/// migrated, and the same authentication boundary as /api/v1.</summary>
public sealed class V1CompatibilityTests : IAsyncLifetime
{
    private readonly string _root = Directory.CreateTempSubdirectory("saplens-v1compat-").FullName;
    private readonly string _token = HostSettings.NewToken();
    private WebApplication _app = null!;
    private HttpClient _client = null!;

    public async Task InitializeAsync()
    {
        _app = AuthLensHost.Build(new HostSettings { DataDirectory = Path.Combine(_root, "data"), Port = 0, AccessToken = _token, JsonConsoleLogging = false, PrincipalName = "tester" });
        await _app.StartAsync();
        _client = new HttpClient { BaseAddress = new Uri(_app.Urls.First()) };
        _client.DefaultRequestHeaders.Add(RequestBoundary.TokenHeader, _token);
        _client.DefaultRequestHeaders.Add("X-SAP-Lens", "1"); // what the React client always sends; it carries no authority here
    }

    public async Task DisposeAsync()
    {
        _client.Dispose();
        await _app.StopAsync();
        await _app.DisposeAsync();
        Microsoft.Data.Sqlite.SqliteConnection.ClearAllPools();
        try { Directory.Delete(_root, true); } catch (IOException) { }
    }

    private async Task<JsonElement> Get(string path, HttpStatusCode expected = HttpStatusCode.OK)
    {
        var response = await _client.GetAsync(path);
        var body = await response.Content.ReadAsStringAsync();
        Assert.True(response.StatusCode == expected, $"{path}: {response.StatusCode} {body}");
        return JsonDocument.Parse(body).RootElement;
    }

    private async Task Import(string source, string csv)
    {
        var job = await (await _client.PostAsync($"/api/v1/imports/{source}", new StringContent(csv, Encoding.UTF8, "text/csv"))).Content.ReadFromJsonAsync<JsonElement>();
        for (var i = 0; i < 200; i++)
        {
            var state = await Get($"/api/v1/jobs/{job.GetProperty("id").GetInt64()}");
            if (state.GetProperty("status").GetString() == "Completed") return;
            Assert.NotEqual("Failed", state.GetProperty("status").GetString());
            await Task.Delay(50);
        }
        throw new TimeoutException();
    }

    [Fact]
    public async Task Compatibility_routes_require_the_same_authentication_as_the_api()
    {
        using var anonymous = new HttpClient { BaseAddress = _client.BaseAddress };
        anonymous.DefaultRequestHeaders.Add("X-SAP-Lens", "1");
        foreach (var path in new[] { "/api/auth/state", "/api/configuration", "/api/roles", "/api/dashboard" })
            Assert.Equal(HttpStatusCode.Unauthorized, (await anonymous.GetAsync(path)).StatusCode);
        var problem = JsonDocument.Parse(await (await anonymous.GetAsync("/api/roles")).Content.ReadAsStringAsync()).RootElement;
        Assert.Equal("Missing or invalid access token.", problem.GetProperty("detail").GetString()); // the field the React client shows
    }

    [Fact]
    public async Task Boot_endpoints_follow_the_v1_shapes()
    {
        var state = await Get("/api/auth/state");
        Assert.Equal("shared-token", state.GetProperty("provider").GetString());
        Assert.False(state.GetProperty("setup_required").GetBoolean());

        var response = await _client.GetAsync("/api/configuration");
        var revision = response.Headers.GetValues("X-Data-Revision").Single();
        Assert.Matches(new Regex("^[a-f0-9]+\\.\\d+\\.\\d+$"), revision); // parseRevision() in frontend/src/lib/dataRevision.ts
        var configuration = JsonDocument.Parse(await response.Content.ReadAsStringAsync()).RootElement;
        var settings = configuration.GetProperty("settings");
        foreach (var key in new[] { "schema_version", "revision", "organization", "theme", "theme_colors", "module_overrides", "import_profiles", "active_import",
                     "user_import_profiles", "active_user_import", "data_csv_path", "user_csv_path", "logo_id" })
            Assert.True(settings.TryGetProperty(key, out _), $"settings.{key}");
        Assert.False(configuration.GetProperty("loading").GetBoolean());
        Assert.Equal(JsonValueKind.Null, configuration.GetProperty("error").ValueKind);
        Assert.Equal(V1Compatibility.Boot, configuration.GetProperty("instance_id").GetString());
        Assert.Equal(revision, configuration.GetProperty("data_revision").GetString());

        var registry = await Get("/api/registry/modules");
        Assert.Equal(49, registry.GetProperty("modules").GetArrayLength());
        var fi = registry.GetProperty("modules").EnumerateArray().Single(m => m.GetProperty("id").GetString() == "FI");
        Assert.Equal("Financial Accounting", fi.GetProperty("name").GetString());
        Assert.Equal("DollarSign", fi.GetProperty("icon").GetString());
        Assert.True(registry.GetProperty("icons").GetArrayLength() > 0);

        Assert.Equal("dotnet", (await Get("/api/version")).GetProperty("mode").GetString());
        Assert.Equal("server", (await Get("/api/runtime")).GetProperty("deployment_mode").GetString());
    }

    [Fact]
    public async Task Role_lookup_routes_return_the_domain_results_in_v1_shape()
    {
        await Import("roles", Csv.Roles(30));
        var revisionBefore = (await _client.GetAsync("/api/version")).Headers.GetValues("X-Data-Revision").Single();
        var modules = await Get("/api/modules");
        var module = Assert.Single(modules.EnumerateArray());
        Assert.Equal("FI", module.GetProperty("function_key").GetString());
        Assert.Equal("Financial Accounting", module.GetProperty("module_name").GetString());

        var all = await Get("/api/roles");
        Assert.Equal(30, all.GetArrayLength());
        var first = all[0];
        foreach (var key in new[] { "agr_name", "text", "function_key", "module_name", "tcode_count", "single_role_count", "matching_tcodes", "module_ambiguous", "source_modules" })
            Assert.True(first.TryGetProperty(key, out _), key);
        var v2 = await Get("/api/v1/roles?limit=100");
        Assert.Equal(v2.GetProperty("items").EnumerateArray().Select(r => r.GetProperty("agr_name").GetString()), all.EnumerateArray().Select(r => r.GetProperty("agr_name").GetString()));

        var byCode = await Get("/api/roles?tcodes=T001&tcodes=T002&transaction_mode=or");
        Assert.True(byCode.GetArrayLength() > 0);
        Assert.All(byCode.EnumerateArray(), r => Assert.True(r.GetProperty("matching_tcodes").GetArrayLength() > 0));
        Assert.Equal(1, (await Get("/api/roles?search=ROLE_0007")).GetArrayLength());
        await Get("/api/roles?transaction_mode=xor", HttpStatusCode.UnprocessableEntity);

        var detail = await Get("/api/roles/ZC:FI:ROLE_0003");
        Assert.Equal("ZC:FI:ROLE_0003", detail.GetProperty("agr_name").GetString());
        Assert.True(detail.GetProperty("single_roles").GetArrayLength() > 0);
        Assert.Equal(JsonValueKind.Array, detail.GetProperty("relationships").ValueKind);
        Assert.True(detail.GetProperty("single_roles")[0].GetProperty("tcodes")[0].TryGetProperty("assignment_sources", out _));
        Assert.Equal("CSV FUNCTION_KEY", detail.GetProperty("analysis").GetProperty("module_source").GetString());
        Assert.Contains("not found", (await Get("/api/roles/ZC:NOPE", HttpStatusCode.NotFound)).GetProperty("detail").GetString());
        Assert.Matches(new Regex("^[a-f0-9]+\\.[1-9]\\d*\\.0$"), revisionBefore); // publication counts the activated dataset
    }

    [Theory]
    [InlineData("GET", "/api/retention/policy")]
    [InlineData("GET", "/api/unknown-feature")]
    [InlineData("POST", "/api/unknown-feature/confirm")]
    [InlineData("GET", "/api/unknown-feature/status")]
    [InlineData("POST", "/api/unknown-feature/approve")]
    [InlineData("GET", "/api/sod/reports/preview")]
    [InlineData("POST", "/api/unknown-feature/create")]
    public async Task Routes_not_migrated_answer_501_with_a_detail_and_change_nothing(string method, string path)
    {
        using var request = new HttpRequestMessage(new HttpMethod(method), path);
        if (method == "POST") { request.Content = JsonContent.Create(new { }); request.Headers.Add("Origin", _client.BaseAddress!.GetLeftPart(UriPartial.Authority)); }
        var response = await _client.SendAsync(request);
        Assert.Equal((HttpStatusCode)501, response.StatusCode);
        var body = JsonDocument.Parse(await response.Content.ReadAsStringAsync()).RootElement;
        Assert.Equal("not_migrated", body.GetProperty("code").GetString());
        Assert.Contains("not available in the .NET server yet", body.GetProperty("detail").GetString());
        Assert.Equal(0, (await Get("/api/v1/datasets")).GetArrayLength());
    }
}
