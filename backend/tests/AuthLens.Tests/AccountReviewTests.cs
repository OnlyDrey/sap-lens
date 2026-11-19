using System.Net;
using System.Net.Http.Json;
using System.Text;
using System.Text.Json.Nodes;
using Microsoft.AspNetCore.Builder;
using Microsoft.Extensions.DependencyInjection;
using AuthLens.Api;
using AuthLens.Application;
using AuthLens.Application.Accounts;

namespace AuthLens.Tests;

/// <summary>Account Review (port of account_review.py and routers/account_review.py) on the append-only, hash-chained review store, with per-user
/// attribution from v1 accounts. Synthetic users only.</summary>
public sealed class AccountReviewTests : IAsyncLifetime
{
    private const string Password = "Synthetic review password 123";
    private readonly string _root = Directory.CreateTempSubdirectory("saplens-review-").FullName;
    private readonly string _token = HostSettings.NewToken();
    private WebApplication _app = null!;
    private Uri _base = null!;

    public async Task InitializeAsync()
    {
        _app = AuthLensHost.Build(new HostSettings { DataDirectory = Path.Combine(_root, "data"), Port = 0, AccessToken = _token, JsonConsoleLogging = false, Authentication = AuthenticationMode.Accounts });
        await _app.StartAsync();
        _base = new Uri(_app.Urls.First());
        var store = _app.Services.GetRequiredService<AccountStore>();
        var (code, _, _) = await store.IssueAsync();
        await store.CompleteAsync(code, "admin", "Admin", Password, false);
        var admin = (await store.LoginAsync("admin", Password, "fixture")).Principal;
        await store.CreateUserAsync(admin, "reviewer1", "Reviewer One", "reviewer", Password);
        await store.CreateUserAsync(admin, "viewer1", "Viewer One", "viewer", Password);
    }

    public async Task DisposeAsync()
    {
        await _app.StopAsync();
        await _app.DisposeAsync();
        Microsoft.Data.Sqlite.SqliteConnection.ClearAllPools();
        try { Directory.Delete(_root, true); } catch (IOException) { }
    }

    private const string Active = "20000101;99991231";
    private static string Users(bool withSecond = true, string secondLock = "") => Csv.UsersHeader + "\n"
        + $"USER0001;ZC:FI:ROLE_0001;GRP_FIN;Ada;One;ada@example.invalid;20000101;99991231;{Active};;A\n"
        + (withSecond ? $"USER0002;ZC:FI:ROLE_0002;GRP_FIN;Bo;Two;bo@example.invalid;20000101;99991231;{Active};{secondLock};A\n" : "")
        + $"SVC0001;ZC:FI:ROLE_0001;GRP_TECH;;;;20000101;99991231;{Active};;S\n";

    private async Task Import(string source, string csv)
    {
        using var client = new HttpClient { BaseAddress = _base };
        client.DefaultRequestHeaders.Add(RequestBoundary.TokenHeader, _token);
        var job = JsonNode.Parse(await (await client.PostAsync($"/api/v1/imports/{source}", new StringContent(csv, Encoding.UTF8, "text/csv"))).Content.ReadAsStringAsync())!;
        for (var i = 0; i < 200 && (string)JsonNode.Parse(await client.GetStringAsync($"/api/v1/jobs/{(long)job["id"]!}"))!["status"]! != "Completed"; i++) await Task.Delay(50);
    }

    private sealed class Session(HttpClient client, CookieContainer cookies)
    {
        public HttpClient Client => client;
        public async Task<HttpResponseMessage> Post(string path, object body)
        {
            using var request = new HttpRequestMessage(HttpMethod.Post, path) { Content = JsonContent.Create(body) };
            request.Headers.Add("Origin", client.BaseAddress!.GetLeftPart(UriPartial.Authority));
            if (cookies.GetCookies(client.BaseAddress)[V1Auth.CsrfCookie] is { } csrf) request.Headers.Add(V1Auth.CsrfHeader, csrf.Value);
            return await client.SendAsync(request);
        }
        public async Task<JsonNode> Get(string path) => JsonNode.Parse(await client.GetStringAsync(path))!;
    }

    private async Task<Session> SignIn(string username)
    {
        var cookies = new CookieContainer();
        var session = new Session(new HttpClient(new HttpClientHandler { CookieContainer = cookies }) { BaseAddress = _base }, cookies);
        Assert.Equal(HttpStatusCode.OK, (await session.Post("/api/auth/login", new { username, password = Password })).StatusCode);
        return session;
    }

    private static JsonNode Row(JsonNode page, string username) => page["items"]!.AsArray().Single(r => (string)r!["username"]! == username)!;

    [Fact]
    public async Task Decisions_are_attributed_concurrency_checked_kept_as_history_and_invalidated_by_disappearance_or_evidence_change()
    {
        await Import("roles", Csv.Roles(3));
        await Import("users", Users());
        var reviewer = await SignIn("reviewer1");
        var page = await reviewer.Get("/api/account-review?include_completed=true");
        Assert.Equal(3, (int)page["summary"]!["total"]!);
        Assert.Equal(["technical"], Row(page, "SVC0001")["findings"]!.AsArray().Select(f => (string)f!));
        Assert.Equal(1, (int)page["summary"]!["requiring_review"]!);
        var row = Row(page, "USER0002");
        var evidence = (string)row["evidence_version"]!;

        // Signed-in reviewers must send the decision version they saw ('' when none); the reviewer is the account, not the text sent.
        Assert.Equal(HttpStatusCode.Conflict, (await reviewer.Post("/api/account-review/decision/USER0002", new { state = "Investigating", reviewer = "x", rationale = "Check", evidence_version = evidence })).StatusCode);
        Assert.Equal(HttpStatusCode.Conflict, (await reviewer.Post("/api/account-review/decision/USER0002", new { state = "Investigating", reviewer = "x", rationale = "Check", evidence_version = new string('0', 64), expected_decision = "" })).StatusCode);
        Assert.Equal(HttpStatusCode.UnprocessableEntity, (await reviewer.Post("/api/account-review/decision/USER0002", new { state = "Delete it", reviewer = "x", rationale = "Check", evidence_version = evidence, expected_decision = "" })).StatusCode);
        Assert.Equal(HttpStatusCode.OK, (await reviewer.Post("/api/account-review/decision/USER0002", new { state = "Investigating", reviewer = "Someone Else", rationale = "Check access", evidence_version = evidence, expected_decision = "" })).StatusCode);
        var decision = Row(await reviewer.Get("/api/account-review"), "USER0002")["decision"]!;
        Assert.Equal(("reviewer1", "server-session", "Reviewer One"), ((string)decision["reviewer"]!, (string)decision["actor_identity"]!["provenance"]!, (string)decision["actor_identity"]!["display_name"]!));
        var stale = (await reviewer.Post("/api/account-review/decision/USER0002", new { state = "No action required", reviewer = "x", rationale = "Fine", evidence_version = evidence, expected_decision = "" })).StatusCode;
        Assert.Equal(HttpStatusCode.Conflict, stale); // another decision was recorded after the version this request saw

        Assert.Equal(HttpStatusCode.OK, (await reviewer.Post("/api/account-review/decision/USER0002", new { state = "No action required", reviewer = "x", rationale = "Confirmed with owner", evidence_version = evidence, expected_decision = (string)decision["timestamp"]! })).StatusCode);
        var queue = await reviewer.Get("/api/account-review");
        Assert.Equal(1, (int)queue["completed_hidden"]!); // a completed review leaves the default queue
        Assert.DoesNotContain(queue["items"]!.AsArray(), r => (string)r!["username"]! == "USER0002");
        var completed = Row(await reviewer.Get("/api/account-review?include_completed=true"), "USER0002");
        Assert.Equal(("completed", "No action required", 1), ((string)completed["workflow_status"]!, (string)completed["review_state"]!, (int)completed["history_count"]!));
        var history = await reviewer.Get("/api/account-review/history/USER0002");
        Assert.Equal(("Investigating", 1), ((string)history["items"]![0]!["state"]!, (int)history["total"]!));

        // Viewers cannot record decisions.
        var viewer = await SignIn("viewer1");
        Assert.Equal(HttpStatusCode.Forbidden, (await viewer.Post("/api/account-review/decision/USER0001", new { state = "Investigating", reviewer = "v", rationale = "r", evidence_version = evidence, expected_decision = "" })).StatusCode);

        // The account disappears and returns: the decision stays in history but no longer applies.
        await Import("users", Users(withSecond: false));
        await Import("users", Users());
        var returned = Row(await reviewer.Get("/api/account-review?include_completed=true"), "USER0002");
        Assert.Equal((true, "Needs review", "open"), ((bool)returned["stale"]!, (string)returned["review_state"]!, (string)returned["workflow_status"]!));
        Assert.Equal("No action required", (string)returned["decision"]!["state"]!);

        // Changed account evidence (now locked) also makes a fresh decision outdated.
        var fresh = (string)returned["evidence_version"]!;
        Assert.Equal(HttpStatusCode.OK, (await reviewer.Post("/api/account-review/decision/USER0002", new { state = "No action required", reviewer = "x", rationale = "Re-reviewed", evidence_version = fresh, expected_decision = (string)returned["decision"]!["timestamp"]! })).StatusCode);
        Assert.False((bool)Row(await reviewer.Get("/api/account-review?include_completed=true"), "USER0002")["stale"]!);
        await Import("users", Users(secondLock: "X"));
        Assert.True((bool)Row(await reviewer.Get("/api/account-review?include_completed=true"), "USER0002")["stale"]!);

        // Every decision is in the hash chain and the chain verifies.
        var chain = await _app.Services.GetRequiredService<ReviewService>().VerifyChainAsync();
        Assert.True(chain.Ok);
        Assert.Equal(3, chain.Count);
    }

    [Fact]
    public async Task A_shared_access_token_is_not_a_reviewer_identity()
    {
        await Import("roles", Csv.Roles(3));
        await Import("users", Users());
        using var client = new HttpClient { BaseAddress = _base };
        client.DefaultRequestHeaders.Add(RequestBoundary.TokenHeader, _token);
        var row = Row(JsonNode.Parse(await client.GetStringAsync("/api/account-review"))!, "SVC0001");
        var response = await client.PostAsJsonAsync("/api/account-review/decision/SVC0001", new { state = "Investigating", reviewer = "operator", rationale = "r", evidence_version = (string)row["evidence_version"]!, expected_decision = "" });
        Assert.Equal(HttpStatusCode.Forbidden, response.StatusCode);
        Assert.Contains("individual sign-in", await response.Content.ReadAsStringAsync());
    }
}
