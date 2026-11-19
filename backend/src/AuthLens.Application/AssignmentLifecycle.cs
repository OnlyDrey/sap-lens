using System.Security.Cryptography;
using System.Text;
using System.Text.Json.Nodes;
using Microsoft.EntityFrameworkCore;
using AuthLens.Domain.Directory;
using AuthLens.Domain.Json;
using AuthLens.Domain.Roles;
using AuthLens.Domain.Sod;
using AuthLens.Persistence;

namespace AuthLens.Application;

/// <summary>What the review views need from the lifecycle memory: when each assignment decision stops applying and why, or, when the memory cannot be
/// trusted, the reason every assignment decision stops applying (v1 assignment_lifecycle.Applicability).</summary>
public sealed record LifecycleApplicability(IReadOnlyDictionary<string, string> Reappeared, IReadOnlyDictionary<string, string> Reasons, string State, string Detail)
{
    public string? Unavailable => State == "ok" ? null : AssignmentLifecycle.Unavailable;
}

/// <summary>Port of assignment_lifecycle.py: minimal memory for decided assignments. An assignment with at least one decision event that becomes verifiably
/// absent from a committed users revision (the user fully mapped, or gone) and later returns, or whose user's identity evidence (unshared e-mail, full
/// name hashes) changes completely, makes its earlier decisions read Outdated until a new decision is recorded. Decision events are never changed; the
/// status is derived. If the memory is damaged (seal mismatch), missing although it was established, or older than the newest revision this database
/// recorded, every assignment decision reads Outdated until an administrator re-baselines. Stored as the "assignment-lifecycle" SoD document, with the
/// newest written revision kept separately ("assignment-lifecycle-meta"), like v1's file plus store meta.</summary>
/// <summary>Called after an import committed a new active dataset (v1 csv_lifecycle calls assignment_lifecycle.observe() there).</summary>
public interface IImportCommitted
{
    Task CommittedAsync(CancellationToken ct);
}

public sealed class AssignmentLifecycle(WriteCoordinator writer, IDbContextFactory<AuthLensDb> factory, SnapshotService snapshots, TimeProvider clock) : IImportCommitted
{
    public Task CommittedAsync(CancellationToken ct) => ObserveAsync(ct);

    public const string Document = "assignment-lifecycle", Meta = "assignment-lifecycle-meta";
    public const string Reappeared = "Assignment reappeared after it was removed from the SAP import; review it again. The earlier decision stays in history.";
    public const string Identity = "SAP user identity evidence (e-mail and name) changed since this assignment was reviewed; review it again. The earlier decision stays in history.";
    public const string Unavailable = "Review continuity data is unavailable or cannot be trusted, so the earlier decision cannot be confirmed for the same identity; review it again or re-baseline in Data Health. The earlier decision stays in history.";

    private static string Seal(JsonObject data)
    {
        var body = data.DeepClone().AsObject();
        body.Remove("digest");
        return Convert.ToHexStringLower(SHA256.HashData(Encoding.UTF8.GetBytes(CanonicalJson.Serialize(body))));
    }

    private static JsonObject Empty() => new() { ["version"] = 1, ["revision"] = 0, ["observed_source"] = "", ["baseline"] = new JsonObject(), ["digest"] = "", ["items"] = new JsonObject() };

    private static bool Valid(JsonObject data) =>
        (int?)data["version"] == 1 && data["revision"] is JsonValue && data["items"] is JsonObject items
        && items.All(p => p.Key.Length == 64 && p.Key.All(c => c is >= '0' and <= '9' or >= 'a' and <= 'f') && p.Value is JsonObject item && (string?)item["state"] is "present" or "absent")
        && ((string?)data["digest"] is not { Length: > 0 } digest || digest == Seal(data));

    /// <summary>load(): (data, state, detail); state is ok, corrupt, missing or stale. Anything but ok means continuity cannot be trusted.</summary>
    public static async Task<(JsonObject Data, string State, string Detail)> LoadAsync(AuthLensDb db, CancellationToken ct)
    {
        var rows = await db.SodDocuments.AsNoTracking().Where(d => d.Name == Document || d.Name == Meta).ToListAsync(ct);
        var stored = rows.FirstOrDefault(r => r.Name == Document);
        int? meta = rows.FirstOrDefault(r => r.Name == Meta)?.Revision;
        if (stored is null)
            return meta is null ? (Empty(), "ok", "") : (Empty(), "missing", "The lifecycle file is missing although this installation had written one before.");
        JsonObject? data;
        try { data = JsonNode.Parse(stored.Json) as JsonObject; }
        catch (System.Text.Json.JsonException) { data = null; }
        if (data is null || !Valid(data)) return (Empty(), "corrupt", "The lifecycle file is unreadable or failed its integrity check.");
        var revision = (int)data["revision"]!;
        if (meta is { } newest && revision < newest)
            return (data, "stale", $"The lifecycle file (revision {revision}) is older than the newest known state (revision {newest}), for example after restoring an old backup.");
        return (data, "ok", "");
    }

    public async Task<LifecycleApplicability> ApplicabilityAsync(CancellationToken ct)
    {
        await using var db = await factory.CreateDbContextAsync(ct);
        var (data, state, detail) = await LoadAsync(db, ct);
        if (state != "ok") return new(new Dictionary<string, string>(), new Dictionary<string, string>(), state, detail);
        var map = new Dictionary<string, string>(StringComparer.Ordinal);
        var reasons = new Dictionary<string, string>(StringComparer.Ordinal);
        foreach (var (key, item) in data["items"]!.AsObject())
            if ((string?)item!["reappeared_at"] is { Length: > 0 } at)
            {
                map[key] = at;
                reasons[key] = (string?)item["reason"] == "identity" ? Identity : Reappeared;
            }
        return new(map, reasons, "ok", "");
    }

    /// <summary>problems(): for Data Health, the integrity state, the decided assignments affected by an untrusted memory, and the assignments awaiting a
    /// new review because they came back or changed identity (until a newer decision is recorded).</summary>
    public async Task<(string State, string Detail, List<(string Key, string User, string Role, string Reason)> Affected, List<(string Key, string User, string Role, string Reason)> Pending)> ProblemsAsync(CancellationToken ct)
    {
        await using var db = await factory.CreateDbContextAsync(ct);
        var (data, state, detail) = await LoadAsync(db, ct);
        var rows = await db.SodDecisionEvents.AsNoTracking().Where(e => e.Kind == "assignment").OrderBy(e => e.Seq).Select(e => new { e.Key, e.Json }).ToListAsync(ct);
        var events = new Dictionary<string, (string Timestamp, string User, string Role)>(StringComparer.Ordinal);
        foreach (var row in rows)
        {
            var json = JsonNode.Parse(row.Json)!;
            var value = ((string)json["timestamp"]!, (string)json["user"]!, (string)json["ref"]!);
            if (!events.TryGetValue(row.Key, out var known) || string.CompareOrdinal(value.Item1, known.Timestamp) > 0) events[row.Key] = value;
        }
        if (state != "ok") return (state, detail, events.Select(p => (p.Key, p.Value.User, p.Value.Role, state)).ToList(), []);
        var pending = new List<(string, string, string, string)>();
        foreach (var (key, item) in data["items"]!.AsObject())
            if ((string?)item!["reappeared_at"] is { Length: > 0 } at && events.TryGetValue(key, out var e) && string.CompareOrdinal(e.Timestamp, at) < 0)
                pending.Add((key, e.User, e.Role, (string?)item["reason"] is { Length: > 0 } reason ? reason : "reappeared"));
        return ("ok", "", [], pending);
    }

    private static void Write(AuthLensDb db, SodDocument? row, SodDocument? metaRow, JsonObject data, DateTime now, string actor)
    {
        data["digest"] = "";
        data["digest"] = Seal(data);
        var revision = (int)data["revision"]!;
        if (row is null) db.SodDocuments.Add(row = new SodDocument { Name = Document, Json = "{}" });
        (row.Revision, row.Json, row.UpdatedUtc, row.UpdatedBy) = (revision, data.ToJsonString(), now, actor);
        if (metaRow is null) db.SodDocuments.Add(metaRow = new SodDocument { Name = Meta, Json = "{}" });
        if (revision > metaRow.Revision || metaRow.UpdatedUtc == default) (metaRow.Revision, metaRow.UpdatedUtc, metaRow.UpdatedBy) = (Math.Max(revision, metaRow.Revision), now, actor);
    }

    /// <summary>tokens(): hashed identity evidence of one SAP user (unshared e-mail addresses, complete names), at most 12.</summary>
    public static List<string> Tokens(AuthLens.Domain.Users.SapUser? user, IReadOnlySet<string> shared)
    {
        if (user is null) return [];
        static string Digest(string text) => Convert.ToHexStringLower(SHA256.HashData(Encoding.UTF8.GetBytes(text)))[..20];
        var found = new SortedSet<string>(StringComparer.Ordinal);
        foreach (var email in user.Emails)
            if (email.Trim().Length > 0 && !shared.Contains(EmployeeDirectory.Normalized(email))) found.Add(Digest("mail:" + EmployeeDirectory.Normalized(email)));
        foreach (var (first, last) in user.Names)
            if (first.Trim().Length > 0 && last.Trim().Length > 0) found.Add(Digest("name:" + EmployeeDirectory.Normalized(first) + " " + EmployeeDirectory.Normalized(last)));
        return found.Take(12).ToList();
    }

    private static async Task<(bool Sod, bool Mapping)> FeaturesAsync(AuthLensDb db, CancellationToken ct)
    {
        var json = await db.Settings.AsNoTracking().Select(s => s.Json).FirstOrDefaultAsync(ct);
        var features = json is null ? null : JsonNode.Parse(json)?["features"];
        return ((bool?)features?["sod"] ?? false, (bool?)features?["user_role_mapping"] ?? true);
    }

    /// <summary>observe(): compares the decided assignments with the active users revision. Returns "current", "unassessable", "blocked" or the number of
    /// changed items. Idempotent per users+catalogue revision; runs after every committed import and before review reads.</summary>
    public async Task<string> ObserveAsync(CancellationToken ct)
    {
        var snapshot = await snapshots.GetAsync(ct);
        return await writer.WriteAsync(async (db, token) =>
        {
            var (sod, mapping) = await FeaturesAsync(db, token);
            var datasets = await db.Datasets.AsNoTracking().Where(d => d.Status == DatasetStatus.Active && (d.Source == Sources.Users || d.Source == Sources.Roles))
                .Select(d => new { d.Id, d.Source, d.ContentHash }).ToListAsync(token);
            var users = datasets.FirstOrDefault(d => d.Source == Sources.Users);
            if (!sod || !mapping || snapshot.Catalogue.Roles.Count == 0 || snapshot.Sod is null || users is null || snapshot.Users.Users.Count == 0)
                return "unassessable";   // SoD or user mapping unavailable: absence cannot be established, nothing changes
            if (snapshot.Ids.Users != users.Id) return "unassessable";   // a newer dataset was published while this ran; the next read observes it
            var marker = $"{users.ContentHash}:{datasets.FirstOrDefault(d => d.Source == Sources.Roles)?.ContentHash ?? ""}";
            var (data, state, _) = await LoadAsync(db, token);
            if (state != "ok") return "blocked";   // untrusted memory is never repaired silently; an administrator re-baselines
            if ((string?)data["observed_source"] == marker) return "current";

            // verification_population(): every imported assignment identity, and the users whose eligible assignments are all mapped.
            var ids = new HashSet<string>(StringComparer.Ordinal);
            var complete = new HashSet<string>(StringComparer.Ordinal);
            foreach (var (name, record) in snapshot.Users.Users)
            {
                if (snapshot.Users.InvalidCataloguePatterns == 0 && record.Assignments.Where(a => a.Scope != "other").All(a => a.Resolved)) complete.Add(name);
                foreach (var a in record.Assignments) ids.Add(SodGovernance.AssignmentId(name, a.RoleName, a.ValidFrom, a.ValidTo, a.UserGroup));
            }
            var owners = new Dictionary<string, int>(StringComparer.Ordinal);
            foreach (var record in snapshot.Users.Users.Values)
                foreach (var email in record.Emails.Where(e => e.Trim().Length > 0).Select(EmployeeDirectory.Normalized).Distinct()) owners[email] = owners.GetValueOrDefault(email) + 1;
            var shared = owners.Where(p => p.Value > 1).Select(p => p.Key).ToHashSet(StringComparer.Ordinal);

            // decided(): the latest assignment event per key over every context -> its user.
            var events = await db.SodDecisionEvents.AsNoTracking().Where(e => e.Kind == "assignment").OrderBy(e => e.Seq).Select(e => new { e.Key, e.Json }).ToListAsync(token);
            var decided = new Dictionary<string, (string Timestamp, string User)>(StringComparer.Ordinal);
            foreach (var e in events)
            {
                var json = JsonNode.Parse(e.Json)!;
                var (timestamp, user) = ((string)json["timestamp"]!, (string)json["user"]!);
                if (!decided.TryGetValue(e.Key, out var known) || string.CompareOrdinal(timestamp, known.Timestamp) > 0) decided[e.Key] = (timestamp, user);
            }
            var items = data["items"]!.AsObject();
            var stamp = SodDecisionStore.Stamp(clock.GetUtcNow());
            var changed = 0;
            foreach (var (key, (_, decidedUser)) in decided.OrderBy(p => p.Key, StringComparer.Ordinal))
            {
                var user = RoleNames.NormalizeUsername(decidedUser);
                var item = items[key] as JsonObject;
                List<string> Recorded() => item?["identity"] is JsonArray list ? list.Select(v => (string)v!).ToList() : [];
                if (ids.Contains(key))
                {
                    var current = Tokens(snapshot.Users.Users.GetValueOrDefault(user), shared);
                    if (item is not null && (string?)item["state"] == "absent")
                    {
                        (item["state"], item["reappeared_at"], item["reappeared_source"], item["reason"]) = ("present", stamp, marker, "reappeared");
                        item["identity"] = new JsonArray([.. (current.Count > 0 ? current : Recorded()).Select(v => (JsonNode?)v)]);
                        changed++;
                    }
                    else if (item is not null && Recorded().Count > 0 && current.Count > 0 && !Recorded().Intersect(current).Any())
                    {
                        // Same username, same assignment, but nothing of the recorded person's evidence remains: probably someone else.
                        (item["reappeared_at"], item["reappeared_source"], item["reason"]) = (stamp, marker, "identity");
                        item["identity"] = new JsonArray([.. current.Select(v => (JsonNode?)v)]);
                        changed++;
                    }
                    else if (item is null || (current.Count > 0 && !current.SequenceEqual(Recorded())))
                    {
                        item ??= NewItem();
                        item["identity"] = new JsonArray([.. (current.Count > 0 ? current : Recorded()).Select(v => (JsonNode?)v)]);
                        items[key] = item;
                    }
                }
                else if (complete.Contains(user) || !snapshot.Users.Users.ContainsKey(user))
                {
                    // Verified absence, or the identity itself is gone from the source (a later user of the same name is not the same person).
                    if (item is null || (string?)item["state"] != "absent")
                    {
                        item ??= NewItem();
                        (item["state"], item["absent_since"], item["absent_source"]) = ("absent", stamp, marker);
                        items[key] = item;
                        changed++;
                    }
                }
                // present but only partly mapped (ambiguous): neither absent nor present, no change
            }
            data["observed_source"] = marker;
            var revision = (int)data["revision"]!;
            if (changed > 0 || revision == 0) data["revision"] = revision + 1;
            var rows = await db.SodDocuments.Where(d => d.Name == Document || d.Name == Meta).ToListAsync(token);
            Write(db, rows.FirstOrDefault(r => r.Name == Document), rows.FirstOrDefault(r => r.Name == Meta), data, clock.GetUtcNow().UtcDateTime, "lifecycle");
            return changed.ToString(System.Globalization.CultureInfo.InvariantCulture);
        }, ct);
    }

    private static JsonObject NewItem() => new()
    {
        ["state"] = "present", ["absent_since"] = "", ["absent_source"] = "", ["reappeared_at"] = "", ["reappeared_source"] = "", ["reason"] = "", ["identity"] = new JsonArray(),
    };

    /// <summary>rebaseline(): an administrator acknowledges the current data as the continuity baseline; the previous document is kept aside.</summary>
    public async Task<string> RebaselineAsync(string actor, CancellationToken ct)
    {
        await writer.WriteAsync(async (db, token) =>
        {
            var rows = await db.SodDocuments.Where(d => d.Name == Document || d.Name == Meta || d.Name.StartsWith("assignment-lifecycle-before")).ToListAsync(token);
            var row = rows.FirstOrDefault(r => r.Name == Document);
            var metaRow = rows.FirstOrDefault(r => r.Name == Meta);
            var now = clock.GetUtcNow();
            if (row is not null)
                db.SodDocuments.Add(new SodDocument { Name = "assignment-lifecycle-before-" + now.ToString("yyyyMMddHHmmss"), Json = row.Json, Revision = row.Revision, UpdatedUtc = now.UtcDateTime, UpdatedBy = actor });
            int old;
            try { old = row is null ? 0 : (int?)JsonNode.Parse(row.Json)?["revision"] ?? 0; }
            catch (System.Text.Json.JsonException) { old = 0; }
            var data = Empty();
            data["revision"] = Math.Max(old, metaRow?.Revision ?? 0) + 1;
            data["baseline"] = new JsonObject { ["by"] = actor.Length > 120 ? actor[..120] : actor, ["at"] = SodDecisionStore.Stamp(now) };
            Write(db, row, metaRow, data, now.UtcDateTime, actor);
            return 0;
        }, ct);
        return await ObserveAsync(ct);
    }
}
