using System.Net;
using System.Net.Http.Json;
using System.Text;
using System.Text.Json.Nodes;
using Microsoft.AspNetCore.Builder;
using AuthLens.Api;
using AuthLens.Domain.Json;

namespace AuthLens.Tests;

/// <summary>GET /api/sod/analysis, /evidence and /export against Python v1. Fixtures/sod/analysis/expected.python.json was written by
/// tools/sod_analysis_reference.py (v1 analyze, the router's enrichment and filtered()) for the synthetic small dataset in the same folder.</summary>
public sealed class SodAnalysisTests : IAsyncLifetime
{
    private static string Fixture(string name) => Path.Combine(AppContext.BaseDirectory, "Fixtures", "sod", "analysis", name);
    private readonly string _root = Directory.CreateTempSubdirectory("saplens-sodan-").FullName;
    private readonly string _token = HostSettings.NewToken();
    private WebApplication _app = null!;
    private HttpClient _client = null!;

    public async Task InitializeAsync()
    {
        _app = AuthLensHost.Build(new HostSettings { DataDirectory = Path.Combine(_root, "data"), Port = 0, AccessToken = _token, JsonConsoleLogging = false });
        await _app.StartAsync();
        _client = new HttpClient { BaseAddress = new Uri(_app.Urls.First()) };
        _client.DefaultRequestHeaders.Add(RequestBoundary.TokenHeader, _token);
        foreach (var source in new[] { "roles", "users", "sod" })
        {
            var job = JsonNode.Parse(await (await _client.PostAsync($"/api/v1/imports/{source}", new StringContent(File.ReadAllText(Fixture(source + ".sod.txt")), Encoding.UTF8, "text/csv"))).Content.ReadAsStringAsync())!;
            for (var i = 0; i < 400 && (string)JsonNode.Parse(await _client.GetStringAsync($"/api/v1/jobs/{(long)job["id"]!}"))!["status"]! != "Completed"; i++) await Task.Delay(50);
        }
    }

    public async Task DisposeAsync()
    {
        _client.Dispose();
        await _app.StopAsync();
        await _app.DisposeAsync();
        Microsoft.Data.Sqlite.SqliteConnection.ClearAllPools();
        try { Directory.Delete(_root, true); } catch (IOException) { }
    }

    private async Task EnableSod()
    {
        var settings = JsonNode.Parse(await _client.GetStringAsync("/api/configuration"))!["settings"]!.AsObject();
        settings["features"]!["sod"] = true;
        using var request = new HttpRequestMessage(HttpMethod.Post, "/api/configuration") { Content = JsonContent.Create(settings) };
        Assert.Equal(HttpStatusCode.OK, (await _client.SendAsync(request)).StatusCode);
    }

    private static string QueryString(JsonObject spec)
    {
        var parts = new List<string> { "limit=25" };
        foreach (var (key, value) in spec)
        {
            if (key == "name") continue;
            if (value is JsonArray list) parts.AddRange(list.Select(v => $"{key}={Uri.EscapeDataString((string)v!)}"));
            else parts.Add($"{key}={Uri.EscapeDataString(value!.GetValueKind() is System.Text.Json.JsonValueKind.True or System.Text.Json.JsonValueKind.False ? value.ToJsonString() : (string)value!)}");
        }
        return string.Join('&', parts);
    }

    private static object? Plain(JsonNode? node) => node switch
    {
        JsonObject o => o.ToDictionary(p => p.Key, p => Plain(p.Value)),
        JsonArray a => a.Select(Plain).ToList(),
        JsonValue v when v.TryGetValue<string>(out var s) => s,
        JsonValue v when v.TryGetValue<bool>(out var b) => b,
        JsonValue v when v.TryGetValue<long>(out var l) => l,
        _ => null,
    };

    [Fact]
    public async Task Findings_filters_sorting_and_enrichment_equal_python_v1()
    {
        var disabled = JsonNode.Parse(await _client.GetStringAsync("/api/sod/analysis"))!;
        Assert.Equal(("unavailable", "sod_disabled", 0), ((string)disabled["coverage"]!["status"]!, (string)disabled["coverage"]!["reason"]!, (int)disabled["total"]!));
        await EnableSod();
        var expected = JsonNode.Parse(File.ReadAllText(Fixture("expected.python.json")))!.AsObject();
        foreach (var spec in JsonNode.Parse(File.ReadAllText(Fixture("queries.json")))!.AsArray().Select(s => s!.AsObject()))
        {
            var name = (string)spec["name"]!;
            var python = expected[name]!;
            var actual = JsonNode.Parse(await _client.GetStringAsync("/api/sod/analysis?" + QueryString(spec)))!;
            Assert.True((int)python["total"]! == (int)actual["total"]!, $"{name}: total {actual["total"]} vs python {python["total"]}");
            Assert.Equal((int)python["subjects"]!, (int)actual["summary"]!["filtered"]!["subjects"]!);
            Assert.Equal(CanonicalJson.Serialize(Plain(python["summary"])), CanonicalJson.Serialize(Plain(actual["summary"]!["unfiltered"])));
            Assert.Equal(CanonicalJson.Serialize(Plain(python["coverage"])), CanonicalJson.Serialize(Plain(actual["coverage"])));
            Assert.True(CanonicalJson.Serialize(Plain(python["items"])) == CanonicalJson.Serialize(Plain(actual["items"])), $"{name}: items differ");
        }
    }

    [Fact]
    public async Task Evidence_paging_generation_check_export_and_unmigrated_filters()
    {
        await EnableSod();
        var page = JsonNode.Parse(await _client.GetStringAsync("/api/sod/analysis?validity=all&sort=evidence_count&descending=true&limit=1"))!;
        var finding = page["items"]![0]!;
        var generation = (string)page["generation"]!;
        var total = (int)finding["evidence_total"]!["ACTVT1"]!;
        var evidence = JsonNode.Parse(await _client.GetStringAsync($"/api/sod/analysis/evidence?validity=all&finding_id={finding["finding_id"]}&expected_generation={generation}&side=ACTVT1&offset=0&limit=100"))!;
        Assert.Equal(total, (int)evidence["total"]!);
        Assert.Equal(Math.Min(total, 100), evidence["items"]!.AsArray().Count);
        Assert.Equal(HttpStatusCode.Conflict, (await _client.GetAsync($"/api/sod/analysis/evidence?validity=all&finding_id={finding["finding_id"]}&expected_generation={new string('0', 64)}")).StatusCode);
        Assert.Equal(HttpStatusCode.NotFound, (await _client.GetAsync($"/api/sod/analysis/evidence?validity=all&finding_id={new string('a', 64)}&expected_generation={generation}")).StatusCode);

        var export = await _client.GetAsync($"/api/sod/analysis/export?validity=all&risks={finding["risk_id"]}&expected_generation={generation}");
        Assert.Equal(HttpStatusCode.OK, export.StatusCode);
        Assert.Equal(generation, export.Headers.GetValues("X-SAP-Lens-Data-Generation").Single());
        var lines = Encoding.UTF8.GetString(await export.Content.ReadAsByteArrayAsync()).TrimStart('﻿').Split("\r\n", StringSplitOptions.RemoveEmptyEntries);
        Assert.StartsWith("\"FINDING_ID\";\"KIND\";\"SUBJECT\";\"RISK\"", lines[0]);
        Assert.All(lines.Skip(1), l => Assert.Contains($"\"{finding["risk_id"]}\"", l));
        var count = int.Parse(export.Headers.GetValues("X-SAP-Lens-Finding-Count").Single());
        Assert.True(lines.Length - 1 >= count); // one line per evidence path of each finding

        Assert.Equal(HttpStatusCode.OK, (await _client.GetAsync("/api/sod/analysis?functional_groups=g1")).StatusCode);   // organization filters select users by name
        Assert.Equal(HttpStatusCode.UnprocessableEntity, (await _client.GetAsync("/api/sod/analysis?validity=sometimes")).StatusCode);
        Assert.Equal(HttpStatusCode.UnprocessableEntity, (await _client.GetAsync("/api/sod/analysis?kind=roles&selected_roles=ZC:NOT:THERE&selected_roles=ZC:FI:ROLE_00001")).StatusCode);
    }
}
