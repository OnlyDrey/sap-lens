using System.Net;
using System.Net.Http.Json;
using System.Text;
using System.Text.Json.Nodes;
using Microsoft.AspNetCore.Builder;
using AuthLens.Api;

namespace AuthLens.Tests;

/// <summary>POST /api/configuration/export, /import and /reset (configuration_routes.py, portable_config.py) and the Desktop reviewer profile
/// (review_identity.py). Fixtures/configuration/expected.python.json was written by tools/configuration_reference.py from Python v1.</summary>
public sealed class ConfigurationTests : IAsyncLifetime
{
    private readonly string _root = Directory.CreateTempSubdirectory("saplens-config-").FullName;
    private readonly string _token = HostSettings.NewToken();
    private WebApplication _app = null!;
    private HttpClient _client = null!;

    public Task InitializeAsync() => StartAsync(HostMode.Server);

    private async Task StartAsync(HostMode mode)
    {
        _app = AuthLensHost.Build(new HostSettings { DataDirectory = Path.Combine(_root, "data"), Port = 0, AccessToken = _token, JsonConsoleLogging = false, Mode = mode });
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

    private async Task<(HttpStatusCode Status, JsonNode? Body)> Post(string path, object? body = null)
    {
        var request = new HttpRequestMessage(HttpMethod.Post, path) { Content = body is null ? null : JsonContent.Create(body) };
        request.Headers.Add("Origin", _client.BaseAddress!.GetLeftPart(UriPartial.Authority));
        var response = await _client.SendAsync(request);
        var text = await response.Content.ReadAsStringAsync();
        return (response.StatusCode, text.Length == 0 ? null : JsonNode.Parse(text));
    }

    private async Task<JsonObject> Settings() => JsonNode.Parse(await _client.GetStringAsync("/api/configuration"))!["settings"]!.AsObject();

    private static JsonObject Expected() =>
        JsonNode.Parse(ProductRename.Apply(File.ReadAllText(Path.Combine(AppContext.BaseDirectory, "Fixtures", "configuration", "expected.python.json"))))!.AsObject();

    private async Task SaveOrganization()
    {
        var settings = await Settings();
        settings["theme"] = "dark";
        settings["organization"]!["name"] = "Example Org";
        settings["organization"]!["description"] = "Synthetic organization";
        var (status, body) = await Post("/api/configuration", settings);
        Assert.True(status == HttpStatusCode.OK, body?.ToJsonString());
    }

    private static JsonObject WithoutRevisionFields(JsonNode node)
    {
        var copy = node.DeepClone().AsObject();
        copy["settings"]!.AsObject().Remove("schema_version");
        return copy;
    }

    [Fact]
    public async Task Export_equals_python_v1_redacted_and_private()
    {
        await SaveOrganization();
        var expected = Expected();
        foreach (var (query, key) in new[] { ("", "redacted"), ("?include_private=false", "redacted"), ("?include_private=true", "private") })
        {
            var (status, body) = await Post("/api/configuration/export" + query);
            Assert.Equal(HttpStatusCode.OK, status);
            Assert.True(JsonNode.DeepEquals(WithoutRevisionFields(expected[key]!), WithoutRevisionFields(body!)), $"{key}: {body!.ToJsonString()}");
        }
        var redacted = (await Post("/api/configuration/export")).Body!;
        Assert.DoesNotContain("Example Org", redacted.ToJsonString());
        Assert.Equal(HttpStatusCode.UnprocessableEntity, (await Post("/api/configuration/export?include_private=maybe")).Status);
    }

    [Fact]
    public async Task Import_applies_a_package_keeps_local_state_and_refuses_paths_history_and_logos()
    {
        await SaveOrganization();
        var package = (await Post("/api/configuration/export?include_private=true")).Body!.AsObject();
        // A fresh server receives the package: organization and theme arrive, revision and local data state are its own.
        await RestartAsync(HostMode.Server);
        var before = await Settings();
        var (status, body) = await Post("/api/configuration/import", package);
        Assert.True(status == HttpStatusCode.OK, body?.ToJsonString());
        var after = body!["settings"]!;
        Assert.Equal("Example Org", (string)after["organization"]!["name"]!);
        Assert.Equal("dark", (string)after["theme"]!);
        Assert.Equal((int)before["revision"]! + 1, (int)after["revision"]!);
        Assert.True(JsonNode.DeepEquals(before["data_lifecycle"], after["data_lifecycle"]));

        JsonObject Variant(Action<JsonObject> change) { var copy = package.DeepClone().AsObject(); change(copy); return copy; }
        var revision = (int)(await Settings())["revision"]!;
        var refusals = new (JsonObject Package, HttpStatusCode Status)[]
        {
            (Variant(p => p["settings"]!["data_csv_path"] = "/tmp/roles.csv"), HttpStatusCode.BadRequest),
            (Variant(p => p["settings"]!["employee_snapshot_id"] = "abc"), HttpStatusCode.BadRequest),
            (Variant(p => p["settings"]!["data_lifecycle"]!["history"] = new JsonArray(new JsonObject { ["id"] = "x" })), HttpStatusCode.BadRequest),
            (Variant(p => p["settings"]!["logo_id"] = new string('a', 64)), HttpStatusCode.BadRequest),
            (Variant(p => p["logo_base64"] = Convert.ToBase64String([137, 80, 78, 71])), HttpStatusCode.BadRequest),   // corrupt image: v1 refuses the package
            (Variant(p => p["format"] = "Other"), HttpStatusCode.UnprocessableEntity),
            (Variant(p => p["package_version"] = 2), HttpStatusCode.UnprocessableEntity),
            (Variant(p => p["extra"] = true), HttpStatusCode.UnprocessableEntity),
            (Variant(p => p["settings"]!["unknown_field"] = 1), HttpStatusCode.UnprocessableEntity),
            (Variant(p => p["settings"]!["theme"] = 5), HttpStatusCode.UnprocessableEntity),
        };
        foreach (var (variant, expected) in refusals)
        {
            var (refused, detail) = await Post("/api/configuration/import", variant);
            Assert.True(refused == expected, $"{expected} expected, {refused}: {detail?.ToJsonString()}");
        }
        Assert.Equal(revision, (int)(await Settings())["revision"]!);
    }

    [Fact]
    public async Task Reset_restores_defaults_unloads_datasets_and_keeps_history()
    {
        var csv = "AGR_NAME;AGR_TEXT;TCODE;TTEXT\nZ_ROLE_A;Role A;SU01;User maintenance\n";
        var job = JsonNode.Parse(await (await _client.PostAsync("/api/v1/imports/roles", new StringContent(csv, Encoding.UTF8, "text/csv"))).Content.ReadAsStringAsync())!;
        for (var i = 0; i < 400 && (string)JsonNode.Parse(await _client.GetStringAsync($"/api/v1/jobs/{(long)job["id"]!}"))!["status"]! != "Completed"; i++) await Task.Delay(50);
        Assert.NotEmpty(JsonNode.Parse(await _client.GetStringAsync("/api/roles"))!.AsArray());
        await SaveOrganization();
        var lifecycle = (await Settings())["data_lifecycle"]!.DeepClone();

        var (status, body) = await Post("/api/configuration/reset");
        Assert.True(status == HttpStatusCode.OK, body?.ToJsonString());
        var settings = body!["settings"]!.AsObject();
        var defaults = Expected()["defaults"]!.AsObject();
        foreach (var key in new[] { "theme", "organization", "import_profiles", "features", "module_overrides" })
            Assert.True(JsonNode.DeepEquals(defaults[key], settings[key]), key);
        Assert.True(JsonNode.DeepEquals(lifecycle, settings["data_lifecycle"]));
        Assert.Empty(JsonNode.Parse(await _client.GetStringAsync("/api/roles"))!.AsArray());
        // The dataset is retired, not deleted: the v1 history API still lists it.
        Assert.Contains("Retired", await _client.GetStringAsync("/api/v1/datasets?source=roles"));
    }

    [Fact]
    public async Task Reviewer_profile_is_desktop_only_revisioned_and_attributes_decisions()
    {
        Assert.Equal(HttpStatusCode.Forbidden, (await _client.GetAsync("/api/reviewer-profile")).StatusCode);
        Assert.Equal(HttpStatusCode.Forbidden, (await Post("/api/reviewer-profile", new { display_name = "X", expected_revision = 0 })).Status);

        await RestartAsync(HostMode.Desktop);
        var profile = JsonNode.Parse(await _client.GetStringAsync("/api/reviewer-profile"))!;
        Assert.Equal(1, (int)profile["version"]!);
        Assert.Equal(0, (int)profile["revision"]!);
        Assert.Equal("Local reviewer", (string)profile["identity"]!["display_name"]!);
        Assert.Equal("desktop-local", (string)profile["identity"]!["provenance"]!);
        Assert.Matches("^[a-f0-9]{32}$", (string)profile["identity"]!["id"]!);
        Assert.Equal((string)profile["identity"]!["id"]!, (string)JsonNode.Parse(await _client.GetStringAsync("/api/reviewer-profile"))!["identity"]!["id"]!);

        Assert.Equal(HttpStatusCode.UnprocessableEntity, (await Post("/api/reviewer-profile", new { display_name = "A" })).Status);
        Assert.Equal(HttpStatusCode.UnprocessableEntity, (await Post("/api/reviewer-profile", new { display_name = "  ", expected_revision = 0 })).Status);
        Assert.Equal(HttpStatusCode.Conflict, (await Post("/api/reviewer-profile", new { display_name = "A", expected_revision = 5 })).Status);
        var (status, saved) = await Post("/api/reviewer-profile", new { display_name = "  Ada Reviewer ", expected_revision = 0 });
        Assert.Equal(HttpStatusCode.OK, status);
        Assert.Equal("Ada Reviewer", (string)saved!["identity"]!["display_name"]!);
        Assert.Equal(1, (int)saved["revision"]!);
        Assert.NotNull(saved["modified"]);

        await RestartAsync(HostMode.Desktop);
        var reloaded = JsonNode.Parse(await _client.GetStringAsync("/api/reviewer-profile"))!;
        Assert.True(JsonNode.DeepEquals(saved, reloaded));
    }
}
