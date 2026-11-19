using System.Globalization;
using System.Text.Json.Nodes;
using AuthLens.Api;
using AuthLens.Domain.Sod;

namespace AuthLens.Tests;

/// <summary>MIG-018: the SoD report and remediation models against Python v1. Fixtures/sod/reports/expected.python.json was written by
/// tools/sod_reports_reference.py: v1 captured, reviewed and approved a period on the synthetic dataset and built report models for several option sets.
/// The .NET builders read the same frozen snapshot and must reproduce every section, table and the sealed model checksum.</summary>
public sealed class SodReportsTests
{
    private static readonly string FixtureText = File.ReadAllText(Path.Combine(AppContext.BaseDirectory, "Fixtures", "sod", "reports", "expected.python.json"));
    private static readonly JsonObject V1Fixture = JsonNode.Parse(FixtureText)!.AsObject();
    /// <summary>The v1 reference with the product named AuthLens (ProductRename); report checksums are resealed below, after the v1 algorithm is proven.</summary>
    private static readonly JsonObject Fixture = JsonNode.Parse(ProductRename.Apply(FixtureText))!.AsObject();

    private static (Dictionary<string, SodUserEntry> View, SodStates State, List<JsonObject> Actions, Func<string, string, string> Verify) Frozen()
    {
        var saved = Fixture["saved"]!.AsObject();
        var model = SodGovernance.Derive(saved["analysis"]!["users"]!.AsArray().Select(f => f!.AsObject()));
        var source = saved["assignment_source"]!.AsObject().Select(p => (p.Key, (IEnumerable<SodGovernance.SourceAssignment>)p.Value!["assignments"]!.AsArray().Select(a => new SodGovernance.SourceAssignment(
            (string)a!["role_name"]!, (string?)a["valid_from"], (string?)a["valid_to"], (string?)a["user_group"] ?? "", (string?)a["match_status"],
            [.. a["catalogue_roles"]!.AsArray().Select(r => (string)r!)], [.. a["tcodes"]!.AsArray().Select(t => (string)t!)])).ToList()));
        var view = SodGovernance.ReviewModel(model, source, "active", DateOnly.ParseExact((string)saved["evaluation_date"]!, "yyyy-MM-dd", CultureInfo.InvariantCulture));
        var decisions = saved["decisions"]!.AsObject();
        var latest = SodGovernance.Decisions.Keys.ToDictionary(k => k, k => (IReadOnlyDictionary<string, SodDecisionEvent>)((decisions["events"]![k] as JsonObject ?? [])
            .ToDictionary(p => p.Key, p => SodDecisionEvent.FromJson(p.Value!.AsArray()[^1]!.AsObject()), StringComparer.Ordinal)), StringComparer.Ordinal);
        var approval = DateOnly.ParseExact((string)Fixture["period"]!["approval_date"]!, "yyyy-MM-dd", CultureInfo.InvariantCulture);
        var state = SodGovernance.States(view, latest, approval);
        var verification = decisions["verification"]!.AsObject();
        return (view, state, [.. decisions["actions"]!.AsArray().Select(a => a!.AsObject())], (_, aid) => (string?)verification[aid] ?? "Not assessed at approval");
    }

    private static string Differences(JsonNode? want, JsonNode? got, string path = "")
    {
        if (JsonNode.DeepEquals(want, got)) return "";
        if (want is JsonObject wo && got is JsonObject go)
            return string.Join("\n", wo.Select(p => p.Key).Union(go.Select(p => p.Key)).Select(k => Differences(wo[k], go[k], path + "." + k)).Where(d => d.Length > 0).Take(3));
        if (want is JsonArray wa && got is JsonArray ga && wa.Count == ga.Count)
            return string.Join("\n", Enumerable.Range(0, wa.Count).Select(i => Differences(wa[i], ga[i], $"{path}[{i}]")).Where(d => d.Length > 0).Take(3));
        string Short(JsonNode? n) { var t = n?.ToJsonString() ?? "null"; return t.Length > 300 ? t[..300] : t; }
        return $"{path}: {Short(got)} vs {Short(want)}";
    }

    [Fact]
    public void Report_models_equal_python_v1_including_the_sealed_checksum()
    {
        var (view, state, actions, verify) = Frozen();
        var failures = new List<string>();
        foreach (var (name, raw) in Fixture["options"]!.AsObject())
        {
            var (options, errors) = SodReports.ParseOptions(raw);
            Assert.True(options is not null, string.Join("; ", errors));
            var inputs = new SodReports.ModelInputs(Fixture["period"]!.AsObject(), Fixture["saved"]!.AsObject(), (string)Fixture["checksum"]!, true, view, state, actions, verify, null, null);
            var model = SodReports.Model(inputs, options!);
            // The sealing algorithm equals v1: v1's own model, resealed, gives v1's checksum.
            var v1Model = V1Fixture["models"]![name]!.DeepClone().AsObject();
            var v1Checksum = (string)v1Model["model_checksum"]!;
            v1Model.Remove("model_checksum");
            Assert.Equal(v1Checksum, (string)SodReports.Seal(v1Model)["model_checksum"]!);
            // The model equals v1's with the product named AuthLens, sealed by that algorithm.
            var want = Fixture["models"]![name]!.DeepClone().AsObject();
            want.Remove("model_checksum");
            SodReports.Seal(want);
            if (!JsonNode.DeepEquals(want, model)) failures.Add($"{name}:\n{Differences(want, model)}");
        }
        Assert.True(failures.Count == 0, string.Join("\n", failures));
    }

    [Fact]
    public void Remediation_models_equal_python_v1()
    {
        var (view, state, actions, verify) = Frozen();
        var saved = Fixture["saved"]!.AsObject();
        var failures = new List<string>();
        foreach (var (name, raw) in Fixture["remediation_options"]!.AsObject())
        {
            var (options, errors) = SodReports.ParseRemediationOptions(raw);
            Assert.True(options is not null, string.Join("; ", errors));
            var inputs = new SodReports.RemediationInputs(Fixture["period"]!.AsObject(), true, (string)Fixture["checksum"]!, view, state, actions, verify, SodReports.ForPeriod(saved),
                saved["organization"], null);
            var model = SodReports.RemediationModel(inputs, options!);
            var want = Fixture["remediation"]![name]!;
            if (!JsonNode.DeepEquals(want, model)) failures.Add($"{name}:\n{Differences(want, model)}");
        }
        Assert.True(failures.Count == 0, string.Join("\n", failures));
    }

    [Fact]
    public void Approval_labels_and_identities_follow_the_v1_rules()
    {
        var (view, state, actions, verify) = Frozen();
        var open = Fixture["period"]!.DeepClone().AsObject();
        open["state"] = "In review";
        var (approved, _) = SodReports.ParseOptions(new JsonObject { ["status"] = "Approved" });
        var refused = Assert.Throws<SodReports.ReportException>(() => SodReports.Model(new SodReports.ModelInputs(open, Fixture["saved"]!.AsObject(), "x", true, view, state, actions, verify, null, null), approved!));
        Assert.Equal(422, refused.Status);
        var (other, _) = SodReports.ParseOptions(new JsonObject { ["approver"] = "Somebody else" });
        Assert.Equal(422, Assert.Throws<SodReports.ReportException>(() => SodReports.Model(new SodReports.ModelInputs(Fixture["period"]!.AsObject(), Fixture["saved"]!.AsObject(), "x", true, view, state, actions, verify, null, null), other!)).Status);
        Assert.Null(SodReports.ParseOptions(new JsonObject { ["sections"] = new JsonArray("executive", "executive") }).Value);
        Assert.Equal("Reviewed", SodReports.ParseOptions(new JsonObject { ["status"] = "For review" }).Value!.Status);   // legacy label
    }
}
