using System.Globalization;
using System.Text.Json.Nodes;
using AuthLens.Domain.Sod;

namespace AuthLens.Tests;

/// <summary>The SoD 2.0 views (restrict, matrices, grouping, explorer tables, queue, conflict concentration, remediation) against Python v1.
/// Fixtures/sod/governance/views.python.json was written by tools/sod_views_reference.py on the decision scenario of sod_governance_reference.py.</summary>
public sealed class SodViewsTests
{
    private static readonly string Folder = Path.Combine(AppContext.BaseDirectory, "Fixtures", "sod", "governance");
    private static readonly JsonObject Scenario = JsonNode.Parse(File.ReadAllText(Path.Combine(Folder, "expected.python.json")))!.AsObject();
    private static readonly JsonObject Views = JsonNode.Parse(File.ReadAllText(Path.Combine(Folder, "views.python.json")))!.AsObject();

    private static (Dictionary<string, SodUserEntry> Model, SodStates State, DateOnly Today) Build()
    {
        var model = SodGovernance.Derive(Scenario["findings"]!.AsArray().Select(f => f!.AsObject()));
        var latest = SodGovernance.Decisions.Keys.ToDictionary(k => k, k => (IReadOnlyDictionary<string, SodDecisionEvent>)new Dictionary<string, SodDecisionEvent>(StringComparer.Ordinal), StringComparer.Ordinal);
        foreach (var node in Scenario["events"]!.AsArray())
        {
            var e = SodDecisionEvent.FromJson(node!.AsObject());
            ((Dictionary<string, SodDecisionEvent>)latest[e.Kind])[e.Key] = e;
        }
        var reappeared = Scenario["reappeared"]!.AsObject().ToDictionary(p => p.Key, p => (string)p.Value!, StringComparer.Ordinal);
        var today = DateOnly.ParseExact((string)Scenario["today"]!, "yyyy-MM-dd", CultureInfo.InvariantCulture);
        return (model, SodGovernance.States(model, latest, today, reappeared), today);
    }

    private static Dictionary<string, HashSet<string>> Sets(string name) =>
        Views[name]!.AsObject().ToDictionary(p => p.Key, p => p.Value!.AsArray().Select(v => (string)v!).ToHashSet(StringComparer.Ordinal), StringComparer.Ordinal);

    /// <summary>The reference writes an event as its event id.</summary>
    private static JsonNode? Plain(JsonNode? node)
    {
        switch (node)
        {
            case JsonObject o:
                var copy = new JsonObject();
                foreach (var (k, v) in o) copy[k] = k == "event" && v is JsonObject e ? e["event_id"]!.DeepClone() : Plain(v);
                return copy;
            case JsonArray a: return new JsonArray([.. a.Select(Plain)]);
            default: return node?.DeepClone();
        }
    }

    private static void Same(List<string> failures, string name, JsonNode? actual)
    {
        var want = Views[name];
        var got = Plain(actual);
        if (JsonNode.DeepEquals(want, got)) return;
        if (want is JsonArray wa && got is JsonArray ga)
        {
            var index = Enumerable.Range(0, Math.Min(wa.Count, ga.Count)).FirstOrDefault(i => !JsonNode.DeepEquals(wa[i], ga[i]), -1);
            failures.Add($"{name}: count {ga.Count} vs {wa.Count}; first difference at {index}: {Short(index >= 0 ? ga[index] : null)} vs {Short(index >= 0 ? wa[index] : null)}");
        }
        else if (want is JsonObject wo && got is JsonObject go)
            failures.Add($"{name}: differs in {string.Join(", ", wo.Select(p => p.Key).Union(go.Select(p => p.Key)).Where(k => !JsonNode.DeepEquals(wo[k], go[k])).Select(k => $"{k}: {Short(go[k])} vs {Short(wo[k])}"))}");
        else failures.Add($"{name}: {Short(got)} vs {Short(want)}");
    }

    private static string Short(JsonNode? node) { var text = node?.ToJsonString() ?? "null"; return text.Length > 600 ? text[..600] : text; }

    [Fact]
    public void Views_equal_python_v1()
    {
        var (model, state, today) = Build();
        var view = SodViews.Restrict(model, Sets("visible"), Sets("allowed"));
        var failures = new List<string>();
        var restricted = new JsonObject();
        foreach (var (user, entry) in view)
        {
            var json = SodGovernance.ToJson(entry);
            json["finding_ids"] = new JsonArray([.. entry.Findings.Values.Select(f => (JsonNode?)(string)f["finding_id"]!).OrderBy(v => (string)v!, StringComparer.Ordinal)]);
            json["visible_assignments"] = new JsonArray([.. (entry.VisibleAssignments ?? new HashSet<string>()).Order(StringComparer.Ordinal).Select(v => (JsonNode?)v)]);
            restricted[user] = json;
        }
        Same(failures, "restricted", restricted);
        Same(failures, "risk_matrix", SodViews.RiskMatrix(model, state));
        Same(failures, "activity_matrix", SodViews.ActivityMatrix(model, state));
        Same(failures, "risk_matrix_view", SodViews.RiskMatrix(view, state));
        Same(failures, "activity_matrix_view", SodViews.ActivityMatrix(view, state));
        Same(failures, "risk_groups", SodViews.AggregateByGroup(SodViews.RiskMatrix(model, state)));
        Same(failures, "activity_groups", SodViews.AggregateByGroup(SodViews.ActivityMatrix(view, state)));
        var placed = SodViews.PlaceInGroups(SodViews.RiskMatrix(model, state)["rows"]!.AsArray(), ["GRP_PRC"], false);
        Same(failures, "placed", new JsonArray(placed.Rows, placed.Summaries));
        var reverse = SodViews.PlaceInGroups(SodViews.ActivityMatrix(view, state)["rows"]!.AsArray(), [], true);
        Same(failures, "placed_reverse", new JsonArray(reverse.Rows, reverse.Summaries));
        var explorer = new JsonObject();
        foreach (var table in new[] { "user_risk", "user_activity", "access_list", "lookup" }) explorer[table] = SodViews.ExplorerRows(table, view, state);
        Same(failures, "explorer", explorer);
        Same(failures, "explorer_full", new JsonObject { ["access_list"] = SodViews.ExplorerRows("access_list", model, state), ["lookup"] = SodViews.ExplorerRows("lookup", model, state) });
        Same(failures, "queue", new JsonArray([.. SodViews.QueueItems(view, state)]));
        Same(failures, "queue_full", new JsonArray([.. SodViews.QueueItems(model, state)]));
        Same(failures, "concentration", SodViews.ConflictConcentration(model));
        var actions = Views["actions"]!.AsArray().Select(a => a!.AsObject()).ToList();
        static string Verify(string user, string aid) => string.CompareOrdinal(user + aid, "U") < 0 ? "Still present in current evidence" : "Not present in current evidence";
        var remediation = SodViews.RemediationRows(model, state, actions, Verify, today);
        Same(failures, "remediation", new JsonArray(new JsonArray([.. remediation.Rows]), remediation.Summary));
        var pending = SodViews.RemediationRows(view, state, actions, Verify, today, includePending: true);
        Same(failures, "remediation_pending", new JsonArray(new JsonArray([.. pending.Rows]), pending.Summary));
        Assert.True(failures.Count == 0, string.Join("\n", failures));
    }

    [Theory]
    [InlineData("ZC:FI:AP_CLERK_1000", "1000")]
    [InlineData("Z_ROLE-DE", "DE")]
    [InlineData("PLAIN", "")]
    [InlineData("A:B_", "")]
    public void Role_suffix_is_the_token_after_the_last_separator(string role, string suffix) => Assert.Equal(suffix, SodViews.RoleSuffix(role));
}
