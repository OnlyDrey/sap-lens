using System.Net;
using System.Text;
using System.Text.Json.Nodes;
using Microsoft.AspNetCore.Builder;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;
using AuthLens.Api;
using AuthLens.Application;
using AuthLens.Persistence;

namespace AuthLens.Tests;

/// <summary>Assignment reappearance memory (assignment_lifecycle.py) observed through GET /api/sod/subject, against Python v1. Fixtures/sod/governance/
/// lifecycle.python.json was written by tools/sod_lifecycle_reference.py: a multi-import sequence (review, removal, reappearance, new review, a second
/// cycle, identity change, validity change) through v1's decide(), observe() and subject(). The .NET run imports the same users CSV transforms, with a
/// restart, a failed import and a held (unconfirmed) import in between, which must change nothing.</summary>
public sealed class SodLifecycleTests : IAsyncLifetime
{
    private readonly string _root = Directory.CreateTempSubdirectory("saplens-lifecycle-").FullName;
    private readonly string _token = HostSettings.NewToken();
    private WebApplication _app = null!;
    private HttpClient _client = null!;

    private static string Fixture(params string[] path) => Path.Combine([AppContext.BaseDirectory, "Fixtures", "sod", .. path]);
    private static readonly JsonObject Reference = JsonNode.Parse(File.ReadAllText(Fixture("governance", "lifecycle.python.json")))!.AsObject();
    private static readonly string BaseUsers = File.ReadAllText(Fixture("analysis", "users.sod.txt"));

    public async Task InitializeAsync()
    {
        await StartAsync();
        var roles = string.Concat(File.ReadAllLines(Fixture("analysis", "roles.sod.txt")).Where(l => !l.Contains("ZC:BAD?PATTERN", StringComparison.Ordinal)).Select(l => l + "\n"));
        Assert.Equal("Completed", await Import("roles", roles));
        Assert.Equal("Completed", await Import("sod", File.ReadAllText(Fixture("analysis", "sod.sod.txt"))));
        var settings = JsonNode.Parse(await _client.GetStringAsync("/api/configuration"))!["settings"]!.AsObject();
        settings["features"]!["sod"] = true;
        Assert.Equal(HttpStatusCode.OK, (await Post("/api/configuration", settings)).Status);
    }

    private async Task StartAsync()
    {
        _app = AuthLensHost.Build(new HostSettings { DataDirectory = Path.Combine(_root, "data"), Port = 0, AccessToken = _token, JsonConsoleLogging = false, Mode = HostMode.Desktop });
        await _app.StartAsync();
        _client = new HttpClient { BaseAddress = new Uri(_app.Urls.First()) };
        _client.DefaultRequestHeaders.Add(RequestBoundary.TokenHeader, _token);
    }

    private async Task RestartAsync()
    {
        _client.Dispose();
        await _app.StopAsync();
        await _app.DisposeAsync();
        await StartAsync();
    }

    public async Task DisposeAsync()
    {
        _client.Dispose();
        await _app.StopAsync();
        await _app.DisposeAsync();
        Microsoft.Data.Sqlite.SqliteConnection.ClearAllPools();
        try { Directory.Delete(_root, true); } catch (IOException) { }
    }

    private async Task<string> Import(string source, string csv)
    {
        var job = JsonNode.Parse(await (await _client.PostAsync($"/api/v1/imports/{source}", new StringContent(csv, Encoding.UTF8, "text/csv"))).Content.ReadAsStringAsync())!;
        string status = "";
        for (var i = 0; i < 400; i++)
        {
            status = (string)JsonNode.Parse(await _client.GetStringAsync($"/api/v1/jobs/{(long)job["id"]!}"))!["status"]!;
            if (status is "Completed" or "Failed" or "Cancelled") break;
            await Task.Delay(50);
        }
        return status;
    }

    private async Task<(HttpStatusCode Status, JsonNode? Body)> Post(string path, JsonNode body)
    {
        var request = new HttpRequestMessage(HttpMethod.Post, path) { Content = new StringContent(body.ToJsonString(), Encoding.UTF8, "application/json") };
        request.Headers.Add("Origin", _client.BaseAddress!.GetLeftPart(UriPartial.Authority));
        var response = await _client.SendAsync(request);
        var text = await response.Content.ReadAsStringAsync();
        return (response.StatusCode, text.Length == 0 ? null : JsonNode.Parse(text));
    }

    /// <summary>The reference script's users CSV transforms (drop rows, replace identity evidence, change a role's validity).</summary>
    private static string Transform(JsonObject spec)
    {
        var lines = BaseUsers.Split('\n');
        var header = lines[0].TrimEnd('\r').Split(';');
        int Col(string name) => Array.IndexOf(header, name);
        var drop = (spec["drop"] as JsonArray ?? []).Select(p => ((string)p![0]!, (string)p[1]!)).ToHashSet();
        var identity = spec["identity"] as JsonObject ?? [];
        var validTo = spec["valid_to"] as JsonObject ?? [];
        var result = new StringBuilder(lines[0] + "\n");
        foreach (var raw in lines.Skip(1))
        {
            if (raw.Length == 0) continue;
            var ending = raw.EndsWith('\r') ? "\r" : "";
            var cells = raw.TrimEnd('\r').Split(';');
            var (user, role) = (cells[Col("USERNAME")].Trim().ToUpperInvariant(), cells[Col("ROLE_NAME")]);
            if (drop.Contains((user, role))) continue;
            if (identity[user] is JsonArray person) (cells[Col("FIRST_NAME")], cells[Col("LAST_NAME")], cells[Col("EMAIL")]) = ((string)person[0]!, (string)person[1]!, (string)person[2]!);
            if ((string?)validTo[$"{user}|{role}"] is { } date) cells[Col("ROLE_VALID_TO")] = date;
            result.Append(string.Join(';', cells)).Append(ending).Append('\n');
        }
        return result.ToString();
    }

    private async Task<JsonObject> Subject(string user)
    {
        var response = await _client.GetAsync($"/api/sod/subject?user={Uri.EscapeDataString(user)}");
        var text = await response.Content.ReadAsStringAsync();
        Assert.True(response.StatusCode == HttpStatusCode.OK, text);
        return JsonNode.Parse(text)!.AsObject();
    }

    private static JsonObject Comparable(JsonObject subject)
    {
        JsonArray Clean(JsonNode rows, params string[] drop) => new([.. rows.AsArray().Select(r => { var copy = r!.DeepClone().AsObject(); foreach (var d in drop) copy.Remove(d); return (JsonNode?)copy; })]);
        var overview = subject["overview"]!;
        return new JsonObject
        {
            ["user"] = subject["user"]!.DeepClone(), ["groups"] = subject["groups"]!.DeepClone(),
            ["assignments"] = Clean(overview["assignments"]!, "event", "remediation_verification"), ["activities"] = Clean(overview["activities"]!, "event"),
            ["risks"] = Clean(overview["risks"]!, "event", "risk_review_event"),
        };
    }

    private async Task Keep(string user, string role)
    {
        var subject = await Subject(user);
        var row = subject["overview"]!["assignments"]!.AsArray().Single(a => (string)a!["role"]! == role)!;
        var body = new JsonObject
        {
            ["expected_revision"] = subject["revision"]!.DeepClone(), ["expected_generation"] = subject["generation"]!.DeepClone(), ["decision"] = "Keep",
            ["justification"] = "Synthetic justification",
            ["items"] = new JsonArray(new JsonObject { ["key"] = row["id"]!.DeepClone(), ["user"] = user, ["ref"] = role, ["evidence_version"] = row["evidence_version"]!.DeepClone() }),
        };
        var (status, result) = await Post("/api/sod/decisions/assignment", body);
        Assert.True(status == HttpStatusCode.OK, result?.ToJsonString());
    }

    private async Task<int> AssignmentEvents()
    {
        await using var db = await _app.Services.GetRequiredService<IDbContextFactory<AuthLensDb>>().CreateDbContextAsync();
        return await db.SodDecisionEvents.CountAsync(e => e.Kind == "assignment");
    }

    [Fact]
    public async Task Removal_reappearance_and_identity_change_follow_python_v1_through_imports_and_restarts()
    {
        var user = (string)Reference["user"]!;
        var failures = new List<string>();
        foreach (var step in Reference["steps"]!.AsArray().Select(s => s!.AsObject()))
        {
            var name = (string)step["name"]!;
            if (step["users"] is JsonObject spec) Assert.Equal("Completed", await Import("users", Transform(spec)));
            foreach (var role in step["keep"]!.AsArray().Select(r => (string)r!)) await Keep(user, role);
            var actual = Comparable(await Subject(user));
            if (!JsonNode.DeepEquals(step["subject"], actual))
            {
                var want = step["subject"]!["assignments"]!.ToJsonString();
                failures.Add($"{name}: assignments {actual["assignments"]!.ToJsonString()[..Math.Min(700, actual["assignments"]!.ToJsonString().Length)]} vs python {want[..Math.Min(700, want.Length)]}");
                foreach (var part in new[] { "user", "groups", "activities", "risks" })
                    if (!JsonNode.DeepEquals(step["subject"]![part], actual[part])) failures.Add($"{name}: {part} differs");
            }
            Assert.Equal((int)step["events"]!, await AssignmentEvents());     // decisions are only ever appended; reappearance writes none

            switch (name)
            {
                case "removed":
                    // A restart between imports keeps the memory; a failed and a held (unconfirmed) import change nothing.
                    await RestartAsync();
                    Assert.Equal("Failed", await Import("users", "NOT;A;USERS;FILE\n\u0000"));
                    var held = string.Join('\n', BaseUsers.Split('\n').Take(3)) + "\n";
                    Assert.Equal("Completed", await Import("users", held));
                    await using (var db = await _app.Services.GetRequiredService<IDbContextFactory<AuthLensDb>>().CreateDbContextAsync())
                        Assert.True(await db.Datasets.AnyAsync(d => d.Source == "users" && d.Status == DatasetStatus.Held), "the drastic users file must be held, not activated");
                    Assert.True(JsonNode.DeepEquals(step["subject"], Comparable(await Subject(user))), "a failed or held import changed the review state");
                    break;
                case "reappeared":
                    await RestartAsync();
                    Assert.True(JsonNode.DeepEquals(step["subject"], Comparable(await Subject(user))), "the reappearance did not survive a restart");
                    break;
            }
        }
        Assert.True(failures.Count == 0, string.Join("\n", failures));

        // History is never rewritten: the reappeared assignment keeps every earlier decision, newest first.
        var reappeared = (await Subject(user))["overview"]!["assignments"]!.AsArray().Single(a => (string)a!["role"]! == (string)Reference["roles"]![0]!)!;
        var history = JsonNode.Parse(await _client.GetStringAsync($"/api/sod/decisions/assignment/history?key={reappeared["id"]}"))!["items"]!.AsArray();
        Assert.Equal(3, history.Count);
        Assert.All(history, e => Assert.Equal("Keep", (string)e!["decision"]!));
        foreach (var e in history)
        {
            var evidence = JsonNode.Parse(await _client.GetStringAsync($"/api/sod/decisions/assignment/evidence?key={reappeared["id"]}&event_id={e!["event_id"]}"))!;
            Assert.Equal((string)reappeared["id"]!, (string)evidence["evidence"]!["id"]!);
        }
        Assert.True((await _app.Services.GetRequiredService<SodDecisionStore>().VerifyChainAsync(CancellationToken.None)).Ok);
    }

    [Fact]
    public async Task Damaged_lifecycle_memory_makes_every_assignment_decision_outdated_until_rebaseline()
    {
        var user = (string)Reference["user"]!;
        var roles = Reference["roles"]!.AsArray().Select(r => (string)r!).ToList();
        Assert.Equal("Completed", await Import("users", BaseUsers));
        foreach (var role in roles) await Keep(user, role);
        Assert.All((await Subject(user))["overview"]!["assignments"]!.AsArray(), a => Assert.Equal("Keep", (string)a!["decision"]!));
        await using (var db = await _app.Services.GetRequiredService<IDbContextFactory<AuthLensDb>>().CreateDbContextAsync())
            await db.Database.ExecuteSqlRawAsync("UPDATE SodDocuments SET Json = replace(Json, '\"observed_source\":\"', '\"observed_source\":\"tampered') WHERE Name = 'assignment-lifecycle'");
        var rows = (await Subject(user))["overview"]!["assignments"]!.AsArray();
        Assert.All(rows, a => Assert.Equal("Outdated", (string)a!["decision"]!));
        Assert.All(rows, a => Assert.Equal(AssignmentLifecycle.Unavailable, (string)a!["decision_summary"]!["basis"]!));
        Assert.Equal("blocked", await _app.Services.GetRequiredService<AssignmentLifecycle>().ObserveAsync(CancellationToken.None));   // never repaired silently
        Assert.Equal((HttpStatusCode)422, (await Post("/api/storage/lifecycle/rebaseline", new JsonObject { ["confirm"] = false })).Status);
        Assert.Equal((HttpStatusCode)422, (await Post("/api/storage/lifecycle/rebaseline", new JsonObject())).Status);
        Assert.All((await Subject(user))["overview"]!["assignments"]!.AsArray(), a => Assert.Equal("Outdated", (string)a!["decision"]!));   // unchanged until confirmed
        var (status, result) = await Post("/api/storage/lifecycle/rebaseline", new JsonObject { ["confirm"] = true });
        Assert.True(status == HttpStatusCode.OK, result?.ToJsonString());
        Assert.Equal("ok", (string)result!["review_continuity"]!["state"]!);
        await using (var db = await _app.Services.GetRequiredService<IDbContextFactory<AuthLensDb>>().CreateDbContextAsync())
        {
            Assert.True(await db.SodDocuments.AnyAsync(d => d.Name.StartsWith("assignment-lifecycle-before-")));                     // the damaged copy is kept aside
            var (data, _, _) = await AssignmentLifecycle.LoadAsync(db, CancellationToken.None);
            Assert.Equal("Local reviewer", (string)data["baseline"]!["by"]!);                                                      // attributed to the Desktop profile
        }
        Assert.All((await Subject(user))["overview"]!["assignments"]!.AsArray(), a => Assert.Equal("Keep", (string)a!["decision"]!));
        Assert.Equal(2, await AssignmentEvents());
    }

    private async Task<JsonObject> Health(string query = "") => JsonNode.Parse(await _client.GetStringAsync("/api/data-health" + query))!.AsObject();
    private static JsonObject Finding(JsonObject health, string id) => health["findings"]!.AsArray().Single(f => (string)f!["id"]! == id)!.AsObject();

    /// <summary>v1 test_reappeared_assignments_awaiting_review_are_listed_until_a_new_decision and test_problems_surface_in_data_health_diagnostics.</summary>
    [Fact]
    public async Task Data_health_lists_reappeared_assignments_until_a_new_decision_and_surfaces_untrusted_memory()
    {
        var user = (string)Reference["user"]!;
        var role = (string)Reference["roles"]![0]!;
        Assert.Equal("Completed", await Import("users", BaseUsers));
        await Keep(user, role);
        var health = await Health();
        Assert.Equal((0, 0), ((int)Finding(health, "lifecycle_integrity")["count"]!, (int)Finding(health, "reappeared_assignments")["count"]!));
        Assert.Equal("Completed", await Import("users", Transform(new JsonObject { ["drop"] = new JsonArray(new JsonArray(user, role)) })));
        Assert.Equal("Completed", await Import("users", BaseUsers));
        var listed = await Health("?finding=reappeared_assignments");
        Assert.Equal([(user, role, "reappeared")], listed["items"]!.AsArray().Select(i => ((string)i!["username"]!, (string)i["identifier"]!, (string)i["reason"]!)));
        Assert.Equal("information", (string)Finding(listed, "reappeared_assignments")["severity"]!);
        await Keep(user, role);
        Assert.Empty((await Health("?finding=reappeared_assignments"))["items"]!.AsArray());

        await using (var db = await _app.Services.GetRequiredService<IDbContextFactory<AuthLensDb>>().CreateDbContextAsync())
            await db.Database.ExecuteSqlRawAsync("UPDATE SodDocuments SET Json = 'garbage' WHERE Name = 'assignment-lifecycle'");
        health = await Health("?finding=lifecycle_integrity");
        var integrity = Finding(health, "lifecycle_integrity");
        Assert.Equal((1, "warning"), ((int)integrity["count"]!, (string)integrity["severity"]!));
        Assert.Contains("failed its integrity check", (string)integrity["explanation"]!);
        Assert.Equal((user, role, "corrupt"), ((string)health["items"]![0]!["username"]!, (string)health["items"]![0]!["identifier"]!, (string)health["items"]![0]!["reason"]!));
        Assert.Equal(0, (int)Finding(health, "reappeared_assignments")["count"]!);
        Assert.Equal("corrupt", (string)JsonNode.Parse(await _client.GetStringAsync("/api/diagnostics/export"))!["review_continuity"]!);
    }

    /// <summary>The import itself observes (v1 csv_lifecycle calls observe() after the commit): with no review read in between, the memory records the
    /// removal of a decided assignment.</summary>
    [Fact]
    public async Task A_committed_import_observes_the_memory_without_any_review_read()
    {
        var user = (string)Reference["user"]!;
        var role = (string)Reference["roles"]![0]!;
        Assert.Equal("Completed", await Import("users", BaseUsers));
        await Keep(user, role);
        Assert.Equal("Completed", await Import("users", Transform(new JsonObject { ["drop"] = new JsonArray(new JsonArray(user, role)) })));
        string? state = null;
        for (var i = 0; i < 100 && state != "absent"; i++)
        {
            await using var db = await _app.Services.GetRequiredService<IDbContextFactory<AuthLensDb>>().CreateDbContextAsync();
            var (data, _, _) = await AssignmentLifecycle.LoadAsync(db, CancellationToken.None);
            state = data["items"]!.AsObject().Select(p => (string?)p.Value!["state"]).FirstOrDefault(s => s == "absent");
            if (state != "absent") await Task.Delay(50);
        }
        Assert.Equal("absent", state);
    }

    [Fact]
    public async Task Rebaseline_is_refused_for_a_shared_access_token()
    {
        _client.Dispose();
        await _app.StopAsync();
        await _app.DisposeAsync();
        _app = AuthLensHost.Build(new HostSettings { DataDirectory = Path.Combine(_root, "data"), Port = 0, AccessToken = _token, JsonConsoleLogging = false, Mode = HostMode.Server });
        await _app.StartAsync();
        _client = new HttpClient { BaseAddress = new Uri(_app.Urls.First()) };
        _client.DefaultRequestHeaders.Add(RequestBoundary.TokenHeader, _token);
        Assert.Equal(HttpStatusCode.Forbidden, (await Post("/api/storage/lifecycle/rebaseline", new JsonObject { ["confirm"] = true })).Status);
        await using var db = await _app.Services.GetRequiredService<IDbContextFactory<AuthLensDb>>().CreateDbContextAsync();
        Assert.False(await db.SodDocuments.AnyAsync(d => d.Name.StartsWith("assignment-lifecycle-before-")));
    }

    [Fact]
    public async Task Subject_refuses_unknown_users_and_unmigrated_contexts()
    {
        Assert.Equal("Completed", await Import("users", BaseUsers));
        Assert.Equal(HttpStatusCode.NotFound, (await _client.GetAsync("/api/sod/subject?user=NOBODY")).StatusCode);
        Assert.Equal(HttpStatusCode.NotFound, (await _client.GetAsync($"/api/sod/subject?user={Reference["user"]}&risk=NO_RISK")).StatusCode);
        Assert.Equal((HttpStatusCode)422, (await _client.GetAsync("/api/sod/subject")).StatusCode);
        Assert.Equal(HttpStatusCode.NotFound, (await _client.GetAsync($"/api/sod/subject?user={Reference["user"]}&context=P2026")).StatusCode);   // unknown review period
    }
}
