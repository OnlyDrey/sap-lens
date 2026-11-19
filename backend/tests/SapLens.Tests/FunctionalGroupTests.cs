using System.Net;
using System.Net.Http.Json;
using System.Text.Json.Nodes;
using Microsoft.AspNetCore.Builder;
using Microsoft.Extensions.DependencyInjection;
using SapLens.Api;
using SapLens.Application;

namespace SapLens.Tests;

/// <summary>MIG-004 Functional Groups: identity keys, normalization, rule matching, suggestions, legacy migration and the group analysis equal Python v1
/// (tools/functional_groups_reference.py); the catalogue, membership, bulk and filter workflows follow the v1 contract; a shared token never records a
/// confirmation.</summary>
public sealed class FunctionalGroupTests : IAsyncLifetime
{
    private static readonly string Fixtures = Path.Combine(AppContext.BaseDirectory, "Fixtures");
    private static readonly JsonObject Reference = JsonNode.Parse(File.ReadAllText(Path.Combine(Fixtures, "functional-groups", "functional-groups.python.json")))!.AsObject();
    private readonly string _root = Directory.CreateTempSubdirectory("saplens-fg-").FullName;
    private readonly string _token = HostSettings.NewToken();
    private WebApplication _app = null!;
    private HttpClient _client = null!;

    public Task InitializeAsync() => StartAsync(HostMode.Desktop);

    private async Task StartAsync(HostMode mode)
    {
        _app = SapLensHost.Build(new HostSettings { DataDirectory = Path.Combine(_root, "data"), Port = 0, AccessToken = _token, JsonConsoleLogging = false, PrincipalName = "operator", Mode = mode });
        await _app.StartAsync();
        _client = new HttpClient { BaseAddress = new Uri(_app.Urls.First()) };
        _client.DefaultRequestHeaders.Add(RequestBoundary.TokenHeader, _token);
        _client.DefaultRequestHeaders.Add("Origin", _client.BaseAddress.GetLeftPart(UriPartial.Authority));
    }

    public async Task DisposeAsync()
    {
        _client.Dispose();
        await _app.StopAsync();
        await _app.DisposeAsync();
        Microsoft.Data.Sqlite.SqliteConnection.ClearAllPools();
        try { Directory.Delete(_root, true); } catch (IOException) { }
    }

    private async Task ImportAsync()
    {
        foreach (var (source, file) in new[] { ("roles", "roles.sod.txt"), ("users", "users.sod.txt") })
        {
            var path = Path.Combine(_root, source + ".csv");
            File.Copy(Path.Combine(Fixtures, "sod", "analysis", file), path, overwrite: true);
            var revision = (int)JsonNode.Parse(await _client.GetStringAsync("/api/configuration"))!["settings"]!["revision"]!;
            var response = await _client.PostAsJsonAsync($"/api/data-sources/{source}/select", new { path, revision, mode = "static", confirm_anomalies = true });
            Assert.True(response.IsSuccessStatusCode, await response.Content.ReadAsStringAsync());
        }
    }

    private async Task<(HttpStatusCode Status, JsonNode Body)> Send(HttpMethod method, string path, object? body = null)
    {
        var request = new HttpRequestMessage(method, path);
        if (body is not null) request.Content = JsonContent.Create(body);
        var response = await _client.SendAsync(request);
        return (response.StatusCode, JsonNode.Parse(await response.Content.ReadAsStringAsync())!);
    }

    [Fact]
    public void Identity_normalization_rules_suggestions_and_legacy_migration_equal_python_v1()
    {
        foreach (var (name, key) in Reference["user_keys"]!.AsObject()) Assert.Equal((string)key!, FunctionalGroupStore.UserKey(name));
        // Text without compatibility characters (NFKC is the identity for it); the NFKC cases are in the test below.
        foreach (var (text, folded) in Reference["normalized"]!.AsObject().Where(p => p.Key.All(c => char.IsAscii(c) || c == 'ß')))
            Assert.Equal((string)folded!, FunctionalGroupStore.NormalizeText(text));
        var store = new JsonObject { ["format"] = 2, ["groups"] = Reference["legacy"]!["groups"]!.DeepClone(), ["users"] = new JsonObject(), ["history"] = new JsonArray() };
        var rules = new JsonArray();
        // The rules are those of the reference (recovered from the suggestion matches); compare rule_matches per rule and person.
        var ruleSet = new Dictionary<string, JsonObject>
        {
            ["fr_000000000001"] = new() { ["id"] = "fr_000000000001", ["group_id"] = "fg_aaaaaaaaaaaa", ["department"] = "Finance", ["title_contains"] = "", ["department_mode"] = "contains" },
            ["fr_000000000002"] = new() { ["id"] = "fr_000000000002", ["group_id"] = "fg_aaaaaaaaaaaa", ["department"] = "", ["title_contains"] = "Accountant", ["department_mode"] = "contains" },
            ["fr_000000000003"] = new() { ["id"] = "fr_000000000003", ["group_id"] = "fg_bbbbbbbbbbbb", ["department"] = "Finance Ops", ["title_contains"] = "Buyer", ["department_mode"] = "equals" },
            ["fr_000000000004"] = new() { ["id"] = "fr_000000000004", ["group_id"] = "fg_cccccccccccc", ["department"] = "Finance", ["title_contains"] = "" },
            ["fr_000000000005"] = new() { ["id"] = "fr_000000000005", ["group_id"] = "fg_bbbbbbbbbbbb", ["department"] = "Procurement", ["title_contains"] = "", ["department_mode"] = "equals" },
        };
        foreach (var match in Reference["matches"]!.AsArray())
        {
            var actual = FunctionalGroupStore.RuleMatches(ruleSet[(string)match!["rule"]!], (string)match["department"]!, (string)match["title"]!);
            var expected = match["reasons"] as JsonArray;
            Assert.Equal(expected?.Select(r => (string)r!), actual);
        }
        foreach (var rule in ruleSet.Values) rules.Add(rule.DeepClone());
        store["rules"] = rules;
        foreach (var item in Reference["suggestions"]!.AsArray())
        {
            var actual = FunctionalGroupStore.Suggest(store, (string)item!["department"]!, (string)item["title"]!, item["held"]!.AsArray().Select(h => (string)h!));
            Assert.True(JsonNode.DeepEquals(item["result"], actual), $"expected {item["result"]!.ToJsonString()}\nactual   {actual.ToJsonString()}");
        }
        var migrated = FunctionalGroupStore.Validate(Reference["legacy"]!.DeepClone());
        Assert.True(JsonNode.DeepEquals(Reference["migrated"], migrated), $"expected {Reference["migrated"]!.ToJsonString()}\nactual   {migrated.ToJsonString()}");
        // A broken store is refused, never silently repaired.
        var broken = Reference["migrated"]!.DeepClone().AsObject();
        broken["users"]!.AsObject().First().Value!["username"] = "SOMEONE ELSE";
        Assert.Throws<FormatException>(() => FunctionalGroupStore.Validate(broken));
    }

    /// <summary>Blocked (BLK-GLOBALIZATION in MIGRATION_MATRIX.md): the server builds with InvariantGlobalization, where NFKC normalization of
    /// compatibility characters (ligatures, full-width letters, no-break space) is not available; v1 folds them. Enabling ICU is a packaging decision.</summary>
    [Fact]
    public void Compatibility_characters_fold_like_python_v1()
    {
        foreach (var (text, folded) in Reference["normalized"]!.AsObject()) Assert.Equal((string)folded!, FunctionalGroupStore.NormalizeText(text));
    }

    [Fact]
    public async Task Group_analysis_equals_python_v1()
    {
        await ImportAsync();
        var snapshot = await _app.Services.GetRequiredService<SnapshotService>().GetAsync(CancellationToken.None);
        var group = Reference["legacy"]!["groups"]!["fg_aaaaaaaaaaaa"]!.AsObject();
        foreach (var run in Reference["analyses"]!.AsArray())
        {
            var actual = V1FunctionalGroups.Analyse(snapshot.Users, run!["members"]!.AsArray().Select(m => (string)m!).ToList(), group, DateOnly.Parse((string)run["today"]!, System.Globalization.CultureInfo.InvariantCulture));
            Assert.True(JsonNode.DeepEquals(run["result"], actual), $"expected {run["result"]!.ToJsonString()}\nactual   {actual.ToJsonString()}");
        }
    }

    [Fact]
    public async Task Catalogue_memberships_bulk_and_filters_follow_the_v1_contract()
    {
        await ImportAsync();
        var (status, finance) = await Send(HttpMethod.Post, "/api/functional-groups", new { name = "  Finance   Operations ", description = "AP and AR" });
        Assert.Equal(HttpStatusCode.OK, status);
        Assert.Equal("Finance Operations", (string)finance["name"]!);
        var gid = (string)finance["id"]!;
        Assert.Matches("^fg_[a-f0-9]{12}$", gid);
        Assert.Equal(HttpStatusCode.Conflict, (await Send(HttpMethod.Post, "/api/functional-groups", new { name = "finance operations" })).Status);
        Assert.Equal(HttpStatusCode.UnprocessableEntity, (await Send(HttpMethod.Post, "/api/functional-groups", new { name = "x", extra = 1 })).Status);
        var (_, buyers) = await Send(HttpMethod.Post, "/api/functional-groups", new { name = "Buyers" });
        var bid = (string)buyers["id"]!;

        // Memberships: add, idempotent repeat, optimistic revision, removal needs a rationale; history records each change.
        var (s1, added) = await Send(HttpMethod.Post, "/api/functional-groups/memberships", new { username = "user00152", group_id = gid, rationale = "Owns AP", reviewer = "Ada Reviewer", expected_revision = 0 });
        Assert.Equal(HttpStatusCode.OK, s1);
        Assert.Equal("added", (string)added["outcome"]!);
        Assert.Equal("Confirmed", (string)added["classification"]!["status"]!);
        Assert.Equal("Ada Reviewer", (string)added["classification"]!["confirmed_by"]!);
        Assert.Equal("unchanged", (string)(await Send(HttpMethod.Post, "/api/functional-groups/memberships", new { username = "USER00152", group_id = gid, reviewer = "Ada Reviewer", expected_revision = 1 })).Body["outcome"]!);
        Assert.Equal(HttpStatusCode.Conflict, (await Send(HttpMethod.Post, "/api/functional-groups/memberships", new { username = "USER00152", group_id = bid, reviewer = "Ada Reviewer", expected_revision = 0 })).Status);
        await Send(HttpMethod.Post, "/api/functional-groups/memberships", new { username = "USER00152", group_id = bid, reviewer = "Ada Reviewer", expected_revision = 1 });
        Assert.Equal(HttpStatusCode.UnprocessableEntity, (await Send(HttpMethod.Post, "/api/functional-groups/memberships/remove", new { username = "USER00152", group_id = bid, reviewer = "Ada Reviewer", expected_revision = 2 })).Status);
        Assert.Equal(HttpStatusCode.NotFound, (await Send(HttpMethod.Post, "/api/functional-groups/memberships", new { username = "NOBODY", group_id = gid, reviewer = "Ada Reviewer", expected_revision = 0 })).Status);
        var user = JsonNode.Parse(await _client.GetStringAsync("/api/functional-groups/users/user00152"))!;
        Assert.Equal(2, user["classification"]!["memberships"]!.AsArray().Count);
        Assert.Null(user["classification"]!["group_id"]);                                      // only with exactly one membership
        Assert.Equal(2, (int)user["history"]!["total"]!);

        // Bulk: preview, apply once, a replayed operation is refused, a stale selection is refused.
        var (_, preview) = await Send(HttpMethod.Post, "/api/functional-groups/bulk/preview", new { group_ids = new[] { gid }, usernames = new[] { "USER00152", "user00170", "GHOST" } });
        Assert.Equal(1, (int)preview["counts"]!["existing"]!);
        Assert.Equal(["GHOST"], preview["missing"]!.AsArray().Select(m => (string)m!));
        var operation = new { group_ids = new[] { gid }, usernames = new[] { "user00170", "USER00017", "GHOST" }, operation_id = "op-00000001", expected = new Dictionary<string, int>(), reviewer = "Ada Reviewer",
            data_revision = (string)preview["data_revision"]! };
        var (_, bulk) = await Send(HttpMethod.Post, "/api/functional-groups/bulk", operation);
        Assert.Equal("partial", (string)bulk["status"]!);
        Assert.Equal(2, bulk["applied"]!.AsArray().Count);
        Assert.Equal("not_in_dataset", (string)bulk["rejected"]![0]!["reason"]!);
        Assert.Equal(HttpStatusCode.Conflict, (await Send(HttpMethod.Post, "/api/functional-groups/bulk", operation)).Status);
        var stale = await Send(HttpMethod.Post, "/api/functional-groups/bulk/preview", new { group_ids = new[] { gid }, usernames = new[] { "USER00152" }, data_revision = "x.999.0" });
        Assert.Equal(("stale_dataset", HttpStatusCode.Conflict), ((string)stale.Body["detail"]!["code"]!, stale.Status));

        // Catalogue counts, members, options and the User Access / Account Review filters.
        var list = JsonNode.Parse(await _client.GetStringAsync("/api/functional-groups"))!["items"]!.AsArray();
        Assert.Equal(3, (int)list.Single(g => (string)g!["id"]! == gid)!["user_count"]!);
        var members = JsonNode.Parse(await _client.GetStringAsync($"/api/functional-groups/{gid}/members"))!;
        Assert.Equal(3, (int)members["total"]!);
        Assert.Equal(["Buyers"], members["items"]!.AsArray().Single(m => ((string)m!["username"]!).ToUpperInvariant() == "USER00152")!["other_groups"]!.AsArray().Select(n => (string)n!));
        var options = JsonNode.Parse(await _client.GetStringAsync("/api/functional-groups/options"))!["functional_groups"]!.AsArray();
        Assert.Equal(3, (int)options.Single(o => (string)o!["value"]! == gid)!["count"]!);
        var access = JsonNode.Parse(await _client.GetStringAsync($"/api/access/users?functional_groups={gid}&limit=100"))!;
        Assert.Equal(3, (int)access["total"]!);
        Assert.Contains(access["items"]!.AsArray(), i => i!["functional_groups"]!.AsArray().Count == 2);
        var unassigned = JsonNode.Parse(await _client.GetStringAsync("/api/access/users?functional_groups=unassigned&limit=1"))!;
        var all = JsonNode.Parse(await _client.GetStringAsync("/api/access/users?limit=1"))!;
        Assert.Equal((int)all["total"]! - 3, (int)unassigned["total"]!);
        var review = JsonNode.Parse(await _client.GetStringAsync($"/api/account-review?functional_groups={gid}&include_completed=true&limit=100"))!;
        Assert.Equal(2, (int)review["total"]!);                                                 // v1 filters by the sole membership's group
        Assert.Contains(review["functional_group_options"]!.AsArray(), o => (string)o!["value"]! == gid);

        // Rules: duplicate refused; a group is deleted only when archived and with the confirmed member count (permanent deletion: see below).
        var (_, rule) = await Send(HttpMethod.Post, "/api/functional-groups/rules", new { group_id = gid, department = "Finance" });
        Assert.Equal("contains", (string)rule["department_mode"]!);
        Assert.Equal(HttpStatusCode.Conflict, (await Send(HttpMethod.Post, "/api/functional-groups/rules", new { group_id = gid, department = " finance " })).Status);
        Assert.Equal(HttpStatusCode.Conflict, (await Send(HttpMethod.Delete, $"/api/functional-groups/{gid}?expected_members=3")).Status);
        await Send(HttpMethod.Post, $"/api/functional-groups/{gid}/archive");
        Assert.Equal(HttpStatusCode.Conflict, (await Send(HttpMethod.Post, "/api/functional-groups/memberships", new { username = "USER00296", group_id = gid, reviewer = "Ada Reviewer", expected_revision = 0 })).Status);
        var (_, empty) = await Send(HttpMethod.Post, "/api/functional-groups", new { name = "Temporary" });
        await Send(HttpMethod.Post, $"/api/functional-groups/{(string)empty["id"]!}/archive");
        Assert.Equal("deleted", (string)(await Send(HttpMethod.Delete, $"/api/functional-groups/{(string)empty["id"]!}?expected_members=0")).Body["status"]!);
    }

    [Fact]
    public async Task An_archived_group_with_members_is_deleted_permanently_without_touching_users_or_evidence()
    {
        await ImportAsync();
        var (_, kept) = await Send(HttpMethod.Post, "/api/functional-groups", new { name = "Buyers" });
        var (_, doomed) = await Send(HttpMethod.Post, "/api/functional-groups", new { name = "Planners" });
        var (keptId, gid) = ((string)kept["id"]!, (string)doomed["id"]!);
        async Task<int> Revision(string user) => (int)JsonNode.Parse(await _client.GetStringAsync($"/api/functional-groups/users/{user}"))!["classification"]!["revision"]!;
        foreach (var user in new[] { "USER00152", "USER00170" })
            Assert.Equal(HttpStatusCode.OK, (await Send(HttpMethod.Post, "/api/functional-groups/memberships", new { username = user, group_id = gid, reviewer = "Ada Reviewer", expected_revision = await Revision(user) })).Status);
        Assert.Equal(HttpStatusCode.OK, (await Send(HttpMethod.Post, "/api/functional-groups/memberships", new { username = "USER00152", group_id = keptId, reviewer = "Ada Reviewer", expected_revision = await Revision("USER00152") })).Status);
        await Send(HttpMethod.Post, "/api/functional-groups/rules", new { group_id = gid, department = "Planning" });
        await Send(HttpMethod.Post, "/api/functional-groups/rules", new { group_id = keptId, department = "Purchasing" });
        var usersBefore = (int)JsonNode.Parse(await _client.GetStringAsync("/api/access/users?limit=1"))!["total"]!;
        var rolesBefore = await _client.GetStringAsync("/api/roles");
        var document = async () => await _client.GetStringAsync("/api/functional-groups") + await _client.GetStringAsync("/api/functional-groups/rules")
            + await _client.GetStringAsync("/api/functional-groups/users/USER00152") + await _client.GetStringAsync("/api/functional-groups/users/USER00170");

        // Active groups are never deleted; a request without the confirmed member count, or with a different one, changes nothing.
        var before = await document();
        var active = await Send(HttpMethod.Delete, $"/api/functional-groups/{gid}?expected_members=2");
        Assert.Equal(HttpStatusCode.Conflict, active.Status);
        Assert.Contains("Archive", (string)active.Body["detail"]!);
        await Send(HttpMethod.Post, $"/api/functional-groups/{gid}/archive");
        var archived = await document();
        Assert.Equal(HttpStatusCode.UnprocessableEntity, (await Send(HttpMethod.Delete, $"/api/functional-groups/{gid}")).Status);
        var stale = await Send(HttpMethod.Delete, $"/api/functional-groups/{gid}?expected_members=1");      // a member was added after the dialog opened
        Assert.Equal(HttpStatusCode.Conflict, stale.Status);
        Assert.Contains("now has 2 member(s), not the 1 confirmed", (string)stale.Body["detail"]!);
        Assert.Equal(archived, await document());
        Assert.NotEqual(before, archived);                                                     // only the archive itself changed the catalogue

        // Delete: the memberships and the group's rules go; users, other memberships, other rules, SAP data and history stay.
        var revision = await Revision("USER00170");
        var (status, deleted) = await Send(HttpMethod.Delete, $"/api/functional-groups/{gid}?expected_members=2");
        Assert.Equal(HttpStatusCode.OK, status);
        Assert.Equal(("deleted", 2, 1), ((string)deleted["status"]!, (int)deleted["members_removed"]!, (int)deleted["rules_removed"]!));
        Assert.DoesNotContain(JsonNode.Parse(await _client.GetStringAsync("/api/functional-groups"))!["items"]!.AsArray(), g => (string)g!["id"]! == gid);
        var rules = JsonNode.Parse(await _client.GetStringAsync("/api/functional-groups/rules"))!["items"]!.AsArray();
        Assert.Equal([keptId], rules.Select(r => (string)r!["group_id"]!));
        var buyer = JsonNode.Parse(await _client.GetStringAsync("/api/functional-groups/users/USER00152"))!;
        Assert.Equal([keptId], buyer["classification"]!["memberships"]!.AsArray().Select(m => (string)m!["group_id"]!));
        var planner = JsonNode.Parse(await _client.GetStringAsync("/api/functional-groups/users/USER00170"))!;
        Assert.Equal("Unassigned", (string)planner["classification"]!["status"]!);
        Assert.Equal(usersBefore, (int)JsonNode.Parse(await _client.GetStringAsync("/api/access/users?limit=1"))!["total"]!);
        Assert.Equal(rolesBefore, await _client.GetStringAsync("/api/roles"));
        // History keeps the assignment and records the removal; the deleted group's name stays resolvable.
        var history = planner["history"]!["items"]!.AsArray();
        Assert.Equal(["removed", "assigned"], history.Select(e => (string)e!["event"]!));
        Assert.All(history, e => Assert.Equal(("Planners", true), ((string?)e!["previous_group_name"] ?? (string?)e["new_group_name"], (bool)e["group_deleted"]!)));
        Assert.Equal("Functional Group \"Planners\" was deleted.", (string)history[0]!["reason"]!);
        // A classification loaded before the deletion is refused instead of silently restoring the membership.
        Assert.Equal(HttpStatusCode.Conflict, (await Send(HttpMethod.Post, "/api/functional-groups/memberships", new { username = "USER00170", group_id = keptId, reviewer = "Ada Reviewer", expected_revision = revision })).Status);
        // Audit trail: archive and delete with actor, time, identity and counts.
        var audit = JsonNode.Parse(await _client.GetStringAsync("/api/functional-groups/audit"))!["items"]!.AsArray();
        Assert.Equal(["deleted", "archived"], audit.Select(e => (string)e!["event"]!));
        Assert.Equal((gid, "Planners", 2, 1, "operator"), ((string)audit[0]!["group_id"]!, (string)audit[0]!["group_name"]!, (int)audit[0]!["members"]!, (int)audit[0]!["rules"]!, (string)audit[0]!["actor"]!));
        Assert.True(DateTimeOffset.TryParse((string)audit[0]!["timestamp"]!, out _));
        Assert.Equal(HttpStatusCode.NotFound, (await Send(HttpMethod.Delete, $"/api/functional-groups/{gid}?expected_members=0")).Status);
        // The stored document stays valid across a restart (deleted references resolve through the audit event).
        await _app.StopAsync(); await _app.DisposeAsync(); _client.Dispose();
        await StartAsync(HostMode.Desktop);
        Assert.Equal(2, (int)JsonNode.Parse(await _client.GetStringAsync("/api/functional-groups/users/USER00170"))!["history"]!["total"]!);
    }

    [Fact]
    public void Deletion_and_the_audit_trail_are_administrator_operations()
    {
        Assert.Equal("admin", V1Auth.Permission("DELETE", "/api/functional-groups/fg_000000000000"));
        Assert.Equal("admin", V1Auth.Permission("POST", "/api/functional-groups/fg_000000000000/archive"));
        Assert.Equal("admin", V1Auth.Permission("GET", "/api/functional-groups/audit"));
        Assert.Equal("read", V1Auth.Permission("GET", "/api/functional-groups"));
    }

    [Fact]
    public async Task A_shared_access_token_cannot_record_a_classification()
    {
        await DisposeAsync();
        Directory.CreateDirectory(_root);
        await StartAsync(HostMode.Server);
        foreach (var (source, file) in new[] { ("roles", "roles.sod.txt"), ("users", "users.sod.txt") })
        {
            var revision = (int)JsonNode.Parse(await _client.GetStringAsync("/api/configuration"))!["settings"]!["revision"]!;
            var form = new MultipartFormDataContent
            {
                { new ByteArrayContent(File.ReadAllBytes(Path.Combine(Fixtures, "sod", "analysis", file))), "file", source + ".csv" },
                { new StringContent(revision.ToString()), "revision" }, { new StringContent("true"), "confirm_anomalies" },
            };
            Assert.True((await _client.PostAsync($"/api/server/uploads/{source}/activate", form)).IsSuccessStatusCode);
        }
        var (_, group) = await Send(HttpMethod.Post, "/api/functional-groups", new { name = "Finance" });
        var (status, body) = await Send(HttpMethod.Post, "/api/functional-groups/memberships", new { username = "USER00152", group_id = (string)group["id"]!, reviewer = "Ada", expected_revision = 0 });
        Assert.Equal(HttpStatusCode.Forbidden, status);
        Assert.Contains("shared access token is not a reviewer identity", (string)body["detail"]!);
        Assert.Equal(HttpStatusCode.Forbidden, (await Send(HttpMethod.Post, "/api/functional-groups/bulk", new { group_ids = new[] { (string)group["id"]! }, usernames = new[] { "USER00152" }, operation_id = "op-00000002", reviewer = "Ada" })).Status);
        Assert.Equal(0, (int)JsonNode.Parse(await _client.GetStringAsync("/api/functional-groups"))!["items"]![0]!["references"]!["history"]!);
    }
}
