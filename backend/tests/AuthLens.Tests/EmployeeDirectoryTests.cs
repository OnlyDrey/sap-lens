using System.Net;
using System.Net.Http.Json;
using System.Text;
using System.Text.Json.Nodes;
using Microsoft.AspNetCore.Builder;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;
using AuthLens.Api;
using AuthLens.Domain.Csv;
using AuthLens.Domain.Directory;
using AuthLens.Persistence;

namespace AuthLens.Tests;

/// <summary>Employee Directory (port of employee_directory.py, routers/employees.py, employee_preview.py) on the versioned dataset pipeline.
/// Synthetic reserved-domain records only.</summary>
public sealed class EmployeeDirectoryTests : IAsyncLifetime
{
    private static readonly string Header = string.Join(';', EmployeeDirectory.Headers);
    private static string Row(string name, string sam, string mail, string dept = "Finance", string title = "Analyst", string enabled = "True", string managerMail = "", string managerDn = "", string managerSam = "", string dn = "") =>
        string.Join(';', "HQ", name, sam, sam + "@example.invalid", mail, dept, title, enabled, dn.Length > 0 ? dn : $"CN={name},OU=Staff", managerDn, "Manager " + name, managerSam, managerMail, "Leadership", "Head", "Resolved");
    private static string Csv(params string[] rows) => Header + "\n" + string.Join("\n", rows) + "\n";

    private readonly string _root = Directory.CreateTempSubdirectory("saplens-employees-").FullName;
    private readonly string _token = HostSettings.NewToken();
    private WebApplication _app = null!;
    private HttpClient _client = null!;

    public async Task InitializeAsync()
    {
        _app = AuthLensHost.Build(new HostSettings { DataDirectory = Path.Combine(_root, "data"), Port = 0, AccessToken = _token, JsonConsoleLogging = false });
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

    private async Task<(HttpStatusCode Status, JsonNode? Body)> Send(HttpMethod method, string path, HttpContent? content = null)
    {
        using var request = new HttpRequestMessage(method, path) { Content = content };
        var response = await _client.SendAsync(request);
        var text = await response.Content.ReadAsStringAsync();
        return (response.StatusCode, text.Length > 0 ? JsonNode.Parse(text) : null);
    }

    private async Task<JsonObject> Settings() => JsonNode.Parse(await _client.GetStringAsync("/api/configuration"))!["settings"]!.AsObject();

    private async Task<(HttpStatusCode, JsonNode?)> Upload(string source, string csv)
    {
        var form = new MultipartFormDataContent
        {
            { new ByteArrayContent(Encoding.UTF8.GetBytes(csv)), "file", source + ".csv" },
            { new StringContent(((int)(await Settings())["revision"]!).ToString()), "revision" },
        };
        return await Send(HttpMethod.Post, $"/api/server/uploads/{source}/activate", form);
    }

    private async Task EnableDirectory()
    {
        var settings = await Settings();
        settings["features"]!["employee_directory"] = true;
        Assert.Equal(HttpStatusCode.OK, (await Send(HttpMethod.Post, "/api/configuration", JsonContent.Create(settings))).Status);
    }

    [Fact]
    public void Parser_enforces_the_documented_schema_and_python_csv_quoting()
    {
        var rows = EmployeeDirectory.Parse(Encoding.UTF8.GetBytes("﻿" + Csv(Row("Ada", "ADA", " Ada@Example.invalid "), "", Row("Bob \"B\"", "BOB", "bob@example.invalid"))));
        Assert.Equal(2, rows.Count);
        Assert.Equal("Ada@Example.invalid", rows[0]["Mail"]);
        Assert.Equal("Bob \"B\"", rows[1]["Name"]); // a quote inside an unquoted field is literal text
        var quoted = EmployeeDirectory.Parse(Encoding.UTF8.GetBytes(Header + "\n\"HQ;North\";\"Multi\nLine\";" + string.Join(';', Enumerable.Repeat("x", 14)) + "\n"));
        Assert.Equal(("HQ;North", "Multi\nLine"), (quoted[0]["Site"], quoted[0]["Name"]));
        void Refused(string text, string message) => Assert.Contains(message, Assert.Throws<CsvFormatException>(() => EmployeeDirectory.Parse(Encoding.UTF8.GetBytes(text))).Message);
        Refused(Header.Replace(";ManagerLookupStatus", "") + "\n", "all 16 documented headers");
        Refused(Header + ";Mail\n", "all 16 documented headers");
        Refused(Header + "\n", "no employee records");
        Refused(Header + "\na;b\n", "malformed rows");
        Refused(Header + "\n\"a\"b;" + string.Join(';', Enumerable.Repeat("x", 15)) + "\n", "malformed CSV quoting");
        Refused(Header + "\n\"open;" + string.Join(';', Enumerable.Repeat("x", 15)) + "\n", "malformed CSV quoting");
        Refused(Header + "\n" + new string('x', 4097) + ";" + string.Join(';', Enumerable.Repeat("x", 15)) + "\n", "oversized fields");
        Assert.Contains("UTF-8", Assert.Throws<CsvFormatException>(() => EmployeeDirectory.Parse([.. Encoding.UTF8.GetBytes(Header + "\n"), 0xff, 0xfe])).Message);
    }

    [Fact]
    public void Managers_resolve_by_preferred_key_without_fallback_and_identities_match_by_exact_email()
    {
        var rows = EmployeeDirectory.Parse(Encoding.UTF8.GetBytes(Csv(
            Row("Boss", "BOSS", "boss@example.invalid"),
            Row("Ada", "ADA", "ada@example.invalid", managerMail: "BOSS@example.invalid"),
            Row("Dup1", "DUP1", "dup@example.invalid"),
            Row("Dup2", "DUP2", "dup@example.invalid"),
            Row("Cy", "CY", "cy@example.invalid", managerMail: "dup@example.invalid", managerSam: "BOSS"),     // ambiguous preferred key: no fallback
            Row("Self", "SELF", "self@example.invalid", managerMail: "self@example.invalid"),
            Row("Gone", "GONE", "", managerDn: "CN=Nobody"),
            Row("None", "NONE", "none@example.invalid"))));
        var directory = new EmployeeDirectory(rows, "employees.csv", new string('a', 64), "2026-01-01T00:00:00+00:00");
        Assert.Equal(("resolved", (int?)0), directory.Manager(1));
        Assert.Equal("ambiguous", directory.Manager(4).Status);
        Assert.Equal("self_reference", directory.Manager(5).Status);
        Assert.Equal("unresolved", directory.Manager(6).Status);
        Assert.Equal("missing", directory.Manager(7).Status);
        Assert.Equal("matched", directory.Match(["ADA@example.invalid "]).Status);
        Assert.Equal("duplicate_email", directory.Match(["dup@example.invalid"]).Status);
        Assert.Equal("ambiguous_sap_email", directory.Match(["ada@example.invalid", "cy@example.invalid"]).Status);
        Assert.Equal("unmatched", directory.Match(["other@example.invalid"]).Status);
        Assert.Equal("missing_email", directory.Match([" "]).Status);
        var report = directory.Report();
        Assert.Equal((8, 1, 1), ((int)report["records"]!, (int)report["duplicate_emails"]!, (int)report["missing_emails"]!));
        Assert.Equal("Enabled", directory.View(0)["account_status"]);
    }

    [Fact]
    public async Task Upload_activates_a_versioned_directory_with_status_search_match_inspection_and_clear()
    {
        await Upload("roles", AuthLens.Tests.Csv.Roles(5));
        await Upload("users", AuthLens.Tests.Csv.UsersHeader + "\nUSER0001;ZC:FI:ROLE_0001;GRP_FIN;Ada;Lovelace;ada@example.invalid;;;;;;A\nUSER0002;ZC:FI:ROLE_0002;GRP_FIN;Bo;Boss;boss@example.invalid;;;;;;A\nUSER0003;ZC:FI:ROLE_0002;GRP_FIN;No;Mail;;;;;;;A\n");
        var revisionBefore = (await _client.GetAsync("/api/runtime")).Headers.GetValues("X-Data-Revision").Single();
        var (status, body) = await Upload("employees", Csv(Row("Boss", "BOSS", "boss@example.invalid"), Row("Ada", "ADA", "ADA@example.invalid", managerMail: "boss@example.invalid")));
        Assert.Equal(HttpStatusCode.OK, status);
        Assert.Equal(2, (int)body!["records"]!);
        var revisionAfter = (await _client.GetAsync("/api/runtime")).Headers.GetValues("X-Data-Revision").Single();
        Assert.Equal(revisionBefore.Split('.')[1], revisionAfter.Split('.')[1]); // a directory-only change keeps the SAP publication
        Assert.NotEqual(revisionBefore.Split('.')[2], revisionAfter.Split('.')[2]);
        var settings = await Settings();
        Assert.Matches("^[a-f0-9]{64}$", (string)settings["employee_snapshot_id"]!);

        // The feature switch gates enrichment exactly as in v1.
        var disabled = JsonNode.Parse(await _client.GetStringAsync("/api/employees/status"))!;
        Assert.Equal(("disabled", false), ((string)disabled["status"]!, (bool)disabled["enabled"]!));
        Assert.Equal("directory_unavailable", (string)JsonNode.Parse(await _client.GetStringAsync("/api/employees/match/USER0001"))!["status"]!);
        await EnableDirectory();
        var enabled = JsonNode.Parse(await _client.GetStringAsync("/api/employees/status"))!;
        Assert.Equal(("healthy", "ready", 3), ((string)enabled["status"]!, (string)enabled["operational_status"]!, (int)enabled["coverage_total"]!));
        Assert.Equal(2, (int)enabled["coverage"]!["matched"]!);
        Assert.Equal(1, (int)enabled["coverage"]!["missing_email"]!);

        var list = JsonNode.Parse(await _client.GetStringAsync("/api/employees?search=ada"))!;
        Assert.Equal(1, (int)list["total"]!);
        var generation = (string)list["generation"]!;
        var record = JsonNode.Parse(await _client.GetStringAsync($"/api/employees/record/{(string)list["items"]![0]!["id"]!}?generation={generation}"))!;
        Assert.Equal(("Ada", "resolved"), ((string)record["name"]!, (string)record["manager"]!["status"]!));
        Assert.Equal(HttpStatusCode.Conflict, (await _client.GetAsync($"/api/employees/record/0?generation={new string('0', 64)}")).StatusCode);

        var match = JsonNode.Parse(await _client.GetStringAsync("/api/employees/match/user0001"))!;
        Assert.Equal(("matched", "Ada", "matched", "USER0002", "Bo Boss"), ((string)match["status"]!, (string)match["employee"]!["name"]!, (string)match["manager_sap"]!["status"]!,
            (string)match["manager_sap"]!["username"]!, (string)match["manager_sap"]!["display_name"]!));
        Assert.Equal("Normalized exact email", (string)match["diagnostics"]!["matching_method"]!);
        Assert.Equal(HttpStatusCode.NotFound, (await _client.GetAsync("/api/employees/match/NOBODY")).StatusCode);

        var inspect = (await Send(HttpMethod.Post, "/api/data-sources/employees/inspect", JsonContent.Create(new { filter = "matched", sort = "name" }))).Body!;
        Assert.Equal(2, (int)inspect["total"]!);
        Assert.Equal("matched", (string)inspect["items"]![0]!["sap_match"]!);
        Assert.Equal(2, (int)inspect["replacement"]!["unchanged"]!);

        var dashboard = JsonNode.Parse(await _client.GetStringAsync("/api/dashboard"))!;
        int? Metric(string id) => (int?)dashboard["metrics"]!.AsArray().Single(m => (string)m!["id"]! == id)!["value"];
        Assert.Equal((2, 2, 1, 0, 1), (Metric("employees"), Metric("email_matches"), Metric("directory_missing"), Metric("directory_ambiguous"), Metric("unresolved")));
        var health = JsonNode.Parse(await _client.GetStringAsync("/api/data-health"))!;
        Assert.Equal(2, (int)health["coverage"]![2]!["numerator"]!);

        // Clear retires the active dataset (kept as history) and resets the source in one transaction.
        var revision = (int)(await Settings())["revision"]!;
        Assert.Equal(HttpStatusCode.Conflict, (await Send(HttpMethod.Post, "/api/employees/clear", JsonContent.Create(new { path = "", revision = revision + 5 }))).Status);
        Assert.Equal(HttpStatusCode.OK, (await Send(HttpMethod.Post, "/api/employees/clear", JsonContent.Create(new { path = "", revision }))).Status);
        Assert.False((bool)JsonNode.Parse(await _client.GetStringAsync("/api/employees/status"))!["loaded"]!);
        await using var scope = _app.Services.CreateAsyncScope();
        await using var db = await scope.ServiceProvider.GetRequiredService<IDbContextFactory<AuthLensDb>>().CreateDbContextAsync();
        Assert.Equal(DatasetStatus.Retired, (await db.Datasets.SingleAsync(d => d.Source == "employees")).Status);
    }

    [Fact]
    public async Task Invalid_directories_never_replace_the_active_one_and_server_paths_are_refused()
    {
        Assert.Equal(HttpStatusCode.OK, (await Upload("employees", Csv(Row("Ada", "ADA", "ada@example.invalid")))).Item1);
        var (status, body) = await Upload("employees", Header + "\nbroken;row\n");
        Assert.Equal(HttpStatusCode.BadRequest, status);
        Assert.Contains("malformed rows", (string)body!["detail"]!);
        await EnableDirectory();
        Assert.Equal(1, (int)JsonNode.Parse(await _client.GetStringAsync("/api/employees"))!["total"]!);
        var form = new MultipartFormDataContent { { new ByteArrayContent("x"u8.ToArray()), "file", "e.csv" }, { new StringContent(((int)(await Settings())["revision"]!).ToString()), "revision" }, { new StringContent("{}"), "profile" } };
        Assert.Equal(HttpStatusCode.BadRequest, (await Send(HttpMethod.Post, "/api/server/uploads/employees/activate", form)).Status); // fixed schema: no import profile
        Assert.Equal(HttpStatusCode.BadRequest, (await Send(HttpMethod.Post, "/api/employees/preview", JsonContent.Create(new { path = "/etc/passwd", revision = 0 }))).Status);
    }
}
