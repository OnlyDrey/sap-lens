using System.Net;
using System.Net.Http.Json;
using System.Text.Json.Nodes;
using Microsoft.AspNetCore.Builder;
using SapLens.Api;

namespace SapLens.Tests;

/// <summary>MIG-002: a settings save that changes a source's import format imports that source again before the settings are kept (v1 perform_apply);
/// a format that cannot read the file keeps the previous data and settings; an enabled schedule must satisfy its run checks.</summary>
public sealed class SettingsReimportTests : IAsyncLifetime
{
    private readonly string _root = Directory.CreateTempSubdirectory("saplens-reimport-").FullName;
    private readonly string _token = HostSettings.NewToken();
    private WebApplication _app = null!;
    private HttpClient _client = null!;

    public async Task InitializeAsync()
    {
        _app = SapLensHost.Build(new HostSettings { DataDirectory = Path.Combine(_root, "data"), Port = 0, AccessToken = _token, JsonConsoleLogging = false, PrincipalName = "operator", Mode = HostMode.Desktop });
        await _app.StartAsync();
        _client = new HttpClient { BaseAddress = new Uri(_app.Urls.First()) };
        _client.DefaultRequestHeaders.Add(RequestBoundary.TokenHeader, _token);
        _client.DefaultRequestHeaders.Add("Origin", _client.BaseAddress.GetLeftPart(UriPartial.Authority));
    }

    public async Task DisposeAsync()
    {
        _client.Dispose();
        await _app.StopAsync();
        await _app.DisposeAsync();
        Microsoft.Data.Sqlite.SqliteConnection.ClearAllPools();
        try { Directory.Delete(_root, true); } catch (IOException) { }
    }

    private async Task<JsonObject> Settings() => JsonNode.Parse(await _client.GetStringAsync("/api/configuration"))!["settings"]!.AsObject();

    [Fact]
    public async Task Changing_the_active_import_format_reimports_the_source_and_keeps_data_when_it_fails()
    {
        // Roles with a renamed role column: the default format cannot read it, a mapping can.
        var file = Path.Combine(_root, "roles.csv");
        File.WriteAllText(file, "FUNCTION_KEY;AGR_NAME;TEXT;TCODE\n" + string.Join('\n', Enumerable.Range(0, 30).Select(i => $"FI;ZC:FI:ROLE_{i:000};Role {i};T{i:000}")) + "\n");
        var revision = (int)(await Settings())["revision"]!;
        Assert.True((await _client.PostAsJsonAsync("/api/data-sources/roles/select", new { path = file, revision, mode = "dynamic" })).IsSuccessStatusCode);
        File.WriteAllText(file, "FUNCTION_KEY;ROLLE;TEXT;TCODE\n" + string.Join('\n', Enumerable.Range(0, 30).Select(i => $"FI;ZC:FI:ROLE_{i:000};Rolle {i};T{i:000}")) + "\n");

        // A format that does not fit the file: refused, data and settings unchanged.
        var settings = await Settings();
        settings["import_profiles"]!.AsArray().Add(new JsonObject { ["id"] = "broken", ["name"] = "Broken", ["version"] = 1, ["mapping"] = new JsonObject { ["AGR_NAME"] = "MISSING" }, ["delimiter"] = ";", ["encoding"] = "auto" });
        settings["active_import"] = "broken";
        var refused = await _client.PostAsJsonAsync("/api/configuration", settings);
        Assert.Equal(HttpStatusCode.BadRequest, refused.StatusCode);
        var detail = JsonNode.Parse(await refused.Content.ReadAsStringAsync())!["detail"]!;
        Assert.Equal(("roles", "headers"), ((string)detail["source"]!, (string)detail["category"]!));
        Assert.Equal("default", (string)(await Settings())["active_import"]!);
        Assert.Contains("\"Role 1\"", await _client.GetStringAsync("/api/roles/ZC:FI:ROLE_001"));       // previous data retained

        // The right mapping: the source is imported again with it, and the settings are kept with the format's version.
        settings = await Settings();
        settings["import_profiles"]!.AsArray().Add(new JsonObject { ["id"] = "nordic", ["name"] = "Nordic", ["version"] = 1, ["mapping"] = new JsonObject { ["AGR_NAME"] = "ROLLE" }, ["delimiter"] = ";", ["encoding"] = "auto" });
        settings["active_import"] = "nordic";
        var saved = await _client.PostAsJsonAsync("/api/configuration", settings);
        Assert.True(saved.IsSuccessStatusCode, await saved.Content.ReadAsStringAsync());
        Assert.Equal("nordic", (string)(await Settings())["active_import"]!);
        var history = JsonNode.Parse(await _client.GetStringAsync("/api/data-sources/history"))!["items"]![0]!;
        Assert.Equal(("import", "changed"), ((string)history["operation"]!, (string)history["status"]!));
        var role = JsonNode.Parse(await _client.GetStringAsync("/api/roles/ZC:FI:ROLE_001"))!;
        Assert.Contains("Rolle 1", role.ToJsonString());

        // Editing the active format again raises its version.
        settings = await Settings();
        settings["import_profiles"]!.AsArray().OfType<JsonObject>().Single(p => (string?)p["id"] == "nordic")["delimiter"] = "auto";
        Assert.True((await _client.PostAsJsonAsync("/api/configuration", settings)).IsSuccessStatusCode);
        Assert.Equal(2, (int)(await Settings())["import_profiles"]!.AsArray().OfType<JsonObject>().Single(p => (string?)p["id"] == "nordic")["version"]!);
    }

    [Fact]
    public async Task An_enabled_schedule_must_satisfy_its_run_checks_and_a_stale_revision_is_refused()
    {
        var settings = await Settings();
        settings["refresh_schedule"] = new JsonObject { ["enabled"] = true, ["mode"] = "cron", ["cron"] = "*/2 * * * *", ["time"] = "06:00", ["timezone"] = "UTC" };
        var response = await _client.PostAsJsonAsync("/api/configuration", settings);
        Assert.Equal(HttpStatusCode.UnprocessableEntity, response.StatusCode);
        Assert.Contains("at least 5 minutes apart", await response.Content.ReadAsStringAsync());
        settings["refresh_schedule"]!["enabled"] = false;                                    // a disabled draft is only parsed, as v1
        Assert.Equal(HttpStatusCode.OK, (await _client.PostAsJsonAsync("/api/configuration", settings)).StatusCode);
        Assert.Equal(HttpStatusCode.Conflict, (await _client.PostAsJsonAsync("/api/configuration", settings)).StatusCode);
    }
}
