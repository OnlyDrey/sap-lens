using System.Text.Json;
using System.Text.Json.Nodes;
using AuthLens.Application;
using AuthLens.Domain.Directory;
using AuthLens.Domain.Roles;
using AuthLens.Domain.Users;

namespace AuthLens.Api;

/// <summary>MIG-004, port of routers/functional_groups.py, organization.py and functional_group_analysis.py: the Functional Group catalogue, per-user
/// memberships with history, advisory suggestion rules, bulk assignment and the group/manager choices used by User Access and Account Review filters.
/// Writes that record a confirmation (memberships, classification, bulk assignment) need an individual identity: a server account or the local
/// Desktop user. A shared access token is not a reviewer identity (stricter than v1, which recorded the token's operator name).</summary>
public static class V1FunctionalGroups
{
    private const string MappingDisabled = "User–Role Mapping is disabled. Enable it in Settings → Features; imported data is retained.";

    public static void Map(RouteGroupBuilder api)
    {
        var fg = api.MapGroup("/functional-groups").AddEndpointFilter(async (context, next) =>
        {
            try { return await next(context); }
            catch (V1Problem problem) { return problem.ToResult(); }
        });

        fg.MapGet("", async (FunctionalGroupStore store, bool? include_archived, CancellationToken ct) =>
            Json(new JsonObject
            {
                ["items"] = new JsonArray([.. FunctionalGroupStore.ListGroups(await store.ReadAsync(ct), include_archived ?? true)]),
                ["statuses"] = new JsonArray([.. FunctionalGroupStore.Statuses.Select(s => (JsonNode)s)]),
            }));
        fg.MapPost("", async (HttpContext http, FunctionalGroupStore store, CancellationToken ct) =>
        {
            var (body, invalid) = await Body(http, ["name", "description"], ct);
            if (invalid is not null) return invalid;
            var errors = new List<object>();
            var name = V1Validation.Text(body!, "name", 1, 80, true, errors);
            var description = V1Validation.Text(body!, "description", 0, 500, false, errors) ?? "";
            if (errors.Count > 0) return Errors(errors);
            return Json(await store.CreateGroupAsync(name!, description, Actors.Name(http), ct));
        });
        fg.MapPatch("/{gid}", async (string gid, HttpContext http, FunctionalGroupStore store, CancellationToken ct) =>
        {
            var (body, invalid) = await Body(http, ["name", "description"], ct);
            if (invalid is not null) return invalid;
            var errors = new List<object>();
            var name = body!["name"] is null ? null : V1Validation.Text(body, "name", 1, 80, false, errors);
            var description = body["description"] is null ? null : V1Validation.Text(body, "description", 0, 500, false, errors);
            if (errors.Count > 0) return Errors(errors);
            return Json(await store.UpdateGroupAsync(gid, name, description, Actors.Name(http), ct));
        });
        fg.MapPost("/{gid}/archive", async (string gid, HttpContext http, FunctionalGroupStore store, CancellationToken ct) => Json(await store.SetStatusAsync(gid, "archived", Actors.Name(http), ct)));
        fg.MapPost("/{gid}/restore", async (string gid, HttpContext http, FunctionalGroupStore store, CancellationToken ct) => Json(await store.SetStatusAsync(gid, "active", Actors.Name(http), ct)));
        // Permanent deletion: the group must be archived and the request must repeat the member count the person confirmed (`expected_members`).
        fg.MapDelete("/{gid}", async (string gid, HttpContext http, FunctionalGroupStore store, CancellationToken ct) =>
        {
            if (!int.TryParse(http.Request.Query["expected_members"], System.Globalization.NumberStyles.None, System.Globalization.CultureInfo.InvariantCulture, out var expected))
                return Detail(422, "Confirm the deletion with the number of members shown (expected_members).");
            return Json(await store.DeleteGroupAsync(gid, expected, Actors.Name(http), ct));
        });
        fg.MapGet("/audit", async (FunctionalGroupStore store, int? offset, int? limit, CancellationToken ct) =>
        {
            var (o, l) = (offset ?? 0, limit ?? 50);
            if (o < 0 || l is < 1 or > 200) return Detail(422, "Invalid audit query.");
            return Json(FunctionalGroupStore.CatalogueHistory(await store.ReadAsync(ct), o, l));
        });

        var mapped = fg.MapGroup("").AddEndpointFilter(async (context, next) =>
        {
            var settings = await context.HttpContext.RequestServices.GetRequiredService<V1Settings>().GetAsync(context.HttpContext.RequestAborted);
            return ((bool?)settings["features"]?["user_role_mapping"] ?? true) ? await next(context) : Detail(409, MappingDisabled);
        });

        mapped.MapGet("/options", async (HttpContext http, FunctionalGroupStore store, CancellationToken ct) =>
        {
            var (snapshot, directory) = await StateAsync(http, ct);
            return Json(Options(snapshot, directory, await store.ReadAsync(ct)));
        });

        mapped.MapGet("/{gid}/members", async (string gid, HttpContext http, FunctionalGroupStore store, string? search, string? status, int? offset, int? limit, CancellationToken ct) =>
        {
            var (o, l) = (offset ?? 0, limit ?? 50);
            if ((search ?? "").Length > 200 || (status ?? "").Length > 20 || o < 0 || l is < 1 or > 200) return Detail(422, "Invalid members query.");
            var data = await store.ReadAsync(ct);
            if (data["groups"]![gid] is not JsonObject group) return Detail(404, "Functional Group not found.");
            var (snapshot, directory) = await StateAsync(http, ct);
            var owners = directory is null ? null : EmployeeDirectory.SapEmailOwners(snapshot.Users.Users.Values);
            var people = snapshot.Users.Users.Values.ToDictionary(u => u.Username.Trim().PyUpper(), u => u);
            var needle = Fold((search ?? "").Trim());
            var rows = new List<JsonObject>();
            foreach (var (_, user) in data["users"]!.AsObject())
            {
                if (user!["memberships"]![gid] is not JsonObject member) continue;
                var username = (string)user["username"]!;
                people.TryGetValue(username.Trim().PyUpper(), out var sap);
                Dictionary<string, object?>? employee = null;
                var identity = "not_in_import";
                if (sap is not null)
                {
                    identity = "unmatched";
                    if (directory is not null && directory.MatchSapIdentity(sap, owners!) is ("matched", { } found)) (employee, identity) = (found, "matched");
                }
                var names = sap?.Names.Select(n => string.Join(' ', new[] { n.First, n.Last }.Where(p => p.Length > 0)).Trim()) ?? [];
                var row = new JsonObject
                {
                    ["username"] = username, ["full_name"] = (string?)employee?["name"] is { Length: > 0 } en ? en : names.FirstOrDefault(n => n.Length > 0) ?? "",
                    ["department"] = (string?)employee?["department"] ?? "", ["title"] = (string?)employee?["title"] ?? "", ["identity"] = identity,
                    ["status"] = member["status"]!.DeepClone(), ["confirmed_at"] = (string?)member["confirmed_at"] is { Length: > 0 } c ? c : null,
                    ["confirmed_by"] = (string?)member["confirmed_by"] ?? "", ["revision"] = user["revision"]!.DeepClone(), ["review"] = member["review"]?.DeepClone(),
                    ["other_groups"] = new JsonArray([.. user["memberships"]!.AsObject().Select(p => p.Key).Where(g => g != gid)
                        .Select(g => (string)data["groups"]![g]!["name"]!).Order(StringComparer.Ordinal).Select(n => (JsonNode)n)]),
                };
                if ((status ?? "").Length > 0 && (string?)row["status"] != status) continue;
                if (needle.Length > 0 && !Fold(string.Join(' ', new[] { "username", "full_name", "department", "title" }.Select(k => (string?)row[k]))).Contains(needle, StringComparison.Ordinal)) continue;
                rows.Add(row);
            }
            rows = rows.OrderBy(r => Fold((string)r["username"]!), StringComparer.Ordinal).ToList();
            return Json(new JsonObject
            {
                ["group"] = new JsonObject { ["id"] = gid, ["name"] = group["name"]!.DeepClone(), ["status"] = group["status"]!.DeepClone() },
                ["total"] = rows.Count, ["items"] = new JsonArray([.. rows.Skip(o).Take(l)]), ["offset"] = o, ["limit"] = l,
            });
        });

        mapped.MapGet("/analysis/{gid}", async (string gid, HttpContext http, FunctionalGroupStore store, TimeProvider clock, CancellationToken ct) =>
        {
            var data = await store.ReadAsync(ct);
            if (data["groups"]![gid] is not JsonObject group) return Detail(404, "Functional Group not found.");
            var members = data["users"]!.AsObject().Where(p => p.Value!["memberships"]![gid] is not null).Select(p => (string)p.Value!["username"]!).ToList();
            var (snapshot, _) = await StateAsync(http, ct);
            return Json(Analyse(snapshot.Users, members, group, DateOnly.FromDateTime(clock.GetLocalNow().DateTime)));
        });

        mapped.MapPost("/bulk/preview", async (HttpContext http, FunctionalGroupStore store, CancellationToken ct) =>
        {
            var (bulk, invalid) = await BulkBody(http, assign: false, ct);
            if (invalid is not null) return invalid;
            var (snapshot, _) = await StateAsync(http, ct);
            var (known, missing, stale) = Resolve(snapshot, bulk!);
            if (stale is not null) return stale;
            var preview = FunctionalGroupStore.BulkPreview(await store.ReadAsync(ct), Targets(bulk!), known);
            preview["missing"] = new JsonArray([.. missing.Select(m => (JsonNode)m)]);
            preview["requested"] = known.Count + missing.Count;
            preview["data_revision"] = Revision(snapshot);
            return Json(preview);
        });

        mapped.MapPost("/bulk", async (HttpContext http, FunctionalGroupStore store, CancellationToken ct) =>
        {
            var (bulk, invalid) = await BulkBody(http, assign: true, ct);
            if (invalid is not null) return invalid;
            var (who, refused) = await Reviewer(http, ct);
            if (refused is not null) return refused;
            if ((bool?)bulk!["replace_existing"] == true) return Detail(422, "Replacing memberships is not supported: assignment adds groups. Remove a membership on the user instead.");
            var groups = Targets(bulk);
            var (snapshot, _) = await StateAsync(http, ct);
            var (known, missing, stale) = Resolve(snapshot, bulk);
            if (stale is not null) return stale;
            var expected = (bulk["expected"] as JsonObject ?? []).ToDictionary(p => FunctionalGroupStore.UserKey(p.Key), p => (int)p.Value!);
            var result = await store.BulkAssignAsync(groups, known, expected, (string?)bulk["rationale"] ?? "", who!, (string)bulk["operation_id"]!, ct);
            result["rejected"] = new JsonArray([.. missing.Select(m => (JsonNode)new JsonObject { ["username"] = m, ["reason"] = "not_in_dataset", ["detail"] = "Not in the active SAP user dataset." })]);
            if (missing.Count > 0 && (string?)result["status"] == "applied") result["status"] = "partial";
            result["data_revision"] = Revision(snapshot);
            return Json(result);
        });

        fg.MapGet("/rules", async (HttpContext http, FunctionalGroupStore store, bool? counts, CancellationToken ct) =>
        {
            var items = FunctionalGroupStore.ListRules(await store.ReadAsync(ct));
            if (counts == true)
            {
                var (snapshot, directory) = await StateAsync(http, ct);
                var (eligible, notLinked, available) = Audience(snapshot, directory);
                foreach (var rule in items)
                {
                    rule["match_count"] = available ? eligible.Count(r => Applies(rule, r)) : null;
                    rule["not_linked_count"] = available ? notLinked.Count(r => Applies(rule, r)) : null;
                }
            }
            return Json(new JsonObject { ["items"] = new JsonArray([.. items]) });
        });
        fg.MapPost("/rules", async (HttpContext http, FunctionalGroupStore store, CancellationToken ct) =>
        {
            var (rule, invalid) = await RuleBody(http, ct);
            if (invalid is not null) return invalid;
            return Json(await store.AddRuleAsync(rule!.Group, rule.Department, rule.Title, rule.Mode, Actors.Name(http), ct));
        });
        fg.MapPut("/rules/{ruleId}", async (string ruleId, HttpContext http, FunctionalGroupStore store, CancellationToken ct) =>
        {
            var (rule, invalid) = await RuleBody(http, ct);
            if (invalid is not null) return invalid;
            return Json(await store.UpdateRuleAsync(ruleId, rule!.Group, rule.Department, rule.Title, rule.Mode, Actors.Name(http), ct));
        });
        fg.MapDelete("/rules/{ruleId}", async (string ruleId, HttpContext http, FunctionalGroupStore store, CancellationToken ct) =>
        {
            await store.DeleteRuleAsync(ruleId, Actors.Name(http), ct);
            return Json(new JsonObject { ["status"] = "deleted" });
        });

        mapped.MapGet("/rules/{ruleId}/matches", async (string ruleId, HttpContext http, FunctionalGroupStore store, string? search, bool? only_new, int? offset, int? limit, CancellationToken ct) =>
        {
            var (o, l) = (offset ?? 0, limit ?? 50);
            if ((search ?? "").Length > 200 || o < 0 || l is < 1 or > 200) return Detail(422, "Invalid rule match query.");
            var data = await store.ReadAsync(ct);
            var rule = FunctionalGroupStore.ListRules(data).FirstOrDefault(r => (string?)r["id"] == ruleId);
            if (rule is null) return Detail(404, "Rule not found.");
            var (snapshot, directory) = await StateAsync(http, ct);
            var (rows, unlinked) = RuleRows(snapshot, directory, data, rule, search ?? "", only_new ?? false);
            return Json(new JsonObject
            {
                ["rule"] = rule, ["total"] = rows.Count, ["items"] = new JsonArray([.. rows.Skip(o).Take(l)]), ["offset"] = o, ["limit"] = l, ["not_linked_total"] = unlinked.Count,
                ["not_linked"] = new JsonArray([.. unlinked.Take(25).Select(r => (JsonNode)new JsonObject
                {
                    ["full_name"] = r.FullName, ["department"] = r.Department, ["title"] = r.Title, ["reason"] = "No unique SAP user is linked to this Directory identity",
                })]),
                ["data_revision"] = Revision(snapshot),
            });
        });
        mapped.MapGet("/rules/{ruleId}/matches/selection", async (string ruleId, HttpContext http, FunctionalGroupStore store, string? search, bool? only_new, CancellationToken ct) =>
        {
            if ((search ?? "").Length > 200) return Detail(422, "Invalid rule match query.");
            var data = await store.ReadAsync(ct);
            var rule = FunctionalGroupStore.ListRules(data).FirstOrDefault(r => (string?)r["id"] == ruleId);
            if (rule is null) return Detail(404, "Rule not found.");
            var (snapshot, directory) = await StateAsync(http, ct);
            var (rows, _) = RuleRows(snapshot, directory, data, rule, search ?? "", only_new ?? false);
            const int cap = 5000;
            return Json(new JsonObject
            {
                ["total"] = rows.Count, ["usernames"] = new JsonArray([.. rows.Take(cap).Select(r => r["username"]!.DeepClone())]), ["truncated"] = rows.Count > cap, ["limit"] = cap,
                ["data_revision"] = Revision(snapshot),
            });
        });

        mapped.MapGet("/users/{**username}", async (string username, HttpContext http, FunctionalGroupStore store, CancellationToken ct) =>
        {
            var (snapshot, directory) = await StateAsync(http, ct);
            var known = Known(snapshot, username);
            if (known is null) return Detail(404, "SAP user not found.");
            await SyncOrganizationalChangesAsync(http.RequestServices, snapshot, directory, ct);
            var data = await store.ReadAsync(ct);
            var context = DirectoryContext(snapshot, directory, known);
            var current = FunctionalGroupStore.PublicUser(data, known.Username);
            var suggestion = context is not null && (string?)context["match_status"] == "matched"
                ? FunctionalGroupStore.Suggest(data, (string?)context["department"], (string?)context["title"], current["group_ids"]!.AsArray().Select(n => (string)n!)) : null;
            return Json(new JsonObject { ["classification"] = current, ["history"] = FunctionalGroupStore.UserHistory(data, known.Username, 0, 10), ["directory"] = context, ["suggestion"] = suggestion });
        });

        mapped.MapPut("/users/{**username}", async (string username, HttpContext http, FunctionalGroupStore store, CancellationToken ct) =>
        {
            var (body, invalid) = await Body(http, ["group_id", "rationale", "reviewer", "expected_revision", "change_id"], ct);
            if (invalid is not null) return invalid;
            var (fields, errors) = Classification(body!, membership: false);
            if (errors.Count > 0) return Errors(errors);
            var (snapshot, _) = await StateAsync(http, ct);
            var known = Known(snapshot, username);
            if (known is null) return Detail(404, "SAP user not found.");
            var (who, refused) = await Reviewer(http, ct);
            if (refused is not null) return refused;
            if (fields.Group is null && fields.Rationale.Trim().Length == 0) return Detail(422, "A rationale is required to clear a Functional Group.");
            return Json(await store.ClassifyAsync(known.Username, fields.Group, fields.Rationale, fields.Expected, who!, fields.ChangeId, ct));
        });

        mapped.MapPost("/memberships", (HttpContext http, FunctionalGroupStore store, CancellationToken ct) => MembershipAsync(http, store, remove: false, ct));
        mapped.MapPost("/memberships/remove", (HttpContext http, FunctionalGroupStore store, CancellationToken ct) => MembershipAsync(http, store, remove: true, ct));

        mapped.MapGet("/history/{**username}", async (string username, HttpContext http, FunctionalGroupStore store, int? offset, int? limit, CancellationToken ct) =>
        {
            var (o, l) = (offset ?? 0, limit ?? 25);
            if (o < 0 || l is < 1 or > 100) return Detail(422, "Invalid history query.");
            var (snapshot, _) = await StateAsync(http, ct);
            var known = Known(snapshot, username);
            if (known is null) return Detail(404, "SAP user not found.");
            return Json(FunctionalGroupStore.UserHistory(await store.ReadAsync(ct), known.Username, o, l));
        });
    }

    private static async Task<IResult> MembershipAsync(HttpContext http, FunctionalGroupStore store, bool remove, CancellationToken ct)
    {
        var (body, invalid) = await Body(http, ["username", "group_id", "rationale", "reviewer", "expected_revision", "change_id"], ct);
        if (invalid is not null) return invalid;
        var (fields, errors) = Classification(body!, membership: true);
        if (errors.Count > 0) return Errors(errors);
        var (snapshot, _) = await StateAsync(http, ct);
        var known = Known(snapshot, fields.Username!);
        if (known is null) return Detail(404, "SAP user not found.");
        var (who, refused) = await Reviewer(http, ct);
        if (refused is not null) return refused;
        if (remove)
        {
            if (fields.Rationale.Trim().Length == 0) return Detail(422, "A rationale is required to remove a Functional Group.");
            return Json(new JsonObject { ["classification"] = await store.RemoveMembershipAsync(known.Username, fields.Group!, fields.Rationale, fields.Expected, who!, fields.ChangeId, ct) });
        }
        var (classification, outcome) = await store.AddMembershipAsync(known.Username, fields.Group!, fields.Rationale, fields.Expected, who!, fields.ChangeId, ct);
        return Json(new JsonObject { ["classification"] = classification, ["outcome"] = outcome });
    }

    // --- shared helpers --------------------------------------------------------------------------------------------------------

    private static IResult Json(JsonNode value) => Results.Content(value.ToJsonString(), "application/json");
    private static IResult Detail(int status, object detail) => Results.Json(new { detail }, statusCode: status);
    private static IResult Errors(List<object> errors) => Results.Json(new { detail = errors }, statusCode: 422);
    private static string Fold(string text) => AuthLens.Domain.Text.PythonText.Casefold(text);

    private static async Task<(JsonObject? Body, IResult? Invalid)> Body(HttpContext http, string[] fields, CancellationToken ct)
    {
        var (body, invalid) = await V1Validation.ReadBody(http, ct);
        if (invalid is not null) return (null, invalid);
        var errors = new List<object>();
        V1Validation.Extra(body!, fields, errors);
        return errors.Count > 0 ? (null, Errors(errors)) : (body, null);
    }

    /// <summary>Who records a confirmation: the signed-in account, or the local Desktop user with the name from the reviewer profile. Never a shared token.</summary>
    private static async Task<(string? Reviewer, IResult? Refused)> Reviewer(HttpContext http, CancellationToken ct)
    {
        var actor = Actors.Current(http);
        if (actor.Provenance is not ("server-session" or "desktop"))
            return (null, Detail(403, "Functional Group classifications need an individual sign-in. Enable Accounts mode for this server; a shared access token is not a reviewer identity."));
        var who = actor.Provenance == "server-session" ? actor.Username : (string)(await V1Configuration.EnsureProfileAsync(http.RequestServices.GetRequiredService<AuthLens.Persistence.WriteCoordinator>(), http.RequestServices.GetRequiredService<TimeProvider>(), null, null, ct))["identity"]!["display_name"]!;
        return who.Length == 0 ? (null, Detail(422, "A reviewer is required.")) : (who, null);
    }

    private sealed record ClassificationFields(string? Username, string? Group, string Rationale, string Reviewer, int Expected, string ChangeId);

    /// <summary>The Classification and Membership models (group id pattern, text lengths, expected_revision >= 0).</summary>
    private static (ClassificationFields Fields, List<object> Errors) Classification(JsonObject body, bool membership)
    {
        var errors = new List<object>();
        var username = membership ? V1Validation.Text(body, "username", 1, 200, true, errors) : null;
        var group = body["group_id"] is null ? null : V1Validation.Text(body, "group_id", 0, 64, membership, errors);
        if (membership && body["group_id"] is null && !errors.Any()) errors.Add(V1Validation.Error("missing", "group_id", "Field required"));
        if (group is not null && !FunctionalGroupStore.GroupId().IsMatch(group)) errors.Add(V1Validation.Error("string_pattern_mismatch", "group_id", "String should match pattern '^fg_[a-f0-9]{12}$'"));
        var rationale = V1Validation.Text(body, "rationale", 0, 2000, false, errors) ?? "";
        var reviewer = V1Validation.Text(body, "reviewer", 0, 120, false, errors) ?? "";
        var changeId = V1Validation.Text(body, "change_id", 0, 64, false, errors) ?? "";
        var expected = 0;
        if (body["expected_revision"] is not JsonValue ev || ev.GetValueKind() != JsonValueKind.Number || !ev.TryGetValue(out expected))
            errors.Add(V1Validation.Error(body["expected_revision"] is null ? "missing" : "int_type", "expected_revision", body["expected_revision"] is null ? "Field required" : "Input should be a valid integer"));
        else if (expected < 0) errors.Add(V1Validation.Error("greater_than_equal", "expected_revision", "Input should be greater than or equal to 0"));
        return (new ClassificationFields(username, group, rationale, reviewer, expected, changeId), errors);
    }

    private sealed record Rule(string Group, string Department, string Title, string Mode);

    private static async Task<(Rule? Rule, IResult? Invalid)> RuleBody(HttpContext http, CancellationToken ct)
    {
        var (body, invalid) = await Body(http, ["group_id", "department", "title_contains", "department_mode"], ct);
        if (invalid is not null) return (null, invalid);
        var errors = new List<object>();
        var group = V1Validation.Text(body!, "group_id", 0, 64, true, errors);
        if (group is not null && !FunctionalGroupStore.GroupId().IsMatch(group)) errors.Add(V1Validation.Error("string_pattern_mismatch", "group_id", "String should match pattern '^fg_[a-f0-9]{12}$'"));
        var department = V1Validation.Text(body!, "department", 0, 200, false, errors) ?? "";
        var title = V1Validation.Text(body!, "title_contains", 0, 200, false, errors) ?? "";
        var mode = V1Validation.Text(body!, "department_mode", 0, 20, false, errors) is { Length: > 0 } given ? given : "contains";
        if (mode is not ("contains" or "equals")) errors.Add(V1Validation.Error("string_pattern_mismatch", "department_mode", "String should match pattern '^(contains|equals)$'"));
        return errors.Count > 0 ? (null, Errors(errors)) : (new Rule(group!, department, title, mode), null);
    }

    private static async Task<(JsonObject? Body, IResult? Invalid)> BulkBody(HttpContext http, bool assign, CancellationToken ct)
    {
        string[] fields = assign ? ["group_ids", "group_id", "usernames", "data_revision", "operation_id", "expected", "replace_existing", "rationale", "reviewer"] : ["group_ids", "group_id", "usernames", "data_revision"];
        var (body, invalid) = await Body(http, fields, ct);
        if (invalid is not null) return (null, invalid);
        var errors = new List<object>();
        if (body!["group_ids"] is not null and not JsonArray { Count: <= 50 } || body["group_ids"] is JsonArray ids && ids.Any(i => i is not JsonValue v || v.GetValueKind() != JsonValueKind.String))
            errors.Add(V1Validation.Error("list_type", "group_ids", "Input should be a valid list of at most 50 strings"));
        V1Validation.Text(body, "group_id", 0, 64, false, errors);
        if (body["usernames"] is not JsonArray { Count: >= 1 and <= 5000 } names || names.Any(n => n is not JsonValue v || v.GetValueKind() != JsonValueKind.String))
            errors.Add(V1Validation.Error("too_short", "usernames", "List should have between 1 and 5000 user names"));
        V1Validation.Text(body, "data_revision", 0, 64, false, errors);
        if (assign)
        {
            V1Validation.Text(body, "operation_id", 8, 64, true, errors);
            V1Validation.Text(body, "rationale", 0, 1000, false, errors);
            V1Validation.Text(body, "reviewer", 0, 200, false, errors);
            if (body["expected"] is not null and not JsonObject || body["expected"] is JsonObject e && e.Any(p => p.Value is not JsonValue v || !v.TryGetValue<int>(out _)))
                errors.Add(V1Validation.Error("dict_type", "expected", "Input should be a valid dictionary of revisions"));
            if (body["replace_existing"] is not null and not JsonValue || body["replace_existing"] is JsonValue r && r.GetValueKind() is not (JsonValueKind.True or JsonValueKind.False))
                errors.Add(V1Validation.Error("bool_type", "replace_existing", "Input should be a valid boolean"));
        }
        return errors.Count > 0 ? (null, Errors(errors)) : (body, null);
    }

    private static List<string> Targets(JsonObject body)
    {
        var ids = (body["group_ids"] as JsonArray ?? []).Select(n => (string)n!).ToList();
        if ((string?)body["group_id"] is { Length: > 0 } single) ids.Add(single);
        ids = ids.Distinct().ToList();
        return ids.Count > 0 ? ids : throw new V1Problem(422, "Select at least one Functional Group.");
    }

    public static string Revision(Snapshot snapshot) =>
        $"{V1Compatibility.Boot}.{(snapshot.Ids.Roles ?? 0) + (snapshot.Ids.Users ?? 0) + (snapshot.Ids.Sod ?? 0)}.{snapshot.Ids.Employees ?? 0}";

    /// <summary>resolve_bulk: refuses a selection made on another publication; returns the canonical names found and the names not in the dataset.</summary>
    private static (List<string> Known, List<string> Missing, IResult? Stale) Resolve(Snapshot snapshot, JsonObject body)
    {
        if ((string?)body["data_revision"] is { Length: > 0 } seen && !seen.Split('.').Take(2).SequenceEqual(Revision(snapshot).Split('.').Take(2)))
            return ([], [], Detail(409, new JsonObject { ["code"] = "stale_dataset", ["message"] = "The user data changed after this selection was made. Select the users again." }));
        var users = snapshot.Users.Users;
        var known = new List<string>();
        var missing = new List<string>();
        var keys = new HashSet<string>();
        foreach (var name in body["usernames"]!.AsArray().Select(n => (string)n!))
        {
            var key = RoleNames.NormalizeUsername(name);
            if (key.Length == 0 || !keys.Add(key)) continue;
            if (users.TryGetValue(key, out var user)) known.Add(user.Username); else missing.Add(name.Trim());
        }
        return (known, missing, null);
    }

    private static async Task<(Snapshot Snapshot, EmployeeDirectory? Directory)> StateAsync(HttpContext http, CancellationToken ct)
    {
        var snapshot = await http.RequestServices.GetRequiredService<SnapshotService>().GetAsync(ct);
        var settings = await http.RequestServices.GetRequiredService<V1Settings>().GetAsync(ct);
        return (snapshot, V1Employees.Available(snapshot, settings));
    }

    private static SapUser? Known(Snapshot snapshot, string username) =>
        snapshot.Users.Users.Values.FirstOrDefault(u => u.Username.Trim().PyUpper() == username.Trim().PyUpper());

    /// <summary>sync_organizational_changes: applies stored Directory change events to classified users. Never fails a read.</summary>
    public static async Task SyncOrganizationalChangesAsync(IServiceProvider services, Snapshot snapshot, EmployeeDirectory? directory, CancellationToken ct)
    {
        try
        {
            var store = services.GetRequiredService<FunctionalGroupStore>();
            var data = await store.ReadAsync(ct);
            if (directory is null || data["users"]!.AsObject().Count == 0) return;
            var changes = await services.GetRequiredService<PositionChangeStore>().ReadAsync(ct);
            if (changes["events"]!.AsArray().Count == 0 && changes["manager_events"]!.AsArray().Count == 0) return;
            var owners = EmployeeDirectory.SapEmailOwners(snapshot.Users.Users.Values);
            var classified = data["users"]!.AsObject().Select(p => ((string)p.Value!["username"]!).Trim().PyUpper()).ToHashSet();
            var emails = new Dictionary<string, string>();
            foreach (var user in snapshot.Users.Users.Values)
                if (classified.Contains(user.Username.Trim().PyUpper()) && directory.MatchSapIdentity(user, owners) is ("matched", { } employee) && (string?)employee["email"] is { Length: > 0 } mail)
                    emails[user.Username.Trim().PyUpper()] = PositionChanges.NormalizeText(mail);
            await store.ApplyOrganizationalChangesAsync(emails, changes["events"]!.AsArray().OfType<JsonObject>(), changes["manager_events"]!.AsArray().OfType<JsonObject>(), ct);
        }
        catch (Exception error) when (error is not OperationCanceledException)
        {
            services.GetService<ILoggerFactory>()?.CreateLogger("AuthLens.FunctionalGroups").LogWarning("Functional Group review synchronisation failed ({Type}); classifications are unchanged.", error.GetType().Name);
        }
    }

    /// <summary>directory_context: Department, Job Title and Manager only for an unambiguous Directory match.</summary>
    private static JsonObject? DirectoryContext(Snapshot snapshot, EmployeeDirectory? directory, SapUser user)
    {
        if (directory is null) return null;
        var (status, employee) = directory.MatchSapIdentity(user, EmployeeDirectory.SapEmailOwners(snapshot.Users.Users.Values));
        if (status != "matched" || employee is null) return new JsonObject { ["match_status"] = status };
        var manager = (Dictionary<string, object?>)employee["manager"]!;
        return new JsonObject
        {
            ["match_status"] = "matched", ["department"] = (string?)employee["department"], ["title"] = (string?)employee["title"], ["site"] = (string?)employee["site"],
            ["manager"] = (string?)manager["name"], ["manager_email"] = (string?)manager["email"],
        };
    }

    // --- organization.py ---------------------------------------------------------------------------------------------------------

    public static string ManagerKey(Dictionary<string, object?>? employee) =>
        employee?["manager"] is Dictionary<string, object?> manager && EmployeeDirectory.Normalized((string?)manager["email"] ?? "") is { Length: > 0 } key ? key : "none";

    /// <summary>group_keys: the id of every group the user belongs to, or "unassigned".</summary>
    public static IReadOnlyList<string> GroupKeys(IReadOnlyDictionary<string, JsonObject> classes, string username) =>
        classes.TryGetValue(username.Trim().PyUpper(), out var record) && record["group_ids"]!.AsArray().Count > 0
            ? record["group_ids"]!.AsArray().Select(n => (string)n!).ToList() : ["unassigned"];

    /// <summary>organization.options: Functional Group and manager choices with SAP user counts.</summary>
    public static JsonObject Options(Snapshot snapshot, EmployeeDirectory? directory, JsonObject data)
    {
        var classes = FunctionalGroupStore.ClassificationMap(data);
        var counts = new Dictionary<string, int>();
        foreach (var user in snapshot.Users.Users.Values)
            foreach (var key in GroupKeys(classes, user.Username)) counts[key] = counts.GetValueOrDefault(key) + 1;
        var managers = new Dictionary<string, int>();
        var labels = new Dictionary<string, string>();
        if (directory is not null)
        {
            var owners = EmployeeDirectory.SapEmailOwners(snapshot.Users.Users.Values);
            foreach (var user in snapshot.Users.Users.Values)
            {
                var (status, employee) = directory.MatchSapIdentity(user, owners);
                var key = status == "matched" ? ManagerKey(employee) : "none";
                managers[key] = managers.GetValueOrDefault(key) + 1;
                if (key != "none")
                {
                    var manager = (Dictionary<string, object?>)employee!["manager"]!;
                    labels[key] = (string?)manager["name"] is { Length: > 0 } name ? name : (string?)manager["email"] ?? "";
                }
            }
        }
        var groupOptions = new JsonArray(new JsonObject { ["value"] = "unassigned", ["label"] = "Unassigned", ["count"] = counts.GetValueOrDefault("unassigned") });
        foreach (var group in FunctionalGroupStore.ListGroups(data))
        {
            var gid = (string)group["id"]!;
            if ((string?)group["status"] != "active" && counts.GetValueOrDefault(gid) == 0) continue;
            groupOptions.Add(new JsonObject { ["value"] = gid, ["label"] = (string)group["name"]! + ((string?)group["status"] == "archived" ? " (archived)" : ""), ["count"] = counts.GetValueOrDefault(gid) });
        }
        var managerOptions = managers.Select(p => new { Value = p.Key, Label = labels.GetValueOrDefault(p.Key, "No manager"), Count = p.Value })
            .OrderBy(o => o.Value == "none").ThenBy(o => Fold(o.Label), StringComparer.Ordinal).ThenBy(o => o.Value, StringComparer.Ordinal)
            .Select(o => (JsonNode)new JsonObject { ["value"] = o.Value, ["label"] = o.Label, ["count"] = o.Count });
        return new JsonObject { ["functional_groups"] = groupOptions, ["managers"] = new JsonArray([.. managerOptions]) };
    }

    /// <summary>organization.selection: a user predicate for the functional_groups and managers filters (OR within, AND between), or null when inactive.</summary>
    public static Func<SapUser, bool>? Selection(Snapshot snapshot, EmployeeDirectory? directory, JsonObject data, IReadOnlyCollection<string> groups, IReadOnlyCollection<string> managers)
    {
        if (groups.Count == 0 && managers.Count == 0) return null;
        var wantedGroups = groups.ToHashSet();
        var wantedManagers = managers.Select(EmployeeDirectory.Normalized).ToHashSet();
        var classes = wantedGroups.Count > 0 ? FunctionalGroupStore.ClassificationMap(data) : new Dictionary<string, JsonObject>();
        var owners = wantedManagers.Count > 0 && directory is not null ? EmployeeDirectory.SapEmailOwners(snapshot.Users.Users.Values) : null;
        return user =>
        {
            if (wantedGroups.Count > 0 && !GroupKeys(classes, user.Username).Any(wantedGroups.Contains)) return false;
            if (wantedManagers.Count > 0)
            {
                var key = "none";
                if (directory is not null && directory.MatchSapIdentity(user, owners!) is ("matched", var employee)) key = ManagerKey(employee);
                if (!wantedManagers.Contains(key)) return false;
            }
            return true;
        };
    }

    // --- rule audience (directory identities with a unique SAP link) ---------------------------------------------------------------

    private sealed record Person(string Username, string FullName, string Department, string Title, string Dn, string Tn);

    private static (List<Person> Eligible, List<Person> NotLinked, bool Available) Audience(Snapshot snapshot, EmployeeDirectory? directory)
    {
        if (directory is null) return ([], [], false);
        var owners = EmployeeDirectory.SapEmailOwners(snapshot.Users.Users.Values);
        var linked = new HashSet<string>();
        var eligible = new List<Person>();
        foreach (var user in snapshot.Users.Users.Values)
        {
            if (directory.MatchSapIdentity(user, owners) is not ("matched", { } employee)) continue;
            linked.Add((string)employee["id"]!);
            var names = user.Names.Select(n => string.Join(' ', new[] { n.First, n.Last }.Where(p => p.Length > 0)).Trim());
            var department = (string?)employee["department"] ?? "";
            var title = (string?)employee["title"] ?? "";
            eligible.Add(new Person(user.Username, (string?)employee["name"] is { Length: > 0 } n ? n : names.FirstOrDefault(x => x.Length > 0) ?? "", department, title,
                FunctionalGroupStore.NormalizeText(department), FunctionalGroupStore.NormalizeText(title)));
        }
        var notLinked = directory.Rows.Select((row, i) => (row, i)).Where(p => !linked.Contains(p.i.ToString(System.Globalization.CultureInfo.InvariantCulture)))
            .Select(p => new Person("", p.row["Name"], p.row["Department"], p.row["Title"], FunctionalGroupStore.NormalizeText(p.row["Department"]), FunctionalGroupStore.NormalizeText(p.row["Title"]))).ToList();
        return (eligible, notLinked, true);
    }

    private static bool Applies(JsonObject rule, Person row)
    {
        var department = FunctionalGroupStore.NormalizeText((string?)rule["department"]);
        var title = FunctionalGroupStore.NormalizeText((string?)rule["title_contains"]);
        if (department.Length > 0)
        {
            var equals = ((string?)rule["department_mode"] is { Length: > 0 } m ? m : "equals") == "equals";
            if (row.Dn.Length == 0 || (equals ? department != row.Dn : !row.Dn.Contains(department, StringComparison.Ordinal))) return false;
        }
        if (title.Length > 0 && !row.Tn.Contains(title, StringComparison.Ordinal)) return false;
        return department.Length > 0 || title.Length > 0;
    }

    private static (List<JsonObject> Rows, List<Person> Unlinked) RuleRows(Snapshot snapshot, EmployeeDirectory? directory, JsonObject data, JsonObject rule, string search, bool onlyNew)
    {
        var (eligible, notLinked, available) = Audience(snapshot, directory);
        if (!available) throw new V1Problem(409, "The Employee Directory is not available. Import it in Data Sources to preview matching users.");
        var classes = FunctionalGroupStore.ClassificationMap(data);
        var needle = Fold(search.Trim());
        var rows = new List<JsonObject>();
        foreach (var row in eligible)
        {
            if (!Applies(rule, row)) continue;
            var groups = classes.TryGetValue(row.Username.Trim().PyUpper(), out var record) ? record["memberships"]!.AsArray().Select(m => m!["group"]!.DeepClone()).ToList() : [];
            var member = groups.Any(g => (string?)g!["id"] == (string?)rule["group_id"]);
            if (onlyNew && member) continue;
            if (needle.Length > 0 && !Fold(string.Join(' ', row.Username, row.FullName, row.Department, row.Title)).Contains(needle, StringComparison.Ordinal)) continue;
            rows.Add(new JsonObject
            {
                ["username"] = row.Username, ["full_name"] = row.FullName, ["department"] = row.Department, ["title"] = row.Title, ["groups"] = new JsonArray([.. groups]), ["already_member"] = member,
            });
        }
        return (rows.OrderBy(r => Fold((string)r["username"]!), StringComparer.Ordinal).ToList(), notLinked.Where(r => Applies(rule, r)).ToList());
    }

    // --- functional_group_analysis.py ----------------------------------------------------------------------------------------------

    private const double CommonAt = 0.6, UncommonAt = 0.25;
    private const int MinMembers = 3;

    private static Dictionary<string, string> ActiveRoles(SapUser user, DateOnly today)
    {
        var roles = new Dictionary<string, string>(StringComparer.Ordinal);
        foreach (var assignment in user.Assignments)
            if (SapDates.IntervalStatus(assignment.ValidFrom, assignment.ValidTo, today) == "active")
                roles.TryAdd(string.Concat(assignment.RoleName.Where(c => !char.IsWhiteSpace(c))).PyUpper(), assignment.RoleName);
        return roles;
    }

    public static JsonObject Analyse(UserDirectory users, IReadOnlyList<string> members, JsonObject group, DateOnly today)
    {
        var byName = users.Users.Values.ToDictionary(u => u.Username.Trim().PyUpper(), u => u);
        var eligible = new Dictionary<string, Dictionary<string, string>>();
        foreach (var name in members.OrderBy(Fold, StringComparer.Ordinal))
            if (byName.TryGetValue(name.Trim().PyUpper(), out var user)) eligible[user.Username] = ActiveRoles(user, today);
        var missing = members.Where(n => !byName.ContainsKey(n.Trim().PyUpper())).Order(StringComparer.Ordinal).ToList();
        var limitations = new JsonArray();
        if (missing.Count > 0) limitations.Add($"{missing.Count} classified member(s) are not in the SAP user import and were not compared.");
        if (eligible.Count < MinMembers) limitations.Add($"Only {eligible.Count} comparable member(s): at least {MinMembers} are needed before common and uncommon roles mean anything.");
        var total = eligible.Count;
        var holders = new Dictionary<string, List<string>>();
        var labels = new Dictionary<string, string>();
        foreach (var (username, roles) in eligible)
            foreach (var (role, label) in roles)
            {
                if (!holders.TryGetValue(role, out var list)) holders[role] = list = [];
                list.Add(username);
                labels.TryAdd(role, label);
            }
        var comparable = total >= MinMembers;
        var rows = new List<(string Role, JsonObject Row, string Kind)>();
        foreach (var role in holders.Keys.OrderBy(r => -holders[r].Count).ThenBy(r => Fold(labels[r]), StringComparer.Ordinal))
        {
            var frequency = holders[role].Count / (double)total;
            var kind = !comparable ? "not compared" : frequency >= CommonAt ? "common" : frequency <= UncommonAt ? "uncommon" : "shared";
            rows.Add((role, new JsonObject
            {
                ["role"] = labels[role], ["users"] = holders[role].Count, ["eligible"] = total, ["frequency"] = Math.Round(frequency, 4, MidpointRounding.ToEven), ["kind"] = kind,
                ["holders"] = new JsonArray([.. holders[role].OrderBy(Fold, StringComparer.Ordinal).Select(h => (JsonNode)h)]),
            }, kind));
        }
        var kinds = rows.ToDictionary(r => r.Role, r => r.Kind);
        var compared = new JsonArray();
        foreach (var username in eligible.Keys.OrderBy(Fold, StringComparer.Ordinal))
        {
            var record = byName[username.Trim().PyUpper()];
            var names = record.Names.FirstOrDefault(n => n.First.Length > 0 || n.Last.Length > 0);
            var statuses = record.Accounts.Select(a => SapDates.IntervalStatus(a.ValidFrom, a.ValidTo, today)).Distinct().Order(StringComparer.Ordinal);
            compared.Add(new JsonObject
            {
                ["username"] = username, ["full_name"] = string.Join(' ', new[] { names.First ?? "", names.Last ?? "" }.Where(p => p.Length > 0)).Trim(),
                ["account_status"] = string.Join('/', statuses), ["roles"] = eligible[username].Count,
            });
        }
        var people = eligible.Select(p =>
        {
            var extra = p.Value.Keys.Where(r => comparable && kinds[r] == "uncommon").Select(r => labels[r]).OrderBy(Fold, StringComparer.Ordinal).ToList();
            var lacking = holders.Keys.Where(r => comparable && kinds[r] == "common" && !p.Value.ContainsKey(r)).Select(r => labels[r]).OrderBy(Fold, StringComparer.Ordinal).ToList();
            return (Username: p.Key, Roles: p.Value.Count, Extra: extra, Lacking: lacking);
        }).OrderBy(u => -(u.Extra.Count + u.Lacking.Count)).ThenBy(u => Fold(u.Username), StringComparer.Ordinal).ToList();
        return new JsonObject
        {
            ["group"] = new JsonObject { ["id"] = group["id"]!.DeepClone(), ["name"] = group["name"]!.DeepClone(), ["status"] = group["status"]!.DeepClone() },
            ["members"] = members.Count, ["eligible"] = total, ["not_in_import"] = new JsonArray([.. missing.Select(m => (JsonNode)m)]),
            ["distinct_roles"] = rows.Count, ["common_roles"] = rows.Count(r => r.Kind == "common"), ["deviations"] = people.Count(u => u.Extra.Count + u.Lacking.Count > 0),
            ["roles"] = new JsonArray([.. rows.Select(r => (JsonNode)r.Row)]),
            ["users"] = new JsonArray([.. people.Select(u => (JsonNode)new JsonObject
            {
                ["username"] = u.Username, ["roles"] = u.Roles, ["additional_roles"] = new JsonArray([.. u.Extra.Select(e => (JsonNode)e)]),
                ["missing_common_roles"] = new JsonArray([.. u.Lacking.Select(e => (JsonNode)e)]),
            })]),
            ["compared"] = compared, ["limitations"] = limitations, ["comparable"] = comparable,
            ["method"] = new JsonObject
            {
                ["common_at"] = CommonAt, ["uncommon_at"] = UncommonAt, ["min_members"] = MinMembers,
                ["note"] = "Advisory only. Roles are unique active user and role pairs; a deviation is a prompt to investigate, not a finding.",
            },
        };
    }
}
