using System.Globalization;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;
using Microsoft.EntityFrameworkCore;
using AuthLens.Application;
using AuthLens.Domain.Json;
using AuthLens.Domain.Sod;
using AuthLens.Persistence;

namespace AuthLens.Api;

/// <summary>Content-addressed private snapshots (v1 write_private/read_private 'snapshots'): SHA-256 of the canonical JSON, stored once, never changed.</summary>
public static class PrivateSnapshots
{
    public static string Write(AuthLensDb db, JsonNode value)
    {
        var json = CanonicalJson.Serialize(value);
        var id = Convert.ToHexStringLower(SHA256.HashData(Encoding.UTF8.GetBytes(json)));
        if (db.SodEvidenceSnapshots.Local.All(s => s.Sha256 != id) && !db.SodEvidenceSnapshots.Any(s => s.Sha256 == id))
            db.SodEvidenceSnapshots.Add(new SodEvidenceSnapshot { Sha256 = id, Json = json });
        return id;
    }

    /// <summary>The snapshot, re-verified against its address; null when it is missing or altered.</summary>
    public static async Task<JsonObject?> ReadAsync(AuthLensDb db, string id, CancellationToken ct)
    {
        var row = await db.SodEvidenceSnapshots.AsNoTracking().FirstOrDefaultAsync(s => s.Sha256 == id, ct);
        if (row is null || Convert.ToHexStringLower(SHA256.HashData(Encoding.UTF8.GetBytes(row.Json))) != id) return null;
        return JsonNode.Parse(row.Json) as JsonObject;
    }
}

/// <summary>Port of sod_reviews.py: legacy (SoD 1.0) justified risk reviews. Every save appends an immutable, evidence-bearing event; absence from the
/// source is historical, not resolution. Stored as one document (revision for optimistic concurrency) with content-addressed finding snapshots.</summary>
public sealed class SodReviewStore(WriteCoordinator writer, IDbContextFactory<AuthLensDb> factory, TimeProvider clock)
{
    public const string Document = "sod-reviews";
    public const int MaxReviews = 10_000, MaxEvents = 1000;
    public static readonly string[] Decisions = ["Pending review", "Accepted with mitigating controls", "Access removal required", "Not applicable / false positive", "Further investigation required"];
    public static readonly string[] ActionStatuses = ["Not started", "In progress", "Completed", "Not applicable"];
    public static readonly string[] Lifecycles = ["Pending", "Reviewed", "Action required", "Outdated", "Historical"];

    public async Task<JsonObject> ReadAsync(CancellationToken ct)
    {
        await using var db = await factory.CreateDbContextAsync(ct);
        return await ReadAsync(db, ct);
    }

    private static async Task<JsonObject> ReadAsync(AuthLensDb db, CancellationToken ct)
    {
        var row = await db.SodDocuments.AsNoTracking().FirstOrDefaultAsync(d => d.Name == Document, ct);
        var data = row is null ? new JsonObject() : JsonNode.Parse(row.Json) as JsonObject ?? [];
        data["version"] = 1;
        data["revision"] = row?.Revision ?? 0;
        if (data["contexts"] is not JsonObject) data["contexts"] = new JsonObject();
        return data;
    }

    /// <summary>Annotation: validated and cleaned as v1's model; returns the cleaned annotation or an error message (422).</summary>
    public static (JsonObject? Annotation, string? Error) Annotation(JsonNode? node)
    {
        if (node is not JsonObject raw) return (null, "An annotation is required.");
        string[] fields = ["decision", "reviewer", "rationale", "comments", "mitigating_controls", "action_owner", "target_date", "action_status", "completion_notes"];
        if (raw.Any(p => !fields.Contains(p.Key))) return (null, "Extra inputs are not permitted");
        var result = new JsonObject();
        foreach (var (name, max) in new[] { ("decision", 100), ("reviewer", 120), ("rationale", 4000), ("comments", 4000), ("mitigating_controls", 8000), ("action_owner", 120), ("action_status", 40), ("completion_notes", 4000) })
        {
            var value = raw[name] is JsonValue v && v.TryGetValue<string>(out var text) ? text : raw[name] is null ? null : "\u0000";
            if (value == "\u0000") return (null, $"{name}: Input should be a valid string");
            if (value is not null && value.Any(c => c < 32 && c is not ('\n' or '\r' or '\t'))) return (null, "Review text contains unsupported control characters.");
            value = value?.Trim() ?? "";
            if (value.Length > max) return (null, $"{name}: String should have at most {max} characters");
            result[name] = value;
        }
        if ((string)result["action_status"]! == "") result["action_status"] = "Not started";
        if (!Decisions.Contains((string)result["decision"]!) || !ActionStatuses.Contains((string)result["action_status"]!)) return (null, "Choose a supported decision and action status.");
        if ((string)result["reviewer"]! == "" || (string)result["rationale"]! == "") return (null, "Reviewer and justification are required.");
        string? due = null;
        if (raw["target_date"] is JsonValue d)
        {
            if (!d.TryGetValue<string>(out var t) || !DateOnly.TryParseExact(t, "yyyy-MM-dd", CultureInfo.InvariantCulture, DateTimeStyles.None, out _)) return (null, "target_date: Input should be a valid date");
            due = t;
        }
        result["target_date"] = due;
        if ((string)result["decision"]! == "Accepted with mitigating controls" && (string)result["mitigating_controls"]! == "") return (null, "Describe the mitigating controls before accepting this finding.");
        if ((string)result["action_status"]! == "Completed" && (string)result["completion_notes"]! == "") return (null, "Completion notes are required for a completed action.");
        return (result, null);
    }

    /// <summary>save: appends one review event for the finding (the evidence it was made against is retained as a private snapshot).</summary>
    public Task<JsonObject> SaveAsync(JsonObject finding, JsonObject annotation, int expectedRevision, string expectedEvidenceVersion, string context, JsonObject? identity, CancellationToken ct)
    {
        SodDecisionStore.CheckContext(context);
        if (expectedEvidenceVersion != (string?)finding["evidence_version"]) throw new SodDecisionException(409, "SoD finding evidence changed. Reload before recording a decision.");
        return writer.WriteAsync(async (db, token) =>
        {
            var data = await ReadAsync(db, token);
            if ((int)data["revision"]! != expectedRevision) throw new SodDecisionException(409, "SoD reviews changed. Reload before saving a decision.");
            var contexts = data["contexts"]!.AsObject();
            if (contexts[context] is not JsonObject reviews) contexts[context] = reviews = [];
            var id = (string)finding["finding_id"]!;
            if (reviews[id] is not JsonArray events) events = [];
            var count = contexts.Sum(c => c.Value!.AsObject().Count);
            if (events.Count == 0 && count >= MaxReviews || events.Count >= MaxEvents)
                throw new SodDecisionException(409, "SoD review history capacity is reached. Existing events are retained; preserve a private backup before recovery.");
            var snapshot = PrivateSnapshots.Write(db, new JsonObject { ["version"] = 1, ["source"] = "sod-review-finding", ["finding"] = finding.DeepClone() });
            var e = new JsonObject();
            if (identity is not null) e["actor_identity"] = identity.DeepClone();
            e["event_id"] = Guid.NewGuid().ToString("N"); e["context"] = context; e["timestamp"] = SodDecisionStore.Stamp(clock.GetUtcNow()); e["finding_id"] = id;
            e["evidence_version"] = finding["evidence_version"]!.DeepClone(); e["annotation"] = annotation.DeepClone(); e["finding_snapshot"] = snapshot;
            e["subject"] = finding["subject"]!.DeepClone(); e["risk_id"] = finding["risk_id"]!.DeepClone();
            events.Add(e);
            reviews[id] = events.DeepClone();
            var row = await db.SodDocuments.FirstOrDefaultAsync(d => d.Name == Document, token);
            if (row is null) db.SodDocuments.Add(row = new SodDocument { Name = Document, Json = "{}" });
            var revision = (row.Revision = expectedRevision + 1);
            data["revision"] = revision;
            (row.Json, row.UpdatedUtc, row.UpdatedBy) = (data.ToJsonString(), clock.GetUtcNow().UtcDateTime, (string)annotation["reviewer"]!);
            return new JsonObject { ["event"] = e.DeepClone(), ["revision"] = revision, ["reviewer_identity"] = V1SodDecisions.IdentityNotice };
        }, ct);
    }

    /// <summary>finding_for_event: the immutable observation one event was made against.</summary>
    public async Task<JsonObject> FindingForEventAsync(JsonObject e, CancellationToken ct)
    {
        await using var db = await factory.CreateDbContextAsync(ct);
        var saved = await PrivateSnapshots.ReadAsync(db, (string)e["finding_snapshot"]!, ct);
        var finding = saved?["finding"] as JsonObject;
        if ((string?)saved?["source"] != "sod-review-finding" || finding is null || (string?)finding["finding_id"] != (string?)e["finding_id"] || (string?)finding["evidence_version"] != (string?)e["evidence_version"]
            || (string?)finding["subject"] != (string?)e["subject"] || (string?)finding["risk_id"] != (string?)e["risk_id"])
            throw new SodDecisionException(409, "Retained SoD review evidence is unavailable or invalid. Review history is preserved; restore its snapshot from a private backup.");
        return finding;
    }

    /// <summary>listing: every current finding and every reviewed one, with its lifecycle (Historical when no longer present, Outdated when its evidence changed).</summary>
    public async Task<JsonObject> ListingAsync(IEnumerable<JsonObject> currentFindings, string context, JsonNode? coverage, CancellationToken ct)
    {
        SodDecisionStore.CheckContext(context);
        var current = currentFindings.ToDictionary(f => (string)f["finding_id"]!, f => f.DeepClone().AsObject(), StringComparer.Ordinal);
        var data = await ReadAsync(ct);
        var saved = data["contexts"]![context] as JsonObject ?? [];
        var items = new JsonArray();
        foreach (var id in current.Keys.Concat(saved.Select(p => p.Key)).Distinct().Order(StringComparer.Ordinal))
        {
            var events = saved[id] as JsonArray ?? [];
            var e = events.Count > 0 ? events[^1]!.AsObject() : null;
            var present = current.ContainsKey(id);
            var finding = present ? current[id] : await FindingForEventAsync(e!, ct);
            var stale = e is not null && (!present || (string?)e["evidence_version"] != (string?)finding["evidence_version"]);
            var decision = (string?)e?["annotation"]?["decision"] ?? "Pending review";
            var lifecycle = !present ? "Historical" : stale ? "Outdated" : decision == "Pending review" ? "Pending"
                : decision is "Accepted with mitigating controls" or "Not applicable / false positive" ? "Reviewed" : "Action required";
            items.Add(new JsonObject
            {
                ["finding_id"] = id, ["finding"] = finding, ["decision"] = decision, ["event"] = e?.DeepClone(), ["history_count"] = events.Count, ["stale"] = stale,
                ["lifecycle"] = lifecycle, ["presence"] = present ? "current" : "historical",
            });
        }
        return new JsonObject
        {
            ["items"] = items, ["revision"] = data["revision"]!.DeepClone(), ["context"] = context, ["coverage"] = coverage?.DeepClone(), ["reviewer_identity"] = V1SodDecisions.IdentityNotice,
            ["summary"] = Summary(items, Lifecycles),
        };
    }

    public static JsonObject Summary(JsonArray items, IEnumerable<string> names)
    {
        var summary = new JsonObject();
        foreach (var name in names) summary[name] = items.Count(i => (string?)i!["lifecycle"] == name);
        return summary;
    }

    public async Task<List<JsonObject>> HistoryAsync(string findingId, string context, CancellationToken ct)
    {
        SodDecisionStore.CheckContext(context);
        if (!Regex.IsMatch(findingId, "^[a-f0-9]{64}$")) throw new SodDecisionException(422, "Choose a valid finding identifier.");
        var data = await ReadAsync(ct);
        var events = data["contexts"]![context]?[findingId] as JsonArray ?? [];
        return [.. events.Reverse().Select(e => e!.AsObject().DeepClone().AsObject())];
    }
}

/// <summary>Port of sod_periods.py storage: the period index (one document, optimistic revision) and content-addressed immutable period snapshots.</summary>
public sealed class SodPeriodStore(WriteCoordinator writer, IDbContextFactory<AuthLensDb> factory)
{
    public const string Document = "sod-periods";
    public static readonly Dictionary<string, string[]> Allowed = new(StringComparer.Ordinal)
    {
        ["Draft"] = ["In review"], ["In review"] = ["Draft", "Ready for approval"], ["Ready for approval"] = ["In review", "Approved", "Rejected"], ["Rejected"] = ["In review"], ["Approved"] = ["Closed"],
    };
    /// <summary>periods.lock: serializes period lifecycle changes (capture, transition, recapture, deletion).</summary>
    public SemaphoreSlim Gate { get; } = new(1, 1);

    public async Task<JsonObject> ReadAsync(CancellationToken ct)
    {
        await using var db = await factory.CreateDbContextAsync(ct);
        return await ReadAsync(db, ct);
    }

    public static async Task<JsonObject> ReadAsync(AuthLensDb db, CancellationToken ct)
    {
        var row = await db.SodDocuments.AsNoTracking().FirstOrDefaultAsync(d => d.Name == Document, ct);
        var index = row is null ? new JsonObject() : JsonNode.Parse(row.Json) as JsonObject ?? throw new SodDecisionException(409, "SoD period index is unavailable. Original data is preserved; restore a private backup.");
        index["version"] = 1;
        index["revision"] = row?.Revision ?? 0;
        if (index["items"] is not JsonArray) index["items"] = new JsonArray();
        if (index["deletions"] is not JsonArray) index["deletions"] = new JsonArray();
        return index;
    }

    public static JsonObject Find(JsonObject index, string id, bool archived = false)
    {
        var item = index["items"]!.AsArray().Select(i => i!.AsObject()).FirstOrDefault(i => (string?)i["id"] == id);
        if (item is null || item["deleted_at"] is JsonValue && !archived) throw new SodDecisionException(404, "Review period not found.");
        return item;
    }

    public async Task<JsonObject> SnapshotAsync(JsonObject period, CancellationToken ct)
    {
        await using var db = await factory.CreateDbContextAsync(ct);
        var saved = await PrivateSnapshots.ReadAsync(db, (string)period["snapshot"]!, ct);
        if (saved is null || (string?)saved["source"] != "sod-period" || (string?)saved["period_id"] != (string?)period["id"])
            throw new SodDecisionException(409, "Period snapshot is unavailable or invalid. Restore its private backup.");
        return saved;
    }

    /// <summary>Writes the index with an expected revision (409 when another change happened) and any new snapshots in one transaction.</summary>
    public Task<int> SaveAsync(int expectedRevision, Func<AuthLensDb, JsonObject, CancellationToken, Task> change, string actor, CancellationToken ct) => writer.WriteAsync(async (db, token) =>
    {
        var index = await ReadAsync(db, token);
        if ((int)index["revision"]! != expectedRevision) throw new SodDecisionException(409, "Review periods changed. Reload before saving.");
        await change(db, index, token);
        if (index["items"]!.AsArray().Count > 250 || index["deletions"]!.AsArray().Count > 500) throw new SodDecisionException(409, "Period changes could not be saved. Previous snapshots remain retained.");
        var row = await db.SodDocuments.FirstOrDefaultAsync(d => d.Name == Document, token);
        if (row is null) db.SodDocuments.Add(row = new SodDocument { Name = Document, Json = "{}" });
        row.Revision = expectedRevision + 1;
        index["revision"] = row.Revision;
        (row.Json, row.UpdatedUtc, row.UpdatedBy) = (index.ToJsonString(), DateTime.UtcNow, actor);
        return row.Revision;
    }, ct);
}

/// <summary>Port of sod_periods.py operations and routers/sod_periods.py: explicit review periods with reproducible snapshots. Approved and closed
/// periods are immutable: their snapshot carries a frozen copy of every decision and action. Deletion archives (tombstones) a period with recorded
/// work; only an empty draft is erased. Nothing here changes imported evidence.</summary>
public static class SodPeriods
{
    public const string IdentityNotice = V1SodDecisions.IdentityNotice;
    public const string Limitation = "Evaluation uses retained imported evidence at an explicit date; it does not reconstruct unexported historical SAP authorizations.";
    private static IResult Json(JsonNode node) => Results.Content(node.ToJsonString(), "application/json");
    private static T Service<T>(IServiceProvider s) where T : notnull => s.GetRequiredService<T>();
    private static string Now(IServiceProvider s) => SodDecisionStore.Stamp(Service<TimeProvider>(s).GetUtcNow());
    private static DateOnly Day(string text) => DateOnly.ParseExact(text, "yyyy-MM-dd", CultureInfo.InvariantCulture);

    /// <summary>Runs a handler and maps SodDecisionException to v1's HTTP status and detail.</summary>
    public static async Task<IResult> Guard(Func<Task<IResult>> handler)
    {
        try { return await handler(); }
        catch (SodDecisionException error) { return SodScope.Problem(error.Status, error.Message); }
    }

    // ---- capture

    /// <summary>capture: analysis at the evaluation date with frozen risk definitions, descriptions, the legacy review baseline and the assignment cut.</summary>
    public static async Task<JsonObject> CaptureAsync(IServiceProvider services, string id, DateOnly evaluation, bool legacy, CancellationToken ct)
    {
        var c = await V1SodCatalogue.ContextAsync(services, ct);
        var query = new V1SodAnalysis.Query("users", "active", evaluation, [], "", "", "", "", "", "", "", "", "", "", "", [], [], [], [], [], [], "subject", false);
        var (result, error) = await V1SodAnalysis.CaptureAsync(services, query, ct);
        if (error is not null || (string?)result!.Coverage["status"] != "available")
            throw new SodDecisionException(409, "Review periods require validated matrix, catalogue and enabled User–Role Mapping sources.");
        var riskItems = V1SodCatalogue.Catalogue(c)["items"]!.AsArray().Select(i => i!.AsObject()).Where(i => (bool?)i["current"] ?? false).ToList();
        var definitions = c.Snapshot.Sod!.Risks.ToDictionary(r => (string)r["risk_id"]!, StringComparer.Ordinal);
        var entries = c.Storage["entries"]!.AsObject();
        var settings = c.Settings;
        var versions = new JsonObject();
        if (settings["data_lifecycle"]?["sources"] is JsonObject references) foreach (var (name, reference) in references) versions[name] = reference?["snapshot"]?.DeepClone();
        if ((string?)settings["employee_snapshot_id"] is { Length: > 0 } employees) versions["employees"] = employees;
        var findings = result.Users.Select(f => f.DeepClone().AsObject()).ToList();
        foreach (var finding in findings)
        {
            var riskId = (string)finding["risk_id"]!;
            var local = entries[riskId]?["metadata"] as JsonObject;
            var source = definitions[riskId];
            finding["risk"] = new JsonObject
            {
                ["display_name"] = (string?)local?["display_name"] ?? "", ["business_category"] = (string?)local?["business_category"] ?? "",
                ["source_text"] = (string?)source["source_text"] ?? "", ["risk_type"] = (string?)source["risk_type"] ?? "",
            };
            finding["source_versions"] = versions.DeepClone();
            finding["evaluation_as_of"] = evaluation.ToString("yyyy-MM-dd", CultureInfo.InvariantCulture);
        }
        var analysis = new JsonObject
        {
            ["generation"] = result.Generation, ["as_of"] = result.AsOf, ["users"] = new JsonArray([.. findings]), ["roles"] = new JsonArray([.. result.Roles.Select(r => (JsonNode?)r.DeepClone())]),
            ["summary"] = result.Summary.DeepClone(), ["coverage"] = result.Coverage.DeepClone(), ["methodology"] = result.Methodology.DeepClone(), ["sources"] = result.Sources.DeepClone(),
        };
        var baseline = await Service<SodReviewStore>(services).ListingAsync(findings, "current", result.Coverage, ct);
        var currentRows = new JsonArray([.. baseline["items"]!.AsArray().Where(r => (string?)r!["presence"] == "current").Select(r => r!.DeepClone())]);
        baseline["items"] = currentRows;
        baseline["summary"] = SodReviewStore.Summary(currentRows, SodReviewStore.Lifecycles);
        var users = c.Snapshot.Users;
        var complete = users.UserOrder.Where(k => users.Users[k].Assignments.Where(a => a.Scope != "other").All(a => a.MatchStatus is "exact" or "wildcard")).ToList();
        var cut = new JsonObject();
        foreach (var key in users.UserOrder)
            cut[key] = new JsonObject
            {
                ["assignments"] = new JsonArray([.. users.Users[key].Assignments.Select(a => (JsonNode?)new JsonObject
                {
                    ["role_name"] = a.RoleName, ["valid_from"] = a.ValidFrom, ["valid_to"] = a.ValidTo, ["user_group"] = a.UserGroup,
                    ["catalogue_roles"] = new JsonArray([.. a.CatalogueRoles.Select(r => (JsonNode?)r)]), ["match_status"] = a.MatchStatus, ["tcodes"] = new JsonArray([.. a.Tcodes.Select(t => (JsonNode?)t)]),
                })]),
            };
        var metadata = new JsonObject();
        foreach (var (name, reference) in settings["data_lifecycle"]?["sources"] as JsonObject ?? [])
            metadata[name] = new JsonObject { ["imported_at"] = reference?["imported_at"]?.DeepClone(), ["checked_at"] = reference?["checked_at"]?.DeepClone() };
        var saved = new JsonObject { ["version"] = 1, ["source"] = "sod-period" };
        if (!legacy) saved["model"] = 2;
        saved["period_id"] = id; saved["captured_at"] = Now(services); saved["evaluation_date"] = evaluation.ToString("yyyy-MM-dd", CultureInfo.InvariantCulture);
        saved["analysis"] = analysis; saved["risks"] = new JsonArray([.. riskItems.Select(r => (JsonNode?)r.DeepClone())]); saved["reviews"] = baseline;
        saved["source_versions"] = versions; saved["source_metadata"] = metadata;
        saved["source_counts"] = new JsonObject { ["users"] = users.Users.Count, ["roles"] = c.Snapshot.Catalogue.Roles.Count, ["matrix_records"] = c.Snapshot.Sod.Records.Count };
        saved["catalogue_names"] = new JsonArray([.. c.Snapshot.Catalogue.Roles.Keys.Select(k => (JsonNode?)k)]);
        saved["assignment_source"] = cut;
        saved["complete_users"] = new JsonArray([.. complete.Select(k => (JsonNode?)k)]);
        saved["metadata"] = FrozenMetadata(c, riskItems.Select(r => (string)r["risk_id"]!));
        saved["organization"] = settings["organization"]?.DeepClone(); saved["logo_id"] = settings["logo_id"]?.DeepClone();
        saved["identity_notice"] = IdentityNotice; saved["limitation"] = Limitation;
        return saved;
    }

    /// <summary>sod_metadata.frozen: the resolved descriptions of the given risks and their activities, as they are at capture time.</summary>
    private static JsonObject FrozenMetadata(V1SodCatalogue.Context c, IEnumerable<string> riskIds)
    {
        var resolved = V1SodCatalogue.Lookup(c);
        var wanted = riskIds.ToHashSet(StringComparer.Ordinal);
        var activityIds = (c.Snapshot.Sod?.Risks ?? []).Where(r => wanted.Contains((string)r["risk_id"]!)).SelectMany(V1SodCatalogue.Mappings).Select(m => m.Activity).ToHashSet(StringComparer.Ordinal);
        JsonObject Pick(JsonObject source, Func<string, bool> keep, string[] drop)
        {
            var result = new JsonObject();
            foreach (var (key, entry) in source)
            {
                if (!keep(key)) continue;
                var copy = new JsonObject();
                foreach (var (name, value) in entry!.AsObject()) if (!drop.Contains(name)) copy[name] = value?.DeepClone();
                if (copy.Count > 1) result[key] = copy;
            }
            return result;
        }
        var importedSource = new JsonObject();
        foreach (var (k, v) in c.Snapshot.Sod?.Metadata?.Source ?? new SortedDictionary<string, List<string>>()) importedSource[k] = new JsonArray([.. v.Select(x => (JsonNode?)x)]);
        var reference = c.Reference;
        importedSource["reference"] = new JsonObject
        {
            ["origin"] = reference["origin"]?.DeepClone(), ["library_version"] = reference["library_version"]?.DeepClone(), ["source"] = reference["source"]?.DeepClone(),
            ["version"] = reference["version"]?.DeepClone(), ["revision"] = reference["revision"]?.DeepClone(), ["digest"] = reference["digest"]?.DeepClone(),
            ["imported_at"] = reference["imported_at"]?.DeepClone(), ["risks"] = (reference["risks"] as JsonObject)?.Count ?? 0,
            ["activities"] = (reference["activities"] as JsonObject)?.Count ?? 0, ["terms"] = (reference["terms"] as JsonObject)?.Count ?? (reference["terms"] as JsonArray)?.Count ?? 0,
        };
        return new JsonObject
        {
            ["version"] = 1, ["risks"] = Pick(resolved["risks"]!.AsObject(), wanted.Contains, ["criticality", "type", "risks", "activities"]),
            ["activities"] = Pick(resolved["activities"]!.AsObject(), activityIds.Contains, ["risks", "risk_ids"]), ["source"] = importedSource,
        };
    }

    // ---- read models

    /// <summary>overlaid: an open period shows its own legacy review events over the captured baseline.</summary>
    private static async Task<JsonObject> OverlaidAsync(IServiceProvider services, JsonObject period, JsonObject saved, CancellationToken ct)
    {
        if (SodScope.FrozenStates.Contains((string)period["state"]!)) return saved;
        var local = await Service<SodReviewStore>(services).ListingAsync(saved["analysis"]!["users"]!.AsArray().Select(f => f!.AsObject()), (string)period["id"]!, saved["analysis"]!["coverage"], ct);
        var baseline = new Dictionary<string, JsonNode>(StringComparer.Ordinal);
        foreach (var row in saved["reviews"]!["items"]!.AsArray()) baseline[(string)row!["finding_id"]!] = row.DeepClone();
        foreach (var row in local["items"]!.AsArray()) if (row!["event"] is JsonObject) baseline[(string)row["finding_id"]!] = row.DeepClone();
        var rows = new JsonArray([.. baseline.Values]);
        var result = saved.DeepClone().AsObject();
        local["items"] = rows;
        local["summary"] = SodReviewStore.Summary(rows, SodReviewStore.Lifecycles);
        result["reviews"] = local;
        return result;
    }

    private static async Task<int> ReviewRevisionAsync(IServiceProvider services, JsonObject saved, CancellationToken ct) =>
        (int?)saved["model"] == 2 ? await Service<SodDecisionStore>(services).RevisionAsync(ct) : (int)(await Service<SodReviewStore>(services).ReadAsync(ct))["revision"]!;

    /// <summary>outstanding: review-population gaps of a v2 period (undecided or outdated activities and risk acceptances block approval).</summary>
    public static async Task<JsonObject> OutstandingAsync(IServiceProvider services, string id, CancellationToken ct)
    {
        var b = await SodScope.LoadAsync(services, id, "active", null, ct);
        var model = SodScope.ReviewModel(b);
        var state = await SodScope.StatesAsync(services, b, model, ct);
        var result = new JsonObject();
        var coverage = new JsonObject();
        foreach (var kind in new[] { "activity", "assignment", "acceptance" })
        {
            var counts = new JsonObject();
            foreach (var item in state.Items[kind].Values) counts[item.Lifecycle] = ((int?)counts[item.Lifecycle] ?? 0) + 1;
            result[kind] = counts;
            coverage[kind] = new JsonObject { ["decided"] = state.Coverage[kind].Values.Count(v => (bool?)v["reviewed"] ?? false), ["total"] = state.Coverage[kind].Count };
        }
        result["review_coverage"] = coverage;
        result["blocking"] = new[] { "activity", "acceptance" }.Sum(k => new[] { "Pending", "Outdated" }.Sum(n => (int?)result[k]![n] ?? 0));
        return result;
    }

    private static readonly Dictionary<string, JsonObject> ProgressCache = new(StringComparer.Ordinal);

    /// <summary>progress: canonical assessment coverage, memoized on its inputs (snapshot, state, approval, modification, decision and lifecycle revisions, today).</summary>
    public static async Task<JsonObject?> ProgressAsync(IServiceProvider services, JsonObject period, CancellationToken ct)
    {
        int lifecycle;
        await using (var db = await Service<IDbContextFactory<AuthLensDb>>(services).CreateDbContextAsync(ct))
            lifecycle = await db.SodDocuments.AsNoTracking().Where(d => d.Name == AssignmentLifecycle.Document).Select(d => d.Revision).FirstOrDefaultAsync(ct);
        var key = string.Join('|', period["id"], period["snapshot"], period["state"], period["approval_date"], period["modified"], await Service<SodDecisionStore>(services).RevisionAsync(ct),
            lifecycle, DateOnly.FromDateTime(DateTime.Now).ToString("yyyy-MM-dd", CultureInfo.InvariantCulture));
        lock (ProgressCache) if (ProgressCache.TryGetValue(key, out var hit)) return hit.DeepClone().AsObject();
        try
        {
            var saved = await Service<SodPeriodStore>(services).SnapshotAsync(period, ct);
            if ((int?)saved["model"] != 2) return null;
            var gaps = await OutstandingAsync(services, (string)period["id"]!, ct);
            var coverage = gaps["review_coverage"]!.AsObject();
            var result = new JsonObject
            {
                ["decided"] = coverage.Sum(p => (int)p.Value!["decided"]!), ["total"] = coverage.Sum(p => (int)p.Value!["total"]!), ["blocking"] = gaps["blocking"]!.DeepClone(),
            };
            lock (ProgressCache) { if (ProgressCache.Count >= 1024) ProgressCache.Clear(); ProgressCache[key] = result.DeepClone().AsObject(); }
            return result;
        }
        catch (Exception error) when (error is SodDecisionException or InvalidOperationException) { return null; }
    }

    // ---- operations

    private static string? Text(JsonObject body, string name) => body[name] is JsonValue v && v.TryGetValue<string>(out var t) ? t : null;

    /// <summary>The person a period change is attributed to (server_access.actor). A shared access token identifies nobody and is refused.</summary>
    private static async Task<(string? Name, JsonObject? Identity, IResult? Error)> ActorAsync(HttpContext http, CancellationToken ct) =>
        await V1SodDecisions.AttributionAsync(http, ct);

    public static async Task<IResult> CreateAsync(HttpContext http, CancellationToken ct)
    {
        var (body, invalid) = await V1Validation.ReadBody(http, ct);
        if (invalid is not null) return invalid;
        var errors = new List<object>();
        V1Validation.Extra(body!, ["name", "start", "end", "evaluation_date", "expected_revision"], errors);
        var name = V1Validation.Text(body!, "name", 1, 120, true, errors);
        DateOnly? Date(string field)
        {
            if (Text(body!, field) is { } t && DateOnly.TryParseExact(t, "yyyy-MM-dd", CultureInfo.InvariantCulture, DateTimeStyles.None, out var d)) return d;
            errors.Add(V1Validation.Error(body!.ContainsKey(field) ? "date_from_datetime_parsing" : "missing", field, body.ContainsKey(field) ? "Input should be a valid date" : "Field required"));
            return null;
        }
        var (start, end, evaluation) = (Date("start"), Date("end"), Date("evaluation_date"));
        if (body!["expected_revision"] is not JsonValue rv || !rv.TryGetValue<int>(out var revision) || revision < 0) { errors.Add(V1Validation.Error("missing", "expected_revision", "Field required")); revision = -1; }
        if (errors.Count > 0) return Results.Json(new { detail = errors }, statusCode: 422);
        var services = http.RequestServices;
        var store = Service<SodPeriodStore>(services);
        await store.Gate.WaitAsync(ct);
        try
        {
            var index = await store.ReadAsync(ct);
            if ((int)index["revision"]! != revision) throw new SodDecisionException(409, "Review periods changed. Reload before saving.");
            if (index["items"]!.AsArray().Count >= 250) throw new SodDecisionException(409, "Review period capacity reached; preserve a private backup before recovery.");
            if (start > end || !(start <= evaluation && evaluation <= end)) throw new SodDecisionException(422, "Choose a named period with an evaluation date within its start/end range.");
            var id = Guid.NewGuid().ToString("N");
            var stamp = Now(services);
            var saved = await CaptureAsync(services, id, evaluation!.Value, false, ct);
            var period = new JsonObject
            {
                ["id"] = id, ["name"] = name!.Trim(), ["start"] = start!.Value.ToString("yyyy-MM-dd", CultureInfo.InvariantCulture), ["end"] = end!.Value.ToString("yyyy-MM-dd", CultureInfo.InvariantCulture),
                ["evaluation_date"] = evaluation.Value.ToString("yyyy-MM-dd", CultureInfo.InvariantCulture), ["state"] = "Draft", ["snapshot"] = "", ["snapshots"] = new JsonArray(),
                ["created"] = stamp, ["modified"] = stamp, ["reviewer"] = "", ["approver"] = "", ["approval_date"] = null, ["deleted_at"] = null, ["rejection_reason"] = "", ["history"] = new JsonArray(),
            };
            var next = await store.SaveAsync(revision, (db, index, _) =>
            {
                var snapshot = PrivateSnapshots.Write(db, saved);
                period["snapshot"] = snapshot;
                period["snapshots"] = new JsonArray(snapshot);
                index["items"]!.AsArray().Add(period.DeepClone());
                return Task.CompletedTask;
            }, "", ct);
            return Json(new JsonObject { ["period"] = period, ["revision"] = next });
        }
        finally { store.Gate.Release(); }
    }

    private static JsonObject HistoryEvent(string stamp, string from, string to, string actor, JsonObject? identity, string note)
    {
        var e = new JsonObject();
        if (identity is not null) e["actor_identity"] = identity.DeepClone();
        e["timestamp"] = stamp; e["from_state"] = from; e["to_state"] = to; e["actor"] = actor; e["note"] = note;
        return e;
    }

    private static void Append(JsonObject period, string key, JsonNode value, int limit)
    {
        var list = period[key] as JsonArray ?? [];
        list.Add(value);
        while (list.Count > limit) list.RemoveAt(0);
        period[key] = list;
    }

    public static async Task<IResult> TransitionAsync(HttpContext http, string id, CancellationToken ct)
    {
        var (body, invalid) = await V1Validation.ReadBody(http, ct);
        if (invalid is not null) return invalid;
        var errors = new List<object>();
        V1Validation.Extra(body!, ["state", "expected_revision", "expected_review_revision", "reviewer", "approver", "approval_date", "confirm", "actor", "reason"], errors);
        var target = V1Validation.Text(body!, "state", 0, 40, true, errors) ?? "";
        V1Validation.Text(body!, "reviewer", 0, 120, false, errors); V1Validation.Text(body!, "approver", 0, 120, false, errors);
        V1Validation.Text(body!, "actor", 0, 120, false, errors);
        var reason = (V1Validation.Text(body!, "reason", 0, 2000, false, errors) ?? "").Trim();
        int Int(string field) { if (body![field] is JsonValue v && v.TryGetValue<int>(out var n) && n >= 0) return n; errors.Add(V1Validation.Error("missing", field, "Field required")); return -1; }
        var (revision, reviewRevision) = (Int("expected_revision"), Int("expected_review_revision"));
        DateOnly? approvalDate = null;
        if (body!["approval_date"] is JsonValue ad)
        {
            if (ad.TryGetValue<string>(out var t) && DateOnly.TryParseExact(t, "yyyy-MM-dd", CultureInfo.InvariantCulture, DateTimeStyles.None, out var d)) approvalDate = d;
            else errors.Add(V1Validation.Error("date_from_datetime_parsing", "approval_date", "Input should be a valid date"));
        }
        var confirm = body["confirm"] is JsonValue cv && cv.GetValueKind() == JsonValueKind.True;
        if (errors.Count > 0) return Results.Json(new { detail = errors }, statusCode: 422);
        // Every period state change is attributed to an individual (server session or the Desktop reviewer profile).
        var (actor, identity, refused) = await ActorAsync(http, ct);
        if (refused is not null) return refused;
        var reviewer = actor!;
        var approver = target is "Approved" or "Approved / closed" ? actor! : (Text(body, "approver") ?? "").Trim();
        var services = http.RequestServices;
        var store = Service<SodPeriodStore>(services);
        await store.Gate.WaitAsync(ct);
        try
        {
            var index = await store.ReadAsync(ct);
            if ((int)index["revision"]! != revision) throw new SodDecisionException(409, "Review periods changed. Reload before saving.");
            var period = SodPeriodStore.Find(index, id).DeepClone().AsObject();
            var saved = await store.SnapshotAsync(period, ct);
            var previous = (string)period["state"]!;
            JsonObject? newSnapshot = null;
            if ((int?)saved["model"] == 2)
            {
                if (!SodPeriodStore.Allowed.GetValueOrDefault(previous, []).Contains(target))
                {
                    if (SodScope.FrozenStates.Contains(previous) && target != "Closed") throw new SodDecisionException(409, "Approved snapshots are immutable. Create a new review period.");
                    throw new SodDecisionException(422, "Unsupported review-period transition.");
                }
                if (await Service<SodDecisionStore>(services).RevisionAsync(ct) != reviewRevision) throw new SodDecisionException(409, "Review decisions changed. Reload before changing period state.");
                if (target == "Rejected" && reason.Length == 0) throw new SodDecisionException(422, "A rejection requires a reason.");
                if (target is "Ready for approval" or "Approved" && (int)(await OutstandingAsync(services, id, ct))["blocking"]! > 0)
                    throw new SodDecisionException(409, "Complete or renew all activity reviews and risk acceptance decisions before approval preparation.");
                if (target == "Approved")
                {
                    if (!confirm || approvalDate is null) throw new SodDecisionException(422, "Confirm approval with self-reported reviewer, approver and approval date.");
                    var frozen = await Service<SodDecisionStore>(services).FreezeAsync(id, ct);
                    var actions = frozen["actions"]!.AsArray().Select(a => a!.AsObject()).ToList();
                    var tracked = actions.Where(a => (string?)a["assignment_id"] is { Length: > 0 } && (string?)a["recommended"] == "Remove assignment" && (string?)a["status"] != "Cancelled").ToList();
                    var (verify, _) = await SodScope.VerifierAsync(services, tracked.Select(a => (string)a["user"]!).Distinct(), ct);
                    var verification = new JsonObject();
                    foreach (var a in tracked) verification[(string)a["assignment_id"]!] = verify((string)a["user"]!, (string)a["assignment_id"]!);
                    frozen["verification"] = verification;
                    period["reviewer"] = reviewer; period["approver"] = approver; period["approval_date"] = approvalDate.Value.ToString("yyyy-MM-dd", CultureInfo.InvariantCulture);
                    newSnapshot = await OverlaidAsync(services, period, saved, ct);
                    var approval = new JsonObject { ["reviewer"] = reviewer, ["approver"] = approver, ["date"] = (string)period["approval_date"]!, ["actor"] = actor };
                    if (identity is not null) approval["actor_identity"] = identity.DeepClone();
                    approval["identity_notice"] = IdentityNotice;
                    newSnapshot["approval"] = approval;
                    newSnapshot["decisions"] = frozen;
                    newSnapshot["decision_summary"] = await OutstandingAsync(services, id, ct);
                }
                if (target == "Closed" && !confirm) throw new SodDecisionException(422, "Explicitly confirm closing an approved period.");
                if (target == "Rejected") period["rejection_reason"] = reason;
            }
            else
            {
                var allowed = new Dictionary<string, string[]> { ["Draft"] = ["In review"], ["In review"] = ["Draft", "Ready for approval"], ["Ready for approval"] = ["In review", "Approved / closed"] };
                if (SodScope.FrozenStates.Contains(previous)) throw new SodDecisionException(409, "Approved snapshots are immutable. Create a new review period.");
                if (!allowed.GetValueOrDefault(previous, []).Contains(target)) throw new SodDecisionException(422, "Unsupported review-period transition.");
                if ((int)(await Service<SodReviewStore>(services).ReadAsync(ct))["revision"]! != reviewRevision) throw new SodDecisionException(409, "Review decisions changed. Reload before changing period state.");
                var overlaid = await OverlaidAsync(services, period, saved, ct);
                if (target is "Ready for approval" or "Approved / closed" && overlaid["reviews"]!["items"]!.AsArray().Any(r => (string?)r!["lifecycle"] is "Pending" or "Outdated"))
                    throw new SodDecisionException(409, "Complete or renew all finding decisions before approval preparation.");
                if (target == "Approved / closed")
                {
                    if (!confirm || approvalDate is null) throw new SodDecisionException(422, "Confirm closure with self-reported reviewer, approver and approval date.");
                    period["reviewer"] = reviewer; period["approver"] = approver; period["approval_date"] = approvalDate.Value.ToString("yyyy-MM-dd", CultureInfo.InvariantCulture);
                    newSnapshot = overlaid;
                    newSnapshot["approval"] = new JsonObject { ["reviewer"] = reviewer, ["approver"] = approver, ["date"] = (string)period["approval_date"]!, ["identity_notice"] = IdentityNotice };
                }
            }
            if (newSnapshot is not null && period["snapshots"]!.AsArray().Count >= 100) throw new SodDecisionException(409, "Period snapshot capacity reached.");
            var stamp = Now(services);
            var next = await store.SaveAsync(revision, (db, index, _) =>
            {
                if (newSnapshot is not null)
                {
                    var snapshot = PrivateSnapshots.Write(db, newSnapshot);
                    period["snapshot"] = snapshot;
                    period["snapshots"]!.AsArray().Add(snapshot);
                }
                Append(period, "history", HistoryEvent(stamp, previous, target, actor!, identity, (int?)saved["model"] == 2 ? reason : reason), 500);
                period["state"] = target;
                period["modified"] = stamp;
                Replace(index, period);
                return Task.CompletedTask;
            }, actor!, ct);
            return Json(new JsonObject { ["period"] = period, ["revision"] = next });
        }
        finally { store.Gate.Release(); }
    }

    private static void Replace(JsonObject index, JsonObject period)
    {
        var items = index["items"]!.AsArray();
        var at = items.Select((p, i) => (p, i)).First(x => (string?)x.p!["id"] == (string?)period["id"]).i;
        items[at] = period.DeepClone();
    }

    public static async Task<IResult> RecaptureAsync(HttpContext http, string id, CancellationToken ct)
    {
        var (body, invalid) = await V1Validation.ReadBody(http, ct);
        if (invalid is not null) return invalid;
        var errors = new List<object>();
        V1Validation.Extra(body!, ["expected_revision", "confirm"], errors);
        if (body!["expected_revision"] is not JsonValue rv || !rv.TryGetValue<int>(out var revision) || revision < 0) { errors.Add(V1Validation.Error("missing", "expected_revision", "Field required")); revision = -1; }
        if (errors.Count > 0) return Results.Json(new { detail = errors }, statusCode: 422);
        var confirm = body["confirm"] is JsonValue cv && cv.GetValueKind() == JsonValueKind.True;
        var services = http.RequestServices;
        var store = Service<SodPeriodStore>(services);
        await store.Gate.WaitAsync(ct);
        try
        {
            var index = await store.ReadAsync(ct);
            if ((int)index["revision"]! != revision) throw new SodDecisionException(409, "Review periods changed. Reload before saving.");
            var period = SodPeriodStore.Find(index, id).DeepClone().AsObject();
            if ((string)period["state"]! is not ("Draft" or "In review") || !confirm) throw new SodDecisionException(409, "Explicitly confirm recapture of an open Draft/In review period.");
            if (period["snapshots"]!.AsArray().Count >= 100) throw new SodDecisionException(409, "Period snapshot capacity reached.");
            var legacy = (int?)(await store.SnapshotAsync(period, ct))["model"] != 2;
            var saved = await CaptureAsync(services, id, Day((string)period["evaluation_date"]!), legacy, ct);
            var stamp = Now(services);
            var next = await store.SaveAsync(revision, (db, index, _) =>
            {
                var snapshot = PrivateSnapshots.Write(db, saved);
                period["snapshot"] = snapshot;
                period["snapshots"]!.AsArray().Add(snapshot);
                period["modified"] = stamp;
                Replace(index, period);
                return Task.CompletedTask;
            }, "", ct);
            return Json(new JsonObject { ["period"] = period, ["revision"] = next });
        }
        finally { store.Gate.Release(); }
    }

    /// <summary>POST periods/{id}/reviews/{finding_id}: a legacy risk review recorded in an open period.</summary>
    public static async Task<IResult> ReviewAsync(HttpContext http, string id, string findingId, CancellationToken ct)
    {
        var (body, invalid) = await V1Validation.ReadBody(http, ct);
        if (invalid is not null) return invalid;
        var errors = new List<object>();
        V1Validation.Extra(body!, ["expected_revision", "expected_review_revision", "evidence_version", "annotation"], errors);
        int Int(string field) { if (body![field] is JsonValue v && v.TryGetValue<int>(out var n) && n >= 0) return n; errors.Add(V1Validation.Error("missing", field, "Field required")); return -1; }
        var (revision, reviewRevision) = (Int("expected_revision"), Int("expected_review_revision"));
        var evidence = V1Validation.Text(body!, "evidence_version", 64, 64, true, errors) ?? "";
        var (annotation, problem) = SodReviewStore.Annotation(body!["annotation"]);
        if (errors.Count > 0) return Results.Json(new { detail = errors }, statusCode: 422);
        if (problem is not null) return SodScope.Problem(422, problem);
        var (actor, identity, refused) = await ActorAsync(http, ct);
        if (refused is not null) return refused;
        annotation!["reviewer"] = actor;
        var services = http.RequestServices;
        var store = Service<SodPeriodStore>(services);
        var index = await store.ReadAsync(ct);
        if ((int)index["revision"]! != revision) throw new SodDecisionException(409, "Review periods changed. Reload before saving.");
        var period = SodPeriodStore.Find(index, id);
        if ((string)period["state"]! is not ("Draft" or "In review")) throw new SodDecisionException(409, "Only Draft/In review periods accept decisions.");
        var saved = await store.SnapshotAsync(period, ct);
        var finding = saved["analysis"]!["users"]!.AsArray().Select(f => f!.AsObject()).FirstOrDefault(f => (string?)f["finding_id"] == findingId)
            ?? throw new SodDecisionException(404, "Finding not present in this period snapshot.");
        return Json(await Service<SodReviewStore>(services).SaveAsync(finding, annotation, reviewRevision, evidence, id, identity, ct));
    }

    public static async Task<JsonObject> DetailsAsync(IServiceProvider services, string id, CancellationToken ct)
    {
        var store = Service<SodPeriodStore>(services);
        var index = await store.ReadAsync(ct);
        var period = SodPeriodStore.Find(index, id);
        var saved = await store.SnapshotAsync(period, ct);
        var current = await OverlaidAsync(services, period, saved, ct);
        var result = new JsonObject
        {
            ["period"] = period.DeepClone(), ["revision"] = index["revision"]!.DeepClone(), ["review_revision"] = await ReviewRevisionAsync(services, saved, ct), ["snapshot"] = current,
            ["checksum"] = period["snapshot"]!.DeepClone(), ["model"] = (int?)saved["model"] == 2 ? 2 : 1,
        };
        if ((int?)saved["model"] == 2) result["outstanding"] = await OutstandingAsync(services, id, ct);
        return result;
    }

    private static async Task<Dictionary<(string, string, string), string>> DecisionRowsAsync(IServiceProvider services, string id, CancellationToken ct)
    {
        var b = await SodScope.LoadAsync(services, id, "active", null, ct);
        var model = SodScope.ReviewModel(b);
        var state = await SodScope.StatesAsync(services, b, model, ct);
        return SodViews.QueueItems(model, state).ToDictionary(i => ((string)i["kind"]!, (string)i["user"]!, (string)i["ref"]!), i => (string)i["lifecycle"]!);
    }

    public static async Task<JsonObject> CompareAsync(IServiceProvider services, string leftId, string rightId, CancellationToken ct)
    {
        var store = Service<SodPeriodStore>(services);
        var index = await store.ReadAsync(ct);
        var (leftPeriod, rightPeriod) = (SodPeriodStore.Find(index, leftId), SodPeriodStore.Find(index, rightId));
        var (leftSaved, rightSaved) = (await store.SnapshotAsync(leftPeriod, ct), await store.SnapshotAsync(rightPeriod, ct));
        var left = await OverlaidAsync(services, leftPeriod, leftSaved, ct);
        var right = await OverlaidAsync(services, rightPeriod, rightSaved, ct);
        static Dictionary<string, JsonObject> Findings(JsonObject s) => s["analysis"]!["users"]!.AsArray().Select(f => f!.AsObject()).ToDictionary(f => (string)f["finding_id"]!, StringComparer.Ordinal);
        var (a, b) = (Findings(left), Findings(right));
        var previous = new HashSet<string>(StringComparer.Ordinal);
        foreach (var period in index["items"]!.AsArray().Select(p => p!.AsObject()))
            if (period["deleted_at"] is not JsonValue && (string)period["id"]! != leftId && string.CompareOrdinal((string)period["created"]!, (string)leftPeriod["created"]!) <= 0
                && SodScope.FrozenStates.Contains((string)period["state"]!) && string.CompareOrdinal((string)period["modified"]!, (string)leftPeriod["created"]!) <= 0)
                previous.UnionWith(Findings(await store.SnapshotAsync(period, ct)).Keys);
        static Dictionary<string, string> Versions(JsonObject s) => s["risks"]!.AsArray().ToDictionary(r => (string)r!["risk_id"]!, r => (string)r!["definition_version"]!, StringComparer.Ordinal);
        var (riskA, riskB) = (Versions(left), Versions(right));
        var enabled = right["risks"]!.AsArray().Where(r => ((bool?)r!["local"]?["enabled"] ?? false) && ((bool?)r["source"]?["supported"] ?? false)).Select(r => (string)r!["risk_id"]!).ToHashSet(StringComparer.Ordinal);
        var complete = (right["complete_users"] as JsonArray ?? []).Select(u => (string)u!).ToHashSet(StringComparer.Ordinal);
        var rightAvailable = (string?)right["analysis"]!["coverage"]!["status"] == "available";
        var changes = new JsonArray();
        static JsonNode? Brief(JsonObject? f) => f is null ? null : new JsonObject { ["subject"] = f["subject"]!.DeepClone(), ["risk_id"] = f["risk_id"]!.DeepClone(), ["evidence_version"] = f["evidence_version"]!.DeepClone() };
        foreach (var id in a.Keys.Concat(b.Keys).Distinct().Order(StringComparer.Ordinal))
        {
            string status;
            if (a.ContainsKey(id) && b.ContainsKey(id)) status = (string?)a[id]["evidence_version"] == (string?)b[id]["evidence_version"] ? "Unchanged" : "Changed";
            else if (b.ContainsKey(id)) status = previous.Contains(id) ? "Reopened" : "New";
            else
            {
                var old = a[id];
                var riskId = (string)old["risk_id"]!;
                var eligible = rightAvailable && complete.Contains((string)old["subject"]!) && enabled.Contains(riskId) && riskA.GetValueOrDefault(riskId) == riskB.GetValueOrDefault(riskId);
                status = eligible ? "Resolved" : "Not observed / coverage changed";
            }
            changes.Add(new JsonObject { ["finding_id"] = id, ["status"] = status, ["before"] = Brief(a.GetValueOrDefault(id)), ["after"] = Brief(b.GetValueOrDefault(id)) });
        }
        var summary = new JsonObject();
        foreach (var name in new[] { "New", "Resolved", "Unchanged", "Changed", "Reopened", "Not observed / coverage changed" }) summary[name] = changes.Count(c => (string?)c!["status"] == name);
        var result = new JsonObject
        {
            ["left"] = leftPeriod.DeepClone(), ["right"] = rightPeriod.DeepClone(), ["items"] = changes, ["summary"] = summary,
            ["changed_risks"] = new JsonArray([.. riskA.Keys.Concat(riskB.Keys).Distinct().Order(StringComparer.Ordinal).Where(r => riskA.GetValueOrDefault(r) != riskB.GetValueOrDefault(r)).Select(r => (JsonNode?)r)]),
            ["source_coverage_changed"] = !JsonNode.DeepEquals(left["source_counts"], right["source_counts"]),
            ["review_counts"] = new JsonObject { ["before"] = left["reviews"]!["summary"]!.DeepClone(), ["after"] = right["reviews"]!["summary"]!.DeepClone() },
        };
        if ((int?)leftSaved["model"] == 2 && (int?)rightSaved["model"] == 2)
        {
            var (before, after) = (await DecisionRowsAsync(services, leftId, ct), await DecisionRowsAsync(services, rightId, ct));
            result["decision_changes"] = new JsonArray([.. before.Keys.Concat(after.Keys).Distinct().OrderBy(k => k.Item1, StringComparer.Ordinal).ThenBy(k => k.Item2, StringComparer.Ordinal).ThenBy(k => k.Item3, StringComparer.Ordinal)
                .Where(k => before.GetValueOrDefault(k) != after.GetValueOrDefault(k)).Take(2000)
                .Select(k => (JsonNode?)new JsonObject { ["kind"] = k.Item1, ["user"] = k.Item2, ["ref"] = k.Item3, ["before"] = before.GetValueOrDefault(k), ["after"] = after.GetValueOrDefault(k) })]);
        }
        return result;
    }

    /// <summary>deletion_impact: what a deletion would remove, retain or affect; never changes state.</summary>
    public static async Task<JsonObject> DeletionImpactAsync(IServiceProvider services, string id, CancellationToken ct)
    {
        var store = Service<SodPeriodStore>(services);
        var index = await store.ReadAsync(ct);
        var period = SodPeriodStore.Find(index, id);
        var saved = await store.SnapshotAsync(period, ct);
        var summary = await Service<SodDecisionStore>(services).ContextSummaryAsync(id, ct);
        var legacy = (await Service<SodReviewStore>(services).ReadAsync(ct))["contexts"]![id] as JsonObject ?? [];
        var counts = new JsonObject
        {
            ["decisions"] = summary["events"]!.DeepClone(), ["legacy_risk_decisions"] = legacy.Sum(p => p.Value!.AsArray().Count), ["actions"] = summary["actions"]!.DeepClone(),
            ["reports"] = summary["reports"]!.AsArray().Count, ["dependents"] = summary["dependents"]!.AsArray().Count, ["snapshots"] = period["snapshots"]!.AsArray().Count,
        };
        var issued = summary["reports"]!.AsArray().Where(r => (string?)r!["status"] != "Draft").ToList();
        var frozen = SodScope.FrozenStates.Contains((string)period["state"]!);
        var dependents = summary["dependents"]!.AsArray().Count > 0;
        var empty = new[] { "decisions", "legacy_risk_decisions", "actions", "reports", "dependents" }.All(k => (int)counts[k]! == 0);
        var mode = (string)period["state"]! == "Draft" && empty ? "permanent" : "archive";
        var warnings = new JsonArray();
        if (frozen) warnings.Add("This period was approved or closed. Its frozen snapshot, approval record and decisions are retained but hidden from active work, matrices, comparisons and report generation.");
        if (issued.Count > 0) warnings.Add("Reports already issued from this period stay valid outside AuthLens. Their entries remain in the report log, but they cannot be regenerated from AuthLens afterwards.");
        if (dependents) warnings.Add("Reports that use this period as their comparison baseline keep their log entries; new comparisons against this period are no longer possible.");
        if (frozen || dependents) warnings.Add("Findings first seen in this period are classified as new rather than reopened in later comparisons.");
        return new JsonObject
        {
            ["id"] = id, ["name"] = period["name"]!.DeepClone(), ["state"] = period["state"]!.DeepClone(), ["mode"] = mode, ["counts"] = counts, ["reports"] = summary["reports"]!.DeepClone(),
            ["dependents"] = summary["dependents"]!.DeepClone(),
            ["consequences"] = mode == "permanent" ? "The empty draft is permanently deleted; its captured snapshot holds no decisions and stays unreferenced in the immutable evidence store. A deletion record is kept."
                : "The period is archived (tombstoned): hidden from active work and comparisons, with decisions, actions, snapshots and the report log retained for audit. A deletion record with the reason is kept.",
            ["warnings"] = warnings, ["requires_reason"] = frozen, ["requires_history_confirmation"] = frozen || issued.Count > 0 || dependents,
            ["model"] = (int?)saved["model"] == 2 ? 2 : 1, ["revision"] = index["revision"]!.DeepClone(),
        };
    }

    public static async Task<IResult> DeleteAsync(HttpContext http, string id, CancellationToken ct)
    {
        var (body, invalid) = await V1Validation.ReadBody(http, ct);
        if (invalid is not null) return invalid;
        var errors = new List<object>();
        V1Validation.Extra(body!, ["expected_revision", "confirm_name", "confirm_impact", "confirm_history", "reason", "actor"], errors);
        if (body!["expected_revision"] is not JsonValue rv || !rv.TryGetValue<int>(out var revision) || revision < 0) { errors.Add(V1Validation.Error("missing", "expected_revision", "Field required")); revision = -1; }
        var confirmName = V1Validation.Text(body, "confirm_name", 0, 120, true, errors) ?? "";
        var reason = (V1Validation.Text(body, "reason", 0, 2000, false, errors) ?? "").Trim();
        V1Validation.Text(body, "actor", 0, 120, false, errors);
        if (errors.Count > 0) return Results.Json(new { detail = errors }, statusCode: 422);
        bool Flag(string name) => body[name] is JsonValue v && v.GetValueKind() == JsonValueKind.True;
        var (actor, identity, refused) = await ActorAsync(http, ct);
        if (refused is not null) return refused;
        var services = http.RequestServices;
        var store = Service<SodPeriodStore>(services);
        await store.Gate.WaitAsync(ct);
        try
        {
            var index = await store.ReadAsync(ct);
            if ((int)index["revision"]! != revision) throw new SodDecisionException(409, "Review periods changed. Reload before saving.");
            var period = SodPeriodStore.Find(index, id).DeepClone().AsObject();
            var impact = await DeletionImpactAsync(services, id, ct);
            if (confirmName != (string)period["name"]!) throw new SodDecisionException(422, "Type the exact period name to confirm deletion.");
            if ((string)impact["mode"]! == "archive" && !Flag("confirm_impact")) throw new SodDecisionException(422, "Confirm the impact of archiving a period with recorded work.");
            if ((bool)impact["requires_history_confirmation"]! && !Flag("confirm_history"))
                throw new SodDecisionException(422, "Confirm that approved evidence, issued reports and dependent comparisons are retained but no longer available for active work.");
            if ((bool)impact["requires_reason"]! && reason.Length == 0) throw new SodDecisionException(422, "A reason is required to delete an approved or closed period.");
            var stamp = Now(services);
            var permanent = (string)impact["mode"]! == "permanent";
            var record = new JsonObject();
            if (identity is not null) record["actor_identity"] = identity.DeepClone();
            record["id"] = id; record["name"] = period["name"]!.DeepClone(); record["state"] = period["state"]!.DeepClone(); record["mode"] = permanent ? "permanent" : "archived";
            record["timestamp"] = stamp; record["actor"] = actor; record["counts"] = impact["counts"]!.DeepClone(); record["reason"] = reason;
            record["frozen"] = SodScope.FrozenStates.Contains((string)period["state"]!);
            var next = await store.SaveAsync(revision, async (db, index, token) =>
            {
                if (permanent)
                {
                    var items = index["items"]!.AsArray();
                    items.Remove(items.First(p => (string?)p!["id"] == id));
                    // v1 erased the draft's snapshot files. Here snapshots live in the immutable evidence store (delete is refused by a database
                    // trigger), so the draft's snapshot stays there, unreferenced and unreachable; only the period record is removed.
                    await Task.CompletedTask;
                }
                else
                {
                    Append(period, "history", HistoryEvent(stamp, (string)period["state"]!, "Archived", actor!, identity, reason), 500);
                    period["deleted_at"] = stamp;
                    period["modified"] = stamp;
                    Replace(index, period);
                }
                var deletions = index["deletions"]!.AsArray();
                deletions.Add(record.DeepClone());
                while (deletions.Count > 500) deletions.RemoveAt(0);
            }, actor!, ct);
            return Json(new JsonObject { ["deleted"] = record, ["revision"] = next });
        }
        finally { store.Gate.Release(); }
    }

    public static void Map(RouteGroupBuilder api)
    {
        api.MapGet("/sod/periods", (HttpContext http, CancellationToken ct) => Guard(async () =>
        {
            var services = http.RequestServices;
            var archived = SodScope.Flag(http.Request.Query["include_archived"].FirstOrDefault());
            var index = await Service<SodPeriodStore>(services).ReadAsync(ct);
            var items = new JsonArray();
            foreach (var item in index["items"]!.AsArray().Select(i => i!.AsObject()).Where(i => archived || i["deleted_at"] is not JsonValue))
            {
                var row = item.DeepClone().AsObject();
                row["progress"] = item["deleted_at"] is JsonValue ? null : await ProgressAsync(services, item, ct);
                items.Add(row);
            }
            var deletions = index["deletions"]!.AsArray();
            return Json(new JsonObject { ["revision"] = index["revision"]!.DeepClone(), ["items"] = items, ["deletions"] = new JsonArray([.. deletions.Skip(Math.Max(0, deletions.Count - 50)).Select(d => d!.DeepClone())]) });
        }));
        api.MapPost("/sod/periods", (HttpContext http, CancellationToken ct) => Guard(() => CreateAsync(http, ct)));
        api.MapGet("/sod/periods/compare", (HttpContext http, CancellationToken ct) => Guard(async () =>
        {
            var (left, right) = (http.Request.Query["left"].FirstOrDefault() ?? "", http.Request.Query["right"].FirstOrDefault() ?? "");
            if (!Regex.IsMatch(left, "^[a-f0-9]{32}$") || !Regex.IsMatch(right, "^[a-f0-9]{32}$")) return SodScope.Problem(422, "Choose two review periods.");
            return Json(await CompareAsync(http.RequestServices, left, right, ct));
        }));
        api.MapGet("/sod/periods/{id}", (string id, HttpContext http, CancellationToken ct) => Guard(async () =>
        {
            var q = http.Request.Query;
            var offset = int.TryParse(q["offset"].FirstOrDefault() ?? "0", out var o) ? o : -1;
            var limit = int.TryParse(q["limit"].FirstOrDefault() ?? "25", out var l) ? l : -1;
            if (offset < 0 || limit is < 1 or > 100) return SodScope.Problem(422, "offset must be >= 0 and limit between 1 and 100.");
            var data = await DetailsAsync(http.RequestServices, id, ct);
            var saved = data["snapshot"]!.AsObject();
            saved.Remove("decisions");
            var users = saved["analysis"]!["users"]!.AsArray();
            var rows = saved["reviews"]!["items"]!.AsArray();
            data["total"] = users.Count;
            saved["analysis"]!["users"] = new JsonArray([.. users.Skip(offset).Take(limit).Select(u => u!.DeepClone())]);
            saved["analysis"]!["roles"] = new JsonArray();
            saved["reviews"]!["items"] = new JsonArray([.. rows.Skip(offset).Take(limit).Select(r => r!.DeepClone())]);
            data["offset"] = offset;
            data["limit"] = limit;
            return Json(data);
        }));
        api.MapPost("/sod/periods/{id}/transition", (string id, HttpContext http, CancellationToken ct) => Guard(() => TransitionAsync(http, id, ct)));
        api.MapPost("/sod/periods/{id}/recapture", (string id, HttpContext http, CancellationToken ct) => Guard(() => RecaptureAsync(http, id, ct)));
        api.MapPost("/sod/periods/{id}/reviews/{findingId}", (string id, string findingId, HttpContext http, CancellationToken ct) => Guard(() => ReviewAsync(http, id, findingId, ct)));
        api.MapGet("/sod/periods/{id}/deletion-impact", (string id, HttpContext http, CancellationToken ct) => Guard(async () => Json(await DeletionImpactAsync(http.RequestServices, id, ct))));
        api.MapPost("/sod/periods/{id}/delete", (string id, HttpContext http, CancellationToken ct) => Guard(() => DeleteAsync(http, id, ct)));

        // Legacy risk reviews of the live context (routers/sod_reviews.py save, history and evidence).
        api.MapPost("/sod/reviews/{findingId}", (string findingId, HttpContext http, CancellationToken ct) => Guard(async () =>
        {
            var (body, invalid) = await V1Validation.ReadBody(http, ct);
            if (invalid is not null) return invalid;
            var errors = new List<object>();
            V1Validation.Extra(body!, ["expected_revision", "expected_generation", "evidence_version", "annotation"], errors);
            if (body!["expected_revision"] is not JsonValue rv || !rv.TryGetValue<int>(out var revision) || revision < 0) { errors.Add(V1Validation.Error("missing", "expected_revision", "Field required")); revision = -1; }
            var generation = V1Validation.Text(body, "expected_generation", 64, 64, true, errors) ?? "";
            var evidence = V1Validation.Text(body, "evidence_version", 64, 64, true, errors) ?? "";
            var (annotation, problem) = SodReviewStore.Annotation(body["annotation"]);
            if (errors.Count > 0) return Results.Json(new { detail = errors }, statusCode: 422);
            if (problem is not null) return SodScope.Problem(422, problem);
            var (actor, identity, refused) = await ActorAsync(http, ct);
            if (refused is not null) return refused;
            annotation!["reviewer"] = actor;
            var b = await SodScope.LoadAsync(http.RequestServices, "current", "active", null, ct);
            if (b.Generation != generation) throw new SodDecisionException(409, "SoD evidence changed. Reload before reviewing.");
            var finding = b.Findings.FirstOrDefault(f => (string?)f["finding_id"] == findingId);
            if (finding is null || !((bool?)finding["current_potential"] ?? false))
                throw new SodDecisionException(409, "Only current active-assignment findings can be reviewed here. Historical investigation is not current access evidence.");
            var copy = finding.DeepClone().AsObject();
            var versions = new JsonObject();
            foreach (var (k, v) in b.Versions) versions[k] = v;
            copy["source_versions"] = versions;
            copy["evaluation_as_of"] = b.AsOf;
            return Json(await Service<SodReviewStore>(http.RequestServices).SaveAsync(copy, annotation, revision, evidence, "current", identity, ct));
        }));
        // Listing, CSV exports and historical evidence of the legacy reviews (routers/sod_reviews.py). A historical finding stays Historical: the .NET port
        // never derives "Resolved" (v1 resolves a historical finding only after several source checks; not claiming resolution is the conservative side).
        api.MapGet("/sod/reviews", (HttpContext http, CancellationToken ct) => Guard(async () =>
        {
            var (rows, data, b, problem) = await LegacyReviewsAsync(http, ct);
            if (problem is not null) return problem;
            var offset = int.TryParse(http.Request.Query["offset"].FirstOrDefault() ?? "0", out var o) ? Math.Max(0, o) : 0;
            var limit = int.TryParse(http.Request.Query["limit"].FirstOrDefault() ?? "25", out var l) ? Math.Clamp(l, 1, 100) : 25;
            var page = new JsonArray();
            foreach (var row in rows.Skip(offset).Take(limit))
            {
                var copy = row.DeepClone().AsObject();
                var finding = copy["finding"]!.AsObject();
                var evidence = finding["evidence"] as JsonObject ?? [];
                finding["evidence_total"] = new JsonObject(evidence.Select(p => KeyValuePair.Create(p.Key, (JsonNode?)((p.Value as JsonArray)?.Count ?? 0))));
                finding["evidence"] = new JsonObject(evidence.Select(p => KeyValuePair.Create(p.Key, (JsonNode?)new JsonArray([.. (p.Value as JsonArray ?? []).Take(25).Select(x => x?.DeepClone())]))));
                page.Add(copy);
            }
            data!["items"] = page;
            data["total"] = rows.Count;
            data["offset"] = offset;
            data["limit"] = limit;
            data["generation"] = b!.Generation;
            data["as_of"] = b.AsOf;
            return Json(data);
        }));
        api.MapGet("/sod/reviews/export", (HttpContext http, CancellationToken ct) => Guard(() => LegacyExportAsync(http, false, ct)));
        api.MapGet("/sod/reviews/actions/export", (HttpContext http, CancellationToken ct) => Guard(() => LegacyExportAsync(http, true, ct)));
        api.MapGet("/sod/reviews/{findingId}/history/{eventId}/evidence", (string findingId, string eventId, HttpContext http, CancellationToken ct) => Guard(async () =>
        {
            var side = http.Request.Query["side"].FirstOrDefault() ?? "ACTVT1";
            if (side is not ("ACTVT1" or "ACTVT2")) return Results.Json(new { detail = new[] { new { type = "literal_error", loc = new[] { "query", "side" }, msg = "Input should be 'ACTVT1' or 'ACTVT2'" } } }, statusCode: 422);
            var store = Service<SodReviewStore>(http.RequestServices);
            var e = (await store.HistoryAsync(findingId, "current", ct)).FirstOrDefault(x => (string?)x["event_id"] == eventId);
            if (e is null) return Results.Json(new { detail = "Review event is not available." }, statusCode: 404);
            var finding = await store.FindingForEventAsync(e, ct);
            var rows = finding["evidence"]?[side] as JsonArray ?? [];
            var offset = int.TryParse(http.Request.Query["offset"].FirstOrDefault() ?? "0", out var o) ? Math.Max(0, o) : 0;
            var limit = int.TryParse(http.Request.Query["limit"].FirstOrDefault() ?? "25", out var l) ? Math.Clamp(l, 1, 100) : 25;
            return Json(new JsonObject
            {
                ["items"] = new JsonArray([.. rows.Skip(offset).Take(limit).Select(r => r?.DeepClone())]), ["total"] = rows.Count, ["offset"] = offset, ["limit"] = limit,
                ["source_versions"] = finding["source_versions"]?.DeepClone() ?? new JsonObject(), ["evaluation_as_of"] = finding["evaluation_as_of"]?.DeepClone(),
            });
        }));
        api.MapGet("/sod/reviews/{findingId}/history", (string findingId, HttpContext http, CancellationToken ct) => Guard(async () =>
        {
            var events = await Service<SodReviewStore>(http.RequestServices).HistoryAsync(findingId, "current", ct);
            var offset = int.TryParse(http.Request.Query["offset"].FirstOrDefault() ?? "0", out var o) ? Math.Max(0, o) : 0;
            var limit = int.TryParse(http.Request.Query["limit"].FirstOrDefault() ?? "25", out var l) ? Math.Clamp(l, 1, 100) : 25;
            return Json(new JsonObject
            {
                ["items"] = new JsonArray([.. events.Skip(offset).Take(limit)]), ["total"] = events.Count, ["offset"] = offset, ["limit"] = limit, ["reviewer_identity"] = IdentityNotice,
            });
        }));
    }

    private static readonly string[] ReviewSorts = ["subject", "risk_id", "decision", "modified", "target_date"];

    /// <summary>review_query + selected(): the legacy review rows of the live context after the v1 filters and sort.</summary>
    private static async Task<(List<JsonObject> Rows, JsonObject? Data, SodBundle? Bundle, IResult? Problem)> LegacyReviewsAsync(HttpContext http, CancellationToken ct)
    {
        var q = http.Request.Query;
        string Q(string name, int max) => (q[name].FirstOrDefault() ?? "") is var v && v.Length <= max ? v : throw new SodDecisionException(422, $"{name} is too long.");
        var (search, risk, decision, lifecycle, status, reviewer) = (Q("search", 256), Q("risk", 512), Q("decision", 100), Q("lifecycle", 64), Q("action_status", 64), Q("reviewer", 120));
        var sort = q["sort"].FirstOrDefault() ?? "subject";
        if (!ReviewSorts.Contains(sort)) return ([], null, null, Results.Json(new { detail = new[] { new { type = "literal_error", loc = new[] { "query", "sort" }, msg = "Input should be 'subject', 'risk_id', 'decision', 'modified' or 'target_date'" } } }, statusCode: 422));
        var descending = SodScope.Flag(q["descending"].FirstOrDefault());
        var b = await SodScope.LoadAsync(http.RequestServices, "current", "active", null, ct);
        var data = await Service<SodReviewStore>(http.RequestServices).ListingAsync(b.Findings, "current", b.Coverage, ct);
        var rows = new List<JsonObject>();
        foreach (var row in data["items"]!.AsArray().Select(r => r!.AsObject()))
        {
            var finding = row["finding"]!.AsObject();
            var annotation = row["event"]?["annotation"] as JsonObject ?? [];
            string A(string k) => (string?)annotation[k] ?? "";
            if (search.Length > 0 && !AuthLens.Domain.Text.TextMatching.SearchFields(search, (string?)finding["subject"], (string?)finding["risk_id"], A("reviewer"), A("rationale"))) continue;
            if ((risk.Length > 0 && risk != (string?)finding["risk_id"]) || (decision.Length > 0 && decision != (string?)row["decision"]) || (lifecycle.Length > 0 && lifecycle != (string?)row["lifecycle"])
                || (status.Length > 0 && status != A("action_status")) || (reviewer.Length > 0 && reviewer != A("reviewer"))) continue;
            rows.Add(row);
        }
        string Key(JsonObject row)
        {
            var e = row["event"] as JsonObject;
            var value = sort is "subject" or "risk_id" ? (string?)row["finding"]![sort] : sort == "decision" ? (string?)row["decision"] : sort == "modified" ? (string?)e?["timestamp"] : (string?)e?["annotation"]?["target_date"];
            return (value ?? "").PyCasefold();
        }
        var ordered = rows.OrderBy(Key, StringComparer.Ordinal).ThenBy(r => (string)r["finding_id"]!, StringComparer.Ordinal).ToList();
        if (descending) ordered.Reverse();
        return (ordered, data, b, null);
    }

    private static readonly string[] ReviewColumns = ["FINDING_ID", "USERNAME", "RISK", "DECISION", "LIFECYCLE", "EVIDENCE_FRESHNESS", "REVIEWER", "REVIEW_DATE", "JUSTIFICATION",
        "MITIGATING_CONTROLS", "ACTION_OWNER", "TARGET_DATE", "ACTION_STATUS", "COMPLETION_NOTES", "EVIDENCE_VERSION"];

    private static async Task<IResult> LegacyExportAsync(HttpContext http, bool actions, CancellationToken ct)
    {
        var (rows, _, _, problem) = await LegacyReviewsAsync(http, ct);
        if (problem is not null) return problem;
        if (actions) rows = [.. rows.Where(r => r["event"] is JsonObject e && (string?)e["annotation"]?["action_status"] is not ("Completed" or "Not applicable") && (string?)r["decision"] is "Access removal required" or "Further investigation required")];
        var sb = new StringBuilder("\uFEFF" + string.Join(';', ReviewColumns.Select(c => $"\"{c}\"")) + "\r\n");
        foreach (var row in rows)
        {
            var e = row["event"] as JsonObject;
            var a = e?["annotation"] as JsonObject ?? [];
            string A(string k) => (string?)a[k] ?? "";
            var values = new[] { (string?)row["finding_id"], (string?)row["finding"]!["subject"], (string?)row["finding"]!["risk_id"], (string?)row["decision"], (string?)row["lifecycle"],
                (bool?)row["stale"] == true ? "Outdated" : "Current", A("reviewer"), (string?)e?["timestamp"], A("rationale"), A("mitigating_controls"), A("action_owner"), A("target_date"), A("action_status"),
                A("completion_notes"), (string?)e?["evidence_version"] };
            sb.Append(string.Join(';', values.Select(v => "\"" + V1Csv.Cell(v).Replace("\"", "\"\"", StringComparison.Ordinal) + "\""))).Append("\r\n");
        }
        http.Response.Headers.CacheControl = "no-store";
        http.Response.Headers.ContentDisposition = $"attachment; filename=\"authlens-sod-{(actions ? "actions" : "reviews")}-{DateTime.Now:yyyy-MM-dd}.csv\"";
        return Results.Text(sb.ToString(), "text/csv; charset=utf-8", Encoding.UTF8);
    }
}
