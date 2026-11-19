using System.Net;
using System.Net.Http.Json;
using System.Text;
using System.Text.Json.Nodes;
using Microsoft.AspNetCore.Builder;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;
using AuthLens.Api;
using AuthLens.Persistence;

namespace AuthLens.Tests;

/// <summary>GET /api/data-health in the v1 shape. Finding counts were compared with Python v1 calculations() on the small synthetic dataset (all 11 match);
/// these tests pin the shape, availability rules and the review-continuity findings fed by the .NET review store.</summary>
public sealed class DataHealthTests : IAsyncLifetime
{
    private readonly string _root = Directory.CreateTempSubdirectory("saplens-health-").FullName;
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

    private async Task Import(string source, string csv)
    {
        var job = JsonNode.Parse(await (await _client.PostAsync($"/api/v1/imports/{source}", new StringContent(csv, Encoding.UTF8, "text/csv"))).Content.ReadAsStringAsync())!;
        for (var i = 0; i < 200 && (string)JsonNode.Parse(await _client.GetStringAsync($"/api/v1/jobs/{(long)job["id"]!}"))!["status"]! != "Completed"; i++) await Task.Delay(50);
    }

    private async Task<JsonNode> Health(string query = "") => JsonNode.Parse(await _client.GetStringAsync("/api/data-health" + query))!;
    private static int? Count(JsonNode health, string id) => (int?)health["findings"]!.AsArray().Single(f => (string)f!["id"]! == id)!["count"];

    [Fact]
    public async Task Findings_are_unavailable_without_data_and_counted_from_the_active_snapshot()
    {
        var empty = await Health();
        Assert.Equal(13, empty["findings"]!.AsArray().Count);
        Assert.Null(Count(empty, "unmapped"));
        Assert.False((bool)empty["sources"]![0]!["available"]!);
        Assert.Null((int?)empty["coverage"]![0]!["numerator"]);

        await Import("roles", Csv.Roles(10));
        await Import("users", Csv.Users([.. Csv.Assignments(5, 1, 10), ("USER0009", "ZC:XX:NOT_IN_CATALOGUE")]));
        var health = await Health();
        Assert.Equal(1, Count(health, "unmapped"));
        Assert.Equal(6, Count(health, "unknown_dates"));
        Assert.Equal(0, Count(health, "lifecycle_integrity"));
        Assert.True((bool)health["sources"]![1]!["available"]!);
        Assert.Equal(6, (int)health["sources"]![1]!["records"]!);
        Assert.False((bool)health["sources"]![2]!["available"]!); // Employee Directory not migrated: stated, not estimated
        Assert.Equal(5, (int)health["coverage"]![0]!["numerator"]!);
        Assert.Equal(6, (int)health["coverage"]![0]!["denominator"]!);
        Assert.Equal(6, (int)health["import_totals"]!["users"]!["parsed_rows"]!);
        var rows = await Health("?finding=unmapped");
        Assert.Equal("ZC:XX:NOT_IN_CATALOGUE", (string)rows["items"]![0]!["identifier"]!);
        Assert.Equal(1, (int)rows["total"]!);
    }

    /// <summary>Reappeared assignments follow v1's SoD assignment lifecycle memory (covered in SodLifecycleTests against v1); a decision history that fails
    /// its hash chain is reported as a continuity problem in addition to v1's lifecycle states.</summary>
    [Fact]
    public async Task A_broken_review_chain_is_reported_as_a_continuity_problem()
    {
        await Import("roles", Csv.Roles(30));
        var all = Csv.Assignments(30, 1, 30).ToList();
        await Import("users", Csv.Users(all));
        var review = await _client.PostAsJsonAsync("/api/v1/reviews", new { subject_type = "assignment", subject_key = "USER0001\u001fZC:FI:ROLE_0001", decision = "approved" });
        Assert.Equal(HttpStatusCode.Created, review.StatusCode);
        Assert.Equal(0, Count(await Health(), "lifecycle_integrity"));
        Assert.Equal(0, Count(await Health(), "reappeared_assignments"));

        await using (var scope = _app.Services.CreateAsyncScope())
        {
            await using var db = await scope.ServiceProvider.GetRequiredService<IDbContextFactory<AuthLensDb>>().CreateDbContextAsync();
            await db.Database.ExecuteSqlRawAsync("DROP TRIGGER ReviewDecisions_NoUpdate; UPDATE ReviewDecisions SET Decision = 'rejected';");
        }
        var health = await Health("?finding=lifecycle_integrity");
        Assert.Equal(1, Count(health, "lifecycle_integrity"));
        Assert.Contains("hash chain broken", (string)health["items"]![0]!["reason"]!);
    }
}
