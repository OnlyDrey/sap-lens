using System.Globalization;
using System.Text.Json.Nodes;
using AuthLens.Domain.Json;

namespace AuthLens.Domain.Sod;

/// <summary>One SoD 2.0 decision event (sod_decisions.Event): immutable, attributed, bound to the evidence version it was made against.</summary>
public sealed record SodDecisionEvent(
    string EventId, string Kind, string Context, string Timestamp, string Key, string User, string Ref, string Decision, string Reviewer, string Justification,
    string EvidenceVersion, string EvidenceSnapshot, string BulkOperationId = "", string PreviousDecision = "", string Approver = "", string Controls = "",
    string? Expires = null, IReadOnlyDictionary<string, string>? SourceVersions = null, JsonObject? ActorIdentity = null)
{
    /// <summary>model_dump(mode='json'): actor_identity is omitted when absent (IdentityRecorded.preserve_legacy).</summary>
    public JsonObject ToJson()
    {
        var json = new JsonObject();
        if (ActorIdentity is not null) json["actor_identity"] = ActorIdentity.DeepClone();
        json["event_id"] = EventId; json["bulk_operation_id"] = BulkOperationId; json["previous_decision"] = PreviousDecision; json["kind"] = Kind;
        json["context"] = Context; json["timestamp"] = Timestamp; json["key"] = Key; json["user"] = User; json["ref"] = Ref; json["decision"] = Decision;
        json["reviewer"] = Reviewer; json["approver"] = Approver; json["justification"] = Justification; json["controls"] = Controls; json["expires"] = Expires;
        json["evidence_version"] = EvidenceVersion; json["evidence_snapshot"] = EvidenceSnapshot;
        var versions = new JsonObject();
        foreach (var (k, v) in SourceVersions ?? new Dictionary<string, string>()) versions[k] = v;
        json["source_versions"] = versions;
        return json;
    }

    public static SodDecisionEvent FromJson(JsonObject json) => new(
        (string)json["event_id"]!, (string)json["kind"]!, (string)json["context"]!, (string)json["timestamp"]!, (string)json["key"]!, (string)json["user"]!,
        (string)json["ref"]!, (string)json["decision"]!, (string)json["reviewer"]!, (string)json["justification"]!, (string)json["evidence_version"]!,
        (string)json["evidence_snapshot"]!, (string?)json["bulk_operation_id"] ?? "", (string?)json["previous_decision"] ?? "", (string?)json["approver"] ?? "",
        (string?)json["controls"] ?? "", (string?)json["expires"],
        (json["source_versions"] as JsonObject)?.ToDictionary(p => p.Key, p => (string)p.Value!, StringComparer.Ordinal), json["actor_identity"]?.DeepClone() as JsonObject);
}

public sealed class SodActivity
{
    public required string Name { get; init; }
    public required string Key { get; init; }
    public SortedSet<string> Risks { get; } = new(StringComparer.Ordinal);
    public SortedSet<string> Slots { get; } = new(StringComparer.Ordinal);
    public SortedSet<string> Tcodes { get; } = new(StringComparer.Ordinal);
    public SortedSet<string> Assignments { get; } = new(StringComparer.Ordinal);
    public string EvidenceVersion { get; set; } = "";
}

public sealed class SodAssignment
{
    public required string Id { get; init; }
    public required string User { get; init; }
    public required string Role { get; init; }
    public string? ValidFrom { get; init; }
    public string? ValidTo { get; init; }
    public string UserGroup { get; init; } = "";
    public string? IntervalStatus { get; init; }
    public string? MatchingStatus { get; init; }
    public SortedSet<string> CatalogueRoles { get; } = new(StringComparer.Ordinal);
    public SortedSet<string> SingleRoles { get; } = new(StringComparer.Ordinal);
    public SortedDictionary<string, SortedSet<string>> Supplies { get; } = new(StringComparer.Ordinal);
    public SortedSet<string> Risks { get; } = new(StringComparer.Ordinal);
    public string EvidenceVersion { get; set; } = "";
    /// <summary>review_model_for: every catalogue transaction of the imported assignment (absent for conflict-only assignments outside the source cut).</summary>
    public IReadOnlyList<string>? CatalogueTcodes { get; init; }

    public SodAssignment With(IReadOnlyList<string> catalogueTcodes)
    {
        var copy = new SodAssignment
        {
            Id = Id, User = User, Role = Role, ValidFrom = ValidFrom, ValidTo = ValidTo, UserGroup = UserGroup, IntervalStatus = IntervalStatus, MatchingStatus = MatchingStatus,
            EvidenceVersion = EvidenceVersion, CatalogueTcodes = catalogueTcodes,
        };
        copy.CatalogueRoles.UnionWith(CatalogueRoles); copy.SingleRoles.UnionWith(SingleRoles); copy.Risks.UnionWith(Risks);
        foreach (var (k, v) in Supplies) copy.Supplies[k] = new SortedSet<string>(v, StringComparer.Ordinal);
        return copy;
    }
}

public sealed class SodUserEntry
{
    public required string User { get; init; }
    /// <summary>risk_id -> the user finding (v1 shape); insertion order as in the findings list.</summary>
    public Dictionary<string, JsonObject> Findings { get; } = new(StringComparer.Ordinal);
    public Dictionary<string, SodActivity> Activities { get; } = new(StringComparer.Ordinal);
    public Dictionary<string, SodAssignment> Assignments { get; } = new(StringComparer.Ordinal);
    public SortedSet<string> Groups { get; } = new(StringComparer.Ordinal);
    public JsonNode? Account { get; set; }
    /// <summary>restrict(): assignment ids passing the assignment-level filters (null: every assignment is shown).</summary>
    public IReadOnlySet<string>? VisibleAssignments { get; set; }
}

/// <summary>Lifecycle state of one review item and the latest event it rests on.</summary>
public sealed record SodItemState(string Lifecycle, SodDecisionEvent? Event);

/// <summary>Result of <see cref="SodGovernance.States"/>: per kind and key, the lifecycle, the coverage and the reappearance reasons.</summary>
public sealed class SodStates
{
    public Dictionary<string, Dictionary<string, SodItemState>> Items { get; } = new(StringComparer.Ordinal)
    {
        ["activity"] = new(StringComparer.Ordinal), ["assignment"] = new(StringComparer.Ordinal), ["acceptance"] = new(StringComparer.Ordinal), ["risk"] = new(StringComparer.Ordinal),
    };
    public Dictionary<string, string> Reappeared { get; } = new(StringComparer.Ordinal);
    public Dictionary<string, Dictionary<string, JsonObject>> Coverage { get; } = new(StringComparer.Ordinal)
    {
        ["activity"] = new(StringComparer.Ordinal), ["assignment"] = new(StringComparer.Ordinal), ["acceptance"] = new(StringComparer.Ordinal),
    };
}

/// <summary>Port of sod_governance.py (derive, simulate, states, review_coverage, effective_decision, decision_summary) and sod_decisions.lifecycle.
/// Pure: nothing here reads or writes storage, and the technical conflict evidence is never changed by a decision.</summary>
public static class SodGovernance
{
    public static readonly IReadOnlyDictionary<string, string[]> Decisions = new Dictionary<string, string[]>(StringComparer.Ordinal)
    {
        ["activity"] = ["Pending", "Approved", "Conditional", "Remove", "Investigate"],
        ["assignment"] = ["Pending", "Keep", "Remove", "Investigate"],
        ["acceptance"] = ["Pending", "Accepted", "Rejected"],
        ["risk"] = ["Pending", "Approved", "Remove", "Investigate"],
    };

    public const string Reappeared = "Assignment reappeared after it was removed from the SAP import; review it again. The earlier decision stays in history.";

    private static string? Text(JsonObject path, string name) => path[name] is JsonValue v ? (string?)v : null;

    /// <summary>Stable identity of one actual assignment: user, assigned role, validity and group.</summary>
    public static string AssignmentId(string user, JsonObject path) => CanonicalJson.Sha256(new object?[]
        { "sod-assignment", 1, user, Text(path, "actual_assigned_role") ?? "", Text(path, "role_valid_from") ?? "", Text(path, "role_valid_to") ?? "", Text(path, "user_group") ?? "" });

    public static string AssignmentId(string user, string role, string? validFrom, string? validTo, string userGroup) =>
        CanonicalJson.Sha256(new object?[] { "sod-assignment", 1, user, role, validFrom ?? "", validTo ?? "", userGroup });

    public static string ActivityKey(string user, string activity) => CanonicalJson.Sha256(new object?[] { "sod-activity", 1, user, activity });

    /// <summary>A finding in v1's JSON shape (the analysis response and the input of <see cref="Derive"/>).</summary>
    public static JsonObject FindingJson(SodFinding finding) => JsonNode.Parse(CanonicalJson.Serialize(new Dictionary<string, object?>
    {
        ["finding_id"] = finding.FindingId, ["subject"] = finding.Subject, ["kind"] = finding.Kind, ["risk_id"] = finding.RiskId, ["criticality"] = finding.Criticality,
        ["evaluation_policy"] = SodSource.EvaluationPolicy, ["evidence"] = finding.Evidence, ["current_potential"] = finding.CurrentPotential, ["account"] = finding.Account,
        ["evidence_version"] = finding.EvidenceVersion,
    }))!.AsObject();

    /// <summary>derive: index user findings into activities, assignments and per-risk side providers (current potential findings only by default).</summary>
    public static Dictionary<string, SodUserEntry> Derive(IEnumerable<JsonObject> findings, bool onlyCurrent = true)
    {
        var users = new Dictionary<string, SodUserEntry>(StringComparer.Ordinal);
        foreach (var finding in findings)
        {
            if ((string?)finding["kind"] != "user" || (onlyCurrent && !((bool?)finding["current_potential"] ?? false))) continue;
            var user = (string)finding["subject"]!;
            if (!users.TryGetValue(user, out var entry)) users[user] = entry = new SodUserEntry { User = user, Account = finding["account"]?.DeepClone() };
            var riskId = (string)finding["risk_id"]!;
            entry.Findings[riskId] = finding;
            foreach (var (slot, paths) in finding["evidence"]!.AsObject())
                foreach (var path in paths!.AsArray().Select(p => p!.AsObject()))
                {
                    var aid = AssignmentId(user, path);
                    if (!entry.Assignments.TryGetValue(aid, out var assignment))
                        entry.Assignments[aid] = assignment = new SodAssignment
                        {
                            Id = aid, User = user, Role = Text(path, "actual_assigned_role") ?? "", ValidFrom = Text(path, "role_valid_from"), ValidTo = Text(path, "role_valid_to"),
                            UserGroup = Text(path, "user_group") ?? "", IntervalStatus = Text(path, "interval_status"), MatchingStatus = Text(path, "matching_status"),
                        };
                    var activityName = (string)path["activity"]!;
                    var transaction = (string)path["matrix_transaction"]!;
                    assignment.CatalogueRoles.Add((string)path["matched_catalogue_pattern"]!);
                    assignment.SingleRoles.Add((string)path["single_role"]!);
                    if (!assignment.Supplies.TryGetValue(activityName, out var codes)) assignment.Supplies[activityName] = codes = new(StringComparer.Ordinal);
                    codes.Add(transaction);
                    assignment.Risks.Add(riskId);
                    if (!entry.Activities.TryGetValue(activityName, out var activity))
                        entry.Activities[activityName] = activity = new SodActivity { Name = activityName, Key = ActivityKey(user, activityName) };
                    activity.Risks.Add(riskId);
                    activity.Slots.Add(slot);
                    activity.Tcodes.Add(transaction);
                    activity.Assignments.Add(aid);
                    if (Text(path, "user_group") is { Length: > 0 } group) entry.Groups.Add(group);
                }
        }
        foreach (var entry in users.Values)
        {
            foreach (var activity in entry.Activities.Values)
                activity.EvidenceVersion = CanonicalJson.Sha256(new object?[] { "sod-activity-evidence", 1, entry.User, activity.Name, activity.Tcodes.ToList() });
            foreach (var assignment in entry.Assignments.Values)
                assignment.EvidenceVersion = AssignmentEvidenceVersion(assignment.Id, assignment.Supplies.SelectMany(p => p.Value.Select(code => (p.Key, code))));
        }
        return users;
    }

    /// <summary>sorted((activity, transaction) pairs) as v1 hashes them; an assignment without supplies hashes an empty list.</summary>
    public static string AssignmentEvidenceVersion(string id, IEnumerable<(string Activity, string Code)> supplies) =>
        CanonicalJson.Sha256(new object?[] { "sod-assignment-evidence", 1, id,
            supplies.OrderBy(p => p.Activity, StringComparer.Ordinal).ThenBy(p => p.Code, StringComparer.Ordinal).Select(p => new object?[] { p.Activity, p.Code }).ToList() });

    /// <summary>listify(entry) without findings and account: the derived review population in v1's JSON shape.</summary>
    public static JsonObject ToJson(SodUserEntry entry)
    {
        JsonArray List(IEnumerable<string> values) => new([.. values.Select(v => (JsonNode?)JsonValue.Create(v))]);
        var activities = new JsonObject();
        foreach (var (name, a) in entry.Activities)
            activities[name] = new JsonObject
            {
                ["activity"] = a.Name, ["key"] = a.Key, ["risks"] = List(a.Risks), ["slots"] = List(a.Slots), ["tcodes"] = List(a.Tcodes), ["assignments"] = List(a.Assignments),
                ["evidence_version"] = a.EvidenceVersion,
            };
        var assignments = new JsonObject();
        foreach (var (id, a) in entry.Assignments)
        {
            var supplies = new JsonObject();
            foreach (var (name, codes) in a.Supplies) supplies[name] = List(codes);
            assignments[id] = new JsonObject
            {
                ["id"] = a.Id, ["user"] = a.User, ["role"] = a.Role, ["valid_from"] = a.ValidFrom, ["valid_to"] = a.ValidTo, ["user_group"] = a.UserGroup,
                ["interval_status"] = a.IntervalStatus, ["matching_status"] = a.MatchingStatus, ["catalogue_roles"] = List(a.CatalogueRoles), ["single_roles"] = List(a.SingleRoles),
                ["supplies"] = supplies, ["risks"] = List(a.Risks), ["evidence_version"] = a.EvidenceVersion,
            };
        }
        return new JsonObject { ["user"] = entry.User, ["activities"] = activities, ["assignments"] = assignments, ["groups"] = List(entry.Groups) };
    }

    /// <summary>listify(assignment): the evidence an assignment decision is recorded against.</summary>
    public static JsonObject AssignmentEvidence(SodAssignment a)
    {
        JsonArray List(IEnumerable<string> values) => new([.. values.Select(v => (JsonNode?)JsonValue.Create(v))]);
        var supplies = new JsonObject();
        foreach (var (name, codes) in a.Supplies) supplies[name] = List(codes);
        var json = new JsonObject
        {
            ["id"] = a.Id, ["user"] = a.User, ["role"] = a.Role, ["valid_from"] = a.ValidFrom, ["valid_to"] = a.ValidTo, ["user_group"] = a.UserGroup,
            ["interval_status"] = a.IntervalStatus, ["matching_status"] = a.MatchingStatus, ["catalogue_roles"] = List(a.CatalogueRoles), ["single_roles"] = List(a.SingleRoles),
            ["supplies"] = supplies, ["risks"] = List(a.Risks), ["evidence_version"] = a.EvidenceVersion,
        };
        if (a.CatalogueTcodes is not null) json["catalogue_tcodes"] = List(a.CatalogueTcodes);
        return json;
    }

    /// <summary>activity_detail: the activity with its contributing assignments, duplicate coverage and sibling activities.</summary>
    public static JsonObject? ActivityDetail(SodUserEntry entry, string keyOrName)
    {
        var activity = entry.Activities.GetValueOrDefault(keyOrName) ?? entry.Activities.Values.FirstOrDefault(a => a.Key == keyOrName);
        if (activity is null) return null;
        JsonArray List(IEnumerable<string> values) => new([.. values.Select(v => (JsonNode?)JsonValue.Create(v))]);
        var assignments = new JsonArray();
        foreach (var aid in activity.Assignments)
        {
            var a = entry.Assignments[aid];
            assignments.Add(new JsonObject
            {
                ["id"] = aid, ["role"] = a.Role, ["valid_from"] = a.ValidFrom, ["valid_to"] = a.ValidTo, ["user_group"] = a.UserGroup, ["interval_status"] = a.IntervalStatus,
                ["tcodes"] = List(a.Supplies.GetValueOrDefault(activity.Name) ?? []), ["other_activities"] = List(a.Supplies.Keys.Where(n => n != activity.Name)),
                ["risks"] = List(a.Risks), ["catalogue_roles"] = List(a.CatalogueRoles), ["evidence_version"] = a.EvidenceVersion,
            });
        }
        return new JsonObject
        {
            ["activity"] = activity.Name, ["key"] = activity.Key, ["risks"] = List(activity.Risks), ["slots"] = List(activity.Slots), ["tcodes"] = List(activity.Tcodes),
            ["evidence_version"] = activity.EvidenceVersion, ["assignments"] = assignments, ["duplicate_coverage"] = assignments.Count > 1,
        };
    }

    /// <summary>One imported assignment of the review source (user_access record), as review_model_for reads it.</summary>
    public sealed record SourceAssignment(string RoleName, string? ValidFrom, string? ValidTo, string UserGroup, string? MatchStatus, IReadOnlyList<string> CatalogueRoles, IReadOnlyList<string> Tcodes);

    /// <summary>review_model_for: the conflict model extended with every imported assignment of the validity (source-only, never an input to conflict
    /// detection). The base model is not changed.</summary>
    public static Dictionary<string, SodUserEntry> ReviewModel(IReadOnlyDictionary<string, SodUserEntry> model, IEnumerable<(string User, IEnumerable<SourceAssignment> Assignments)> source,
        string validity, DateOnly asOf)
    {
        var result = new Dictionary<string, SodUserEntry>(StringComparer.Ordinal);
        SodUserEntry Copy(SodUserEntry entry)
        {
            var copy = new SodUserEntry { User = entry.User, Account = entry.Account };
            foreach (var (k, v) in entry.Findings) copy.Findings[k] = v;
            foreach (var (k, v) in entry.Activities) copy.Activities[k] = v;
            foreach (var (k, v) in entry.Assignments) copy.Assignments[k] = v;
            copy.Groups.UnionWith(entry.Groups);
            return copy;
        }
        foreach (var (user, entry) in model) result[user] = Copy(entry);
        foreach (var (user, assignments) in source)
            foreach (var row in assignments)
            {
                var status = Roles.SapDates.IntervalStatus(row.ValidFrom, row.ValidTo, asOf);
                if (validity != "all" && status != validity) continue;
                if (string.IsNullOrEmpty(row.RoleName)) continue;
                if (!result.TryGetValue(user, out var entry)) result[user] = entry = new SodUserEntry { User = user };
                var aid = AssignmentId(user, row.RoleName, row.ValidFrom, row.ValidTo, row.UserGroup);
                if (!entry.Assignments.TryGetValue(aid, out var assignment))
                {
                    assignment = new SodAssignment
                    {
                        Id = aid, User = user, Role = row.RoleName, ValidFrom = row.ValidFrom, ValidTo = row.ValidTo, UserGroup = row.UserGroup, IntervalStatus = status,
                        MatchingStatus = row.MatchStatus ?? "unknown", EvidenceVersion = AssignmentEvidenceVersion(aid, []),
                    };
                    assignment.CatalogueRoles.UnionWith(row.CatalogueRoles);
                }
                entry.Assignments[aid] = assignment.With(row.Tcodes.Count > 0 ? row.Tcodes : [.. assignment.Supplies.Values.SelectMany(c => c)]);
                if (row.UserGroup.Length > 0) entry.Groups.Add(row.UserGroup);
            }
        return result;
    }

    /// <summary>routers.sod_governance._locate: the item in the current model (key, evidence version, evidence) or null when evidence no longer supports it.</summary>
    public static (string Key, string EvidenceVersion, JsonNode Evidence)? Locate(IReadOnlyDictionary<string, SodUserEntry> model, string kind, string user, string key, string reference)
    {
        if (!model.TryGetValue(user, out var entry)) return null;
        if (kind == "activity")
            return entry.Activities.TryGetValue(reference, out var a) ? (a.Key, a.EvidenceVersion, ActivityDetail(entry, reference)!) : null;
        if (kind == "assignment")
            return entry.Assignments.TryGetValue(key, out var s) && s.Role == reference ? (s.Id, s.EvidenceVersion, AssignmentEvidence(s)) : null;
        return entry.Findings.TryGetValue(reference, out var f) ? ((string)f["finding_id"]!, (string)f["evidence_version"]!, f.DeepClone()) : null;
    }

    /// <summary>sod_decisions.lifecycle. currentVersion is null when evidence no longer supports the item. Timestamps are compared as v1 compares
    /// them (ISO strings in UTC); acceptance expiry is inclusive of its day.</summary>
    public static string Lifecycle(string kind, SodDecisionEvent? e, string? currentVersion, DateOnly today, string? reappeared = null)
    {
        if (e is null) return "Pending";
        if (currentVersion is null) return "Historical";
        if (e.EvidenceVersion != currentVersion) return "Outdated";
        if (kind == "acceptance" && e.Expires is { Length: > 0 } expires && DateOnly.ParseExact(expires, "yyyy-MM-dd", CultureInfo.InvariantCulture) < today) return "Outdated";
        if (reappeared is { Length: > 0 } && string.CompareOrdinal(e.Timestamp, reappeared) < 0) return "Outdated";
        return e.Decision == "Remove" ? "Removal required" : e.Decision;
    }

    /// <summary>simulate: the risks a removal of these assignments resolves, with the same two-sided rule; evidence is not changed.</summary>
    public static (List<string> Before, List<string> After, List<string> Resolved, List<string> LostActivities) Simulate(SodUserEntry entry, IReadOnlySet<string> removed)
    {
        if (removed.Any(id => !entry.Assignments.ContainsKey(id))) throw new ArgumentException("Select assignments that contribute to this user's detected evidence.");
        List<string> before = [], after = [], resolved = [], lost = [];
        foreach (var (riskId, finding) in entry.Findings.OrderBy(p => p.Key, StringComparer.Ordinal))
        {
            before.Add(riskId);
            var remaining = finding["evidence"]!.AsObject().Select(p => p.Value!.AsArray().Select(x => x!.AsObject()).Where(path => !removed.Contains(AssignmentId(entry.User, path))).ToList()).ToList();
            var still = (bool?)finding["current_potential"] ?? false
                ? remaining.All(paths => paths.Any(path => Text(path, "interval_status") == "active"))
                : remaining.All(paths => paths.Count > 0);
            (still ? after : resolved).Add(riskId);
        }
        foreach (var (name, activity) in entry.Activities.OrderBy(p => p.Key, StringComparer.Ordinal))
            if (activity.Assignments.Count > 0 && activity.Assignments.IsSubsetOf(removed)) lost.Add(name);
        return (before, after, resolved, lost);
    }

    /// <summary>states: lifecycle per review item. latest maps kind -> key -> latest event; reappeared maps assignment key -> the moment it came back.</summary>
    public static SodStates States(IReadOnlyDictionary<string, SodUserEntry> model, IReadOnlyDictionary<string, IReadOnlyDictionary<string, SodDecisionEvent>> latest, DateOnly today,
        IReadOnlyDictionary<string, string>? reappeared = null, IReadOnlyDictionary<string, string>? reasons = null, string? unavailable = null)
    {
        // assignment_lifecycle.applicability() when its memory cannot be trusted: every assignment decision stops applying (v1 _Everything/_Always).
        if (unavailable is not null) (reappeared, reasons) = (new Everything("9999-12-31T00:00:00+00:00"), new Everything(unavailable));
        var result = new SodStates();
        SodDecisionEvent? Latest(string kind, string key) => latest.TryGetValue(kind, out var map) && map.TryGetValue(key, out var e) ? e : null;
        foreach (var entry in model.Values)
        {
            foreach (var activity in entry.Activities.Values)
            {
                var e = Latest("activity", activity.Key);
                result.Items["activity"][activity.Key] = new(Lifecycle("activity", e, activity.EvidenceVersion, today), e);
            }
            foreach (var assignment in entry.Assignments.Values)
            {
                var e = Latest("assignment", assignment.Id);
                var back = reappeared?.GetValueOrDefault(assignment.Id);
                result.Items["assignment"][assignment.Id] = new(Lifecycle("assignment", e, assignment.EvidenceVersion, today, back), e);
                if (e is not null && back is { Length: > 0 } && string.CompareOrdinal(e.Timestamp, back) < 0)
                    result.Reappeared[assignment.Id] = reasons?.GetValueOrDefault(assignment.Id) ?? Reappeared;
            }
            foreach (var finding in entry.Findings.Values)
            {
                var id = (string)finding["finding_id"]!;
                var version = (string)finding["evidence_version"]!;
                var risk = Latest("risk", id);
                result.Items["risk"][id] = new(Lifecycle("risk", risk, version, today), risk);
                var acceptance = Latest("acceptance", id);
                result.Items["acceptance"][id] = new(Lifecycle("acceptance", acceptance, version, today), acceptance);
            }
        }
        ReviewCoverage(model, result);
        return result;
    }

    /// <summary>A mapping that answers every key with the same value.</summary>
    private sealed class Everything(string value) : IReadOnlyDictionary<string, string>
    {
        public string this[string key] => value;
        public IEnumerable<string> Keys => [];
        public IEnumerable<string> Values => [];
        public int Count => 0;
        public bool ContainsKey(string key) => true;
        public bool TryGetValue(string key, out string result) { result = value; return true; }
        public IEnumerator<KeyValuePair<string, string>> GetEnumerator() => Enumerable.Empty<KeyValuePair<string, string>>().GetEnumerator();
        System.Collections.IEnumerator System.Collections.IEnumerable.GetEnumerator() => GetEnumerator();
    }

    /// <summary>simulate() in v1's JSON shape; decisions maps activity name -> its lifecycle (only to warn about approved access that would disappear).</summary>
    public static JsonObject SimulateJson(SodUserEntry entry, IReadOnlySet<string> removed, IReadOnlyDictionary<string, string>? decisions = null)
    {
        var (before, after, resolved, lost) = Simulate(entry, removed);
        var affected = lost.Where(n => decisions?.GetValueOrDefault(n) is "Approved" or "Conditional").Order(StringComparer.Ordinal).ToList();
        JsonArray List(IEnumerable<string> values) => new([.. values.Select(v => (JsonNode?)JsonValue.Create(v))]);
        return new JsonObject
        {
            ["removed"] = List(removed.Order(StringComparer.Ordinal)), ["before"] = List(before), ["after"] = List(after), ["resolved"] = List(resolved), ["lost_activities"] = List(lost),
            ["affected_approved_activities"] = List(affected), ["warnings"] = List(affected.Select(n => $"Removal would end approved access to activity {n}.")),
            ["eliminates_all"] = before.Count > 0 && after.Count == 0,
        };
    }

    /// <summary>removal_options: for one risk, removing all providers of either activity side.</summary>
    public static JsonArray RemovalOptions(SodUserEntry entry, string riskId, IReadOnlyDictionary<string, string>? decisions = null)
    {
        var options = new JsonArray();
        if (!entry.Findings.TryGetValue(riskId, out var finding)) return options;
        JsonArray List(IEnumerable<string> values) => new([.. values.Select(v => (JsonNode?)JsonValue.Create(v))]);
        foreach (var (slot, paths) in finding["evidence"]!.AsObject().OrderBy(p => p.Key, StringComparer.Ordinal))
        {
            var list = paths!.AsArray().Select(p => p!.AsObject()).ToList();
            var providers = list.Select(p => AssignmentId(entry.User, p)).Distinct().Order(StringComparer.Ordinal).ToList();
            var result = SimulateJson(entry, providers.ToHashSet(StringComparer.Ordinal), decisions);
            var resolved = result["resolved"]!.AsArray().Select(v => (string)v!).ToList();
            options.Add(new JsonObject
            {
                ["slot"] = slot, ["activities"] = List(list.Select(p => (string)p["activity"]!).Distinct().Order(StringComparer.Ordinal)), ["assignments"] = List(providers),
                ["roles"] = List(providers.Select(a => entry.Assignments[a].Role).Distinct().Order(StringComparer.Ordinal)), ["resolves_risk"] = resolved.Contains(riskId),
                ["also_resolves"] = List(resolved.Where(r => r != riskId)), ["affected_approved_activities"] = result["affected_approved_activities"]!.DeepClone(),
                ["warnings"] = result["warnings"]!.DeepClone(),
            });
        }
        return options;
    }

    /// <summary>single_assignment_impact.</summary>
    public static JsonObject SingleAssignmentImpact(SodUserEntry entry, string aid, IReadOnlyDictionary<string, string>? decisions = null)
    {
        var result = SimulateJson(entry, new HashSet<string>(StringComparer.Ordinal) { aid }, decisions);
        return new JsonObject
        {
            ["assignment_id"] = aid, ["resolves"] = result["resolved"]!.DeepClone(), ["remaining"] = result["after"]!.DeepClone(), ["lost_activities"] = result["lost_activities"]!.DeepClone(),
            ["affected_approved_activities"] = result["affected_approved_activities"]!.DeepClone(), ["warnings"] = result["warnings"]!.DeepClone(), ["eliminates_all"] = result["eliminates_all"]!.DeepClone(),
        };
    }

    /// <summary>review_coverage: assignment decisions -> base activities -> risk assessment; explicit risk reviews cover activities only afterwards, so
    /// coverage never travels back through a shared activity into another risk. Never writes events.</summary>
    private static void ReviewCoverage(IReadOnlyDictionary<string, SodUserEntry> model, SodStates state)
    {
        var covered = state.Coverage;
        foreach (var entry in model.Values)
        {
            foreach (var aid in entry.Assignments.Keys)
            {
                var life = state.Items["assignment"][aid].Lifecycle;
                var reviewed = life is "Keep" or "Removal required";
                covered["assignment"][aid] = new JsonObject { ["reviewed"] = reviewed, ["provenance"] = reviewed ? "Explicit assignment review" : "", ["removal_planned"] = life == "Removal required" };
            }
            var baseline = new Dictionary<string, (bool Reviewed, string Provenance)>(StringComparer.Ordinal);
            foreach (var (name, activity) in entry.Activities)
            {
                var life = state.Items["activity"][activity.Key].Lifecycle;
                var manual = life is "Approved" or "Conditional" or "Removal required";
                var throughRoles = activity.Assignments.Count > 0 && activity.Assignments.All(aid => (bool)covered["assignment"][aid]["reviewed"]!);
                baseline[name] = (manual || throughRoles, manual ? "Explicit activity review" : throughRoles ? "Reviewed through roles" : "");
            }
            var removed = entry.Assignments.Keys.Where(aid => state.Items["assignment"][aid].Lifecycle == "Removal required").ToHashSet(StringComparer.Ordinal);
            var planned = removed.Count > 0 ? Simulate(entry, removed).Resolved.ToHashSet(StringComparer.Ordinal) : [];
            var explicitRisks = new HashSet<string>(StringComparer.Ordinal);
            foreach (var (rid, finding) in entry.Findings)
            {
                var id = (string)finding["finding_id"]!;
                var life = state.Items["acceptance"][id].Lifecycle;
                var formal = life is "Accepted" or "Rejected";
                var manual = formal || state.Items["risk"].GetValueOrDefault(id)?.Lifecycle is "Approved" or "Removal required";
                if (formal) explicitRisks.Add(rid);
                var names = finding["evidence"]!.AsObject().SelectMany(p => p.Value!.AsArray().Select(path => (string)path!["activity"]!)).ToHashSet(StringComparer.Ordinal);
                var derived = names.Count > 0 && names.All(n => baseline[n].Reviewed);
                var reviewed = manual || derived;
                covered["acceptance"][id] = new JsonObject
                {
                    ["reviewed"] = reviewed, ["provenance"] = manual ? "Explicit risk review" : derived ? "Reviewed through access evidence" : "",
                    ["removal_planned"] = planned.Contains(rid), ["risk_accepted"] = life == "Accepted", ["remediation_verified"] = false,
                    ["label"] = reviewed && planned.Contains(rid) ? "Reviewed — removal planned" : reviewed ? "Reviewed" : "Needs review",
                };
            }
            foreach (var (name, activity) in entry.Activities)
            {
                var (reviewed, provenance) = baseline[name];
                if (!reviewed && activity.Risks.Overlaps(explicitRisks)) (reviewed, provenance) = (true, "Reviewed through risk review");
                covered["activity"][activity.Key] = new JsonObject { ["reviewed"] = reviewed, ["provenance"] = provenance, ["removal_planned"] = false };
            }
        }
    }

    private static readonly Dictionary<string, string> Names = new(StringComparer.Ordinal)
    {
        ["Keep"] = "Approved", ["Approved"] = "Approved", ["Removal required"] = "Remove", ["Remove"] = "Remove", ["Investigate"] = "Investigate", ["Conditional"] = "Approved",
    };
    private static readonly Dictionary<string, string> Tones = new(StringComparer.Ordinal) { ["Approved"] = "success", ["Remove"] = "error", ["Investigate"] = "warning", ["Pending"] = "neutral" };

    private static string StaleBasis(SodStates state, string kind, string key, string life) =>
        kind == "assignment" && state.Reappeared.TryGetValue(key, out var reason) && life == "Outdated" ? reason : "Previous decision; evidence needs review";

    /// <summary>effective_decision: current explicit decisions win; role-derived activity approval never writes events. Stale approval grants nothing;
    /// a retained Remove stays visible.</summary>
    public static JsonObject EffectiveDecision(SodUserEntry entry, SodStates state, string kind, string key)
    {
        var (life, e) = (state.Items[kind][key].Lifecycle, state.Items[kind][key].Event);
        var coverage = state.Coverage[kind == "risk" ? "acceptance" : kind][key];
        var distribution = new SortedDictionary<string, int>(StringComparer.Ordinal);
        var derived = "Pending";
        if (kind == "activity")
        {
            var activity = entry.Activities.Values.First(a => a.Key == key);
            foreach (var aid in activity.Assignments) { var l = state.Items["assignment"][aid].Lifecycle; distribution[l] = distribution.GetValueOrDefault(l) + 1; }
            if (distribution.GetValueOrDefault("Keep") > 0) derived = "Approved";
            else if (distribution.Count > 0 && distribution.Keys.All(k => k == "Removal required")) derived = "Remove";
            else if (distribution.GetValueOrDefault("Investigate") > 0) derived = "Investigate";
        }
        var isExplicit = e is not null && Names.ContainsKey(life);
        var stale = life is "Outdated" or "Historical";
        var explicitLabel = Names.GetValueOrDefault(life, "Pending");
        var label = isExplicit ? explicitLabel : derived;
        if (stale && e is { Decision: "Remove" }) label = "Remove";
        var assignmentDecisions = new JsonObject();
        foreach (var (k, v) in distribution) assignmentDecisions[k] = v;
        return new JsonObject
        {
            ["label"] = label, ["tone"] = Tones[label], ["explicit"] = isExplicit, ["stale"] = stale,
            ["basis"] = isExplicit ? "Explicit decision" : stale ? StaleBasis(state, kind, key, life)
                : kind == "activity" && derived != "Pending" ? "Derived from current assignment decisions" : (string?)coverage["provenance"] is { Length: > 0 } p ? p : "No current decision",
            ["assignment_decisions"] = assignmentDecisions, ["derived_label"] = derived, ["explicit_label"] = explicitLabel,
            ["disagreement"] = kind == "activity" && isExplicit && derived != "Pending" && explicitLabel != derived,
        };
    }

    /// <summary>decision_summary: formal acceptance is presented separately from the four primary access decisions.</summary>
    public static JsonObject DecisionSummary(SodUserEntry entry, SodStates state, string kind, string key)
    {
        if (kind != "acceptance") return EffectiveDecision(entry, state, kind, key);
        var (life, e) = (state.Items[kind][key].Lifecycle, state.Items[kind][key].Event);
        var stale = life is "Outdated" or "Historical";
        var isExplicit = e is not null && !stale && life is "Accepted" or "Rejected";
        var (label, tone) = stale ? (life == "Outdated" ? ("Needs review", "warning") : ("Historical", "neutral"))
            : isExplicit ? (life, life == "Accepted" ? "success" : "error") : ("Acceptance pending", "warning");
        return new JsonObject
        {
            ["label"] = label, ["tone"] = tone, ["explicit"] = isExplicit, ["stale"] = stale,
            ["basis"] = isExplicit ? "Explicit decision" : stale ? StaleBasis(state, kind, key, life)
                : (string?)state.Coverage[kind][key]["provenance"] is { Length: > 0 } p ? p : "No current decision",
            ["assignment_decisions"] = new JsonObject(),
        };
    }
}
