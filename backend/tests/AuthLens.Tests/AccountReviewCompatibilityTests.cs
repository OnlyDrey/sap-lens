using System.Text.Json;
using AuthLens.Api;
using AuthLens.Application;
using AuthLens.Domain.Catalogue;
using AuthLens.Domain.Users;
using AuthLens.Persistence;

namespace AuthLens.Tests;

public sealed class AccountReviewCompatibilityTests
{
    // Independent Python json.dumps vectors, including default ASCII escaping in nested evidence,
    // non-BMP text and Python's Unicode-scalar ordering. No Python runtime is needed by these tests.
    private const string V1 = "427546c96134f61c4dd0531c953f1ab7355bb8a6ec86d1ccab726ea3c429d8b3";
    private const string UnicodeV1 = "6ff6f4acc92f3179e29480af9f1329a80c5c82f87e89642edb651273dc7bc7bf";
    private static Snapshot Fixture(bool unicode = false)
    {
        var group = unicode ? "GRØUP" : "SYNTHETIC";
        var role = unicode ? "ZC:FI:Ø_TEST" : "ZC:FI:ROLE_TEST";
        var user = new SapUser { Username = "SYNTHETIC0001", Names = unicode ? [("Åse😀", "Person"), ("\ue000", "Last"), ("\U00010000", "Last")] : [("Test", "Person")],
            Emails = ["TEST@EXAMPLE.INVALID"], Groups = [group], Accounts = [new Account("2000-01-01", "9999-12-31", false, "A", group)] };
        user.Assignments.Add(new Assignment { Username = user.Username, UserKey = user.Username, RoleName = role, UserGroup = group, Scope = "business",
            ValidFrom = "2000-01-01", ValidTo = "9999-12-31", UserType = "A", MatchStatus = "exact", CatalogueRoles = [role], Tcodes = ["FB01"] });
        var users = new UserDirectory(); users.Users.Add(user.Username, user); users.UserOrder.Add(user.Username);
        return new Snapshot { Ids = new ActiveIds(1, 2, null), Catalogue = new RoleCatalogue(), Users = users, AssignmentKeys = [] };
    }

    private static ReviewDecision Decision(string evidence, string details = "{\"evidence_schema\":2}") => new()
    {
        SubjectType = "account", SubjectKey = Sources.AccountKey("SYNTHETIC0001"), EvidenceVersion = evidence, Decision = "No action required",
        Reviewer = "Synthetic", Hash = "immutable", PreviousHash = "previous", DetailsJson = details,
    };
    private static Dictionary<string, object?> Row(Snapshot state, ReviewDecision? decision = null, bool invalidated = false) =>
        V1AccountReview.Rows(state, null, decision is null ? [] : new Dictionary<string, V1AccountReview.Stored> { [decision.SubjectKey] = new(decision, [], invalidated) }, [], new DateOnly(2026, 11, 20)).Single();

    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public void Unchanged_V1_schema_2_evidence_is_current_without_rewriting_history(bool unicode)
    {
        var state = Fixture(unicode); var d = Decision(unicode ? UnicodeV1 : V1); var before = JsonSerializer.Serialize(d);
        Assert.False((bool)Row(state, d)["stale"]!);
        Assert.Equal("completed", Row(state, d)["workflow_status"]);
        Assert.Equal(before, JsonSerializer.Serialize(d));
    }

    [Theory]
    [InlineData("identity")]
    [InlineData("assignment")]
    [InlineData("account")]
    [InlineData("group")]
    public void A_changed_V1_evidence_field_still_invalidates_the_decision(string field)
    {
        var state = Fixture(); var user = state.Users.Users.Values.Single();
        if (field == "identity") user.Emails = ["changed@example.invalid"];
        if (field == "assignment") user.Assignments.Clear();
        if (field == "account") user.Accounts = [user.Accounts[0] with { Locked = true }];
        if (field == "group") user.Groups.Add("CHANGED");
        Assert.True((bool)Row(state, Decision(V1))["stale"]!);
    }

    [Fact]
    public void V1_and_current_dotnet_decisions_keep_their_own_fingerprints_and_invalidation_guards()
    {
        var state = Fixture(); var current = (string)Row(state)["evidence_version"]!;
        Assert.NotEqual(V1, current);
        var legacy = Decision(V1); var modern = Decision(current);
        foreach (var d in new[] { legacy, modern })
        {
            Assert.False((bool)Row(state, d)["stale"]!);
            Assert.True((bool)Row(state, d, invalidated: true)["stale"]!);
            var absent = Decision(d.EvidenceVersion!, "{\"evidence_schema\":2,\"absent_since\":\"2026-11-01T00:00:00+00:00\"}");
            Assert.True((bool)Row(state, absent)["stale"]!);
        }
        state.Users.Users.Values.Single().Names = [("Different", "Identity")];
        Assert.True((bool)Row(state, legacy)["stale"]!);
        Assert.True((bool)Row(state, modern)["stale"]!);
    }

    [Theory]
    [InlineData("{}")]
    [InlineData("{\"evidence_schema\":1}")]
    [InlineData("{\"evidence_schema\":99}")]
    public void Unestablished_schemas_do_not_receive_V1_schema_2_compatibility(string details) =>
        Assert.True((bool)Row(Fixture(), Decision(V1, details))["stale"]!);

    [Fact]
    public void Mixed_users_keep_independent_V1_and_dotnet_applicability()
    {
        var state = Fixture(); var original = state.Users.Users.Values.Single();
        var second = new SapUser { Username = "SYNTHETIC0002", Names = [.. original.Names], Emails = [.. original.Emails], Groups = [.. original.Groups], Accounts = [.. original.Accounts] };
        second.Assignments.AddRange(original.Assignments);
        state.Users.Users.Add(second.Username, second); state.Users.UserOrder.Add(second.Username);
        List<Dictionary<string, object?>> Read(Dictionary<string, V1AccountReview.Stored> saved) => V1AccountReview.Rows(state, null, saved, [], new DateOnly(2026, 11, 20));
        var modern = Decision((string)Read([])[1]["evidence_version"]!); modern.SubjectKey = Sources.AccountKey(second.Username);
        var old = Decision(V1);
        var saved = new Dictionary<string, V1AccountReview.Stored> { [old.SubjectKey] = new(old, [], false), [modern.SubjectKey] = new(modern, [], false) };
        var before = JsonSerializer.Serialize(new[] { old, modern });
        Assert.All(Read(saved), row => Assert.False((bool)row["stale"]!));
        original.Emails = ["changed@example.invalid"];
        var after = Read(saved);
        Assert.True((bool)after[0]["stale"]!); Assert.False((bool)after[1]["stale"]!);
        Assert.Equal(before, JsonSerializer.Serialize(new[] { old, modern }));
    }
}
