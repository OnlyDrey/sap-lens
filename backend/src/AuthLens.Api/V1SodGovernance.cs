using System.Globalization;
using System.Text;
using System.Text.Json.Nodes;
using AuthLens.Application;
using AuthLens.Domain.Sod;

namespace AuthLens.Api;

/// <summary>Port of routers/sod_governance.py read routes and routers/sod.py overview: review context, matrices and group heatmaps, filter options, Access
/// Explorer tables and exports, the bulk selection, the review queue (items, users, export), remediation (list, exports) and the SoD overview. Every route
/// works for the live context and for review periods (frozen periods read their own snapshot); nothing here changes evidence or decisions.</summary>
public static class V1SodGovernance
{
    public const int MaxColumns = 500, MatrixPageMax = 5000, SelectionLimit = 5000;
    private static readonly StringComparer Ordinal = StringComparer.Ordinal;
    public static readonly string[] StatusFilters = ["Pending", "Reviewed", "Conditional", "Removal required", "Investigate", "Rejected", "Risk acceptance pending", "Awaiting approval", "Outdated", "Resolved", "Historical"];
    public static readonly string[] QueueColumns = ["CONTEXT", "REVIEW_TYPE", "USERNAME", "USER_GROUPS", "REFERENCE", "RISKS", "LIFECYCLE", "DECISION", "REVIEWER", "APPROVER", "TIMESTAMP",
        "JUSTIFICATION", "CONTROLS", "EXPIRES", "EVIDENCE_VERSION", "ACCESS_REVIEWED", "REVIEW_PROVENANCE", "REMOVAL_PLANNED", "BULK_OPERATION_ID", "PREVIOUS_DECISION"];
    public static readonly string[] RemediationColumns = ["USERNAME", "USER_GROUP", "ACTIVITY", "RISKS", "ROLE", "ASSIGNMENT_ID", "VALID_FROM", "VALID_TO", "ACTIVITY_REVIEW", "ASSIGNMENT_REVIEW",
        "RISK_ACCEPTANCE", "RECOMMENDED_ACTION", "JUSTIFICATION", "OWNER", "DUE_DATE", "ACTION_STATUS", "VERIFICATION"];
    public static readonly string[] RoleAssignmentColumns = ["USERNAME", "ROLE", "SAP User Group", "Decision Status"];
    private static readonly Dictionary<string, string[]> ExplorerColumns = new(Ordinal)
    {
        ["user_risk"] = ["USERNAME", "RISK", "CRITICITY", "BUSINESS_AREA", "USER_GROUPS", "ACTIVITIES", "ROLES", "RISK_ACCEPTANCE"],
        ["user_activity"] = ["USERNAME", "USER_GROUPS", "ACTIVITY", "RISKS", "TRANSACTIONS", "ROLE_ASSIGNMENTS", "DUPLICATE_COVERAGE", "ACTIVITY_REVIEW"],
        ["access_list"] = ["USERNAME", "ROLE", "VALID_FROM", "VALID_TO", "ASSIGNMENT_STATUS", "USER_GROUP", "ACTIVITIES", "RISKS", "ASSIGNMENT_REVIEW", "ASSIGNMENT_ID", "ROLE_SUFFIX"],
        ["lookup"] = ["ROLE", "USERS", "CATALOGUE_ROLES", "ACTIVITIES", "RISKS"],
    };
    private static readonly string[] Tables = ["user_risk", "user_activity", "access_list", "lookup"];

    private static IResult Json(JsonNode node) => Results.Content(node.ToJsonString(), "application/json");
    private static IResult Bad(string message) => SodScope.Problem(422, message);
    private static string Join(JsonNode? list) => string.Join(", ", (list as JsonArray ?? []).Select(v => v?.ToString() ?? ""));
    private static string S(JsonNode? node) => node is JsonValue v ? v.ToString() : "";
    private static string Py(bool value) => value ? "True" : "False";

    /// <summary>Paging parameters with v1's bounds; null when invalid.</summary>
    private static (int Offset, int Limit)? Paging(IQueryCollection q, int fallback, int max)
    {
        var offset = int.TryParse(q["offset"].FirstOrDefault() ?? "0", out var o) ? o : -1;
        var limit = int.TryParse(q["limit"].FirstOrDefault() ?? fallback.ToString(CultureInfo.InvariantCulture), out var l) ? l : -1;
        return offset < 0 || limit < 1 || limit > max ? null : (offset, limit);
    }

    private static async Task<(SodQuery? Query, IResult? Error)> QueryAsync(HttpContext http, CancellationToken ct)
    {
        var (q, error) = SodScope.Parse(http.Request.Query);
        if (error is not null) return (null, error);
        return (await SodScope.OrganizationalAsync(http.RequestServices, q!, ct), null);
    }

    private static async Task<JsonObject> InfoAsync(HttpContext http, SodBundle b, CancellationToken ct) => await SodScope.InfoAsync(http.RequestServices, b, ct);

    private static IResult Csv(HttpContext http, IEnumerable<string> columns, IEnumerable<IEnumerable<string?>> rows, string name)
    {
        var csv = new StringBuilder("﻿");
        V1Csv.Line(csv, columns, cells: false);
        foreach (var row in rows) V1Csv.Line(csv, row, cells: true);
        http.Response.Headers["Content-Disposition"] = $"attachment; filename=\"authlens-sod-{name}-{DateTime.Now:yyyy-MM-dd}.csv\"";
        http.Response.Headers.CacheControl = "no-store";
        return Results.Text(csv.ToString(), "text/csv; charset=utf-8");
    }

    // ---- matrices

    private static async Task<(SodScope.Scoped Scope, JsonObject Matrix)> BuiltAsync(HttpContext http, string kind, SodQuery q, CancellationToken ct)
    {
        var scope = await SodScope.ScopedAsync(http.RequestServices, q, ct);
        return (scope, kind == "risk" ? SodViews.RiskMatrix(scope.View, scope.State) : SodViews.ActivityMatrix(scope.View, scope.State));
    }

    /// <summary>Users by their first SAP User Group, then name; users without a group always last.</summary>
    private static List<JsonObject> ByGroup(IEnumerable<JsonObject> rows, bool descending)
    {
        static string First(JsonObject r) => SodViews.Fold((string)r["groups"]![0]!);
        static string User(JsonObject r) => SodViews.Fold((string)r["user"]!);
        var list = rows.ToList();
        var with = list.Where(r => r["groups"]!.AsArray().Count > 0);
        var ordered = descending ? with.OrderByDescending(First, Ordinal).ThenByDescending(User, Ordinal) : with.OrderBy(First, Ordinal).ThenBy(User, Ordinal);
        var without = list.Where(r => r["groups"]!.AsArray().Count == 0);
        return [.. ordered, .. descending ? without.OrderByDescending(User, Ordinal) : without.OrderBy(User, Ordinal)];
    }

    private static async Task<IResult> MatrixAsync(HttpContext http, string kind, CancellationToken ct)
    {
        var (q, error) = await QueryAsync(http, ct);
        if (error is not null) return error;
        var groupBy = http.Request.Query["group_by"].FirstOrDefault() ?? "user";
        if (groupBy is not ("user" or "group" or "user_group")) return Bad("Choose user, group or user_group.");
        if (Paging(http.Request.Query, 50, MatrixPageMax) is not { } page) return Bad("Invalid paging.");
        var (scope, matrix) = await BuiltAsync(http, kind, q!, ct);
        var key = kind == "risk" ? "acceptance" : "decision";
        var statusCounts = new JsonObject();
        foreach (var row in matrix["rows"]!.AsArray())
            foreach (var (_, cell) in row!["cells"]!.AsObject()) { var s = (string)cell![key]!; statusCounts[s] = ((int?)statusCounts[s] ?? 0) + 1; }
        if (groupBy == "group") matrix = SodViews.AggregateByGroup(matrix);
        var rows = matrix["rows"]!.AsArray().Select(r => r!.AsObject()).ToList();
        if (q!.Sort == "findings")
        {
            rows = [.. rows.OrderBy(r => -r["cells"]!.AsObject().Count).ThenBy(r => (string)r["user"]!, Ordinal)];
            if (q.Descending) rows.Reverse();
        }
        else if (q.Sort == "group") rows = ByGroup(rows, q.Descending);
        else if (q.Descending) rows.Reverse();
        JsonNode? summaries = null;
        if (groupBy == "user_group")
        {
            var (ordered, groups) = SodViews.PlaceInGroups(rows, q.Many("group", "groups"), q.Descending);
            rows = [.. ordered.Select(r => r!.AsObject())];
            summaries = groups;
        }
        var columns = matrix["columns"]!.AsArray().Take(MaxColumns).ToList();
        var keep = columns.Select(c => (string)c![kind == "risk" ? "risk_id" : "activity"]!).ToHashSet(Ordinal);
        var pageRows = new JsonArray();
        foreach (var row in rows.Skip(page.Offset).Take(page.Limit))
        {
            var copy = row.DeepClone().AsObject();
            var cells = new JsonObject();
            foreach (var (name, cell) in row["cells"]!.AsObject()) if (keep.Contains(name)) cells[name] = cell!.DeepClone();
            copy["cells"] = cells;
            pageRows.Add(copy);
        }
        var result = await InfoAsync(http, scope.Bundle, ct);
        result["kind"] = kind; result["group_by"] = groupBy; result["columns"] = new JsonArray([.. columns.Select(c => c!.DeepClone())]);
        result["columns_truncated"] = matrix["columns"]!.AsArray().Count > MaxColumns; result["rows"] = pageRows; result["total_rows"] = rows.Count;
        result["offset"] = page.Offset; result["limit"] = page.Limit; result["status_counts"] = statusCounts; result["group_summaries"] = summaries;
        foreach (var (name, value) in matrix) if (name is not ("columns" or "rows")) result[name] = value?.DeepClone();
        return Json(result);
    }

    private static async Task<IResult> GroupExportAsync(HttpContext http, string kind, CancellationToken ct)
    {
        var (q, error) = await QueryAsync(http, ct);
        if (error is not null) return error;
        var (_, matrix) = await BuiltAsync(http, kind, q!, ct);
        var grouped = SodViews.AggregateByGroup(matrix);
        var rows = grouped["rows"]!.AsArray().SelectMany(r => r!["cells"]!.AsObject().Select(c => new[] { (string?)r["user"], c.Key, S(c.Value!["users"]), S(r["users"]) }));
        return Csv(http, ["SAP_USER_GROUP", kind == "risk" ? "RISK_ID" : "ACTIVITY", "USERS_WITH_ITEM", "USERS_IN_GROUP_WITH_ITEMS"], rows, $"group-{kind}-heatmap");
    }

    // ---- filter options

    private static readonly Dictionary<string, string> Plural = new(Ordinal)
    {
        ["username"] = "usernames", ["role_suffix"] = "role_suffixes", ["risk"] = "risks", ["activity"] = "activities", ["group"] = "groups", ["role"] = "roles", ["tcode"] = "tcodes",
        ["category"] = "categories", ["criticality"] = "criticalities",
    };

    public static List<string> OptionValues(IReadOnlyDictionary<string, SodUserEntry> model, string field)
    {
        var values = new HashSet<string>(Ordinal);
        foreach (var (user, entry) in model)
        {
            if (field == "username") values.Add(user);
            else if (field == "group") values.UnionWith(entry.Groups);
            else if (field is "risk" or "criticality" or "risk_type" or "category")
                foreach (var (riskId, finding) in entry.Findings)
                {
                    var definition = finding["risk"] as JsonObject;
                    values.Add(field switch
                    {
                        "risk" => riskId, "criticality" => (string?)finding["criticality"] ?? "", "risk_type" => (string?)definition?["risk_type"] ?? "", _ => (string?)definition?["business_category"] ?? "",
                    });
                }
            else if (field is "activity" or "tcode")
                foreach (var activity in entry.Activities.Values) { if (field == "activity") values.Add(activity.Name); else values.UnionWith(activity.Tcodes); }
            else
                foreach (var a in SodViews.Shown(entry))
                {
                    if (field == "role") values.Add(a.Role);
                    else if (field == "role_suffix") values.Add(SodViews.RoleSuffix(a.Role));
                    else values.UnionWith(field == "composite_role" ? a.CatalogueRoles : a.SingleRoles);
                }
        }
        return [.. values.Where(v => v.Length > 0).OrderBy(SodViews.Fold, Ordinal).ThenBy(v => v, Ordinal)];
    }

    private static async Task<IResult> FilterOptionsAsync(HttpContext http, CancellationToken ct)
    {
        var (q, error) = await QueryAsync(http, ct);
        if (error is not null) return error;
        var query = http.Request.Query;
        var field = query["field"].FirstOrDefault() ?? "risk";
        if (field is not ("risk" or "activity" or "criticality" or "risk_type" or "category" or "group" or "username" or "role" or "role_suffix" or "tcode" or "composite_role" or "single_role"))
            return Bad("Choose a supported filter field.");
        var term = query["term"].FirstOrDefault() ?? "";
        if (term.Length > 128) return Bad("term: String should have at most 128 characters");
        var limit = int.TryParse(query["limit"].FirstOrDefault() ?? "50", out var l) ? l : -1;
        if (limit is < 1 or > 200) return Bad("limit must be between 1 and 200.");
        var groupRoles = SodScope.Flag(query["group_roles"].FirstOrDefault());
        string[] own = field == "role" ? [field, Plural[field], "role_families", "role_exact"] : Plural.TryGetValue(field, out var plural) ? [field, plural] : [field];
        // v1 always takes the scoped path here (its role_match default is a non-empty value): options follow the other active filters.
        var scope = await SodScope.ScopedAsync(http.RequestServices, q!.Without(own) with { Sort = "subject", Descending = false }, ct);
        var values = OptionValues(scope.View, field);
        var families = field == "role" && groupRoles ? SodScope.FamilyMap(scope.Bundle) : new Dictionary<string, string>(Ordinal);
        if (families.Count > 0) values = [.. values.Select(v => families.GetValueOrDefault(v, v)).Distinct().OrderBy(SodViews.Fold, Ordinal).ThenBy(v => v, Ordinal)];
        var needle = SodViews.Fold(term.Trim());
        if (needle.Length > 0) values = [.. values.Where(v => SodViews.Fold(v).Contains(needle, StringComparison.Ordinal))];
        var result = await InfoAsync(http, scope.Bundle, ct);
        result["field"] = field;
        result["items"] = new JsonArray([.. values.Take(limit).Select(v => (JsonNode?)v)]);
        result["total"] = values.Count;
        result["family_values"] = new JsonArray([.. families.Values.Distinct().Order(Ordinal).Select(v => (JsonNode?)v)]);
        return Json(result);
    }

    // ---- explorer

    private static async Task<(SodScope.Scoped Scope, List<JsonObject> Rows)> ExplorerAsync(HttpContext http, string table, SodQuery q, CancellationToken ct)
    {
        var scope = await SodScope.ScopedAsync(http.RequestServices, q, ct);
        var array = SodViews.ExplorerRows(table, scope.View, scope.State);
        var rows = array.Select(r => r!.AsObject()).ToList();
        array.Clear();   // detach the rows so responses can own them
        if (table == "access_list" && scope.Query.AssignmentScope != "all")
            rows = [.. rows.Where(r => r["risks"]!.AsArray().Any(risk => scope.View[(string)r["user"]!].Findings.ContainsKey((string)risk!)))];
        if (q.Descending) rows.Reverse();
        return (scope, rows);
    }

    private static async Task<JsonObject> ProgressAsync(HttpContext http, SodQuery q, CancellationToken ct)
    {
        var (_, rows) = await ExplorerAsync(http, "access_list", q with { ReviewStatus = "" }, ct);
        int Count(params string[] names) => rows.Count(r => names.Contains((string)r["decision"]!));
        return new JsonObject
        {
            ["total"] = rows.Count, ["completed"] = Count("Keep", "Removal required"), ["pending"] = Count("Pending"), ["investigating"] = Count("Investigate"),
            ["outdated"] = Count("Outdated"), ["attention"] = Count("Pending", "Investigate", "Outdated"), ["removal"] = Count("Removal required"),
        };
    }

    private static IEnumerable<string?> ExplorerCsv(string table, JsonObject r) => table switch
    {
        "user_risk" => [S(r["user"]), S(r["risk_id"]), S(r["criticality"]), S(r["category"]), Join(r["groups"]), Join(r["activities"]), Join(r["roles"]), S(r["acceptance"])],
        "user_activity" => [S(r["user"]), Join(r["groups"]), S(r["activity"]), Join(r["risks"]), Join(r["tcodes"]), S(r["roles"]), (bool)r["duplicate"]! ? "Yes" : "No", S(r["decision"])],
        "access_list" => [S(r["user"]), S(r["role"]), S(r["valid_from"]), S(r["valid_to"]), S(r["interval_status"]), S(r["user_group"]), Join(r["activities"]), Join(r["risks"]), S(r["decision"]), S(r["id"]), S(r["suffix"])],
        _ => [S(r["role"]), S(r["users"]), Join(r["catalogue_roles"]), Join(r["activities"]), Join(r["risks"])],
    };

    private static async Task<IResult> SelectionAsync(HttpContext http, CancellationToken ct)
    {
        var (q, error) = await QueryAsync(http, ct);
        if (error is not null) return error;
        var store = http.RequestServices.GetRequiredService<SodDecisionStore>();
        var before = await store.RevisionAsync(ct);
        var (scope, rows) = await ExplorerAsync(http, "access_list", q!, ct);
        if (await store.RevisionAsync(ct) != before) throw new SodDecisionException(409, "Review decisions changed during preview. Reload before selecting assignments.");
        var reviewable = scope.Bundle.Reviewable;
        var eligible = new JsonObject();
        foreach (var (action, life) in new[] { ("Keep", "Keep"), ("Remove", "Removal required"), ("Investigate", "Investigate") })
            eligible[action] = new JsonObject
            {
                ["unreviewed"] = reviewable ? rows.Count(r => !(bool)r["has_review"]! && (string)r["decision"]! != life) : 0,
                ["include_reviewed"] = reviewable ? rows.Count(r => (string)r["decision"]! != life) : 0,
            };
        var result = await InfoAsync(http, scope.Bundle, ct);
        result["eligible_counts"] = eligible;
        result["revision"] = before;
        result["items"] = new JsonArray([.. rows.Take(SelectionLimit).Select(r => (JsonNode?)new JsonObject
        {
            ["key"] = r["id"]!.DeepClone(), ["user"] = r["user"]!.DeepClone(), ["ref"] = r["role"]!.DeepClone(), ["suffix"] = r["suffix"]!.DeepClone(), ["evidence_version"] = r["evidence_version"]!.DeepClone(),
            ["decision"] = r["decision"]!.DeepClone(), ["user_group"] = r["user_group"]!.DeepClone(), ["has_review"] = r["has_review"]!.DeepClone(), ["previous_decision"] = r["previous_decision"]!.DeepClone(),
        })]);
        result["matching_users"] = rows.Select(r => (string)r["user"]!).Distinct().Count();
        result["matching_roles"] = rows.Select(r => (string)r["role"]!).Distinct().Count();
        result["total"] = rows.Count; result["truncated"] = rows.Count > SelectionLimit; result["limit"] = SelectionLimit;
        return Json(result);
    }

    // ---- queue

    private static bool StatusMatch(JsonObject item, string status, bool awaiting)
    {
        var life = (string)item["lifecycle"]!;
        var reviewed = (bool?)item["review_coverage"]?["reviewed"] ?? false;
        return status switch
        {
            "Pending" => life == "Pending" && !reviewed, "Reviewed" => reviewed || life is "Approved" or "Keep" or "Accepted", "Conditional" => life == "Conditional",
            "Removal required" => life == "Removal required", "Investigate" => life == "Investigate", "Rejected" => life == "Rejected",
            "Risk acceptance pending" => (string)item["kind"]! == "acceptance" && life == "Pending", "Awaiting approval" => awaiting && SodScope.Decided.Contains(life),
            "Outdated" => life == "Outdated", "Resolved" => life == "Resolved", _ => life == "Historical",
        };
    }

    private static readonly string[] QueueFilterNames = ["search", "risk", "risks", "username", "usernames", "role", "roles", "role_families", "role_exact", "role_suffix", "role_suffixes",
        "tcode", "tcodes", "activity", "activities", "group", "groups", "criticality", "criticalities", "category", "categories"];

    private static async Task<(SodScope.Scoped Scope, List<JsonObject> Items, JsonObject Counts)> QueueAsync(HttpContext http, SodQuery q, string kind, string status, CancellationToken ct)
    {
        var services = http.RequestServices;
        var scope = await SodScope.ScopedAsync(services, q with { ReviewPopulation = true }, ct);
        var b = scope.Bundle;
        var items = SodViews.QueueItems(scope.View, scope.State);
        var filtered = QueueFilterNames.Any(n => q.S(n).Length > 0 || q.L(n).Count > 0) || q.AssignmentDecision.Length > 0 || q.ReviewStatus.Length > 0;
        if (b.Context == "current" && b.Reviewable && !filtered)
        {
            var model = scope.Model;
            var known = new Dictionary<string, HashSet<string>>(Ordinal)
            {
                ["activity"] = model.Values.SelectMany(e => e.Activities.Values).Select(a => a.Key).ToHashSet(Ordinal),
                ["assignment"] = model.Values.SelectMany(e => e.Assignments.Keys).ToHashSet(Ordinal),
                ["acceptance"] = model.Values.SelectMany(e => e.Findings.Values).Select(f => (string)f["finding_id"]!).ToHashSet(Ordinal),
            };
            known["risk"] = known["acceptance"];
            foreach (var (kindName, events) in await SodScope.LatestAsync(services, b, ct))
                foreach (var (key, e) in events)
                    if (!known[kindName].Contains(key))
                        items.Add(new JsonObject
                        {
                            ["kind"] = kindName, ["key"] = key, ["user"] = e.User, ["ref"] = e.Ref, ["risks"] = kindName == "acceptance" ? new JsonArray(e.Ref) : new JsonArray(),
                            ["lifecycle"] = await SodScope.OrphanLifecycleAsync(services, kindName, e, ct), ["roles"] = 0, ["event"] = e.ToJson(), ["evidence_version"] = e.EvidenceVersion,
                        });
        }
        var awaiting = (string?)b.Period?["state"] == "Ready for approval";
        if (kind.Length > 0) items = [.. items.Where(i => (string)i["kind"]! == kind)];
        var counts = new JsonObject();
        foreach (var name in StatusFilters) counts[name] = items.Count(i => StatusMatch(i, name, awaiting));
        if (status.Length > 0) items = [.. items.Where(i => StatusMatch(i, status, awaiting))];
        var order = new Dictionary<string, int>(Ordinal) { ["activity"] = 0, ["assignment"] = 1, ["acceptance"] = 2, ["risk"] = 3 };
        items = [.. items.OrderBy(i => SodViews.Fold((string)i["user"]!), Ordinal).ThenBy(i => order[(string)i["kind"]!]).ThenBy(i => SodViews.Fold((string)i["ref"]!), Ordinal)];
        return (scope, items, counts);
    }

    private static (string Kind, string Status, IResult? Error) QueueFilters(IQueryCollection query)
    {
        var kind = query["kind"].FirstOrDefault() ?? "";
        var status = query["status"].FirstOrDefault() ?? "";
        if (kind is not ("" or "activity" or "assignment" or "acceptance") || status.Length > 0 && !StatusFilters.Contains(status)) return (kind, status, Bad("Choose a supported review type and status."));
        return (kind, status, null);
    }

    private static async Task<IResult> QueueUsersAsync(HttpContext http, CancellationToken ct)
    {
        var (q, error) = await QueryAsync(http, ct);
        if (error is not null) return error;
        var query = http.Request.Query;
        var progress = query["progress"].FirstOrDefault() ?? "";
        var sort = query["queue_sort"].FirstOrDefault() ?? "";
        if (progress is not ("" or "outstanding" or "complete" or "removal") || sort is not ("" or "username" or "group" or "progress" or "activity" or "assignment" or "risk" or "acceptance" or "removal"))
            return Bad("Choose a supported progress filter and sort.");
        if (Paging(query, 50, 200) is not { } page) return Bad("Invalid paging.");
        var (scope, items, _) = await QueueAsync(http, q!, "", "", ct);
        var rows = new Dictionary<string, JsonObject>(Ordinal);
        var groups = new Dictionary<string, SortedSet<string>>(Ordinal);
        foreach (var item in items)
        {
            var user = (string)item["user"]!;
            if (!rows.TryGetValue(user, out var row))
            {
                rows[user] = row = new JsonObject
                {
                    ["user"] = user, ["groups"] = new JsonArray(), ["activity"] = Part(), ["assignment"] = Part(), ["acceptance"] = Part(), ["removal"] = 0, ["historical"] = 0,
                };
                groups[user] = new SortedSet<string>(Ordinal);
            }
            var life = (string)item["lifecycle"]!;
            if (life is "Historical" or "Resolved") { row["historical"] = (int)row["historical"]! + 1; continue; }
            groups[user].UnionWith((item["groups"] as JsonArray ?? []).Select(g => (string)g!));
            var part = row[(string)item["kind"]!]!.AsObject();
            part["total"] = (int)part["total"]! + 1;
            var decided = item["review_coverage"]?["reviewed"] is JsonValue reviewed ? (bool)reviewed : SodScope.Decided.Contains(life);
            part["decided"] = (int)part["decided"]! + (decided ? 1 : 0);
            if (life == "Removal required") row["removal"] = (int)row["removal"]! + 1;
            if ((string)item["kind"]! == "acceptance")
            {
                if (row["formal_acceptance"] is not JsonObject formal) row["formal_acceptance"] = formal = Part();
                formal["total"] = (int)formal["total"]! + 1;
                if (life == "Accepted") formal["decided"] = (int)formal["decided"]! + 1;
            }
        }
        static JsonObject Part() => new() { ["total"] = 0, ["decided"] = 0 };
        var result = new List<JsonObject>();
        foreach (var (user, row) in rows)
        {
            row["groups"] = new JsonArray([.. groups[user].Select(g => (JsonNode?)g)]);
            var total = new[] { "activity", "assignment", "acceptance" }.Sum(k => (int)row[k]!["total"]!);
            var decided = new[] { "activity", "assignment", "acceptance" }.Sum(k => (int)row[k]!["decided"]!);
            row["formal_acceptance"] ??= Part();
            row["total"] = total; row["decided"] = decided; row["outstanding"] = total - decided;
            if (total > 0) result.Add(row);
        }
        var counts = new JsonObject
        {
            ["all"] = result.Count, ["outstanding"] = result.Count(r => (int)r["outstanding"]! > 0), ["complete"] = result.Count(r => (int)r["outstanding"]! == 0), ["removal"] = result.Count(r => (int)r["removal"]! > 0),
        };
        if (progress == "outstanding") result = [.. result.Where(r => (int)r["outstanding"]! > 0)];
        else if (progress == "complete") result = [.. result.Where(r => (int)r["outstanding"]! == 0)];
        else if (progress == "removal") result = [.. result.Where(r => (int)r["removal"]! > 0)];
        result = [.. result.OrderBy(r => SodViews.Fold((string)r["user"]!), Ordinal)];
        if (sort.Length > 0)
        {
            static double Ratio(JsonNode part) => (int)part["total"]! == 0 ? 0 : (double)(int)part["decided"]! / (int)part["total"]!;
            IComparer<JsonObject> comparer = sort switch
            {
                "username" => Comparer<JsonObject>.Create((x, y) => string.CompareOrdinal(SodViews.Fold((string)x["user"]!), SodViews.Fold((string)y["user"]!))),
                "group" => Comparer<JsonObject>.Create((x, y) => CompareSequences(x["groups"]!.AsArray().Select(g => SodViews.Fold((string)g!)).Order(Ordinal).ToList(), y["groups"]!.AsArray().Select(g => SodViews.Fold((string)g!)).Order(Ordinal).ToList())),
                "progress" => Comparer<JsonObject>.Create((x, y) => Fraction(x).CompareTo(Fraction(y))),
                "activity" or "assignment" => Comparer<JsonObject>.Create((x, y) => Ratio(x[sort]!).CompareTo(Ratio(y[sort]!))),
                "risk" => Comparer<JsonObject>.Create((x, y) => Ratio(x["acceptance"]!).CompareTo(Ratio(y["acceptance"]!))),
                "acceptance" => Comparer<JsonObject>.Create((x, y) => Ratio(x["formal_acceptance"]!).CompareTo(Ratio(y["formal_acceptance"]!))),
                _ => Comparer<JsonObject>.Create((x, y) => ((int)x["removal"]!).CompareTo((int)y["removal"]!)),
            };
            result = q!.Descending ? [.. result.OrderByDescending(r => r, comparer)] : [.. result.OrderBy(r => r, comparer)];
        }
        else result = [.. result.OrderBy(r => (int)r["outstanding"]! == 0)];
        static double Fraction(JsonObject r) => (int)r["total"]! == 0 ? 0 : (double)(int)r["decided"]! / (int)r["total"]!;
        var output = await InfoAsync(http, scope.Bundle, ct);
        output["items"] = new JsonArray([.. result.Skip(page.Offset).Take(page.Limit)]);
        output["total"] = result.Count; output["counts"] = counts; output["offset"] = page.Offset; output["limit"] = page.Limit;
        return Json(output);
    }

    private static int CompareSequences(List<string> a, List<string> b)
    {
        for (var i = 0; i < Math.Min(a.Count, b.Count); i++) { var c = string.CompareOrdinal(a[i], b[i]); if (c != 0) return c; }
        return a.Count.CompareTo(b.Count);
    }

    // ---- remediation

    private static async Task<(SodScope.Scoped Scope, List<JsonObject> Rows, JsonObject Summary, List<JsonObject> Actions, Func<string, string, string> Verify, JsonObject? Reference)> RemediationDataAsync(
        HttpContext http, SodQuery q, CancellationToken ct)
    {
        var services = http.RequestServices;
        var scope = await SodScope.ScopedAsync(services, q with { ReviewPopulation = true }, ct);
        var b = scope.Bundle;
        var actions = await SodScope.ActionsAsync(services, b, ct);
        Func<string, string, string> verify;
        JsonObject? reference = null;
        if (b.FrozenDecisions is not null)
        {
            var frozen = b.FrozenDecisions["verification"] as JsonObject ?? [];
            verify = (_, aid) => (string?)frozen[aid] ?? "Not assessed at approval";
        }
        else (verify, reference) = await SodScope.VerifierAsync(services, actions.Where(a => (string?)a["assignment_id"] is { Length: > 0 }).Select(a => (string)a["user"]!).Distinct(), ct);
        var (rows, summary) = SodViews.RemediationRows(scope.View, scope.State, actions, verify, DateOnly.FromDateTime(DateTime.Now));
        return (scope, rows, summary, actions, verify, reference);
    }

    private static (string Recommended, string Tracking, IResult? Error) RemediationFilters(IQueryCollection query)
    {
        var recommended = query["recommended"].FirstOrDefault() ?? "";
        var tracking = query["tracking"].FirstOrDefault() ?? "";
        if (recommended.Length > 0 && !SodViews.RemediationGroups.Contains(recommended) || tracking is not ("" or "untracked" or "verified")) return ("", "", Bad("Choose a supported recommendation and tracking filter."));
        return (recommended, tracking, null);
    }

    private static List<JsonObject> Tracked(List<JsonObject> rows, string tracking) =>
        tracking == "untracked" ? [.. rows.Where(r => (string)r["recommended"]! == "Remove assignment" && r["action"] is null)] : rows;

    private static async Task<IResult> RemediationAsync(HttpContext http, CancellationToken ct)
    {
        var (q, error) = await QueryAsync(http, ct);
        if (error is not null) return error;
        var (recommended, tracking, invalid) = RemediationFilters(http.Request.Query);
        if (invalid is not null) return invalid;
        if (Paging(http.Request.Query, 50, 200) is not { } page) return Bad("Invalid paging.");
        var (scope, rows, summary, actions, verify, reference) = await RemediationDataAsync(http, q!, ct);
        if (recommended.Length > 0) rows = [.. rows.Where(r => (string)r["recommended"]! == recommended)];
        rows = Tracked(rows, tracking);
        var verified = scope.Bundle.FrozenDecisions is null ? SodScope.RemovalVerification(actions, verify, reference).Ids : [];
        if (tracking == "verified") rows = [];
        var tracked = new JsonArray();
        foreach (var a in actions)
        {
            if (tracking == "verified" && !verified.Contains((string)a["id"]!)) continue;
            var item = a.DeepClone().AsObject();
            item["verification"] = (string?)a["assignment_id"] is { Length: > 0 } aid && (string?)a["recommended"] == "Remove assignment" ? verify((string)a["user"]!, aid) : "Not verifiable from source evidence";
            item["verified"] = verified.Contains((string)a["id"]!);
            tracked.Add(item);
        }
        var result = await InfoAsync(http, scope.Bundle, ct);
        result["items"] = new JsonArray([.. rows.Skip(page.Offset).Take(page.Limit)]);
        result["total"] = rows.Count; result["summary"] = summary; result["offset"] = page.Offset; result["limit"] = page.Limit; result["actions"] = tracked; result["tracking"] = tracking;
        return Json(result);
    }

    public static IEnumerable<IEnumerable<string?>> RemediationCsv(IEnumerable<JsonObject> rows) => rows.Select(r => (IEnumerable<string?>)
    [
        S(r["user"]), S(r["user_group"]), S(r["activity"]), Join(r["risks"]), S(r["role"]), S(r["assignment_id"]), S(r["valid_from"]), S(r["valid_to"]), S(r["activity_decision"]),
        S(r["assignment_decision"]), Join(r["risk_acceptance"]), S(r["recommended"]), S(r["reason"]) is { Length: > 0 } reason ? reason : S(r["controls"]), S(r["owner"]), S(r["due_date"]),
        S(r["action_status"]) + ((bool)r["overdue"]! ? " (overdue)" : ""), S(r["verification"]),
    ]);

    /// <summary>role_assignment_rows: one row per exact (user, role); several groups join, differing decisions show as Mixed (A / B).</summary>
    public static IEnumerable<IEnumerable<string?>> RoleAssignmentCsv(IEnumerable<JsonObject> rows)
    {
        var pairs = new SortedDictionary<(string, string), (SortedSet<string> Groups, SortedSet<string> Decisions)>(Comparer<(string, string)>.Create((x, y) =>
        {
            var c = string.CompareOrdinal(x.Item1, y.Item1);
            return c != 0 ? c : string.CompareOrdinal(x.Item2, y.Item2);
        }));
        foreach (var r in rows)
        {
            var key = ((string)r["user"]!, (string)r["role"]!);
            if (!pairs.TryGetValue(key, out var entry)) pairs[key] = entry = (new SortedSet<string>(Ordinal), new SortedSet<string>(Ordinal));
            if (S(r["user_group"]).Length > 0) entry.Groups.Add(S(r["user_group"]));
            entry.Decisions.Add(S(r["assignment_decision"]) is { Length: > 0 } d ? d : "Pending");
        }
        foreach (var ((user, role), entry) in pairs)
            yield return [user, role, string.Join(", ", entry.Groups), entry.Decisions.Count == 1 ? entry.Decisions.First() : "Mixed (" + string.Join(" / ", entry.Decisions) + ")"];
    }

    // ---- overview

    /// <summary>routers/sod_reviews.review_data: the live legacy review listing; a historical finding is Resolved only with conservative, verifiable absence.</summary>
    public static async Task<(SodBundle Bundle, JsonObject Data)> ReviewDataAsync(IServiceProvider services, CancellationToken ct)
    {
        var b = await SodScope.LoadAsync(services, "current", "active", null, ct);
        var data = await services.GetRequiredService<SodReviewStore>().ListingAsync(b.Findings, "current", b.Coverage, ct);
        var c = await V1SodCatalogue.ContextAsync(services, ct);
        var reference = (string?)c.Settings["data_lifecycle"]?["sources"]?["sod"]?["snapshot"];
        var mapping = (bool?)c.Settings["features"]?["user_role_mapping"] ?? true;
        var risks = (c.Snapshot.Sod?.Risks ?? []).ToDictionary(r => (string)r["risk_id"]!, Ordinal);
        foreach (var row in data["items"]!.AsArray().Select(r => r!.AsObject()))
        {
            if ((string?)row["presence"] != "historical" || row["event"] is not JsonObject || !mapping || c.Snapshot.Catalogue.Roles.Count == 0 || c.Snapshot.Sod is null) continue;
            var finding = row["finding"]!.AsObject();
            var user = c.Snapshot.Users.Users.GetValueOrDefault((string)finding["subject"]!);
            var risk = risks.GetValueOrDefault((string)finding["risk_id"]!);
            var local = c.Storage["entries"]?[(string)finding["risk_id"]!]?["metadata"];
            if (user is null || risk is null || !((bool?)risk["supported"] ?? false) || local is not null && !((bool?)local["enabled"] ?? true)) continue;
            if (reference is null || (string?)finding["source_versions"]?["sod"] != reference) continue;
            if (user.Assignments.Where(a => a.Scope != "other").Any(a => a.MatchStatus is not ("exact" or "wildcard"))) continue;
            row["lifecycle"] = "Resolved";
            row["stale"] = false;
        }
        data["summary"] = SodReviewStore.Summary(data["items"]!.AsArray(), ["Pending", "Reviewed", "Action required", "Outdated", "Resolved", "Historical"]);
        return (b, data);
    }

    /// <summary>governance_overview: actionable SoD 2.0 summary; counts distinguish users, findings, activities and assignments.</summary>
    private static async Task<JsonObject> GovernanceOverviewAsync(IServiceProvider services, CancellationToken ct)
    {
        var b = await SodScope.LoadAsync(services, "current", "active", null, ct);
        if ((string?)b.Coverage["status"] != "available")
            return new JsonObject { ["available"] = false, ["reason"] = b.Coverage["reason"]?.DeepClone(), ["missing"] = b.Coverage["missing"]?.DeepClone() ?? new JsonArray() };
        var conflicts = SodScope.Model(b);
        var change = await SodScope.ObserveAsync(services, b, conflicts, ct);
        var model = SodScope.ReviewModel(b);
        var state = await SodScope.StatesAsync(services, b, model, ct);
        JsonObject Tally(string kind)
        {
            var result = new JsonObject();
            foreach (var item in state.Items[kind].Values) result[item.Lifecycle] = ((int?)result[item.Lifecycle] ?? 0) + 1;
            return result;
        }
        var actions = await SodScope.ActionsAsync(services, b, ct);
        var today = DateOnly.FromDateTime(DateTime.Now).ToString("yyyy-MM-dd", CultureInfo.InvariantCulture);
        var open = actions.Where(a => (string?)a["status"] is "Open" or "In progress").ToList();
        var (verify, reference) = await SodScope.VerifierAsync(services, null, ct);
        var (rows, _) = SodViews.RemediationRows(model, state, actions, verify, DateOnly.FromDateTime(DateTime.Now));
        var index = await services.GetRequiredService<SodPeriodStore>().ReadAsync(ct);
        var periods = index["items"]!.AsArray().Select(p => p!.AsObject()).ToList();
        var progress = new JsonArray();
        foreach (var period in periods.OrderByDescending(p => (string)p["modified"]!, Ordinal))
        {
            if (period["deleted_at"] is JsonValue || SodScope.FrozenStates.Contains((string)period["state"]!)) continue;
            if (await SodPeriods.ProgressAsync(services, period, ct) is not { } assessment) continue;
            var row = new JsonObject { ["id"] = period["id"]!.DeepClone(), ["name"] = period["name"]!.DeepClone(), ["state"] = period["state"]!.DeepClone() };
            foreach (var (k, v) in assessment) row[k] = v?.DeepClone();
            progress.Add(row);
            if (progress.Count >= 5) break;
        }
        var latest = periods.Where(p => p["deleted_at"] is not JsonValue && SodScope.FrozenStates.Contains((string)p["state"]!) && p["approval_date"] is JsonValue)
            .OrderByDescending(p => (string)p["approval_date"]!, Ordinal).ThenByDescending(p => (string)p["modified"]!, Ordinal).FirstOrDefault();
        var coverage = new JsonObject();
        foreach (var (kind, values) in state.Coverage) coverage[kind] = new JsonObject { ["total"] = values.Count, ["reviewed"] = values.Values.Count(v => (bool?)v["reviewed"] ?? false) };
        return new JsonObject
        {
            ["available"] = true,
            ["latest_approval"] = latest is null ? null : new JsonObject
            {
                ["id"] = latest["id"]!.DeepClone(), ["name"] = latest["name"]!.DeepClone(), ["state"] = latest["state"]!.DeepClone(), ["approval_date"] = latest["approval_date"]!.DeepClone(), ["approver"] = latest["approver"]?.DeepClone(),
            },
            ["users_with_conflicts"] = conflicts.Count, ["user_risk_findings"] = conflicts.Values.Sum(e => e.Findings.Count),
            ["activities"] = Tally("activity"), ["assignments"] = Tally("assignment"), ["acceptance"] = Tally("acceptance"), ["review_coverage"] = coverage,
            ["assignments_marked_remove"] = state.Items["assignment"].Values.Count(i => i.Lifecycle == "Removal required"), ["concentration"] = SodViews.ConflictConcentration(conflicts),
            ["remediation"] = new JsonObject
            {
                ["open_actions"] = open.Count, ["overdue"] = open.Count(a => (string?)a["due_date"] is { Length: > 0 } due && string.CompareOrdinal(due, today) < 0),
                ["removal_without_action"] = rows.Where(r => (string)r["recommended"]! == "Remove assignment" && r["action"] is null).Select(r => ((string)r["user"]!, (string)r["assignment_id"]!)).Distinct().Count(),
                ["verification"] = SodScope.RemovalVerification(actions, verify, reference).Summary,
            },
            ["periods"] = progress, ["change"] = change?.DeepClone(), ["as_of"] = b.AsOf,
        };
    }

    private static async Task<IResult> OverviewAsync(HttpContext http, CancellationToken ct)
    {
        var services = http.RequestServices;
        var (b, reviews) = await ReviewDataAsync(services, ct);
        var c = await V1SodCatalogue.ContextAsync(services, ct);
        var catalogue = V1SodCatalogue.Catalogue(c);
        var summary = catalogue["summary"]!.AsObject();
        var available = (string?)b.Coverage["status"] == "available";
        var reviewSummary = reviews["summary"]!.AsObject();
        var criticality = new JsonObject();
        foreach (var row in b.Findings) { var level = (string)row["criticality"]!; criticality[level] = ((int?)criticality[level] ?? 0) + 1; }
        var roleFindings = (bool?)b.Coverage["roles_available"] ?? false;
        int? roles = null;
        if (roleFindings)
        {
            var (captured, _) = await V1SodAnalysis.CaptureAsync(services, b.Query!, ct);
            roles = captured?.Roles.Count;
        }
        var counts = new JsonObject
        {
            ["defined"] = summary["current"]?.DeepClone(), ["enabled"] = summary["enabled"]?.DeepClone(), ["new"] = summary["new"]?.DeepClone(),
            ["needs_description_review"] = summary["needs_description_review"]?.DeepClone(), ["user_findings"] = available ? b.Findings.Count : null, ["role_findings"] = roles,
            ["reviewed"] = (int?)reviewSummary["Reviewed"] ?? 0, ["pending"] = available ? (int?)reviewSummary["Pending"] ?? 0 : null, ["outdated"] = (int?)reviewSummary["Outdated"] ?? 0,
        };
        return Json(new JsonObject
        {
            ["counts"] = counts, ["criticality"] = criticality, ["source"] = catalogue["source"]?.DeepClone(), ["coverage"] = b.Coverage.DeepClone(),
            ["governance"] = await GovernanceOverviewAsync(services, ct),
        });
    }

    // ---- routes

    public static void Map(RouteGroupBuilder api)
    {
        static Task<IResult> Guard(Func<Task<IResult>> handler) => SodPeriods.Guard(handler);
        api.MapGet("/sod/context", (HttpContext http, CancellationToken ct) => Guard(async () =>
        {
            var context = http.Request.Query["context"].FirstOrDefault() ?? "current";
            if (context.Length > 64) return Bad("context: String should have at most 64 characters");
            var b = await SodScope.LoadAsync(http.RequestServices, context, "active", null, ct);
            return Json(await InfoAsync(http, b, ct));
        }));
        api.MapGet("/sod/overview", (HttpContext http, CancellationToken ct) => Guard(() => OverviewAsync(http, ct)));
        api.MapGet("/sod/matrix/{kind}", (string kind, HttpContext http, CancellationToken ct) => Guard(() => kind is "risk" or "activity" ? MatrixAsync(http, kind, ct) : Task.FromResult(Bad("Choose risk or activity."))));
        api.MapGet("/sod/matrix/{kind}/group-export", (string kind, HttpContext http, CancellationToken ct) => Guard(() => kind is "risk" or "activity" ? GroupExportAsync(http, kind, ct) : Task.FromResult(Bad("Choose risk or activity."))));
        api.MapGet("/sod/filter-options", (HttpContext http, CancellationToken ct) => Guard(() => FilterOptionsAsync(http, ct)));
        api.MapGet("/sod/explorer/access_list/selection", (HttpContext http, CancellationToken ct) => Guard(() => SelectionAsync(http, ct)));
        api.MapGet("/sod/explorer/{table}", (string table, HttpContext http, CancellationToken ct) => Guard(async () =>
        {
            if (!Tables.Contains(table)) return Bad("Choose a supported explorer table.");
            var (q, error) = await QueryAsync(http, ct);
            if (error is not null) return error;
            if (Paging(http.Request.Query, 50, 200) is not { } page) return Bad("Invalid paging.");
            var (scope, rows) = await ExplorerAsync(http, table, q!, ct);
            var result = await InfoAsync(http, scope.Bundle, ct);
            result["table"] = table; result["items"] = new JsonArray([.. rows.Skip(page.Offset).Take(page.Limit)]); result["total"] = rows.Count;
            result["offset"] = page.Offset; result["limit"] = page.Limit;
            if (table == "access_list") result["progress"] = await ProgressAsync(http, q!, ct);
            return Json(result);
        }));
        api.MapGet("/sod/explorer/{table}/export", (string table, HttpContext http, CancellationToken ct) => Guard(async () =>
        {
            if (!Tables.Contains(table)) return Bad("Choose a supported explorer table.");
            var (q, error) = await QueryAsync(http, ct);
            if (error is not null) return error;
            var (_, rows) = await ExplorerAsync(http, table, q!, ct);
            return Csv(http, ExplorerColumns[table], rows.Select(r => ExplorerCsv(table, r)), "explorer-" + table.Replace('_', '-'));
        }));
        api.MapGet("/sod/queue", (HttpContext http, CancellationToken ct) => Guard(async () =>
        {
            var (q, error) = await QueryAsync(http, ct);
            if (error is not null) return error;
            var (kind, status, invalid) = QueueFilters(http.Request.Query);
            if (invalid is not null) return invalid;
            if (Paging(http.Request.Query, 50, 200) is not { } page) return Bad("Invalid paging.");
            var (scope, items, counts) = await QueueAsync(http, q!, kind, status, ct);
            var result = await InfoAsync(http, scope.Bundle, ct);
            result["items"] = new JsonArray([.. items.Skip(page.Offset).Take(page.Limit)]); result["total"] = items.Count; result["counts"] = counts;
            result["offset"] = page.Offset; result["limit"] = page.Limit; result["identity_notice"] = V1SodDecisions.IdentityNotice;
            return Json(result);
        }));
        api.MapGet("/sod/queue/users", (HttpContext http, CancellationToken ct) => Guard(() => QueueUsersAsync(http, ct)));
        api.MapGet("/sod/queue/export", (HttpContext http, CancellationToken ct) => Guard(async () =>
        {
            var (q, error) = await QueryAsync(http, ct);
            if (error is not null) return error;
            var (kind, status, invalid) = QueueFilters(http.Request.Query);
            if (invalid is not null) return invalid;
            var (_, items, _) = await QueueAsync(http, q!, kind, status, ct);
            var rows = items.Select(i =>
            {
                var e = i["event"] as JsonObject;
                var coverage = i["review_coverage"];
                return (IEnumerable<string?>)
                [
                    q!.Context, S(i["kind"]), S(i["user"]), Join(i["groups"]), S(i["ref"]), Join(i["risks"]), S(i["lifecycle"]), S(e?["decision"]), S(e?["reviewer"]), S(e?["approver"]),
                    S(e?["timestamp"]), S(e?["justification"]), S(e?["controls"]), S(e?["expires"]), S(e?["evidence_version"]), Py((bool?)coverage?["reviewed"] ?? false),
                    S(coverage?["provenance"]), Py((bool?)coverage?["removal_planned"] ?? false), S(e?["bulk_operation_id"]), S(e?["previous_decision"]),
                ];
            });
            return Csv(http, QueueColumns, rows, "review-queue");
        }));
        api.MapGet("/sod/remediation", (HttpContext http, CancellationToken ct) => Guard(() => RemediationAsync(http, ct)));
        api.MapGet("/sod/remediation/export", (HttpContext http, CancellationToken ct) => Guard(async () =>
        {
            var (q, error) = await QueryAsync(http, ct);
            if (error is not null) return error;
            var (recommended, tracking, invalid) = RemediationFilters(http.Request.Query);
            if (invalid is not null) return invalid;
            var format = http.Request.Query["format"].FirstOrDefault() ?? "detailed";
            if (format is not ("detailed" or "role-assignments")) return Bad("Choose detailed or role-assignments.");
            var (_, rows, _, _, _, _) = await RemediationDataAsync(http, q!, ct);
            if (recommended.Length > 0) rows = [.. rows.Where(r => (string)r["recommended"]! == recommended)];
            rows = Tracked(rows, tracking);
            return format == "role-assignments" ? Csv(http, RoleAssignmentColumns, RoleAssignmentCsv(rows), "role-assignments") : Csv(http, RemediationColumns, RemediationCsv(rows), "access-remediation");
        }));
    }
}
