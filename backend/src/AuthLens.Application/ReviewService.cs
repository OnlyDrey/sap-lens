using Microsoft.EntityFrameworkCore;
using AuthLens.Domain.Json;
using AuthLens.Domain.Roles;
using AuthLens.Persistence;

namespace AuthLens.Application;

public sealed record AssignmentReviewStatus(string AssignmentKey, bool Present, ReviewDecision? LatestDecision, bool DecisionApplies, bool NeedsReview);

/// <summary>Append-only review decisions with a hash chain. A decision on an assignment applies only while no invalidation (the assignment disappeared in a
/// later activated revision) is newer than the users revision the decision was made against: an assignment that disappears and reappears needs a new review,
/// while every historical decision stays unchanged.</summary>
public sealed class ReviewService(WriteCoordinator writer, IDbContextFactory<AuthLensDb> factory, SnapshotService snapshots, TimeProvider clock)
{
    public static readonly string[] Decisions = ["approved", "rejected", "mitigated"];
    public static readonly string[] SubjectTypes = ["assignment", "sod_finding"];

    public static string HashOf(ReviewDecision d, string? previous)
    {
        var fields = new Dictionary<string, object?>
        {
            ["previous"] = previous, ["subject_type"] = d.SubjectType, ["subject_key"] = d.SubjectKey, ["evidence_version"] = d.EvidenceVersion, ["decision"] = d.Decision,
            ["reviewer"] = d.Reviewer, ["comment"] = d.Comment, ["dataset_id"] = d.DatasetId, ["decided_utc"] = d.DecidedUtc.ToString("yyyy-MM-ddTHH:mm:ss.fffffff"),
        };
        if (d.DetailsJson is not null) fields["details"] = d.DetailsJson; // decisions written before details existed keep their hashes
        return CanonicalJson.Sha256(fields);
    }

    public static readonly string[] AccountStates = ["Needs review", "Investigating", "Approved for deactivation", "No action required"];

    /// <summary>Appends an Account Review decision (v1 states) to the same hash chain. Refused when the users revision changed since the caller computed
    /// the evidence, or when another decision for the account was recorded after the one the reviewer saw (<paramref name="expectedLatest"/>).</summary>
    public Task<ReviewDecision> RecordAccountAsync(string username, string state, string evidenceVersion, string reviewer, string rationale, string detailsJson,
        long usersId, Func<ReviewDecision?, bool> expectedLatest, CancellationToken cancellation = default)
    {
        if (!AccountStates.Contains(state)) throw new DomainValidationException("Unknown review state.");
        var key = Sources.AccountKey(username);
        return writer.WriteAsync(async (db, ct) =>
        {
            var active = await SnapshotService.ActiveAsync(db, ct);
            if (active.Users != usersId) throw new ImportConflictException("Source data changed while saving. Refresh the review before saving.");
            var latest = await db.ReviewDecisions.Where(d => d.SubjectType == "account" && d.SubjectKey == key).OrderByDescending(d => d.Id).FirstOrDefaultAsync(ct);
            if (!expectedLatest(latest)) throw new ImportConflictException("Another user changed this review. Reload before saving.");
            var previous = await db.ReviewDecisions.OrderByDescending(d => d.Id).Select(d => d.Hash).FirstOrDefaultAsync(ct);
            var record = new ReviewDecision
            {
                SubjectType = "account", SubjectKey = key, EvidenceVersion = evidenceVersion, Decision = state, Reviewer = reviewer, Comment = rationale, DetailsJson = detailsJson,
                DatasetId = usersId, DecidedUtc = clock.GetUtcNow().UtcDateTime, Hash = "", PreviousHash = previous,
            };
            record.Hash = HashOf(record, previous);
            db.ReviewDecisions.Add(record);
            return record;
        }, cancellation);
    }

    public async Task<ReviewDecision> RecordAsync(string subjectType, string subjectKey, string? evidenceVersion, string decision, string reviewer, string? comment, CancellationToken cancellation = default)
    {
        if (!SubjectTypes.Contains(subjectType)) throw new DomainValidationException("Unknown review subject type.");
        if (!Decisions.Contains(decision)) throw new DomainValidationException("Unknown review decision.");
        if (string.IsNullOrWhiteSpace(subjectKey) || subjectKey.Length > 1100) throw new DomainValidationException("A review subject is required.");
        if ((comment ?? "").Length > 4000) throw new DomainValidationException("The review comment is too long.");
        if (subjectType == "sod_finding" && (evidenceVersion is null || evidenceVersion.Length != 64)) throw new DomainValidationException("A SoD decision needs the finding's evidence version.");
        var snapshot = await snapshots.GetAsync(cancellation);
        if (snapshot.Ids.Users is not { } usersId) throw new DomainValidationException("No active user assignment data.");
        if (subjectType == "assignment" && !snapshot.AssignmentKeys.Contains(subjectKey)) throw new DomainValidationException("The assignment is not present in the active data.");
        return await writer.WriteAsync(async (db, ct) =>
        {
            // The active revision is re-read inside the write transaction: a decision is bound to the data that was active when it committed.
            var active = await SnapshotService.ActiveAsync(db, ct);
            if (active.Users != usersId) throw new ImportConflictException("The user data changed while the decision was being recorded; review again.");
            var previous = await db.ReviewDecisions.OrderByDescending(d => d.Id).Select(d => d.Hash).FirstOrDefaultAsync(ct);
            var record = new ReviewDecision
            {
                SubjectType = subjectType, SubjectKey = subjectKey, EvidenceVersion = evidenceVersion, Decision = decision, Reviewer = reviewer, Comment = comment ?? "",
                DatasetId = usersId, DecidedUtc = clock.GetUtcNow().UtcDateTime, Hash = "", PreviousHash = previous,
            };
            record.Hash = HashOf(record, previous);
            db.ReviewDecisions.Add(record);
            return record;
        }, cancellation);
    }

    public async Task<AssignmentReviewStatus> AssignmentStatusAsync(string key, CancellationToken cancellation = default)
    {
        var snapshot = await snapshots.GetAsync(cancellation);
        await using var db = await factory.CreateDbContextAsync(cancellation);
        var latest = await db.ReviewDecisions.AsNoTracking().Where(d => d.SubjectType == "assignment" && d.SubjectKey == key).OrderByDescending(d => d.Id).FirstOrDefaultAsync(cancellation);
        var lastInvalidation = await db.ReviewInvalidations.AsNoTracking().Where(i => i.AssignmentKey == key).MaxAsync(i => (long?)i.DatasetId, cancellation);
        var present = snapshot.AssignmentKeys.Contains(key);
        var applies = latest is not null && present && (lastInvalidation is null || latest.DatasetId >= lastInvalidation);
        return new AssignmentReviewStatus(key, present, latest, applies, present && !applies);
    }

    /// <summary>Recomputes the chain; any edited, removed or reordered decision breaks it.</summary>
    public async Task<(bool Ok, long? BrokenAt, int Count)> VerifyChainAsync(CancellationToken cancellation = default)
    {
        await using var db = await factory.CreateDbContextAsync(cancellation);
        string? previous = null;
        var count = 0;
        await foreach (var d in db.ReviewDecisions.AsNoTracking().OrderBy(d => d.Id).AsAsyncEnumerable().WithCancellation(cancellation))
        {
            if (d.PreviousHash != previous || HashOf(d, previous) != d.Hash) return (false, d.Id, count);
            previous = d.Hash;
            count++;
        }
        return (true, null, count);
    }
}
