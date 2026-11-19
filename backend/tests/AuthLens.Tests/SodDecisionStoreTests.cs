using System.Text.Json.Nodes;
using Microsoft.AspNetCore.Builder;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;
using AuthLens.Api;
using AuthLens.Application;
using AuthLens.Persistence;

namespace AuthLens.Tests;

/// <summary>The SoD decision store against Python v1. Fixtures/sod/governance/decisions.python.json was written by tools/sod_decisions_reference.py: a
/// scripted sequence of sod_decisions.record calls with v1's outcome of each (status, revision, previous decisions, evidence content addresses) and the
/// resulting histories. Event ids and timestamps are random or clock values and are not compared.</summary>
public sealed class SodDecisionStoreTests : IAsyncLifetime
{
    private readonly string _root = Directory.CreateTempSubdirectory("saplens-soddec-").FullName;
    private WebApplication _app = null!;
    private SodDecisionStore Store => _app.Services.GetRequiredService<SodDecisionStore>();

    private static readonly JsonObject Fixture =
        JsonNode.Parse(File.ReadAllText(Path.Combine(AppContext.BaseDirectory, "Fixtures", "sod", "governance", "decisions.python.json")))!.AsObject();

    public Task InitializeAsync() => StartAsync();

    private async Task StartAsync()
    {
        _app = AuthLensHost.Build(new HostSettings { DataDirectory = Path.Combine(_root, "data"), Port = 0, AccessToken = HostSettings.NewToken(), JsonConsoleLogging = false });
        await _app.StartAsync();
    }

    private async Task RestartAsync()
    {
        await _app.StopAsync();
        await _app.DisposeAsync();
        await StartAsync();
    }

    public async Task DisposeAsync()
    {
        await _app.StopAsync();
        await _app.DisposeAsync();
        Microsoft.Data.Sqlite.SqliteConnection.ClearAllPools();
        try { Directory.Delete(_root, true); } catch (IOException) { }
    }

    private static SodRecordRequest Request(JsonObject op) => new(
        (string)op["kind"]!, (string?)op["context"] ?? "current",
        op["items"]!.AsArray().Select(i => new SodDecisionItem((string)i!["key"]!, (string)i["user"]!, (string)i["ref"]!, (string)i["evidence_version"]!, i["evidence"]!.DeepClone())).ToList(),
        (string)op["decision"]!, (string?)op["reviewer"] ?? "Synthetic reviewer", (string?)op["justification"] ?? "Synthetic justification", (int)op["expected_revision"]!,
        (string?)op["approver"] ?? "", (string?)op["controls"] ?? "", (string?)op["expires"],
        new Dictionary<string, string> { ["users"] = new('u', 64), ["sod"] = new('s', 64) }, (string?)op["bulk_operation_id"] ?? "");

    private async Task<JsonObject> Run(JsonObject op)
    {
        try
        {
            var result = await Store.RecordAsync(Request(op), null, CancellationToken.None);
            var events = new JsonArray();
            foreach (var e in result.Events)
            {
                var json = e.ToJson();
                json.Remove("event_id");
                json.Remove("timestamp");
                events.Add(json);
            }
            return new JsonObject { ["status"] = 200, ["revision"] = result.Revision, ["events"] = events };
        }
        catch (SodDecisionException error) { return new JsonObject { ["status"] = error.Status, ["detail"] = error.Message }; }
    }

    [Fact]
    public async Task Operation_sequence_and_histories_equal_python_v1_and_survive_restart()
    {
        var failures = new List<string>();
        foreach (var op in Fixture["operations"]!.AsArray().Select(o => o!.AsObject()))
        {
            var want = op["outcome"]!.AsObject();
            var actual = await Run(op);
            // v1 reports pydantic validation errors with pydantic's text; status codes are compared for those, messages where v1 gives its own.
            if ((int)want["status"]! == 422 && want["detail"] is null) actual.Remove("detail");
            if (!JsonNode.DeepEquals(want, actual)) failures.Add($"{op["name"]}: expected {want.ToJsonString()[..Math.Min(300, want.ToJsonString().Length)]} got {actual.ToJsonString()[..Math.Min(300, actual.ToJsonString().Length)]}");
        }
        Assert.True(failures.Count == 0, string.Join("\n", failures));

        await RestartAsync();
        Assert.Equal((int)Fixture["revision"]!, await Store.RevisionAsync(CancellationToken.None));
        foreach (var (id, want) in Fixture["histories"]!.AsObject())
        {
            var parts = id.Split(':');
            var history = await Store.HistoryAsync(parts[0], parts[1], int.Parse(parts[2]).ToString("x64"), CancellationToken.None);
            var actual = new JsonArray();
            foreach (var e in history)
                actual.Add(new JsonObject { ["decision"] = e["decision"]!.DeepClone(), ["previous_decision"] = e["previous_decision"]!.DeepClone(), ["reviewer"] = e["reviewer"]!.DeepClone(),
                    ["evidence"] = await Store.EvidenceAsync(e, CancellationToken.None) });
            Assert.True(JsonNode.DeepEquals(want, actual), $"{id}: {actual.ToJsonString()}");
        }
        var chain = await Store.VerifyChainAsync(CancellationToken.None);
        Assert.True(chain.Ok);
        Assert.Equal(12, chain.Count);   // the committed events of the v1 sequence
    }

    private static JsonObject Op(int key, string decision, int revision, string kind = "assignment", string? reference = null) => new()
    {
        ["kind"] = kind, ["decision"] = decision, ["expected_revision"] = revision,
        ["items"] = new JsonArray(new JsonObject { ["key"] = key.ToString("x64"), ["user"] = "USER01", ["ref"] = reference ?? "ROLE", ["evidence_version"] = (key + 1000).ToString("x64"), ["evidence"] = new JsonObject { ["n"] = key } }),
    };

    [Fact]
    public async Task Concurrent_writers_with_the_same_revision_commit_exactly_once()
    {
        var results = await Task.WhenAll(Enumerable.Range(1, 8).Select(n => Run(Op(n, "Keep", 0))));
        Assert.Equal(1, results.Count(r => (int)r["status"]! == 200));
        Assert.Equal(7, results.Count(r => (int)r["status"]! == 409));
        Assert.Equal(1, await Store.RevisionAsync(CancellationToken.None));
        Assert.Equal(1, (await Store.VerifyChainAsync(CancellationToken.None)).Count);
    }

    [Fact]
    public async Task A_failing_item_writes_nothing_of_the_call()
    {
        var op = Op(1, "Keep", 0);
        op["items"]!.AsArray().Add(new JsonObject { ["key"] = 2.ToString("x64"), ["user"] = "USER01", ["ref"] = new string('R', 600), ["evidence_version"] = 3.ToString("x64"), ["evidence"] = new JsonObject() });
        Assert.Equal(422, (int)(await Run(op))["status"]!);
        await using var db = await _app.Services.GetRequiredService<IDbContextFactory<AuthLensDb>>().CreateDbContextAsync();
        Assert.Equal(0, await db.SodDecisionEvents.CountAsync());
        Assert.Equal(0, await db.SodEvidenceSnapshots.CountAsync());
        Assert.Equal(0, await Store.RevisionAsync(CancellationToken.None));
    }

    [Fact]
    public async Task Events_and_evidence_are_append_only_and_tampering_breaks_the_chain()
    {
        Assert.Equal(200, (int)(await Run(Op(1, "Keep", 0)))["status"]!);
        Assert.Equal(200, (int)(await Run(Op(1, "Remove", 1)))["status"]!);
        Assert.Equal(200, (int)(await Run(Op(2, "Keep", 2)))["status"]!);
        await using var db = await _app.Services.GetRequiredService<IDbContextFactory<AuthLensDb>>().CreateDbContextAsync();
        await Assert.ThrowsAsync<Microsoft.Data.Sqlite.SqliteException>(() => db.Database.ExecuteSqlRawAsync("UPDATE SodDecisionEvents SET Json = Json || ' '"));
        await Assert.ThrowsAsync<Microsoft.Data.Sqlite.SqliteException>(() => db.Database.ExecuteSqlRawAsync("DELETE FROM SodDecisionEvents"));
        await Assert.ThrowsAsync<Microsoft.Data.Sqlite.SqliteException>(() => db.Database.ExecuteSqlRawAsync("UPDATE SodEvidenceSnapshots SET Json = '[]'"));

        // Someone with file access removes the guard and edits history: the chain no longer verifies, and edited evidence fails its address.
        await db.Database.ExecuteSqlRawAsync("DROP TRIGGER SodDecisionEvents_NoUpdate; DROP TRIGGER SodEvidenceSnapshots_NoUpdate;");
        await db.Database.ExecuteSqlRawAsync("UPDATE SodDecisionEvents SET Json = replace(Json, '\"Remove\"', '\"Keep\"') WHERE Seq = 2");
        var chain = await Store.VerifyChainAsync(CancellationToken.None);
        Assert.False(chain.Ok);
        Assert.Equal(2, chain.BrokenAt);
        await db.Database.ExecuteSqlRawAsync("UPDATE SodEvidenceSnapshots SET Json = replace(Json, '\"n\":2', '\"n\":3')");
        var history = await Store.HistoryAsync("assignment", "current", 2.ToString("x64"), CancellationToken.None);
        var error = await Assert.ThrowsAsync<SodDecisionException>(() => Store.EvidenceAsync(history[0], CancellationToken.None));
        Assert.Equal(409, error.Status);
    }

    [Fact]
    public async Task History_and_context_identifiers_are_validated_like_v1()
    {
        Assert.Equal(422, (await Assert.ThrowsAsync<SodDecisionException>(() => Store.HistoryAsync("role", "current", 1.ToString("x64"), CancellationToken.None))).Status);
        Assert.Equal(422, (await Assert.ThrowsAsync<SodDecisionException>(() => Store.HistoryAsync("assignment", "current", "ABC", CancellationToken.None))).Status);
        Assert.Equal(422, (await Assert.ThrowsAsync<SodDecisionException>(() => Store.HistoryAsync("assignment", "-bad", 1.ToString("x64"), CancellationToken.None))).Status);
        Assert.Empty(await Store.HistoryAsync("assignment", "current", 1.ToString("x64"), CancellationToken.None));
    }
}
