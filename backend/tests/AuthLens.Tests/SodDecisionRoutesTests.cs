using System.Net;
using System.Text;
using System.Text.Json.Nodes;
using Microsoft.AspNetCore.Builder;
using AuthLens.Api;

namespace AuthLens.Tests;

/// <summary>POST /api/sod/decisions/{kind}, GET /history and /evidence (routers/sod_governance.py) on the synthetic small dataset of Fixtures/sod/analysis.
/// The evidence a decision stores is compared with Python v1 by content address (Fixtures/sod/governance/items.python.json, v1's _locate); the
/// refusals follow v1's decide(): nothing is written when the evidence generation, an item or the revision is stale.</summary>
public sealed class SodDecisionRoutesTests : IAsyncLifetime
{
    private readonly string _root = Directory.CreateTempSubdirectory("saplens-sodroutes-").FullName;
    private readonly string _token = HostSettings.NewToken();
    private WebApplication _app = null!;
    private HttpClient _client = null!;

    private static string Fixture(params string[] path) => Path.Combine([AppContext.BaseDirectory, "Fixtures", "sod", .. path]);
    private static readonly JsonObject Items = JsonNode.Parse(File.ReadAllText(Fixture("governance", "items.python.json")))!.AsObject();

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

    private async Task<string> Generation() => (string)JsonNode.Parse(await _client.GetStringAsync("/api/sod/analysis?limit=1"))!["generation"]!;

    private static JsonObject Item(string kind, int skip = 0) => Items["items"]!.AsArray().Select(i => i!.AsObject()).Where(i => (string)i["kind"]! == kind).Skip(skip).First();

    private static JsonObject Body(JsonObject item, string decision, int revision, string generation, string justification = "Synthetic justification") => new()
    {
        ["expected_revision"] = revision, ["expected_generation"] = generation, ["decision"] = decision, ["justification"] = justification,
        ["items"] = new JsonArray(new JsonObject { ["key"] = item["key"]!.DeepClone(), ["user"] = item["user"]!.DeepClone(), ["ref"] = item["ref"]!.DeepClone(), ["evidence_version"] = item["evidence_version"]!.DeepClone() }),
    };

    private async Task<int> Revision(string kind, JsonObject item) => (await HistoryOf(kind, item))["items"]!.AsArray().Count;
    private async Task<JsonNode> HistoryOf(string kind, JsonObject item) => JsonNode.Parse(await _client.GetStringAsync($"/api/sod/decisions/{kind}/history?key={item["key"]}"))!;

    [Fact]
    public async Task Decisions_store_python_v1_evidence_and_survive_restart()
    {
        var generation = await Generation();
        var revision = 0;
        var profile = JsonNode.Parse(await _client.GetStringAsync("/api/reviewer-profile"))!["identity"]!;
        foreach (var (kind, decision) in new[] { ("assignment", "Keep"), ("activity", "Approved"), ("acceptance", "Accepted"), ("risk", "Investigate") })
        {
            var item = Item(kind);
            var body = Body(item, decision, revision, generation);
            if (kind == "acceptance") body["approver"] = "Ignored on Desktop";
            var (status, result) = await Post($"/api/sod/decisions/{kind}", body);
            Assert.True(status == HttpStatusCode.OK, $"{kind}: {result?.ToJsonString()}");
            revision = (int)result!["revision"]!;
            var e = result["events"]![0]!;
            // The evidence content address equals v1's for the same item (assignment, activity, enriched finding).
            Assert.Equal((string)item["address"]!, (string)e["evidence_snapshot"]!);
            Assert.Equal((string)item["evidence_version"]!, (string)e["evidence_version"]!);
            Assert.Equal((string)profile["display_name"]!, (string)e["reviewer"]!);                 // v1 actor(): the Desktop profile name
            Assert.Equal((string)profile["id"]!, (string)e["actor_identity"]!["id"]!);
            Assert.Equal(kind == "acceptance" ? (string)profile["display_name"]! : "", (string)e["approver"]!);
            Assert.Equal(V1SodDecisions.IdentityNotice, (string)result["reviewer_identity"]!);
            if (kind == "assignment")
            {
                var confirmed = result["confirmed_assignments"]![(string)item["key"]!]!;
                Assert.Equal("Keep", (string)confirmed["decision"]!);
                Assert.Equal("Approved", (string)confirmed["decision_summary"]!["label"]!);
                Assert.True((bool)confirmed["review_coverage"]!["reviewed"]!);
            }
        }
        Assert.Equal(4, revision);

        // A second decision on the same assignment: history newest first, previous decision recorded, evidence retrievable and verified.
        var assignment = Item("assignment");
        var (second, secondBody) = await Post("/api/sod/decisions/assignment", Body(assignment, "Remove", 4, generation));
        Assert.Equal(HttpStatusCode.OK, second);
        Assert.Equal("Keep", (string)secondBody!["events"]![0]!["previous_decision"]!);
        Assert.Equal("Removal required", (string)secondBody["confirmed_assignments"]![(string)assignment["key"]!]!["decision"]!);

        await RestartAsync(HostMode.Desktop);
        var history = await HistoryOf("assignment", assignment);
        Assert.Equal(["Remove", "Keep"], history["items"]!.AsArray().Select(e => (string)e!["decision"]!));
        var verification = history["verification"]!;
        Assert.Equal("Not verified", (string)verification["status"]!);
        Assert.Equal("Still present in current evidence", (string)verification["reason"]!);   // the assignment is still imported
        Assert.Equal((string)history["items"]![0]!["event_id"]!, (string)verification["decision_event_id"]!);
        var newest = history["items"]![0]!;
        var evidence = JsonNode.Parse(await _client.GetStringAsync($"/api/sod/decisions/assignment/evidence?key={assignment["key"]}&event_id={newest["event_id"]}"))!;
        Assert.Equal((string)assignment["key"]!, (string)evidence["evidence"]!["id"]!);
        Assert.True(JsonNode.DeepEquals(newest, evidence["event"]));
        Assert.Equal(HttpStatusCode.NotFound, (await _client.GetAsync($"/api/sod/decisions/assignment/evidence?key={assignment["key"]}&event_id={new string('a', 32)}")).StatusCode);
        Assert.Null((await HistoryOf("activity", Item("activity")))["verification"]);
    }

    [Fact]
    public async Task Stale_invalid_or_unsupported_requests_are_refused_and_write_nothing()
    {
        var generation = await Generation();
        var item = Item("assignment");
        async Task Refused(HttpStatusCode expected, string kind, JsonObject body)
        {
            var (status, detail) = await Post($"/api/sod/decisions/{kind}", body);
            Assert.True(status == expected, $"{expected} expected, {status}: {detail?.ToJsonString()}");
        }
        JsonObject Changed(Action<JsonObject> change) { var body = Body(item, "Keep", 0, generation); change(body); return body; }

        await Refused(HttpStatusCode.Conflict, "assignment", Body(item, "Keep", 0, new string('0', 64)));                                     // evidence generation changed
        await Refused(HttpStatusCode.Conflict, "assignment", Body(item, "Keep", 3, generation));                                              // stale revision
        await Refused(HttpStatusCode.Conflict, "assignment", Changed(b => b["items"]![0]!["evidence_version"] = new string('c', 64)));      // evidence changed
        await Refused(HttpStatusCode.Conflict, "assignment", Changed(b => b["items"]![0]!["ref"] = "SOME_OTHER_ROLE"));                     // role no longer matches
        await Refused(HttpStatusCode.Conflict, "assignment", Changed(b => b["items"]![0]!["user"] = "NOBODY"));
        await Refused((HttpStatusCode)422, "assignment", Changed(b => b["decision"] = "Approved"));                                          // not an assignment decision
        await Refused((HttpStatusCode)422, "assignment", Changed(b => b["justification"] = ""));
        await Refused((HttpStatusCode)422, "assignment", Changed(b => b["justification"] = "   "));                                          // blank after stripping
        await Refused((HttpStatusCode)422, "assignment", Changed(b => b["extra"] = 1));
        await Refused((HttpStatusCode)422, "assignment", Changed(b => b["items"]![0]!["key"] = "ABC"));
        await Refused((HttpStatusCode)422, "assignment", Changed(b => b["items"] = new JsonArray()));
        await Refused((HttpStatusCode)422, "assignment", Changed(b => b["approver"] = "Boss"));                                              // approver only for acceptance
        await Refused((HttpStatusCode)422, "role", Body(item, "Keep", 0, generation));
        await Refused((HttpStatusCode)422, "activity", Body(Item("activity"), "Conditional", 0, generation));                                // conditions required
        await Refused((HttpStatusCode)422, "acceptance", Changed(b => { b["expires"] = "2000-01-01"; b["decision"] = "Accepted"; b["items"] = Body(Item("acceptance"), "Accepted", 0, generation)["items"]!.DeepClone(); }));
        await Refused(HttpStatusCode.NotFound, "assignment", Changed(b => b["context"] = "P2026-Q1"));                                       // an unknown review period (v1: 404)

        Assert.Empty((await HistoryOf("assignment", item))["items"]!.AsArray());
        var (status, ok) = await Post("/api/sod/decisions/assignment", Body(item, "Keep", 0, generation));
        Assert.True(status == HttpStatusCode.OK, ok?.ToJsonString());
        Assert.Equal(1, (int)ok!["revision"]!);                                                                                             // nothing above was written
    }

    [Fact]
    public async Task A_shared_access_token_cannot_record_attributed_decisions()
    {
        var generation = await Generation();
        await RestartAsync(HostMode.Server);
        var (status, body) = await Post("/api/sod/decisions/assignment", Body(Item("assignment"), "Keep", 0, generation));
        Assert.Equal(HttpStatusCode.Forbidden, status);
        Assert.Contains("individual sign-in", (string)body!["detail"]!);
        Assert.Empty((await HistoryOf("assignment", Item("assignment")))["items"]!.AsArray());
    }
}
