using System.Globalization;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;
using Microsoft.EntityFrameworkCore;
using AuthLens.Domain.Json;
using AuthLens.Domain.Sod;
using AuthLens.Persistence;

namespace AuthLens.Application;

/// <summary>A refused SoD decision operation with the v1 HTTP status and message. Nothing was written.</summary>
public sealed class SodDecisionException(int status, string message) : Exception(message)
{
    public int Status { get; } = status;
}

/// <summary>One item of a decision call: the review item located in the current model, with the evidence it is decided against.</summary>
public sealed record SodDecisionItem(string Key, string User, string Ref, string EvidenceVersion, JsonNode Evidence);

public sealed record SodRecordRequest(string Kind, string Context, IReadOnlyList<SodDecisionItem> Items, string Decision, string Reviewer, string Justification,
    int ExpectedRevision, string Approver = "", string Controls = "", string? Expires = null, IReadOnlyDictionary<string, string>? SourceVersions = null,
    string BulkOperationId = "", JsonObject? ActorIdentity = null);

public sealed record SodRecordResult(IReadOnlyList<SodDecisionEvent> Events, int Revision);

/// <summary>Port of sod_decisions.py (record, latest, history, evidence_for) on SQLite. Events are append-only per (context, kind, key), hash-chained,
/// and keep the content-addressed evidence they were made against. One store-wide revision gives v1's optimistic concurrency: every write needs the
/// current revision and increases it by one. All items of a call are written in one transaction, or none.</summary>
public sealed partial class SodDecisionStore(WriteCoordinator writer, IDbContextFactory<AuthLensDb> factory, TimeProvider clock)
{
    public const int MaxEvents = 500, MaxKeys = 100_000, MaxBatch = 100, MaxBulk = 1000, MaxContexts = 1000;
    private const string RevisionDocument = "sod-decisions";

    [GeneratedRegex("^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")] public static partial Regex ContextPattern();
    [GeneratedRegex("^[a-f0-9]{64}$")] private static partial Regex Hex64();
    [GeneratedRegex("^([a-f0-9]{32})?$")] private static partial Regex Hex32OrEmpty();

    public static string CheckContext(string? context) =>
        context is not null && ContextPattern().IsMatch(context) ? context : throw new SodDecisionException(422, "Choose a supported review context identifier.");

    /// <summary>datetime.now(timezone.utc).isoformat(): microseconds (omitted when zero) and a +00:00 offset.</summary>
    public static string Stamp(DateTimeOffset now)
    {
        var utc = now.UtcDateTime;
        var micro = (utc.Ticks % TimeSpan.TicksPerSecond) / 10;
        return utc.ToString("yyyy-MM-dd'T'HH:mm:ss", CultureInfo.InvariantCulture) + (micro == 0 ? "" : "." + micro.ToString("000000", CultureInfo.InvariantCulture)) + "+00:00";
    }

    /// <summary>_clean: refuse control characters other than newline, carriage return and tab; strip surrounding whitespace.</summary>
    private static string Clean(string? value)
    {
        var text = value ?? "";
        if (text.Any(c => c < 32 && c is not ('\n' or '\r' or '\t'))) throw new SodDecisionException(422, "Text contains unsupported control characters.");
        return text.Trim();
    }

    /// <summary>The Event model's field and consistency validators.</summary>
    public static void Validate(SodDecisionEvent e)
    {
        void Check(bool ok, string message) { if (!ok) throw new SodDecisionException(422, message); }
        Check(SodGovernance.Decisions.ContainsKey(e.Kind), "Unsupported review type.");
        Check(ContextPattern().IsMatch(e.Context), "Choose a supported review context identifier.");
        Check(Hex64().IsMatch(e.Key) && Hex64().IsMatch(e.EvidenceVersion) && Hex64().IsMatch(e.EvidenceSnapshot), "Invalid review item identity.");
        Check(Hex32OrEmpty().IsMatch(e.BulkOperationId) && e.EventId.Length == 32, "Invalid event identity.");
        Check(e.User.Length is >= 1 and <= 512 && e.Ref.Length is >= 1 and <= 512, "Choose a valid review item.");
        Check(e.Reviewer.Length is >= 1 and <= 120, "A reviewer of 1-120 characters is required.");
        Check(e.Approver.Length <= 120 && e.Justification.Length <= 4000 && e.Controls.Length <= 8000 && e.Decision.Length <= 40 && e.PreviousDecision.Length <= 40, "Text is too long.");
        Check(SodGovernance.Decisions[e.Kind].Contains(e.Decision), "Unsupported decision for this review type.");
        Check(e.Justification.Length > 0, "A justification is required.");
        Check(!(e.Kind == "activity" && e.Decision == "Conditional" && e.Controls.Length == 0), "Describe the conditions before approving this activity conditionally.");
        Check(!(e.Kind == "acceptance" && e.Decision != "Pending" && e.Approver.Length == 0), "Risk acceptance and rejection require a named approver.");
        Check(e.Kind == "acceptance" || (e.Approver.Length == 0 && e.Expires is null), "Approver and expiry apply to risk acceptance only.");
        Check((e.SourceVersions?.Count ?? 0) <= 4, "Too many source versions.");
    }

    private static string ChainHash(string? previous, string json) =>
        Convert.ToHexStringLower(SHA256.HashData(Encoding.UTF8.GetBytes((previous ?? "") + "\n" + json)));

    public async Task<int> RevisionAsync(CancellationToken ct)
    {
        await using var db = await factory.CreateDbContextAsync(ct);
        return await db.SodDocuments.AsNoTracking().Where(d => d.Name == RevisionDocument).Select(d => (int?)d.Revision).FirstOrDefaultAsync(ct) ?? 0;
    }

    /// <summary>record(): appends one event per item atomically; all items share one decision and justification. <paramref name="guard"/> runs inside
    /// the same write transaction (the caller re-checks that the evidence generation is unchanged, like v1's publication guard).</summary>
    public Task<SodRecordResult> RecordAsync(SodRecordRequest request, Func<CancellationToken, Task>? guard, CancellationToken cancellation)
    {
        var context = CheckContext(request.Context);
        var limit = request.BulkOperationId.Length > 0 ? MaxBulk : MaxBatch;
        if (request.Items.Count == 0 || request.Items.Count > limit || request.Items.Select(i => i.Key).Distinct(StringComparer.Ordinal).Count() != request.Items.Count)
            throw new SodDecisionException(422, $"Choose between 1 and {limit} distinct items.");
        var now = clock.GetUtcNow();
        if (request.Expires is { } expires && DateOnly.ParseExact(expires, "yyyy-MM-dd", CultureInfo.InvariantCulture) < DateOnly.FromDateTime(now.LocalDateTime))
            throw new SodDecisionException(422, "The expiration date cannot be in the past.");
        var reviewer = Clean(request.Reviewer);
        var approver = Clean(request.Approver);
        var justification = Clean(request.Justification);
        var controls = Clean(request.Controls);
        return writer.WriteAsync(async (db, ct) =>
        {
            if (guard is not null) await guard(ct);
            var revisionRow = await db.SodDocuments.FirstOrDefaultAsync(d => d.Name == RevisionDocument, ct);
            if ((revisionRow?.Revision ?? 0) != request.ExpectedRevision) throw new SodDecisionException(409, "SoD decisions changed. Reload before saving.");
            var stamp = Stamp(now);
            var previousHash = await db.SodDecisionEvents.OrderByDescending(e => e.Seq).Select(e => e.Hash).FirstOrDefaultAsync(ct);
            var newKeys = 0;
            var events = new List<SodDecisionEvent>();
            foreach (var item in request.Items)
            {
                var evidence = new JsonObject { ["version"] = 1, ["source"] = "sod-decision-evidence", ["kind"] = request.Kind, ["evidence"] = item.Evidence.DeepClone() };
                var evidenceJson = CanonicalJson.Serialize(evidence);
                var identity = Convert.ToHexStringLower(SHA256.HashData(Encoding.UTF8.GetBytes(evidenceJson)));
                var history = await db.SodDecisionEvents.Where(e => e.Context == context && e.Kind == request.Kind && e.Key == item.Key)
                    .OrderByDescending(e => e.Seq).Select(e => e.Json).Take(1).ToListAsync(ct);
                var count = await db.SodDecisionEvents.CountAsync(e => e.Context == context && e.Kind == request.Kind && e.Key == item.Key, ct);
                if (count >= MaxEvents) throw new SodDecisionException(409, "SoD decision history capacity is reached for an item. Existing events are retained.");
                if (count == 0) newKeys++;
                var previous = history.Count == 0 ? "" : (string)JsonNode.Parse(history[0])!["decision"]!;
                var e = new SodDecisionEvent(Guid.NewGuid().ToString("N"), request.Kind, context, stamp, item.Key, Clean(item.User), Clean(item.Ref), request.Decision,
                    reviewer, justification, item.EvidenceVersion, identity, request.BulkOperationId, previous, approver, controls, request.Expires, request.SourceVersions,
                    request.ActorIdentity);
                Validate(e);
                if (await db.SodEvidenceSnapshots.FindAsync([identity], ct) is null && db.SodEvidenceSnapshots.Local.All(s => s.Sha256 != identity))
                    db.SodEvidenceSnapshots.Add(new SodEvidenceSnapshot { Sha256 = identity, Json = evidenceJson });
                var json = CanonicalJson.Serialize(e.ToJson());
                var hash = ChainHash(previousHash, json);
                db.SodDecisionEvents.Add(new SodDecisionRecord { EventId = e.EventId, Context = context, Kind = e.Kind, Key = e.Key, Json = json, PreviousHash = previousHash, Hash = hash });
                previousHash = hash;
                events.Add(e);
            }
            if (newKeys > 0)
            {
                var keys = await db.SodDecisionEvents.Select(e => new { e.Context, e.Kind, e.Key }).Distinct().CountAsync(ct);
                var contexts = await db.SodDecisionEvents.Select(e => e.Context).Distinct().CountAsync(ct);
                var newContext = contexts == 0 || !await db.SodDecisionEvents.AnyAsync(e => e.Context == context, ct);
                if (keys + newKeys > MaxKeys || contexts + (newContext ? 1 : 0) > MaxContexts)
                    throw new SodDecisionException(409, "SoD decision storage capacity or format is invalid. Existing history is retained.");
            }
            if (revisionRow is null) db.SodDocuments.Add(revisionRow = new SodDocument { Name = RevisionDocument, Json = "{}" });
            revisionRow.Revision = request.ExpectedRevision + 1;
            (revisionRow.UpdatedUtc, revisionRow.UpdatedBy) = (now.UtcDateTime, reviewer);
            return new SodRecordResult(events, revisionRow.Revision);
        }, cancellation);
    }

    public const int MaxActions = 20_000;
    private const string ActionsDocument = "sod-remediation-actions";
    public static readonly string[] Recommended = ["Remove assignment", "Investigate assignment", "Maintain access", "Apply compensating control", "No action required"];
    public static readonly string[] ActionStatuses = ["Open", "In progress", "Completed", "Cancelled"];
    private static readonly string[] ActionValueFields = ["user", "activity", "risk_id", "assignment_id", "role", "recommended", "reason", "owner", "due_date", "status", "completion_evidence"];
    private static readonly string[] TrackedChanges = ["recommended", "reason", "owner", "due_date", "status", "completion_evidence"];

    private static async Task<(SodDocument? Row, JsonObject Actions)> ActionsRowAsync(AuthLensDb db, bool tracked, CancellationToken ct)
    {
        var query = db.SodDocuments.Where(d => d.Name == ActionsDocument);
        var row = tracked ? await query.FirstOrDefaultAsync(ct) : await query.AsNoTracking().FirstOrDefaultAsync(ct);
        return (row, row is null ? new JsonObject() : JsonNode.Parse(row.Json)!.AsObject());
    }

    /// <summary>actions_for(): the remediation actions of one context, in creation order.</summary>
    public async Task<List<JsonObject>> ActionsAsync(string context, CancellationToken ct)
    {
        await using var db = await factory.CreateDbContextAsync(ct);
        var (_, actions) = await ActionsRowAsync(db, false, ct);
        return actions.Select(p => p.Value!.AsObject()).Where(a => (string?)a["context"] == context).ToList();
    }

    /// <summary>The Action model's validators on a candidate action (values already cleaned).</summary>
    private static void ValidateAction(JsonObject a)
    {
        void Check(bool ok, string message) { if (!ok) throw new SodDecisionException(422, message); }
        string Text(string name) => (string?)a[name] ?? "";
        Check(Text("user").Length is >= 1 and <= 512 && Text("activity").Length <= 512 && Text("risk_id").Length <= 512 && Text("role").Length <= 512 && Text("owner").Length <= 120
            && Text("reason").Length <= 4000 && Text("completion_evidence").Length <= 4000 && Text("assignment_id").Length <= 64 && Text("created_by").Length is >= 1 and <= 120, "Text is too long or missing.");
        Check(Recommended.Contains(Text("recommended")) && ActionStatuses.Contains(Text("status")), "Unsupported recommendation or status.");
        Check(!(Text("status") == "Completed" && Text("completion_evidence").Length == 0), "Completion evidence is required to complete an action.");
        Check(Text("reason").Length > 0, "A reason is required.");
        Check(Text("assignment_id").Length == 0 || Hex64().IsMatch(Text("assignment_id")), "Invalid assignment identity.");
    }

    /// <summary>save_action(): creates or updates a remediation action; every change is appended to its history. Shares the decision revision.</summary>
    public Task<(JsonObject Action, int Revision)> SaveActionAsync(string context, JsonObject values, string actor, JsonObject? identity, int expectedRevision, string actionId,
        Func<AuthLensDb, CancellationToken, Task>? alsoInTransaction, CancellationToken cancellation)
    {
        CheckContext(context);
        var cleaned = new JsonObject();
        foreach (var field in ActionValueFields)
            cleaned[field] = field == "due_date" ? values[field]?.DeepClone() : Clean((string?)values[field] ?? "");
        var by = Clean(actor);
        return writer.WriteAsync(async (db, ct) =>
        {
            var revisionRow = await db.SodDocuments.FirstOrDefaultAsync(d => d.Name == RevisionDocument, ct);
            if ((revisionRow?.Revision ?? 0) != expectedRevision) throw new SodDecisionException(409, "SoD decisions changed. Reload before saving.");
            var now = clock.GetUtcNow();
            var stamp = Stamp(now);
            var (row, actions) = await ActionsRowAsync(db, true, ct);
            var previous = actionId.Length > 0 ? actions[actionId] as JsonObject : null;
            if (actionId.Length > 0 && previous is null) throw new SodDecisionException(404, "Remediation action not found.");
            if (previous is not null && (string?)previous["context"] != context) throw new SodDecisionException(422, "An action cannot move to another review context.");
            if (previous is null && actions.Count >= MaxActions) throw new SodDecisionException(409, "Remediation action capacity is reached. Existing actions are retained.");
            JsonObject Event(string note)
            {
                var e = new JsonObject();
                if (identity is not null) e["actor_identity"] = identity.DeepClone();
                (e["timestamp"], e["actor"], e["note"]) = (stamp, by, note);
                return e;
            }
            JsonObject entry;
            if (previous is not null)
            {
                string Old(string name) => previous[name] is JsonValue v ? v.ToString() : "";
                string New(string name) => cleaned[name] is JsonValue v ? v.ToString() : "";
                var changes = TrackedChanges.Where(n => Old(n) != New(n)).Select(n => $"{n}: {(Old(n).Length > 0 ? Old(n) : "-")} → {(New(n).Length > 0 ? New(n) : "-")}").ToList();
                entry = previous.DeepClone().AsObject();
                foreach (var (k, v) in cleaned) entry[k] = v?.DeepClone();
                entry["modified"] = stamp;
                var history = entry["history"]!.AsArray();
                if (history.Count >= 500) throw new SodDecisionException(422, "Action history capacity is reached.");
                history.Add(Event(changes.Count > 0 ? string.Join("; ", changes) : "Reviewed"));
            }
            else
            {
                entry = new JsonObject { ["id"] = Guid.NewGuid().ToString("N"), ["context"] = context };
                foreach (var (k, v) in cleaned) entry[k] = v?.DeepClone();
                (entry["created"], entry["modified"], entry["created_by"]) = (stamp, stamp, by);
                entry["history"] = new JsonArray(Event("Created"));
            }
            ValidateAction(entry);
            actions[(string)entry["id"]!] = entry;
            if (row is null) db.SodDocuments.Add(row = new SodDocument { Name = ActionsDocument, Json = "{}" });
            (row.Json, row.Revision, row.UpdatedUtc, row.UpdatedBy) = (actions.ToJsonString(), row.Revision + 1, now.UtcDateTime, by);
            if (alsoInTransaction is not null) await alsoInTransaction(db, ct);
            if (revisionRow is null) db.SodDocuments.Add(revisionRow = new SodDocument { Name = RevisionDocument, Json = "{}" });
            revisionRow.Revision = expectedRevision + 1;
            (revisionRow.UpdatedUtc, revisionRow.UpdatedBy) = (now.UtcDateTime, by);
            return (entry.DeepClone().AsObject(), revisionRow.Revision);
        }, cancellation);
    }

    /// <summary>latest(): kind -> key -> most recent event of one context.</summary>
    public async Task<Dictionary<string, IReadOnlyDictionary<string, SodDecisionEvent>>> LatestAsync(string context, CancellationToken ct)
    {
        await using var db = await factory.CreateDbContextAsync(ct);
        var rows = await db.SodDecisionEvents.AsNoTracking().Where(e => e.Context == context).OrderBy(e => e.Seq).Select(e => new { e.Kind, e.Key, e.Json }).ToListAsync(ct);
        var result = SodGovernance.Decisions.Keys.ToDictionary(k => k, _ => (IReadOnlyDictionary<string, SodDecisionEvent>)new Dictionary<string, SodDecisionEvent>(StringComparer.Ordinal), StringComparer.Ordinal);
        foreach (var row in rows) ((Dictionary<string, SodDecisionEvent>)result[row.Kind])[row.Key] = SodDecisionEvent.FromJson(JsonNode.Parse(row.Json)!.AsObject());
        return result;
    }

    /// <summary>history(): the events of one item, newest first.</summary>
    public async Task<List<JsonObject>> HistoryAsync(string kind, string context, string key, CancellationToken ct)
    {
        if (!SodGovernance.Decisions.ContainsKey(kind) || !Hex64().IsMatch(key)) throw new SodDecisionException(422, "Choose a valid review item.");
        CheckContext(context);
        await using var db = await factory.CreateDbContextAsync(ct);
        var rows = await db.SodDecisionEvents.AsNoTracking().Where(e => e.Context == context && e.Kind == kind && e.Key == key).OrderByDescending(e => e.Seq).Select(e => e.Json).ToListAsync(ct);
        return rows.Select(json => JsonNode.Parse(json)!.AsObject()).ToList();
    }

    /// <summary>evidence_for(): the retained evidence of one event, verified against its content address.</summary>
    public async Task<JsonNode?> EvidenceAsync(JsonObject e, CancellationToken ct)
    {
        await using var db = await factory.CreateDbContextAsync(ct);
        var identity = (string?)e["evidence_snapshot"] ?? "";
        var saved = await db.SodEvidenceSnapshots.AsNoTracking().FirstOrDefaultAsync(s => s.Sha256 == identity, ct);
        JsonNode? parsed = null;
        var valid = saved is not null && Convert.ToHexStringLower(SHA256.HashData(Encoding.UTF8.GetBytes(saved.Json))) == identity
            && (parsed = JsonNode.Parse(saved.Json)) is JsonObject o && (string?)o["source"] == "sod-decision-evidence" && (string?)o["kind"] == (string?)e["kind"] && (int?)o["version"] == 1;
        if (!valid) throw new SodDecisionException(409, "Retained decision evidence is unavailable or invalid. History is preserved; restore its snapshot from a private backup.");
        return parsed!["evidence"]?.DeepClone();
    }

    /// <summary>Recomputes the event chain; any edited, removed or reordered event breaks it. Also checks that every event names an existing evidence snapshot.</summary>
    /// <summary>freeze: complete copy of one context (every event per kind and key, in order, and its actions) for an immutable period snapshot.</summary>
    public async Task<JsonObject> FreezeAsync(string context, CancellationToken ct)
    {
        await using var db = await factory.CreateDbContextAsync(ct);
        var rows = await db.SodDecisionEvents.AsNoTracking().Where(e => e.Context == context).OrderBy(e => e.Seq).Select(e => new { e.Kind, e.Key, e.Json }).ToListAsync(ct);
        var events = new JsonObject();
        foreach (var kind in SodGovernance.Decisions.Keys) events[kind] = new JsonObject();
        foreach (var row in rows)
        {
            var kind = events[row.Kind]!.AsObject();
            if (kind[row.Key] is not JsonArray list) kind[row.Key] = list = [];
            list.Add(JsonNode.Parse(row.Json));
        }
        return new JsonObject { ["events"] = events, ["actions"] = new JsonArray([.. (await ActionsAsync(context, ct)).Select(a => (JsonNode?)a.DeepClone())]) };
    }

    public const string ReportLog = "sod-report-log";
    public const int MaxReports = 5000;

    /// <summary>The report log (sod_decisions.Storage.reports): one immutable entry per issued or draft report.</summary>
    public async Task<List<JsonObject>> ReportsAsync(CancellationToken ct)
    {
        await using var db = await factory.CreateDbContextAsync(ct);
        var row = await db.SodDocuments.AsNoTracking().FirstOrDefaultAsync(d => d.Name == ReportLog, ct);
        return row is null ? [] : [.. (JsonNode.Parse(row.Json)?["reports"] as JsonArray ?? []).Select(r => r!.AsObject())];
    }

    /// <summary>log_report: appends one entry; existing entries are never changed.</summary>
    public Task<JsonObject> LogReportAsync(JsonObject entry, CancellationToken ct) => writer.WriteAsync(async (db, token) =>
    {
        var row = await db.SodDocuments.FirstOrDefaultAsync(d => d.Name == ReportLog, token);
        var data = row is null ? new JsonObject { ["reports"] = new JsonArray() } : JsonNode.Parse(row.Json)!.AsObject();
        var reports = data["reports"]!.AsArray();
        if (reports.Count >= MaxReports) throw new SodDecisionException(409, "Report log capacity is reached. Existing entries are retained.");
        reports.Add(entry.DeepClone());
        if (row is null) db.SodDocuments.Add(row = new SodDocument { Name = ReportLog, Json = "{}" });
        (row.Json, row.Revision, row.UpdatedUtc, row.UpdatedBy) = (data.ToJsonString(), row.Revision + 1, clock.GetUtcNow().UtcDateTime, (string?)entry["prepared_by"] ?? "");
        return entry;
    }, ct);

    /// <summary>context_summary: counts used for a period's deletion impact, including reports issued from or comparing against it.</summary>
    public async Task<JsonObject> ContextSummaryAsync(string context, CancellationToken ct)
    {
        await using var db = await factory.CreateDbContextAsync(ct);
        var keys = await db.SodDecisionEvents.AsNoTracking().Where(e => e.Context == context).GroupBy(e => new { e.Kind, e.Key }).Select(g => new { g.Key.Kind, Count = g.Count() }).ToListAsync(ct);
        var reports = await ReportsAsync(ct);
        return new JsonObject
        {
            ["activity"] = keys.Count(k => k.Kind == "activity"), ["assignment"] = keys.Count(k => k.Kind == "assignment"), ["acceptance"] = keys.Count(k => k.Kind == "acceptance"),
            ["events"] = keys.Sum(k => k.Count), ["actions"] = (await ActionsAsync(context, ct)).Count,
            ["reports"] = new JsonArray([.. reports.Where(r => (string?)r["period_id"] == context).Select(r => (JsonNode?)r.DeepClone())]),
            ["dependents"] = new JsonArray([.. reports.Where(r => (string?)r["previous_period_id"] == context && (string?)r["period_id"] != context).Select(r => (JsonNode?)r.DeepClone())]),
        };
    }

    public async Task<(bool Ok, long? BrokenAt, int Count)> VerifyChainAsync(CancellationToken ct)
    {
        await using var db = await factory.CreateDbContextAsync(ct);
        string? previous = null;
        var count = 0;
        await foreach (var row in db.SodDecisionEvents.AsNoTracking().OrderBy(e => e.Seq).AsAsyncEnumerable().WithCancellation(ct))
        {
            if (row.PreviousHash != previous || ChainHash(previous, row.Json) != row.Hash) return (false, row.Seq, count);
            previous = row.Hash;
            count++;
        }
        return (true, null, count);
    }
}
