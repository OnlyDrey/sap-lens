using System.Globalization;
using System.Text;
using SapLens.Application;
using SapLens.Domain.Analysis;
using SapLens.Domain.Roles;
using SapLens.Domain.Users;

namespace SapLens.Api;

/// <summary>Port of the Release Roles part of routers/access.py (release-options, release-roles, releases, release-assignments and their CSV exports)
/// and of assignment_filters.py (inclusive assignment-date filters). Only assignments in the "release" scope take part.</summary>
public static class V1ReleaseRoles
{
    private static readonly string[] Statuses = ["active", "expired", "future", "unknown", "all"];
    private static readonly string[] Sorts = ["role_name", "document_type", "release_group", "release_strategy", "assigned_users"];
    private static readonly string[] RoleListColumns = ["ROLE_NAME", "ROLE_DESCRIPTION", "RELEASE_AREA", "RELEASE_GROUP", "RELEASE_STRATEGY", "PR_PO"];
    private static readonly string[] AssignmentColumns = ["USERNAME", "FIRST_NAME", "LAST_NAME", "EMAIL", "USER_GROUP", "ROLE_NAME", "ROLE_VALID_FROM", "ROLE_VALID_TO",
        "ASSIGNMENT_STATUS", "PR_PO", "RELEASE_GROUP", "RELEASE_STRATEGY", "MATCHED_FILTER"];

    private static IResult Detail(int status, string detail) => Results.Json(new { detail }, statusCode: status);

    /// <summary>assignment_filters.assignment_dates: inclusive bounds on the role validity dates; valid_to 9999-12-31 is "open ended".</summary>
    public sealed record DateFilter(DateOnly? FromMin, DateOnly? FromMax, DateOnly? ToMin, DateOnly? ToMax, string OpenEnded, bool IncludeMissingEnd)
    {
        public bool Within(Assignment a)
        {
            var from = SapDates.Parse(a.ValidFrom);
            if ((FromMin is not null || FromMax is not null) && (from is null || from < FromMin || from > FromMax)) return false;
            var to = SapDates.Parse(a.ValidTo);
            if (to is null) { if (!IncludeMissingEnd) return false; }
            else if ((ToMin is not null || ToMax is not null) && (to < ToMin || to > ToMax)) return false;
            if (OpenEnded == "only" && a.ValidTo != "9999-12-31") return false;
            if (OpenEnded == "exclude" && a.ValidTo == "9999-12-31") return false;
            return true;
        }
    }

    public static (DateFilter? Filter, IResult? Error) Dates(IQueryCollection q)
    {
        DateOnly? Date(string name, ref bool bad)
        {
            var text = q[name].FirstOrDefault();
            if (string.IsNullOrEmpty(text)) return null;
            if (DateOnly.TryParseExact(text, "yyyy-MM-dd", CultureInfo.InvariantCulture, DateTimeStyles.None, out var value)) return value;
            bad = true;
            return null;
        }
        var invalid = false;
        var filter = new DateFilter(Date("valid_from_min", ref invalid), Date("valid_from_max", ref invalid), Date("valid_to_min", ref invalid), Date("valid_to_max", ref invalid),
            q["open_ended"].FirstOrDefault() ?? "", q["include_missing_end"].FirstOrDefault() is not ("false" or "False" or "0"));
        if (invalid || filter.OpenEnded is not ("" or "only" or "exclude")) return (null, Detail(422, "Assignment dates must be YYYY-MM-DD and open_ended '', 'only' or 'exclude'."));
        if (filter.FromMin > filter.FromMax || filter.ToMin > filter.ToMax) return (null, Detail(422, "Earliest assignment dates must not follow their latest dates."));
        return (filter, null);
    }

    /// <summary>user_access.release_area: the first character of a well-formed release group (E2 -> E).</summary>
    public static string? ReleaseArea(string? releaseGroup)
    {
        var value = (releaseGroup ?? "").Trim().PyUpper();
        return value.Length > 0 && value.All(c => c is >= 'A' and <= 'Z' or >= '0' and <= '9') ? value[..1] : null;
    }

    private static HashSet<string> Exact(IEnumerable<string?> values, string single = "") =>
        values.Append(single).Where(v => !string.IsNullOrEmpty(v) && v.Trim().Length > 0 && v.Length <= 512).Select(v => v!.Trim()).ToHashSet(StringComparer.Ordinal);

    private static HashSet<string> Bounded(IEnumerable<string?> values) =>
        values.Where(v => v is not null && v.Trim().Length > 0 && v.Length <= 100).Select(v => v!.Trim().PyUpper()).ToHashSet(StringComparer.Ordinal);

    private static bool TextMatchesAny(string? value, string query)
    {
        var terms = TextMatching.SearchTerms(query);
        return terms.Count == 0 || terms.Any(t => TextMatching.TextMatches(value, t));
    }

    private static bool Relevant(Assignment a, string status, DateOnly today) =>
        status == "all" || SapDates.IntervalStatus(a.ValidFrom, a.ValidTo, today) == status;

    private static int Ordinal(string? a, string? b) => string.CompareOrdinal(a, b);

    private sealed record Filters(DateFilter Dates, HashSet<string> UserGroups, string DocumentType, string ReleaseGroup, HashSet<string> Areas, HashSet<string> Groups,
        string Strategy, HashSet<string> Strategies, string Username, string Role, string Status, string Sort, bool Descending);

    private static bool TooLong(IQueryCollection q, string name, int max) => (q[name].FirstOrDefault()?.Length ?? 0) > max;

    /// <summary>release_filters, validated as the v1 query model.</summary>
    private static (Filters? Value, IResult? Error) Parse(IQueryCollection q)
    {
        var (dates, error) = Dates(q);
        if (error is not null) return (null, error);
        var documentType = q["document_type"].FirstOrDefault() ?? "";
        var status = q["status"].FirstOrDefault() ?? "active";
        var sort = q["sort"].FirstOrDefault() ?? "role_name";
        if (documentType is not ("" or "PR" or "PO" or "Unparsed") || !Statuses.Contains(status) || !Sorts.Contains(sort)) return (null, Detail(422, "Unsupported filter value."));
        if (q["user_groups"].Count > 100 || q["release_areas"].Count > 50 || q["release_groups"].Count > 200 || q["strategies"].Count > 100
            || TooLong(q, "group", 512) || TooLong(q, "release_group", 100) || TooLong(q, "strategy", 100) || TooLong(q, "username", 512) || TooLong(q, "role", 512))
            return (null, Detail(422, "Too many or too long filter values."));
        return (new Filters(dates!, Exact(q["user_groups"], q["group"].FirstOrDefault() ?? ""), documentType, q["release_group"].FirstOrDefault() ?? "",
            Bounded(q["release_areas"]), Bounded(q["release_groups"]), q["strategy"].FirstOrDefault() ?? "", [.. q["strategies"].OfType<string>()],
            q["username"].FirstOrDefault() ?? "", q["role"].FirstOrDefault() ?? "", status, sort, V1Access.Flag(q, "descending")), null);
    }

    /// <summary>filtered_release_assignments, in dataset order.</summary>
    private static IEnumerable<Assignment> Filtered(UserDirectory users, Filters f, DateOnly today)
    {
        var strategies = Bounded(f.Strategies);
        foreach (var a in users.Assignments)
        {
            if (a.Scope != "release" || !f.Dates.Within(a)) continue;
            var r = a.Release ?? new ReleaseRole(false, null, null, null);
            if (f.UserGroups.Count > 0 && !f.UserGroups.Contains(a.UserGroup)) continue;
            if (f.DocumentType.Length > 0 && (r.DocumentType ?? "Unparsed") != f.DocumentType) continue;
            if (f.ReleaseGroup.Length > 0 && r.ReleaseGroup != f.ReleaseGroup) continue;
            if (f.Areas.Count > 0 && (ReleaseArea(r.ReleaseGroup) is not { } area || !f.Areas.Contains(area))) continue;
            if (f.Groups.Count > 0 && (r.ReleaseGroup is null || !f.Groups.Contains(r.ReleaseGroup))) continue;
            if (f.Strategy.Length > 0 && r.ReleaseStrategy != f.Strategy) continue;
            if (f.Strategies.Count > 0 && (r.ReleaseStrategy is null || !strategies.Contains(r.ReleaseStrategy))) continue;
            if (f.Username.Length > 0 && !TextMatchesAny(a.Username, f.Username)) continue;
            if (f.Role.Length > 0 && !TextMatchesAny(a.RoleName, f.Role)) continue;
            if (!Relevant(a, f.Status, today)) continue;
            yield return a;
        }
    }

    private static Dictionary<string, object?> Release(ReleaseRole? r) => r is { Parsed: true }
        ? new() { ["parsed"] = true, ["document_type"] = r.DocumentType, ["release_group"] = r.ReleaseGroup, ["release_strategy"] = r.ReleaseStrategy, ["opaque_scope"] = r.OpaqueScope, ["opaque_suffix"] = r.OpaqueSuffix }
        : new() { ["parsed"] = false, ["document_type"] = null, ["release_group"] = null, ["release_strategy"] = null };

    /// <summary>distinct_release_roles: one entry per technical role, sorted by normalized name.</summary>
    private static List<Dictionary<string, object?>> DistinctRoles(Snapshot snapshot, Filters f, DateOnly today)
    {
        var roles = new Dictionary<string, Dictionary<string, object?>>(StringComparer.Ordinal);
        foreach (var a in Filtered(snapshot.Users, f, today))
        {
            var key = RoleNames.Normalize(a.RoleName);
            if (roles.ContainsKey(key)) continue;
            var r = a.Release ?? new ReleaseRole(false, null, null, null);
            roles[key] = new()
            {
                ["role_name"] = a.RoleName, ["description"] = snapshot.Catalogue.Roles.TryGetValue(a.RoleName, out var role) ? role.Text ?? "" : "",
                ["document_type"] = r.DocumentType, ["release_group"] = r.ReleaseGroup, ["release_strategy"] = r.ReleaseStrategy, ["release_area"] = ReleaseArea(r.ReleaseGroup),
                ["parsed"] = r.Parsed,
            };
        }
        return roles.Values.OrderBy(r => RoleNames.Normalize((string)r["role_name"]!), StringComparer.Ordinal).ThenBy(r => (string)r["role_name"]!, StringComparer.Ordinal).ToList();
    }

    private static async Task<Dictionary<string, object?>> Source(HttpContext http, Snapshot snapshot, DateOnly today, CancellationToken ct) => new()
    {
        ["loaded"] = snapshot.Ids.Users is not null, ["catalogue_loaded"] = snapshot.Catalogue.Roles.Count > 0, ["report"] = await V1Access.UsersReport(http, snapshot, ct),
        ["as_of"] = today.ToString("yyyy-MM-dd", CultureInfo.InvariantCulture), ["data_revision"] = V1Access.Revision(snapshot),
    };

    private static List<string> Groups(Snapshot snapshot) =>
        snapshot.Users.Users.Values.SelectMany(u => u.Groups).Where(g => g.Length > 0).Distinct(StringComparer.Ordinal).Order(StringComparer.Ordinal).ToList();

    private static void CsvHeaders(HttpContext http, Snapshot snapshot, string fileKind, DateOnly day, string countHeader, int count)
    {
        var iso = day.ToString("yyyy-MM-dd", CultureInfo.InvariantCulture);
        http.Response.Headers["Content-Disposition"] = $"attachment; filename=\"sap-lens-{fileKind}-review-{iso}.csv\"";
        http.Response.Headers["X-SAP-Lens-Data-Revision"] = V1Access.Revision(snapshot);
        http.Response.Headers["X-SAP-Lens-As-Of"] = iso;
        http.Response.Headers[countHeader] = count.ToString(CultureInfo.InvariantCulture);
        http.Response.Headers.CacheControl = "no-store";
    }

    public static void Map(RouteGroupBuilder api)
    {
        api.MapGet("/access/release-options", async (HttpContext http, SnapshotService snapshots, CancellationToken ct) =>
        {
            var q = http.Request.Query;
            var field = q["field"].FirstOrDefault() ?? "";
            var rank = field switch { "group" => 0, "document_type" => 1, "release_area" => 2, "release_group" => 3, "strategy" => 4, "username" or "role" => 5, _ => -1 };
            var (dates, error) = Dates(q);
            if (error is not null) return error;
            var status = q["status"].FirstOrDefault() ?? "active";
            if (rank < 0 || !Statuses.Contains(status)) return Detail(422, "Unsupported option field or status.");
            if (!V1Access.Paging(q, 50, out _, out var limit)) return Detail(422, "limit must be between 1 and 100.");
            if (q["user_groups"].Count > 100 || q["release_areas"].Count > 50 || q["release_groups"].Count > 200 || q["strategies"].Count > 100
                || TooLong(q, "search", 512) || TooLong(q, "selected", 512) || TooLong(q, "group", 100) || TooLong(q, "document_type", 20) || TooLong(q, "release_group", 100) || TooLong(q, "strategy", 100))
                return Detail(422, "Too many or too long filter values.");
            var search = q["search"].FirstOrDefault() ?? "";
            var selected = q["selected"].FirstOrDefault() ?? "";
            var documentType = q["document_type"].FirstOrDefault() ?? "";
            var releaseGroup = q["release_group"].FirstOrDefault() ?? "";
            var strategy = q["strategy"].FirstOrDefault() ?? "";
            var strategies = q["strategies"].OfType<string>().ToHashSet(StringComparer.Ordinal);
            var areas = Bounded(q["release_areas"]);
            var groups = Bounded(q["release_groups"]);
            var userGroups = Exact(q["user_groups"], q["group"].FirstOrDefault() ?? "");
            var snapshot = await snapshots.GetAsync(ct);
            var today = V1Access.Today();
            var values = new HashSet<string>(StringComparer.Ordinal);
            foreach (var a in snapshot.Users.Assignments)
            {
                if (a.Scope != "release" || !dates!.Within(a) || !Relevant(a, status, today)) continue;
                var r = a.Release ?? new ReleaseRole(false, null, null, null);
                var kind = r.DocumentType ?? "Unparsed";
                if (rank > 0 && userGroups.Count > 0 && !userGroups.Contains(a.UserGroup)) continue;
                if (rank > 1 && documentType.Length > 0 && kind != documentType) continue;
                if (rank > 2 && areas.Count > 0 && (ReleaseArea(r.ReleaseGroup) is not { } area || !areas.Contains(area))) continue;
                if (rank > 3 && groups.Count > 0 && (r.ReleaseGroup is null || !groups.Contains(r.ReleaseGroup))) continue;
                if (rank > 3 && releaseGroup.Length > 0 && r.ReleaseGroup != releaseGroup) continue;
                if (rank > 4 && strategy.Length > 0 && r.ReleaseStrategy != strategy) continue;
                if (rank > 4 && strategies.Count > 0 && (r.ReleaseStrategy is null || !strategies.Contains(r.ReleaseStrategy))) continue;
                var value = field switch
                {
                    "group" => a.UserGroup, "document_type" => kind, "release_area" => ReleaseArea(r.ReleaseGroup), "release_group" => r.ReleaseGroup,
                    "strategy" => r.ReleaseStrategy, "username" => a.Username, _ => a.RoleName,
                };
                if (!string.IsNullOrEmpty(value)) values.Add(value);
            }
            var matches = values.Where(v => TextMatchesAny(v, search)).OrderBy(V1SavedFilters.Fold, StringComparer.Ordinal).ThenBy(v => v, StringComparer.Ordinal).ToList();
            var available = selected.Length == 0 || (field is "username" or "role" ? values.Any(v => TextMatchesAny(v, selected)) : values.Contains(selected));
            return Results.Ok(new { items = matches.Take(limit).ToList(), total = matches.Count, has_more = matches.Count > limit, selected_available = available });
        });

        api.MapGet("/access/release-roles", async (HttpContext http, SnapshotService snapshots, CancellationToken ct) =>
        {
            var (filters, error) = Parse(http.Request.Query);
            if (error is not null) return error;
            var snapshot = await snapshots.GetAsync(ct);
            if (snapshot.Ids.Users is null) return Detail(409, "No validated User Access dataset is loaded.");
            var roles = DistinctRoles(snapshot, filters!, V1Access.Today());
            return Results.Ok(new { items = roles, total = roles.Count });
        });

        api.MapGet("/access/exports/release-roles", async (HttpContext http, SnapshotService snapshots, CancellationToken ct) =>
        {
            var (filters, error) = Parse(http.Request.Query);
            if (error is not null) return error;
            var snapshot = await snapshots.GetAsync(ct);
            if (snapshot.Ids.Users is null) return Detail(409, "No validated User Access dataset is loaded.");
            var today = V1Access.Today();
            var roles = DistinctRoles(snapshot, filters!, today);
            var csv = new StringBuilder("﻿");
            V1Csv.Line(csv, RoleListColumns, cells: false);
            foreach (var role in roles)
                V1Csv.Line(csv, [(string?)role["role_name"], (string?)role["description"], (string?)role["release_area"], (string?)role["release_group"], (string?)role["release_strategy"], (string?)role["document_type"]], cells: true);
            CsvHeaders(http, snapshot, "release-role-list", today, "X-SAP-Lens-Role-Count", roles.Count);
            return Results.Text(csv.ToString(), "text/csv; charset=utf-8");
        });

        api.MapGet("/access/exports/releases", async (HttpContext http, SnapshotService snapshots, CancellationToken ct) =>
        {
            var (filters, error) = Parse(http.Request.Query);
            if (error is not null) return error;
            var snapshot = await snapshots.GetAsync(ct);
            if (snapshot.Ids.Users is null) return Detail(409, "No validated User Access dataset is loaded.");
            var today = V1Access.Today();
            var entries = Filtered(snapshot.Users, filters!, today).ToList();
            entries.Sort((x, y) =>
            {
                var c = Ordinal(RoleNames.Normalize(x.RoleName), RoleNames.Normalize(y.RoleName));
                if (c == 0) c = Ordinal(x.UserKey, y.UserKey);
                if (c == 0) c = Ordinal(x.ValidFrom ?? "", y.ValidFrom ?? "");
                if (c == 0) c = Ordinal(x.ValidTo ?? "", y.ValidTo ?? "");
                return c != 0 ? c : x.Id.CompareTo(y.Id);
            });
            if (filters!.Descending) entries.Reverse();
            var identities = entries.Select(a => a.UserKey).Distinct().ToDictionary(k => k, k => UserLookup.Summary(snapshot.Users.Users[k], [], today));
            var csv = new StringBuilder("﻿");
            V1Csv.Line(csv, AssignmentColumns, cells: false);
            static string Local(string? value) => SapDates.Parse(value) is { } d ? $"{d.Day:00}.{d.Month:00}.{d.Year:0000}" : "";
            foreach (var a in entries)
            {
                var identity = identities[a.UserKey];
                var status = SapDates.IntervalStatus(a.ValidFrom, a.ValidTo, today);
                V1Csv.Line(csv, [a.Username, identity.FirstName, identity.LastName, identity.Email, a.UserGroup, a.RoleName, Local(a.ValidFrom), Local(a.ValidTo),
                    char.ToUpperInvariant(status[0]) + status[1..], a.Release?.DocumentType, a.Release?.ReleaseGroup, a.Release?.ReleaseStrategy, "Yes"], cells: true);
            }
            CsvHeaders(http, snapshot, "release-roles", today, "X-SAP-Lens-Assignment-Count", entries.Count);
            return Results.Text(csv.ToString(), "text/csv; charset=utf-8");
        });

        api.MapGet("/access/releases", async (HttpContext http, SnapshotService snapshots, CancellationToken ct) =>
        {
            var q = http.Request.Query;
            var (filters, error) = Parse(q);
            if (error is not null) return error;
            if (!V1Access.Paging(q, 50, out var offset, out var limit) || !int.TryParse(q["matrix_offset"].FirstOrDefault() ?? "0", out var matrixOffset) || matrixOffset < 0
                || TooLong(q, "anchor", 512))
                return Detail(422, "Offsets must be ≥ 0 and limit between 1 and 100.");
            var byUserGroup = V1Access.Flag(q, "group_by_user_group");
            var snapshot = await snapshots.GetAsync(ct);
            var today = V1Access.Today();
            var buckets = new Dictionary<string, List<Assignment>>(StringComparer.Ordinal);
            var cells = new Dictionary<(string G, string D, string R, string S), HashSet<string>>();
            var cellRoles = new Dictionary<(string, string, string, string), Dictionary<string, string>>();
            foreach (var a in Filtered(snapshot.Users, filters!, today))
            {
                var key = RoleNames.Normalize(a.RoleName);
                if (!buckets.TryGetValue(key, out var bucket)) buckets[key] = bucket = [];
                bucket.Add(a);
                if (a.Release is { Parsed: true } r)
                {
                    var cell = (byUserGroup ? a.UserGroup : "", r.DocumentType!, r.ReleaseGroup!, r.ReleaseStrategy!);
                    if (!cells.TryGetValue(cell, out var people)) { cells[cell] = people = []; cellRoles[cell] = new(StringComparer.Ordinal); }
                    people.Add(a.UserKey);
                    cellRoles[cell][key] = a.RoleName;
                }
            }
            var rows = buckets.Values.Select(assignments =>
            {
                var sample = assignments[0];
                var row = new Dictionary<string, object?> { ["role_name"] = sample.RoleName };
                foreach (var (k, v) in Release(sample.Release)) row[k] = v;
                row["release_area"] = ReleaseArea(sample.Release?.ReleaseGroup);
                row["assigned_users"] = assignments.Select(a => a.UserKey).Distinct().Count();
                row["assignment_count"] = assignments.Count;
                row["statuses"] = assignments.Select(a => SapDates.IntervalStatus(a.ValidFrom, a.ValidTo, today)).Distinct().Order(StringComparer.Ordinal).ToList();
                row["valid_from"] = assignments.Select(a => a.ValidFrom).Where(v => !string.IsNullOrEmpty(v)).Order(StringComparer.Ordinal).FirstOrDefault();
                row["valid_to"] = assignments.Select(a => a.ValidTo).Where(v => !string.IsNullOrEmpty(v)).Order(StringComparer.Ordinal).LastOrDefault();
                row["missing_dates"] = assignments.Any(a => string.IsNullOrEmpty(a.ValidFrom) || string.IsNullOrEmpty(a.ValidTo));
                return row;
            }).ToList();
            var sort = filters!.Sort;
            rows.Sort((x, y) =>
            {
                int c;
                if (sort == "assigned_users") c = ((int)x["assigned_users"]!).CompareTo((int)y["assigned_users"]!);
                else c = Ordinal(x[sort] as string ?? "", y[sort] as string ?? "");
                return c != 0 ? c : Ordinal((string)x["role_name"]!, (string)y["role_name"]!);
            });
            if (filters.Descending) rows.Reverse();
            var anchor = q["anchor"].FirstOrDefault() ?? "";
            if (anchor.Length > 0)
            {
                var wanted = RoleNames.Normalize(anchor);
                var index = rows.FindIndex(r => RoleNames.Normalize((string)r["role_name"]!) == wanted);
                return Results.Ok(new
                {
                    items = rows.Skip(offset).Take(limit).ToList(), total = rows.Count, offset, limit,
                    navigation = new
                    {
                        index = index < 0 ? (int?)null : index, total = rows.Count,
                        previous = index > 0 ? rows[index - 1]["role_name"] : null, next = index >= 0 && index + 1 < rows.Count ? rows[index + 1]["role_name"] : null,
                    },
                });
            }
            var matrix = cells.OrderBy(c => c.Key.G, StringComparer.Ordinal).ThenBy(c => c.Key.D, StringComparer.Ordinal).ThenBy(c => c.Key.R, StringComparer.Ordinal)
                .ThenBy(c => c.Key.S, StringComparer.Ordinal)
                .Select(c => new Dictionary<string, object?>
                {
                    ["user_group"] = c.Key.G, ["document_type"] = c.Key.D, ["release_group"] = c.Key.R, ["release_strategy"] = c.Key.S, ["user_count"] = c.Value.Count,
                    ["roles"] = cellRoles[c.Key].OrderBy(p => p.Key, StringComparer.Ordinal).ThenBy(p => p.Value, StringComparer.Ordinal).Select(p => p.Value).ToList(),
                }).ToList();
            var listComplete = V1Access.Flag(q, "list_complete");
            var (pageOffset, pageLimit) = listComplete ? (0, Math.Max(1, rows.Count)) : (offset, limit);
            var result = new Dictionary<string, object?>
            {
                ["items"] = rows.Skip(pageOffset).Take(pageLimit).ToList(), ["total"] = rows.Count, ["offset"] = pageOffset, ["limit"] = pageLimit,
                ["matrix"] = V1Access.Flag(q, "matrix_complete") ? matrix : matrix.Skip(matrixOffset).Take(200).ToList(), ["matrix_total"] = matrix.Count, ["matrix_offset"] = matrixOffset,
            };
            foreach (var (k, v) in await Source(http, snapshot, today, ct)) result[k] = v;
            result["export_assignments"] = buckets.Values.Sum(b => b.Count);
            result["groups"] = Groups(snapshot);
            result["groups_total"] = snapshot.Users.GroupCount;
            return Results.Ok(result);
        });

        api.MapGet("/access/release-assignments", async (HttpContext http, SnapshotService snapshots, CancellationToken ct) =>
        {
            var q = http.Request.Query;
            var (dates, error) = Dates(q);
            if (error is not null) return error;
            var documentType = q["document_type"].FirstOrDefault() ?? "";
            var status = q["status"].FirstOrDefault() ?? "active";
            if (documentType is not ("" or "PR" or "PO") || !Statuses.Contains(status)) return Detail(422, "Unsupported filter value.");
            if (!V1Access.Paging(q, 50, out var offset, out var limit)) return Detail(422, "offset must be ≥ 0 and limit between 1 and 100.");
            if (q["user_groups"].Count > 100 || q["strategies"].Count > 100 || TooLong(q, "role", 512) || TooLong(q, "group", 512) || TooLong(q, "username", 512)
                || TooLong(q, "role_search", 512) || TooLong(q, "release_group", 100) || TooLong(q, "strategy", 100))
                return Detail(422, "Too many or too long filter values.");
            var role = q["role"].FirstOrDefault() ?? "";
            var username = q["username"].FirstOrDefault() ?? "";
            var roleSearch = q["role_search"].FirstOrDefault() ?? "";
            var releaseGroup = q["release_group"].FirstOrDefault() ?? "";
            var strategy = q["strategy"].FirstOrDefault() ?? "";
            var strategies = Bounded(q["strategies"]);
            var anyStrategies = q["strategies"].Count > 0;
            var ungrouped = V1Access.Flag(q, "ungrouped");
            var userGroups = Exact(q["user_groups"], q["group"].FirstOrDefault() ?? "");
            var snapshot = await snapshots.GetAsync(ct);
            var today = V1Access.Today();
            var wantedRole = RoleNames.Normalize(role);
            var entries = snapshot.Users.Assignments.Where(a =>
            {
                if (a.Scope != "release" || !dates!.Within(a)) return false;
                var r = a.Release ?? new ReleaseRole(false, null, null, null);
                if (username.Length > 0 && !TextMatchesAny(a.Username, username)) return false;
                if (roleSearch.Length > 0 && !TextMatchesAny(a.RoleName, roleSearch)) return false;
                if (role.Length > 0 && RoleNames.Normalize(a.RoleName) != wantedRole) return false;
                if ((userGroups.Count > 0 && !userGroups.Contains(a.UserGroup)) || (ungrouped && a.UserGroup.Length > 0)) return false;
                if (documentType.Length > 0 && r.DocumentType != documentType) return false;
                if (releaseGroup.Length > 0 && r.ReleaseGroup != releaseGroup) return false;
                if (strategy.Length > 0 && r.ReleaseStrategy != strategy) return false;
                if (anyStrategies && (r.ReleaseStrategy is null || !strategies.Contains(r.ReleaseStrategy))) return false;
                return Relevant(a, status, today);
            }).ToList();
            entries.Sort((x, y) =>
            {
                var c = Ordinal(x.UserKey, y.UserKey);
                if (c == 0) c = Ordinal(x.RoleName, y.RoleName);
                if (c == 0) c = Ordinal(x.ValidFrom ?? "", y.ValidFrom ?? "");
                return c != 0 ? c : x.Id.CompareTo(y.Id);
            });
            string DisplayName(string key) => snapshot.Users.Users.TryGetValue(key, out var user) && user.Names.Count > 0
                ? string.Join(' ', new[] { user.Names[0].First, user.Names[0].Last }.Where(p => p.Length > 0)) : "";
            var items = entries.Skip(offset).Take(limit).Select(a => { var view = V1Access.AssignmentView(a, today); view["display_name"] = DisplayName(a.UserKey); return view; }).ToList();
            return Results.Ok(new Dictionary<string, object?>
            {
                ["items"] = items, ["total"] = entries.Count, ["offset"] = offset, ["limit"] = limit, ["distinct_users"] = entries.Select(a => a.UserKey).Distinct().Count(),
                ["role_info"] = role.Length > 0 ? Release(RoleNames.ParseRelease(role)) : null,
            });
        });
    }
}
