using System.Net;
using System.Text;
using System.Text.Json.Nodes;
using Microsoft.AspNetCore.Builder;
using AuthLens.Api;

namespace AuthLens.Tests;

/// <summary>MIG-013/015/017: the SoD 2.0 read routes (context, matrices, group views, filter options, explorer tables, selection, queue, queue users,
/// remediation) against Python v1's router functions on the synthetic dataset. Fixtures/sod/routes/expected.python.json was written by
/// tools/sod_routes_reference.py (live context, no decisions); the evidence generation and the decision revision are not compared.</summary>
public sealed class SodRoutesTests : IAsyncLifetime
{
    private readonly string _root = Directory.CreateTempSubdirectory("saplens-sodroutes-").FullName;
    private readonly string _token = HostSettings.NewToken();
    private WebApplication _app = null!;
    private HttpClient _client = null!;

    private static string Fixture(params string[] path) => System.IO.Path.Combine([AppContext.BaseDirectory, "Fixtures", "sod", .. path]);

    public async Task InitializeAsync()
    {
        _app = AuthLensHost.Build(new HostSettings { DataDirectory = System.IO.Path.Combine(_root, "data"), Port = 0, AccessToken = _token, JsonConsoleLogging = false, Mode = HostMode.Desktop });
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
        var request = new HttpRequestMessage(HttpMethod.Post, "/api/configuration") { Content = new StringContent(settings.ToJsonString(), Encoding.UTF8, "application/json") };
        request.Headers.Add("Origin", _client.BaseAddress!.GetLeftPart(UriPartial.Authority));
        Assert.Equal(HttpStatusCode.OK, (await _client.SendAsync(request)).StatusCode);
    }

    public async Task DisposeAsync()
    {
        _client.Dispose();
        await _app.StopAsync();
        await _app.DisposeAsync();
        Microsoft.Data.Sqlite.SqliteConnection.ClearAllPools();
        try { Directory.Delete(_root, true); } catch (IOException) { }
    }

    private static string Value(JsonNode value) => value.GetValueKind() switch
    {
        System.Text.Json.JsonValueKind.True => "true", System.Text.Json.JsonValueKind.False => "false", System.Text.Json.JsonValueKind.String => (string)value!, _ => value.ToJsonString(),
    };

    private static string RoutePath(JsonObject spec) => (string)spec["route"]! switch
    {
        "context" => "/api/sod/context", "matrix_risk" => "/api/sod/matrix/risk", "matrix_activity" => "/api/sod/matrix/activity", "explorer" => $"/api/sod/explorer/{spec["table"]}",
        "queue" => "/api/sod/queue", "queue_users" => "/api/sod/queue/users", "remediation" => "/api/sod/remediation", "filter_options" => "/api/sod/filter-options",
        _ => "/api/sod/explorer/access_list/selection",
    };

    private static string Short(JsonNode? node) { var text = node?.ToJsonString() ?? "null"; return text.Length > 500 ? text[..500] : text; }

    [Fact]
    public async Task Read_routes_equal_python_v1()
    {
        var expected = JsonNode.Parse(File.ReadAllText(Fixture("routes", "expected.python.json")))!.AsObject();
        var failures = new List<string>();
        foreach (var spec in JsonNode.Parse(File.ReadAllText(Fixture("routes", "queries.json")))!.AsArray().Select(s => s!.AsObject()))
        {
            var name = (string)spec["name"]!;
            // Golden output was captured on this evaluation date. Exercise that same
            // public filter rather than comparing today's live date to yesterday's fixture.
            spec["as_of"] ??= (string)expected["context"]!["as_of"]!;
            var query = string.Join('&', spec.Where(p => p.Key is not ("name" or "route" or "table")).SelectMany(p => p.Value is JsonArray values
                ? values.Select(v => $"{p.Key}={Uri.EscapeDataString(Value(v!))}") : [$"{p.Key}={Uri.EscapeDataString(Value(p.Value!))}"]));
            var dayBefore = DateTime.Today.ToString("yyyy-MM-dd", System.Globalization.CultureInfo.InvariantCulture);
            var response = await _client.GetAsync(RoutePath(spec) + (query.Length > 0 ? "?" + query : ""));
            var text = await response.Content.ReadAsStringAsync();
            if (response.StatusCode != HttpStatusCode.OK) { failures.Add($"{name}: {(int)response.StatusCode} {text}"); continue; }
            var actual = JsonNode.Parse(text)!.AsObject();
            actual.Remove("generation");
            actual.Remove("revision");
            var want = expected[name]!.DeepClone().AsObject();
            if ((string)spec["route"]! == "context")
            {
                // /context describes the live context and deliberately has no as_of
                // override. Assert its current-day contract before comparing the
                // remaining captured fields; account for a request crossing midnight.
                var dayAfter = DateTime.Today.ToString("yyyy-MM-dd", System.Globalization.CultureInfo.InvariantCulture);
                Assert.Contains((string)actual["as_of"]!, new[] { dayBefore, dayAfter });
                want["as_of"] = actual["as_of"]!.DeepClone();
            }
            if (JsonNode.DeepEquals(want, actual)) continue;
            var keys = want.Select(p => p.Key).Union(actual.Select(p => p.Key)).Where(k => !JsonNode.DeepEquals(want[k], actual[k])).ToList();
            var detail = keys.Select(k =>
            {
                if (want[k] is JsonArray wa && actual[k] is JsonArray aa)
                {
                    var i = Enumerable.Range(0, Math.Min(wa.Count, aa.Count)).FirstOrDefault(i => !JsonNode.DeepEquals(wa[i], aa[i]), -1);
                    return $"{k}: count {aa.Count} vs {wa.Count}, first difference {i}: {Short(i >= 0 ? aa[i] : null)} vs {Short(i >= 0 ? wa[i] : null)}";
                }
                return $"{k}: {Short(actual[k])} vs {Short(want[k])}";
            });
            failures.Add($"{name}: {string.Join(" | ", detail)}");
        }
        Assert.True(failures.Count == 0, string.Join("\n", failures));
    }

    [Fact]
    public async Task Sod_source_inspection_describes_the_active_snapshot_and_a_candidate_file()
    {
        var active = JsonNode.Parse(await _client.GetStringAsync("/api/data-sources/sod/inspection"))!;
        Assert.True((bool)active["loaded"]!);
        Assert.Equal(7, active["checks"]!.AsArray().Count);
        Assert.True((int)active["counts"]!["risks"]! > 0);
        Assert.Equal(10, active["columns"]!.AsArray().Count);
        Assert.Equal(5, active["descriptions"]!["indicators"]!.AsArray().Count);
        Assert.True(active["samples"]!.AsArray().Count is > 0 and <= 20);

        var file = System.IO.Path.Combine(_root, "candidate.csv");
        File.Copy(Fixture("analysis", "sod.sod.txt"), file);
        var request = new HttpRequestMessage(HttpMethod.Post, "/api/data-sources/sod/inspect") { Content = new StringContent(new JsonObject { ["path"] = file }.ToJsonString(), Encoding.UTF8, "application/json") };
        request.Headers.Add("Origin", _client.BaseAddress!.GetLeftPart(UriPartial.Authority));
        var candidate = JsonNode.Parse(await (await _client.SendAsync(request)).Content.ReadAsStringAsync())!;
        Assert.True((bool)candidate["valid"]!, candidate.ToJsonString());
        Assert.Equal((int)active["counts"]!["risks"]!, (int)candidate["counts"]!["risks"]!);
        Assert.All(candidate["columns"]!.AsArray(), c => Assert.Equal("detected", (string)c!["state"]!));
    }
}
