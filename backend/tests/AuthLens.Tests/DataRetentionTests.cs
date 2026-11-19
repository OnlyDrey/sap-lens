using System.Text.Json.Nodes;
using Microsoft.EntityFrameworkCore;
using AuthLens.Application;
using AuthLens.Application.Retention;
using AuthLens.Persistence;

namespace AuthLens.Tests;

/// <summary>Data retention on the AuthLens database: superseded source revisions are removed only after a preview, a matching approval and the period;
/// references from audit history and review decisions, the newest previous revisions, recent revisions and the active revision are protected; review
/// periods are never removed; approvals are bound to the installation and voided by a restore.</summary>
public sealed class DataRetentionTests
{
    private static async Task<(CoreEnv Env, DataRetention Retention, List<Dataset> Revisions)> FiveRevisionsAsync()
    {
        var env = await CoreEnv.StartAsync();
        for (var i = 0; i < 5; i++)
        {
            await env.RunImportAsync(Sources.Roles, Csv.Roles(10 + i));
            env.Clock.Advance(TimeSpan.FromDays(183));
        }
        env.Clock.Advance(TimeSpan.FromDays(30 * 30));
        var revisions = await env.QueryAsync(db => db.Datasets.AsNoTracking().Where(d => d.Source == Sources.Roles).OrderBy(d => d.Revision).ToListAsync());
        Assert.Equal([DatasetStatus.Retired, DatasetStatus.Retired, DatasetStatus.Retired, DatasetStatus.Retired, DatasetStatus.Active], revisions.Select(r => r.Status));
        return (env, new DataRetention(env.Options, env.Factory, env.Clock), revisions);
    }

    [Fact]
    public async Task Restore_hold_blocks_manual_approval_and_preserves_eligible_revisions()
    {
        var (env, retention, _) = await FiveRevisionsAsync();
        await using var owned = env;
        var before = await retention.PreviewAsync("source", default);
        Assert.True((int)before["count"]! > 0);
        var records = await env.QueryAsync(db => db.DatasetRecords.CountAsync());
        DataRetention.AfterRestore(env.Options.DataDirectory, env.Clock.GetUtcNow());
        var during = await retention.PreviewAsync("source", default);
        var error = await Assert.ThrowsAsync<RetentionException>(() => retention.ApproveAsync("source", (string)during["digest"]!, "admin.synthetic", default));
        Assert.Contains("paused after a restore", error.Message);
        Assert.Equal(records, await env.QueryAsync(db => db.DatasetRecords.CountAsync()));
        Assert.Null(retention.Status()["categories"]!["source"]!["approval"]);
        env.Clock.Advance(TimeSpan.FromDays(7).Add(TimeSpan.FromSeconds(1)));
        var after = await retention.PreviewAsync("source", default);
        var result = await retention.ApproveAsync("source", (string)after["digest"]!, "admin.synthetic", default);
        Assert.NotEmpty(result["removed"]!.AsObject());
    }

    [Fact]
    public async Task Only_old_unreferenced_superseded_revisions_are_removed_after_a_matching_approval()
    {
        var (env, retention, revisions) = await FiveRevisionsAsync();
        await using var _ = env;
        // A refresh report (audit history) naming revision 1 protects it.
        await env.QueryAsync(async db =>
        {
            db.RefreshReports.Add(new RefreshReport { Id = new string('a', 32), TimestampUtc = env.Clock.GetUtcNow().UtcDateTime, Operation = "refresh", Status = "succeeded",
                Json = new JsonObject { ["sources"] = new JsonObject { ["roles"] = new JsonObject { ["snapshot"] = revisions[0].ContentHash } } }.ToJsonString() });
            return await db.SaveChangesAsync();
        });

        var preview = await retention.PreviewAsync("source", default);
        Assert.Equal(1, (int)preview["count"]!);
        Assert.Equal(revisions[1].ContentHash, (string)preview["sample"]![0]!["id"]!);
        Assert.Equal((1, 2), ((int)preview["protected"]!["referenced"]!, (int)preview["protected"]!["kept_newest"]!));
        Assert.Equal(revisions[1].RecordCount, (int)preview["records"]!);

        // The daily check only measures before approval.
        Assert.Equal("awaiting_approval", await retention.CheckAsync("automatic", default));
        Assert.Equal(0, await env.QueryAsync(db => db.Datasets.CountAsync(d => d.Status == DatasetStatus.Purged)));

        await Assert.ThrowsAsync<RetentionException>(() => retention.ApproveAsync("source", new string('0', 64), "admin.synthetic", default));
        var result = await retention.ApproveAsync("source", (string)preview["digest"]!, "admin.synthetic", default);
        Assert.True(result["removed"]!["roles revisions"] is not null, result.ToJsonString());
        Assert.Equal(1, (int)result["removed"]!["roles revisions"]!);
        var left = await env.QueryAsync(db => db.Datasets.AsNoTracking().OrderBy(d => d.Revision).Select(d => d.Status).ToListAsync());
        Assert.Equal([DatasetStatus.Retired, DatasetStatus.Purged, DatasetStatus.Retired, DatasetStatus.Retired, DatasetStatus.Active], left);
        Assert.Equal(revisions[1].ContentHash, await env.QueryAsync(db => db.Datasets.Where(d => d.Id == revisions[1].Id).Select(d => d.ContentHash).FirstAsync()));   // evidence row kept
        Assert.Equal(0, await env.QueryAsync(db => db.DatasetRecords.CountAsync(r => r.DatasetId == revisions[1].Id)));
        var status = retention.Status();
        Assert.Equal("approved", (string)status["categories"]!["source"]!["state"]!);
        Assert.Contains(status["history"]!.AsArray(), h => (string)h!["trigger"]! == "approval");

        // Idempotent: nothing further is eligible; shortening the period voids the approval.
        Assert.Equal(0, (int)(await retention.PreviewAsync("source", default))["count"]!);
        retention.SetPolicy(true, 12, null, null, "admin.synthetic");
        Assert.Equal("awaiting_approval", (string)retention.Status()["categories"]!["source"]!["state"]!);
    }

    [Fact]
    public async Task Review_decisions_and_recent_revisions_are_protected_and_review_periods_are_never_removed()
    {
        var (env, retention, revisions) = await FiveRevisionsAsync();
        await using var _ = env;
        await env.QueryAsync(async db =>
        {
            db.ReviewDecisions.Add(new ReviewDecision { SubjectType = "assignment", SubjectKey = "SYNTH.USER|ROLE", Decision = "keep", Reviewer = "reviewer.synthetic", DatasetId = revisions[1].Id,
                DecidedUtc = env.Clock.GetUtcNow().UtcDateTime, Hash = new string('b', 64) });
            db.SodDocuments.Add(new SodDocument { Name = "sod-periods", Revision = 1, UpdatedUtc = DateTime.UtcNow,
                Json = new JsonObject { ["items"] = new JsonArray(new JsonObject { ["id"] = "p1", ["name"] = "Synthetic period", ["state"] = "Closed" }) }.ToJsonString() });
            return await db.SaveChangesAsync();
        });
        var source = await retention.PreviewAsync("source", default);
        Assert.Equal(1, (int)source["count"]!);                                      // revision 1 only; revision 2 is named by a review decision
        Assert.Equal(revisions[0].ContentHash, (string)source["sample"]![0]!["id"]!);

        var review = await retention.PreviewAsync("review", default);
        Assert.Equal((0, 1), ((int)review["count"]!, (int)review["protected"]!));
        var approved = await retention.ApproveAsync("review", (string)review["digest"]!, "admin.synthetic", default);
        Assert.Empty(approved["removed"]!.AsObject());
        Assert.Contains("Closed", await env.QueryAsync(db => db.SodDocuments.Where(d => d.Name == "sod-periods").Select(d => d.Json).FirstAsync()));

        // A longer period protects everything as recent.
        retention.SetPolicy(true, 120, null, null, "admin.synthetic");
        var longer = await retention.PreviewAsync("source", default);
        Assert.Equal(0, (int)longer["count"]!);
        Assert.Equal(1, (int)longer["protected"]!["recent"]!);
    }

    [Fact]
    public async Task A_restore_or_another_installation_voids_approvals_and_pauses_cleanup()
    {
        var (env, retention, _) = await FiveRevisionsAsync();
        await using var _e = env;
        var preview = await retention.PreviewAsync("source", default);
        await retention.ApproveAsync("source", (string)preview["digest"]!, "admin.synthetic", default);
        Assert.Equal("approved", (string)retention.Status()["categories"]!["source"]!["state"]!);

        // Another installation (different identity file): the approval read from a copied state file is not valid there.
        File.WriteAllText(Path.Combine(env.Options.DataDirectory, ".installation-id"), new string('c', 32));
        Assert.Equal("awaiting_approval", (string)retention.Status()["categories"]!["source"]!["state"]!);

        DataRetention.AfterRestore(env.Options.DataDirectory, env.Clock.GetUtcNow());
        var status = retention.Status();
        Assert.Null(status["categories"]!["source"]!["approval"]);
        Assert.True(DateTimeOffset.Parse((string)status["quiet_until"]!) > env.Clock.GetUtcNow().AddDays(6));
    }
}
