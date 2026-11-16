using System.Globalization;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;
using SapLens.Application;
using SapLens.Domain.Sod;
using SapLens.Persistence;

namespace SapLens.Api;

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
    private static V1SodAnalysis.Query LiveQuery() =>
        new("users", "active", DateOnly.FromDateTime(DateTime.Now), [], "", "", "", "", "", "", "", "", "", "", "", [], [], [], [], [], [], "subject", false);

    /// <summary>The live review bundle: evidence generation, conflict model and the review model with every imported assignment.</summary>
    private sealed record Bundle(string Generation, DateOnly AsOf, Dictionary<string, SodUserEntry> Model, Dictionary<string, SodUserEntry> Review, Dictionary<string, string> Versions);

    private static async Task<(Bundle? Bundle, IResult? Error)> LoadAsync(IServiceProvider services, CancellationToken ct)
    {
        var query = LiveQuery();
        var (captured, error) = await V1SodAnalysis.CaptureAsync(services, query, ct);
        if (error is not null) return (null, error);
        var snapshot = await services.GetRequiredService<SnapshotService>().GetAsync(ct);
        var settings = await services.GetRequiredService<V1Settings>().GetAsync(ct);
        var features = settings["features"];
        var model = SodGovernance.Derive(captured!.Users);
        // _assignment_source is the user directory only while SoD and User-Role Mapping are both enabled.
        var sourceEnabled = ((bool?)features?["sod"] ?? false) && ((bool?)features?["user_role_mapping"] ?? true);
        var source = sourceEnabled
            ? snapshot.Users.UserOrder.Select(key => (key, snapshot.Users.Users[key].Assignments.Select(a =>
                new SodGovernance.SourceAssignment(a.RoleName, a.ValidFrom, a.ValidTo, a.UserGroup, a.MatchStatus, a.CatalogueRoles, a.Tcodes))))
            : [];
        var review = (string?)captured.Coverage["status"] == "available" ? SodGovernance.ReviewModel(model, source, query.Validity, query.AsOf) : model;
        var versions = new Dictionary<string, string>(StringComparer.Ordinal);
        if (settings["data_lifecycle"]?["sources"] is JsonObject references)
            foreach (var (name, reference) in references) if ((string?)reference?["snapshot"] is { } version) versions[name] = version;
        if ((string?)settings["employee_snapshot_id"] is { Length: > 0 } employees) versions["employees"] = employees;
        return (new Bundle(captured.Generation, query.AsOf, model, review, versions), null);
    }

    /// <summary>v1 actor(): the reviewer name and identity snapshot of this request, or the refusal when nobody individual is signed in.</summary>
    private static async Task<(string? Name, JsonObject? Identity, IResult? Error)> AttributionAsync(HttpContext http, CancellationToken ct)
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
            var key = SapLens.Domain.Roles.RoleNames.NormalizeUsername(user);
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
            if (context != "current") return V1Compatibility.NotMigrated(http, $"sod/decisions/{kind} for review period '{context}' (review periods are not migrated)");
            var (name, identity, refused) = await AttributionAsync(http, ct);
            if (refused is not null) return refused;

            var (bundle, loadError) = await LoadAsync(http.RequestServices, ct);
            if (loadError is not null) return loadError;
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
                    // publication_guard: the evidence generation must still be the one the reviewer saw when the decision commits.
                    var (now, _) = await V1SodAnalysis.CaptureAsync(http.RequestServices, LiveQuery(), token);
                    if (now?.Generation != expectedGeneration) throw new SodDecisionException(409, "SoD source evidence changed. Reload before saving.");
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

        api.MapGet("/sod/decisions/{kind}/history", async (string kind, HttpContext http, SodDecisionStore store, CancellationToken ct) =>
        {
            var q = http.Request.Query;
            var key = q["key"].FirstOrDefault();
            var context = q["context"].FirstOrDefault() ?? "current";
            if (!Kinds.Contains(kind) || key is null || !Hex64().IsMatch(key) || !SodDecisionStore.ContextPattern().IsMatch(context))
                return Errors([V1Validation.At("value_error", "Invalid review item, kind or context.", "query")]);
            if (context != "current") return V1Compatibility.NotMigrated(http, $"sod/decisions/{kind}/history for review period '{context}' (review periods are not migrated)");
            List<JsonObject> items;
            try { items = await store.HistoryAsync(kind, context, key, ct); }
            catch (SodDecisionException error) { return Detail(error.Status, error.Message); }
            JsonNode? verification = kind == "assignment" && items.Count > 0 && (string?)items[0]["decision"] == "Remove" ? await VerifyRemovalAsync(http.RequestServices, items[0], ct) : null;
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
            if (context != "current") return V1Compatibility.NotMigrated(http, $"sod/decisions/{kind}/evidence for review period '{context}' (review periods are not migrated)");
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
