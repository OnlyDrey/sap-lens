using Microsoft.AspNetCore.Mvc;
using SapLens.Application;
using SapLens.Domain.Analysis;
using SapLens.Domain.Roles;
using SapLens.Domain.Users;

namespace SapLens.Api;

/// <summary>Phase 2B: v1 User Access (`/api/access/users`, user detail) and Compare Users (`/api/user-comparison`, evidence) in v1 shapes, from the
/// equivalence-tested C# domain. Filters that need data not migrated yet (username lists, functional groups, managers, missing roles, assignment
/// bands, assignment dates) and the Employee Directory sorts answer 501 instead of being ignored: a filter is never silently dropped.</summary>
public static class V1Access
{
    private static readonly string[] Statuses = ["", "active", "expired", "future", "unknown"];
    private static readonly string[] Sorts = ["username", "group", "first_name", "last_name", "email", "account_status", "relevant_roles"];
    private static readonly string[] Validities = ["active", "expired", "future", "unknown", "all"];

    private static DateOnly Today() => DateOnly.FromDateTime(DateTime.Now);
    private static IResult Detail(int status, string detail) => Results.Json(new { detail }, statusCode: status);

    public static void Map(RouteGroupBuilder api)
    {
        api.MapGet("/access/users", async (HttpContext http, SnapshotService snapshots, CancellationToken ct) =>
        {
            var q = http.Request.Query;
            foreach (var unsupported in new[] { "usernames", "functional_groups", "managers", "missing_roles", "assignment_band" })
                if (q[unsupported].Any(v => !string.IsNullOrEmpty(v)))
                    return V1Compatibility.NotMigrated(http, $"access/users?{unsupported}=… (filter not migrated yet)");
            var sort = q["sort"].FirstOrDefault() ?? "username";
            if (sort is "job_title" or "department") return V1Compatibility.NotMigrated(http, $"access/users?sort={sort} (Employee Directory not migrated yet)");
            var status = q["status"].FirstOrDefault() ?? "";
            var mode = q["transaction_mode"].FirstOrDefault() ?? "and";
            var excludeMode = q["exclude_mode"].FirstOrDefault() ?? "any";
            if (!Sorts.Contains(sort) || !Statuses.Contains(status) || mode is not ("and" or "or") || excludeMode is not ("any" or "all"))
                return Detail(422, "Unsupported filter value.");
            if (!Paging(q, 50, out var offset, out var limit)) return Detail(422, "offset must be ≥ 0 and limit between 1 and 100.");
            if (q["groups"].Count > 50 || q["roles"].Count > 50 || q["tcodes"].Count > 21 || q["exclude_tcodes"].Count > 21) return Detail(422, "Too many filter values.");
            var snapshot = await snapshots.GetAsync(ct);
            var showExpired = Flag(q, "show_expired");
            var query = new UserLookupQuery(q["search"].FirstOrDefault() ?? "", q["group"].FirstOrDefault() ?? "", [.. q["groups"].OfType<string>()], q["role"].FirstOrDefault() ?? "",
                [.. q["roles"].OfType<string>()], q["tcode"].FirstOrDefault() ?? "", [.. q["tcodes"].OfType<string>()], mode, Flag(q, "exclude_transactions"),
                [.. q["exclude_tcodes"].OfType<string>()], excludeMode, status, showExpired, sort, Flag(q, "descending"));
            var today = Today();
            var result = UserLookup.Find(snapshot.Users, snapshot.Catalogue.Roles.Count > 0, query, today);
            var anchor = q["anchor"].FirstOrDefault() ?? "";
            var pageItems = result.Skip(offset).Take(limit).ToList();
            if (anchor.Length > 0)
            {
                var wanted = RoleNames.NormalizeUsername(anchor);
                var index = result.FindIndex(u => RoleNames.NormalizeUsername(u.Username) == wanted);
                return Results.Ok(new
                {
                    items = pageItems.Select(Row).ToList(), total = result.Count, offset, limit,
                    navigation = new
                    {
                        index = index < 0 ? (int?)null : index, total = result.Count,
                        previous = index > 0 ? result[index - 1].Username : null, next = index >= 0 && index + 1 < result.Count ? result[index + 1].Username : null,
                    },
                });
            }
            var includeExpired = showExpired || status == "expired";
            var exportAssignments = result.Sum(u => snapshot.Users.Users[u.UserKey].Assignments.Count(a => includeExpired || SapDates.IntervalStatus(a.ValidFrom, a.ValidTo, today) != "expired"));
            var groups = snapshot.Users.Users.Values.SelectMany(u => u.Groups).Where(g => g.Length > 0).Distinct(StringComparer.Ordinal).Order(StringComparer.Ordinal).ToList();
            return Results.Ok(new
            {
                items = pageItems.Select(Row).ToList(), total = result.Count, offset, limit, username_filter = (object?)null,
                loaded = snapshot.Ids.Users is not null, catalogue_loaded = snapshot.Catalogue.Roles.Count > 0,
                report = new
                {
                    unique_users = snapshot.Users.Users.Count, assignments = snapshot.Users.Assignments.Count, relevant_assignments = snapshot.Users.RelevantAssignments,
                    directory_only_users = snapshot.Users.DirectoryOnlyUsers, invalid_catalogue_patterns = snapshot.Users.InvalidCataloguePatterns, group_count = snapshot.Users.GroupCount,
                },
                as_of = today.ToString("yyyy-MM-dd"), data_revision = Revision(snapshot), groups, groups_total = snapshot.Users.GroupCount, export_assignments = exportAssignments,
            });
        });

        api.MapGet("/access/users/{**username}", async (HttpContext http, string username, SnapshotService snapshots, CancellationToken ct) =>
        {
            var q = http.Request.Query;
            foreach (var unsupported in new[] { "valid_from_min", "valid_from_max", "valid_to_min", "valid_to_max", "open_ended" })
                if (q[unsupported].Any(v => !string.IsNullOrEmpty(v))) return V1Compatibility.NotMigrated(http, $"access/users/…?{unsupported}=… (date filters not migrated yet)");
            if (q["include_missing_end"].FirstOrDefault() is "false") return V1Compatibility.NotMigrated(http, "access/users/…?include_missing_end=false (date filters not migrated yet)");
            var status = q["status"].FirstOrDefault() ?? "";
            var scope = q["scope"].FirstOrDefault() ?? "";
            var mode = q["transaction_mode"].FirstOrDefault() ?? "and";
            if (!Statuses.Contains(status) || scope is not ("" or "business" or "release" or "other" or "all") || mode is not ("and" or "or")) return Detail(422, "Unsupported filter value.");
            if (!Paging(q, 50, out var offset, out var limit) || !NonNegative(q, "account_offset", out var accountOffset) || !NonNegative(q, "name_offset", out var nameOffset)
                || !NonNegative(q, "email_offset", out var emailOffset)) return Detail(422, "Offsets must be ≥ 0 and limit between 1 and 100.");
            var snapshot = await snapshots.GetAsync(ct);
            if (!snapshot.Users.Users.TryGetValue(RoleNames.NormalizeUsername(username), out var user)) return Detail(404, "User not found in the current local export.");
            var today = Today();
            var showExpired = Flag(q, "show_expired");
            var entries = user.Assignments.Where(a => UserLookup.Relevant(a, status, showExpired, today)
                && (scope.Length == 0 || (scope == "all" ? a.Scope is "business" or "release" : a.Scope == scope))).ToList();
            var unmapped = entries.Count(a => !a.Resolved || a.Tcodes.Count == 0);
            var tcode = q["tcode"].FirstOrDefault() ?? "";
            var wanted = TransactionFilters.Normalize(tcode.Length > 0 ? [tcode, .. q["tcodes"].OfType<string>()] : q["tcodes"].OfType<string>());
            if (wanted.Count > 0)
            {
                var names = TransactionFilters.MatchingRoleNames(snapshot.Users.TcodeIndex.ToDictionary(p => p.Key, p => p.Value.ToHashSet(StringComparer.Ordinal)), wanted, mode);
                entries = entries.Where(a => a.Resolved && names.Overlaps(a.CatalogueRoles)).ToList();
            }
            var rows = entries.OrderBy(a => RoleNames.Normalize(a.RoleName), StringComparer.Ordinal).ThenBy(a => a.ValidFrom ?? "", StringComparer.Ordinal).ThenBy(a => a.Id).ToList();
            var summary = UserLookup.Summary(user, entries, today);
            var items = rows.Skip(offset).Take(limit).Select(a =>
            {
                var view = AssignmentView(a, today);
                var role = a.CatalogueRoles.Count == 1 && a.Resolved && snapshot.Catalogue.Roles.TryGetValue(a.CatalogueRoles[0], out var r) ? r : null;
                view["role_description"] = role?.Text ?? "";
                view["transaction_roles"] = a.Resolved && wanted.Count > 0
                    ? a.CatalogueRoles.Where(snapshot.Catalogue.Roles.ContainsKey).SelectMany(n => snapshot.Catalogue.Roles[n].SingleRoles)
                        .Where(s => s.Tcodes.Any(t => wanted.Any(p => TransactionFilters.MatchingCodes(snapshot.Users.TcodeIndex, p).Contains(t.Code.ToUpperInvariant()))))
                        .Select(s => s.ChildAgr).Distinct(StringComparer.Ordinal).Order(StringComparer.Ordinal).ToList()
                    : [];
                return view;
            }).ToList();
            return Results.Ok(new Dictionary<string, object?>
            {
                ["mapping_available"] = snapshot.Catalogue.Roles.Count > 0, ["unmapped_assignments"] = unmapped, ["data_revision"] = Revision(snapshot),
                ["items"] = items, ["total"] = rows.Count, ["offset"] = offset, ["limit"] = limit,
                ["username"] = summary.Username, ["user_key"] = summary.UserKey, ["groups"] = summary.Groups, ["first_name"] = summary.FirstName, ["last_name"] = summary.LastName,
                ["email"] = summary.Email, ["account_status"] = summary.AccountStatus, ["lock_status"] = summary.LockStatus, ["relevant_roles"] = summary.RelevantRoles,
                ["names"] = user.Names.Skip(nameOffset).Take(100).Select(n => new[] { n.First, n.Last }).ToList(), ["names_total"] = user.Names.Count,
                ["emails"] = user.Emails.Skip(emailOffset).Take(100).ToList(), ["emails_total"] = user.Emails.Count,
                ["accounts"] = user.Accounts.Skip(accountOffset).Take(50).Select(a => new
                {
                    valid_from = a.ValidFrom, valid_to = a.ValidTo, locked = a.Locked, user_type = a.UserType, user_group = a.UserGroup,
                    status = SapDates.IntervalStatus(a.ValidFrom, a.ValidTo, today),
                }).ToList(),
                ["account_total"] = user.Accounts.Count, ["account_offset"] = accountOffset, ["retained_assignments"] = user.Assignments.Count,
                ["as_of"] = today.ToString("yyyy-MM-dd"),
            });
        });

        api.MapGet("/user-comparison", async (HttpContext http, SnapshotService snapshots, CancellationToken ct) =>
        {
            var q = http.Request.Query;
            var (left, right) = (q["user_a"].FirstOrDefault() ?? "", q["user_b"].FirstOrDefault() ?? "");
            var validity = q["validity"].FirstOrDefault() ?? "active";
            var kind = q["kind"].FirstOrDefault() ?? "roles";
            var difference = q["difference"].FirstOrDefault() ?? "";
            var sort = q["sort"].FirstOrDefault() ?? "identifier";
            if (left.Length is 0 or > 512 || right.Length is 0 or > 512 || !Validities.Contains(validity) || kind is not ("roles" or "transactions")
                || difference is not ("" or "shared" or "a" or "b") || sort is not ("identifier" or "difference" or "a" or "b")) return Detail(422, "Invalid comparison parameters.");
            if (!Paging(q, 25, out var offset, out var limit)) return Detail(422, "offset must be ≥ 0 and limit between 1 and 100.");
            var snapshot = await snapshots.GetAsync(ct);
            var today = Today();
            var result = UserComparison.Compare(snapshot.Catalogue, snapshot.Users, left, right, validity, today);
            var areas = new HashSet<string>(q["areas"].OfType<string>().Where(a => a.Length > 0), StringComparer.Ordinal);
            if (q["area"].FirstOrDefault() is { Length: > 0 } single) areas.Add(single);
            var (search, descending) = (q["search"].FirstOrDefault() ?? "", Flag(q, "descending"));
            List<object> rows = kind == "roles"
                ? [.. UserComparison.Select(result.Roles, difference, areas, search, sort, descending, r => r.Identifier, r => r.Difference, r => r.Areas, r => r.Description, r => r.A.Count, r => r.B.Count)
                    .Skip(offset).Take(limit).Select(r => (object)new
                    {
                        identifier = r.Identifier, a = r.A.Take(25).ToList(), b = r.B.Take(25).ToList(), a_total = r.A.Count, b_total = r.B.Count, areas = r.Areas,
                        description = r.Description, difference = r.Difference,
                    })]
                : [.. UserComparison.Select(result.Transactions, difference, areas, search, sort, descending, r => r.Identifier, r => r.Difference, r => r.Areas, _ => "", r => r.A.Count, r => r.B.Count)
                    .Skip(offset).Take(limit).Select(r => (object)new
                    {
                        identifier = r.Identifier, a = r.A.Take(25).ToList(), b = r.B.Take(25).ToList(), a_total = r.A.Count, b_total = r.B.Count, areas = r.Areas, difference = r.Difference,
                    })];
            var total = kind == "roles"
                ? UserComparison.Select(result.Roles, difference, areas, search, sort, descending, r => r.Identifier, r => r.Difference, r => r.Areas, r => r.Description, r => r.A.Count, r => r.B.Count).Count
                : UserComparison.Select(result.Transactions, difference, areas, search, sort, descending, r => r.Identifier, r => r.Difference, r => r.Areas, _ => "", r => r.A.Count, r => r.B.Count).Count;
            object evidence = new Dictionary<string, object>();
            if (kind == "transactions")
            {
                var page = UserComparison.Select(result.Transactions, difference, areas, search, sort, descending, r => r.Identifier, r => r.Difference, r => r.Areas, _ => "", r => r.A.Count, r => r.B.Count)
                    .Skip(offset).Take(limit).ToList();
                evidence = new Dictionary<string, object>
                {
                    ["a"] = Provenance(result, page.SelectMany(r => r.A.Take(25)), "a"), ["b"] = Provenance(result, page.SelectMany(r => r.B.Take(25)), "b"),
                };
            }
            static Dictionary<string, int> Count<T>(IEnumerable<T> rows, Func<T, string> diff) => new[] { "shared", "a", "b" }.ToDictionary(d => d, d => rows.Count(r => diff(r) == d));
            return Results.Ok(new
            {
                items = rows, assignment_evidence = evidence, total, offset, limit,
                users = result.Users.Select(u => new
                {
                    username = u.Summary.Username, user_key = u.Summary.UserKey, groups = u.Summary.Groups, first_name = u.Summary.FirstName, last_name = u.Summary.LastName,
                    email = u.Summary.Email, account_status = u.Summary.AccountStatus, lock_status = u.Summary.LockStatus, relevant_roles = u.Summary.RelevantRoles,
                    identity_ambiguous = u.IdentityAmbiguous,
                }).ToList(),
                summary = new { roles = Count(result.Roles, r => r.Difference), transactions = Count(result.Transactions, r => r.Difference) },
                areas = result.Roles.SelectMany(r => r.Areas).Distinct(StringComparer.Ordinal).Order(StringComparer.Ordinal).ToList(),
                catalogue_available = snapshot.Catalogue.Roles.Count > 0, as_of = today.ToString("yyyy-MM-dd"), data_revision = Revision(snapshot),
            });
        });

        api.MapGet("/user-comparison/evidence", async (HttpContext http, SnapshotService snapshots, CancellationToken ct) =>
        {
            var q = http.Request.Query;
            var (left, right, identifier) = (q["user_a"].FirstOrDefault() ?? "", q["user_b"].FirstOrDefault() ?? "", q["identifier"].FirstOrDefault() ?? "");
            var side = q["side"].FirstOrDefault() ?? "a";
            var validity = q["validity"].FirstOrDefault() ?? "active";
            var kind = q["kind"].FirstOrDefault() ?? "roles";
            if (left.Length == 0 || right.Length == 0 || identifier.Length is 0 or > 512 || side is not ("a" or "b") || !Validities.Contains(validity) || kind is not ("roles" or "transactions"))
                return Detail(422, "Invalid evidence parameters.");
            if (!Paging(q, 25, out var offset, out var limit)) return Detail(422, "offset must be ≥ 0 and limit between 1 and 100.");
            var snapshot = await snapshots.GetAsync(ct);
            var result = UserComparison.Compare(snapshot.Catalogue, snapshot.Users, left, right, validity, Today());
            List<object> items;
            Dictionary<string, object> evidence = [];
            if (kind == "roles")
            {
                var row = result.Roles.FirstOrDefault(r => r.Identifier == RoleNames.Normalize(identifier));
                items = [.. (side == "a" ? row?.A : row?.B) ?? []];
            }
            else
            {
                var row = result.Transactions.FirstOrDefault(r => r.Identifier == identifier);
                var names = (side == "a" ? row?.A : row?.B)?.ToList() ?? [];
                items = [.. names];
                evidence = Provenance(result, names.Skip(offset).Take(limit), side);
            }
            return Results.Ok(new
            {
                items = items.Skip(offset).Take(limit).ToList(), total = items.Count, offset, limit, assignment_evidence = evidence, data_revision = Revision(snapshot),
                as_of = Today().ToString("yyyy-MM-dd"),
            });
        });
    }

    private static Dictionary<string, object> Provenance(ComparisonResult result, IEnumerable<string> names, string side) =>
        names.Distinct(StringComparer.Ordinal).Order(StringComparer.Ordinal).ToDictionary(n => n, n =>
        {
            var role = result.Roles.FirstOrDefault(r => r.Identifier == n);
            var list = (side == "a" ? role?.A : role?.B) ?? [];
            return (object)new { items = list.Take(25).ToList(), total = list.Count };
        });

    private static Dictionary<string, object?> AssignmentView(Assignment a, DateOnly today) => new()
    {
        ["id"] = a.Id, ["username"] = a.Username, ["user_key"] = a.UserKey, ["role_name"] = a.RoleName, ["user_group"] = a.UserGroup, ["scope"] = a.Scope,
        ["valid_from"] = a.ValidFrom, ["valid_to"] = a.ValidTo, ["user_valid_from"] = a.UserValidFrom, ["user_valid_to"] = a.UserValidTo, ["user_locked"] = a.UserLocked,
        ["user_type"] = a.UserType, ["match_status"] = a.MatchStatus, ["catalogue_roles"] = a.CatalogueRoles, ["tcodes"] = a.Tcodes.Take(100).ToList(), ["tcode_count"] = a.Tcodes.Count,
        ["release"] = a.Release is null ? null : a.Release.Parsed
            ? new Dictionary<string, object?> { ["parsed"] = true, ["document_type"] = a.Release.DocumentType, ["release_group"] = a.Release.ReleaseGroup, ["release_strategy"] = a.Release.ReleaseStrategy, ["opaque_scope"] = a.Release.OpaqueScope, ["opaque_suffix"] = a.Release.OpaqueSuffix }
            : new Dictionary<string, object?> { ["parsed"] = false, ["document_type"] = null, ["release_group"] = null, ["release_strategy"] = null },
        ["status"] = SapDates.IntervalStatus(a.ValidFrom, a.ValidTo, today), ["account_status"] = SapDates.IntervalStatus(a.UserValidFrom, a.UserValidTo, today),
    };

    /// <summary>One User Access row: the v1 summary plus organization annotations. Functional groups and the Employee Directory are not migrated, so the
    /// row states that truthfully (no membership, directory unavailable), as v1 does when those sources are absent.</summary>
    private static Dictionary<string, object?> Row(UserSummary u) => new()
    {
        ["username"] = u.Username, ["user_key"] = u.UserKey, ["groups"] = u.Groups, ["first_name"] = u.FirstName, ["last_name"] = u.LastName, ["email"] = u.Email,
        ["account_status"] = u.AccountStatus, ["lock_status"] = u.LockStatus, ["relevant_roles"] = u.RelevantRoles,
        ["job_title"] = "", ["department"] = "", ["directory_status"] = "unavailable", ["functional_group"] = null, ["functional_groups"] = Array.Empty<object>(),
        ["classification_status"] = "Unassigned",
    };

    private static string Revision(Snapshot snapshot) => $"{V1Compatibility.Boot}.{(snapshot.Ids.Roles ?? 0) + (snapshot.Ids.Users ?? 0) + (snapshot.Ids.Sod ?? 0)}.{(snapshot.Ids.Employees ?? 0)}";
    private static bool Flag(IQueryCollection q, string name) => q[name].FirstOrDefault() is "true" or "True" or "1";

    private static bool NonNegative(IQueryCollection q, string name, out int value)
    {
        value = 0;
        return q[name].FirstOrDefault() is not { } text || (int.TryParse(text, out value) && value >= 0);
    }

    private static bool Paging(IQueryCollection q, int defaultLimit, out int offset, out int limit)
    {
        limit = defaultLimit;
        if (!NonNegative(q, "offset", out offset)) return false;
        if (q["limit"].FirstOrDefault() is { } text && (!int.TryParse(text, out limit) || limit is < 1 or > 100)) return false;
        return true;
    }
}
