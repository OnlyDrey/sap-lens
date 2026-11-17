using SapLens.Application;
using SapLens.Domain.Roles;

namespace SapLens.Api;

/// <summary>Port of routers/dashboard.py: aggregates of the active validated snapshots. Missing or disabled sources are never zero-filled.
/// Position-change history is not migrated yet; its metric is null with an explicit reason, never estimated.</summary>
public static class V1Dashboard
{
    public const string PositionReason = "Position-change history between Employee Directory imports is not available in the .NET server yet.";
    public static readonly string[] Bands = ["0–5", "6–10", "11–20", "21–30", "31+"];

    public static string Band(int count) => count <= 5 ? Bands[0] : count <= 10 ? Bands[1] : count <= 20 ? Bands[2] : count <= 30 ? Bands[3] : Bands[4];

    public static void Map(RouteGroupBuilder api)
    {
        api.MapGet("/dashboard", async (SnapshotService snapshots, V1Settings store, IServiceProvider services, CancellationToken ct) =>
        {
            var state = await snapshots.GetAsync(ct);
            var settings = await store.GetAsync(ct);
            var today = DateOnly.FromDateTime(DateTime.Now);
            var catalogue = state.Ids.Roles is not null;
            var mappingEnabled = (bool?)settings["features"]?["user_role_mapping"] ?? true;
            var mapping = mappingEnabled && state.Ids.Users is not null;
            var metrics = new List<Dictionary<string, object?>>();
            void Add(string id, string label, int? value, string destination, string context, string reason = "Source not loaded") => metrics.Add(new()
            {
                ["id"] = id, ["label"] = label, ["value"] = value, ["destination"] = destination, ["context"] = context, ["unavailable_reason"] = value is null ? reason : null,
            });
            Add("roles", "Catalogue roles", catalogue ? state.Catalogue.Roles.Count : null, "roles", "Open the complete role catalogue.");
            Add("areas", "Enabled SAP areas", catalogue ? state.Catalogue.Ordered.Select(r => r.FunctionKey).Distinct(StringComparer.Ordinal)
                .Select(k => V1Compatibility.ModuleEnabled(k, settings["module_overrides"] as System.Text.Json.Nodes.JsonObject) ? 1 : 0).Sum() : null, "roles", "Open Role Lookup and its SAP area filters.");
            Add("mappings", "Role/T-code mappings", catalogue ? state.Catalogue.Ordered.Sum(r => r.TcodeCount) : null, "roles", "Distinct role/code pairs; open Role Lookup.");
            var reason = mappingEnabled ? "User Access CSV not loaded" : "User–Role Mapping disabled";
            var assignments = state.Users.Assignments;
            Add("users", "SAP users", mapping ? state.Users.Users.Count : null, "users", "Open all SAP users.", reason);
            Add("assignments", "Role assignment records", mapping ? assignments.Count : null, "users", "All imported intervals, including technical roles; open all users.", reason);
            Add("assigned_users", "Users with assignments", mapping ? assignments.Select(a => a.UserKey).Distinct(StringComparer.Ordinal).Count() : null, "users",
                "Any imported assignment; open all users, including users without assignments.", reason);
            Add("releases", "Release roles", mapping ? assignments.Where(a => a.Scope == "release").Select(a => RoleNames.Normalize(a.RoleName)).Distinct(StringComparer.Ordinal).Count() : null,
                "releases", "Distinct release roles across all validity states; opens the currently-valid release view.", reason);
            var statuses = mapping ? assignments.GroupBy(a => SapDates.IntervalStatus(a.ValidFrom, a.ValidTo, today)).ToDictionary(g => g.Key, g => g.Count()) : [];
            foreach (var status in new[] { "expired", "future" })
                Add(status, char.ToUpperInvariant(status[0]) + status[1..] + " assignment records", mapping ? statuses.GetValueOrDefault(status) : null, "users",
                    "Snapshot validity, not account state. Opens all users; select assignment status in User Details.", reason);
            var directory = V1Employees.Status(state, settings, @private: false);
            var directoryEnabled = (bool)directory["enabled"]!;
            var coverage = (Dictionary<string, int>)directory["coverage"]!;
            var coverageTotal = (int)directory["coverage_total"]!;
            var coverageReason = (string)directory["coverage_reason"]!;
            int? Coverage(Func<Dictionary<string, int>, int> value) => coverageTotal > 0 ? value(coverage) : null;
            Add("employees", "Employee Directory records", directoryEnabled && (bool)directory["loaded"]! ? state.Directory!.Rows.Count : null, "employees", "Open directory import and data quality.",
                directoryEnabled ? "Import directory records first" : "Employee Directory disabled");
            Add("email_matches", "Matched SAP identities", Coverage(c => c.GetValueOrDefault("matched")), "review", $"Exact matches of {coverageTotal} SAP identities; open directory data quality.", coverageReason);
            Add("directory_missing", "Missing matches", Coverage(c => c.GetValueOrDefault("missing_email") + c.GetValueOrDefault("unmatched")), "review",
                "SAP users without an email or whose email is not in the directory; open them in Account Review.", coverageReason);
            Add("directory_ambiguous", "Ambiguous matches", Coverage(c => c.GetValueOrDefault("duplicate_email") + c.GetValueOrDefault("ambiguous_sap_email")), "review",
                "Duplicate directory emails or SAP emails shared by several users; open them in Account Review.", coverageReason);
            Add("unresolved", "Missing or ambiguous directory matches", Coverage(c => c.Where(p => p.Key != "matched").Sum(p => p.Value)), "review",
                "Includes missing SAP email, unmatched and ambiguous evidence; open data quality.", coverageReason);
            if (mapping)
            {
                var rows = (await V1AccountReview.CurrentAsync(services, ct)).Rows;
                Add("account_review", "Accounts requiring review", rows.Count(r => (bool)r["needs_review"]!), "review",
                    "Review supported account evidence and stale annotations, not effective authorization or license savings.");
                var reviewed = rows.Count(r => V1AccountReview.Has(r, "reviewed"));
                foreach (var (id, label, value) in new[] { ("reviewed", "Completed reviews", reviewed), ("pending", "Pending reviews", rows.Count - reviewed), ("outdated", "Outdated reviews", rows.Count(r => (bool)r["stale"]!)) })
                    Add(id, label, value, "review", "All currently imported SAP accounts form the review population; outdated reviews are included in pending.");
                var directoryLoaded = directoryEnabled && (bool)directory["loaded"]!;
                Add("position_changes", "Users requiring review — Position changes", null, "review",
                    "Department or job title changed between Employee Directory imports and not yet reviewed. Separate from SoD conflicts and other account findings; opens Account Review.",
                    directoryLoaded ? PositionReason : "Employee Directory not loaded");
                Add("ad_disabled_open", "AD disabled / SAP valid and unlocked", directoryLoaded ? rows.Count(r => ((List<string>)r["findings"]!).Contains("ad_disabled_open")) : null, "review",
                    "Reliably matched AD and SAP account evidence.", coverageReason);
            }
            else
            {
                Add("account_review", "Accounts requiring review", null, "review", "Open Account Review.", reason);
                foreach (var (id, label) in new[] { ("reviewed", "Completed reviews"), ("pending", "Pending reviews"), ("outdated", "Outdated reviews") })
                    Add(id, label, null, "review", "Open Account Review.", reason);
            }

            Dictionary<string, int>? roleDistribution = catalogue
                ? state.Catalogue.Ordered.GroupBy(r => string.IsNullOrEmpty(r.FunctionKey) ? "UNCLASSIFIED" : r.FunctionKey, StringComparer.Ordinal).ToDictionary(g => g.Key, g => g.Count())
                : null;
            Dictionary<string, int>? assignmentDistribution = null;
            if (mapping)
            {
                assignmentDistribution = Bands.ToDictionary(b => b, _ => 0);
                foreach (var user in state.Users.Users.Values)
                {
                    var current = user.Assignments.Where(a => a.Scope is "business" or "release" && SapDates.IntervalStatus(a.ValidFrom, a.ValidTo, today) == "active")
                        .Select(a => RoleNames.Normalize(a.RoleName)).Distinct(StringComparer.Ordinal).Count();
                    assignmentDistribution[Band(current)]++;
                }
            }
            var lifecycle = settings["data_lifecycle"]?.AsObject();
            (string? Import, string? Checked) Freshness(string key, string pathField)
            {
                var reference = lifecycle?["sources"]?[key];
                return reference is not null && (string?)reference["path"] == ((string?)settings[pathField] ?? "") ? ((string?)reference["imported_at"], (string?)reference["checked_at"]) : (null, null);
            }
            static object Source(string id, string name, bool enabled, bool configured, bool available, (string? Import, string? Checked) f) =>
                new { id, name, enabled, configured, available, last_import = f.Import, last_checked = f.Checked };
            return Results.Ok(new
            {
                metrics,
                review_population = mapping ? state.Users.Users.Count : (int?)null,
                role_distribution = roleDistribution,
                assignment_distribution = assignmentDistribution,
                last_successful_refresh = (string?)lifecycle?["last_successful_refresh"],
                source_warning = (string?)null,
                coverage_total = coverageTotal,
                sources = new[]
                {
                    Source("roles", "Role Catalogue", true, !string.IsNullOrEmpty((string?)settings["data_csv_path"]), catalogue, Freshness("roles", "data_csv_path")),
                    Source("users", "User–Role Mapping", mappingEnabled, !string.IsNullOrEmpty((string?)settings["user_csv_path"]), state.Ids.Users is not null, Freshness("users", "user_csv_path")),
                    Source("employees", "Employee Directory", directoryEnabled, (bool)directory["configured"]!, (bool)directory["loaded"]!, Freshness("employees", "employee_csv_path")),
                },
                as_of = state.Directory is { } d && (bool)directory["loaded"]! ? d.ImportedAt : null,
                notice = "Current local snapshots only; no historical trends or effective-authorization claims.",
            });
        });
    }
}
