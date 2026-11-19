using System.Text.Json.Nodes;
using AuthLens.Application;
using AuthLens.Domain.Analysis;
using AuthLens.Domain.Roles;
using AuthLens.Domain.Users;

namespace AuthLens.Api;

/// <summary>Phase 2B: v1 User Access (`/api/access/users`, user detail) and Compare Users (`/api/user-comparison`, evidence) in v1 shapes, from the
/// equivalence-tested C# domain. Filters that need data not migrated yet (username lists, functional groups, managers, missing roles, assignment
/// bands, assignment dates) and the Employee Directory sorts answer 501 instead of being ignored: a filter is never silently dropped.</summary>
public static class V1Access
{
    private static readonly string[] Statuses = ["", "active", "expired", "future", "unknown"];
    private static readonly string[] Sorts = ["username", "group", "first_name", "last_name", "email", "account_status", "relevant_roles"];
    private static readonly string[] Validities = ["active", "expired", "future", "unknown", "all"];

    internal static DateOnly Today() => DateOnly.FromDateTime(DateTime.Now);
    private static IResult Detail(int status, string detail) => Results.Json(new { detail }, statusCode: status);

    private static readonly string[] AssignmentColumns = ["USERNAME", "FIRST_NAME", "LAST_NAME", "EMAIL", "USER_GROUP", "ROLE_NAME", "ROLE_VALID_FROM", "ROLE_VALID_TO",
        "ASSIGNMENT_STATUS", "PR_PO", "RELEASE_GROUP", "RELEASE_STRATEGY", "MATCHED_FILTER"];

    /// <summary>audit_assignments: every imported assignment of a user, except expired ones unless expired assignments are shown or filtered.</summary>
    private static IEnumerable<Assignment> AuditAssignments(SapUser user, bool showExpired, string status, DateOnly today) =>
        user.Assignments.Where(a => showExpired || status == "expired" || SapDates.IntervalStatus(a.ValidFrom, a.ValidTo, today) != "expired");

    /// <summary>routers/access.directory_filters: the shared filter set of the user listing, the selection and the export.</summary>
    private static (IResult? Error, (UserLookupQuery Query, bool ShowExpired, string Status) Value) Parse(HttpContext http)
    {
        var q = http.Request.Query;
        var sort = q["sort"].FirstOrDefault() ?? "username";
        // Directory sorts are applied after the lookup (OrganizationAsync); the lookup itself orders by username.
        if (sort is "job_title" or "department") sort = "username";
        if ((q["usernames"].FirstOrDefault() ?? "").Length > 16000 || q["missing_roles"].Count > 20 || (q["missing_mode"].FirstOrDefault() ?? "any") is not ("any" or "all")
            || (q["assignment_band"].FirstOrDefault() ?? "") is not ("" or "0–5" or "6–10" or "11–20" or "21–30" or "31+" or "0" or "1–5" or "6–20" or "21+"))
            return (Detail(422, "Unsupported filter value."), default);
        if (ParseUsernames(q["usernames"].FirstOrDefault() ?? "").Requested.Count > 500) return (Detail(422, "At most 500 different usernames can be filtered at once."), default);
        var status = q["status"].FirstOrDefault() ?? "";
        var mode = q["transaction_mode"].FirstOrDefault() ?? "and";
        var excludeMode = q["exclude_mode"].FirstOrDefault() ?? "any";
        if (!Sorts.Contains(sort) || !Statuses.Contains(status) || mode is not ("and" or "or") || excludeMode is not ("any" or "all")) return (Detail(422, "Unsupported filter value."), default);
        if (q["functional_groups"].Count > 50 || q["managers"].Count > 50 || q["groups"].Count > 50 || q["roles"].Count > 50 || q["tcodes"].Count > 21 || q["exclude_tcodes"].Count > 21) return (Detail(422, "Too many filter values."), default);
        var showExpired = Flag(q, "show_expired");
        var query = new UserLookupQuery(q["search"].FirstOrDefault() ?? "", q["group"].FirstOrDefault() ?? "", [.. q["groups"].OfType<string>()], q["role"].FirstOrDefault() ?? "",
            [.. q["roles"].OfType<string>()], q["tcode"].FirstOrDefault() ?? "", [.. q["tcodes"].OfType<string>()], mode, Flag(q, "exclude_transactions"),
            [.. q["exclude_tcodes"].OfType<string>()], excludeMode, status, showExpired, sort, Flag(q, "descending"));
        return (null, (query, showExpired, status));
    }

    public static void Map(RouteGroupBuilder api)
    {
        api.MapGet("/access/users", async (HttpContext http, SnapshotService snapshots, CancellationToken ct) =>
        {
            var q = http.Request.Query;
            if (Parse(http) is { Error: { } error }) return error;
            var (query, showExpired, status) = Parse(http).Value;
            if (!Paging(q, 50, out var offset, out var limit)) return Detail(422, "offset must be ≥ 0 and limit between 1 and 100.");
            var snapshot = await snapshots.GetAsync(ct);
            var today = Today();
            var org = await OrganizationAsync(http, snapshot, ct);
            var result = org.Filter(UserLookup.Find(snapshot.Users, snapshot.Catalogue.Roles.Count > 0, query, today, org.DirectoryFields));
            var Row = org.Row;
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
            var exportAssignments = result.Sum(u => AuditAssignments(snapshot.Users.Users[u.UserKey], showExpired, status, today).Count());
            var groups = snapshot.Users.Users.Values.SelectMany(u => u.Groups).Where(g => g.Length > 0).Distinct(StringComparer.Ordinal).Order(StringComparer.Ordinal).ToList();
            return Results.Ok(new
            {
                items = pageItems.Select(Row).ToList(), total = result.Count, offset, limit, username_filter = org.Feedback(result),
                loaded = snapshot.Ids.Users is not null, catalogue_loaded = snapshot.Catalogue.Roles.Count > 0,
                report = await UsersReport(http, snapshot, ct),
                as_of = today.ToString("yyyy-MM-dd"), data_revision = Revision(snapshot), groups, groups_total = snapshot.Users.GroupCount, export_assignments = exportAssignments,
            });
        });

        // Every username of the current filter result, in listing order (capped), so a selection across pages is an explicit list.
        api.MapGet("/access/users-selection", async (HttpContext http, SnapshotService snapshots, CancellationToken ct) =>
        {
            if (Parse(http) is { Error: { } error }) return error;
            var (query, _, _) = Parse(http).Value;
            var snapshot = await snapshots.GetAsync(ct);
            var org = await OrganizationAsync(http, snapshot, ct);
            var result = org.Filter(UserLookup.Find(snapshot.Users, snapshot.Catalogue.Roles.Count > 0, query, Today(), org.DirectoryFields));
            const int cap = 5000;
            return Results.Ok(new { total = result.Count, usernames = result.Take(cap).Select(u => u.Username).ToList(), truncated = result.Count > cap, limit = cap, data_revision = Revision(snapshot) });
        });

        // csv_exports.assignment_response for the filtered users: every retained assignment (expired ones only when shown or filtered), MATCHED_FILTER per row.
        api.MapGet("/access/exports/users", async (HttpContext http, SnapshotService snapshots, CancellationToken ct) =>
        {
            if (Parse(http) is { Error: { } error }) return error;
            var (query, showExpired, status) = Parse(http).Value;
            var snapshot = await snapshots.GetAsync(ct);
            if (snapshot.Ids.Users is null) return Detail(409, "No validated User Access dataset is loaded.");
            var today = Today();
            var org = await OrganizationAsync(http, snapshot, ct);
            var (found, evidence) = UserLookup.FindWithEvidence(snapshot.Users, snapshot.Catalogue.Roles.Count > 0, query, today, org.DirectoryFields);
            var result = org.Filter(found);
            var rows = result.SelectMany(u => AuditAssignments(snapshot.Users.Users[u.UserKey], showExpired, status, today)
                .Select(a => (Assignment: a, Identity: u, Matched: evidence.TryGetValue(u.UserKey, out var hit) && hit.Any(e => e.Id == a.Id)))).ToList();
            var csv = new System.Text.StringBuilder("\ufeff");
            V1Csv.Line(csv, AssignmentColumns, cells: false);
            static string Local(string? value) => SapDates.Parse(value) is { } d ? $"{d.Day:00}.{d.Month:00}.{d.Year:0000}" : "";
            foreach (var (a, identity, matched) in rows)
            {
                var status2 = SapDates.IntervalStatus(a.ValidFrom, a.ValidTo, today);
                V1Csv.Line(csv, [a.Username, identity.FirstName, identity.LastName, identity.Email, a.UserGroup, a.RoleName, Local(a.ValidFrom), Local(a.ValidTo),
                    char.ToUpperInvariant(status2[0]) + status2[1..], a.Release?.DocumentType, a.Release?.ReleaseGroup, a.Release?.ReleaseStrategy, matched ? "Yes" : "No"], cells: true);
            }
            var day = today.ToString("yyyy-MM-dd");
            http.Response.Headers["Content-Disposition"] = $"attachment; filename=\"authlens-user-directory-review-{day}.csv\"";
            http.Response.Headers["X-SAP-Lens-Data-Revision"] = Revision(snapshot);
            http.Response.Headers["X-SAP-Lens-As-Of"] = day;
            http.Response.Headers["X-SAP-Lens-Assignment-Count"] = rows.Count.ToString(System.Globalization.CultureInfo.InvariantCulture);
            http.Response.Headers.CacheControl = "no-store";
            return Results.Text(csv.ToString(), "text/csv; charset=utf-8");
        });

        api.MapGet("/access/users/{**username}", async (HttpContext http, string username, SnapshotService snapshots, CancellationToken ct) =>
        {
            var q = http.Request.Query;
            var (dates, dateError) = V1ReleaseRoles.Dates(q);
            if (dateError is not null) return dateError;
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
            var entries = user.Assignments.Where(a => dates!.Within(a) && UserLookup.Relevant(a, status, showExpired, today)
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
                        .Where(s => s.Tcodes.Any(t => wanted.Any(p => TransactionFilters.MatchingCodes(snapshot.Users.TcodeIndex, p).Contains(t.Code.PyUpper()))))
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

    internal static Dictionary<string, object?> AssignmentView(Assignment a, DateOnly today) => new()
    {
        ["id"] = a.Id, ["username"] = a.Username, ["user_key"] = a.UserKey, ["role_name"] = a.RoleName, ["user_group"] = a.UserGroup, ["scope"] = a.Scope,
        ["valid_from"] = a.ValidFrom, ["valid_to"] = a.ValidTo, ["user_valid_from"] = a.UserValidFrom, ["user_valid_to"] = a.UserValidTo, ["user_locked"] = a.UserLocked,
        ["user_type"] = a.UserType, ["match_status"] = a.MatchStatus, ["catalogue_roles"] = a.CatalogueRoles, ["tcodes"] = a.Tcodes.Take(100).ToList(), ["tcode_count"] = a.Tcodes.Count,
        ["release"] = a.Release is null ? null : a.Release.Parsed
            ? new Dictionary<string, object?> { ["parsed"] = true, ["document_type"] = a.Release.DocumentType, ["release_group"] = a.Release.ReleaseGroup, ["release_strategy"] = a.Release.ReleaseStrategy, ["opaque_scope"] = a.Release.OpaqueScope, ["opaque_suffix"] = a.Release.OpaqueSuffix }
            : new Dictionary<string, object?> { ["parsed"] = false, ["document_type"] = null, ["release_group"] = null, ["release_strategy"] = null },
        ["status"] = SapDates.IntervalStatus(a.ValidFrom, a.ValidTo, today), ["account_status"] = SapDates.IntervalStatus(a.UserValidFrom, a.UserValidTo, today),
    };

    /// <summary>The organizational context of a User Access request (MIG-004): the functional_groups / managers filter (organization.selection) and the
    /// row annotation (organization.annotate): Functional Group memberships and, for a user linked to exactly one Directory employee, job title and department.</summary>
    private sealed record Organization(Func<List<UserSummary>, List<UserSummary>> Filter, Func<UserSummary, Dictionary<string, object?>> Row, Func<List<UserSummary>, JsonObject?> Feedback,
        Func<string, (string Title, string Department)> DirectoryFields);

    private static readonly System.Text.RegularExpressions.Regex Separators = new(@"[\s,;]+");
    private static readonly System.Text.RegularExpressions.Regex ValidUsername = new("^[^\\s@,;<>\"\\x00-\\x1f]{1,40}$");

    /// <summary>username_filter.parse_usernames: exact names (first spelling, de-duplicated, in input order), duplicates and invalid entries.</summary>
    private static (List<string> Requested, int Duplicates, List<string> Invalid) ParseUsernames(string text)
    {
        var (requested, invalid, seen) = (new List<string>(), new List<string>(), new HashSet<string>());
        var duplicates = 0;
        foreach (var raw in Separators.Split(text))
        {
            var token = raw.Trim();
            if (token.Length == 0) continue;
            if (!ValidUsername.IsMatch(token)) { if (!invalid.Contains(token)) invalid.Add(token); continue; }
            if (!seen.Add(RoleNames.NormalizeUsername(token))) { duplicates++; continue; }
            requested.Add(token);
        }
        return (requested, duplicates, invalid);
    }

    /// <summary>current_role_count: distinct business/release roles with a currently valid assignment.</summary>
    private static int CurrentRoleCount(SapUser user, DateOnly today) => user.Assignments
        .Where(a => a.Scope is "business" or "release" && SapDates.IntervalStatus(a.ValidFrom, a.ValidTo, today) == "active").Select(a => RoleNames.Normalize(a.RoleName)).Distinct().Count();

    /// <summary>in_assignment_band: '6–10', '31+' or a single value such as '0'.</summary>
    private static bool InBand(int count, string band)
    {
        var match = System.Text.RegularExpressions.Regex.Match(band, "^(\\d+)(?:–(\\d+)|(\\+))?$");
        if (!match.Success) return false;
        var low = int.Parse(match.Groups[1].Value, System.Globalization.CultureInfo.InvariantCulture);
        int? high = match.Groups[3].Success ? null : match.Groups[2].Success ? int.Parse(match.Groups[2].Value, System.Globalization.CultureInfo.InvariantCulture) : low;
        return count >= low && (high is null || count <= high);
    }

    private static async Task<Organization> OrganizationAsync(HttpContext http, Snapshot snapshot, CancellationToken ct)
    {
        var q = http.Request.Query;
        var settings = await http.RequestServices.GetRequiredService<V1Settings>().GetAsync(ct);
        var directory = V1Employees.Available(snapshot, settings);
        var data = await http.RequestServices.GetRequiredService<FunctionalGroupStore>().ReadAsync(ct);
        var keep = V1FunctionalGroups.Selection(snapshot, directory, data, [.. q["functional_groups"].OfType<string>().Where(v => v.Length > 0)],
            [.. q["managers"].OfType<string>().Where(v => v.Length > 0)]);
        var classes = FunctionalGroupStore.ClassificationMap(data);
        var owners = directory is null ? null : AuthLens.Domain.Directory.EmployeeDirectory.SapEmailOwners(snapshot.Users.Users.Values);
        Dictionary<string, object?> Row(UserSummary u)
        {
            var (title, department, status) = ("", "", directory is null ? "unavailable" : "unmatched");
            if (directory is not null && snapshot.Users.Users.TryGetValue(u.UserKey, out var sap) && directory.MatchSapIdentity(sap, owners!) is ("matched", { } employee))
                (title, department, status) = (((string?)employee["title"] ?? "").Trim(), ((string?)employee["department"] ?? "").Trim(), "matched");
            classes.TryGetValue(u.Username.Trim().PyUpper(), out var record);
            return new()
            {
                ["username"] = u.Username, ["user_key"] = u.UserKey, ["groups"] = u.Groups, ["first_name"] = u.FirstName, ["last_name"] = u.LastName, ["email"] = u.Email,
                ["account_status"] = u.AccountStatus, ["lock_status"] = u.LockStatus, ["relevant_roles"] = u.RelevantRoles,
                ["job_title"] = title, ["department"] = department, ["directory_status"] = status,
                ["functional_group"] = record?["group"]?.DeepClone(),   // only with exactly one membership (compatibility)
                ["functional_groups"] = record is null ? new JsonArray() : new JsonArray([.. record["memberships"]!.AsArray().Select(m => m!["group"]!.DeepClone())]),
                ["classification_status"] = record is null ? "Unassigned" : (string)record["status"]!,
            };
        }
        var today = DateOnly.FromDateTime(DateTime.Now);
        // Exact username list (v1 username_filter), assignment band, missing catalogue roles (v1 missing_users) and the Directory sorts.
        var usernameText = q["usernames"].FirstOrDefault() ?? "";
        var parsed = usernameText.Trim().Length > 0 ? ParseUsernames(usernameText) : default;
        var listed = parsed.Requested?.Select(RoleNames.NormalizeUsername).Where(snapshot.Users.Users.ContainsKey).ToHashSet();
        var band = q["assignment_band"].FirstOrDefault() ?? "";
        var missingRoles = q["missing_roles"].OfType<string>().Where(v => v.Length > 0).ToList();
        HashSet<string>? missing = null;
        if (missingRoles.Count > 0)
        {
            missing = [];
            if (snapshot.Catalogue.Roles.Count > 0)
            {
                var wanted = missingRoles.Select(RoleNames.Normalize).ToHashSet();
                var all = (q["missing_mode"].FirstOrDefault() ?? "any") == "all";
                var groups = q["groups"].OfType<string>().Append(q["group"].FirstOrDefault() ?? "").Where(v => v.Length > 0).ToHashSet();
                var status = q["status"].FirstOrDefault() ?? "";
                var showExpired = (q["show_expired"].FirstOrDefault() ?? "") is "true" or "True" or "1";
                foreach (var (key, user) in snapshot.Users.Users)
                {
                    var entries = user.Assignments.Where(a => a.Scope != "other" && (groups.Count == 0 || groups.Contains(a.UserGroup))
                        && (status.Length > 0 ? SapDates.IntervalStatus(a.ValidFrom, a.ValidTo, today) == status : showExpired || SapDates.IntervalStatus(a.ValidFrom, a.ValidTo, today) != "expired")).ToList();
                    // Absence is concluded only from eligible assignments that are all mapped to catalogue roles.
                    if (entries.Count == 0 || entries.Any(a => !a.Resolved)) continue;
                    var held = entries.Select(a => RoleNames.Normalize(a.RoleName)).Concat(entries.SelectMany(a => a.CatalogueRoles.Select(RoleNames.Normalize))).ToHashSet();
                    var lacking = wanted.Where(w => !held.Contains(w)).Count();
                    if (all ? lacking == wanted.Count : lacking > 0) missing.Add(key);
                }
            }
        }
        var sort = q["sort"].FirstOrDefault() ?? "username";
        var descending = (q["descending"].FirstOrDefault() ?? "") is "true" or "True" or "1";
        (string Title, string Department) Fields(UserSummary u) => FieldsOf(u.UserKey);
        (string Title, string Department) FieldsOf(string userKey)
        {
            if (directory is not null && snapshot.Users.Users.TryGetValue(userKey, out var sap) && directory.MatchSapIdentity(sap, owners!) is ("matched", { } employee))
                return (((string?)employee["title"] ?? "").Trim(), ((string?)employee["department"] ?? "").Trim());
            return ("", "");
        }
        List<UserSummary> Filter(List<UserSummary> result)
        {
            var kept = result.Where(u => snapshot.Users.Users.TryGetValue(u.UserKey, out var user) && (keep is null || keep(user))
                && (listed is null || listed.Contains(u.UserKey)) && (missing is null || missing.Contains(u.UserKey))
                && (band.Length == 0 || InBand(CurrentRoleCount(user, today), band))).ToList();
            if (sort is not ("job_title" or "department")) return kept;
            // Users without a Directory value come last in both directions (v1).
            var valued = kept.Select(u => (Value: sort == "job_title" ? Fields(u).Title : Fields(u).Department, User: u)).ToList();
            var known = valued.Where(p => p.Value.Length > 0).OrderBy(p => p.Value.PyCasefold(), StringComparer.Ordinal).ThenBy(p => p.User.UserKey, StringComparer.Ordinal).ToList();
            if (descending) known.Reverse();
            return [.. known.Select(p => p.User), .. valued.Where(p => p.Value.Length == 0).Select(p => p.User).OrderBy(u => u.UserKey, StringComparer.Ordinal)];
        }
        JsonObject? Feedback(List<UserSummary> result)
        {
            if (parsed.Requested is null) return null;
            var keys = parsed.Requested.Select(n => (Key: RoleNames.NormalizeUsername(n), Name: n)).ToList();
            var present = keys.Where(k => snapshot.Users.Users.ContainsKey(k.Key)).Select(k => k.Key).ToList();
            var shown = result.Select(u => u.UserKey).ToHashSet();
            return new JsonObject
            {
                ["requested"] = parsed.Requested.Count, ["duplicates"] = parsed.Duplicates, ["invalid"] = new JsonArray([.. parsed.Invalid.Select(i => (JsonNode)i)]),
                ["found"] = present.Count, ["matched"] = present.Count(shown.Contains),
                ["filtered_out"] = new JsonArray([.. present.Where(k => !shown.Contains(k)).Take(100).Select(k => (JsonNode)snapshot.Users.Users[k].Username)]),
                ["unmatched"] = new JsonArray([.. keys.Where(k => !snapshot.Users.Users.ContainsKey(k.Key)).Select(k => (JsonNode)k.Name)]),
                ["limit"] = 500, ["exceeds_limit"] = parsed.Requested.Count > 500,
            };
        }
        return new Organization(Filter, Row, Feedback, FieldsOf);
    }

    /// <summary>source_info's report: v1's User Access import report (users.report without samples and file name) from the stored import report and the
    /// built directory's counts.</summary>
    internal static async Task<Dictionary<string, object?>> UsersReport(HttpContext http, Snapshot snapshot, CancellationToken ct)
    {
        if (snapshot.Ids.Users is not { } id) return [];
        var factory = http.RequestServices.GetRequiredService<Microsoft.EntityFrameworkCore.IDbContextFactory<AuthLens.Persistence.AuthLensDb>>();
        await using var db = await factory.CreateDbContextAsync(ct);
        var json = await Microsoft.EntityFrameworkCore.EntityFrameworkQueryableExtensions.FirstOrDefaultAsync(
            System.Linq.Queryable.Select(System.Linq.Queryable.Where(db.Datasets, d => d.Id == id), d => d.ReportJson), ct);
        var stored = json is null ? null : System.Text.Json.Nodes.JsonNode.Parse(json);
        var report = new Dictionary<string, object?>();
        foreach (var key in new[] { "import_profile", "import_version", "detected_columns", "resolved_mapping", "parsed_rows", "unique_records", "duplicate_rows", "warnings" })
            if (stored?[key] is { } value) report[key] = value.DeepClone();
        report["errors"] = Array.Empty<string>();
        report["unique_users"] = snapshot.Users.Users.Count;
        report["assignments"] = snapshot.Users.Assignments.Count;
        report["relevant_assignments"] = snapshot.Users.RelevantAssignments;
        report["directory_only_users"] = snapshot.Users.DirectoryOnlyUsers;
        report["invalid_catalogue_patterns"] = snapshot.Users.InvalidCataloguePatterns;
        return report;
    }

    internal static string Revision(Snapshot snapshot) => $"{V1Compatibility.Boot}.{(snapshot.Ids.Roles ?? 0) + (snapshot.Ids.Users ?? 0) + (snapshot.Ids.Sod ?? 0)}.{(snapshot.Ids.Employees ?? 0)}";
    internal static bool Flag(IQueryCollection q, string name) => q[name].FirstOrDefault() is "true" or "True" or "1";

    private static bool NonNegative(IQueryCollection q, string name, out int value)
    {
        value = 0;
        return q[name].FirstOrDefault() is not { } text || (int.TryParse(text, out value) && value >= 0);
    }

    internal static bool Paging(IQueryCollection q, int defaultLimit, out int offset, out int limit)
    {
        limit = defaultLimit;
        if (!NonNegative(q, "offset", out offset)) return false;
        if (q["limit"].FirstOrDefault() is { } text && (!int.TryParse(text, out limit) || limit is < 1 or > 100)) return false;
        return true;
    }
}
