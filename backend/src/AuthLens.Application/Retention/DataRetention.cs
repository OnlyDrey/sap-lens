using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;
using Microsoft.EntityFrameworkCore;
using AuthLens.Application.Backups;
using AuthLens.Persistence;

namespace AuthLens.Application.Retention;

/// <summary>Data retention (v1 data_retention.py, review_retention.py and backup_retention.py) on the AuthLens database, in three categories with their
/// own period, preview digest and one-time administrator approval. A daily check only measures until a category is approved for this installation.
///
/// * Source: the records of superseded (Retired) source revisions (the revision row stays as Purged evidence), aged from the moment the next revision of the same source was activated (no moment: protected until
///   classified). Protected by reference: any revision whose content hash appears in settings, SoD documents (periods, assessments, remediation, catalogue),
///   decision events, evidence snapshots or refresh reports (audit history), or that review decisions or invalidations name; also the newest two superseded
///   revisions per source and everything younger than the period (default 24 months). Removal is one transaction per revision, re-checked immediately before.
/// * Review: AuthLens keeps completed review periods. Their snapshots are immutable audit evidence (database triggers forbid deletion) and a closed period
///   alone is no deletion reason, so the review preview lists completed periods as protected and never removes them. This deliberately differs from v1.
/// * Backup: automatic backups older than the period (default 90 days); manual and migration backups are never candidates.
///
/// State lives in data-retention.json in the data directory, outside the data an application restore replaces. Approvals are bound to the installation
/// identity (.installation-id, never in a backup); a restore voids approvals and pauses cleanup for 7 days.</summary>
public sealed partial class DataRetention(DatabaseOptions options, IDbContextFactory<AuthLensDb> factory, TimeProvider clock, WriteCoordinator? writer = null)
{
    private readonly WriteCoordinator _writer = writer ?? new WriteCoordinator(factory);

    public const int DefaultMonths = 24, MinMonths = 6, MaxMonths = 120, DefaultDays = 90, MinDays = 7, MaxDays = 3650, KeepPerSource = 2;
    public static readonly string[] Categories = ["source", "review", "backup"];
    private static readonly string[] Frozen = ["Approved", "Closed", "Approved / closed"];
    private static readonly SemaphoreSlim Gate = new(1, 1);
    [GeneratedRegex("[a-f0-9]{64}")] private static partial Regex Hex();
    [GeneratedRegex("\"migrated_from_v1\":\\{\"snapshot\":\"([a-f0-9]{64})\"")] private static partial Regex V1Alias();

    private string Data => options.DataDirectory;
    private static string FileOf(string data) => Path.Combine(data, "data-retention.json");
    private static string Iso(DateTimeOffset value) => value.ToUniversalTime().ToString("yyyy-MM-dd'T'HH:mm:ss'+00:00'");
    private static string Iso(DateTime value) => Iso(new DateTimeOffset(DateTime.SpecifyKind(value, DateTimeKind.Utc)));

    /// <summary>This installation's identity: random, private, never part of an application backup.</summary>
    public static string Instance(string data)
    {
        var path = Path.Combine(data, ".installation-id");
        if (File.Exists(path) && File.ReadAllText(path).Trim() is { Length: 32 } existing && ApplicationBackups.Identity().IsMatch(existing)) return existing;
        Directory.CreateDirectory(data);
        var created = Convert.ToHexStringLower(RandomNumberGenerator.GetBytes(16));
        try { using var stream = new FileStream(path, FileMode.CreateNew, FileAccess.Write); stream.Write(Encoding.ASCII.GetBytes(created)); }
        catch (IOException) { return File.ReadAllText(path).Trim(); }
        return created;
    }

    // ---- state

    public static JsonObject Read(string data)
    {
        JsonObject Empty() => new()
        {
            ["version"] = 1, ["revision"] = 0, ["policy"] = new JsonObject { ["enabled"] = true, ["months"] = DefaultMonths, ["review_months"] = DefaultMonths, ["backup_days"] = DefaultDays },
            ["approvals"] = new JsonObject(), ["quiet_until"] = "", ["last_check"] = "", ["last_cleanup"] = new JsonObject(), ["last_preview"] = new JsonObject(), ["history"] = new JsonArray(),
        };
        try
        {
            var path = FileOf(data);
            if (!File.Exists(path) || new FileInfo(path).Length > 512_000) return Empty();
            if (JsonNode.Parse(File.ReadAllText(path)) is not JsonObject value || value["policy"] is not JsonObject policy) return Empty();
            var empty = Empty();
            foreach (var (key, node) in empty) value[key] ??= node!.DeepClone();
            foreach (var (key, node) in empty["policy"]!.AsObject()) policy[key] ??= node!.DeepClone();
            return value;
        }
        catch (Exception error) when (error is IOException or JsonException) { return Empty(); }
    }

    private static void Write(string data, JsonObject value)
    {
        value["revision"] = (Int(value["revision"]) ?? 0) + 1;
        BackupKeys.WriteAtomic(FileOf(data), value.ToJsonString());
    }

    private static int? Int(JsonNode? node) => node is JsonValue v && v.GetValueKind() == JsonValueKind.Number && int.TryParse(v.ToJsonString(), out var i) ? i : null;
    private static int Period(JsonObject state, string category) => Int(state["policy"]![category switch { "source" => "months", "review" => "review_months", _ => "backup_days" }]) ?? (category == "backup" ? DefaultDays : DefaultMonths);

    private bool Approved(JsonObject state, string category) =>
        state["approvals"]?[category] is JsonObject a && (string?)a["instance"] == Instance(Data) && Period(state, category) >= (Int(a["period"]) ?? int.MaxValue);

    private string Label(JsonObject state, string category) => state["policy"]!["enabled"]?.GetValue<bool>() != true ? "disabled" : Approved(state, category) ? "approved" : "awaiting_approval";

    private static void Append(JsonObject state, JsonObject entry)
    {
        var history = state["history"] as JsonArray ?? [];
        history.Add(entry);
        while (history.Count > 100) history.RemoveAt(0);
        state["history"] = history.DeepClone();
    }

    /// <summary>After a restore: approvals are void and no cleanup runs for 7 days, so recovered records are not removed again before an administrator looked.</summary>
    public static void AfterRestore(string data, DateTimeOffset now)
    {
        var state = Read(data);
        state["approvals"] = new JsonObject();
        state["quiet_until"] = Iso(now.AddDays(7));
        Append(state, new JsonObject { ["at"] = Iso(now), ["trigger"] = "restore", ["status"] = "changed", ["category"] = "source", ["months"] = Period(state, "source"), ["by"] = "", ["bytes"] = 0,
            ["message"] = "Application data was restored: approvals are void and no cleanup runs for 7 days." });
        Write(data, state);
    }

    // ---- plans (pure measurement)

    private static string Digest(IEnumerable<string> ids, int period) => AuthLens.Domain.Json.Digests.Text(string.Join('\n', ids) + "|" + period);

    /// <summary>Every 64-hex identifier named outside the source revisions themselves, plus the revisions review decisions and invalidations name.</summary>
    private static async Task<(HashSet<string> Hashes, HashSet<long> Ids)> ReferencesAsync(AuthLensDb db, CancellationToken ct)
    {
        var hashes = new HashSet<string>(StringComparer.Ordinal);
        void Scan(string? text) { if (text is not null) foreach (Match m in Hex().Matches(text)) hashes.Add(m.Value); }
        foreach (var t in await db.Settings.AsNoTracking().Select(s => s.Json).ToListAsync(ct)) Scan(t);
        foreach (var t in await db.SodDocuments.AsNoTracking().Select(s => s.Json).ToListAsync(ct)) Scan(t);
        foreach (var t in await db.SodDecisionEvents.AsNoTracking().Select(s => s.Json).ToListAsync(ct)) Scan(t);
        foreach (var t in await db.SodEvidenceSnapshots.AsNoTracking().Select(s => s.Json).ToListAsync(ct)) Scan(t);
        foreach (var t in await db.RefreshReports.AsNoTracking().Select(s => s.Json).ToListAsync(ct)) Scan(t);
        foreach (var t in await db.ReviewDecisions.AsNoTracking().Select(s => s.DetailsJson).ToListAsync(ct)) Scan(t);
        var ids = (await db.ReviewDecisions.AsNoTracking().Select(d => d.DatasetId).Distinct().ToListAsync(ct))
            .Concat(await db.ReviewInvalidations.AsNoTracking().Select(d => d.DatasetId).Distinct().ToListAsync(ct)).ToHashSet();
        return (hashes, ids);
    }

    private sealed record Candidate(long Id, string Source, int Revision, string Hash, int Records, DateTime Superseded);

    private async Task<(JsonObject Plan, List<Candidate> Items)> SourcePlanAsync(AuthLensDb db, int months, DateTimeOffset now, CancellationToken ct)
    {
        var cutoff = now.UtcDateTime.AddDays(-months * 30.4375);
        var (hashes, ids) = await ReferencesAsync(db, ct);
        var all = await db.Datasets.AsNoTracking().Where(d => d.Status == DatasetStatus.Active || d.Status == DatasetStatus.Retired)
            .Select(d => new { d.Id, d.Source, d.Revision, d.Status, d.ContentHash, d.RecordCount, d.ActivatedUtc, d.CreatedUtc, d.ReportJson }).ToListAsync(ct);
        // A revision migrated from SAP Lens 1 is also referenced by its v1 snapshot id (periods, decisions and reports written by v1 name that id).
        static string? Alias(string? report) => report is not null && V1Alias().Match(report) is { Success: true } m ? m.Groups[1].Value : null;
        var active = all.Where(d => d.Status == DatasetStatus.Active).Select(d => d.ContentHash).ToHashSet(StringComparer.Ordinal);
        var items = new List<Candidate>();
        var protectedCounts = new Dictionary<string, int> { ["referenced"] = 0, ["recent"] = 0, ["kept_newest"] = 0, ["unclassified"] = 0, ["unrecognised"] = 0 };
        foreach (var group in all.Where(d => d.Status == DatasetStatus.Retired).GroupBy(d => d.Source))
        {
            var entries = group.Where(d =>
                {
                    if (!active.Contains(d.ContentHash) && !hashes.Contains(d.ContentHash) && !ids.Contains(d.Id) && !(Alias(d.ReportJson) is { } alias && hashes.Contains(alias))) return true;
                    protectedCounts["referenced"]++;
                    return false;
                })
                // Superseded when the next revision of this source was activated.
                .Select(d => (Row: d, Moment: all.Where(o => o.Source == d.Source && o.Revision > d.Revision && o.ActivatedUtc != null).OrderBy(o => o.Revision).FirstOrDefault()?.ActivatedUtc))
                .OrderByDescending(e => e.Moment ?? DateTime.MaxValue).ThenByDescending(e => e.Row.Revision).ToList();
            protectedCounts["kept_newest"] += Math.Min(KeepPerSource, entries.Count);
            foreach (var (row, moment) in entries.Skip(KeepPerSource))
            {
                if (moment is null) protectedCounts["unclassified"]++;
                else if (moment > cutoff || row.CreatedUtc > cutoff) protectedCounts["recent"]++;
                else items.Add(new Candidate(row.Id, row.Source, row.Revision, row.ContentHash, row.RecordCount, moment.Value));
            }
        }
        items = items.OrderBy(i => i.Source, StringComparer.Ordinal).ThenBy(i => i.Revision).ToList();
        var summary = new JsonObject();
        foreach (var g in items.GroupBy(i => $"{i.Source} revisions"))
            summary[g.Key] = new JsonObject { ["count"] = g.Count(), ["bytes"] = 0, ["records"] = g.Sum(i => i.Records), ["oldest_days"] = g.Max(i => (int)(now.UtcDateTime - i.Superseded).TotalDays) };
        var plan = new JsonObject
        {
            ["months"] = months, ["generated"] = Iso(now), ["categories"] = summary, ["count"] = items.Count, ["bytes"] = 0, ["records"] = items.Sum(i => i.Records),
            ["protected"] = new JsonObject(protectedCounts.Select(p => KeyValuePair.Create(p.Key, (JsonNode?)p.Value))),
            ["digest"] = Digest(items.Select(i => $"{i.Source} revisions:{i.Hash}"), months),
            ["sample"] = new JsonArray([.. items.Take(100).Select(i => (JsonNode)new JsonObject
            {
                ["category"] = $"{i.Source} revisions", ["kind"] = i.Source, ["id"] = i.Hash, ["revision"] = i.Revision, ["records"] = i.Records, ["age_days"] = (int)(now.UtcDateTime - i.Superseded).TotalDays,
            })]),
            ["truncated"] = items.Count > 100,
        };
        return (plan, items);
    }

    private static async Task<JsonObject> ReviewPlanAsync(AuthLensDb db, int months, DateTimeOffset now, CancellationToken ct)
    {
        var row = await db.SodDocuments.AsNoTracking().FirstOrDefaultAsync(d => d.Name == "sod-periods", ct);
        var items = (row is null ? null : JsonNode.Parse(row.Json)?["items"] as JsonArray) ?? [];
        var completed = items.Where(p => Frozen.Contains((string?)p?["state"])).ToList();
        var reasons = new JsonObject();
        if (completed.Count > 0) reasons["Completed review periods are immutable AuthLens audit evidence and are never removed automatically"] = completed.Count;
        return new JsonObject
        {
            ["months"] = months, ["generated"] = Iso(now), ["count"] = 0, ["bytes"] = 0, ["protected"] = completed.Count, ["reasons"] = reasons, ["sample"] = new JsonArray(),
            ["protected_sample"] = new JsonArray([.. completed.Take(100).Select(p => (JsonNode)new JsonObject { ["name"] = p!["name"]?.DeepClone(), ["state"] = p["state"]?.DeepClone(), ["reason"] = "Immutable audit evidence" })]),
            ["truncated"] = false, ["digest"] = Digest([], months),
        };
    }

    private async Task<(JsonObject Plan, List<BackupRecord> Items)> BackupPlanAsync(AuthLensDb db, int days, DateTimeOffset now, CancellationToken ct)
    {
        var cutoff = now.UtcDateTime.AddDays(-days);
        var rows = await db.Backups.AsNoTracking().Where(b => b.DeletedUtc == null).ToListAsync(ct);
        var staged = StagedArchives();
        var items = new List<BackupRecord>();
        var protectedRows = new JsonArray();
        var counts = new Dictionary<string, int> { ["automatic"] = 0, ["manual"] = 0, ["unclassified"] = 0, ["migration"] = 0 };
        void Keep(BackupRecord b, string kind, string reason) => protectedRows.Add(new JsonObject { ["id"] = ApplicationBackups.IdOf(b) ?? b.Sha256[..Math.Min(32, b.Sha256.Length)], ["kind"] = kind, ["reason"] = reason, ["created"] = Iso(b.CreatedUtc) });
        foreach (var b in rows.OrderBy(b => b.CreatedUtc))
        {
            var path = Path.Combine(options.BackupDirectory, b.FileName);
            if (b.Kind == BackupKind.Migration)
            {
                counts["migration"]++;
                Keep(b, "migration", b.AdminConfirmedUtc is null ? "Migration backup waiting for administrator confirmation" : "Migration backup confirmed: delete it explicitly when no longer needed");
                continue;
            }
            if (b.Kind == BackupKind.Manual) { counts["manual"]++; Keep(b, "manual", "Manual backup: removed only by an administrator"); continue; }
            if (b.Kind != BackupKind.Automatic || ApplicationBackups.IdOf(b) is null) { counts["unclassified"]++; Keep(b, "unclassified", "No reliable classification (protected)"); continue; }
            counts["automatic"]++;
            if (b.CreatedUtc >= cutoff) Keep(b, "automatic", $"Younger than {days} days (or exactly {days})");
            else if (staged.Contains(b.Sha256)) Keep(b, "automatic", "Protects a staged restore");
            else if (File.Exists(path) && Sha(path) != b.Sha256) Keep(b, "automatic", "Archive does not match its recorded digest");
            else items.Add(b);
        }
        var reasons = new JsonObject();
        foreach (var g in protectedRows.GroupBy(r => (string)r!["reason"]!)) reasons[g.Key] = g.Count();
        var plan = new JsonObject
        {
            ["days"] = days, ["generated"] = Iso(now), ["count"] = items.Count, ["bytes"] = items.Sum(b => b.SizeBytes), ["reasons"] = reasons,
            ["counts"] = new JsonObject(counts.Select(c => KeyValuePair.Create(c.Key, (JsonNode?)c.Value))), ["keep"] = KeepCount(), ["count_limit"] = new JsonArray(),
            ["digest"] = Digest(items.Select(b => ApplicationBackups.IdOf(b)!).Order(StringComparer.Ordinal), days),
            ["sample"] = new JsonArray([.. items.Take(100).Select(b => (JsonNode)new JsonObject
            {
                ["id"] = ApplicationBackups.IdOf(b), ["created"] = Iso(b.CreatedUtc), ["bytes"] = b.SizeBytes, ["age_days"] = (int)(now.UtcDateTime - b.CreatedUtc).TotalDays,
                ["note"] = File.Exists(Path.Combine(options.BackupDirectory, b.FileName)) ? "" : "archive already removed; record completed", ["rule"] = $"Older than {days} days", ["rules"] = new JsonArray("age"),
            })]),
            ["protected_sample"] = new JsonArray([.. protectedRows.Take(100).Select(r => r!.DeepClone())]), ["truncated"] = items.Count > 100,
        };
        return (plan, items);
    }

    private int KeepCount()
    {
        var path = Path.Combine(options.BackupDirectory, "schedule.json");
        try { return File.Exists(path) && JsonNode.Parse(File.ReadAllText(path))?["schedule"]?["keep"] is JsonValue v && v.TryGetValue<int>(out var k) ? k : 7; }
        catch (Exception error) when (error is IOException or JsonException) { return 7; }
    }

    private HashSet<string> StagedArchives()
    {
        var result = new HashSet<string>(StringComparer.Ordinal);
        var root = Path.Combine(Data, "restore");
        if (!Directory.Exists(root)) return result;
        foreach (var folder in Directory.GetDirectories(root))
        {
            var preview = Path.Combine(folder, "preview.json");
            try { if (File.Exists(preview) && (string?)JsonNode.Parse(File.ReadAllText(preview))?["archive_sha256"] is { } sha) result.Add(sha); }
            catch (Exception error) when (error is IOException or JsonException) { }
        }
        return result;
    }

    private static string Sha(string path) => AuthLens.Domain.Json.Digests.File(path);

    public async Task<JsonObject> PreviewAsync(string category, CancellationToken ct)
    {
        var state = Read(Data);
        var now = clock.GetUtcNow();
        await using var db = await factory.CreateDbContextAsync(ct);
        return category switch
        {
            "source" => (await SourcePlanAsync(db, Period(state, "source"), now, ct)).Plan,
            "review" => await ReviewPlanAsync(db, Period(state, "review"), now, ct),
            _ => (await BackupPlanAsync(db, Period(state, "backup"), now, ct)).Plan,
        };
    }

    // ---- execution

    private async Task<JsonObject> ExecuteAsync(string category, string trigger, string actor, CancellationToken ct)
    {
        var now = clock.GetUtcNow();
        var state = Read(Data);
        RefuseRestoreHold(state, now);
        var period = Period(state, category);
        var removed = new JsonObject();
        long bytes = 0;
        var errors = 0;
        if (category == "source")
        {
            List<Candidate> items;
            await using (var db = await factory.CreateDbContextAsync(ct)) (_, items) = await SourcePlanAsync(db, period, now, ct);   // re-planned: a preview is never trusted
            foreach (var item in items)
                try
                {
                    // One write transaction per revision (BEGIN IMMEDIATE through the coordinator), re-checked inside it: still superseded, still
                    // unreferenced by review decisions or invalidations. The records go; the revision row stays as evidence (activated datasets are
                    // never deleted, a database trigger enforces it).
                    var purged = await _writer.WriteAsync(async (db, token) =>
                    {
                        var dataset = await db.Datasets.FirstOrDefaultAsync(d => d.Id == item.Id && d.Status == DatasetStatus.Retired, token);
                        if (dataset is null || await db.ReviewDecisions.AnyAsync(r => r.DatasetId == item.Id, token) || await db.ReviewInvalidations.AnyAsync(r => r.DatasetId == item.Id, token)) return false;
                        await db.DatasetRecords.Where(r => r.DatasetId == item.Id).ExecuteDeleteAsync(token);
                        dataset.Status = DatasetStatus.Purged;
                        return true;
                    }, ct);
                    if (purged) { var key = $"{item.Source} revisions"; removed[key] = (Int(removed[key]) ?? 0) + 1; }
                }
                catch (DbUpdateException) { errors++; }
        }
        else if (category == "backup")
        {
            if (!File.Exists(Path.Combine(Data, "restore", "pending.json")))
            {
                List<BackupRecord> items;
                await using (var db = await factory.CreateDbContextAsync(ct)) (_, items) = await BackupPlanAsync(db, period, now, ct);
                foreach (var item in items)
                {
                    var path = Path.Combine(options.BackupDirectory, item.FileName);
                    try
                    {
                        if (File.Exists(path)) File.Delete(path);
                        await _writer.WriteAsync(async (db, token) =>
                        {
                            var tracked = await db.Backups.FirstAsync(b => b.Id == item.Id, token);
                            tracked.DeletedUtc = now.UtcDateTime;
                            tracked.Reason = $"{tracked.Reason};expired by retention ({actor})";
                        }, ct);
                        removed["automatic backups"] = (Int(removed["automatic backups"]) ?? 0) + 1;
                        bytes += item.SizeBytes;
                    }
                    catch (IOException) { errors++; }
                }
            }
        }
        // Review: nothing is removed (immutable audit evidence).
        if (removed.Count > 0 || errors > 0)
        {
            state = Read(Data);
            Append(state, new JsonObject
            {
                ["at"] = Iso(now), ["trigger"] = trigger, ["status"] = errors > 0 ? "partial" : "completed", ["category"] = category, ["months"] = period, ["removed"] = removed.DeepClone(), ["bytes"] = bytes,
                ["by"] = actor.Length > 120 ? actor[..120] : actor, ["message"] = errors > 0 ? $"{errors} item(s) could not be removed and will be retried." : "",
            });
            (state["last_cleanup"] as JsonObject ?? [])[category] = Iso(now);
            state["last_cleanup"] ??= new JsonObject { [category] = Iso(now) };
            Write(Data, state);
        }
        return new JsonObject { ["removed"] = removed, ["bytes"] = bytes, ["errors"] = errors };
    }

    /// <summary>Approves one category for the period of the preview the administrator saw (the digest must still match), then cleans it up once now.</summary>
    public async Task<JsonObject> ApproveAsync(string category, string digest, string actor, CancellationToken ct)
    {
        await Gate.WaitAsync(ct);
        try
        {
            RefuseRestoreHold(Read(Data), clock.GetUtcNow());
            var found = await PreviewAsync(category, ct);
            if ((string?)found["digest"] != digest) throw new RetentionException("The data changed since the preview was created. Review the new preview and approve again.");
            var state = Read(Data);
            var now = clock.GetUtcNow();
            var period = Period(state, category);
            (state["approvals"] as JsonObject ?? [])[category] = new JsonObject { ["by"] = actor, ["at"] = Iso(now), ["period"] = period, ["instance"] = Instance(Data) };
            state["approvals"] ??= new JsonObject();
            Append(state, new JsonObject
            {
                ["at"] = Iso(now), ["trigger"] = "approval", ["status"] = "changed", ["category"] = category, ["months"] = period, ["by"] = actor, ["bytes"] = 0,
                ["message"] = category switch
                {
                    "source" => $"Approved cleanup of {found["count"]} superseded source revision(s) older than {period} months.",
                    "review" => "Approved review retention; completed review periods remain protected as immutable audit evidence.",
                    _ => $"Approved removal of {found["count"]} automatic backup(s) older than {period} days.",
                },
            });
            Write(Data, state);
            return await ExecuteAsync(category, "manual", actor, ct);
        }
        finally { Gate.Release(); }
    }

    private static void RefuseRestoreHold(JsonObject state, DateTimeOffset now)
    {
        if (DateTimeOffset.TryParse((string?)state["quiet_until"], System.Globalization.CultureInfo.InvariantCulture,
            System.Globalization.DateTimeStyles.AssumeUniversal, out var until) && until > now)
            throw new RetentionException($"Cleanup is paused after a restore until {Iso(until)}. Previews remain available; approve again after the hold ends.");
    }

    public JsonObject SetPolicy(bool enabled, int months, int? reviewMonths, int? backupDays, string actor)
    {
        var state = Read(Data);
        var policy = state["policy"]!.AsObject();
        var old = policy.ToJsonString();
        policy["enabled"] = enabled;
        policy["months"] = months;
        if (reviewMonths is { } r) policy["review_months"] = r;
        if (backupDays is { } d) policy["backup_days"] = d;
        if (policy.ToJsonString() != old)
        {
            var shorter = Categories.Where(c => state["approvals"]?[c] is JsonObject a && Period(state, c) < (Int(a["period"]) ?? 0)).ToList();
            Append(state, new JsonObject
            {
                ["at"] = Iso(clock.GetUtcNow()), ["trigger"] = "policy", ["status"] = "changed", ["category"] = "source", ["months"] = months, ["by"] = actor, ["bytes"] = 0,
                ["message"] = $"Retention {(enabled ? "enabled" : "disabled")}: source {Period(state, "source")} months, review {Period(state, "review")} months, automatic backups {Period(state, "backup")} days."
                    + (shorter.Count > 0 ? $" Shortening needs a new approval ({string.Join(", ", shorter)})." : ""),
            });
        }
        Write(Data, state);
        return Status();
    }

    /// <summary>The daily check: measures every category, records the previews, and cleans up only approved categories outside a post-restore pause.</summary>
    public async Task<string> CheckAsync(string trigger, CancellationToken ct)
    {
        await Gate.WaitAsync(ct);
        try
        {
            var state = Read(Data);
            if (state["policy"]!["enabled"]?.GetValue<bool>() != true) return "disabled";
            var now = clock.GetUtcNow();
            var previews = new JsonObject();
            foreach (var category in Categories)
            {
                var plan = await PreviewAsync(category, ct);
                plan.Remove("sample"); plan.Remove("protected_sample");
                previews[category] = plan;
            }
            state = Read(Data);
            state["last_check"] = Iso(now);
            state["last_preview"] = previews.DeepClone();
            Write(Data, state);
            var paused = DateTimeOffset.TryParse((string?)state["quiet_until"], System.Globalization.CultureInfo.InvariantCulture, System.Globalization.DateTimeStyles.AssumeUniversal, out var quiet) && quiet > now;
            var outcome = Categories.Any(c => (Int(previews[c]!["count"]) ?? 0) > 0) ? "awaiting_approval" : "nothing";
            foreach (var category in Categories)
                if ((Int(previews[category]!["count"]) ?? 0) > 0 && Approved(state, category) && !paused)
                {
                    await ExecuteAsync(category, trigger, "data-retention", ct);
                    outcome = "cleaned";
                }
            return outcome;
        }
        finally { Gate.Release(); }
    }

    public bool Due()
    {
        var state = Read(Data);
        if (state["policy"]!["enabled"]?.GetValue<bool>() != true) return false;
        return !DateTimeOffset.TryParse((string?)state["last_check"], System.Globalization.CultureInfo.InvariantCulture, System.Globalization.DateTimeStyles.AssumeUniversal, out var last)
               || clock.GetUtcNow() - last >= TimeSpan.FromHours(24);
    }

    public JsonObject Status()
    {
        var state = Read(Data);
        JsonObject Category(string name)
        {
            var approval = state["approvals"]?[name] as JsonObject;
            var value = new JsonObject
            {
                ["months"] = Period(state, name), ["state"] = Label(state, name), ["last_preview"] = state["last_preview"]?[name]?.DeepClone() ?? new JsonObject(),
                ["approval"] = approval is null ? null : new JsonObject { ["by"] = approval["by"]?.DeepClone(), ["at"] = approval["at"]?.DeepClone(), ["months"] = approval["period"]?.DeepClone(), ["valid"] = Approved(state, name) },
                ["last_cleanup"] = state["last_cleanup"]?[name]?.DeepClone(),
            };
            if (name == "backup")
            {
                value["days"] = Period(state, name);
                value["keep"] = KeepCount();
                value["last_check"] = state["last_check"]?.DeepClone();
                value["next_check"] = DateTimeOffset.TryParse((string?)state["last_check"], System.Globalization.CultureInfo.InvariantCulture, System.Globalization.DateTimeStyles.AssumeUniversal, out var last) ? Iso(last.AddHours(24)) : null;
            }
            return value;
        }
        var history = state["history"] as JsonArray ?? [];
        return new JsonObject
        {
            ["policy"] = state["policy"]!.DeepClone(),
            ["categories"] = new JsonObject { ["source"] = Category("source"), ["review"] = Category("review"), ["backup"] = Category("backup") },
            ["last_check"] = state["last_check"]?.DeepClone(), ["quiet_until"] = state["quiet_until"]?.DeepClone(),
            ["history"] = new JsonArray([.. history.Reverse().Take(20).Select(h => h!.DeepClone())]),
            ["scope"] = new JsonObject
            {
                ["source"] = new JsonArray("Superseded role, user, SoD matrix and Employee Directory revisions that nothing references"),
                ["review"] = new JsonArray("Completed review periods are immutable audit evidence and are kept; nothing in this category is removed"),
                ["backup"] = new JsonArray("Automatic (scheduled) backups older than the period, counted from their recorded creation time"),
            },
            ["protected_note"] = "Current source data, revisions referenced by review periods, decisions, evidence, remediation or refresh reports, all review periods, manual and migration backups and the newest previous revisions are never removed.",
        };
    }
}

public sealed class RetentionException(string message, int status = 409) : Exception(message)
{
    public int Status { get; } = status;
}
