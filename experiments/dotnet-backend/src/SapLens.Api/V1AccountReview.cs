using System.Globalization;
using System.Text.Json;
using System.Text.Json.Nodes;
using Microsoft.EntityFrameworkCore;
using SapLens.Application;
using SapLens.Application.Accounts;
using SapLens.Domain.Directory;
using SapLens.Domain.Json;
using SapLens.Domain.Roles;
using SapLens.Domain.Text;
using SapLens.Domain.Users;
using SapLens.Persistence;

namespace SapLens.Api;

/// <summary>Port of account_review.py and routers/account_review.py: evidence-based review of SAP accounts. Decisions are annotations, never SAP
/// account actions. They are appended to the hash-chained review store (subject type <c>account</c>) and never rewritten: the latest decision is
/// the current one, earlier ones are its history. A decision is Outdated when the account's evidence changed or the account disappeared from a later
/// User Access revision (recorded as an invalidation), so a reappearing account needs a new review. Not yet migrated (reported, never guessed):
/// position and manager change events between directory imports, and functional-group classifications (every account reads Unassigned).</summary>
public static class V1AccountReview
{
    public static readonly string[] States = ReviewService.AccountStates;
    public static readonly Dictionary<string, string> Findings = new()
    {
        ["ad_disabled_open"] = "AD disabled / SAP valid and unlocked", ["ad_disabled_locked"] = "AD disabled / SAP locked", ["directory_match"] = "Missing or ambiguous directory match",
        ["expired"] = "Expired SAP account", ["technical"] = "Technical or service account",
    };
    private static readonly HashSet<string> FilterNames = [.. Findings.Keys, "any", "stale", "matched", "reviewed", "pending", "position_change", "manager_change", "functional_group_review", "directory_missing", "directory_ambiguous"];
    private static readonly string[] Sorts = ["username", "name", "sap_validity", "lock_status", "ad_status", "review_state", "priority"];

    private static IResult Detail(int status, string detail) => Results.Json(new { detail }, statusCode: status);
    private static IResult Json(object? value) => Results.Content(JsonSerializer.Serialize(value), "application/json");
    public static string Stamp(DateTime utc) => DateTime.SpecifyKind(utc, DateTimeKind.Utc).ToString("yyyy-MM-dd'T'HH:mm:ss.ffffff'+00:00'", CultureInfo.InvariantCulture);

    public static string Validity(IEnumerable<Account> accounts, DateOnly today)
    {
        var statuses = accounts.Select(a => SapDates.IntervalStatus(a.ValidFrom, a.ValidTo, today)).ToHashSet();
        return statuses.SetEquals(["active"]) ? "Valid" : statuses.Count > 0 && statuses.IsSubsetOf(["expired", "future"]) ? "Invalid" : "Unknown";
    }

    public sealed record Stored(ReviewDecision Latest, List<ReviewDecision> History, bool Invalidated);

    private static Dictionary<string, object?> DecisionView(ReviewDecision d)
    {
        var view = new Dictionary<string, object?> { ["state"] = d.Decision, ["reviewer"] = d.Reviewer, ["rationale"] = d.Comment, ["evidence_version"] = d.EvidenceVersion, ["timestamp"] = Stamp(d.DecidedUtc) };
        if (d.DetailsJson is not null && JsonNode.Parse(d.DetailsJson) is JsonObject details)
            foreach (var (key, value) in details) view[key] = value?.DeepClone();
        return view;
    }

    /// <summary>v1 rows(): one row per SAP user with its findings, evidence version, current decision and workflow status.</summary>
    public static List<Dictionary<string, object?>> Rows(Snapshot state, EmployeeDirectory? directory, IReadOnlyDictionary<string, Stored> saved, IReadOnlyList<string> groups, DateOnly today,
        IReadOnlyDictionary<string, System.Text.Json.Nodes.JsonObject>? classifications = null)
    {
        var configured = groups.Select(g => g.Trim().ToUpperInvariant().ToLowerInvariant()).ToHashSet(StringComparer.Ordinal);
        var owners = directory is null ? null : EmployeeDirectory.SapEmailOwners(state.Users.Users.Values);
        var sortedGroups = groups.Select(g => g.Trim().ToUpperInvariant().ToLowerInvariant()).Order(StringComparer.Ordinal).ToList();
        var result = new List<Dictionary<string, object?>>();
        foreach (var key in state.Users.UserOrder)
        {
            var user = state.Users.Users[key];
            var (matchStatus, employee) = directory is null ? ("directory_unavailable", null) : directory.MatchSapIdentity(user, owners!);
            var ad = employee is null ? "Unknown" : (string)employee["account_status"]!;
            var valid = Validity(user.Accounts, today);
            var locks = user.Accounts.Select(a => a.Locked).ToHashSet();
            var locked = locks.SetEquals([true]) ? "Locked" : locks.SetEquals([false]) ? "Unlocked" : "Unknown";
            var findings = new List<string>();
            if (ad == "Disabled" && valid == "Valid" && locked == "Unlocked") findings.Add("ad_disabled_open");
            if (ad == "Disabled" && locked == "Locked") findings.Add("ad_disabled_locked");
            if (directory is not null && matchStatus != "matched") findings.Add("directory_match");
            if (user.Accounts.Any(a => SapDates.IntervalStatus(a.ValidFrom, a.ValidTo, today) == "expired")) findings.Add("expired");
            if (user.Accounts.Any(a => a.UserType.Trim().ToUpperInvariant() is "B" or "C" or "S" or "L")) findings.Add("technical");
            var unlicensed = user.Groups.Any(g => configured.Contains(g.Trim().ToUpperInvariant().ToLowerInvariant()));
            var identity = CanonicalJson.Sha256(new object[]
            {
                user.Username.Trim().ToUpperInvariant(), user.Emails.Select(EmployeeDirectory.Normalized).Distinct().Order(StringComparer.Ordinal).ToList(),
                user.Names.Select(n => new[] { n.First, n.Last }).OrderBy(n => n[0], StringComparer.Ordinal).ThenBy(n => n[1], StringComparer.Ordinal).ToList(),
            });
            // Canonical evidence: CSV row order and unrelated directory fields do not change the version.
            var accounts = user.Accounts.Select(a => CanonicalJson.Serialize(new Dictionary<string, object?> { ["valid_from"] = a.ValidFrom, ["valid_to"] = a.ValidTo, ["locked"] = a.Locked, ["user_type"] = a.UserType, ["user_group"] = a.UserGroup }))
                .Order(StringComparer.Ordinal).ToList();
            var assignments = user.Assignments.Select(a => CanonicalJson.Serialize(new Dictionary<string, object?>
            {
                ["role_name"] = a.RoleName, ["user_group"] = a.UserGroup, ["valid_from"] = a.ValidFrom, ["valid_to"] = a.ValidTo, ["scope"] = a.Scope, ["match_status"] = a.MatchStatus,
                ["catalogue_roles"] = a.CatalogueRoles, ["tcodes"] = a.Tcodes,
            })).Order(StringComparer.Ordinal).ToList();
            var version = CanonicalJson.Sha256(new object?[]
            {
                identity, accounts, assignments, user.Groups.Order(StringComparer.Ordinal).ToList(),
                employee is null ? null : new Dictionary<string, object?> { ["email"] = employee["email"], ["username"] = employee["username"], ["account_status"] = employee["account_status"] },
                matchStatus, sortedGroups, valid, findings,
            });
            var stored = saved.GetValueOrDefault(Sources.AccountKey(user.Username));
            var stale = stored is not null && (stored.Invalidated || stored.Latest.EvidenceVersion != version);
            var decision = stored is null ? null : DecisionView(stored.Latest);
            // MIG-004: a Functional Group membership that needs review (Directory Department or Job Title changed) is a review signal.
            System.Text.Json.Nodes.JsonObject? classified = null;
            classifications?.TryGetValue(user.Username.Trim().ToUpperInvariant(), out classified);
            var classificationReview = (string?)classified?["status"] == "Needs review";
            var needs = findings.Count > 0 || stale || classificationReview;
            var completed = decision is not null && (string)decision["state"]! == "No action required" && !stale && !classificationReview;
            var manager = employee?["manager"] as Dictionary<string, object?>;
            result.Add(new()
            {
                ["username"] = user.Username, ["name"] = string.Join(" / ", user.Names.Where(n => n.First.Length > 0 || n.Last.Length > 0).Select(n => $"{n.First} {n.Last}".Trim())),
                ["groups"] = user.Groups, ["sap_validity"] = valid, ["lock_status"] = locked, ["ad_status"] = ad, ["match_status"] = matchStatus, ["findings"] = findings, ["unlicensed"] = unlicensed,
                ["evidence_version"] = version, ["identity_version"] = identity,
                ["evidence"] = new Dictionary<string, object?>
                {
                    ["accounts"] = user.Accounts.Take(25).Select(a => new Dictionary<string, object?> { ["valid_from"] = a.ValidFrom, ["valid_to"] = a.ValidTo, ["locked"] = a.Locked, ["user_type"] = a.UserType, ["user_group"] = a.UserGroup }).ToList(),
                    ["account_total"] = user.Accounts.Count, ["assignment_records"] = user.Assignments.Count, ["sap_emails"] = user.Emails.Take(5).ToList(), ["directory_email"] = employee?["email"],
                },
                ["decision"] = decision, ["history_count"] = stored?.History.Count ?? 0, ["stale"] = stale,
                ["review_state"] = decision is null || stale ? "Needs review" : decision["state"], ["needs_review"] = needs, ["workflow_status"] = completed ? "completed" : "open",
                ["position_change"] = null,
                ["manager"] = manager is null ? null : new Dictionary<string, object?> { ["name"] = manager["name"], ["email"] = manager["email"], ["status"] = manager["status"] },
                ["manager_change"] = null, ["functional_group"] = classified?["group"]?.DeepClone(),
                ["functional_groups"] = classified is null ? new System.Text.Json.Nodes.JsonArray() : new System.Text.Json.Nodes.JsonArray([.. classified["memberships"]!.AsArray().Select(m => m!["group"]!.DeepClone())]),
                ["classification"] = classified is null
                    ? new Dictionary<string, object?> { ["status"] = "Unassigned", ["revision"] = 0, ["review"] = null, ["confirmed_at"] = null }
                    : new Dictionary<string, object?> { ["status"] = (string?)classified["status"], ["revision"] = (int)classified["revision"]!, ["review"] = classified["review"]?.DeepClone(), ["confirmed_at"] = (string?)classified["confirmed_at"] },
                ["classification_review"] = classificationReview, ["priority"] = needs ? "Normal" : "None", ["priority_order"] = needs ? 1 : 2,
            });
        }
        return result;
    }

    private static async Task<Dictionary<string, Stored>> LoadAsync(SapLensDb db, CancellationToken ct)
    {
        var decisions = await db.ReviewDecisions.AsNoTracking().Where(d => d.SubjectType == "account").OrderBy(d => d.Id).ToListAsync(ct);
        var invalidations = await db.ReviewInvalidations.AsNoTracking().Where(i => i.AssignmentKey.StartsWith("\u001eaccount\u001f")).GroupBy(i => i.AssignmentKey)
            .Select(g => new { Key = g.Key, Dataset = g.Max(i => i.DatasetId) }).ToDictionaryAsync(g => g.Key, g => g.Dataset, ct);
        return decisions.GroupBy(d => d.SubjectKey).ToDictionary(g => g.Key, g =>
        {
            var latest = g.Last();
            return new Stored(latest, g.Take(g.Count() - 1).ToList(), invalidations.TryGetValue(g.Key, out var dataset) && dataset > latest.DatasetId);
        });
    }

    /// <summary>v1 filters Account Review by the sole membership's group (`functional_group`), else "unassigned".</summary>
    private static string FunctionalGroupId(Dictionary<string, object?> row) => (string?)(row["functional_group"] as System.Text.Json.Nodes.JsonNode)?["id"] ?? "unassigned";

    private static string ManagerKey(Dictionary<string, object?> row) =>
        row["manager"] is Dictionary<string, object?> m && EmployeeDirectory.Normalized((string?)m["email"]) is { Length: > 0 } email ? email : "none";

    internal static bool Has(Dictionary<string, object?> r, string name)
    {
        var decision = r["decision"] is not null;
        var stale = (bool)r["stale"]!;
        var state = (string)r["review_state"]!;
        var match = (string)r["match_status"]!;
        return name switch
        {
            "any" => (bool)r["needs_review"]!, "stale" => stale, "matched" => match == "matched",
            "directory_missing" => match is "missing_email" or "unmatched", "directory_ambiguous" => match is "duplicate_email" or "ambiguous_sap_email",
            "reviewed" => decision && state != "Needs review" && !stale, "pending" => !decision || state == "Needs review" || stale,
            "position_change" or "manager_change" => false,
            "functional_group_review" => (bool)r["classification_review"]!,
            _ => ((List<string>)r["findings"]!).Contains(name),
        };
    }

    internal static async Task<(Snapshot State, EmployeeDirectory? Directory, List<Dictionary<string, object?>> Rows, string Generation, JsonObject Settings)> CurrentAsync(IServiceProvider services, CancellationToken ct)
    {
        var state = await services.GetRequiredService<SnapshotService>().GetAsync(ct);
        var settings = await services.GetRequiredService<V1Settings>().GetAsync(ct);
        await using var db = await services.GetRequiredService<IDbContextFactory<SapLensDb>>().CreateDbContextAsync(ct);
        var saved = await LoadAsync(db, ct);
        var directory = V1Employees.Available(state, settings);
        var groups = settings["unlicensed_user_groups"]?.AsArray().Select(g => (string)g!).ToList() ?? [];
        var today = DateOnly.FromDateTime(DateTime.Now);
        var classifications = FunctionalGroupStore.ClassificationMap(await services.GetRequiredService<FunctionalGroupStore>().ReadAsync(ct));
        var rows = Rows(state, directory, saved, groups, today, classifications);
        var generation = CanonicalJson.Sha256(new object?[] { state.Ids.Users, directory?.Digest, groups, saved.Values.Select(s => s.Latest.Id).Order().ToList(), today.ToString("yyyy-MM-dd", CultureInfo.InvariantCulture) });
        return (state, directory, rows, generation, settings);
    }

    public static void Map(RouteGroupBuilder api)
    {
        var group = api.MapGroup("/account-review").AddEndpointFilter(async (context, next) =>
        {
            var settings = await context.HttpContext.RequestServices.GetRequiredService<V1Settings>().GetAsync(context.HttpContext.RequestAborted);
            return ((bool?)settings["features"]?["user_role_mapping"] ?? true) ? await next(context) : Detail(409, "User–Role Mapping is disabled. Enable it in Settings → Features; imported data is retained.");
        });

        group.MapGet("", async (HttpContext http, IServiceProvider services, CancellationToken ct) =>
        {
            var q = http.Request.Query;
            var search = q["search"].FirstOrDefault() ?? "";
            var wanted = q["findings"].Concat(q["finding"].Where(f => !string.IsNullOrEmpty(f))).Select(f => f!).Distinct().ToList();
            var licenses = q["license_groups"].Concat(q["license_group"].Where(f => !string.IsNullOrEmpty(f))).Select(f => f!).ToHashSet();
            var states = q["review_states"].Concat(q["review_state"].Where(f => !string.IsNullOrEmpty(f))).Select(f => f!).ToHashSet();
            var functionalGroups = q["functional_groups"].Select(f => f!).ToList();
            var managers = q["managers"].Select(f => f!).ToHashSet();
            var sort = q["sort"].FirstOrDefault() ?? "username";
            var descending = q["descending"].FirstOrDefault() is "true" or "1";
            var includeCompleted = q["include_completed"].FirstOrDefault() is "true" or "1";
            var offset = int.TryParse(q["offset"].FirstOrDefault() ?? "0", out var o) ? o : -1;
            var limit = int.TryParse(q["limit"].FirstOrDefault() ?? "25", out var l) ? l : -1;
            if (search.Length > 256 || offset < 0 || limit is < 1 or > 100 || !Sorts.Contains(sort) || licenses.Any(x => x is not ("classified" or "exclude")) || states.Any(s => !States.Contains(s))
                || wanted.Count > 32 || functionalGroups.Count > 50 || managers.Count > 50) return Detail(422, "Invalid account review query.");
            if (wanted.Any(w => !FilterNames.Contains(w))) return Detail(422, "Unknown review finding.");
            var (state, directory, items, generation, _) = await CurrentAsync(services, ct);
            var loaded = state.Ids.Users is not null;
            Dictionary<string, object?> summary = loaded ? new()
            {
                ["total"] = items.Count, ["outdated"] = items.Count(r => (bool)r["stale"]!), ["matched"] = directory is null ? null : items.Count(r => (string)r["match_status"]! == "matched"),
                ["missing"] = directory is null ? null : items.Count(r => ((List<string>)r["findings"]!).Contains("directory_match")),
                ["mismatch"] = items.Count(r => ((List<string>)r["findings"]!).Contains("ad_disabled_open")), ["requiring_review"] = items.Count(r => (bool)r["needs_review"]!),
                ["position_changes"] = null, ["unlicensed"] = items.Count(r => (bool)r["unlicensed"]!), ["reviewed"] = items.Count(r => Has(r, "reviewed")),
                ["completed"] = items.Count(r => (string)r["workflow_status"]! == "completed"), ["pending"] = items.Count(r => Has(r, "pending")),
            } : new[] { "total", "outdated", "matched", "missing", "mismatch", "requiring_review", "position_changes", "unlicensed", "reviewed", "completed", "pending" }.ToDictionary(k => k, _ => (object?)null);
            var term = search.Trim();
            var licenseFilter = licenses.Count == 1 ? licenses : [];
            var showCompleted = includeCompleted || states.Contains("No action required") || wanted.Contains("reviewed");
            var matching = items.Where(r =>
            {
                string[] fields = [(string)r["username"]!, (string)r["name"]!, .. (List<string>)r["groups"]!];
                if (term.Length > 0 && !(term.Contains('*') ? fields.Any(f => TextMatching.TextMatches(f, term)) : TextMatching.TextMatches(string.Join(' ', fields), term))) return false;
                return (wanted.Count == 0 || wanted.Any(w => Has(r, w))) && (licenseFilter.Count == 0 || (bool)r["unlicensed"]! == licenseFilter.Contains("classified"))
                    && (states.Count == 0 || states.Contains((string)r["review_state"]!)) && (functionalGroups.Count == 0 || functionalGroups.Contains(FunctionalGroupId(r)))
                    && (managers.Count == 0 || managers.Contains(ManagerKey(r)));
            }).ToList();
            var hidden = showCompleted ? 0 : matching.Count(r => (string)r["workflow_status"]! == "completed");
            var visible = showCompleted ? matching : matching.Where(r => (string)r["workflow_status"]! != "completed").ToList();
            static string Fold(object? value) => (value as string ?? "").ToUpperInvariant().ToLowerInvariant();
            IEnumerable<Dictionary<string, object?>> ordered = sort == "priority"
                ? visible.OrderBy(r => (int)r["priority_order"]!).ThenBy(r => Fold(r["username"]), StringComparer.Ordinal)
                : visible.OrderBy(r => Fold(r[sort]), StringComparer.Ordinal).ThenBy(r => Fold(r["username"]), StringComparer.Ordinal);
            var list = ordered.ToList();
            if (descending) list.Reverse();
            var managerOptions = items.GroupBy(ManagerKey).Select(g =>
            {
                var m = g.First()["manager"] as Dictionary<string, object?>;
                var label = g.Key == "none" ? "No manager" : (string?)m?["name"] is { Length: > 0 } name ? name : (string?)m?["email"] ?? "No manager";
                return new Dictionary<string, object?> { ["value"] = g.Key, ["label"] = label, ["count"] = g.Count() };
            }).OrderBy(o => (string)o["value"]! == "none").ThenBy(o => Fold(o["label"]), StringComparer.Ordinal).ThenBy(o => (string)o["value"]!, StringComparer.Ordinal).ToList();
            return Json(new Dictionary<string, object?>
            {
                ["items"] = list.Skip(offset).Take(limit).ToList(), ["total"] = list.Count, ["offset"] = offset, ["limit"] = limit, ["completed_hidden"] = hidden, ["include_completed"] = showCompleted,
                ["functional_group_options"] = FunctionalGroupStore.ListGroups(await services.GetRequiredService<FunctionalGroupStore>().ReadAsync(ct))
                    .Where(g => (string?)g["status"] == "active" || (int)g["user_count"]! > 0)
                    .Select(g => new { value = (string)g["id"]!, label = (string)g["name"]! + ((string?)g["status"] == "archived" ? " (archived)" : "") })
                    .Prepend(new { value = "unassigned", label = "Unassigned" }).ToList(), ["manager_options"] = managerOptions,
                ["loaded"] = loaded, ["directory_available"] = directory is not null, ["summary"] = summary, ["data_revision"] = generation, ["finding_labels"] = Findings, ["review_states"] = States,
            });
        });

        group.MapPost("/decision/{**username}", async (string username, HttpContext http, IServiceProvider services, CancellationToken ct) =>
        {
            var (body, invalid) = await V1Validation.ReadBody(http, ct);
            if (invalid is not null) return invalid;
            var errors = new List<object>();
            V1Validation.Extra(body!, ["state", "reviewer", "rationale", "evidence_version", "expected_decision"], errors);
            var state = V1Validation.Text(body!, "state", 1, 64, true, errors);
            var reviewerText = V1Validation.Text(body!, "reviewer", 1, 120, true, errors);
            var rationale = V1Validation.Text(body!, "rationale", 1, 2000, true, errors);
            var evidence = V1Validation.Text(body!, "evidence_version", 64, 64, true, errors);
            string? expected = null;
            var hasExpected = body!.TryGetPropertyValue("expected_decision", out var expectedNode) && expectedNode is not null;
            if (hasExpected) expected = V1Validation.Text(body, "expected_decision", 0, 64, false, errors);
            if (state is not null && !States.Contains(state)) errors.Add(V1Validation.Error("literal_error", "state", "Input should be " + string.Join(", ", States.Select(s => $"'{s}'"))));
            if (evidence is not null && !System.Text.RegularExpressions.Regex.IsMatch(evidence, "^[a-f0-9]{64}$")) errors.Add(V1Validation.Error("string_pattern_mismatch", "evidence_version", "String should match pattern '^[a-f0-9]{64}$'"));
            if (errors.Count > 0) return Results.Json(new { detail = errors }, statusCode: 422);
            if (reviewerText!.Trim().Length == 0 || rationale!.Trim().Length == 0) return Detail(422, "Reviewer and rationale are required.");

            // Attribution: an individual account (Accounts mode) or the single local Desktop user. A shared secret is not a reviewer identity.
            var host = services.GetRequiredService<HostSettings>();
            var actor = Actors.Current(http);
            if (actor.Provenance is not ("server-session" or "desktop"))
                return Detail(403, "Account Review decisions need an individual sign-in. Enable Accounts mode for this server; a shared access token is not a reviewer identity.");
            var sessionUser = actor.Provenance == "server-session";
            var reviewer = sessionUser ? actor.Username : reviewerText.Trim();
            var identity = sessionUser
                ? new Dictionary<string, object?> { ["id"] = actor.Id, ["username"] = actor.Username, ["display_name"] = actor.DisplayName, ["provenance"] = "server-session" }
                : (await V1Configuration.EnsureProfileAsync(services.GetRequiredService<WriteCoordinator>(), services.GetRequiredService<TimeProvider>(), null, null, ct))["identity"]!
                    .AsObject().ToDictionary(p => p.Key, p => (object?)(string?)p.Value);

            var (snapshot, _, items, _, _) = await CurrentAsync(services, ct);
            var row = items.FirstOrDefault(r => ((string)r["username"]!).Trim().ToUpperInvariant() == username.Trim().ToUpperInvariant());
            if (row is null) return Detail(404, "SAP user not found.");
            if ((string)row["evidence_version"]! != evidence) return Detail(409, "Identity evidence changed. Refresh the review before saving.");
            // Signed-in users always need the version they saw; any client that sends it gets the same protection.
            var current = row["decision"] is Dictionary<string, object?> d ? (string)d["timestamp"]! : "";
            if ((sessionUser || hasExpected) && expected != current) return Detail(409, "Another user changed this review. Reload before saving.");
            var details = new JsonObject
            {
                ["evidence_schema"] = 2, ["identity_version"] = (string)row["identity_version"]!, ["position_change_id"] = null, ["manager_change_id"] = null,
                ["actor_identity"] = JsonSerializer.SerializeToNode(identity),
            };
            try
            {
                await services.GetRequiredService<ReviewService>().RecordAccountAsync((string)row["username"]!, state!, evidence!, reviewer, rationale.Trim(), details.ToJsonString(), snapshot.Ids.Users!.Value,
                    latest => (latest is null ? "" : Stamp(latest.DecidedUtc)) == current, ct);
            }
            catch (ImportConflictException error) { return Detail(409, error.Message); }
            return Json(new { status = "saved" });
        });

        group.MapGet("/history/{**username}", async (string username, HttpContext http, IDbContextFactory<SapLensDb> factory, CancellationToken ct) =>
        {
            var offset = int.TryParse(http.Request.Query["offset"].FirstOrDefault() ?? "0", out var o) ? o : -1;
            var limit = int.TryParse(http.Request.Query["limit"].FirstOrDefault() ?? "25", out var l) ? l : -1;
            if (offset < 0 || limit is < 1 or > 100) return Detail(422, "Invalid paging parameters.");
            await using var db = await factory.CreateDbContextAsync(ct);
            var key = Sources.AccountKey(username);
            var decisions = await db.ReviewDecisions.AsNoTracking().Where(d => d.SubjectType == "account" && d.SubjectKey == key).OrderByDescending(d => d.Id).ToListAsync(ct);
            var events = decisions.Skip(1).ToList(); // the latest decision is the current one; earlier ones are its history, newest first
            return Json(new { items = events.Skip(offset).Take(limit).Select(DecisionView).ToList(), total = events.Count, offset, limit });
        });
    }
}
