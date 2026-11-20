using System.Text.Json;
using Microsoft.AspNetCore.Http.Features;
using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;
using AuthLens.Application;
using AuthLens.Domain.Analysis;
using AuthLens.Domain.Roles;
using AuthLens.Domain.Sod;
using AuthLens.Persistence;

namespace AuthLens.Api;

public sealed record Page<T>(IReadOnlyList<T> Items, int Total, int Offset, int Limit, ActiveIds Datasets);

public sealed record ReviewRequest(string SubjectType, string SubjectKey, string? EvidenceVersion, string Decision, string? Comment);

public static class Endpoints
{
    public const int MaxLimit = 100;
    public const long MaxUploadBytes = 128L * 1024 * 1024;

    private static (int Offset, int Limit) Paging(int? offset, int? limit)
    {
        var o = offset ?? 0;
        var l = limit ?? 50;
        if (o < 0) throw new DomainValidationException("offset must not be negative.");
        if (l is < 1 or > MaxLimit) throw new DomainValidationException($"limit must be between 1 and {MaxLimit}.");
        return (o, l);
    }

    private static Page<T> PageOf<T>(IReadOnlyList<T> rows, int offset, int limit, ActiveIds ids) => new(rows.Skip(offset).Take(limit).ToList(), rows.Count, offset, limit, ids);

    private static DateOnly Today() => DateOnly.FromDateTime(DateTime.Now);

    public static void Map(WebApplication app)
    {
        app.MapGet("/health/live", () => Results.Ok(new { status = "live" })).ExcludeFromDescription();
        app.MapGet("/health/ready", (DatabaseMaintenance db) => db.Ready
            ? Results.Ok(new { status = "ready" })
            : Results.Json(new { status = "not_ready", reason = db.NotReadyReason }, statusCode: 503)).ExcludeFromDescription();

        var api = app.MapGroup("/api/v1");

        api.MapGet("/roles", async (SnapshotService snapshots, [FromQuery] string? search, [FromQuery(Name = "function_key")] string[]? functionKeys,
            [FromQuery] string[]? tcode, [FromQuery(Name = "transaction_mode")] string? transactionMode, [FromQuery(Name = "exclude_tcode")] string[]? excludeTcodes,
            [FromQuery(Name = "exclude_mode")] string? excludeMode, [FromQuery] string? sort, [FromQuery] bool? descending, [FromQuery] int? offset, [FromQuery] int? limit,
            CancellationToken ct) =>
        {
            var (o, l) = Paging(offset, limit);
            var snapshot = await snapshots.GetAsync(ct);
            var rows = RoleLookup.Find(snapshot.Catalogue, new RoleLookupQuery(search, functionKeys, null, tcode, transactionMode ?? "and", false, null, excludeTcodes, excludeMode ?? "any"));
            Func<RoleSummary, IComparable> key = sort switch
            {
                null or "" or "relevance" => r => 0,
                "agr_name" => r => r.AgrName,
                "function_key" => r => r.FunctionKey,
                "tcode_count" => r => r.TcodeCount,
                _ => throw new DomainValidationException("Unsupported sort."),
            };
            // Stable sort; ties keep the v1 result order, so the default order is exactly v1's.
            var ordered = (descending == true ? rows.OrderByDescending(key) : rows.OrderBy(key)).ToList();
            return PageOf(ordered, o, l, snapshot.Ids);
        }).WithName("ListRoles");

        api.MapGet("/users", async (SnapshotService snapshots, [FromQuery] string? search, [FromQuery] string[]? group, [FromQuery] string[]? role,
            [FromQuery] string[]? tcode, [FromQuery(Name = "transaction_mode")] string? transactionMode, [FromQuery(Name = "exclude_tcode")] string[]? excludeTcodes,
            [FromQuery(Name = "exclude_mode")] string? excludeMode, [FromQuery] string? status, [FromQuery(Name = "show_expired")] bool? showExpired,
            [FromQuery] string? sort, [FromQuery] bool? descending, [FromQuery] int? offset, [FromQuery] int? limit, CancellationToken ct) =>
        {
            var (o, l) = Paging(offset, limit);
            var snapshot = await snapshots.GetAsync(ct);
            var query = new UserLookupQuery(search ?? "", "", group, "", role, "", tcode, transactionMode ?? "and", excludeTcodes is { Length: > 0 }, excludeTcodes,
                excludeMode ?? "any", status ?? "", showExpired ?? false, sort ?? "username", descending ?? false);
            return PageOf(UserLookup.Find(snapshot.Users, snapshot.Catalogue.Roles.Count > 0, query, Today()), o, l, snapshot.Ids);
        }).WithName("ListUsers");

        api.MapGet("/users/compare", async (SnapshotService snapshots, [FromQuery] string left, [FromQuery] string right, [FromQuery] string? validity,
            [FromQuery] string? kind, [FromQuery] string? difference, [FromQuery] string[]? area, [FromQuery] string? search, [FromQuery] string? sort,
            [FromQuery] bool? descending, [FromQuery] int? offset, [FromQuery] int? limit, CancellationToken ct) =>
        {
            var (o, l) = Paging(offset, limit);
            var snapshot = await snapshots.GetAsync(ct);
            var result = UserComparison.Compare(snapshot.Catalogue, snapshot.Users, left, right, validity ?? "active", Today());
            var areas = (area ?? []).ToHashSet(StringComparer.Ordinal);
            var (diff, term, order, desc) = (difference ?? "", search ?? "", sort ?? "identifier", descending ?? false);
            IReadOnlyList<object> rows = (kind ?? "roles") switch
            {
                "roles" => UserComparison.Select(result.Roles, diff, areas, term, order, desc, r => r.Identifier, r => r.Difference, r => r.Areas, r => r.Description, r => r.A.Count, r => r.B.Count),
                "transactions" => UserComparison.Select(result.Transactions, diff, areas, term, order, desc, r => r.Identifier, r => r.Difference, r => r.Areas, _ => "", r => r.A.Count, r => r.B.Count),
                _ => throw new DomainValidationException("kind must be roles or transactions."),
            };
            return new { users = result.Users, page = PageOf(rows, o, l, snapshot.Ids) };
        }).WithName("CompareUsers");

        api.MapGet("/sod/findings", async (SnapshotService snapshots, [FromQuery(Name = "as_of")] string? asOf, [FromQuery] string? validity, [FromQuery] string? kind,
            [FromQuery] int? offset, [FromQuery] int? limit, CancellationToken ct) =>
        {
            var (o, l) = Paging(offset, limit);
            var snapshot = await snapshots.GetAsync(ct);
            var date = asOf is null ? Today() : DateOnly.TryParseExact(asOf, "yyyy-MM-dd", out var d) ? d : throw new DomainValidationException("as_of must be YYYY-MM-DD.");
            var result = SodAnalyzer.Analyze(snapshot.Catalogue, snapshot.Users, snapshot.Sod, date, validity ?? "active");
            var findings = (kind ?? "users") switch { "users" => result.Users, "roles" => result.Roles, _ => throw new DomainValidationException("kind must be users or roles.") };
            return new
            {
                evaluation_policy = SodSource.EvaluationPolicy, sod_content_hash = result.SodContentHash, as_of = result.AsOf, validity = result.Validity,
                users_available = result.UsersAvailable, eligible_assignments = result.EligibleAssignments, mapped_assignments = result.MappedAssignments,
                supported_risks = result.SupportedRisks, sod_available = snapshot.Sod is not null, page = PageOf(findings, o, l, snapshot.Ids),
            };
        }).WithName("ListSodFindings");

        api.MapPost("/imports/{source}", async (HttpContext http, string source, JobQueue queue, DatabaseOptions database, CancellationToken ct) =>
        {
            if (!Sources.IsKnown(source)) throw new DomainValidationException("Unknown import source.");
            var feature = http.Features.Get<IHttpMaxRequestBodySizeFeature>();
            if (feature is { IsReadOnly: false }) feature.MaxRequestBodySize = MaxUploadBytes + 1;
            var uploads = Path.Combine(database.DataDirectory, "uploads");
            Directory.CreateDirectory(uploads);
            var path = Path.Combine(uploads, $"{Guid.NewGuid():N}.csv");
            try
            {
                await using (var file = new FileStream(path, FileMode.CreateNew, FileAccess.Write, FileShare.None, 81920, useAsync: true))
                    await http.Request.Body.CopyToAsync(file, ct);
                if (new FileInfo(path).Length == 0) throw new DomainValidationException("The upload is empty.");
                var name = Path.GetFileName(http.Request.Headers["X-File-Name"].ToString());
                var key = http.Request.Headers["Idempotency-Key"].ToString();
                if (key.Length > 128) throw new DomainValidationException("Idempotency-Key is too long.");
                var policy = V1DataSources.ImportPolicy(await http.RequestServices.GetRequiredService<V1Settings>().GetAsync(ct));
                var payload = JsonSerializer.Serialize(new ImportPayload(source, path, name.Length == 0 ? $"{source}.csv" : name[..Math.Min(name.Length, 200)], Checks: policy), Sources.Json);
                var job = await queue.EnqueueAsync(ImportService.JobKind, payload, key.Length == 0 ? null : $"import:{source}:{key}", ct);
                if (!job.PayloadJson.Contains(Path.GetFileName(path), StringComparison.Ordinal)) File.Delete(path); // idempotent replay: the first upload is used
                return Results.Accepted($"/api/v1/jobs/{job.Id}", JobView(job));
            }
            catch
            {
                if (File.Exists(path)) File.Delete(path);
                throw;
            }
        }).WithName("StartImport").Accepts<IFormFile>("text/csv");

        api.MapGet("/jobs/{id:long}", async (long id, JobQueue queue, CancellationToken ct) =>
            await queue.GetAsync(id, ct) is { } job ? Results.Ok(JobView(job)) : throw new NotFoundException("Job not found.")).WithName("GetJob");
        api.MapPost("/jobs/{id:long}/cancel", async (long id, JobQueue queue, CancellationToken ct) =>
            await queue.RequestCancelAsync(id, ct) is { } job ? Results.Ok(JobView(job)) : throw new NotFoundException("Job not found.")).WithName("CancelJob");

        api.MapGet("/datasets", async (IDbContextFactory<AuthLensDb> factory, [FromQuery] string? source, CancellationToken ct) =>
        {
            await using var db = await factory.CreateDbContextAsync(ct);
            var rows = await db.Datasets.AsNoTracking().Where(d => source == null || d.Source == source).OrderByDescending(d => d.Id).Take(MaxLimit)
                .Select(d => new { d.Id, d.Source, d.Revision, d.Status, d.ContentHash, d.RecordCount, d.FileName, d.CreatedUtc, d.ActivatedUtc, d.ConfirmedBy, d.ConfirmedUtc, d.EvaluationJson })
                .ToListAsync(ct);
            return rows.Select(d => new { d.Id, d.Source, d.Revision, d.Status, d.ContentHash, d.RecordCount, d.FileName, d.CreatedUtc, d.ActivatedUtc, d.ConfirmedBy, d.ConfirmedUtc,
                Evaluation = d.EvaluationJson is null ? (JsonElement?)null : JsonDocument.Parse(d.EvaluationJson).RootElement });
        }).WithName("ListDatasets");
        api.MapPost("/datasets/{id:long}/confirm", async (HttpContext http, long id, ImportService imports, CancellationToken ct) =>
        {
            var dataset = await imports.ConfirmAsync(id, Actors.Name(http), ct);
            return new { dataset.Id, dataset.Source, dataset.Status, dataset.ConfirmedBy, dataset.ConfirmedUtc };
        }).WithName("ConfirmDataset");

        api.MapPost("/reviews", async (HttpContext http, ReviewRequest request, ReviewService reviews, CancellationToken ct) =>
        {
            var d = await reviews.RecordAsync(request.SubjectType, request.SubjectKey, request.EvidenceVersion, request.Decision, Actors.Name(http), request.Comment, ct);
            return Results.Created($"/api/v1/reviews/{d.Id}", d);
        }).WithName("RecordReview");
        api.MapGet("/reviews/assignment", async ([FromQuery] string user, [FromQuery] string role, ReviewService reviews, CancellationToken ct) =>
            await reviews.AssignmentStatusAsync(Sources.AssignmentKey(user, role), ct)).WithName("AssignmentReviewStatus");

        var admin = api.MapGroup("/admin");
        admin.MapGet("/integrity", async (DatabaseMaintenance maintenance, ReviewService reviews, CancellationToken ct) =>
        {
            var db = await maintenance.VerifyAsync(ct);
            var chain = await reviews.VerifyChainAsync(ct);
            return new { database_ok = db.Ok, problems = db.Problems, review_chain_ok = chain.Ok, review_chain_broken_at = chain.BrokenAt, review_decisions = chain.Count };
        }).WithName("VerifyIntegrity");
        // The same encrypted, verified archive as Settings, Backups (never a plaintext database copy), with the same boundary (a Server needs an
        // administrator account); 409 without a configured host backup key.
        admin.MapPost("/backups", async (HttpContext http, AuthLens.Application.Backups.ApplicationBackups backups, CancellationToken ct) =>
        {
            if (V1Backups.Guard(http) is { } refused) return refused;
            try { return Results.Content((await backups.CreateAsync(BackupKind.Manual, "", Actors.Name(http), ct)).ToJsonString(), "application/json"); }
            catch (AuthLens.Application.Backups.BackupException error) { return Results.Json(new { detail = error.Message }, statusCode: error.Status); }
        }).WithName("CreateBackup");
        admin.MapGet("/backups", async (IDbContextFactory<AuthLensDb> factory, CancellationToken ct) =>
        {
            await using var db = await factory.CreateDbContextAsync(ct);
            return await db.Backups.AsNoTracking().OrderByDescending(b => b.Id).Take(MaxLimit).ToListAsync(ct);
        }).WithName("ListBackups");
        admin.MapPost("/backups/{id:long}/confirm-upgrade", async (long id, WriteCoordinator writer, CancellationToken ct) => await writer.WriteAsync(async (db, c) =>
        {
            var backup = await db.Backups.FirstOrDefaultAsync(b => b.Id == id && b.Kind == BackupKind.Migration, c) ?? throw new NotFoundException("Migration backup not found.");
            backup.AdminConfirmedUtc ??= DateTime.UtcNow;
            return backup;
        }, ct)).WithName("ConfirmUpgrade");
    }

    private static object JobView(Job job) => new
    {
        job.Id, job.Kind, job.Status, job.Attempts, job.MaxAttempts, job.Progress, job.ProgressText, job.CancelRequested, job.Error, job.CreatedUtc, job.StartedUtc, job.FinishedUtc,
        Result = job.ResultJson is null ? (JsonElement?)null : JsonDocument.Parse(job.ResultJson).RootElement,
    };
}
