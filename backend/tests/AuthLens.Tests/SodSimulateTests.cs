using System.Net;
using System.Text;
using System.Text.Json.Nodes;
using Microsoft.AspNetCore.Builder;
using AuthLens.Api;

namespace AuthLens.Tests;

/// <summary>POST /api/sod/simulate and GET /api/sod/review-subjects against Python v1 (Fixtures/sod/governance/simulate.python.json, written by
/// tools/sod_simulate_reference.py after the same explicit activity approval). Simulation is read-only: no decision is written.</summary>
public sealed class SodSimulateTests : IAsyncLifetime
{
    private readonly string _root = Directory.CreateTempSubdirectory("saplens-simulate-").FullName;
    private readonly string _token = HostSettings.NewToken();
    private WebApplication _app = null!;
    private HttpClient _client = null!;

    private static string Fixture(params string[] path) => Path.Combine([AppContext.BaseDirectory, "Fixtures", "sod", .. path]);
    private static readonly JsonObject Reference = JsonNode.Parse(ProductRename.Apply(File.ReadAllText(Fixture("governance", "simulate.python.json"))))!.AsObject();

    public async Task InitializeAsync()
    {
        _app = AuthLensHost.Build(new HostSettings { DataDirectory = Path.Combine(_root, "data"), Port = 0, AccessToken = _token, JsonConsoleLogging = false, Mode = HostMode.Desktop });
        await _app.StartAsync();
        _client = new HttpClient { BaseAddress = new Uri(_app.Urls.First()) };
        _client.DefaultRequestHeaders.Add(RequestBoundary.TokenHeader, _token);
        foreach (var source in new[] { "roles", "users", "sod" })
        {
            var job = JsonNode.Parse(await (await _client.PostAsync($"/api/v1/imports/{source}", new StringContent(File.ReadAllText(Fixture("analysis", source + ".sod.txt")), Encoding.UTF8, "text/csv"))).Content.ReadAsStringAsync())!;
            for (var i = 0; i < 400 && (string)JsonNode.Parse(await _client.GetStringAsync($"/api/v1/jobs/{(long)job["id"]!}"))!["status"]! != "Completed"; i++) await Task.Delay(50);
        }
        var settings = JsonNode.Parse(await _client.GetStringAsync("/api/configuration"))!["settings"]!.AsObject();
        settings["features"]!["sod"] = true;
        Assert.Equal(HttpStatusCode.OK, (await Post("/api/configuration", settings)).Status);
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

    [Fact]
    public async Task Simulation_and_review_subjects_equal_python_v1_and_write_nothing()
    {
        var user = (string)Reference["user"]!;
        var subject = JsonNode.Parse(await _client.GetStringAsync($"/api/sod/subject?user={user}"))!;
        var activity = subject["overview"]!["activities"]!.AsArray().Single(a => (string)a!["activity"]! == (string)Reference["activity"]!)!;
        var (decided, body) = await Post("/api/sod/decisions/activity", new JsonObject
        {
            ["expected_revision"] = 0, ["expected_generation"] = subject["generation"]!.DeepClone(), ["decision"] = "Approved", ["justification"] = "Synthetic justification",
            ["items"] = new JsonArray(new JsonObject { ["key"] = activity["key"]!.DeepClone(), ["user"] = user, ["ref"] = activity["activity"]!.DeepClone(), ["evidence_version"] = activity["evidence_version"]!.DeepClone() }),
        });
        Assert.True(decided == HttpStatusCode.OK, body?.ToJsonString());
        var ids = subject["overview"]!["assignments"]!.AsArray().ToDictionary(a => (string)a!["role"]!, a => (string)a!["id"]!);

        var failures = new List<string>();
        foreach (var spec in Reference["cases"]!.AsArray().Select(c => c!.AsObject()))
        {
            var name = (string)spec["name"]!;
            var removed = new JsonArray([.. spec["removed_roles"]!.AsArray().Select(r => (JsonNode?)(ids.TryGetValue((string)r!, out var id) ? id : new string('f', 64)))]);
            var (status, result) = await Post("/api/sod/simulate", new JsonObject { ["user"] = (string?)spec["user"] ?? user, ["removed"] = removed });
            var want = Reference["results"]![name]!;
            if ((int)status != (int)want["status"]!) { failures.Add($"{name}: status {(int)status} vs {want["status"]}"); continue; }
            if (status != HttpStatusCode.OK) { if ((string?)result!["detail"] != (string?)want["detail"]) failures.Add($"{name}: detail {result["detail"]}"); continue; }
            var actual = result!.AsObject();
            foreach (var key in new[] { "generation", "as_of", "revision", "coverage", "context", "frozen", "reviewable", "legacy", "period" }) actual.Remove(key);
            if (!JsonNode.DeepEquals(want["body"], actual)) failures.Add($"{name}: {actual.ToJsonString()} vs {want["body"]!.ToJsonString()}");
        }
        Assert.True(failures.Count == 0, string.Join("\n", failures));

        var subjects = JsonNode.Parse(await _client.GetStringAsync($"/api/sod/review-subjects?usernames={user}&usernames=NOBODY&usernames=USER00007&usernames=USER00007&usernames=user00035"))!;
        Assert.True(JsonNode.DeepEquals(Reference["review_subjects"], subjects["users"]), subjects["users"]!.ToJsonString());
        Assert.Equal((int)Reference["revision"]!, (int)subjects["revision"]!);   // simulation wrote nothing
        Assert.Equal((HttpStatusCode)422, (await _client.GetAsync("/api/sod/review-subjects?" + string.Join('&', Enumerable.Range(0, 201).Select(i => $"usernames=U{i}")))).StatusCode);
        Assert.Equal((HttpStatusCode)422, (await Post("/api/sod/simulate", new JsonObject { ["user"] = user, ["removed"] = new JsonArray(1) })).Status);
        Assert.Equal(HttpStatusCode.NotFound, (await Post("/api/sod/simulate", new JsonObject { ["user"] = user, ["context"] = "P1" })).Status);   // unknown review period
    }
}
