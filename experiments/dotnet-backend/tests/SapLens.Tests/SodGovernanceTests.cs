using System.Globalization;
using System.Text.Json.Nodes;
using SapLens.Domain.Sod;

namespace SapLens.Tests;

/// <summary>The SoD 2.0 decision model against Python v1. Fixtures/sod/governance/expected.python.json was written by tools/sod_governance_reference.py:
/// v1 findings of the synthetic small dataset, v1's derived model, a decision scenario (current, stale, removal, investigation, conditional, expired
/// and rejected acceptance, risk review, reappeared assignments) and v1's lifecycle, coverage and derived status of every review item.</summary>
public sealed class SodGovernanceTests
{
    private static readonly JsonObject Fixture =
        JsonNode.Parse(File.ReadAllText(Path.Combine(AppContext.BaseDirectory, "Fixtures", "sod", "governance", "expected.python.json")))!.AsObject();

    private static Dictionary<string, SodUserEntry> Model() => SodGovernance.Derive(Fixture["findings"]!.AsArray().Select(f => f!.AsObject()));

    private static string Short(JsonNode? node) { var text = node?.ToJsonString() ?? "null"; return text.Length > 400 ? text[..400] : text; }

    [Fact]
    public void Derived_review_population_keys_and_evidence_versions_equal_python_v1()
    {
        var model = Model();
        var expected = Fixture["model"]!.AsObject();
        Assert.Equal(expected.Select(p => p.Key).Order(StringComparer.Ordinal), model.Keys.Order(StringComparer.Ordinal));
        var failures = new List<string>();
        foreach (var (user, want) in expected)
        {
            var actual = SodGovernance.ToJson(model[user]);
            actual["finding_ids"] = new JsonArray([.. model[user].Findings.Values.Select(f => (string)f["finding_id"]!).Order(StringComparer.Ordinal).Select(v => (JsonNode?)v)]);
            if (!JsonNode.DeepEquals(want, actual)) failures.Add($"{user}: {Short(actual)}");
        }
        Assert.True(failures.Count == 0, string.Join("\n", failures.Take(5)));
    }

    [Fact]
    public void Lifecycle_coverage_and_derived_status_equal_python_v1_for_the_decision_scenario()
    {
        var model = Model();
        var latest = new Dictionary<string, IReadOnlyDictionary<string, SodDecisionEvent>>(StringComparer.Ordinal);
        foreach (var kind in SodGovernance.Decisions.Keys) latest[kind] = new Dictionary<string, SodDecisionEvent>(StringComparer.Ordinal);
        foreach (var node in Fixture["events"]!.AsArray())
        {
            var e = SodDecisionEvent.FromJson(node!.AsObject());
            ((Dictionary<string, SodDecisionEvent>)latest[e.Kind])[e.Key] = e;
            Assert.True(JsonNode.DeepEquals(node, e.ToJson()), "event round trip: " + Short(node));
        }
        var reappeared = Fixture["reappeared"]!.AsObject().ToDictionary(p => p.Key, p => (string)p.Value!, StringComparer.Ordinal);
        var today = DateOnly.ParseExact((string)Fixture["today"]!, "yyyy-MM-dd", CultureInfo.InvariantCulture);
        var state = SodGovernance.States(model, latest, today, reappeared);

        var failures = new List<string>();
        var compared = 0;
        foreach (var (user, rows) in Fixture["states"]!.AsObject())
            foreach (var (id, want) in rows!.AsObject())
            {
                var (kind, key) = (id.Split(':')[0], id.Split(':')[1]);
                var item = state.Items[kind][key];
                var actual = new JsonObject { ["lifecycle"] = item.Lifecycle, ["event_id"] = item.Event?.EventId };
                if (kind != "risk")
                {
                    actual["coverage"] = state.Coverage[kind][key].DeepClone();
                    actual["summary"] = SodGovernance.DecisionSummary(model[user], state, kind, key);
                }
                else actual["summary"] = SodGovernance.EffectiveDecision(model[user], state, "risk", key);
                compared++;
                if (!JsonNode.DeepEquals(want, actual)) failures.Add($"{user} {id}: expected {Short(want)} got {Short(actual)}");
            }
        Assert.True(failures.Count == 0, $"{failures.Count} of {compared} differ:\n" + string.Join("\n", failures.Take(5)));
        Assert.True(compared > 700);
        Assert.Equal(Fixture["reappeared_reasons"]!.AsObject().Select(p => p.Key).Order(StringComparer.Ordinal), state.Reappeared.Keys.Order(StringComparer.Ordinal));
    }

    [Fact]
    public void The_dotnet_analysis_derives_the_same_review_keys_as_python_v1()
    {
        var folder = Directory.CreateTempSubdirectory("saplens-gov-").FullName;
        IReadOnlyList<IReadOnlyDictionary<string, string>> Records(string source, SapLens.Domain.Csv.CsvSpec spec)
        {
            var path = Path.Combine(folder, source + ".csv");   // the reader accepts .csv only; fixtures use .sod.txt (*.csv is git-ignored)
            File.Copy(Path.Combine(AppContext.BaseDirectory, "Fixtures", "sod", "analysis", source + ".sod.txt"), path);
            return [.. new SapLens.Domain.Csv.CsvImport(path, new SapLens.Domain.Csv.CsvProfile(), spec).Records()];
        }
        var catalogue = SapLens.Domain.Catalogue.CatalogueBuilder.Build(Records("roles", SapLens.Domain.Csv.CsvSpec.Roles));
        var users = SapLens.Domain.Users.UserDirectoryBuilder.Build(Records("users", SapLens.Domain.Csv.CsvSpec.Users), catalogue);
        var sod = SodSource.Build(Records("sod", SapLens.Domain.Csv.CsvSpec.Sod));
        var today = DateOnly.ParseExact((string)Fixture["today"]!, "yyyy-MM-dd", CultureInfo.InvariantCulture);
        var result = SodAnalyzer.Analyze(catalogue, users, sod, today);
        var model = SodGovernance.Derive(result.Users.Select(SodGovernance.FindingJson));
        var expected = Fixture["model"]!.AsObject();
        Assert.Equal(expected.Select(p => p.Key).Order(StringComparer.Ordinal), model.Keys.Order(StringComparer.Ordinal));
        foreach (var (user, want) in expected)
        {
            var actual = SodGovernance.ToJson(model[user]);
            actual["finding_ids"] = new JsonArray([.. model[user].Findings.Values.Select(f => (string)f["finding_id"]!).Order(StringComparer.Ordinal).Select(v => (JsonNode?)v)]);
            Assert.True(JsonNode.DeepEquals(want, actual), $"{user}: {Short(actual)}");
        }
    }

    [Theory]
    [InlineData("assignment", "Keep", "ver", "ver", "2026-01-15", null, null, "Keep")]
    [InlineData("assignment", "Remove", "ver", "ver", "2026-01-15", null, null, "Removal required")]
    [InlineData("assignment", "Keep", "old", "ver", "2026-01-15", null, null, "Outdated")]
    [InlineData("assignment", "Keep", "ver", null, "2026-01-15", null, null, "Historical")]
    [InlineData("assignment", "Keep", "ver", "ver", "2026-01-15", null, "2026-01-11T00:00:00+00:00", "Outdated")]
    [InlineData("assignment", "Keep", "ver", "ver", "2026-01-15", null, "2026-01-09T00:00:00+00:00", "Keep")]
    [InlineData("acceptance", "Accepted", "ver", "ver", "2026-01-15", "2026-01-15", null, "Accepted")]
    [InlineData("acceptance", "Accepted", "ver", "ver", "2026-01-16", "2026-01-15", null, "Outdated")]
    public void Lifecycle_rules_match_v1(string kind, string decision, string eventVersion, string? current, string today, string? expires, string? reappeared, string expected)
    {
        var e = new SodDecisionEvent(new string('a', 32), kind, "current", "2026-01-10T09:00:00+00:00", new string('b', 64), "U", "R", decision, "Reviewer", "Why",
            eventVersion, new string('c', 64), Expires: expires);
        Assert.Equal(expected, SodGovernance.Lifecycle(kind, e, current, DateOnly.Parse(today, CultureInfo.InvariantCulture), reappeared));
        Assert.Equal("Pending", SodGovernance.Lifecycle(kind, null, current, DateOnly.Parse(today, CultureInfo.InvariantCulture)));
    }
}
