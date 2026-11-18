using System.Net;
using System.Net.Http.Json;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using Microsoft.AspNetCore.Builder;
using SapLens.Api;

namespace SapLens.Tests;

/// <summary>Phase 2A contract tests: the v1 Data Sources workflow (settings saves, uploads, path selection, held imports, history, previews) on the .NET
/// server, with the v1 request and response shapes the React UI uses.</summary>
public sealed class DataSourcesTests : IAsyncLifetime
{
    private readonly string _root = Directory.CreateTempSubdirectory("saplens-sources-").FullName;
    private readonly string _token = HostSettings.NewToken();
    private WebApplication _app = null!;
    private HttpClient _client = null!;

    public Task InitializeAsync() => StartAsync(HostMode.Server);

    private async Task StartAsync(HostMode mode)
    {
        _app = SapLensHost.Build(new HostSettings { DataDirectory = Path.Combine(_root, "data"), Port = 0, AccessToken = _token, JsonConsoleLogging = false, PrincipalName = "importer", Mode = mode });
        await _app.StartAsync();
        _client = new HttpClient { BaseAddress = new Uri(_app.Urls.First()) };
        _client.DefaultRequestHeaders.Add(RequestBoundary.TokenHeader, _token);
    }

    private async Task RestartAsync(HostMode mode)
    {
        _client.Dispose();
        await _app.StopAsync();
        await _app.DisposeAsync();
        await StartAsync(mode);
    }

    public async Task DisposeAsync()
    {
        _client.Dispose();
        await _app.StopAsync();
        await _app.DisposeAsync();
        Microsoft.Data.Sqlite.SqliteConnection.ClearAllPools();
        try { Directory.Delete(_root, true); } catch (IOException) { }
    }

    private async Task<(HttpStatusCode Status, JsonNode Body)> Send(HttpRequestMessage request)
    {
        request.Headers.Add("Origin", _client.BaseAddress!.GetLeftPart(UriPartial.Authority));
        var response = await _client.SendAsync(request);
        return (response.StatusCode, JsonNode.Parse(await response.Content.ReadAsStringAsync())!);
    }

    private async Task<JsonObject> Configuration() => JsonNode.Parse(await _client.GetStringAsync("/api/configuration"))!.AsObject();
    private async Task<int> Revision() => (int)(await Configuration())["settings"]!["revision"]!;

    private Task<(HttpStatusCode, JsonNode)> Upload(string source, string csv, int revision, bool confirm = false, string fileName = "export.csv", JsonObject? profile = null)
    {
        var form = new MultipartFormDataContent
        {
            { new ByteArrayContent(Encoding.UTF8.GetBytes(csv)), "file", fileName },
            { new StringContent(revision.ToString()), "revision" },
        };
        if (confirm) form.Add(new StringContent("true"), "confirm_anomalies");
        if (profile is not null) form.Add(new StringContent(profile.ToJsonString()), "profile");
        return Send(new HttpRequestMessage(HttpMethod.Post, $"/api/server/uploads/{source}/activate") { Content = form });
    }

    private string[] StoredSources() => Directory.Exists(Path.Combine(_root, "data", "sources")) ? Directory.GetFiles(Path.Combine(_root, "data", "sources")) : [];

    [Fact]
    public async Task Settings_saves_are_revisioned_validated_and_persist_across_restart()
    {
        var settings = (await Configuration())["settings"]!.AsObject();
        Assert.Equal(0, (int)settings["revision"]!);
        settings["organization"]!["name"] = "Example Test Org";
        var (status, body) = await Send(new HttpRequestMessage(HttpMethod.Post, "/api/configuration") { Content = JsonContent.Create(settings) });
        Assert.Equal(HttpStatusCode.OK, status);
        Assert.Equal(1, (int)body["settings"]!["revision"]!);
        Assert.Equal("Example Test Org", (string)body["settings"]!["organization"]!["name"]!);

        (status, body) = await Send(new HttpRequestMessage(HttpMethod.Post, "/api/configuration") { Content = JsonContent.Create(settings) }); // still revision 0
        Assert.Equal(HttpStatusCode.Conflict, status);
        Assert.Contains("Settings changed", (string)body["detail"]!);

        var unknown = (await Configuration())["settings"]!.AsObject();
        unknown["surprise"] = 1;
        Assert.Equal((HttpStatusCode)422, (await Send(new HttpRequestMessage(HttpMethod.Post, "/api/configuration") { Content = JsonContent.Create(unknown) })).Status);
        var wrongType = (await Configuration())["settings"]!.AsObject();
        wrongType["organization"] = "text";
        Assert.Equal((HttpStatusCode)422, (await Send(new HttpRequestMessage(HttpMethod.Post, "/api/configuration") { Content = JsonContent.Create(wrongType) })).Status);
        var path = (await Configuration())["settings"]!.AsObject();
        path["data_csv_path"] = "/etc/passwd";
        (status, body) = await Send(new HttpRequestMessage(HttpMethod.Post, "/api/configuration") { Content = JsonContent.Create(path) });
        Assert.Equal(HttpStatusCode.BadRequest, status);
        Assert.Contains("Data Sources", (string)body["detail"]!);

        (status, body) = await Send(new HttpRequestMessage(HttpMethod.Post, "/api/configuration/theme") { Content = JsonContent.Create(new { theme = "light" }) });
        Assert.Equal(HttpStatusCode.OK, status);
        await RestartAsync(HostMode.Server);
        var restored = (await Configuration())["settings"]!;
        Assert.Equal("Example Test Org", (string)restored["organization"]!["name"]!);
        Assert.Equal("light", (string)restored["theme"]!);
        Assert.Equal(2, (int)restored["revision"]!);
    }

    [Fact]
    public async Task Upload_activates_the_source_records_settings_history_and_preview_in_v1_shape()
    {
        var (status, body) = await Upload("roles", Csv.Roles(30), await Revision(), fileName: "roles-export.csv");
        Assert.True(status == HttpStatusCode.OK, body.ToJsonString());
        Assert.Equal("roles", (string)body["source"]!);
        Assert.Equal(90, (int)body["records"]!);
        Assert.Equal("roles-export.csv", (string)body["file_name"]!);
        var refresh = body["refresh"]!;
        Assert.Equal("changed", (string)refresh["status"]!);
        Assert.Equal("import", (string)refresh["operation"]!);
        Assert.Matches("^[a-f0-9]{64}$", (string)refresh["id"]!);
        var result = refresh["sources"]![0]!;
        Assert.Equal("updated", (string)result["status"]!);
        Assert.Equal("Role Catalogue", (string)result["name"]!);
        Assert.Equal(90, (int)result["added"]!);
        var settings = body["settings"]!;
        Assert.Equal(1, (int)settings["revision"]!);
        Assert.StartsWith(Path.Combine(_root, "data", "sources"), (string)settings["data_csv_path"]!);
        Assert.Matches("^[a-f0-9]{64}$", (string)settings["data_lifecycle"]!["sources"]!["roles"]!["snapshot"]!);
        Assert.Equal((string)refresh["id"]!, (string)settings["data_lifecycle"]!["history"]![0]!);

        Assert.Equal(30, JsonNode.Parse(await _client.GetStringAsync("/api/roles"))!.AsArray().Count);
        var history = JsonNode.Parse(await _client.GetStringAsync("/api/data-sources/history"))!;
        Assert.Equal((string)refresh["id"]!, (string)history["items"]![0]!["id"]!);
        var preview = JsonNode.Parse(await _client.GetStringAsync("/api/data-sources/roles/preview?limit=5"))!;
        Assert.True((bool)preview["loaded"]!);
        Assert.Equal(90, (int)preview["total"]!);
        Assert.Equal(5, preview["items"]!.AsArray().Count);
        Assert.Equal("ZC:FI:ROLE_0000", (string)preview["items"]![0]!["AGR_NAME"]!);

        // Same content again: unchanged, a new private copy, the previous copy removed.
        var first = StoredSources().Single();
        (status, body) = await Upload("roles", Csv.Roles(30), await Revision());
        Assert.Equal(HttpStatusCode.OK, status);
        Assert.Equal("unchanged", (string)body["refresh"]!["status"]!);
        Assert.DoesNotContain(first, StoredSources());
        Assert.Single(StoredSources());
    }

    [Fact]
    public async Task Suspicious_upload_is_held_with_the_v1_detail_and_activates_only_with_confirmation()
    {
        Assert.Equal(HttpStatusCode.OK, (await Upload("roles", Csv.Roles(60), await Revision())).Item1);
        var (status, body) = await Upload("roles", Csv.Roles(5), await Revision());
        Assert.Equal(HttpStatusCode.Conflict, status);
        var detail = body["detail"]!;
        Assert.Equal("import_needs_confirmation", (string)detail["code"]!);
        Assert.Equal("roles", (string)detail["source"]!);
        var anomaly = detail["anomalies"]![0]!.AsObject();
        Assert.Equal("drop", (string)anomaly["rule"]!);
        Assert.False(anomaly.ContainsKey("group")); // v1 omits fields that do not apply
        Assert.Equal(180, (int)detail["old"]!["records"]!);
        Assert.Equal(60, JsonNode.Parse(await _client.GetStringAsync("/api/roles"))!.AsArray().Count); // previous data retained
        Assert.Single(StoredSources());

        (status, body) = await Upload("roles", Csv.Roles(5), await Revision(), confirm: true);
        Assert.True(status == HttpStatusCode.OK, body.ToJsonString());
        Assert.Equal(5, JsonNode.Parse(await _client.GetStringAsync("/api/roles"))!.AsArray().Count);
        var confirmation = body["settings"]!["data_lifecycle"]!["confirmations"]![0]!;
        Assert.Equal("importer", (string)confirmation["actor"]!);
        Assert.Equal(180, (int)confirmation["old_records"]!);
        Assert.Equal(15, (int)confirmation["new_records"]!);
    }

    [Fact]
    public async Task An_empty_or_header_only_file_never_replaces_or_removes_an_active_snapshot()
    {
        Assert.Equal(HttpStatusCode.OK, (await Upload("roles", Csv.Roles(60), await Revision())).Item1);
        var header = Csv.RolesHeader + "\n";
        foreach (var (content, confirm) in new[] { (header, false), (header, true), ("", false), ("\n\n", true), (header + "\n\n", true) })
        {
            var (status, body) = await Upload("roles", content, await Revision(), confirm: confirm);
            Assert.False(status == HttpStatusCode.OK, $"a file without records was accepted (confirm {confirm}): {body.ToJsonString()}");
            Assert.Equal(60, JsonNode.Parse(await _client.GetStringAsync("/api/roles"))!.AsArray().Count);   // previous data retained
            Assert.Single(StoredSources());
        }
        var (refused, detail) = await Upload("roles", header, await Revision(), confirm: true);
        Assert.Equal(HttpStatusCode.BadRequest, refused);
        Assert.Contains("no usable records", detail.ToJsonString());
        Assert.Contains("Clear source data", detail.ToJsonString());

        // The same for the other CSV sources, with existing data in place.
        Assert.Equal(HttpStatusCode.OK, (await Upload("users", Csv.Users(Csv.Assignments(30, 2, 60)), await Revision())).Item1);
        Assert.Equal(HttpStatusCode.OK, (await Upload("sod", Csv.Sod(), await Revision())).Item1);
        foreach (var (source, sourceHeader) in new[] { ("users", Csv.UsersHeader), ("sod", Csv.SodHeader) })
        {
            var (status, body) = await Upload(source, sourceHeader + "\n", await Revision(), confirm: true);
            Assert.True(status == HttpStatusCode.BadRequest, $"{source}: {body.ToJsonString()}");
            Assert.Contains("no usable records", body.ToJsonString());
        }
        Assert.Equal(30, JsonNode.Parse(await _client.GetStringAsync("/api/access/users?show_expired=true"))!["total"]!.GetValue<int>());
    }

    [Fact]
    public async Task Invalid_stale_or_unsupported_selections_are_refused_and_change_nothing()
    {
        var (status, body) = await Upload("roles", "FUNCTION_KEY;TEXT\nFI;x\n", await Revision());
        Assert.Equal(HttpStatusCode.BadRequest, status);
        Assert.Contains("AGR_NAME", (string)body["detail"]!);
        Assert.Empty(StoredSources());

        (status, body) = await Upload("roles", Csv.Roles(3), 41);
        Assert.Equal(HttpStatusCode.Conflict, status);
        Assert.Contains("Settings changed", (string)body["detail"]!);

        (status, body) = await Send(new HttpRequestMessage(HttpMethod.Post, "/api/data-sources/roles/select")
        { Content = JsonContent.Create(new { path = "/tmp/anything.csv", revision = 0, mode = "static" }) });
        Assert.Equal(HttpStatusCode.BadRequest, status);
        Assert.Contains("upload", (string)body["detail"]!);

        (status, body) = await Upload("employees", "x", await Revision()); // an invalid directory is refused before it can replace anything
        Assert.Equal(HttpStatusCode.BadRequest, status);
        Assert.Contains("16 documented headers", (string)body["detail"]!);
        Assert.Equal(0, await Revision());
        Assert.Empty(JsonNode.Parse(await _client.GetStringAsync("/api/data-sources/history"))!["items"]!.AsArray());
    }

    [Fact]
    public async Task Desktop_selects_local_paths_and_custom_profiles_are_stored_with_a_new_version()
    {
        await RestartAsync(HostMode.Desktop);
        var file = Path.Combine(_root, "users-export.csv");
        await File.WriteAllTextAsync(file, Csv.Users(Csv.Assignments(10, 2, 10)).Replace("USERNAME;", "SAP_USER;"));
        var profile = new JsonObject { ["id"] = "default", ["name"] = "Standard SAP user CSV", ["version"] = 1, ["mapping"] = new JsonObject { ["USERNAME"] = "SAP_USER" },
            ["delimiter"] = ";", ["encoding"] = "auto" };
        var (status, body) = await Send(new HttpRequestMessage(HttpMethod.Post, "/api/data-sources/users/select")
        { Content = JsonContent.Create(new JsonObject { ["path"] = file, ["revision"] = await Revision(), ["mode"] = "dynamic", ["profile"] = profile }) });
        Assert.True(status == HttpStatusCode.OK, body.ToJsonString());
        Assert.Equal(20, (int)body["records"]!);
        var settings = body["settings"]!;
        Assert.Equal(file, (string)settings["user_csv_path"]!);
        Assert.Equal("dynamic", (string)settings["source_modes"]!["users"]!);
        var stored = settings["user_import_profiles"]!.AsArray().Single(p => (string)p!["id"]! == "default")!;
        Assert.Equal("SAP_USER", (string)stored["mapping"]!["USERNAME"]!);
        Assert.Equal(2, (int)stored["version"]!);
        Assert.True(File.Exists(file)); // the user's own file is never removed

        (status, body) = await Send(new HttpRequestMessage(HttpMethod.Post, "/api/data-sources/users/select")
        { Content = JsonContent.Create(new { path = Path.Combine(_root, "missing.csv"), revision = await Revision(), mode = "static" }) });
        Assert.Equal(HttpStatusCode.BadRequest, status);
        Assert.Contains("not found", (string)body["detail"]!);
    }
}
