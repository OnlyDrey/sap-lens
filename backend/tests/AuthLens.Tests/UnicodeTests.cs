using System.Net;
using System.Net.Http.Json;
using System.Text;
using System.Text.Json.Nodes;
using Microsoft.AspNetCore.Builder;
using AuthLens.Api;
using AuthLens.Domain.Text;

namespace AuthLens.Tests;

/// <summary>Unicode parity with SAP Lens v1 (Python 3.12): str.casefold/upper/lower and NFKC on Norwegian and international text (Fixtures/unicode-python312.json
/// was written by Python 3.12), and Norwegian names end to end: CSV import, persistence across a restart, search, sorting, saved-filter name identity
/// and CSV export.</summary>
public sealed class UnicodeTests : IAsyncLifetime
{
    private static readonly JsonObject Reference = JsonNode.Parse(File.ReadAllText(Path.Combine(AppContext.BaseDirectory, "Fixtures", "unicode-python312.json")))!.AsObject();
    private readonly string _root = Directory.CreateTempSubdirectory("saplens-unicode-").FullName;
    private readonly string _token = HostSettings.NewToken();
    private WebApplication _app = null!;
    private HttpClient _client = null!;

    public Task InitializeAsync() => Task.CompletedTask;

    private async Task Start()
    {
        _app = AuthLensHost.Build(new HostSettings { DataDirectory = Path.Combine(_root, "data"), Port = 0, AccessToken = _token, JsonConsoleLogging = false, PrincipalName = "operator", Mode = HostMode.Desktop });
        await _app.StartAsync();
        _client = new HttpClient { BaseAddress = new Uri(_app.Urls.First()) };
        _client.DefaultRequestHeaders.Add(RequestBoundary.TokenHeader, _token);
        _client.DefaultRequestHeaders.Add("Origin", _client.BaseAddress.GetLeftPart(UriPartial.Authority));
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
        if (_app is not null) await Stop();
        try { Directory.Delete(_root, true); } catch (IOException) { }
    }

    [Fact]
    public void Case_mapping_and_normalization_equal_python()
    {
        foreach (var (text, expected) in Reference)
        {
            Assert.Equal((string)expected!["casefold"]!, PythonText.Casefold(text));
            Assert.Equal((string)expected["upper"]!, PythonText.Upper(text));
            Assert.Equal((string)expected["lower"]!, PythonText.Lower(text));
            Assert.Equal((string)expected["nfkc"]!, PythonText.Nfkc(text));
        }
        Assert.Equal("15.0.0", PythonText.UnicodeVersion);
        Assert.NotEqual("unknown", PythonText.VerifyRuntime());
    }

    private async Task ImportAsync(string source, string csv)
    {
        var job = JsonNode.Parse(await (await _client.PostAsync($"/api/v1/imports/{source}", new StringContent(csv, Encoding.UTF8, "text/csv"))).Content.ReadAsStringAsync())!;
        for (var i = 0; i < 200 && (string)JsonNode.Parse(await _client.GetStringAsync($"/api/v1/jobs/{(long)job["id"]!}"))!["status"]! != "Completed"; i++) await Task.Delay(50);
    }

    [Fact]
    public async Task Norwegian_names_import_persist_search_sort_and_export_unchanged()
    {
        await Start();
        await ImportAsync("roles", Csv.Roles(3));
        var users = Csv.UsersHeader + "\n" + string.Join("\n", new[]
        {
            "ØYSTEIN;ZC:FI:ROLE_0000;GRP_ØKONOMI;Øystein;Ødegård;oystein@example.com;;;;;;A",
            "ÅSE;ZC:FI:ROLE_0001;GRP_ØKONOMI;Åse;Ærøy;ase@example.com;;;;;;A",
            "ZARA;ZC:FI:ROLE_0002;GRP_FIN;Zara;Strauß;zara@example.com;;;;;;A",
            "ÆRLIG;ZC:FI:ROLE_0000;GRP_FIN;Kåre;Bjørnstad;kare@example.com;;;;;;A",
        }) + "\n";
        await ImportAsync("users", users);
        await Stop();
        await Start();                                                                        // persisted through SQLite as UTF-8

        var all = JsonNode.Parse(await _client.GetStringAsync("/api/access/users?show_expired=true"))!;
        var names = all["items"]!.AsArray().Select(i => (string)i!["username"]!).ToList();
        Assert.Equal(["ZARA", "ÅSE", "ÆRLIG", "ØYSTEIN"], names);                             // v1 sorts by code point: Z < Å (U+00C5) < Æ (U+00C6) < Ø (U+00D8)
        Assert.Equal("Ødegård", (string)all["items"]!.AsArray().First(i => (string)i!["username"]! == "ØYSTEIN")!["last_name"]!);

        async Task<List<string>> Search(string term) => JsonNode.Parse(await _client.GetStringAsync("/api/access/users?show_expired=true&search=" + Uri.EscapeDataString(term)))!["items"]!
            .AsArray().Select(i => (string)i!["username"]!).ToList();
        Assert.Equal(["ØYSTEIN"], await Search("ødegård"));                                  // case-insensitive on Norwegian letters
        Assert.Equal(["ÅSE", "ØYSTEIN"], await Search("grp_økonomi"));
        Assert.Empty(await Search("STRAUSS"));                                                // v1 search uses str.lower(): sharp s is not folded to "ss"
        Assert.Equal(["ZARA"], await Search("strauß"));
        Assert.Equal(["ÆRLIG"], await Search("kåre*"));

        var export = await _client.GetAsync("/api/access/exports/users?show_expired=true");
        Assert.Equal(HttpStatusCode.OK, export.StatusCode);
        var text = Encoding.UTF8.GetString(await export.Content.ReadAsByteArrayAsync());
        Assert.Contains("Ødegård", text);
        Assert.Contains("Ærøy", text);

        // Saved-filter names are unique per view by str.casefold.
        Assert.Equal(HttpStatusCode.OK, (await _client.PostAsJsonAsync("/api/saved-filters", new { name = "Økonomi Straße", view = "users", filters = new { search = "ø" } })).StatusCode);
        var duplicate = await _client.PostAsJsonAsync("/api/saved-filters", new { name = "ØKONOMI STRASSE", view = "users", filters = new { search = "ø" } });
        Assert.NotEqual(HttpStatusCode.OK, duplicate.StatusCode);
    }
}
