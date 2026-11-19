using System.Net;
using System.Text;
using System.Text.Json.Nodes;
using Microsoft.AspNetCore.Builder;
using Microsoft.Extensions.DependencyInjection;
using AuthLens.Api;
using AuthLens.Application;

namespace AuthLens.Tests;

/// <summary>POST /api/sod/decisions/assignment/bulk and POST /api/sod/remediation/actions against Python v1. Fixtures/sod/governance/bulk.python.json was
/// written by tools/sod_bulk_reference.py: a sequence of v1 route calls (mixed recorded/skipped/failed outcomes, protected decisions, investigation with
/// tracked actions, atomic refusal and replacement, stale revision and generation, validation, action create/update/complete/not found). Items are named
/// by user and role and resolved through GET /api/sod/subject.</summary>
public sealed class SodBulkReviewTests : IAsyncLifetime
{
    private readonly string _root = Directory.CreateTempSubdirectory("saplens-bulk-").FullName;
    private readonly string _token = HostSettings.NewToken();
    private WebApplication _app = null!;
    private HttpClient _client = null!;

    private static string Fixture(params string[] path) => Path.Combine([AppContext.BaseDirectory, "Fixtures", "sod", .. path]);
    private static readonly JsonObject Reference = JsonNode.Parse(File.ReadAllText(Fixture("governance", "bulk.python.json")))!.AsObject();

    public async Task InitializeAsync()
    {
        await StartAsync(HostMode.Desktop);
        foreach (var source in new[] { "roles", "users", "sod" })
        {
            var job = JsonNode.Parse(await (await _client.PostAsync($"/api/v1/imports/{source}", new StringContent(File.ReadAllText(Fixture("analysis", source + ".sod.txt")), Encoding.UTF8, "text/csv"))).Content.ReadAsStringAsync())!;
            for (var i = 0; i < 400 && (string)JsonNode.Parse(await _client.GetStringAsync($"/api/v1/jobs/{(long)job["id"]!}"))!["status"]! != "Completed"; i++) await Task.Delay(50);
        }
        var settings = JsonNode.Parse(await _client.GetStringAsync("/api/configuration"))!["settings"]!.AsObject();
        settings["features"]!["sod"] = true;
        Assert.Equal(HttpStatusCode.OK, (await Post("/api/configuration", settings)).Status);
        // v1's actor() falls back to the given actor name; the Desktop attributes to the reviewer profile, named the same here.
        var profile = JsonNode.Parse(await _client.GetStringAsync("/api/reviewer-profile"))!;
        Assert.Equal(HttpStatusCode.OK, (await Post("/api/reviewer-profile", new JsonObject { ["display_name"] = "Synthetic actor", ["expected_revision"] = profile["revision"]!.DeepClone() })).Status);
    }

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

    private async Task<(HttpStatusCode Status, JsonNode? Body)> Post(string path, JsonNode body)
    {
        var request = new HttpRequestMessage(HttpMethod.Post, path) { Content = new StringContent(body.ToJsonString(), Encoding.UTF8, "application/json") };
        request.Headers.Add("Origin", _client.BaseAddress!.GetLeftPart(UriPartial.Authority));
        var response = await _client.SendAsync(request);
        var text = await response.Content.ReadAsStringAsync();
        return (response.StatusCode, text.Length == 0 ? null : JsonNode.Parse(text));
    }

    private async Task<JsonObject> Subject(string user) => JsonNode.Parse(await _client.GetStringAsync($"/api/sod/subject?user={Uri.EscapeDataString(user)}"))!.AsObject();

    private async Task<JsonObject> Resolve(JsonArray spec)
    {
        var (user, role) = ((string)spec[0]!, (string)spec[1]!);
        var row = (await Subject(user))["overview"]!["assignments"]!.AsArray().Single(a => (string)a!["role"]! == role)!;
        var item = new JsonObject { ["key"] = row["id"]!.DeepClone(), ["user"] = user, ["ref"] = role, ["evidence_version"] = row["evidence_version"]!.DeepClone() };
        if (spec.Count > 2 && (string?)spec[2] == "stale_version") item["evidence_version"] = new string('c', 64);
        if (spec.Count > 2 && (string?)spec[2] == "unknown_key") item["key"] = new string('d', 64);
        return item;
    }

    private static JsonObject StripAction(JsonObject action)
    {
        var copy = action.DeepClone().AsObject();
        foreach (var field in new[] { "id", "created", "modified" }) copy.Remove(field);
        foreach (var h in copy["history"]!.AsArray().Select(h => h!.AsObject())) { h.Remove("timestamp"); h.Remove("actor_identity"); }
        return copy;
    }

    [Fact]
    public async Task Bulk_review_and_remediation_actions_equal_python_v1()
    {
        var user = (string)Reference["user"]!;
        var failures = new List<string>();
        string? lastAction = null;
        foreach (var step in Reference["steps"]!.AsArray().Select(s => s!.AsObject()))
        {
            var name = (string)step["name"]!;
            var subject = await Subject(user);
            var revision = (int)subject["revision"]! + ((int?)step["revision_offset"] ?? 0);
            JsonObject actual;
            if ((string)step["call"]! == "bulk")
            {
                var items = new JsonArray();
                foreach (var spec in step["items"]!.AsArray()) items.Add(await Resolve(spec!.AsArray()));
                var body = new JsonObject
                {
                    ["expected_revision"] = revision, ["expected_generation"] = (string?)step["generation"] ?? (string)subject["generation"]!, ["items"] = items,
                    ["action"] = step["action"]!.DeepClone(), ["reviewer"] = "Synthetic actor", ["justification"] = "Synthetic justification",
                    ["replace_existing"] = (bool?)step["replace_existing"] ?? false, ["atomic"] = (bool?)step["atomic"] ?? false, ["track_action"] = (bool?)step["track_action"] ?? false,
                };
                var (status, result) = await Post("/api/sod/decisions/assignment/bulk", body);
                actual = status == HttpStatusCode.OK
                    ? new JsonObject
                    {
                        ["status"] = 200, ["action"] = result!["action"]!.DeepClone(), ["recorded"] = result["recorded"]!.DeepClone(), ["skipped"] = result["skipped"]!.DeepClone(),
                        ["failed"] = result["failed"]!.DeepClone(), ["tracked_actions"] = result["tracked_actions"]!.DeepClone(), ["revision"] = result["revision"]!.DeepClone(),
                    }
                    : new JsonObject { ["status"] = (int)status, ["detail"] = result?["detail"] is JsonValue d ? (string?)d : null };
            }
            else
            {
                var update = (string?)step["update"];
                var body = new JsonObject
                {
                    ["expected_revision"] = revision, ["actor"] = "Synthetic actor", ["action_id"] = update == "last" ? lastAction : update ?? "", ["user"] = step["user"]!.DeepClone(),
                    ["assignment_id"] = step["assignment"] is null ? "" : (await Resolve(new JsonArray(step["user"]!.DeepClone(), step["assignment"]!.DeepClone())))["key"]!.DeepClone(),
                    ["role"] = (string?)step["assignment"] ?? "", ["recommended"] = step["recommended"]!.DeepClone(), ["reason"] = step["reason"]!.DeepClone(),
                    ["owner"] = (string?)step["owner"] ?? "", ["due_date"] = step["due_date"]?.DeepClone(), ["status"] = (string?)step["status"] ?? "Open",
                    ["completion_evidence"] = (string?)step["completion_evidence"] ?? "",
                };
                var (status, result) = await Post("/api/sod/remediation/actions", body);
                if (status == HttpStatusCode.OK) lastAction = (string)result!["action"]!["id"]!;
                actual = status == HttpStatusCode.OK
                    ? new JsonObject { ["status"] = 200, ["revision"] = result!["revision"]!.DeepClone(), ["action"] = StripAction(result["action"]!.AsObject()) }
                    : new JsonObject { ["status"] = (int)status, ["detail"] = result?["detail"] is JsonValue d ? (string?)d : null };
            }
            var want = step["outcome"]!.DeepClone().AsObject();
            // v1 reports pydantic validation failures with pydantic's own text: the status is compared for those.
            if ((int)want["status"]! == 422 && ((string?)want["detail"] ?? "").Contains("validation error", StringComparison.Ordinal)) { want["detail"] = null; actual["detail"] = null; }
            if (!JsonNode.DeepEquals(want, actual)) failures.Add($"{name}: expected {want.ToJsonString()} got {actual.ToJsonString()}");
        }
        Assert.True(failures.Count == 0, string.Join("\n", failures));

        // After a restart: the same histories (newest first), the same tracked actions, bulk events tagged with their operation, the chain intact.
        await RestartAsync(HostMode.Desktop);
        var rows = (await Subject(user))["overview"]!["assignments"]!.AsArray();
        foreach (var (role, decisions) in Reference["histories"]!.AsObject())
        {
            var key = (string)rows.Single(r => (string)r!["role"]! == role)!["id"]!;
            var history = JsonNode.Parse(await _client.GetStringAsync($"/api/sod/decisions/assignment/history?key={key}"))!["items"]!.AsArray();
            Assert.Equal(decisions!.AsArray().Select(d => (string)d!), history.Select(e => (string)e!["decision"]!));
            Assert.Equal(Reference["bulk_tagged"]![role]!.AsArray().Select(v => (bool)v!), history.Select(e => (string)e!["bulk_operation_id"]! != "").Distinct().Order());
        }
        var actions = await _app.Services.GetRequiredService<SodDecisionStore>().ActionsAsync("current", CancellationToken.None);
        Assert.True(JsonNode.DeepEquals(Reference["actions"], new JsonArray([.. actions.Select(a => (JsonNode?)StripAction(a))])), new JsonArray([.. actions.Select(a => (JsonNode?)StripAction(a))]).ToJsonString());
        Assert.Equal((int)Reference["revision"]!, await _app.Services.GetRequiredService<SodDecisionStore>().RevisionAsync(CancellationToken.None));
        Assert.True((await _app.Services.GetRequiredService<SodDecisionStore>().VerifyChainAsync(CancellationToken.None)).Ok);
    }

    [Fact]
    public async Task A_shared_access_token_cannot_review_in_bulk_or_track_actions()
    {
        var subject = await Subject((string)Reference["user"]!);
        var item = await Resolve(new JsonArray(Reference["user"]!.DeepClone(), Reference["roles"]![0]!.DeepClone()));
        await RestartAsync(HostMode.Server);
        var bulk = new JsonObject
        {
            ["expected_revision"] = 0, ["expected_generation"] = subject["generation"]!.DeepClone(), ["items"] = new JsonArray(item), ["action"] = "Keep", ["justification"] = "x",
        };
        Assert.Equal(HttpStatusCode.Forbidden, (await Post("/api/sod/decisions/assignment/bulk", bulk)).Status);
        var action = new JsonObject { ["expected_revision"] = 0, ["actor"] = "x", ["user"] = Reference["user"]!.DeepClone(), ["recommended"] = "Maintain access", ["reason"] = "x" };
        Assert.Equal(HttpStatusCode.Forbidden, (await Post("/api/sod/remediation/actions", action)).Status);
        Assert.Equal(0, await _app.Services.GetRequiredService<SodDecisionStore>().RevisionAsync(CancellationToken.None));
    }
}
