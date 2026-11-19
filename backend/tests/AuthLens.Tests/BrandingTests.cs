using System.Net;
using System.Net.Http.Json;
using System.Text.Json.Nodes;
using Microsoft.AspNetCore.Builder;
using AuthLens.Api;

namespace AuthLens.Tests;

/// <summary>MIG-001: application and report logos through the v1 routes. Images are sanitized (ReportingTests covers the image rules against v1); files are
/// content-addressed and re-validated on read; a Server never reads a browser-named path; logos travel only in private configuration exports.</summary>
public sealed class BrandingTests : IAsyncLifetime
{
    private static readonly string Images = Path.Combine(AppContext.BaseDirectory, "Fixtures", "reporting", "images");
    private readonly string _root = Directory.CreateTempSubdirectory("saplens-branding-").FullName;
    private readonly string _token = HostSettings.NewToken();
    private WebApplication _app = null!;
    private HttpClient _client = null!;

    public Task InitializeAsync() => StartAsync(HostMode.Desktop);

    private async Task StartAsync(HostMode mode)
    {
        _app = AuthLensHost.Build(new HostSettings { DataDirectory = Path.Combine(_root, "data"), Port = 0, AccessToken = _token, JsonConsoleLogging = false, PrincipalName = "operator", Mode = mode });
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
    public async Task Application_logo_is_sanitized_stored_validated_and_exported_only_privately()
    {
        Assert.Equal(HttpStatusCode.NotFound, (await _client.GetAsync("/api/branding/logo")).StatusCode);
        var preview = await _client.PostAsJsonAsync("/api/branding/preview", new { path = Path.Combine(Images, "photo.jpg") });
        Assert.Equal(HttpStatusCode.OK, preview.StatusCode);
        var staged = JsonNode.Parse(await preview.Content.ReadAsStringAsync())!;
        var id = (string)staged["logo_id"]!;
        Assert.StartsWith("data:image/png;base64,", (string)staged["data_url"]!);
        foreach (var bad in new[] { "vector.svg", "corrupt.jpg", "animated.webp" })
            Assert.Equal(HttpStatusCode.BadRequest, (await _client.PostAsJsonAsync("/api/branding/preview", new { path = Path.Combine(Images, bad) })).StatusCode);
        Assert.Equal(HttpStatusCode.BadRequest, (await _client.PostAsJsonAsync("/api/branding/preview", new { path = "relative/logo.png" })).StatusCode);

        var settings = await Settings();
        settings["logo_id"] = new string('a', 64);                                          // a reference to a logo that does not exist
        Assert.Equal(HttpStatusCode.BadRequest, (await _client.PostAsJsonAsync("/api/configuration", settings)).StatusCode);
        settings["logo_id"] = id;
        Assert.Equal(HttpStatusCode.OK, (await _client.PostAsJsonAsync("/api/configuration", settings)).StatusCode);
        Assert.Equal((string)staged["data_url"]!, (string)JsonNode.Parse(await _client.GetStringAsync("/api/branding/logo"))!["data_url"]!);

        // Exports: the image travels only in a private export; importing it stages a fresh, sanitized copy.
        var shared = JsonNode.Parse(await (await _client.PostAsync("/api/configuration/export", null)).Content.ReadAsStringAsync())!;
        Assert.Null(shared["logo_base64"]);
        var exported = JsonNode.Parse(await (await _client.PostAsync("/api/configuration/export?include_private=true", null)).Content.ReadAsStringAsync())!.AsObject();
        Assert.Equal(id, (string)exported["settings"]!["logo_id"]!);
        Assert.NotNull(exported["logo_base64"]);
        foreach (var field in new[] { "data_csv_path", "user_csv_path", "sod_csv_path", "employee_csv_path" }) exported["settings"]![field] = "";
        var imported = await _client.PostAsJsonAsync("/api/configuration/import", exported);
        Assert.True(imported.IsSuccessStatusCode, await imported.Content.ReadAsStringAsync());
        Assert.Equal(id, (string)(await Settings())["logo_id"]!);
        exported["logo_base64"] = Convert.ToBase64String(File.ReadAllBytes(Path.Combine(Images, "truncated.png")));
        Assert.Equal(HttpStatusCode.BadRequest, (await _client.PostAsJsonAsync("/api/configuration/import", exported)).StatusCode);

        // An altered file is never served.
        var file = Path.Combine(_root, "data", "branding", id + ".png");
        File.WriteAllBytes(file, File.ReadAllBytes(Path.Combine(Images, "small.png")));
        Assert.Equal(HttpStatusCode.NotFound, (await _client.GetAsync("/api/branding/logo")).StatusCode);
    }

    [Fact]
    public async Task Report_logo_follows_the_v1_limits_and_can_be_removed()
    {
        var empty = JsonNode.Parse(await _client.GetStringAsync("/api/sod/reports/branding"))!;
        Assert.Null(empty["logo"]);
        Assert.Equal(1_000_000, (int)empty["limits"]!["max_bytes"]!);
        async Task<HttpResponseMessage> Put(string file) => await _client.PutAsJsonAsync("/api/sod/reports/branding",
            new { image_base64 = Convert.ToBase64String(File.ReadAllBytes(Path.Combine(Images, file))), filename = file });
        var webp = await Put("logo.webp");
        Assert.Equal(HttpStatusCode.UnprocessableEntity, webp.StatusCode);
        Assert.Equal("Use a PNG or JPEG image; SVG and WebP are not accepted.", (string)JsonNode.Parse(await webp.Content.ReadAsStringAsync())!["detail"]!);
        var tiny = await Put("tiny.png");
        Assert.Equal("Logo dimensions must be between 32 and 4096 pixels.", (string)JsonNode.Parse(await tiny.Content.ReadAsStringAsync())!["detail"]!);
        Assert.Equal(HttpStatusCode.UnprocessableEntity, (await _client.PutAsJsonAsync("/api/sod/reports/branding", new { image_base64 = "not base64!" })).StatusCode);
        var stored = JsonNode.Parse(await (await Put("photo.jpg")).Content.ReadAsStringAsync())!["logo"]!;
        Assert.Equal((1024, 576), ((int)stored["width"]!, (int)stored["height"]!));
        Assert.Equal("photo.jpg", (string)stored["filename"]!);
        var removed = JsonNode.Parse(await (await _client.DeleteAsync("/api/sod/reports/branding")).Content.ReadAsStringAsync())!;
        Assert.Null(removed["logo"]);
    }

    [Fact]
    public async Task A_server_never_reads_a_logo_from_a_browser_named_path()
    {
        await DisposeAsync();
        Directory.CreateDirectory(_root);
        await StartAsync(HostMode.Server);
        var response = await _client.PostAsJsonAsync("/api/branding/preview", new { path = Path.Combine(Images, "photo.jpg") });
        Assert.Equal(HttpStatusCode.BadRequest, response.StatusCode);
        Assert.False(Directory.Exists(Path.Combine(_root, "data", "branding")));
    }
}
