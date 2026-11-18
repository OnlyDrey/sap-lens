using System.Net;
using System.Text;
using System.Text.Json.Nodes;
using Microsoft.AspNetCore.Builder;
using SapLens.Api;

namespace SapLens.Tests;

/// <summary>MIG-009: header inspection and import preview for the role catalogue and the user import, against Python v1
/// (Fixtures/imports/preview.python.json, written by tools/import_preview_reference.py from the same synthetic case files). Every run must return v1's
/// status and body exactly: detected columns, delimiter, encoding, proposed mapping, issues, the full import report with samples, the catalogue and
/// directory counts, warnings and the fixed error messages. A preview stores nothing.</summary>
public sealed class ImportPreviewTests : IAsyncLifetime
{
    private readonly string _root = Directory.CreateTempSubdirectory("saplens-preview-").FullName;
    private readonly string _token = HostSettings.NewToken();
    private WebApplication _app = null!;
    private HttpClient _client = null!;
    private static string Fixture(string name) => Path.Combine(AppContext.BaseDirectory, "Fixtures", "imports", name);

    private async Task StartAsync(HostMode mode)
    {
        _app = SapLensHost.Build(new HostSettings
        {
            DataDirectory = Path.Combine(_root, "data"), Port = 0, AccessToken = _token, JsonConsoleLogging = false, Mode = mode,
            Authentication = AuthenticationMode.SharedToken,
        });
        await _app.StartAsync();
        _client = new HttpClient { BaseAddress = new Uri(_app.Urls.First()) };
        _client.DefaultRequestHeaders.Add(RequestBoundary.TokenHeader, _token);
    }

    public Task InitializeAsync() => StartAsync(HostMode.Desktop);

    public async Task DisposeAsync()
    {
        _client.Dispose();
        await _app.StopAsync();
        await _app.DisposeAsync();
        Microsoft.Data.Sqlite.SqliteConnection.ClearAllPools();
        try { Directory.Delete(_root, true); } catch (IOException) { }
    }

    private string Case(string name, string? folder = null)
    {
        var directory = Directory.CreateDirectory(folder ?? Path.Combine(_root, "cases")).FullName;
        var path = Path.Combine(directory, name + ".csv");
        File.Copy(Fixture(name + ".txt"), path, overwrite: true);
        return path;
    }

    private async Task<(HttpStatusCode Status, JsonNode? Body)> Post(string route, JsonNode body)
    {
        var request = new HttpRequestMessage(HttpMethod.Post, route) { Content = new StringContent(body.ToJsonString(), Encoding.UTF8, "application/json") };
        request.Headers.Add("Origin", _client.BaseAddress!.GetLeftPart(UriPartial.Authority));
        var response = await _client.SendAsync(request);
        var text = await response.Content.ReadAsStringAsync();
        return (response.StatusCode, text.Length == 0 ? null : JsonNode.Parse(text));
    }

    private async Task ImportCatalogueAsync()
    {
        var job = JsonNode.Parse(await (await _client.PostAsync("/api/v1/imports/roles", new StringContent(File.ReadAllText(Fixture("roles_default.txt")), Encoding.UTF8, "text/csv"))).Content.ReadAsStringAsync())!;
        for (var i = 0; i < 400 && (string)JsonNode.Parse(await _client.GetStringAsync($"/api/v1/jobs/{(long)job["id"]!}"))!["status"]! != "Completed"; i++) await Task.Delay(50);
    }

    [Fact]
    public async Task Every_preview_and_header_inspection_equals_python_v1()
    {
        await ImportCatalogueAsync();   // the user preview matches against the active catalogue, as v1's cache.get_snapshot().roles
        var reference = JsonNode.Parse(File.ReadAllText(Fixture("preview.python.json")))!;
        var failures = new List<string>();
        foreach (var run in reference["runs"]!.AsArray())
        {
            var route = (string)run!["route"]!;
            var body = new JsonObject { ["data_csv_path"] = Case((string)run["case"]!) };
            if (run["profile"] is JsonObject profile) body["profile"] = profile.DeepClone();
            var (status, actual) = await Post(route, body);
            var expected = run["result"]!;
            var label = $"{route} {run["case"]} {(run["profile"] is null ? "active profile" : (string)run["profile"]!["id"]!)}";
            if ((int)status != (int)expected["status"]!) { failures.Add($"{label}: status {(int)status}, v1 {expected["status"]}: {actual?.ToJsonString()[..Math.Min(300, actual.ToJsonString().Length)]}"); continue; }
            if (!JsonNode.DeepEquals(expected["body"], actual))
                failures.Add($"{label}: body differs\n  .NET {Trim(actual)}\n  v1   {Trim(expected["body"])}");
        }
        Assert.True(failures.Count == 0, string.Join("\n", failures));
    }

    private static string Trim(JsonNode? node) { var text = node?.ToJsonString() ?? "null"; return text.Length > 1500 ? text[..1500] + "…" : text; }

    [Fact]
    public async Task Invalid_requests_are_refused_like_pydantic_and_nothing_is_stored()
    {
        var path = Case("roles_default");
        foreach (var (route, body) in new (string, JsonObject)[]
                 {
                     ("/api/import/headers", new JsonObject()),
                     ("/api/import/preview", new JsonObject { ["data_csv_path"] = "" }),
                     ("/api/import/headers", new JsonObject { ["data_csv_path"] = path, ["extra"] = 1 }),
                     ("/api/import/preview", new JsonObject { ["data_csv_path"] = path, ["profile"] = new JsonObject { ["id"] = "bad id!", ["name"] = "x" } }),
                     ("/api/import/preview", new JsonObject { ["data_csv_path"] = path, ["profile"] = new JsonObject { ["id"] = "p", ["name"] = "x", ["mapping"] = new JsonObject { ["NOT_A_FIELD"] = "x" } } }),
                     ("/api/user-import/preview", new JsonObject { ["data_csv_path"] = path, ["profile"] = new JsonObject { ["id"] = "p", ["name"] = "x", ["mapping"] = new JsonObject { ["USERNAME"] = "a", ["ROLE_NAME"] = "a" } } }),
                     ("/api/user-import/headers", new JsonObject { ["data_csv_path"] = path, ["profile"] = new JsonObject { ["id"] = "p", ["name"] = "x", ["delimiter"] = ":" } }),
                 })
        {
            var (status, detail) = await Post(route, body);
            Assert.True(status == (HttpStatusCode)422, $"{route} {body.ToJsonString()}: {(int)status} {detail?.ToJsonString()}");
        }
        // Not a CSV path, a relative path and a missing file: the route's fixed message (v1 hides the parser reason except in the user preview).
        foreach (var bad in new[] { Path.Combine(_root, "file.txt"), "relative.csv", Path.Combine(_root, "missing.csv") })
        {
            var (status, detail) = await Post("/api/import/headers", new JsonObject { ["data_csv_path"] = bad });
            Assert.Equal(HttpStatusCode.BadRequest, status);
            Assert.Equal("Could not inspect the CSV header. Check path, encoding and delimiter.", (string)detail!["detail"]!);
        }
        Assert.Equal(0, (int)JsonNode.Parse(await _client.GetStringAsync("/api/configuration"))!["settings"]!["revision"]!);   // nothing stored
    }

    [Fact]
    public async Task On_a_server_only_files_in_the_server_source_folder_can_be_previewed()
    {
        await DisposeAsync();
        Directory.CreateDirectory(_root);
        await StartAsync(HostMode.Server);
        var inside = Case("roles_default", Path.Combine(_root, "data", "sources"));
        var outside = Case("roles_default");
        var (ok, report) = await Post("/api/import/preview", new JsonObject { ["data_csv_path"] = inside });
        Assert.True(ok == HttpStatusCode.OK, report?.ToJsonString());
        Assert.True((int)report!["unique_roles"]! > 0);
        foreach (var path in new[] { outside, Path.Combine(_root, "data", "sources", "..", "cases", "roles_default.csv") })
        {
            var (status, detail) = await Post("/api/import/headers", new JsonObject { ["data_csv_path"] = path });
            Assert.Equal(HttpStatusCode.BadRequest, status);
            Assert.Equal("Could not inspect the CSV header. Check path, encoding and delimiter.", (string)detail!["detail"]!);
        }
        if (!OperatingSystem.IsWindows())
        {
            var link = Path.Combine(_root, "data", "sources", "link.csv");
            File.CreateSymbolicLink(link, outside);
            Assert.Equal(HttpStatusCode.BadRequest, (await Post("/api/user-import/headers", new JsonObject { ["data_csv_path"] = link })).Status);   // a link out is refused
        }
    }
}
