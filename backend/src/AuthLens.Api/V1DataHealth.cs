using System.Text.Json.Nodes;
using Microsoft.EntityFrameworkCore;
using AuthLens.Application;
using AuthLens.Domain.Roles;
using AuthLens.Persistence;

namespace AuthLens.Api;

/// <summary>Port of routers/data_health.py: coverage of the active validated snapshots and the same finding catalogue, labels and availability rules.
/// Review continuity comes from the .NET review store (hash chain, invalidated-and-reappeared assignments). Employee Directory
/// source and identity coverage come from the active directory dataset (feature switch applied).</summary>
public static class V1DataHealth
{
    private static readonly (string Id, string Title, string Severity, string Explanation)[] Labels =
    [
        ("unmapped", "Assigned roles absent from catalogue", "warning", "No exact or unambiguous wildcard mapping; absence does not prove invalid access."),
        ("ambiguous", "Ambiguous catalogue matches", "warning", "Multiple equally specific catalogue patterns; no transaction access is inferred."),
        ("unknown_dates", "Assignments with missing dates", "warning", "Missing bounds do not establish current access."),
        ("expired", "Expired assignment records", "information", "Historical records; not inherently a security or data-quality problem."),
        ("future", "Future assignment records", "information", "Scheduled assignments; not evidence of current access."),
        ("unparsed_release", "Unparsed release-role names", "information", "Naming does not match the confirmed PR/PO parser; records are retained."),
        ("no_transactions", "Catalogue roles without T-code mappings", "information", "The export may omit mappings; this does not prove no authorization."),
        ("missing_description", "Catalogue roles without descriptions", "information", "Optional description missing."),
        ("unknown_module", "Unclassified catalogue roles", "information", "No reliable SAP module from the imported catalogue."),
        ("unknown_type", "Unknown or missing SAP user type", "warning", "Technical values are retained; classification cannot be assumed."),
        ("lifecycle_integrity", "Review decision continuity cannot be confirmed", "warning", "The memory that links assignment decisions to the same identity is damaged, missing or outdated, so earlier assignment decisions read Outdated until an administrator re-baselines. Imports are unaffected."),
        ("reappeared_assignments", "Assignments needing a new review after reappearing", "information", "Assignments removed from the SAP import and later returned, or whose SAP user identity evidence changed. The earlier decision stays in history and reads Outdated until a new decision is recorded."),
        ("conflicting_identity", "Users with multiple identity/account observations", "information", "Different names, emails or account intervals may be legitimate source evidence; inspect before interpreting as a conflict."),
    ];

    private static Dictionary<string, List<Dictionary<string, object?>>> Calculations(Snapshot state, DateOnly today)
    {
        var findings = Labels.Where(l => l.Id is not ("lifecycle_integrity" or "reappeared_assignments")).ToDictionary(l => l.Id, _ => new List<Dictionary<string, object?>>());
        foreach (var a in state.Users.Assignments.Where(a => a.Scope != "other"))
        {
            Dictionary<string, object?> Evidence() => new() { ["identifier"] = a.RoleName, ["username"] = a.Username, ["source"] = "users", ["destination"] = "user" };
            if (a.MatchStatus == "unmapped") findings["unmapped"].Add(Evidence());
            else if (a.MatchStatus == "ambiguous") findings["ambiguous"].Add(Evidence());
            var status = SapDates.IntervalStatus(a.ValidFrom, a.ValidTo, today);
            if (status is "expired" or "future") findings[status].Add(Evidence());
            if (string.IsNullOrEmpty(a.ValidFrom) || string.IsNullOrEmpty(a.ValidTo)) findings["unknown_dates"].Add(Evidence());
            if (a.Scope == "release" && a.Release is not { Parsed: true }) findings["unparsed_release"].Add(Evidence());
        }
        foreach (var role in state.Catalogue.Ordered)
        {
            Dictionary<string, object?> Row() => new() { ["identifier"] = role.AgrName, ["source"] = "roles", ["destination"] = "role" };
            if (role.TcodeCount == 0) findings["no_transactions"].Add(Row());
            if (string.IsNullOrEmpty(role.Text)) findings["missing_description"].Add(Row());
            if (string.IsNullOrEmpty(role.FunctionKey) || role.FunctionKey == "UNCLASSIFIED") findings["unknown_module"].Add(Row());
        }
        foreach (var key in state.Users.UserOrder)
        {
            var u = state.Users.Users[key];
            Dictionary<string, object?> Row() => new() { ["identifier"] = u.Username, ["username"] = u.Username, ["source"] = "users", ["destination"] = "user" };
            if (u.Accounts.Any(a => (a.UserType ?? "").PyUpper() is not ("A" or "B" or "C" or "S" or "L"))) findings["unknown_type"].Add(Row());
            if (u.Names.Where(n => n.First.Length > 0 || n.Last.Length > 0).Distinct().Count() > 1 || u.Emails.Count > 1 || u.Accounts.Count > 1) findings["conflicting_identity"].Add(Row());
        }
        return findings;
    }

    public static void Map(RouteGroupBuilder api)
    {
        api.MapGet("/data-health", async (HttpContext http, SnapshotService snapshots, V1Settings store, ReviewService reviews, IDbContextFactory<AuthLensDb> factory, CancellationToken ct) =>
        {
            var q = http.Request.Query;
            var finding = q["finding"].FirstOrDefault() ?? "";
            var offset = int.TryParse(q["offset"].FirstOrDefault() ?? "0", out var o) ? o : -1;
            var limit = int.TryParse(q["limit"].FirstOrDefault() ?? "25", out var l) ? l : -1;
            if (finding.Length > 64 || offset < 0 || limit is < 1 or > 100) return Results.Json(new { detail = "Invalid finding or paging parameters." }, statusCode: 422);
            var state = await snapshots.GetAsync(ct);
            var settings = await store.GetAsync(ct);
            var today = DateOnly.FromDateTime(DateTime.Now);
            var data = Calculations(state, today);
            var mapping = (bool?)settings["features"]?["user_role_mapping"] ?? true;
            var catalogue = state.Ids.Roles is not null;
            var users = mapping && state.Ids.Users is not null;

            // Review continuity (routers/data_health._continuity): the assignment lifecycle memory, plus, beyond v1, the hash chains of the decision stores.
            await using var db = await factory.CreateDbContextAsync(ct);
            // The memory follows the committed revision first (v1 observes inside the load; here the import hook may still be running).
            var memory = http.RequestServices.GetRequiredService<AssignmentLifecycle>();
            await memory.ObserveAsync(ct);
            var lifecycle = await memory.ProblemsAsync(ct);
            static Dictionary<string, object?> Item((string Key, string User, string Role, string Reason) x) =>
                new() { ["identifier"] = x.Role, ["username"] = x.User, ["source"] = "review decisions", ["destination"] = "user", ["reason"] = x.Reason };
            var integrity = lifecycle.Affected.Select(Item).ToList();
            if (integrity.Count == 0 && lifecycle.State != "ok")
                integrity.Add(new() { ["identifier"] = "Review continuity", ["source"] = "review decisions", ["destination"] = "user", ["reason"] = lifecycle.State });
            var detail = lifecycle.Detail;
            var chain = await reviews.VerifyChainAsync(ct);
            var sodChain = await http.RequestServices.GetRequiredService<SodDecisionStore>().VerifyChainAsync(ct);
            foreach (var (ok, at, history) in new[] { (chain.Ok, chain.BrokenAt, "Account Review decisions"), (sodChain.Ok, sodChain.BrokenAt, "SoD decisions") })
                if (!ok)
                {
                    integrity.Add(new() { ["identifier"] = "Review continuity", ["source"] = "review decisions", ["destination"] = "user", ["reason"] = $"{history}: hash chain broken at decision {at}" });
                    detail = (detail + $" The {history} history failed its hash-chain verification.").Trim();
                }
            var continuity = new Dictionary<string, List<Dictionary<string, object?>>>
            {
                ["lifecycle_integrity"] = integrity, ["reappeared_assignments"] = lifecycle.Pending.Select(Item).ToList(),
            };

            var findings = Labels.Select(label =>
            {
                var usable = label.Id is "no_transactions" or "missing_description" or "unknown_module" ? catalogue
                    : users && (label.Id is "unmapped" or "ambiguous" ? catalogue : true);
                int? count = continuity.TryGetValue(label.Id, out var c) ? c.Count : usable ? data[label.Id].Count : null;
                var explanation = label.Id == "lifecycle_integrity" && continuity["lifecycle_integrity"].Count > 0 ? label.Explanation + " " + detail : label.Explanation;
                return new Dictionary<string, object?> { ["id"] = label.Id, ["title"] = label.Title, ["severity"] = label.Severity, ["count"] = count, ["explanation"] = explanation };
            }).ToList();
            var eligible = users ? state.Users.Assignments.Where(a => a.Scope != "other").ToList() : [];
            var matched = eligible.Count(a => a.MatchStatus is "exact" or "wildcard");
            static object Ratio(string label, int n, int d, bool available) => new
            {
                label, numerator = available ? n : (int?)null, denominator = available ? d : (int?)null,
                percent = available && d > 0 ? Math.Round(100.0 * n / d, 1, MidpointRounding.ToEven) : (double?)null,
            };
            var selected = findings.FirstOrDefault(f => (string)f["id"]! == finding);
            var rows = selected is not null && selected["count"] is not null ? (continuity.GetValueOrDefault(finding) ?? data.GetValueOrDefault(finding) ?? []) : [];
            var directory = V1Employees.Status(state, settings, @private: false);
            var coverage = (Dictionary<string, int>)directory["coverage"]!;
            var datasets = await db.Datasets.AsNoTracking().Where(d => d.Status == DatasetStatus.Active).ToListAsync(ct);
            string? Last(string source) => datasets.FirstOrDefault(d => d.Source == source)?.ActivatedUtc?.ToString("yyyy-MM-dd'T'HH:mm:ss.ffffff'+00:00'");
            object Totals(string source)
            {
                var report = datasets.FirstOrDefault(d => d.Source == source)?.ReportJson is { } json ? JsonNode.Parse(json) : null;
                return new { parsed_rows = (int?)report?["parsed_rows"], unique_records = (int?)report?["unique_records"], duplicate_rows = (int?)report?["duplicate_rows"] };
            }
            return Results.Ok(new
            {
                sources = new object[]
                {
                    new { id = "roles", name = "Role Catalogue", enabled = true, configured = !string.IsNullOrEmpty((string?)settings["data_csv_path"]), available = catalogue,
                        records = catalogue ? state.Catalogue.Roles.Count : (int?)null, snapshot = catalogue ? "Durable local snapshot" : "Memory; no durable snapshot yet", last_successful = Last("roles") },
                    new { id = "users", name = "User–Role Mapping", enabled = mapping, configured = !string.IsNullOrEmpty((string?)settings["user_csv_path"]), available = state.Ids.Users is not null,
                        records = state.Ids.Users is not null ? state.Users.Users.Count : (int?)null, snapshot = state.Ids.Users is not null ? "Durable local snapshot" : "Memory; no durable snapshot yet", last_successful = Last("users") },
                    new { id = "employees", name = "Employee Directory", enabled = (bool)directory["enabled"]!, configured = (bool)directory["configured"]!, available = state.Directory is not null,
                        records = state.Directory?.Rows.Count, snapshot = state.Directory is not null ? "Durable local snapshot" : "No durable snapshot", last_successful = Last("employees") },
                    new { id = "sod", name = "SoD Matrix", enabled = true, configured = !string.IsNullOrEmpty((string?)settings["sod_csv_path"]), available = state.Sod is not null,
                        records = state.Sod?.Records.Count, snapshot = state.Sod is not null ? "Durable local snapshot" : "No durable snapshot", last_successful = Last("sod") },
                },
                coverage = new[]
                {
                    Ratio("Business/release assignment records mapped to catalogue", matched, eligible.Count, users && catalogue),
                    Ratio("Catalogue roles with transaction mappings", state.Catalogue.Ordered.Count(r => r.TcodeCount > 0), state.Catalogue.Roles.Count, catalogue),
                    Ratio("SAP identities matched to Employee Directory", coverage.GetValueOrDefault("matched"), (int)directory["coverage_total"]!, (int)directory["coverage_total"]! > 0),
                },
                findings, items = rows.Skip(offset).Take(limit).ToList(), total = rows.Count, offset, limit,
                directory_coverage_reason = (string)directory["coverage_reason"]!,
                data_revision = V1Access.Revision(state.Ids),
                import_totals = new { roles = Totals("roles"), users = Totals("users") },
                validation_note = "Only validated published snapshots are counted. Invalid headers, missing usernames, invalid dates and reversed intervals reject the replacement atomically. Identical duplicate rows are deduplicated at import; import totals below count raw rows, not duplicate role definitions.",
            });
        });
    }
}
