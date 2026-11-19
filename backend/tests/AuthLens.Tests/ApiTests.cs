using System.Net;
using System.Net.Http.Json;
using System.Text;
using System.Text.Json;
using Microsoft.AspNetCore.Builder;
using AuthLens.Api;

namespace AuthLens.Tests;

/// <summary>The real Kestrel host on an OS-assigned loopback port, as Desktop and Server run it.</summary>
public sealed class ApiTests : IAsyncLifetime
{
    private readonly string _root = Directory.CreateTempSubdirectory("saplens-api-").FullName;
    private readonly string _token = HostSettings.NewToken();
    private WebApplication _app = null!;
    private HttpClient _client = null!;
    private string _last = "";

    public async Task InitializeAsync()
    {
        _app = AuthLensHost.Build(new HostSettings
        {
            DataDirectory = Path.Combine(_root, "data"), Port = 0, AccessToken = _token,
            JsonConsoleLogging = false, PrincipalName = "tester",
        });
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

    private async Task<JsonElement> Json(HttpResponseMessage response, HttpStatusCode expected)
    {
        var body = await response.Content.ReadAsStringAsync();
        Assert.True(expected == response.StatusCode, $"{response.StatusCode}: {body}");
        return JsonDocument.Parse(body).RootElement;
    }

    private async Task<JsonElement> ImportAsync(string source, string csv)
    {
        var accepted = await Json(await _client.PostAsync($"/api/v1/imports/{source}", new StringContent(csv, Encoding.UTF8, "text/csv")), HttpStatusCode.Accepted);
        var id = accepted.GetProperty("id").GetInt64();
        for (var i = 0; i < 200; i++)
        {
            var job = await Json(await _client.GetAsync($"/api/v1/jobs/{id}"), HttpStatusCode.OK);
            if (job.GetProperty("status").GetString() is "Completed" or "Failed" or "Cancelled") { _last = job.ToString(); return job; }
            await Task.Delay(50);
        }
        throw new TimeoutException("import job did not finish");
    }

    [Fact]
    public async Task Health_is_open_and_api_requires_the_token()
    {
        using var anonymous = new HttpClient { BaseAddress = _client.BaseAddress };
        Assert.Equal(HttpStatusCode.OK, (await anonymous.GetAsync("/health/live")).StatusCode);
        Assert.Equal(HttpStatusCode.OK, (await anonymous.GetAsync("/health/ready")).StatusCode);
        Assert.Equal(HttpStatusCode.Unauthorized, (await anonymous.GetAsync("/api/v1/roles")).StatusCode);
        anonymous.DefaultRequestHeaders.Add(RequestBoundary.TokenHeader, _token + "x");
        Assert.Equal(HttpStatusCode.Unauthorized, (await anonymous.GetAsync("/api/v1/roles")).StatusCode);
    }

    [Fact]
    public async Task Foreign_host_header_and_cross_origin_writes_are_refused()
    {
        using var rebinding = new HttpRequestMessage(HttpMethod.Get, "/api/v1/roles");
        rebinding.Headers.Host = "attacker.example";
        Assert.Equal((HttpStatusCode)421, (await _client.SendAsync(rebinding)).StatusCode);
        using var crossOrigin = new HttpRequestMessage(HttpMethod.Post, "/api/v1/jobs/999999/cancel");
        crossOrigin.Headers.Add("Origin", "http://evil.example");
        Assert.Equal(HttpStatusCode.Forbidden, (await _client.SendAsync(crossOrigin)).StatusCode);
    }

    [Fact]
    public void Non_loopback_bind_and_short_tokens_are_refused()
    {
        Assert.Throws<InvalidOperationException>(() => AuthLensHost.Build(new HostSettings { DataDirectory = Path.Combine(_root, "x"), ListenAddress = System.Net.IPAddress.Any, AccessToken = _token }));
        Assert.Throws<InvalidOperationException>(() => AuthLensHost.Build(new HostSettings { DataDirectory = Path.Combine(_root, "x"), Port = 0, AccessToken = "short" }));
    }

    [Fact]
    public async Task Problem_details_carry_the_correlation_id()
    {
        using var request = new HttpRequestMessage(HttpMethod.Get, "/api/v1/roles?limit=500");
        request.Headers.Add(RequestBoundary.CorrelationHeader, "test-correlation-1");
        var response = await _client.SendAsync(request);
        var problem = await Json(response, HttpStatusCode.BadRequest);
        Assert.Equal("application/problem+json", response.Content.Headers.ContentType!.MediaType);
        Assert.Equal("test-correlation-1", problem.GetProperty("correlation_id").GetString());
        Assert.Equal("test-correlation-1", response.Headers.GetValues(RequestBoundary.CorrelationHeader).Single());
        await Json(await _client.GetAsync("/api/v1/jobs/999"), HttpStatusCode.NotFound);
        await Json(await _client.GetAsync("/api/v1/users/compare?left=A&right=B"), HttpStatusCode.NotFound);
    }

    [Fact]
    public async Task Import_lookup_pagination_comparison_sod_and_review_flow()
    {
        Assert.Equal("Completed", (await ImportAsync("roles", Csv.Roles(120))).GetProperty("status").GetString());
        Assert.Equal("Completed", (await ImportAsync("users", Csv.Users(Csv.Assignments(30, 2, 120)))).GetProperty("status").GetString());
        Assert.True((await ImportAsync("sod", Csv.Sod())).GetProperty("status").GetString() == "Completed", _last);

        var page = await Json(await _client.GetAsync("/api/v1/roles?offset=100&limit=50&sort=agr_name"), HttpStatusCode.OK);
        Assert.Equal(120, page.GetProperty("total").GetInt32());
        Assert.Equal(20, page.GetProperty("items").GetArrayLength());
        Assert.Equal("ZC:FI:ROLE_0100", page.GetProperty("items")[0].GetProperty("agr_name").GetString());
        var tcodes = await Json(await _client.GetAsync("/api/v1/roles?tcode=T001&tcode=T002&transaction_mode=or&limit=100"), HttpStatusCode.OK);
        Assert.True(tcodes.GetProperty("total").GetInt32() > 0);

        var users = await Json(await _client.GetAsync("/api/v1/users?role=ZC:FI:ROLE_0001&limit=10"), HttpStatusCode.OK);
        Assert.Equal(2, users.GetProperty("total").GetInt32());
        var compare = await Json(await _client.GetAsync("/api/v1/users/compare?left=USER0000&right=USER0001&kind=roles&validity=all"), HttpStatusCode.OK);
        Assert.Equal(3, compare.GetProperty("page").GetProperty("total").GetInt32());
        var sod = await Json(await _client.GetAsync("/api/v1/sod/findings?kind=users&limit=5"), HttpStatusCode.OK);
        Assert.Equal("sod-two-sided-v1", sod.GetProperty("evaluation_policy").GetString());

        var review = await Json(await _client.PostAsJsonAsync("/api/v1/reviews", new { subject_type = "assignment", subject_key = "USER0001\u001fZC:FI:ROLE_0001", decision = "approved", comment = "ok" }), HttpStatusCode.Created);
        Assert.Equal("tester", review.GetProperty("reviewer").GetString());
        var status = await Json(await _client.GetAsync("/api/v1/reviews/assignment?user=user0001&role=ZC:FI:ROLE_0001"), HttpStatusCode.OK);
        Assert.True(status.GetProperty("decision_applies").GetBoolean());
        var integrity = await Json(await _client.GetAsync("/api/v1/admin/integrity"), HttpStatusCode.OK);
        Assert.True(integrity.GetProperty("database_ok").GetBoolean());
        Assert.True(integrity.GetProperty("review_chain_ok").GetBoolean());
    }

    [Fact]
    public async Task Held_import_is_confirmed_through_the_api()
    {
        await ImportAsync("roles", Csv.Roles(60));
        var held = await ImportAsync("roles", Csv.Roles(5));
        Assert.True(held.GetProperty("status").GetString() == "Completed", _last);
        var result = held.GetProperty("result");
        Assert.Equal("Held", result.GetProperty("status").GetString());
        var id = result.GetProperty("dataset_id").GetInt64();
        var confirmed = await Json(await _client.PostAsync($"/api/v1/datasets/{id}/confirm", null), HttpStatusCode.OK);
        Assert.Equal("Active", confirmed.GetProperty("status").GetString());
        Assert.Equal("tester", confirmed.GetProperty("confirmed_by").GetString());
        await Json(await _client.PostAsync($"/api/v1/datasets/{id}/confirm", null), HttpStatusCode.Conflict);
    }

    [Fact]
    public async Task Malformed_import_fails_with_its_message_and_upload_is_removed()
    {
        var job = await ImportAsync("roles", "FUNCTION_KEY;TEXT\nFI;x\n");
        Assert.Equal("Failed", job.GetProperty("status").GetString());
        Assert.Contains("AGR_NAME", job.GetProperty("error").GetString());
        Assert.Empty(Directory.GetFiles(Path.Combine(_root, "data", "uploads")));
    }

    [Fact]
    public async Task OpenApi_document_is_served_and_unknown_files_and_v1_routes_are_404()
    {
        var doc = await Json(await _client.GetAsync("/openapi/v1.json"), HttpStatusCode.OK);
        Assert.True(doc.GetProperty("paths").TryGetProperty("/api/v1/roles", out _));
        Assert.Equal(HttpStatusCode.NotFound, (await _client.GetAsync("/api/v1/unknown")).StatusCode);
        Assert.Equal(HttpStatusCode.NotFound, (await _client.GetAsync("/some/unknown/file.txt")).StatusCode);
    }

    [Theory]
    [InlineData("/theme.js", "text/javascript")]
    [InlineData("/sap-lens.png", "image/png")]
    [InlineData("/login.html", "text/html")]
    [InlineData("/login.css", "text/css")]
    public async Task Static_ui_assets_are_served_without_credentials_and_with_security_headers(string path, string mediaType)
    {
        using var anonymous = new HttpClient { BaseAddress = _client.BaseAddress };
        var response = await anonymous.GetAsync(path);
        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        Assert.Equal(mediaType, response.Content.Headers.ContentType!.MediaType);
        Assert.Equal(RequestBoundary.ContentSecurityPolicy, response.Headers.GetValues("Content-Security-Policy").Single());
        Assert.Equal("same-origin", response.Headers.GetValues("Referrer-Policy").Single()); // no-referrer would make browsers send Origin: null on sign-in
        Assert.Equal("DENY", response.Headers.GetValues("X-Frame-Options").Single());
        Assert.DoesNotContain(_token, await response.Content.ReadAsStringAsync());
    }

    [Fact]
    public async Task Server_sends_anonymous_browsers_to_sign_in_and_serves_the_react_application_when_authenticated()
    {
        using var anonymous = new HttpClient(new HttpClientHandler { AllowAutoRedirect = false }) { BaseAddress = _client.BaseAddress };
        foreach (var path in new[] { "/", "/index.html" })
        {
            var redirect = await anonymous.GetAsync(path);
            Assert.Equal(HttpStatusCode.Redirect, redirect.StatusCode);
            Assert.Equal("/login.html", redirect.Headers.Location!.OriginalString);
        }
        var page = await _client.GetStringAsync("/");
        Assert.Contains(UiAssets.Marker, page);
        Assert.Contains("<title>SAP Lens</title>", page);
        Assert.DoesNotContain(_token, page);
    }

    [Fact]
    public async Task React_entry_point_references_only_local_assets_that_exist()
    {
        var html = await _client.GetStringAsync("/");
        var references = System.Text.RegularExpressions.Regex.Matches(html, "(?:src|href)=\"([^\"]+)\"").Select(m => m.Groups[1].Value).Distinct().ToList();
        Assert.Contains("/theme.js", references);
        Assert.Contains(references, r => r.StartsWith("/assets/", StringComparison.Ordinal) && r.EndsWith(".js", StringComparison.Ordinal));
        Assert.All(references, r => Assert.StartsWith("/", r));
        using var anonymous = new HttpClient { BaseAddress = _client.BaseAddress };
        foreach (var reference in references) Assert.Equal(HttpStatusCode.OK, (await anonymous.GetAsync(reference)).StatusCode);
    }

    [Fact]
    public async Task Session_endpoint_reports_the_principal_and_requires_authentication()
    {
        var session = await Json(await _client.GetAsync("/api/v1/session"), HttpStatusCode.OK);
        Assert.Equal("tester", session.GetProperty("principal").GetString());
        using var anonymous = new HttpClient { BaseAddress = _client.BaseAddress };
        Assert.Equal(HttpStatusCode.Unauthorized, (await anonymous.GetAsync("/api/v1/session")).StatusCode);
    }
}
