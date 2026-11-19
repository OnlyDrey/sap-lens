using System.Globalization;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;
using AuthLens.Application;
using AuthLens.Domain.Sod;
using AuthLens.Persistence;

namespace AuthLens.Api;

/// <summary>Port of routers/sod_governance.py decide, decision_history and decision_evidence for the live review context ("current"). Review periods are
/// not migrated: any other context answers 501. Decisions are attributed to an individual (Accounts-mode session or the Desktop reviewer profile, as v1's
/// actor()); a shared access token identifies no reviewer and is refused.</summary>
public static partial class V1SodDecisions
{
    public const string IdentityNotice = "Identity provenance is retained with events. Self-reported Desktop/legacy attribution is distinct from server identity; session-authenticated server actions retain account identity snapshots. This is not a digital signature.";
    private static readonly string[] Kinds = ["activity", "assignment", "acceptance", "risk"];
    private static readonly string[] BodyFields = ["context", "expected_revision", "expected_generation", "items", "decision", "reviewer", "approver", "justification", "controls", "expires"];
    private static readonly string[] ItemFields = ["key", "user", "ref", "evidence_version"];

    [GeneratedRegex("^[a-f0-9]{64}$")] private static partial Regex Hex64();
    [GeneratedRegex("^[a-f0-9]{32}$")] private static partial Regex Hex32();

    private static IResult Detail(int status, string detail) => Results.Json(new { detail }, statusCode: status);
    private static IResult Json(JsonNode node) => Results.Content(node.ToJsonString(), "application/json");
    private static IResult Errors(List<object> errors) => Results.Json(new { detail = errors }, statusCode: 422);

    /// <summary>The live analysis query of sod_scope.live_query (active validity, today).</summary>
    private static V1SodAnalysis.Query LiveQuery(string validity = "active", DateOnly? asOf = null) =>
        new("users", validity, asOf ?? DateOnly.FromDateTime(DateTime.Now), [], "", "", "", "", "", "", "", "", "", "", "", [], [], [], [], [], [], "subject", false);

    /// <summary>One review bundle (sod_scope.load) for the live context or a review period: evidence generation, conflict model and the review model
    /// with every assignment of the context's source cut.</summary>
    private sealed record Bundle(string Generation, DateOnly AsOf, string Validity, Dictionary<string, SodUserEntry> Model, Dictionary<string, SodUserEntry> Review,
        Dictionary<string, string> Versions, JsonObject Coverage, SodBundle Scope);

    private static async Task<(Bundle? Bundle, IResult? Error)> LoadAsync(IServiceProvider services, CancellationToken ct, string validity = "active", DateOnly? asOf = null, string context = "current")
    {
        SodBundle b;
        try { b = await SodScope.LoadAsync(services, context, validity, asOf, ct); }
        catch (SodDecisionException error) { return (null, Detail(error.Status, error.Message)); }
        return (new Bundle(b.Generation, DateOnly.ParseExact(b.AsOf, "yyyy-MM-dd", CultureInfo.InvariantCulture), validity, SodScope.Model(b), SodScope.ReviewModel(b), b.Versions, b.Coverage, b), null);
    }

    /// <summary>v1 actor(): the reviewer name and identity snapshot of this request, or the refusal when nobody individual is signed in.</summary>
    internal static async Task<(string? Name, JsonObject? Identity, IResult? Error)> AttributionAsync(HttpContext http, CancellationToken ct)
    {
        var actor = Actors.Current(http);
        if (actor.Provenance == "server-session")
            return (actor.Username, new JsonObject { ["id"] = actor.Id, ["username"] = actor.Username, ["display_name"] = actor.DisplayName, ["provenance"] = "server-session" }, null);
        if (actor.Provenance == "desktop")
        {
            var profile = await V1Configuration.EnsureProfileAsync(http.RequestServices.GetRequiredService<WriteCoordinator>(), http.RequestServices.GetRequiredService<TimeProvider>(), null, null, ct);
            var identity = profile["identity"]!.AsObject();
            return ((string)identity["display_name"]!, (JsonObject)identity.DeepClone(), null);
        }
        return (null, null, Detail(403, "SoD decisions need an individual sign-in. Enable Accounts mode for this server; a shared access token is not a reviewer identity."));
    }

    /// <summary>DecisionBody, validated as v1's strict request model.</summary>
    private static (JsonObject? Body, List<object> Errors) Validate(JsonObject body)
    {
        var errors = new List<object>();
        V1Validation.Extra(body, BodyFields, errors);
        if (body["context"] is not null && (body["context"]!.GetValueKind() != JsonValueKind.String || !SodDecisionStore.ContextPattern().IsMatch((string)body["context"]!)))
            errors.Add(V1Validation.Error("string_pattern_mismatch", "context", "String should match pattern '^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$'"));
        if (body["expected_revision"] is not JsonValue revision || revision.GetValueKind() != JsonValueKind.Number || !revision.TryGetValue<int>(out var number) || number < 0)
            errors.Add(V1Validation.Error(body.ContainsKey("expected_revision") ? "greater_than_equal" : "missing", "expected_revision", body.ContainsKey("expected_revision") ? "Input should be a valid integer greater than or equal to 0" : "Field required"));
        if (V1Validation.Text(body, "expected_generation", 64, 64, true, errors) is { } generation && !Hex64().IsMatch(generation))
            errors.Add(V1Validation.Error("string_pattern_mismatch", "expected_generation", "String should match pattern '^[a-f0-9]{64}$'"));
        V1Validation.Text(body, "decision", 0, 40, true, errors);
        V1Validation.Text(body, "reviewer", 0, 120, false, errors);
        V1Validation.Text(body, "approver", 0, 120, false, errors);
        V1Validation.Text(body, "justification", 1, 4000, true, errors);
        V1Validation.Text(body, "controls", 0, 8000, false, errors);
        if (body["expires"] is { } expires && (expires.GetValueKind() != JsonValueKind.String || !DateOnly.TryParseExact((string)expires!, "yyyy-MM-dd", CultureInfo.InvariantCulture, DateTimeStyles.None, out _)))
            errors.Add(V1Validation.Error("date_from_datetime_parsing", "expires", "Input should be a valid date"));
        if (body["items"] is not JsonArray items) errors.Add(V1Validation.Error(body.ContainsKey("items") ? "list_type" : "missing", "items", body.ContainsKey("items") ? "Input should be a valid list" : "Field required"));
        else if (items.Count is < 1 or > SodDecisionStore.MaxBatch)
            errors.Add(V1Validation.Error(items.Count < 1 ? "too_short" : "too_long", "items", items.Count < 1 ? "List should have at least 1 item after validation, not 0" : $"List should have at most {SodDecisionStore.MaxBatch} items after validation, not {items.Count}"));
        else
            for (var i = 0; i < items.Count; i++)
            {
                object[] path = ["items", i];
                if (items[i] is not JsonObject item) { errors.Add(V1Validation.Error("model_type", "", "Input should be a valid dictionary", path)); continue; }
                V1Validation.Extra(item, ItemFields, errors, path);
                foreach (var field in new[] { "key", "evidence_version" })
                    if (V1Validation.Text(item, field, 64, 64, true, errors, path) is { } hex && !Hex64().IsMatch(hex))
                        errors.Add(V1Validation.Error("string_pattern_mismatch", field, "String should match pattern '^[a-f0-9]{64}$'", path));
                V1Validation.Text(item, "user", 1, 512, true, errors, path);
                V1Validation.Text(item, "ref", 1, 512, true, errors, path);
            }
        return (errors.Count == 0 ? body : null, errors);
    }

    /// <summary>sod_scope.make_decision_verifier: source-bound verification of an explicit Remove; never rewrites its event.</summary>
    private static async Task<JsonObject> VerifyRemovalAsync(IServiceProvider services, JsonObject e, CancellationToken ct)
    {
        var snapshot = await services.GetRequiredService<SnapshotService>().GetAsync(ct);
        var settings = await services.GetRequiredService<V1Settings>().GetAsync(ct);
        var features = settings["features"];
        var reference = settings["data_lifecycle"]?["sources"]?["users"] as JsonObject;
        var user = (string)e["user"]!;
        string text;
        if (!((bool?)features?["sod"] ?? false) || !((bool?)features?["user_role_mapping"] ?? true) || snapshot.Catalogue.Roles.Count == 0 || snapshot.Sod is null)
            text = "Not assessable: current analysis is unavailable";
        else
        {
            var key = AuthLens.Domain.Roles.RoleNames.NormalizeUsername(user);
            var record = snapshot.Users.Users.GetValueOrDefault(key);
            var live = record?.Assignments.Select(a => SodGovernance.AssignmentId(key, a.RoleName, a.ValidFrom, a.ValidTo, a.UserGroup)).ToHashSet(StringComparer.Ordinal) ?? [];
            var complete = record is not null && snapshot.Users.InvalidCataloguePatterns == 0 && record.Assignments.Where(a => a.Scope != "other").All(a => a.Resolved);
            text = live.Contains((string)e["key"]!) ? "Still present in current evidence"
                : complete ? "Not present in current evidence" : "Not assessable: source coverage incomplete";
        }
        var result = new JsonObject
        {
            ["status"] = "Not verified", ["reason"] = text, ["source_version"] = reference?["snapshot"]?.DeepClone(), ["imported_at"] = reference?["imported_at"]?.DeepClone(),
            ["decision_event_id"] = e["event_id"]!.DeepClone(),
        };
        if ((string?)e["decision"] != "Remove" || text != "Not present in current evidence" || reference is null) return result;
        if (!DateTimeOffset.TryParse((string?)reference["imported_at"], CultureInfo.InvariantCulture, DateTimeStyles.None, out var imported)
            || !DateTimeOffset.TryParse((string?)e["timestamp"], CultureInfo.InvariantCulture, DateTimeStyles.None, out var decided)) return result;
        if (imported > decided && (string?)reference["snapshot"] != (string?)e["source_versions"]?["users"])
        {
            result["status"] = "Verified";
            result["reason"] = "Assignment absent from a newer validated User–Role snapshot with complete matching coverage for this user.";
        }
        else result["reason"] = "Awaiting a newer validated User–Role source snapshot.";
        return result;
    }

    /// <summary>governance.assignment_confirmation: the confirmed row from the persisted event, with the canonical lifecycle and coverage rules.</summary>
    private static JsonObject Confirmation(SodAssignment assignment, SodDecisionEvent e)
    {
        var entry = new SodUserEntry { User = e.User };
        entry.Assignments[assignment.Id] = assignment;
        var latest = new Dictionary<string, IReadOnlyDictionary<string, SodDecisionEvent>>(StringComparer.Ordinal)
        {
            ["assignment"] = new Dictionary<string, SodDecisionEvent>(StringComparer.Ordinal) { [e.Key] = e },
        };
        var state = SodGovernance.States(new Dictionary<string, SodUserEntry>(StringComparer.Ordinal) { [e.User] = entry }, latest, DateOnly.FromDateTime(DateTime.Now));
        return new JsonObject
        {
            ["decision"] = state.Items["assignment"][e.Key].Lifecycle, ["event"] = e.ToJson(),
            ["decision_summary"] = SodGovernance.EffectiveDecision(entry, state, "assignment", e.Key), ["review_coverage"] = state.Coverage["assignment"][e.Key].DeepClone(),
        };
    }

    /// <summary>scope.states_for: frozen periods keep their approval-date lifecycle; live and open contexts use today and the reappearance memory.</summary>
    private static Task<SodStates> StatesAsync(IServiceProvider services, Bundle bundle, IReadOnlyDictionary<string, SodUserEntry> model, CancellationToken ct) =>
        SodScope.StatesAsync(services, bundle.Scope, model, ct);

    private static Task<JsonObject> InfoAsync(IServiceProvider services, Bundle bundle, CancellationToken ct) => SodScope.InfoAsync(services, bundle.Scope, ct);

    /// <summary>A decision for a period commits only while that period is still open (Draft or In review) on the snapshot the reviewer saw.</summary>
    private static async Task PeriodStillOpenAsync(IServiceProvider services, string context, string generation, CancellationToken ct)
    {
        var period = SodPeriodStore.Find(await services.GetRequiredService<SodPeriodStore>().ReadAsync(ct), context);
        if ((string)period["state"]! is not ("Draft" or "In review")) throw new SodDecisionException(409, ReadOnlyContext);
        if ((string?)period["snapshot"] != generation) throw new SodDecisionException(409, "SoD evidence changed. Reload before reviewing.");
    }

    private const string ReadOnlyContext = "This context accepts no decisions. Frozen periods and non-current evidence are read-only.";

    private static JsonNode? EventJson(SodItemState item) => item.Event?.ToJson();
    private static JsonArray List(IEnumerable<string> values) => new([.. values.Select(v => (JsonNode?)JsonValue.Create(v))]);

    /// <summary>routers.sod_governance.subject: the investigation workspace of one user (evidence path, decisions, history pointers, removal impact).</summary>
    private static async Task<IResult> SubjectAsync(HttpContext http, CancellationToken ct)
    {
        var q = http.Request.Query;
        var context = q["context"].FirstOrDefault() ?? "current";
        var validity = q["validity"].FirstOrDefault() ?? "active";
        var user = q["user"].FirstOrDefault();
        var risk = q["risk"].FirstOrDefault() ?? "";
        var activity = q["activity"].FirstOrDefault() ?? "";
        DateOnly? asOf = null;
        if (q["as_of"].FirstOrDefault() is { Length: > 0 } text)
        {
            if (!DateOnly.TryParseExact(text, "yyyy-MM-dd", CultureInfo.InvariantCulture, DateTimeStyles.None, out var parsed)) return Errors([V1Validation.At("date_from_datetime_parsing", "Input should be a valid date", "query", "as_of")]);
            asOf = parsed;
        }
        if (user is null) return Errors([V1Validation.At("missing", "Field required", "query", "user")]);
        if (user.Length > 512 || risk.Length > 512 || activity.Length > 512 || !SodDecisionStore.ContextPattern().IsMatch(context) || validity is not ("active" or "expired" or "future" or "unknown" or "all"))
            return Errors([V1Validation.At("value_error", "Invalid subject query.", "query")]);
        var services = http.RequestServices;
        var (bundle, loadError) = await LoadAsync(services, ct, validity, asOf, context);
        if (loadError is not null) return loadError;
        var model = bundle!.Review;
        if (!model.TryGetValue(user, out var entry)) return Detail(404, "The SAP user has no detected conflict evidence in this context.");
        var state = await StatesAsync(services, bundle, model, ct);
        if (risk.Length > 0 && !entry.Findings.ContainsKey(risk)) return Detail(404, "The risk is not detected for this user in this context.");
        if (activity.Length > 0 && !entry.Activities.ContainsKey(activity)) return Detail(404, "The activity is not evidenced for this user in this context.");
        var names = entry.Activities.Where(p => (risk.Length == 0 || p.Value.Risks.Contains(risk)) && (activity.Length == 0 || p.Key == activity)).Select(p => p.Key).Order(StringComparer.Ordinal).ToList();

        var rows = new JsonArray();
        foreach (var name in names)
        {
            var detail = SodGovernance.ActivityDetail(entry, name)!;
            var item = state.Items["activity"][(string)detail["key"]!];
            foreach (var assignment in detail["assignments"]!.AsArray().Select(a => a!.AsObject()))
            {
                var a = state.Items["assignment"][(string)assignment["id"]!];
                assignment["decision"] = a.Lifecycle;
                assignment["event"] = EventJson(a);
            }
            detail["decision"] = item.Lifecycle;
            detail["event"] = EventJson(item);
            rows.Add(detail);
        }
        var finding = risk.Length > 0 ? entry.Findings[risk] : null;
        JsonNode? riskInfo = null;
        if (finding is not null)
        {
            var id = (string)finding["finding_id"]!;
            var definition = finding["risk"] as JsonObject;
            var sides = new JsonObject();
            foreach (var (side, paths) in finding["evidence"]!.AsObject()) sides[side] = List(paths!.AsArray().Select(p => (string)p!["activity"]!).Distinct().Order(StringComparer.Ordinal));
            // Legacy risk decisions (sod_reviews) are not migrated: none exist in this store.
            riskInfo = new JsonObject
            {
                ["risk_id"] = risk, ["criticality"] = finding["criticality"]?.DeepClone(), ["display_name"] = (string?)definition?["display_name"] ?? "", ["source_text"] = (string?)definition?["source_text"] ?? "",
                ["category"] = (string?)definition?["business_category"] ?? "", ["risk_type"] = (string?)definition?["risk_type"] ?? "", ["finding_id"] = id,
                ["evidence_version"] = finding["evidence_version"]?.DeepClone(), ["sides"] = sides, ["acceptance"] = state.Items["acceptance"][id].Lifecycle,
                ["event"] = EventJson(state.Items["acceptance"][id]), ["legacy_decisions"] = new JsonArray(),
            };
        }
        var related = names.Count > 0 ? List(names.SelectMany(n => entry.Activities[n].Risks).Where(r => r != risk).Distinct().Order(StringComparer.Ordinal)) : new JsonArray();
        JsonNode? impact = null;
        if (finding is not null)
        {
            var mapping = entry.Activities.Values.ToDictionary(a => a.Name, a => state.Items["activity"][a.Key].Lifecycle, StringComparer.Ordinal);
            var perAssignment = new JsonObject();
            foreach (var aid in names.SelectMany(n => entry.Activities[n].Assignments)) perAssignment[aid] = SodGovernance.SingleAssignmentImpact(entry, aid, mapping);
            impact = new JsonObject { ["options"] = SodGovernance.RemovalOptions(entry, risk, mapping), ["per_assignment"] = perAssignment };
        }

        var activities = new JsonArray();
        foreach (var (name, a) in entry.Activities.OrderBy(p => p.Key, StringComparer.Ordinal))
        {
            var item = state.Items["activity"][a.Key];
            var row = new JsonObject
            {
                ["activity"] = name, ["key"] = a.Key, ["decision"] = item.Lifecycle, ["event"] = EventJson(item), ["evidence_version"] = a.EvidenceVersion, ["risks"] = List(a.Risks),
                ["tcodes"] = List(a.Tcodes), ["roles"] = a.Assignments.Count, ["duplicate_coverage"] = a.Assignments.Count > 1,
                ["review_coverage"] = state.Coverage["activity"][a.Key].DeepClone(), ["decision_summary"] = SodGovernance.DecisionSummary(entry, state, "activity", a.Key),
            };
            activities.Add(row);
        }
        var assignments = new JsonArray();
        var anyRemove = false;
        foreach (var a in entry.Assignments.Values.OrderBy(x => x.Role.PyCasefold(), StringComparer.Ordinal).ThenBy(x => x.Id, StringComparer.Ordinal))
        {
            var item = state.Items["assignment"][a.Id];
            anyRemove |= item.Event?.Decision == "Remove";
            assignments.Add(new JsonObject
            {
                ["id"] = a.Id, ["role"] = a.Role, ["decision"] = item.Lifecycle, ["event"] = EventJson(item), ["evidence_version"] = a.EvidenceVersion, ["risks"] = List(a.Risks),
                ["activities"] = List(a.Supplies.Keys), ["valid_from"] = a.ValidFrom, ["valid_to"] = a.ValidTo, ["interval_status"] = a.IntervalStatus, ["user_group"] = a.UserGroup,
                ["catalogue_roles"] = List(a.CatalogueRoles), ["review_coverage"] = state.Coverage["assignment"][a.Id].DeepClone(),
                ["decision_summary"] = SodGovernance.DecisionSummary(entry, state, "assignment", a.Id),
            });
        }
        if (anyRemove)
            foreach (var row in assignments.Select(r => r!.AsObject()).Where(r => (string?)r["event"]?["decision"] == "Remove"))
            {
                var verification = await VerifyRemovalAsync(services, row["event"]!.AsObject(), ct);
                if ((string?)verification["source_version"] != bundle.Versions.GetValueOrDefault("users"))
                {
                    verification["status"] = "Not verified";
                    verification["reason"] = "Source changed while reading; reload before assessing verification.";
                }
                row["remediation_verification"] = verification;
            }
        var risks = new JsonArray();
        foreach (var (riskId, f) in entry.Findings.OrderBy(p => p.Key, StringComparer.Ordinal))
        {
            var id = (string)f["finding_id"]!;
            var definition = f["risk"] as JsonObject;
            var acceptance = state.Items["acceptance"][id];
            var review = state.Items["risk"][id];
            risks.Add(new JsonObject
            {
                ["risk_id"] = riskId, ["criticality"] = f["criticality"]?.DeepClone(), ["display_name"] = (string?)definition?["display_name"] ?? "", ["source_text"] = (string?)definition?["source_text"] ?? "",
                ["finding_id"] = id, ["evidence_version"] = f["evidence_version"]?.DeepClone(), ["acceptance"] = acceptance.Lifecycle, ["event"] = EventJson(acceptance),
                ["review_coverage"] = state.Coverage["acceptance"][id].DeepClone(), ["decision_summary"] = SodGovernance.DecisionSummary(entry, state, "acceptance", id),
                ["risk_review_summary"] = SodGovernance.EffectiveDecision(entry, state, "risk", id), ["risk_review"] = review.Lifecycle, ["risk_review_event"] = EventJson(review),
            });
        }
        var result = await InfoAsync(services, bundle, ct);
        result["user"] = user;
        result["groups"] = List(entry.Groups);
        result["account"] = entry.Account?.DeepClone();
        result["risk"] = riskInfo;
        result["activities"] = rows;
        result["related_risks"] = related;
        result["impact"] = impact;
        result["overview"] = new JsonObject { ["activities"] = activities, ["assignments"] = assignments, ["risks"] = risks };
        return Json(result);
    }

    private static readonly string[] ActionFields = ["context", "expected_revision", "actor", "action_id", "user", "activity", "risk_id", "assignment_id", "role", "recommended", "reason",
        "owner", "due_date", "status", "completion_evidence"];
    private static readonly string[] BulkFields = ["context", "expected_revision", "expected_generation", "items", "action", "reviewer", "justification", "replace_existing", "atomic", "track_action"];
    public const int BulkMax = 1000;
    /// <summary>Current, completed assignment decisions: replacing one needs explicit confirmation; Pending, Investigate and Outdated reviews do not.</summary>
    private static readonly string[] Protected = ["Keep", "Removal required"];

    private static bool? Bool(JsonObject body, string field, List<object> errors)
    {
        if (!body.TryGetPropertyValue(field, out var node) || node is null) return false;
        if (node.GetValueKind() is JsonValueKind.True or JsonValueKind.False) return (bool)node;
        errors.Add(V1Validation.Error("bool_type", field, "Input should be a valid boolean"));
        return null;
    }

    private static void Revision(JsonObject body, List<object> errors)
    {
        if (body["expected_revision"] is not JsonValue revision || revision.GetValueKind() != JsonValueKind.Number || !revision.TryGetValue<int>(out var number) || number < 0)
            errors.Add(V1Validation.Error(body.ContainsKey("expected_revision") ? "greater_than_equal" : "missing", "expected_revision", body.ContainsKey("expected_revision") ? "Input should be a valid integer greater than or equal to 0" : "Field required"));
    }

    /// <summary>POST /api/sod/remediation/actions (routers.sod_governance.save_action): tracks a remediation action; completion is a manual claim.</summary>
    private static async Task<IResult> SaveActionAsync(HttpContext http, SodDecisionStore store, CancellationToken ct)
    {
        var (raw, readError) = await V1Validation.ReadBody(http, ct);
        if (readError is not null) return readError;
        var body = raw!;
        var errors = new List<object>();
        V1Validation.Extra(body, ActionFields, errors);
        Revision(body, errors);
        if (body["context"] is not null && (body["context"]!.GetValueKind() != JsonValueKind.String || !SodDecisionStore.ContextPattern().IsMatch((string)body["context"]!)))
            errors.Add(V1Validation.Error("string_pattern_mismatch", "context", "String should match pattern '^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$'"));
        V1Validation.Text(body, "actor", 1, 120, true, errors);
        V1Validation.Text(body, "action_id", 0, 32, false, errors);
        V1Validation.Text(body, "user", 1, 512, true, errors);
        foreach (var (field, max) in new[] { ("activity", 512), ("risk_id", 512), ("assignment_id", 64), ("role", 512), ("owner", 120), ("completion_evidence", 4000) })
            V1Validation.Text(body, field, 0, max, false, errors);
        V1Validation.Text(body, "reason", 1, 4000, true, errors);
        if (V1Validation.Text(body, "recommended", 0, 40, true, errors) is { } recommended && !SodDecisionStore.Recommended.Contains(recommended))
            errors.Add(V1Validation.Error("literal_error", "recommended", "Input should be " + string.Join(", ", SodDecisionStore.Recommended.Select(r => $"'{r}'"))));
        if (body.ContainsKey("status") && (V1Validation.Text(body, "status", 0, 20, true, errors) is not { } status || !SodDecisionStore.ActionStatuses.Contains(status)))
            errors.Add(V1Validation.Error("literal_error", "status", "Input should be 'Open', 'In progress', 'Completed' or 'Cancelled'"));
        if (body["due_date"] is { } due && (due.GetValueKind() != JsonValueKind.String || !DateOnly.TryParseExact((string)due!, "yyyy-MM-dd", CultureInfo.InvariantCulture, DateTimeStyles.None, out _)))
            errors.Add(V1Validation.Error("date_from_datetime_parsing", "due_date", "Input should be a valid date"));
        if (errors.Count > 0) return Errors(errors);
        var context = (string?)body["context"] ?? "current";
        var (name, identity, refused) = await AttributionAsync(http, ct);
        if (refused is not null) return refused;
        var (bundle, loadError) = await LoadAsync(http.RequestServices, ct, context: context);
        if (loadError is not null) return loadError;
        if (bundle!.Scope.Frozen) return Detail(409, "Frozen periods retain their remediation actions unchanged. Track follow-up in current evidence.");
        var user = (string)body["user"]!;
        var assignment = (string?)body["assignment_id"] ?? "";
        if (!bundle!.Review.TryGetValue(user, out var entry) || (assignment.Length > 0 && !entry.Assignments.ContainsKey(assignment)))
            return Detail(409, "The action refers to evidence that is not present in this context.");
        var values = new JsonObject();
        foreach (var field in new[] { "user", "activity", "risk_id", "assignment_id", "role", "recommended", "reason", "owner", "completion_evidence" }) values[field] = (string?)body[field] ?? "";
        values["due_date"] = body["due_date"]?.DeepClone();
        values["status"] = (string?)body["status"] ?? "Open";
        try
        {
            var (action, revision) = await store.SaveActionAsync(context, values, name!, identity, (int)body["expected_revision"]!, (string?)body["action_id"] ?? "", null, ct);
            return Json(new JsonObject { ["action"] = action, ["revision"] = revision });
        }
        catch (SodDecisionException error) { return Detail(error.Status, error.Message); }
    }

    /// <summary>POST /api/sod/decisions/assignment/bulk (_bulk_assignment_review): one event per assignment with the individual decision checks, completed
    /// decisions protected unless replace_existing, each outcome reported per assignment. Non-atomic runs commit in chunks of 100: a chunk that fails is
    /// reported as failed (never as skipped) and earlier chunks stay recorded, as v1. Atomic runs refuse everything when anything is skipped or failed.</summary>
    private static async Task<IResult> BulkAsync(HttpContext http, SodDecisionStore store, CancellationToken ct)
    {
        var (raw, readError) = await V1Validation.ReadBody(http, ct);
        if (readError is not null) return readError;
        var body = raw!;
        var errors = new List<object>();
        V1Validation.Extra(body, BulkFields, errors);
        Revision(body, errors);
        if (body["context"] is not null && (body["context"]!.GetValueKind() != JsonValueKind.String || !SodDecisionStore.ContextPattern().IsMatch((string)body["context"]!)))
            errors.Add(V1Validation.Error("string_pattern_mismatch", "context", "String should match pattern '^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$'"));
        if (V1Validation.Text(body, "expected_generation", 64, 64, true, errors) is { } generationText && !Hex64().IsMatch(generationText))
            errors.Add(V1Validation.Error("string_pattern_mismatch", "expected_generation", "String should match pattern '^[a-f0-9]{64}$'"));
        if (V1Validation.Text(body, "action", 0, 20, true, errors) is { } actionText && actionText is not ("Keep" or "Remove" or "Investigate"))
            errors.Add(V1Validation.Error("literal_error", "action", "Input should be 'Keep', 'Remove' or 'Investigate'"));
        V1Validation.Text(body, "reviewer", 0, 120, false, errors);
        V1Validation.Text(body, "justification", 1, 4000, true, errors);
        var replace = Bool(body, "replace_existing", errors);
        var atomic = Bool(body, "atomic", errors);
        var track = Bool(body, "track_action", errors);
        if (body["items"] is not JsonArray list) errors.Add(V1Validation.Error(body.ContainsKey("items") ? "list_type" : "missing", "items", body.ContainsKey("items") ? "Input should be a valid list" : "Field required"));
        else if (list.Count is < 1 or > BulkMax)
            errors.Add(V1Validation.Error(list.Count < 1 ? "too_short" : "too_long", "items", list.Count < 1 ? "List should have at least 1 item after validation, not 0" : $"List should have at most {BulkMax} items after validation, not {list.Count}"));
        else
            for (var i = 0; i < list.Count; i++)
            {
                object[] path = ["items", i];
                if (list[i] is not JsonObject item) { errors.Add(V1Validation.Error("model_type", "", "Input should be a valid dictionary", path)); continue; }
                V1Validation.Extra(item, ItemFields, errors, path);
                foreach (var field in new[] { "key", "evidence_version" })
                    if (V1Validation.Text(item, field, 64, 64, true, errors, path) is { } hex && !Hex64().IsMatch(hex))
                        errors.Add(V1Validation.Error("string_pattern_mismatch", field, "String should match pattern '^[a-f0-9]{64}$'", path));
                V1Validation.Text(item, "user", 1, 512, true, errors, path);
                V1Validation.Text(item, "ref", 1, 512, true, errors, path);
            }
        if (errors.Count > 0) return Errors(errors);
        var context = (string?)body["context"] ?? "current";
        var (name, identity, refused) = await AttributionAsync(http, ct);
        if (refused is not null) return refused;
        var services = http.RequestServices;
        var (bundle, loadError) = await LoadAsync(services, ct, context: context);
        if (loadError is not null) return loadError;
        if (!bundle!.Scope.Reviewable) return Detail(409, ReadOnlyContext);
        var expectedGeneration = (string)body["expected_generation"]!;
        if (bundle!.Generation != expectedGeneration) return Detail(409, "SoD evidence changed. Reload before reviewing.");
        var items = body["items"]!.AsArray().Select(i => i!.AsObject()).ToList();
        if (items.Select(i => (string)i["key"]!).Distinct(StringComparer.Ordinal).Count() != items.Count) return Detail(422, "Each assignment may be listed once.");
        if (atomic == true && track == true) return Detail(422, "Atomic assignment review does not support separate action mutations.");
        var action = (string)body["action"]!;
        var operationId = Guid.NewGuid().ToString("N");
        var model = bundle.Review;
        var state = await StatesAsync(services, bundle, model, ct);
        var tracked = (await store.ActionsAsync(context, ct)).Where(a => (string?)a["assignment_id"] is { Length: > 0 } && (string?)a["status"] != "Cancelled" && (string?)a["recommended"] == "Investigate assignment")
            .Select(a => (string)a["assignment_id"]!).ToHashSet(StringComparer.Ordinal);
        JsonObject Outcome(string key, string user, string reference, string reason) => new() { ["key"] = key, ["user"] = user, ["ref"] = reference, ["reason"] = reason };
        var ready = new List<SodDecisionItem>();
        var skipped = new JsonArray();
        var failed = new JsonArray();
        foreach (var item in items)
        {
            var (key, user, reference, version) = ((string)item["key"]!, (string)item["user"]!, (string)item["ref"]!, (string)item["evidence_version"]!);
            var located = SodGovernance.Locate(model, "assignment", user, key, reference);
            if (located is not { } found || found.Key != key) { failed.Add(Outcome(key, user, reference, "No longer supported by current evidence.")); continue; }
            if (found.EvidenceVersion != version) { failed.Add(Outcome(key, user, reference, "Evidence changed since the selection was made.")); continue; }
            var current = state.Items["assignment"][key];
            if (action == "Investigate" && current.Lifecycle == "Investigate") { skipped.Add(Outcome(key, user, reference, "Already under investigation.")); continue; }
            var isProtected = Protected.Contains(current.Lifecycle) || (atomic == true && current.Event is not null && current.Event.Decision != "Pending");
            if (isProtected && replace != true) { skipped.Add(Outcome(key, user, reference, $"Already reviewed ({current.Lifecycle}); replacing needs explicit confirmation.")); continue; }
            ready.Add(new SodDecisionItem(key, user, reference, found.EvidenceVersion, found.Evidence));
        }
        var recorded = new JsonArray();
        var newActions = new JsonArray();
        var revision = (int)body["expected_revision"]!;
        var justification = (string)body["justification"]!;
        async Task Guard(CancellationToken token)
        {
            if (context != "current") { await PeriodStillOpenAsync(services, context, expectedGeneration, token); return; }
            var (now, _) = await V1SodAnalysis.CaptureAsync(services, LiveQuery(), token);
            if (now?.Generation != expectedGeneration) throw new SodDecisionException(409, "SoD source evidence changed. Reload before saving.");
        }
        async Task Apply(List<SodDecisionItem> chunk)
        {
            revision = (await store.RecordAsync(new SodRecordRequest("assignment", context, chunk, action, name!, justification, revision, SourceVersions: bundle.Versions,
                BulkOperationId: operationId, ActorIdentity: identity), Guard, ct)).Revision;
            if (action == "Investigate" && track == true)
                foreach (var item in chunk)
                {
                    if (tracked.Contains(item.Key)) continue;
                    var values = new JsonObject
                    {
                        ["user"] = item.User, ["assignment_id"] = item.Key, ["role"] = item.Ref, ["recommended"] = "Investigate assignment", ["reason"] = justification, ["owner"] = "",
                        ["due_date"] = null, ["status"] = "Open", ["completion_evidence"] = "", ["activity"] = "", ["risk_id"] = "",
                    };
                    revision = (await store.SaveActionAsync(context, values, name!, identity, revision, "", null, ct)).Revision;
                    newActions.Add(item.Key);
                    tracked.Add(item.Key);
                }
        }
        try
        {
            if (atomic == true)
            {
                if (failed.Count > 0 || skipped.Count > 0 || ready.Count == 0)
                    return Detail(409, "The preview selection changed or includes protected decisions. Reload before reviewing; nothing was saved.");
                await Apply(ready);
                foreach (var item in ready) recorded.Add(item.Key);
            }
            else
                for (var start = 0; start < ready.Count; start += SodDecisionStore.MaxBatch)
                {
                    var chunk = ready.Skip(start).Take(SodDecisionStore.MaxBatch).ToList();
                    try
                    {
                        await Apply(chunk);
                        foreach (var item in chunk) recorded.Add(item.Key);
                    }
                    catch (SodDecisionException error)
                    {
                        if (error.Status == 409 && recorded.Count == 0 && start == 0 && error.Message.Contains("decisions changed", StringComparison.Ordinal)) throw;
                        foreach (var item in chunk) failed.Add(Outcome(item.Key, item.User, item.Ref, error.Message));
                    }
                }
        }
        catch (SodDecisionException error) { return Detail(error.Status, error.Message); }
        return Json(new JsonObject
        {
            ["operation_id"] = operationId, ["action"] = action, ["recorded"] = recorded, ["skipped"] = skipped, ["failed"] = failed, ["tracked_actions"] = newActions,
            ["revision"] = revision, ["reviewer_identity"] = IdentityNotice,
        });
    }

    /// <summary>GET /api/sod/review-subjects: the requested SAP identities present in the review model (batched, independent of page filters).</summary>
    private static async Task<IResult> ReviewSubjectsAsync(HttpContext http, CancellationToken ct)
    {
        var q = http.Request.Query;
        var context = q["context"].FirstOrDefault() ?? "current";
        if (!SodDecisionStore.ContextPattern().IsMatch(context)) return Errors([V1Validation.At("string_pattern_mismatch", "String should match pattern '^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$'", "query", "context")]);
        if (q["usernames"].Count > 200) return Errors([V1Validation.At("too_long", $"List should have at most 200 items after validation, not {q["usernames"].Count}", "query", "usernames")]);
        var (bundle, loadError) = await LoadAsync(http.RequestServices, ct, context: context);
        if (loadError is not null) return loadError;
        var result = await InfoAsync(http.RequestServices, bundle!, ct);
        result["users"] = List(q["usernames"].OfType<string>().Where(bundle!.Review.ContainsKey).Distinct(StringComparer.Ordinal).Order(StringComparer.Ordinal));
        return Json(result);
    }

    /// <summary>POST /api/sod/simulate: read-only what-if over a copy of the evidence; imported data and decisions are untouched.</summary>
    private static async Task<IResult> SimulateAsync(HttpContext http, CancellationToken ct)
    {
        var (raw, readError) = await V1Validation.ReadBody(http, ct);
        if (readError is not null) return readError;
        var body = raw!;
        var errors = new List<object>();
        V1Validation.Extra(body, ["context", "user", "removed"], errors);
        if (body["context"] is not null && (body["context"]!.GetValueKind() != JsonValueKind.String || !SodDecisionStore.ContextPattern().IsMatch((string)body["context"]!)))
            errors.Add(V1Validation.Error("string_pattern_mismatch", "context", "String should match pattern '^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$'"));
        V1Validation.Text(body, "user", 1, 512, true, errors);
        var removed = new List<string>();
        if (body.TryGetPropertyValue("removed", out var node) && node is not null)
        {
            if (node is not JsonArray list || list.Any(v => v?.GetValueKind() != JsonValueKind.String)) errors.Add(V1Validation.Error("list_type", "removed", "Input should be a valid list of strings"));
            else if (list.Count > 200) errors.Add(V1Validation.Error("too_long", "removed", $"List should have at most 200 items after validation, not {list.Count}"));
            else removed = list.Select(v => (string)v!).ToList();
        }
        if (errors.Count > 0) return Errors(errors);
        var context = (string?)body["context"] ?? "current";
        var (bundle, loadError) = await LoadAsync(http.RequestServices, ct, context: context);
        if (loadError is not null) return loadError;
        var user = (string)body["user"]!;
        if (!bundle!.Model.TryGetValue(user, out var entry)) return Detail(404, "The SAP user has no detected conflict evidence in this context.");
        var state = await StatesAsync(http.RequestServices, bundle, bundle.Model, ct);
        var mapping = entry.Activities.Values.ToDictionary(a => a.Name, a => state.Items["activity"][a.Key].Lifecycle, StringComparer.Ordinal);
        JsonObject simulation;
        try { simulation = SodGovernance.SimulateJson(entry, removed.ToHashSet(StringComparer.Ordinal), mapping); }
        catch (ArgumentException error) { return Detail(422, error.Message); }
        var result = await InfoAsync(http.RequestServices, bundle, ct);
        result["user"] = user;
        foreach (var (k, v) in simulation) result[k] = v?.DeepClone();
        result["policy"] = SodSource.EvaluationPolicy;
        result["note"] = "Simulation only: AuthLens does not change SAP. A removal recommendation is not confirmed removal.";
        return Json(result);
    }

    /// <summary>POST /api/storage/lifecycle/rebaseline (routers/storage.rebaseline): an administrator acknowledges the current imported data as the continuity
    /// baseline after the lifecycle memory was damaged, lost or rolled back; earlier assignment decisions then apply again (their history is untouched).
    /// Administrator permission comes from the session boundary (v1 admin()); the acknowledgement is attributed to an individual, never a shared token.</summary>
    private static async Task<IResult> RebaselineAsync(HttpContext http, CancellationToken ct)
    {
        var (raw, readError) = await V1Validation.ReadBody(http, ct);
        if (readError is not null) return readError;
        var errors = new List<object>();
        V1Validation.Extra(raw!, ["confirm"], errors);
        if (raw!["confirm"] is not JsonValue confirm || confirm.GetValueKind() is not (JsonValueKind.True or JsonValueKind.False))
            errors.Add(V1Validation.Error(raw.ContainsKey("confirm") ? "bool_type" : "missing", "confirm", raw.ContainsKey("confirm") ? "Input should be a valid boolean" : "Field required"));
        if (errors.Count > 0) return Errors(errors);
        if (!(bool)raw["confirm"]!) return Detail(422, "Confirm that the current imported data may serve as the continuity baseline.");
        var (name, _, refused) = await AttributionAsync(http, ct);
        if (refused is not null) return refused;
        var lifecycle = http.RequestServices.GetRequiredService<AssignmentLifecycle>();
        await lifecycle.RebaselineAsync(name!, ct);
        var factory = http.RequestServices.GetRequiredService<Microsoft.EntityFrameworkCore.IDbContextFactory<AuthLensDb>>();
        await using var db = await factory.CreateDbContextAsync(ct);
        var (_, state, detail) = await AssignmentLifecycle.LoadAsync(db, ct);
        return Json(new JsonObject { ["review_continuity"] = new JsonObject { ["state"] = state, ["detail"] = detail } });
    }

    public static void Map(RouteGroupBuilder api)
    {
        api.MapPost("/sod/decisions/{kind}", async (string kind, HttpContext http, SodDecisionStore store, CancellationToken ct) =>
        {
            if (!Kinds.Contains(kind)) return Errors([V1Validation.At("literal_error", "Input should be 'activity', 'assignment', 'acceptance' or 'risk'", "path", "kind")]);
            var (raw, readError) = await V1Validation.ReadBody(http, ct);
            if (readError is not null) return readError;
            var (body, errors) = Validate(raw!);
            if (body is null) return Errors(errors);
            var decision = (string)body["decision"]!;
            if (!SodGovernance.Decisions[kind].Contains(decision)) return Detail(422, "Choose a decision supported by this review type.");
            var context = (string?)body["context"] ?? "current";
            var (name, identity, refused) = await AttributionAsync(http, ct);
            if (refused is not null) return refused;

            var (bundle, loadError) = await LoadAsync(http.RequestServices, ct, context: context);
            if (loadError is not null) return loadError;
            if (!bundle!.Scope.Reviewable) return Detail(409, ReadOnlyContext);
            var expectedGeneration = (string)body["expected_generation"]!;
            if (bundle!.Generation != expectedGeneration) return Detail(409, "SoD evidence changed. Reload before reviewing.");
            var model = kind == "assignment" ? bundle.Review : bundle.Model;
            var items = new List<SodDecisionItem>();
            foreach (var item in body["items"]!.AsArray().Select(i => i!.AsObject()))
            {
                var (key, user, reference, version) = ((string)item["key"]!, (string)item["user"]!, (string)item["ref"]!, (string)item["evidence_version"]!);
                var located = SodGovernance.Locate(model, kind, user, key, reference);
                if (located is not { } found || found.Key != key) return Detail(409, "A selected item is no longer supported by current evidence. Reload before reviewing.");
                if (found.EvidenceVersion != version) return Detail(409, "Evidence for a selected item changed. Reload before reviewing.");
                items.Add(new SodDecisionItem(key, user, reference, found.EvidenceVersion, found.Evidence));
            }
            // Desktop and Server attribute reviewer and (for a non-pending acceptance) approver to the signed-in individual, as v1's actor().
            var approver = kind == "acceptance" && decision != "Pending" ? name! : (string?)body["approver"] ?? "";
            var request = new SodRecordRequest(kind, context, items, decision, name!, (string)body["justification"]!, (int)body["expected_revision"]!, approver,
                (string?)body["controls"] ?? "", (string?)body["expires"], bundle.Versions, ActorIdentity: identity);
            SodRecordResult result;
            try
            {
                result = await store.RecordAsync(request, async token =>
                {
                    // publication_guard: the evidence generation must still be the one the reviewer saw when the decision commits; a period must still be open.
                    if (context == "current")
                    {
                        var (now, _) = await V1SodAnalysis.CaptureAsync(http.RequestServices, LiveQuery(), token);
                        if (now?.Generation != expectedGeneration) throw new SodDecisionException(409, "SoD source evidence changed. Reload before saving.");
                    }
                    else await PeriodStillOpenAsync(http.RequestServices, context, expectedGeneration, token);
                }, ct);
            }
            catch (SodDecisionException error) { return Detail(error.Status, error.Message); }
            var response = new JsonObject
            {
                ["events"] = new JsonArray([.. result.Events.Select(e => (JsonNode?)e.ToJson())]), ["revision"] = result.Revision, ["reviewer_identity"] = IdentityNotice,
            };
            if (kind == "assignment")
            {
                var confirmed = new JsonObject();
                foreach (var e in result.Events) confirmed[e.Key] = Confirmation(model[e.User].Assignments[e.Key], e);
                response["confirmed_assignments"] = confirmed;
            }
            return Json(response);
        });

        api.MapGet("/sod/subject", SubjectAsync);
        api.MapPost("/sod/remediation/actions", SaveActionAsync);
        api.MapGet("/sod/review-subjects", ReviewSubjectsAsync);
        api.MapPost("/sod/simulate", SimulateAsync);
        api.MapPost("/storage/lifecycle/rebaseline", RebaselineAsync);
        api.MapPost("/sod/decisions/assignment/bulk", BulkAsync);

        api.MapGet("/sod/decisions/{kind}/history", async (string kind, HttpContext http, SodDecisionStore store, CancellationToken ct) =>
        {
            var q = http.Request.Query;
            var key = q["key"].FirstOrDefault();
            var context = q["context"].FirstOrDefault() ?? "current";
            if (!Kinds.Contains(kind) || key is null || !Hex64().IsMatch(key) || !SodDecisionStore.ContextPattern().IsMatch(context))
                return Errors([V1Validation.At("value_error", "Invalid review item, kind or context.", "query")]);
            List<JsonObject> items;
            try { items = await store.HistoryAsync(kind, context, key, ct); }
            catch (SodDecisionException error) { return Detail(error.Status, error.Message); }
            JsonNode? verification = context == "current" && kind == "assignment" && items.Count > 0 && (string?)items[0]["decision"] == "Remove" ? await VerifyRemovalAsync(http.RequestServices, items[0], ct) : null;
            return Json(new JsonObject { ["items"] = new JsonArray([.. items]), ["verification"] = verification, ["reviewer_identity"] = IdentityNotice });
        });

        api.MapGet("/sod/decisions/{kind}/evidence", async (string kind, HttpContext http, SodDecisionStore store, CancellationToken ct) =>
        {
            var q = http.Request.Query;
            var key = q["key"].FirstOrDefault();
            var eventId = q["event_id"].FirstOrDefault();
            var context = q["context"].FirstOrDefault() ?? "current";
            if (!Kinds.Contains(kind) || key is null || !Hex64().IsMatch(key) || eventId is null || !Hex32().IsMatch(eventId) || !SodDecisionStore.ContextPattern().IsMatch(context))
                return Errors([V1Validation.At("value_error", "Invalid review item, event, kind or context.", "query")]);
            try
            {
                var e = (await store.HistoryAsync(kind, context, key, ct)).FirstOrDefault(i => (string?)i["event_id"] == eventId);
                if (e is null) return Detail(404, "Decision event is not available.");
                return Json(new JsonObject { ["event"] = e, ["evidence"] = await store.EvidenceAsync(e, ct) });
            }
            catch (SodDecisionException error) { return Detail(error.Status, error.Message); }
        });
    }
}
