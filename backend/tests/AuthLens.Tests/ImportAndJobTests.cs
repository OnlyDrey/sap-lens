using Microsoft.EntityFrameworkCore;
using AuthLens.Application;
using AuthLens.Domain.Roles;
using AuthLens.Persistence;

namespace AuthLens.Tests;

public sealed class ImportAndJobTests
{
    [Theory]
    [InlineData("roles", "no usable records")]
    [InlineData("users", "no usable records")]
    [InlineData("sod", "no usable records")]
    [InlineData("employees", "no employee records")]
    public async Task Header_only_replacements_fail_permanently_without_retiring_the_active_source(string source, string message)
    {
        await using var env = await CoreEnv.StartAsync();
        var headers = AuthLens.Domain.Directory.EmployeeDirectory.Headers;
        var csv = source switch
        {
            "roles" => Csv.Roles(5), "users" => Csv.Users([("SYNTHETIC", "ZC:SYN")]), "sod" => Csv.Sod(),
            _ => string.Join(';', headers) + "\n" + string.Join(';', headers.Select(h => h == "Name" ? "Synthetic" : h == "Mail" ? "synthetic@example.test" : "")) + "\n",
        };
        var good = await env.RunImportAsync(source, csv);
        var job = await env.EnqueueImportAsync(source, csv.Split('\n')[0] + "\n");
        var claimed = (await env.Queue.ClaimAsync("empty-check"))!;
        var error = await Assert.ThrowsAnyAsync<Exception>(() => env.Imports.RunAsync(new JobContext(claimed, "empty-check", env.Queue, CancellationToken.None)));
        Assert.Contains(message, error.Message); Assert.False(JobWorker.IsTransient(error));
        await env.Queue.FailAsync(job.Id, "empty-check", JobWorker.Describe(error), false);
        Assert.Equal(JobStatus.Failed, (await env.Queue.GetAsync(job.Id))!.Status);
        Assert.Equal(good.DatasetId, await env.QueryAsync(db => db.Datasets.Where(d => d.Source == source && d.Status == DatasetStatus.Active).Select(d => d.Id).SingleAsync()));
        Assert.Equal(good.Records, await env.QueryAsync(db => db.DatasetRecords.CountAsync(r => r.DatasetId == good.DatasetId)));
        Assert.Equal(0, await env.QueryAsync(db => db.Datasets.CountAsync(d => d.Status == DatasetStatus.Staged)));
    }

    [Fact]
    public async Task A_previously_held_empty_revision_cannot_bypass_empty_source_protection()
    {
        await using var env = await CoreEnv.StartAsync();
        var good = await env.RunImportAsync("roles", Csv.Roles(5));
        var empty = await env.Writer.WriteAsync(async (db, ct) =>
        {
            var dataset = new Dataset { Source = "roles", Revision = 2, Status = DatasetStatus.Held, FileName = "empty.csv", CreatedUtc = env.Clock.GetUtcNow().UtcDateTime };
            db.Datasets.Add(dataset); await db.SaveChangesAsync(ct); return dataset.Id;
        });
        await Assert.ThrowsAsync<ImportConflictException>(() => env.Imports.ConfirmAsync(empty, "synthetic admin"));
        Assert.Equal(good.DatasetId, (await env.Snapshots.GetAsync()).Ids.Roles);
    }

    [Fact]
    public async Task Import_stages_validates_and_activates_atomically_with_job_completion()
    {
        await using var env = await CoreEnv.StartAsync();
        var result = await env.RunImportAsync("roles", Csv.Roles(30));
        Assert.Equal(DatasetStatus.Active, result.Status);
        Assert.Equal(90, result.Records);
        var job = await env.QueryAsync(db => db.Jobs.SingleAsync());
        Assert.Equal(JobStatus.Completed, job.Status);
        var snapshot = await env.Snapshots.GetAsync();
        Assert.Equal(30, snapshot.Catalogue.Roles.Count);
        Assert.Equal(result.DatasetId, snapshot.Ids.Roles);
    }

    [Fact]
    public async Task Identical_content_has_identical_hash_and_new_revision()
    {
        await using var env = await CoreEnv.StartAsync();
        var first = await env.RunImportAsync("roles", Csv.Roles(25));
        var second = await env.RunImportAsync("roles", Csv.Roles(25));
        Assert.Equal(first.ContentHash, second.ContentHash);
        var datasets = await env.QueryAsync(db => db.Datasets.OrderBy(d => d.Id).ToListAsync());
        Assert.Equal([DatasetStatus.Retired, DatasetStatus.Active], datasets.Select(d => d.Status));
        Assert.Equal([1, 2], datasets.Select(d => d.Revision));
    }

    [Fact]
    public async Task Suspiciously_large_change_is_held_until_explicitly_confirmed()
    {
        await using var env = await CoreEnv.StartAsync();
        var first = await env.RunImportAsync("roles", Csv.Roles(40));
        var shrunk = await env.RunImportAsync("roles", Csv.Roles(10));
        Assert.True(shrunk.Suspicious);
        Assert.Equal(DatasetStatus.Held, shrunk.Status);
        Assert.NotEmpty(shrunk.Anomalies);
        Assert.Equal(first.DatasetId, (await env.Snapshots.GetAsync()).Ids.Roles); // the previous revision stays active
        var confirmed = await env.Imports.ConfirmAsync(shrunk.DatasetId, "admin@example.test");
        Assert.Equal(DatasetStatus.Active, confirmed.Status);
        Assert.Equal("admin@example.test", confirmed.ConfirmedBy);
        Assert.Equal(10, (await env.Snapshots.GetAsync()).Catalogue.Roles.Count);
        await Assert.ThrowsAsync<ImportConflictException>(() => env.Imports.ConfirmAsync(shrunk.DatasetId, "admin@example.test"));
    }

    [Fact]
    public async Task Confirmation_is_refused_when_another_revision_was_activated_after_evaluation()
    {
        await using var env = await CoreEnv.StartAsync();
        await env.RunImportAsync("roles", Csv.Roles(40));
        var held = await env.RunImportAsync("roles", Csv.Roles(10));
        await env.RunImportAsync("roles", Csv.Roles(41));
        await Assert.ThrowsAsync<ImportConflictException>(() => env.Imports.ConfirmAsync(held.DatasetId, "admin@example.test"));
    }

    [Theory]
    [InlineData("FUNCTION_KEY;AGR_NAME\nFI;ZC:A\nFI;ZC:B\nFI;ZC:C\nFI;ZC:D\nFI;ZC:E\nFI;ZC:F\nFI;ZC:G\nFI;ZC:H\nFI;ZC:I\nFI;ZC:J\nFI;ZC:K;extra\n", "row width")]
    [InlineData("FUNCTION_KEY;AGR_NAME\nFI;ZC:A\nFI;ZC:B;extra\n", "AGR_NAME field is not mapped")] // v1 behaviour: too few rows to sniff the delimiter
    [InlineData("FUNCTION_KEY;TEXT\nFI;x\n", "AGR_NAME")]
    [InlineData("FUNCTION_KEY;AGR_NAME\nFI;\"unterminated\n", "")]
    public async Task Malformed_csv_fails_permanently_and_leaves_active_data_untouched(string csv, string message)
    {
        await using var env = await CoreEnv.StartAsync();
        var good = await env.RunImportAsync("roles", Csv.Roles(5));
        var job = await env.EnqueueImportAsync("roles", csv);
        var claimed = (await env.Queue.ClaimAsync("w"))!;
        var error = await Assert.ThrowsAnyAsync<Exception>(() => env.Imports.RunAsync(new JobContext(claimed, "w", env.Queue, CancellationToken.None)));
        Assert.False(JobWorker.IsTransient(error));
        Assert.Contains(message, error.Message);
        await env.Queue.FailAsync(job.Id, "w", JobWorker.Describe(error), JobWorker.IsTransient(error));
        Assert.Equal(JobStatus.Failed, (await env.Queue.GetAsync(job.Id))!.Status);
        Assert.Equal(good.DatasetId, (await env.Snapshots.GetAsync()).Ids.Roles);
        Assert.Equal(0, await env.QueryAsync(db => db.Datasets.CountAsync(d => d.Status == DatasetStatus.Staged)));
    }

    [Fact]
    public async Task Cancel_request_stops_a_running_import_and_discards_its_staging()
    {
        await using var env = await CoreEnv.StartAsync();
        var job = await env.EnqueueImportAsync("roles", Csv.Roles(4000, 3)); // 12 000 rows: more than two batches
        var claimed = (await env.Queue.ClaimAsync("w"))!;
        await env.Queue.RequestCancelAsync(job.Id);
        await Assert.ThrowsAsync<JobCancelRequestedException>(() => env.Imports.RunAsync(new JobContext(claimed, "w", env.Queue, CancellationToken.None)));
        await env.Queue.CancelledAsync(job.Id, "w");
        Assert.Equal(JobStatus.Cancelled, (await env.Queue.GetAsync(job.Id))!.Status);
        Assert.Equal(0, await env.QueryAsync(db => db.DatasetRecords.CountAsync()));
        Assert.Equal(DatasetStatus.Discarded, await env.QueryAsync(db => db.Datasets.Select(d => d.Status).SingleAsync()));
    }

    [Fact]
    public async Task Interrupted_import_is_recovered_once_and_the_stale_worker_cannot_complete_it()
    {
        await using var env = await CoreEnv.StartAsync();
        var job = await env.EnqueueImportAsync("roles", Csv.Roles(30));
        var crashed = (await env.Queue.ClaimAsync("worker-before-restart"))!;
        // The first worker staged everything and then "crashed" before completing (no commit of activation).
        var staleOutcome = await env.Imports.RunAsync(new JobContext(crashed, "worker-before-restart", env.Queue, CancellationToken.None));
        Assert.Equal(0, await env.Queue.RecoverExpiredAsync()); // lease still live: never re-run
        env.Clock.Advance(JobQueue.Lease + TimeSpan.FromSeconds(1));
        Assert.Equal(1, await env.Queue.RecoverExpiredAsync());
        Assert.Equal(0, await env.QueryAsync(db => db.DatasetRecords.CountAsync())); // orphan staging discarded

        var resumed = (await env.Queue.ClaimAsync("worker-after-restart"))!;
        Assert.Equal(job.Id, resumed.Id);
        Assert.Equal(2, resumed.Attempts);
        var outcome = await env.Imports.RunAsync(new JobContext(resumed, "worker-after-restart", env.Queue, CancellationToken.None));
        // The stale worker wakes up and tries to commit: fenced out, nothing written.
        await Assert.ThrowsAsync<LeaseLostException>(() => env.Queue.CompleteAsync(job.Id, "worker-before-restart", staleOutcome.ResultJson, staleOutcome.Atomic));
        await env.Queue.CompleteAsync(job.Id, "worker-after-restart", outcome.ResultJson, outcome.Atomic);
        Assert.Equal(1, await env.QueryAsync(db => db.Datasets.CountAsync(d => d.Status == DatasetStatus.Active)));
        Assert.Equal(0, await env.Queue.RecoverExpiredAsync());
        Assert.Null(await env.Queue.ClaimAsync("anyone")); // completed: never executed again
    }

    [Fact]
    public async Task Shutdown_hands_the_job_back_without_counting_the_attempt()
    {
        await using var env = await CoreEnv.StartAsync();
        var job = await env.EnqueueImportAsync("roles", Csv.Roles(5));
        await env.Queue.ClaimAsync("w");
        await env.Queue.ReleaseAsync(job.Id, "w");
        var released = (await env.Queue.GetAsync(job.Id))!;
        Assert.Equal(JobStatus.Queued, released.Status);
        Assert.Equal(0, released.Attempts);
    }

    [Fact]
    public async Task Transient_failures_retry_with_backoff_then_fail()
    {
        await using var env = await CoreEnv.StartAsync();
        var job = await env.Queue.EnqueueAsync("probe", "{}", null);
        for (var attempt = 1; attempt <= 3; attempt++)
        {
            Assert.Null(attempt > 1 ? await env.Queue.ClaimAsync("w") : null); // backoff: not yet eligible
            env.Clock.Advance(TimeSpan.FromMinutes(1));
            var claimed = (await env.Queue.ClaimAsync("w"))!;
            Assert.Equal(attempt, claimed.Attempts);
            await env.Queue.FailAsync(job.Id, "w", "busy", transient: true);
        }
        Assert.Equal(JobStatus.Failed, (await env.Queue.GetAsync(job.Id))!.Status);
    }

    [Fact]
    public async Task Idempotency_key_returns_the_existing_job()
    {
        await using var env = await CoreEnv.StartAsync();
        var a = await env.Queue.EnqueueAsync("probe", "{}", "key-1");
        var b = await env.Queue.EnqueueAsync("probe", "{\"other\":1}", "key-1");
        Assert.Equal(a.Id, b.Id);
    }

    [Fact]
    public async Task Users_import_needs_no_catalogue_and_reports_unmapped_roles()
    {
        await using var env = await CoreEnv.StartAsync();
        var result = await env.RunImportAsync("users", Csv.Users(Csv.Assignments(5, 2, 5)));
        Assert.Equal(DatasetStatus.Active, result.Status);
        var snapshot = await env.Snapshots.GetAsync();
        Assert.All(snapshot.Users.Assignments, a => Assert.Equal("unmapped", a.MatchStatus));
    }
}

public sealed class ReviewTests
{
    private static readonly string Key = "USER0001\u001f" + RoleNames.Normalize("ZC:FI:ROLE_0001");

    [Fact]
    public async Task Assignment_that_disappears_and_reappears_requires_a_new_review_and_history_is_unchanged()
    {
        await using var env = await CoreEnv.StartAsync();
        await env.RunImportAsync("roles", Csv.Roles(50));
        var all = Csv.Assignments(50, 1, 50).ToList();
        await env.RunImportAsync("users", Csv.Users(all));
        var decision = await env.Reviews.RecordAsync("assignment", Key, null, "approved", "reviewer@example.test", "needed for month end");
        Assert.True((await env.Reviews.AssignmentStatusAsync(Key)).DecisionApplies);

        var without = await env.RunImportAsync("users", Csv.Users(all.Where(a => a.Item1 != "USER0001")));
        Assert.Equal(2, without.Invalidated); // the assignment and, for Account Review, the account itself
        var gone = await env.Reviews.AssignmentStatusAsync(Key);
        Assert.False(gone.Present);
        Assert.False(gone.NeedsReview);

        await env.RunImportAsync("users", Csv.Users(all));
        var back = await env.Reviews.AssignmentStatusAsync(Key);
        Assert.True(back.Present);
        Assert.False(back.DecisionApplies);
        Assert.True(back.NeedsReview);
        Assert.Equal(decision.Hash, back.LatestDecision!.Hash); // the historical decision is unchanged

        await env.Reviews.RecordAsync("assignment", Key, null, "approved", "reviewer@example.test", "re-reviewed");
        Assert.True((await env.Reviews.AssignmentStatusAsync(Key)).DecisionApplies);
        var chain = await env.Reviews.VerifyChainAsync();
        Assert.True(chain.Ok);
        Assert.Equal(2, chain.Count);
    }

    [Fact]
    public async Task Assignment_keys_use_the_normalized_role_name_whatever_the_export_spelling()
    {
        await using var env = await CoreEnv.StartAsync();
        await env.RunImportAsync("users", Csv.Users([("user0001", "zc:Finance:role 9")]));
        var key = Sources.AssignmentKey("USER0001", "ZC:FINANCE:ROLE9");
        Assert.Contains(key, (await env.Snapshots.GetAsync()).AssignmentKeys);
        await env.Reviews.RecordAsync("assignment", key, null, "approved", "r", null);
        Assert.True((await env.Reviews.AssignmentStatusAsync(Sources.AssignmentKey(" user0001 ", "ZC:finance:ROLE9"))).DecisionApplies);
    }

    [Fact]
    public async Task Decisions_on_absent_assignments_and_unknown_values_are_rejected()
    {
        await using var env = await CoreEnv.StartAsync();
        await env.RunImportAsync("users", Csv.Users(Csv.Assignments(3, 1, 3)));
        await Assert.ThrowsAsync<DomainValidationException>(() => env.Reviews.RecordAsync("assignment", "NOBODY\u001fZC:X", null, "approved", "r", null));
        await Assert.ThrowsAsync<DomainValidationException>(() => env.Reviews.RecordAsync("assignment", "USER0000\u001fZC:FI:ROLE_0000", null, "maybe", "r", null));
        await Assert.ThrowsAsync<DomainValidationException>(() => env.Reviews.RecordAsync("sod_finding", "f1", "short", "approved", "r", null));
    }

    [Fact]
    public async Task Chain_verification_detects_tampering_that_bypasses_the_triggers()
    {
        await using var env = await CoreEnv.StartAsync();
        await env.RunImportAsync("users", Csv.Users(Csv.Assignments(3, 1, 3)));
        await env.Reviews.RecordAsync("assignment", "USER0000\u001fZC:FI:ROLE_0000", null, "approved", "r", null);
        await env.Reviews.RecordAsync("assignment", "USER0001\u001fZC:FI:ROLE_0001", null, "rejected", "r", null);
        await using (var db = await env.Factory.CreateDbContextAsync())
        {
            // An attacker with file access drops the trigger first; the hash chain still exposes the edit.
            await db.Database.ExecuteSqlRawAsync("DROP TRIGGER ReviewDecisions_NoUpdate; UPDATE ReviewDecisions SET Decision = 'approved' WHERE Id = 2;");
        }
        var chain = await env.Reviews.VerifyChainAsync();
        Assert.False(chain.Ok);
        Assert.Equal(2, chain.BrokenAt);
    }
}
