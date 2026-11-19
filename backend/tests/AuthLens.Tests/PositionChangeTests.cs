using System.Net;
using System.Net.Http.Json;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json.Nodes;
using Microsoft.AspNetCore.Builder;
using AuthLens.Api;
using AuthLens.Domain.Directory;

namespace AuthLens.Tests;

/// <summary>MIG-003: Department/Job Title and Manager changes between Employee Directory imports equal Python v1 (tools/position_changes_reference.py);
/// they reach Account Review as open review evidence (captured by the next decision) and flag Functional Group memberships for review.</summary>
public sealed class PositionChangeTests : IAsyncLifetime
{
    private static readonly string Fixtures = Path.Combine(AppContext.BaseDirectory, "Fixtures", "position-changes");
    private readonly string _root = Directory.CreateTempSubdirectory("saplens-position-").FullName;
    private readonly string _token = HostSettings.NewToken();
    private WebApplication _app = null!;
    private HttpClient _client = null!;

    public async Task InitializeAsync()
    {
        _app = AuthLensHost.Build(new HostSettings { DataDirectory = Path.Combine(_root, "data"), Port = 0, AccessToken = _token, JsonConsoleLogging = false, PrincipalName = "operator", Mode = HostMode.Desktop });
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

    private static EmployeeDirectory Load(string file)
    {
        var bytes = File.ReadAllBytes(Path.Combine(Fixtures, file));
        return new EmployeeDirectory(EmployeeDirectory.Parse(bytes), file, Convert.ToHexStringLower(SHA256.HashData(bytes)), "");
    }

    [Fact]
    public void Detected_changes_and_notices_equal_python_v1()
    {
        var expected = JsonNode.Parse(File.ReadAllText(Path.Combine(Fixtures, "position-changes.python.json")))!.AsObject();
        string[] generated = ["id", "source_generation", "previous_generation", "previous_imported_at", "current_imported_at"];
        JsonArray Comparable(IEnumerable<JsonNode?> events) => new([.. events.Select(e =>
        {
            var copy = e!.DeepClone().AsObject();
            foreach (var key in generated) copy.Remove(key);
            return (JsonNode)copy;
        })]);
        foreach (var (name, result) in expected)
        {
            var (before, after) = (Load($"{name}_before.txt"), Load($"{name}_after.txt"));
            var (events, notices) = PositionChanges.Detect(before, after, "2026-11-16T08:00:00+00:00");
            var managers = PositionChanges.DetectManagers(before, after, "2026-11-16T08:00:00+00:00");
            Assert.True(JsonNode.DeepEquals(Comparable(result!["events"]!.AsArray()), Comparable(events)), $"{name}: {Comparable(events).ToJsonString()}");
            Assert.True(JsonNode.DeepEquals(Comparable(result["managers"]!.AsArray()), Comparable(managers)), $"{name}: {Comparable(managers).ToJsonString()}");
            Assert.Equal(result["notices"]!.AsArray().Select(n => (string)n!), notices);
        }
    }

    private async Task Select(string source, string text)
    {
        var path = Path.Combine(_root, $"{source}-{Guid.NewGuid():N}.csv");
        File.WriteAllText(path, text);
        var revision = (int)JsonNode.Parse(await _client.GetStringAsync("/api/configuration"))!["settings"]!["revision"]!;
        var response = await _client.PostAsJsonAsync($"/api/data-sources/{source}/select", new { path, revision, mode = "static", confirm_anomalies = true });
        Assert.True(response.IsSuccessStatusCode, await response.Content.ReadAsStringAsync());
    }

    private async Task<JsonObject> Row(string user) =>
        JsonNode.Parse(await _client.GetStringAsync($"/api/account-review?search={user}&include_completed=true"))!["items"]!.AsArray().Single()!.AsObject();

    [Fact]
    public async Task A_directory_change_opens_account_review_evidence_and_flags_functional_group_memberships()
    {
        var settings = JsonNode.Parse(await _client.GetStringAsync("/api/configuration"))!["settings"]!.AsObject();
        settings["features"]!["employee_directory"] = true;
        Assert.Equal(HttpStatusCode.OK, (await _client.PostAsJsonAsync("/api/configuration", settings)).StatusCode);
        var users = "USERNAME;ROLE_NAME;USER_GROUP;FIRST_NAME;LAST_NAME;EMAIL\n" + string.Join('\n', Enumerable.Range(0, 20).Select(i => $"USERP{i:00};ZC:FI:ROLE;GRP;Person;{i};person{i}@example.invalid")) + "\n";
        await Select("users", users);
        await Select("employees", File.ReadAllText(Path.Combine(Fixtures, "changes_before.txt")));
        var (status, _) = (await _client.PostAsJsonAsync("/api/functional-groups", new { name = "Finance" })).StatusCode is var s ? (s, 0) : default;
        Assert.Equal(HttpStatusCode.OK, status);
        var gid = (string)JsonNode.Parse(await _client.GetStringAsync("/api/functional-groups"))!["items"]![0]!["id"]!;
        Assert.Equal(HttpStatusCode.OK, (await _client.PostAsJsonAsync("/api/functional-groups/memberships", new { username = "USERP01", group_id = gid, reviewer = "Ada", expected_revision = 0 })).StatusCode);
        var before = await Row("USERP01");
        Assert.Null(before["position_change"]);
        async Task<List<string>> Search(string term) => [.. JsonNode.Parse(await _client.GetStringAsync($"/api/access/users-selection?search={term}"))!["usernames"]!.AsArray().Select(u => (string)u!)];
        Assert.DoesNotContain("USERP01", await Search("Sales"));

        await Select("employees", File.ReadAllText(Path.Combine(Fixtures, "changes_after.txt")));
        var row = await Row("USERP01");
        // v1 directory_selection: the matched employee's Directory department and job title take part in the User Access free-text search.
        Assert.Contains("USERP01", await Search("Sales"));
        Assert.Contains("USERP01", await Search("Lead"));
        Assert.Empty(await Search("NoSuchDepartment"));
        var change = row["position_change"]!.AsObject();
        Assert.True((bool)change["open"]!);
        Assert.Equal(["department", "title"], change["fields"]!.AsArray().Select(f => (string)f!));
        Assert.Equal(("Finance", "Sales"), ((string)change["previous_department"]!, (string)change["current_department"]!));
        Assert.Equal("High", (string)row["priority"]!);
        Assert.Equal("Needs review", (string)row["review_state"]!);
        // The Functional Group membership needs review (synchronised on read), and Account Review shows that signal too.
        Assert.True((bool)row["classification_review"]!);
        var classification = JsonNode.Parse(await _client.GetStringAsync("/api/functional-groups/users/USERP01"))!["classification"]!;
        Assert.Equal("Needs review", (string)classification["status"]!);
        Assert.Contains("Directory Department changed from Finance to Sales", (string)classification["review"]!["reason"]!);
        var manager = (await Row("USERP04"))["manager_change"]!.AsObject();
        Assert.Equal(("Boss", "Other"), ((string)manager["previous_manager"]!, (string)manager["current_manager"]!));
        var filtered = JsonNode.Parse(await _client.GetStringAsync("/api/account-review?findings=position_change&include_completed=true"))!;
        Assert.Contains(filtered["items"]!.AsArray(), i => (string)i!["username"]! == "USERP01");
        Assert.True((int)filtered["summary"]!["position_changes"]! >= 1);
        var dashboard = JsonNode.Parse(await _client.GetStringAsync("/api/dashboard"))!;
        var metric = dashboard["metrics"]!.AsArray().First(m => (string)m!["id"]! == "position_changes")!;
        Assert.Equal((int)JsonNode.Parse(await _client.GetStringAsync("/api/account-review?include_completed=true"))!["summary"]!["position_changes"]!, (int)metric["value"]!);

        // A decision captures the change it reviewed: the change stays visible but is no longer open.
        var decision = await _client.PostAsJsonAsync("/api/account-review/decision/USERP01",
            new { state = "No action required", reviewer = "Ada", rationale = "Moved to Sales; access reviewed", evidence_version = (string)row["evidence_version"]! });
        Assert.True(decision.IsSuccessStatusCode, await decision.Content.ReadAsStringAsync());
        var reviewed = await Row("USERP01");
        Assert.False((bool)reviewed["position_change"]!["open"]!);
        Assert.Equal("Normal", (string)reviewed["priority"]!);                                      // the Functional Group review is still open
    }
}
