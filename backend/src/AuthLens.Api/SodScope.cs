using System.Globalization;
using System.Text.Json.Nodes;
using Microsoft.EntityFrameworkCore;
using AuthLens.Application;
using AuthLens.Domain.Json;
using AuthLens.Domain.Roles;
using AuthLens.Domain.Sod;
using AuthLens.Domain.Users;
using AuthLens.Persistence;

namespace AuthLens.Api;

/// <summary>One review context (sod_scope.load): live evidence ("current") or a review period's captured snapshot. Frozen periods (Approved/Closed) read
/// their decisions from the snapshot, never from the live store. Evidence is never mutated.</summary>
public sealed class SodBundle
{
    public required string Context { get; init; }
    public required string Generation { get; init; }
    public required string AsOf { get; init; }
    public required JsonObject Coverage { get; init; }
    public JsonObject? Period { get; init; }
    public bool Frozen { get; init; }
    public bool Reviewable { get; init; }
    public bool OnlyCurrent { get; init; }
    public required Dictionary<string, string> Versions { get; init; }
    public JsonObject? FrozenDecisions { get; init; }
    public bool Legacy { get; init; }
    /// <summary>The imported assignment cut of this context (null: a historical period captured without it).</summary>
    public List<(string User, List<SodGovernance.SourceAssignment> Assignments)>? AssignmentSource { get; init; }
    public required List<string> CatalogueNames { get; init; }
    public required string Validity { get; init; }
    public required List<JsonObject> Findings { get; init; }
    public V1SodAnalysis.Query? Query { get; init; }
    /// <summary>Complete users of a period (all business assignments matched) for comparisons.</summary>
    public JsonObject? Saved { get; init; }

    internal Dictionary<string, SodUserEntry>? ModelCache, ReviewCache;
    internal int? RevisionCache;
    internal Dictionary<string, IReadOnlyDictionary<string, SodDecisionEvent>>? LatestCache;
    internal List<JsonObject>? ActionsCache;
}

/// <summary>sod_routes scope_query: shared SoD filters. OR within one filter (single value plus its list), AND between filters.</summary>
public sealed record SodQuery
{
    public string Context { get; init; } = "current";
    public string Validity { get; init; } = "active";
    public DateOnly? AsOf { get; init; }
    public Dictionary<string, string> Text { get; init; } = new(StringComparer.Ordinal);
    public Dictionary<string, List<string>> Lists { get; init; } = new(StringComparer.Ordinal);
    public string RoleMatch { get; init; } = "search";
    public string AccountStatus { get; init; } = "";
    public bool MultipleRisks { get; init; }
    public string ActivityDecision { get; init; } = "";
    public string AssignmentDecision { get; init; } = "";
    public string Acceptance { get; init; } = "";
    public string ReviewStatus { get; init; } = "";
    public string AssignmentScope { get; init; } = "conflicts";
    public string Sort { get; init; } = "subject";
    public bool Descending { get; init; }
    public bool ReviewPopulation { get; init; }
    public IReadOnlyDictionary<string, string> FamilyMap { get; init; } = new Dictionary<string, string>(StringComparer.Ordinal);

    public string S(string name) => Text.GetValueOrDefault(name) ?? "";
    public List<string> L(string name) => Lists.GetValueOrDefault(name) ?? [];
    /// <summary>many(): the single value plus the multi-select list.</summary>
    public List<string> Many(string single, string plural) => [.. new[] { S(single) }.Concat(L(plural)).Where(v => v.Length > 0)];

    /// <summary>A copy with one text or list filter cleared.</summary>
    public SodQuery Without(params string[] names)
    {
        var text = new Dictionary<string, string>(Text, StringComparer.Ordinal);
        var lists = Lists.ToDictionary(p => p.Key, p => p.Value, StringComparer.Ordinal);
        foreach (var n in names) { text.Remove(n); lists.Remove(n); }
        var copy = this with { Text = text, Lists = lists };
        if (names.Contains("activity_decision")) copy = copy with { ActivityDecision = "" };
        if (names.Contains("assignment_decision")) copy = copy with { AssignmentDecision = "" };
        if (names.Contains("acceptance")) copy = copy with { Acceptance = "" };
        if (names.Contains("account_status")) copy = copy with { AccountStatus = "" };
        if (names.Contains("multiple_risks")) copy = copy with { MultipleRisks = false };
        if (names.Contains("review_status")) copy = copy with { ReviewStatus = "" };
        return copy;
    }
}

public static class SodScope
{
    public static readonly string[] FrozenStates = ["Approved", "Closed", "Approved / closed"];
    public static readonly HashSet<string> Decided = ["Approved", "Keep", "Accepted", "Conditional", "Removal required", "Rejected"];
    private static readonly StringComparer Ordinal = StringComparer.Ordinal;
    public static readonly (string Name, int Max)[] TextFields =
    [
        ("search", 256), ("risk", 512), ("criticality", 64), ("risk_type", 64), ("category", 120), ("username", 512), ("group", 256), ("composite_role", 512),
        ("single_role", 512), ("tcode", 256), ("role", 512), ("role_suffix", 128), ("activity", 512),
    ];
    public static readonly (string Name, int Max)[] ListFields =
    [
        ("usernames", 100), ("role_suffixes", 100), ("risks", 100), ("activities", 100), ("groups", 100), ("roles", 100), ("role_families", 100), ("role_exact", 100),
        ("tcodes", 100), ("categories", 50), ("criticalities", 50), ("functional_groups", 50), ("managers", 50),
    ];
    private static readonly string[] Lifecycles = ["", "Pending", "Approved", "Keep", "Accepted", "Conditional", "Removal required", "Investigate", "Rejected", "Outdated"];

    public static IResult Problem(int status, object detail) => Results.Json(new { detail }, statusCode: status);

    public static bool Flag(string? value) => (value ?? "").PyLower() is "true" or "1" or "yes" or "on";
    private static bool? ParseBool(string? value) => value is null ? false : value.PyLower() switch
    {
        "true" or "1" or "yes" or "on" or "t" or "y" => true, "false" or "0" or "no" or "off" or "f" or "n" => false, _ => null,
    };

    /// <summary>scope_query: v1's names, enumerations and bounds; an invalid value is a 422.</summary>
    public static (SodQuery? Query, IResult? Error) Parse(IQueryCollection q, string[]? sorts = null)
    {
        IResult Bad(string field, string message) => Problem(422, new[] { new { type = "value_error", loc = new object[] { "query", field }, msg = message, input = (object?)q[field].FirstOrDefault() } });
        var context = q["context"].FirstOrDefault() ?? "current";
        if (!SodDecisionStore.ContextPattern().IsMatch(context)) return (null, Bad("context", "String should match pattern '^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$'"));
        var text = new Dictionary<string, string>(Ordinal);
        foreach (var (name, max) in TextFields)
        {
            var value = q[name].FirstOrDefault() ?? "";
            if (value.Length > max) return (null, Bad(name, $"String should have at most {max} characters"));
            text[name] = value;
        }
        var lists = new Dictionary<string, List<string>>(Ordinal);
        foreach (var (name, max) in ListFields)
        {
            if (q[name].Count > max) return (null, Bad(name, $"List should have at most {max} items after validation, not {q[name].Count}"));
            lists[name] = [.. q[name].Select(v => v ?? "")];
        }
        string Choice(string name, string fallback, params string[] allowed) => q[name].FirstOrDefault() is { } v ? (allowed.Contains(v) ? v : throw new ArgumentException(name)) : fallback;
        try
        {
            DateOnly? asOf = q["as_of"].FirstOrDefault() is { Length: > 0 } day
                ? DateOnly.TryParseExact(day, "yyyy-MM-dd", CultureInfo.InvariantCulture, DateTimeStyles.None, out var parsed) ? parsed : throw new ArgumentException("as_of") : null;
            var multiple = ParseBool(q["multiple_risks"].FirstOrDefault()) ?? throw new ArgumentException("multiple_risks");
            var descending = ParseBool(q["descending"].FirstOrDefault()) ?? throw new ArgumentException("descending");
            return (new SodQuery
            {
                Context = context, Validity = Choice("validity", "active", "active", "expired", "future", "unknown", "all"), AsOf = asOf, Text = text, Lists = lists,
                RoleMatch = Choice("role_match", "search", "search", "exact", "prefix", "wildcard"),
                AccountStatus = Choice("account_status", "", "", "locked", "unlocked", "ad_disabled", "ad_enabled", "unknown"), MultipleRisks = multiple,
                ActivityDecision = Choice("activity_decision", "", Lifecycles), AssignmentDecision = Choice("assignment_decision", "", Lifecycles), Acceptance = Choice("acceptance", "", Lifecycles),
                ReviewStatus = Choice("review_status", "", "", "attention", "pending", "investigating", "reviewed", "all"),
                AssignmentScope = Choice("assignment_scope", "conflicts", "conflicts", "all"), Sort = Choice("sort", "subject", sorts ?? ["subject", "findings", "group"]), Descending = descending,
            }, null);
        }
        catch (ArgumentException error) { return (null, Bad(error.Message, "Input should be a valid value")); }
    }

    // ---- Loading

    private static T Service<T>(IServiceProvider services) where T : notnull => services.GetRequiredService<T>();

    /// <summary>sod_scope.load. Throws SodDecisionException (404/409) like v1's HTTPException.</summary>
    public static async Task<SodBundle> LoadAsync(IServiceProvider services, string context, string validity, DateOnly? asOf, CancellationToken ct)
    {
        SodDecisionStore.CheckContext(context);
        if (context == "current") return await LiveAsync(services, validity, asOf, ct);
        var periods = Service<SodPeriodStore>(services);
        var index = await periods.ReadAsync(ct);
        var period = SodPeriodStore.Find(index, context, archived: true);
        if (period["deleted_at"] is JsonValue) throw new SodDecisionException(404, "Review period not found.");
        var saved = await periods.SnapshotAsync(period, ct);
        var state = (string)period["state"]!;
        var frozen = FrozenStates.Contains(state);
        var analysis = saved["analysis"]!.AsObject();
        var versions = new Dictionary<string, string>(Ordinal);
        if (saved["source_versions"] is JsonObject sv) foreach (var (k, v) in sv) if (v is JsonValue) versions[k] = (string)v!;
        List<(string, List<SodGovernance.SourceAssignment>)>? source = null;
        if (saved["assignment_source"] is JsonObject cut)
            source = [.. cut.Select(p => (p.Key, p.Value!["assignments"]!.AsArray().Select(a => a!.AsObject()).Select(a => new SodGovernance.SourceAssignment(
                (string?)a["role_name"] ?? "", (string?)a["valid_from"], (string?)a["valid_to"], (string?)a["user_group"] ?? "", (string?)a["match_status"],
                a["catalogue_roles"] is JsonArray roles ? [.. roles.Select(r => (string)r!)] : [], a["tcodes"] is JsonArray codes ? [.. codes.Select(c => (string)c!)] : [])).ToList()))];
        return new SodBundle
        {
            Context = context, Generation = (string)period["snapshot"]!, AsOf = (string)saved["evaluation_date"]!, Coverage = analysis["coverage"]!.DeepClone().AsObject(),
            Period = period.DeepClone().AsObject(), Frozen = frozen, Reviewable = state is "Draft" or "In review", OnlyCurrent = true, Versions = versions,
            FrozenDecisions = frozen ? saved["decisions"] as JsonObject : null, Legacy = (int?)saved["model"] != 2, AssignmentSource = source,
            CatalogueNames = saved["catalogue_names"] is JsonArray names ? [.. names.Select(n => (string)n!)] : [], Validity = validity,
            Findings = [.. analysis["users"]!.AsArray().Select(f => f!.AsObject())], Saved = saved,
        };
    }

    private static async Task<SodBundle> LiveAsync(IServiceProvider services, string validity, DateOnly? asOf, CancellationToken ct)
    {
        await Service<AssignmentLifecycle>(services).ObserveAsync(ct);
        var query = new V1SodAnalysis.Query("users", validity, asOf ?? DateOnly.FromDateTime(DateTime.Now), [], "", "", "", "", "", "", "", "", "", "", "", [], [], [], [], [], [], "subject", false);
        var (captured, error) = await V1SodAnalysis.CaptureAsync(services, query, ct);
        if (error is not null) throw new SodDecisionException(409, "SoD evidence is unavailable.");
        var snapshot = await Service<SnapshotService>(services).GetAsync(ct);
        var settings = await Service<V1Settings>(services).GetAsync(ct);
        var features = settings["features"];
        var sourceEnabled = ((bool?)features?["sod"] ?? false) && ((bool?)features?["user_role_mapping"] ?? true);
        var source = sourceEnabled
            ? snapshot.Users.UserOrder.Select(key => (key, snapshot.Users.Users[key].Assignments.Select(a =>
                new SodGovernance.SourceAssignment(a.RoleName, a.ValidFrom, a.ValidTo, a.UserGroup, a.MatchStatus, a.CatalogueRoles, a.Tcodes)).ToList())).ToList()
            : [];
        var versions = new Dictionary<string, string>(Ordinal);
        if (settings["data_lifecycle"]?["sources"] is JsonObject references)
            foreach (var (name, reference) in references) if ((string?)reference?["snapshot"] is { } version) versions[name] = version;
        if ((string?)settings["employee_snapshot_id"] is { Length: > 0 } employees) versions["employees"] = employees;
        return new SodBundle
        {
            Context = "current", Generation = captured!.Generation, AsOf = captured.AsOf, Coverage = captured.Coverage, Frozen = false, Reviewable = validity == "active",
            OnlyCurrent = validity == "active", Versions = versions, AssignmentSource = source, CatalogueNames = [.. snapshot.Catalogue.Roles.Keys], Validity = validity,
            Findings = captured.Users, Query = query,
        };
    }

    public static Dictionary<string, SodUserEntry> Model(SodBundle b) => b.ModelCache ??= SodGovernance.Derive(b.Findings, b.OnlyCurrent);

    /// <summary>review_model_for: the conflict model extended with every assignment of the source cut (never an input to detection).</summary>
    public static Dictionary<string, SodUserEntry> ReviewModel(SodBundle b)
    {
        if (b.ReviewCache is not null) return b.ReviewCache;
        var model = Model(b);
        if ((string?)b.Coverage["status"] != "available" || b.AssignmentSource is null) return b.ReviewCache = model;
        var day = DateOnly.ParseExact(b.AsOf, "yyyy-MM-dd", CultureInfo.InvariantCulture);
        return b.ReviewCache = SodGovernance.ReviewModel(model, b.AssignmentSource.Select(s => (s.User, (IEnumerable<SodGovernance.SourceAssignment>)s.Assignments)), b.Validity, day);
    }

    public static async Task<int> RevisionAsync(IServiceProvider services, SodBundle b, CancellationToken ct) =>
        b.RevisionCache ??= await Service<SodDecisionStore>(services).RevisionAsync(ct);

    /// <summary>latest_for: kind -> key -> latest event (the snapshot copy when frozen).</summary>
    public static async Task<Dictionary<string, IReadOnlyDictionary<string, SodDecisionEvent>>> LatestAsync(IServiceProvider services, SodBundle b, CancellationToken ct)
    {
        if (b.LatestCache is not null) return b.LatestCache;
        if (b.FrozenDecisions is not null)
        {
            var result = new Dictionary<string, IReadOnlyDictionary<string, SodDecisionEvent>>(Ordinal);
            foreach (var kind in SodGovernance.Decisions.Keys)
            {
                var map = new Dictionary<string, SodDecisionEvent>(Ordinal);
                if (b.FrozenDecisions["events"]?[kind] is JsonObject events)
                    foreach (var (key, items) in events) if (items is JsonArray { Count: > 0 } list) map[key] = SodDecisionEvent.FromJson(list[^1]!.AsObject());
                result[kind] = map;
            }
            return b.LatestCache = result;
        }
        return b.LatestCache = await Service<SodDecisionStore>(services).LatestAsync(b.Context, ct);
    }

    /// <summary>states_for: frozen assessments keep their approval-date lifecycle and captured evidence; live contexts use today and the reappearance memory.</summary>
    public static async Task<SodStates> StatesAsync(IServiceProvider services, SodBundle b, IReadOnlyDictionary<string, SodUserEntry> model, CancellationToken ct)
    {
        var latest = await LatestAsync(services, b, ct);
        if (b.Frozen)
        {
            var approved = (string?)b.Period?["approval_date"];
            var day = approved is null ? DateOnly.FromDateTime(DateTime.Now) : DateOnly.ParseExact(approved, "yyyy-MM-dd", CultureInfo.InvariantCulture);
            return SodGovernance.States(model, latest, day);
        }
        var applies = await Service<AssignmentLifecycle>(services).ApplicabilityAsync(ct);
        return SodGovernance.States(model, latest, DateOnly.FromDateTime(DateTime.Now), applies.Reappeared, applies.Reasons, applies.Unavailable);
    }

    public static async Task<List<JsonObject>> ActionsAsync(IServiceProvider services, SodBundle b, CancellationToken ct)
    {
        if (b.ActionsCache is not null) return b.ActionsCache;
        if (b.FrozenDecisions is not null) return b.ActionsCache = [.. (b.FrozenDecisions["actions"] as JsonArray ?? []).Select(a => a!.AsObject())];
        return b.ActionsCache = await Service<SodDecisionStore>(services).ActionsAsync(b.Context, ct);
    }

    /// <summary>context_info.</summary>
    public static async Task<JsonObject> InfoAsync(IServiceProvider services, SodBundle b, CancellationToken ct) => new()
    {
        ["context"] = b.Context, ["generation"] = b.Generation, ["as_of"] = b.AsOf, ["coverage"] = b.Coverage.DeepClone(), ["frozen"] = b.Frozen, ["reviewable"] = b.Reviewable,
        ["revision"] = await RevisionAsync(services, b, ct), ["legacy"] = b.Legacy,
        ["period"] = b.Period is null ? null : new JsonObject { ["id"] = b.Period["id"]!.DeepClone(), ["name"] = b.Period["name"]!.DeepClone(), ["state"] = b.Period["state"]!.DeepClone() },
    };

    // ---- Filters

    public static HashSet<string> WantedSuffixes(SodQuery q) =>
        q.L("role_suffixes").Append(q.S("role_suffix")).Select(v => v.Trim()).Where(v => v.Length > 0).Select(SodViews.Fold).ToHashSet(Ordinal);
    public static HashSet<string> WantedUsers(SodQuery q) => q.L("usernames").Select(v => v.Trim()).Where(v => v.Length > 0).Select(SodViews.Fold).ToHashSet(Ordinal);
    private static bool SuffixMatches(string role, HashSet<string> wanted) => wanted.Count == 0 || wanted.Contains(SodViews.Fold(SodViews.RoleSuffix(role)));
    private static bool AnyMatch(string value, List<string> wanted) => wanted.Count == 0 || wanted.Any(w => TextMatching.TextMatches(value, w));

    public static bool RoleSelectionMatches(string value, List<string> wanted, string mode)
    {
        if (wanted.Count == 0) return true;
        return mode switch
        {
            "exact" => wanted.Contains(value),
            "prefix" => wanted.Any(w => SodViews.Fold(value).StartsWith(SodViews.Fold(w), StringComparison.Ordinal)),
            "wildcard" => wanted.Any(w => w.Contains('*') ? TextMatching.TextMatches(value, w) : SodViews.Fold(value) == SodViews.Fold(w)),
            _ => AnyMatch(value, wanted),
        };
    }

    public static bool RoleFiltersMatch(string value, SodQuery q)
    {
        var wanted = q.Many("role", "roles");
        var families = q.L("role_families");
        var exact = q.L("role_exact");
        if (wanted.Count == 0 && families.Count == 0 && exact.Count == 0) return true;
        return exact.Contains(value) || wanted.Count > 0 && RoleSelectionMatches(value, wanted, q.RoleMatch)
            || families.Count > 0 && q.FamilyMap.TryGetValue(value, out var family) && families.Contains(family);
    }

    /// <summary>access_package.role_families: display families from business-role naming evidence; opaque and interior-wildcard names stay exact.</summary>
    public static Dictionary<string, string> FamilyMap(SodBundle b)
    {
        var names = (b.AssignmentSource ?? []).SelectMany(s => s.Assignments).Select(a => a.RoleName).Where(n => n.Length > 0).ToHashSet(Ordinal);
        var known = AccessPackage.NamingEvidence(names.Concat(b.CatalogueNames));
        var explicitFamilies = b.CatalogueNames.Where(n => n.EndsWith(":*", StringComparison.Ordinal) && n.Count(c => c == '*') == 1 && RoleNames.Scope(n) == "business")
            .Select(RoleNames.Normalize).ToHashSet(Ordinal);
        var result = new Dictionary<string, string>(Ordinal);
        foreach (var name in names)
        {
            if (RoleNames.Scope(name) != "business" || name.Split(':').Length < 4) continue;
            if (name.Contains('*')) { if (name.EndsWith(":*", StringComparison.Ordinal) && name.Count(c => c == '*') == 1) result[name] = name; continue; }
            var cut = name.LastIndexOf(':');
            var (stem, suffix) = (name[..cut], name[(cut + 1)..]);
            if (AccessPackage.SuffixError(AccessPackage.NormalizeSuffix(suffix)) is not null) continue;
            if (AccessPackage.SuffixKind(name, known) == "organizational" || explicitFamilies.Contains(RoleNames.Normalize(stem + ":*"))) result[name] = stem + ":*";
        }
        return result;
    }

    private static bool PathMatches(JsonObject finding, SodQuery q)
    {
        var paths = finding["evidence"]!.AsObject().SelectMany(p => p.Value!.AsArray()).Select(p => p!.AsObject()).ToList();
        string Role(JsonObject p) => (string?)p["actual_assigned_role"] ?? "";
        if ((q.Many("role", "roles").Count > 0 || q.L("role_families").Count > 0 || q.L("role_exact").Count > 0) && !paths.Any(p => RoleFiltersMatch(Role(p), q))) return false;
        var wanted = WantedSuffixes(q);
        if (wanted.Count > 0 && !paths.Any(p => SuffixMatches(Role(p), wanted))) return false;
        var activities = q.Many("activity", "activities");
        return activities.Count == 0 || paths.Any(p => AnyMatch((string)p["activity"]!, activities));
    }

    public static bool AssignmentFiltersActive(SodQuery q) =>
        new[] { "role", "role_suffix", "group", "activity", "tcode" }.Any(n => q.S(n).Length > 0)
        || new[] { "roles", "role_families", "role_exact", "role_suffixes", "groups", "activities", "tcodes" }.Any(n => q.L(n).Count > 0)
        || q.AssignmentDecision.Length > 0 || q.ReviewStatus is not ("" or "all");

    public static readonly Dictionary<string, HashSet<string>> ReviewStatus = new(Ordinal)
    {
        ["attention"] = ["Pending", "Investigate", "Outdated"], ["pending"] = ["Pending", "Outdated"], ["investigating"] = ["Investigate"], ["reviewed"] = ["Keep", "Removal required"],
    };

    /// <summary>{user: assignment ids} passing every assignment-level filter.</summary>
    public static Dictionary<string, HashSet<string>> AllowedAssignments(IReadOnlyDictionary<string, SodUserEntry> model, SodStates state, SodQuery q)
    {
        var wanted = WantedSuffixes(q);
        var groups = q.Many("group", "groups");
        var activities = q.Many("activity", "activities");
        var codes = q.Many("tcode", "tcodes");
        var result = new Dictionary<string, HashSet<string>>(Ordinal);
        foreach (var (user, entry) in model)
        {
            var ids = new HashSet<string>(Ordinal);
            foreach (var (aid, a) in entry.Assignments)
            {
                if (!RoleFiltersMatch(a.Role, q) || !SuffixMatches(a.Role, wanted)) continue;
                if (groups.Count > 0 && !groups.Contains(a.UserGroup)) continue;
                if (activities.Count > 0 && !a.Supplies.Keys.Any(n => AnyMatch(n, activities))) continue;
                if (codes.Count > 0 && !(q.AssignmentScope == "all" ? a.CatalogueTcodes ?? [] : a.Supplies.Values.SelectMany(c => c)).Any(c => AnyMatch(c, codes))) continue;
                var life = state.Items["assignment"][aid].Lifecycle;
                if (q.AssignmentDecision.Length > 0 && life != q.AssignmentDecision) continue;
                if (ReviewStatus.TryGetValue(q.ReviewStatus, out var keep) && !keep.Contains(life)) continue;
                ids.Add(aid);
            }
            result[user] = ids;
        }
        return result;
    }

    private static V1SodAnalysis.Query AnalysisQuery(SodQuery q, SodBundle b) =>
        new("users", q.Validity, DateOnly.ParseExact(b.AsOf, "yyyy-MM-dd", CultureInfo.InvariantCulture), [], q.S("search"), q.S("risk"), q.S("criticality"), q.S("risk_type"),
            q.S("category"), q.S("username"), q.S("group"), q.S("composite_role"), q.S("single_role"), q.S("tcode"), q.AccountStatus, q.L("usernames"), q.L("risks"),
            q.L("criticalities"), q.L("categories"), q.L("groups"), q.L("tcodes"), "subject", false);

    /// <summary>visible_cells: {user: {risk}} after path-level, text and decision filters.</summary>
    public static Dictionary<string, HashSet<string>> VisibleCells(SodBundle b, IReadOnlyDictionary<string, SodUserEntry> model, SodStates state, SodQuery q)
    {
        var rows = b.Findings.Where(r => model.TryGetValue((string)r["subject"]!, out var e) && e.Findings.ContainsKey((string)r["risk_id"]!)).ToList();
        var captured = new V1SodAnalysis.Captured(b.Generation, b.AsOf, rows, [], [], b.Coverage, [], []);
        var users = WantedUsers(q);
        var visible = new Dictionary<string, HashSet<string>>(Ordinal);
        foreach (var finding in V1SodAnalysis.Filtered(captured, AnalysisQuery(q, b)))
        {
            var subject = (string)finding["subject"]!;
            if (users.Count > 0 && !users.Contains(SodViews.Fold(subject))) continue;
            if (!PathMatches(finding, q)) continue;
            var entry = model[subject];
            if (q.MultipleRisks && entry.Findings.Count < 2) continue;
            var riskId = (string)finding["risk_id"]!;
            var names = entry.Activities.Where(p => p.Value.Risks.Contains(riskId)).Select(p => p.Key).ToList();
            if (q.Acceptance.Length > 0 && state.Items["acceptance"][(string)finding["finding_id"]!].Lifecycle != q.Acceptance) continue;
            if (q.ActivityDecision.Length > 0 && !names.Any(n => state.Items["activity"][entry.Activities[n].Key].Lifecycle == q.ActivityDecision)) continue;
            if (q.AssignmentDecision.Length > 0 && !names.Any(n => entry.Activities[n].Assignments.Any(aid => state.Items["assignment"][aid].Lifecycle == q.AssignmentDecision))) continue;
            if (!visible.TryGetValue(subject, out var set)) visible[subject] = set = new HashSet<string>(Ordinal);
            set.Add(riskId);
        }
        return visible;
    }

    /// <summary>assignment_view: the assignment predicates over the complete validated review population.</summary>
    public static Dictionary<string, SodUserEntry> AssignmentView(SodBundle b, IReadOnlyDictionary<string, SodUserEntry> model, SodStates state, SodQuery q)
    {
        if (b.AssignmentSource is null)
            throw new SodDecisionException(409, "This historical period lacks a full assignment snapshot. Use its retained evidence or create a new period; current imports are never substituted.");
        var allowed = AllowedAssignments(model, state, q);
        var constrained = new[] { "risk", "criticality", "risk_type", "category" }.Any(n => q.S(n).Length > 0) || new[] { "risks", "criticalities", "categories" }.Any(n => q.L(n).Count > 0)
            || q.MultipleRisks || q.Acceptance.Length > 0 || q.ActivityDecision.Length > 0;
        var riskScope = constrained ? VisibleCells(b, model, state, q) : null;
        var users = WantedUsers(q);
        var search = q.S("search");
        var result = new Dictionary<string, SodUserEntry>(Ordinal);
        foreach (var (user, entry) in model)
        {
            if (users.Count > 0 && !users.Contains(SodViews.Fold(user))) continue;
            if (q.S("username").Length > 0 && !TextMatching.TextMatches(user, q.S("username"))) continue;
            if (riskScope is not null && !riskScope.ContainsKey(user)) continue;
            var ids = allowed[user];
            if (search.Length > 0 && !TextMatching.TextMatches(user, search)) ids = ids.Where(aid => TextMatching.TextMatches(entry.Assignments[aid].Role, search)).ToHashSet(Ordinal);
            if (ids.Count == 0) continue;
            var risks = riskScope is null ? entry.Findings.Keys.ToHashSet(Ordinal) : riskScope[user];
            var copy = new SodUserEntry { User = entry.User, Account = entry.Account, VisibleAssignments = ids };
            foreach (var (k, v) in entry.Findings) if (risks.Contains(k)) copy.Findings[k] = v;
            foreach (var (k, v) in entry.Activities) if (v.Risks.Overlaps(risks)) copy.Activities[k] = v;
            foreach (var (k, v) in entry.Assignments) copy.Assignments[k] = v;
            copy.Groups.UnionWith(entry.Groups);
            result[user] = copy;
        }
        return result;
    }

    /// <summary>Functional Group and Manager select users by name through the username filter; they never alter conflict evaluation.</summary>
    public static async Task<SodQuery> OrganizationalAsync(IServiceProvider services, SodQuery q, CancellationToken ct)
    {
        var groups = q.L("functional_groups").Where(v => v.Length > 0).ToList();
        var managers = q.L("managers").Where(v => v.Length > 0).ToList();
        if (groups.Count == 0 && managers.Count == 0) return q;
        var snapshot = await Service<SnapshotService>(services).GetAsync(ct);
        var settings = await Service<V1Settings>(services).GetAsync(ct);
        var directory = V1Employees.Available(snapshot, settings);
        var data = await Service<FunctionalGroupStore>(services).ReadAsync(ct);
        var keep = V1FunctionalGroups.Selection(snapshot, directory, data, groups, managers);
        if (keep is null) return q;
        var universe = Model(await LoadAsync(services, q.Context, q.Validity, q.AsOf, ct)).Keys;
        var people = snapshot.Users.UserOrder.Select(k => snapshot.Users.Users[k]).ToList();
        var known = people.Select(u => u.Username.Trim().PyUpper()).ToHashSet(Ordinal);
        var extra = universe.Where(n => !known.Contains(n.Trim().PyUpper())).Select(n => new SapUser { Username = n });
        var allowed = people.Concat(extra).Where(keep).Select(u => u.Username).ToList();
        if (q.L("usernames").Count > 0)
        {
            var existing = q.L("usernames").Select(n => SodViews.Fold(n.Trim())).ToHashSet(Ordinal);
            allowed = allowed.Where(n => existing.Contains(SodViews.Fold(n.Trim()))).ToList();
        }
        var lists = q.Lists.ToDictionary(p => p.Key, p => p.Value, StringComparer.Ordinal);
        lists["usernames"] = allowed.Count > 0 ? allowed : ["\0"];
        return q with { Lists = lists };
    }

    public sealed record Scoped(SodBundle Bundle, Dictionary<string, SodUserEntry> Model, SodStates State, Dictionary<string, SodUserEntry> View, SodQuery Query);

    /// <summary>scoped(): bundle, full model, decision state and the filtered view for one request.</summary>
    public static async Task<Scoped> ScopedAsync(IServiceProvider services, SodQuery q, CancellationToken ct)
    {
        var b = await LoadAsync(services, q.Context, q.Validity, q.AsOf, ct);
        if (q.ReviewPopulation && b.AssignmentSource is not null) q = q with { AssignmentScope = "all" };
        q = q with { FamilyMap = q.L("role_families").Count > 0 ? FamilyMap(b) : new Dictionary<string, string>(Ordinal) };
        var model = q.AssignmentScope == "all" ? ReviewModel(b) : Model(b);
        await ObserveAsync(services, b, model, ct);
        var state = await StatesAsync(services, b, model, ct);
        var view = q.AssignmentScope == "all" ? AssignmentView(b, model, state, q)
            : SodViews.Restrict(model, VisibleCells(b, model, state, q), AssignmentFiltersActive(q) ? AllowedAssignments(model, state, q) : null);
        return new Scoped(b, model, state, view, q);
    }

    // ---- Live verification (verification_population, orphan_lifecycle, verifiers)

    /// <summary>verification_population: every imported assignment identity and the users whose business assignments are all matched (null when unavailable).</summary>
    public static async Task<(HashSet<string>? Ids, HashSet<string> Complete, JsonObject? Reference)> PopulationAsync(IServiceProvider services, IEnumerable<string>? users, CancellationToken ct)
    {
        var snapshot = await Service<SnapshotService>(services).GetAsync(ct);
        var settings = await Service<V1Settings>(services).GetAsync(ct);
        var reference = settings["data_lifecycle"]?["sources"]?["users"] as JsonObject;
        var features = settings["features"];
        if (!((bool?)features?["sod"] ?? false) || !((bool?)features?["user_role_mapping"] ?? true) || snapshot.Catalogue.Roles.Count == 0 || snapshot.Sod is null)
            return (null, [], reference);
        var ids = new HashSet<string>(Ordinal);
        var complete = new HashSet<string>(Ordinal);
        var selected = users is null ? snapshot.Users.Users.Values : users.Select(n => snapshot.Users.Users.GetValueOrDefault(RoleNames.NormalizeUsername(n))).OfType<SapUser>();
        foreach (var record in selected)
        {
            var name = RoleNames.NormalizeUsername(record.Username);
            if (snapshot.Users.InvalidCataloguePatterns == 0 && record.Assignments.Where(a => a.Scope != "other").All(a => a.MatchStatus is "exact" or "wildcard")) complete.Add(name);
            foreach (var a in record.Assignments) ids.Add(SodGovernance.AssignmentId(name, a.RoleName, a.ValidFrom, a.ValidTo, a.UserGroup));
        }
        return (ids, complete, reference);
    }

    /// <summary>make_verifier: no removal is inferred from absence in the filtered SoD finding population.</summary>
    public static async Task<(Func<string, string, string> Verify, JsonObject? Reference)> VerifierAsync(IServiceProvider services, IEnumerable<string>? users, CancellationToken ct)
    {
        var (live, complete, reference) = await PopulationAsync(services, users, ct);
        return ((user, aid) => live is null ? "Not assessable: current analysis is unavailable" : live.Contains(aid) ? "Still present in current evidence"
            : complete.Contains(RoleNames.NormalizeUsername(user)) ? "Not present in current evidence" : "Not assessable: source coverage incomplete", reference);
    }

    /// <summary>removal_verification: Verified needs newer source evidence that shows the assignment gone; a completed status is only a manual claim.</summary>
    public static (JsonObject Summary, HashSet<string> Ids) RemovalVerification(List<JsonObject> actions, Func<string, string, string> verify, JsonObject? reference)
    {
        var tracked = actions.Where(a => (string?)a["assignment_id"] is { Length: > 0 } && (string?)a["recommended"] == "Remove assignment" && (string?)a["status"] != "Cancelled").ToList();
        var summary = new JsonObject { ["tracked"] = tracked.Count, ["verified"] = 0, ["still_present"] = 0, ["awaiting_evidence"] = 0, ["not_assessable"] = 0, ["available"] = true, ["reason"] = null };
        var ids = new HashSet<string>(Ordinal);
        if (tracked.Count == 0) { summary["available"] = false; summary["reason"] = "No removal action is tracked yet."; return (summary, ids); }
        static DateTimeOffset? Moment(string? text) => DateTimeOffset.TryParse(text, CultureInfo.InvariantCulture, DateTimeStyles.AssumeUniversal, out var v) ? v : null;
        var imported = Moment((string?)reference?["imported_at"]);
        void Bump(string name) => summary[name] = (int)summary[name]! + 1;
        foreach (var item in tracked)
        {
            var text = verify((string)item["user"]!, (string)item["assignment_id"]!);
            if (text.StartsWith("Not assessable", StringComparison.Ordinal)) Bump("not_assessable");
            else if (text.StartsWith("Still present", StringComparison.Ordinal)) Bump("still_present");
            else if (imported is not null && (Moment((string?)item["created"]) ?? imported) < imported) { Bump("verified"); ids.Add((string)item["id"]!); }
            else Bump("awaiting_evidence");
        }
        if ((int)summary["not_assessable"]! == tracked.Count) { summary["available"] = false; summary["reason"] = "Current evidence cannot confirm removals (analysis unavailable or source coverage incomplete)."; }
        return (summary, ids);
    }

    /// <summary>orphan_lifecycle: decisions whose evidence is absent from live data are Resolved only when absence is verifiable.</summary>
    public static async Task<string> OrphanLifecycleAsync(IServiceProvider services, string kind, SodDecisionEvent e, CancellationToken ct)
    {
        var (present, complete, _) = await PopulationAsync(services, [e.User], ct);
        var user = RoleNames.NormalizeUsername(e.User);
        if (kind == "assignment") { if (present is null || present.Contains(e.Key) || !complete.Contains(user)) return "Historical"; }
        else if (!complete.Contains(user)) return "Historical";
        var settings = await Service<V1Settings>(services).GetAsync(ct);
        var reference = (string?)settings["data_lifecycle"]?["sources"]?["sod"]?["snapshot"];
        if (reference is null || e.SourceVersions?.GetValueOrDefault("sod") != reference) return "Historical";
        if (kind == "activity" && !await ActivityDefinedAsync(services, e.Ref, ct)) return "Historical";
        return "Resolved";
    }

    private static async Task<bool> ActivityDefinedAsync(IServiceProvider services, string name, CancellationToken ct)
    {
        var c = await V1SodCatalogue.ContextAsync(services, ct);
        if (c.Snapshot.Sod is null) return false;
        foreach (var risk in c.Snapshot.Sod.Risks)
        {
            var local = c.Storage["entries"]?[(string)risk["risk_id"]!]?["metadata"];
            if (local is not null && !((bool?)local["enabled"] ?? true) || !((bool?)risk["supported"] ?? false)) continue;
            if (V1SodCatalogue.Mappings(risk).Any(m => m.Activity == name)) return true;
        }
        return false;
    }

    // ---- observe (sod-observations): which findings were detected per source version, so a refresh can report what changed

    private const string Observations = "sod-observations";
    public const int ObserveLimit = 100_000;

    public static async Task<JsonNode?> ObserveAsync(IServiceProvider services, SodBundle b, IReadOnlyDictionary<string, SodUserEntry> model, CancellationToken ct)
    {
        if (b.Context != "current" || !b.OnlyCurrent) return null;
        try
        {
            var key = CanonicalJson.Sha256(b.Versions.OrderBy(p => p.Key, Ordinal).Select(p => new object[] { p.Key, p.Value }).ToList());
            var ids = model.Values.SelectMany(e => e.Findings.Values).Select(f => (string)f["finding_id"]!).Order(Ordinal).ToList();
            var factory = Service<IDbContextFactory<AuthLensDb>>(services);
            await using (var db = await factory.CreateDbContextAsync(ct))
            {
                var row = await db.SodDocuments.AsNoTracking().FirstOrDefaultAsync(d => d.Name == Observations, ct);
                var current = row is null ? null : JsonNode.Parse(row.Json) as JsonObject;
                if (current is not null && (string?)current["key"] == key && current["finding_ids"] is JsonArray seen && seen.Select(v => (string)v!).SequenceEqual(ids.Take(ObserveLimit)))
                    return current["change"]?.DeepClone();
            }
            var now = SodDecisionStore.Stamp(Service<TimeProvider>(services).GetUtcNow());
            return await Service<WriteCoordinator>(services).WriteAsync(async (db, token) =>
            {
                var row = await db.SodDocuments.FirstOrDefaultAsync(d => d.Name == Observations, token);
                var state = row is null ? new JsonObject() : JsonNode.Parse(row.Json) as JsonObject ?? [];
                var change = state["change"]?.DeepClone();
                if ((string?)state["key"] is { } previousKey && previousKey != key)
                {
                    if (!((bool?)state["truncated"] ?? false))
                    {
                        var before = (state["finding_ids"] as JsonArray ?? []).Select(v => (string)v!).ToHashSet(Ordinal);
                        var after = ids.ToHashSet(Ordinal);
                        change = new JsonObject
                        {
                            ["since"] = state["observed_at"]?.DeepClone(), ["new"] = after.Count(i => !before.Contains(i)), ["no_longer_detected"] = before.Count(i => !after.Contains(i)),
                            ["previous_total"] = before.Count, ["total"] = after.Count, ["observed_at"] = now,
                        };
                    }
                    else change = new JsonObject { ["unavailable"] = true, ["observed_at"] = now };
                }
                var next = new JsonObject
                {
                    ["key"] = key, ["observed_at"] = now, ["finding_ids"] = new JsonArray([.. ids.Take(ObserveLimit).Select(i => (JsonNode?)i)]), ["truncated"] = ids.Count > ObserveLimit,
                    ["change"] = change?.DeepClone(),
                };
                if (row is null) db.SodDocuments.Add(row = new SodDocument { Name = Observations, Json = "{}" });
                (row.Json, row.Revision, row.UpdatedUtc, row.UpdatedBy) = (next.ToJsonString(), row.Revision + 1, DateTime.UtcNow, "sod-observation");
                return change;
            }, ct);
        }
        catch (Exception error) when (error is not OperationCanceledException) { return null; }   // a failure here never affects the request
    }
}
