using System.Net;
using System.Net.Http.Json;
using System.Text;
using System.Text.Json.Nodes;
using Microsoft.AspNetCore.Builder;
using AuthLens.Api;
using AuthLens.Domain.Roles;

namespace AuthLens.Tests;

/// <summary>Port of backend/tests/test_access_package.py: suffix replacement, validation, exact-role confirmation and deterministic export.</summary>
public sealed class AccessPackageTests : IAsyncLifetime
{
    private static readonly string[] Names = ["ZC:MM:BUY:ENP", "ZC:FI:VIEW:ENP", "ZC:FI:VIEW:ENK", "ZC:SD:ORD:ENK", "ZC:MM:BUY:*", "ZC:SD:ORD:EN*", "ZC:HR:MISC:XYZ", "ZO:MM:M:REL:ALL", "ZC:SD:LONG_ROLE_NAME_FOR_SAP:ENP"];
    private static readonly Dictionary<string, int> Known = AccessPackage.NamingEvidence(Names);
    private static string Catalogue => Csv.RolesHeader + "\n" + string.Concat(Names.Select((n, i) => $"MM;{n};Description of {n};ZS:{i};MM;;;MIGO;Goods\n"));

    private readonly string _root = Directory.CreateTempSubdirectory("saplens-package-").FullName;
    private readonly string _token = HostSettings.NewToken();
    private WebApplication _app = null!;
    private HttpClient _client = null!;

    public async Task InitializeAsync()
    {
        _app = AuthLensHost.Build(new HostSettings { DataDirectory = Path.Combine(_root, "data"), Port = 0, AccessToken = _token, JsonConsoleLogging = false });
        await _app.StartAsync();
        _client = new HttpClient { BaseAddress = new Uri(_app.Urls.First()) };
        _client.DefaultRequestHeaders.Add(RequestBoundary.TokenHeader, _token);
        await Import("roles", Catalogue);
    }

    public async Task DisposeAsync()
    {
        _client.Dispose();
        await _app.StopAsync();
        await _app.DisposeAsync();
        Microsoft.Data.Sqlite.SqliteConnection.ClearAllPools();
        try { Directory.Delete(_root, true); } catch (IOException) { }
    }

    private async Task Import(string source, string csv)
    {
        var job = JsonNode.Parse(await (await _client.PostAsync($"/api/v1/imports/{source}", new StringContent(csv, Encoding.UTF8, "text/csv"))).Content.ReadAsStringAsync())!;
        for (var i = 0; i < 200 && (string)JsonNode.Parse(await _client.GetStringAsync($"/api/v1/jobs/{(long)job["id"]!}"))!["status"]! != "Completed"; i++) await Task.Delay(50);
    }

    private async Task<JsonNode> Preview(string fallback, string[]? roles = null, Dictionary<string, string>? overrides = null)
    {
        roles ??= ["ZC:MM:BUY:ENP", "ZC:MM:BUY:*"];
        var response = await _client.PostAsJsonAsync("/api/roles/package/preview", new { default_suffix = fallback, items = roles.Select(r => new { role = r, suffix = overrides?.GetValueOrDefault(r) ?? "" }) });
        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        return JsonNode.Parse(await response.Content.ReadAsStringAsync())!;
    }

    private static List<string?> Field(JsonNode data, string field) => data["items"]!.AsArray().Select(r => (string?)r![field]).ToList();

    [Fact]
    public void Pure_rules_match_v1()
    {
        Assert.Equal(new Dictionary<string, int> { ["ENP"] = 3, ["ENK"] = 2 }, Known);
        Assert.Equal(("ZC:MM:BUY:ENS", "organizational"), Two(AccessPackage.Propose("ZC:MM:BUY:ENP", "ENS", Known)));
        Assert.Equal(("ZC:MM:BUY:ENO", "wildcard"), Two(AccessPackage.Propose("ZC:MM:BUY:*", "ENO", Known)));
        Assert.Equal(("ZC:SD:ORD:ENS", "wildcard"), Two(AccessPackage.Propose("ZC:SD:ORD:EN*", "ENS", Known)));
        foreach (var (source, suffix) in new[] { ("ZC:SD:ORD:EN*", "XX"), ("ZC:*:X*", "ENP"), ("ZC:A**", "ENP") })
        {
            var (name, kind, message) = AccessPackage.Propose(source, suffix, Known);
            Assert.Equal(((string?)null, "ambiguous"), (name, kind));
            Assert.False(string.IsNullOrEmpty(message));
        }
        Assert.Equal("organizational", AccessPackage.SuffixKind("ZC:MM:BUY:ENP", Known));
        Assert.Equal("wildcard", AccessPackage.SuffixKind("ZC:SD:ORD:EN*", Known));
        Assert.Null(AccessPackage.SuffixKind("ZC:HR:MISC:XYZ", Known));
        Assert.Null(AccessPackage.SuffixKind("PLAIN", Known));
        Assert.Null(AccessPackage.SuffixKind("ZC:HR:MISC:ENX", Known));
        Assert.Equal(("ZC:HR:MISC:XYZ", "exact", (string?)null), AccessPackage.Propose("ZC:HR:MISC:XYZ", "ENP", Known));
        Assert.Null(AccessPackage.NameError("ZC:MM:BUY:ENP"));
        foreach (var stem in new[] { "ZC:BC:S4_COMMON_USERS_____MGT:", "ZC:BC:S4_KEYS_USERS_____MGT:", "ZC::BUY" }) Assert.Null(AccessPackage.NameError(stem));
        Assert.DoesNotContain("ZC:SD:LONG", AccessPackage.NameError("ZC:SD:LONG_ROLE_NAME_FOR_SAP:ENP")!);
        foreach (var bad in new[] { "ZC:MM:BUY:enp", "ZC:SD:LONG_ROLE_NAME_FOR_SAP:ENP", "ZC MM", "ZC:MM:BUY$" }) Assert.NotNull(AccessPackage.NameError(bad));
        static (string?, string) Two((string? Name, string Kind, string? Message) p) => (p.Name, p.Kind);
    }

    [Fact]
    public async Task Confirmation_needs_the_exact_role_in_imported_roles_or_assignments()
    {
        var data = await Preview("ENS", ["ZC:MM:BUY:ENP", "ZC:FI:VIEW:ENP"]);
        Assert.Equal(["ZC:MM:BUY:ENS", "ZC:FI:VIEW:ENS"], Field(data, "name"));
        Assert.Equal(["pattern", "attention"], Field(data, "validation"));
        Assert.All(data["items"]!.AsArray(), r => Assert.True((bool)r!["exportable"]!));
        var confirmed = await Preview("ENK", ["ZC:FI:VIEW:ENP"]);
        Assert.Equal(("ZC:FI:VIEW:ENK", "confirmed"), ((string?)confirmed["items"]![0]!["name"], (string?)confirmed["items"]![0]!["validation"]));
        var naming = JsonNode.Parse(await _client.GetStringAsync("/api/roles/naming"))!;
        Assert.Equal("[{\"value\":\"ENP\",\"roles\":3},{\"value\":\"ENK\",\"roles\":2}]", naming["suffixes"]!.ToJsonString());
    }

    [Fact]
    public async Task Default_suffix_with_explicit_overrides_validation_and_catalogue_matches()
    {
        var data = await Preview("enk", overrides: new() { ["ZC:MM:BUY:*"] = "ENP" });
        var (first, second) = (data["items"]![0]!, data["items"]![1]!);
        Assert.Equal(("ZC:MM:BUY:ENK", "ENK", "default", "ok"), ((string?)first["name"], (string?)first["suffix"], (string?)first["suffix_source"], (string?)first["status"]));
        Assert.Equal("{\"status\":\"wildcard\",\"candidates\":[\"ZC:MM:BUY:*\"]}", first["catalogue"]!.ToJsonString());
        Assert.Equal(("ZC:MM:BUY:ENP", "override", "exact"), ((string?)second["name"], (string?)second["suffix_source"], (string?)second["catalogue"]!["status"]));
        Assert.Equal(["pattern", "confirmed"], Field(data, "validation"));
        Assert.Equal(2, (int)data["exportable"]!);
        Assert.Equal(["ZC:MM:BUY:ENS", "ZC:MM:BUY:ENP"], Field(await Preview("ENS", overrides: new() { ["ZC:MM:BUY:*"] = "ENP" }), "name"));
    }

    [Fact]
    public async Task Statuses_for_missing_suffix_unknown_role_ambiguity_syntax_length_and_duplicates()
    {
        Assert.Equal("needs_suffix", (string?)(await Preview("", ["ZC:MM:BUY:ENP"]))["items"]![0]!["status"]);
        var data = await Preview("ENP", ["ZC:NOT:THERE", "ZC:HR:MISC:XYZ", "ZC:SD:LONG_ROLE_NAME_FOR_SAP:ENP", "ZC:MM:BUY:ENP", "ZC:MM:BUY:*"]);
        Assert.Equal(["unknown_role", "ok", "invalid", "ok", "duplicate"], Field(data, "status"));
        Assert.Equal(["attention", "confirmed", "invalid", "confirmed", "invalid"], Field(data, "validation"));
        var exact = data["items"]![1]!;
        Assert.Equal(("ZC:HR:MISC:XYZ", "", false, true), ((string?)exact["name"], (string?)exact["suffix"], (bool)exact["suffix_eligible"]!, (bool)exact["exportable"]!));
        Assert.Contains("no suffix variants", (string)exact["suffix_note"]!);
        Assert.True((bool)data["items"]![3]!["suffix_eligible"]!);
        Assert.Contains("Same name as another role", (string)data["items"]![4]!["messages"]![0]!);
        Assert.Equal("invalid", (string?)(await Preview("bad suffix!"))["items"]![0]!["status"]);
        Assert.Equal("exact", (string?)(await Preview("ENP", ["ZC:MM:BUY:ENP"]))["items"]![0]!["catalogue"]!["status"]);
        var unmapped = (await Preview("ENQ", ["ZC:FI:VIEW:ENP"]))["items"]![0]!;
        Assert.Equal(("ZC:FI:VIEW:ENQ", "unmapped", "attention", true), ((string?)unmapped["name"], (string?)unmapped["catalogue"]!["status"], (string?)unmapped["validation"], (bool)unmapped["exportable"]!));
        Assert.Contains("Check it in SAP", (string)unmapped["messages"]!.AsArray()[^1]!);
        var mixed = await Preview("", ["ZC:MM:BUY:ENP", "ZC:HR:MISC:XYZ"]);
        Assert.Equal(["attention", "confirmed"], Field(mixed, "validation"));
    }

    [Fact]
    public async Task Export_is_deterministic_unique_escaped_and_never_includes_invalid_rows()
    {
        var body = new { default_suffix = "ENS", items = new[] { "ZC:MM:BUY:ENP", "ZC:FI:VIEW:ENP", "ZC:MM:BUY:*", "ZC:HR:MISC:XYZ", "ZC:NOT:THERE" }.Select(r => new { role = r }) };
        var response = await _client.PostAsJsonAsync("/api/roles/package/export", body);
        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        Assert.Matches(@"authlens-access-package-\d{4}-\d{2}-\d{2}\.csv", response.Content.Headers.ContentDisposition!.ToString());
        Assert.Equal("no-store", response.Headers.CacheControl!.ToString());
        var text = Encoding.UTF8.GetString(await response.Content.ReadAsByteArrayAsync());
        Assert.StartsWith("﻿\"Generated SAP Role Name\";\"Role Description\";\"Suffix\";\"Validation\"\r\n", text);
        var lines = text.TrimStart('﻿').Split("\r\n", StringSplitOptions.RemoveEmptyEntries);
        Assert.Equal(["\"ZC:FI:VIEW:ENS\";\"Description of ZC:FI:VIEW:ENP\";\"ENS\";\"Needs attention\"", "\"ZC:HR:MISC:XYZ\";\"Description of ZC:HR:MISC:XYZ\";\"\";\"Confirmed\"",
            "\"ZC:MM:BUY:ENS\";\"Description of ZC:MM:BUY:ENP\";\"ENS\";\"Pattern match\""], lines[1..]);
        Assert.Equal(HttpStatusCode.UnprocessableEntity, (await _client.PostAsJsonAsync("/api/roles/package/export", new { default_suffix = "", items = new[] { new { role = "ZC:MM:BUY:ENP" } } })).StatusCode);
        var many = await _client.PostAsJsonAsync("/api/roles/package/preview", new { items = Enumerable.Range(0, 450).Select(n => new { role = $"ZC:BULK:{n}" }) });
        Assert.Equal(450, JsonNode.Parse(await many.Content.ReadAsStringAsync())!["items"]!.AsArray().Count);
        Assert.Equal(HttpStatusCode.UnprocessableEntity, (await _client.PostAsJsonAsync("/api/roles/package/preview", new { items = Array.Empty<object>(), extra = 1 })).StatusCode);
        Assert.Equal(HttpStatusCode.UnprocessableEntity, (await _client.PostAsJsonAsync("/api/roles/package/preview", new { items = new[] { new { role = "X", source = "other" } } })).StatusCode);
        using var anonymous = new HttpClient { BaseAddress = _client.BaseAddress };
        Assert.Equal(HttpStatusCode.Forbidden, (await anonymous.PostAsJsonAsync("/api/roles/package/preview", new { items = Array.Empty<object>() })).StatusCode);
    }

    [Fact]
    public async Task Release_roles_keep_exact_names_and_unknown_or_duplicate_release_items_are_not_exported()
    {
        await Import("users", Csv.UsersHeader + "\nDEMO_ONE;ZO:MM:M:PR_REL_ST_E2_N1:ALL;G1;;;;;;20200101;99991231;;A\nDEMO_ONE;ZO:MM:M:PO_REL_ST_N1_N2:ENP;G1;;;;;;20200101;99991231;;A\n");
        async Task<HttpResponseMessage> Post(string path, object[] items) => await _client.PostAsJsonAsync("/api/roles/package/" + path, new { default_suffix = "ENS", items });
        object[] items = [new { role = "ZC:MM:BUY:ENP" }, new { role = "ZO:MM:M:PR_REL_ST_E2_N1:ALL", source = "release" }, new { role = "ZO:MM:M:PO_REL_ST_N1_N2:ENP", source = "release", suffix = "XYZ" }];
        var rows = JsonNode.Parse(await (await Post("preview", items)).Content.ReadAsStringAsync())!;
        Assert.Equal(["ZC:MM:BUY:ENS", "ZO:MM:M:PR_REL_ST_E2_N1:ALL", "ZO:MM:M:PO_REL_ST_N1_N2:ENP"], Field(rows, "name"));
        Assert.Equal(["catalogue", "release", "release"], Field(rows, "source"));
        Assert.Equal("", (string?)rows["items"]![2]!["suffix"]);
        var exported = (await (await Post("export", items)).Content.ReadAsStringAsync()).TrimStart('﻿').Split("\r\n", StringSplitOptions.RemoveEmptyEntries).Skip(1).Select(l => l.Split(';')[0].Trim('"'));
        Assert.Equal(["ZC:MM:BUY:ENS", "ZO:MM:M:PO_REL_ST_N1_N2:ENP", "ZO:MM:M:PR_REL_ST_E2_N1:ALL"], exported);
        object[] release = [new { role = "ZO:MM:M:PR_REL_ST_E2_N1:ALL", source = "release" }, new { role = "zo:mm:m:pr_rel_st_e2_n1:all", source = "release" },
            new { role = "ZO:MM:M:PR_REL_ST_X9_N1:ALL", source = "release" }, new { role = "ZO:MM:M:*", source = "release" }, new { role = "ZC:MM:BUY:ENP", source = "release" }];
        var statuses = JsonNode.Parse(await (await Post("preview", release)).Content.ReadAsStringAsync())!;
        Assert.Equal(["ok", "duplicate", "unknown_role", "unknown_role", "unknown_role"], Field(statuses, "status"));
        Assert.Equal(1, (int)statuses["exportable"]!);
    }

    [Theory]
    [InlineData("=SUM(A1)", "'=SUM(A1)")]
    [InlineData(" -1", "' -1")]
    [InlineData("\tx", "'\tx")]
    [InlineData("ZC:MM", "ZC:MM")]
    public void Spreadsheet_cells_are_neutralized_like_v1(string value, string expected) => Assert.Equal(expected, V1Csv.Cell(value));
}
