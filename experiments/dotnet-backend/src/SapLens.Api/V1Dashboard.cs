using SapLens.Application;
using SapLens.Domain.Roles;

namespace SapLens.Api;

/// <summary>Port of routers/dashboard.py: aggregates of the active validated snapshots. Missing or disabled sources are never zero-filled.
/// Employee Directory and Account Review are not migrated yet; their metrics are null with an explicit reason, never estimated.</summary>
public static class V1Dashboard
{
    public const string DirectoryReason = "The Employee Directory is not available in the .NET server yet.";
    public const string ReviewReason = "Account Review is not available in the .NET server yet.";
    public static readonly string[] Bands = ["0–5", "6–10", "11–20", "21–30", "31+"];

    public static string Band(int count) => count <= 5 ? Bands[0] : count <= 10 ? Bands[1] : count <= 20 ? Bands[2] : count <= 30 ? Bands[3] : Bands[4];

    public static void Map(RouteGroupBuilder api)
    {
        api.MapGet("/dashboard", async (SnapshotService snapshots, V1Settings store, CancellationToken ct) =>
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
                .Select(k => V1Compatibility.ModuleEnabled(k) ? 1 : 0).Sum() : null, "roles", "Open Role Lookup and its SAP area filters.");
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
            Add("employees", "Employee Directory records", null, "employees", "Open directory import and data quality.", DirectoryReason);
            Add("email_matches", "Matched SAP identities", null, "review", "Exact matches of SAP identities; open directory data quality.", DirectoryReason);
            Add("directory_missing", "Missing matches", null, "review", "SAP users without an email or whose email is not in the directory; open them in Account Review.", DirectoryReason);
            Add("directory_ambiguous", "Ambiguous matches", null, "review", "Duplicate directory emails or SAP emails shared by several users; open them in Account Review.", DirectoryReason);
            Add("unresolved", "Missing or ambiguous directory matches", null, "review", "Includes missing SAP email, unmatched and ambiguous evidence; open data quality.", DirectoryReason);
            var reviewReason = mapping ? ReviewReason : reason;
            Add("account_review", "Accounts requiring review", null, "review", "Open Account Review.", reviewReason);
            foreach (var (id, label) in new[] { ("reviewed", "Completed reviews"), ("pending", "Pending reviews"), ("outdated", "Outdated reviews") })
                Add(id, label, null, "review", "Open Account Review.", reviewReason);
            if (mapping)
            {
                Add("position_changes", "Users requiring review — Position changes", null, "review",
                    "Department or job title changed between Employee Directory imports and not yet reviewed. Separate from SoD conflicts and other account findings; opens Account Review.", DirectoryReason);
                Add("ad_disabled_open", "AD disabled / SAP valid and unlocked", null, "review", "Reliably matched AD and SAP account evidence.", DirectoryReason);
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
                coverage_total = 0,
                sources = new[]
                {
                    Source("roles", "Role Catalogue", true, !string.IsNullOrEmpty((string?)settings["data_csv_path"]), catalogue, Freshness("roles", "data_csv_path")),
                    Source("users", "User–Role Mapping", mappingEnabled, !string.IsNullOrEmpty((string?)settings["user_csv_path"]), state.Ids.Users is not null, Freshness("users", "user_csv_path")),
                    Source("employees", "Employee Directory", false, false, false, (null, null)),
                },
                as_of = (string?)null,
                notice = "Current local snapshots only; no historical trends or effective-authorization claims.",
            });
        });
    }
}
