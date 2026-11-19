using System.Globalization;
using System.Text;
using System.Text.Json.Nodes;
using AuthLens.Domain.Json;
using AuthLens.Domain.Roles;
using AuthLens.Domain.Sod;

namespace AuthLens.Api;

/// <summary>Port of routers/sod_analysis.py: potential SoD findings for users and catalogue roles from the captured snapshots (the existing
/// SodAnalyzer, equivalence-tested against v1 analyze), enriched with catalogue metadata and account state, filtered and sorted as in v1, plus
/// paged evidence of one finding and the evidence CSV export. Findings carry v1 identities (finding_id) and evidence versions, so review decisions
/// recorded against them stay comparable. The functional-group and manager filters need Functional Groups, which is not migrated: they answer 501.</summary>
public static class V1SodAnalysis
{
    public sealed record Query(string Kind, string Validity, DateOnly AsOf, List<string> SelectedRoles, string Search, string Risk, string Criticality, string RiskType, string Category,
        string Username, string Group, string CompositeRole, string SingleRole, string Tcode, string AccountStatus, List<string> Usernames, List<string> Risks, List<string> Criticalities,
        List<string> Categories, List<string> Groups, List<string> Tcodes, string Sort, bool Descending);

    public sealed record Captured(string Generation, string AsOf, List<JsonObject> Users, List<JsonObject> Roles, JsonObject Summary, JsonObject Coverage, JsonObject Methodology, JsonObject Sources);

    private static IResult Detail(int status, string detail) => Results.Json(new { detail }, statusCode: status);
    private static IResult Json(JsonNode node) => Results.Content(node.ToJsonString(), "application/json");
    private static string Fold(string value) => AuthLens.Domain.Text.PythonText.Casefold(value);

    /// <summary>analysis_query: the same names, enumerations and bounds as v1; an invalid value is a 422.</summary>
    public static (Query? Query, IResult? Error) Parse(IQueryCollection q)
    {
        string One(string name, int max) => q[name].FirstOrDefault() is { } v ? (v.Length <= max ? v : throw new ArgumentException(name)) : "";
        List<string> Many(string name, int count) => q[name].Count <= count ? [.. q[name].Select(v => v ?? "")] : throw new ArgumentException(name);
        try
        {
            if (q["functional_groups"].Count > 50 || q["managers"].Count > 50) throw new ArgumentException("functional_groups");
            var kind = q["kind"].FirstOrDefault() ?? "users";
            var validity = q["validity"].FirstOrDefault() ?? "active";
            var sort = q["sort"].FirstOrDefault() ?? "subject";
            var accountStatus = q["account_status"].FirstOrDefault() ?? "";
            if (kind is not ("users" or "roles") || validity is not ("active" or "expired" or "future" or "unknown" or "all") || sort is not ("subject" or "risk_id" or "criticality" or "evidence_count")
                || accountStatus is not ("" or "locked" or "unlocked" or "ad_disabled" or "ad_enabled" or "unknown")) throw new ArgumentException("enum");
            var asOf = q["as_of"].FirstOrDefault() is { Length: > 0 } text ? DateOnly.ParseExact(text, "yyyy-MM-dd", CultureInfo.InvariantCulture) : DateOnly.FromDateTime(DateTime.Now);
            var selected = Many("selected_roles", 25);
            if (selected.Any(n => n.Length is 0 or > 512)) return (null, Detail(422, "Choose at most 25 existing catalogue role identifiers."));
            return (new Query(kind, validity, asOf, [.. selected.Distinct().Order(StringComparer.Ordinal)], One("search", 256), One("risk", 512), One("criticality", 64), One("risk_type", 64),
                One("category", 120), One("username", 512), One("group", 256), One("composite_role", 512), One("single_role", 512), One("tcode", 256), accountStatus, Many("usernames", 100),
                Many("risks", 100), Many("criticalities", 50), Many("categories", 50), Many("groups", 100), Many("tcodes", 100), sort, q["descending"].FirstOrDefault() is "true" or "1"), null);
        }
        catch (Exception error) when (error is ArgumentException or FormatException) { return (null, Detail(422, "Invalid SoD analysis query.")); }
    }

    /// <summary>organizational_usernames: Functional Group and Manager select users by name through the username filter (never conflict evaluation).</summary>
    public static async Task<Query> OrganizationalAsync(IServiceProvider services, Query query, IQueryCollection q, CancellationToken ct)
    {
        var groups = q["functional_groups"].Select(v => v ?? "").Where(v => v.Length > 0).ToList();
        var managers = q["managers"].Select(v => v ?? "").Where(v => v.Length > 0).ToList();
        if (groups.Count == 0 && managers.Count == 0) return query;
        var scope = new SodQuery
        {
            Context = "current", Validity = query.Validity, AsOf = query.AsOf,
            Lists = new Dictionary<string, List<string>>(StringComparer.Ordinal) { ["usernames"] = query.Usernames, ["functional_groups"] = groups, ["managers"] = managers },
        };
        var expanded = await SodScope.OrganizationalAsync(services, scope, ct);
        return query with { Usernames = expanded.L("usernames") };
    }

    private static readonly Dictionary<string, Captured> Cache = new(StringComparer.Ordinal);

    /// <summary>captured(): analysis of the current snapshots for this context, enriched with catalogue metadata and account state.</summary>
    public static async Task<(Captured? Result, IResult? Error)> CaptureAsync(IServiceProvider services, Query query, CancellationToken ct)
    {
        var c = await V1SodCatalogue.ContextAsync(services, ct);
        var features = c.Settings["features"];
        var (mapping, directoryEnabled, sodEnabled) = ((bool?)features?["user_role_mapping"] ?? true, (bool?)features?["employee_directory"] ?? false, (bool?)features?["sod"] ?? false);
        var references = c.Settings["data_lifecycle"]?["sources"]?.DeepClone() ?? new JsonObject();
        var generation = CanonicalJson.Sha256(new object?[]
        {
            c.Snapshot.Ids.Roles, c.Snapshot.Ids.Users, c.Snapshot.Ids.Sod, c.Snapshot.Ids.Employees, c.Revision, query.AsOf.ToString("yyyy-MM-dd"), query.Validity, query.SelectedRoles,
            mapping, directoryEnabled, sodEnabled, references.ToJsonString(),
        });
        lock (Cache) if (Cache.TryGetValue(generation, out var cached)) return (cached, null);
        var entries = c.Storage["entries"]!.AsObject();
        var enabled = entries.ToDictionary(p => p.Key, p => (bool?)p.Value!["metadata"]!["enabled"] ?? true, StringComparer.Ordinal);
        var sod = sodEnabled ? c.Snapshot.Sod : null;
        SodResult result;
        try
        {
            result = SodAnalyzer.Analyze(c.Snapshot.Catalogue, mapping ? c.Snapshot.Users : new AuthLens.Domain.Users.UserDirectory(), sod, query.AsOf, query.Validity,
                query.SelectedRoles, enabled, directoryEnabled ? c.Snapshot.Directory : null, directoryEnabled);
        }
        catch (ArgumentException) { return (null, Detail(422, "A selected role or analysis option is unavailable in the current dataset.")); }
        var definitions = (sod?.Risks ?? []).ToDictionary(r => (string)r["risk_id"]!, StringComparer.Ordinal);
        JsonObject Enrich(SodFinding finding)
        {
            var node = SodGovernance.FindingJson(finding);
            if (node["account"] is JsonObject account)
            {
                var accounts = account["accounts"]!.AsArray();
                var statuses = accounts.Select(a => SapDates.IntervalStatus((string?)a!["valid_from"], (string?)a["valid_to"], query.AsOf)).ToHashSet();
                account["sap_validity"] = statuses.SetEquals(["active"]) ? "Valid" : statuses.Count > 0 && statuses.IsSubsetOf(["expired", "future"]) ? "Invalid" : "Unknown";
                var locks = accounts.Select(a => a!["locked"]?.GetValue<bool>()).ToHashSet();
                account["lock_status"] = locks.SetEquals([true]) ? "Locked" : locks.SetEquals([false]) ? "Unlocked" : "Unknown";
            }
            var source = definitions[finding.RiskId];
            var local = entries[finding.RiskId]?["metadata"];
            node["risk"] = new JsonObject
            {
                ["display_name"] = (string?)local?["display_name"] ?? "", ["source_text"] = (string)source["source_text"]!, ["business_category"] = (string?)local?["business_category"] ?? "",
                ["risk_type"] = (string)source["risk_type"]!,
            };
            return node;
        }
        var users = result.Users.Select(Enrich).ToList();
        var reason = result.UsersAvailable ? null : !sodEnabled ? "sod_disabled" : !mapping ? "mapping_disabled" : "required_source_unavailable";
        var missing = new JsonArray();
        if (reason == "required_source_unavailable")
            foreach (var (name, present) in new[] { ("roles", c.Snapshot.Catalogue.Roles.Count > 0), ("users", c.Snapshot.Users.Users.Count > 0), ("sod", sod is not null) }) if (!present) missing.Add(name);
        var captured = new Captured(generation, query.AsOf.ToString("yyyy-MM-dd"), users, result.Roles.Select(Enrich).ToList(),
            new JsonObject
            {
                ["user_findings"] = users.Count, ["role_findings"] = result.Roles.Count, ["users_with_findings"] = users.Select(u => (string)u["subject"]!).Distinct().Count(),
                ["current_potential_findings"] = users.Count(u => (bool)u["current_potential"]!),
            },
            new JsonObject
            {
                ["status"] = result.UsersAvailable ? "available" : "unavailable", ["reason"] = reason, ["missing"] = missing, ["eligible_assignment_records"] = result.EligibleAssignments,
                ["mapped_assignment_records"] = result.MappedAssignments, ["unmapped_assignment_records"] = result.EligibleAssignments - result.MappedAssignments,
                ["roles_available"] = c.Snapshot.Catalogue.Roles.Count > 0, ["supported_risks"] = result.SupportedRisks,
            },
            new JsonObject
            {
                ["policy"] = SodSource.EvaluationPolicy, ["validity"] = query.Validity, ["evidence"] = "Potential transaction-derived SoD; not effective SAP authorization.",
                ["historical"] = "All-validity findings do not prove concurrent historical access.", ["role_validity"] = "Catalogue role coverage has no assignment validity.",
            },
            new JsonObject { ["sod_content_hash"] = sod?.ContentHash, ["sap_revision"] = null, ["references"] = references });
        lock (Cache) { if (Cache.Count > 8) Cache.Clear(); Cache[generation] = captured; }
        return (captured, null);
    }

    public static string Subject(JsonObject row) => row["subject"] is JsonArray list ? string.Join(" + ", list.Select(v => (string)v!)) : (string)row["subject"]!;

    private static bool SearchFields(string term, IEnumerable<string?> fields)
    {
        var list = fields.ToList();
        return term.Contains('*') ? list.Any(f => TextMatching.TextMatches(f, term)) : TextMatching.TextMatches(string.Join(' ', list.Select(f => f ?? "")), term);
    }

    private static List<string> Combined(string single, List<string> plural) => [.. new[] { single }.Concat(plural).Where(v => v.Length > 0)];

    private static bool AccountMatches(JsonObject row, string selected)
    {
        if (row["account"] is not JsonObject account) return false;
        var locks = account["accounts"]!.AsArray().Select(a => a!["locked"]?.GetValue<bool>()).ToHashSet();
        return selected switch
        {
            "locked" => locks.SetEquals([true]), "unlocked" => locks.SetEquals([false]), "ad_disabled" => (string?)account["ad_status"] == "Disabled", "ad_enabled" => (string?)account["ad_status"] == "Enabled",
            _ => (string?)account["ad_status"] == "Unknown" || !(locks.SetEquals([true]) || locks.SetEquals([false])),
        };
    }

    /// <summary>v1 filtered(): OR within a filter, AND between filters, and the v1 sort keys with the finding id as tie-breaker.</summary>
    public static List<JsonObject> Filtered(Captured result, Query query)
    {
        var items = new List<JsonObject>();
        var usernames = query.Usernames.Select(Fold).ToHashSet(StringComparer.Ordinal);
        foreach (var row in query.Kind == "users" ? result.Users : result.Roles)
        {
            var definition = row["risk"]!;
            var paths = row["evidence"]!.AsObject().SelectMany(p => p.Value!.AsArray()).Select(p => p!.AsObject()).ToList();
            var search = query.Search.Trim();
            if (search.Length > 0 && !SearchFields(search, new[] { Subject(row), (string)row["risk_id"]!, (string?)definition["display_name"], (string?)definition["source_text"] }
                    .Concat(paths.Select(p => (string?)p["tcode"])).Concat(paths.Select(p => (string?)p["matched_catalogue_pattern"])).Concat(paths.Select(p => (string?)p["actual_assigned_role"] ?? ""))))
                continue;
            if (new[] { (Combined(query.Risk, query.Risks), (string)row["risk_id"]!), (Combined(query.Criticality, query.Criticalities), (string)row["criticality"]!),
                    (Combined(query.Category, query.Categories), (string)definition["business_category"]!) }.Any(f => f.Item1.Count > 0 && !f.Item1.Contains(f.Item2))
                || query.RiskType.Length > 0 && (string?)definition["risk_type"] != query.RiskType) continue;
            if (query.Username.Length > 0 && ((string)row["kind"]! != "user" || !TextMatching.TextMatches((string)row["subject"]!, query.Username))) continue;
            if (usernames.Count > 0 && ((string)row["kind"]! != "user" || !usernames.Contains(Fold((string)row["subject"]!)))) continue;
            var groups = Combined(query.Group, query.Groups);
            if (groups.Count > 0 && !paths.Any(p => groups.Contains((string?)p["user_group"] ?? ""))) continue;
            var tcodes = Combined(query.Tcode, query.Tcodes);
            if (tcodes.Count > 0 && !paths.Any(p => tcodes.Any(t => TextMatching.TextMatches((string?)p["tcode"] ?? "", t)))) continue;
            if (query.CompositeRole.Length > 0 && !paths.Any(p => TextMatching.TextMatches((string?)p["matched_catalogue_pattern"] ?? "", query.CompositeRole))) continue;
            if (query.SingleRole.Length > 0 && !paths.Any(p => TextMatching.TextMatches((string?)p["single_role"] ?? "", query.SingleRole))) continue;
            if (query.AccountStatus.Length > 0 && !AccountMatches(row, query.AccountStatus)) continue;
            items.Add(row);
        }
        IOrderedEnumerable<JsonObject> ordered = query.Sort == "evidence_count"
            ? items.OrderBy(r => r["evidence"]!.AsObject().Sum(p => p.Value!.AsArray().Count))
            : items.OrderBy(r => Fold(query.Sort == "subject" ? Subject(r) : (string)r[query.Sort]!), StringComparer.Ordinal);
        var list = ordered.ThenBy(r => (string)r["finding_id"]!, StringComparer.Ordinal).ToList();
        if (query.Descending) list.Reverse();
        return list;
    }

    private static (int Offset, int Limit)? Paging(IQueryCollection q)
    {
        var offset = int.TryParse(q["offset"].FirstOrDefault() ?? "0", out var o) ? o : -1;
        var limit = int.TryParse(q["limit"].FirstOrDefault() ?? "25", out var l) ? l : -1;
        return offset < 0 || limit is < 1 or > 100 ? null : (offset, limit);
    }

    public static void Map(RouteGroupBuilder api)
    {
        api.MapGet("/sod/analysis", async (HttpContext http, IServiceProvider services, CancellationToken ct) =>
        {
            http.Response.Headers.CacheControl = "no-store";
            var (query, error) = Parse(http.Request.Query);
            if (error is not null) return error;
            query = await OrganizationalAsync(services, query!, http.Request.Query, ct);
            if (Paging(http.Request.Query) is not var (offset, limit)) return Detail(422, "Invalid paging parameters.");
            var (result, failure) = await CaptureAsync(services, query!, ct);
            if (failure is not null) return failure;
            var rows = Filtered(result!, query!);
            var items = new JsonArray([.. rows.Skip(offset).Take(limit).Select(row =>
            {
                var copy = row.DeepClone().AsObject();
                var evidence = row["evidence"]!.AsObject();
                copy["evidence"] = new JsonObject(evidence.Select(p => KeyValuePair.Create(p.Key, (JsonNode?)new JsonArray([.. p.Value!.AsArray().Take(25).Select(x => x!.DeepClone())]))));
                copy["evidence_total"] = new JsonObject(evidence.Select(p => KeyValuePair.Create(p.Key, (JsonNode?)p.Value!.AsArray().Count)));
                return (JsonNode?)copy;
            })]);
            return Json(new JsonObject
            {
                ["items"] = items, ["total"] = rows.Count, ["offset"] = offset, ["limit"] = limit, ["generation"] = result!.Generation,
                ["summary"] = new JsonObject { ["unfiltered"] = result.Summary.DeepClone(), ["filtered"] = new JsonObject { ["findings"] = rows.Count, ["subjects"] = rows.Select(Subject).Distinct().Count() } },
                ["coverage"] = result.Coverage.DeepClone(), ["methodology"] = result.Methodology.DeepClone(), ["as_of"] = result.AsOf, ["sources"] = result.Sources.DeepClone(),
            });
        });

        api.MapGet("/sod/analysis/evidence", async (HttpContext http, IServiceProvider services, CancellationToken ct) =>
        {
            http.Response.Headers.CacheControl = "no-store";
            var q = http.Request.Query;
            var findingId = q["finding_id"].FirstOrDefault() ?? "";
            var expected = q["expected_generation"].FirstOrDefault() ?? "";
            var side = q["side"].FirstOrDefault() ?? "ACTVT1";
            static bool Hex(string v) => v.Length == 64 && v.All(c => c is >= '0' and <= '9' or >= 'a' and <= 'f');
            if (!Hex(findingId) || !Hex(expected) || side is not ("ACTVT1" or "ACTVT2")) return Detail(422, "Invalid evidence request.");
            var (query, error) = Parse(q);
            if (error is not null) return error;
            query = await OrganizationalAsync(services, query!, q, ct);
            if (Paging(q) is not var (offset, limit)) return Detail(422, "Invalid paging parameters.");
            var (result, failure) = await CaptureAsync(services, query!, ct);
            if (failure is not null) return failure;
            if (result!.Generation != expected) return Detail(409, "SoD evidence changed. Reload findings before inspecting further evidence.");
            var row = (query!.Kind == "users" ? result.Users : result.Roles).FirstOrDefault(r => (string)r["finding_id"]! == findingId);
            if (row is null) return Detail(404, "The finding is unavailable in this analysis context.");
            var paths = row["evidence"]![side]!.AsArray();
            return Json(new JsonObject
            {
                ["items"] = new JsonArray([.. paths.Skip(offset).Take(limit).Select(p => p!.DeepClone())]), ["total"] = paths.Count, ["offset"] = offset, ["limit"] = limit,
                ["finding_id"] = findingId, ["side"] = side, ["generation"] = result.Generation, ["as_of"] = result.AsOf,
            });
        });

        api.MapGet("/sod/analysis/export", async (HttpContext http, IServiceProvider services, CancellationToken ct) =>
        {
            var (query, error) = Parse(http.Request.Query);
            if (error is not null) return error;
            query = await OrganizationalAsync(services, query!, http.Request.Query, ct);
            var expected = http.Request.Query["expected_generation"].FirstOrDefault();
            var (result, failure) = await CaptureAsync(services, query!, ct);
            if (failure is not null) return failure;
            if (expected is not null && result!.Generation != expected) return Detail(409, "SoD evidence changed. Reload findings before exporting.");
            var rows = Filtered(result!, query!);
            static string LocalDate(string? value) => SapDates.Parse(value) is { } d ? d.ToString("dd.MM.yyyy", CultureInfo.InvariantCulture) : "";
            string[] columns = ["FINDING_ID", "KIND", "SUBJECT", "RISK", "CRITICITY", "TYPE", "ACTIVITY_SLOT", "ACTIVITY", "TCODE", "MATRIX_TRANSACTION", "ROLE_NAME", "CATALOGUE_ROLE", "SINGLE_ROLE",
                "ROLE_VALID_FROM", "ROLE_VALID_TO", "ASSIGNMENT_STATUS", "USER_GROUP", "MATCHING_STATUS", "EVIDENCE_VERSION", "AS_OF", "EVALUATION_POLICY", "SOD_SOURCE_VERSION", "ROLE_SOURCE_VERSION", "USER_SOURCE_VERSION"];
            var csv = new StringBuilder("﻿");
            V1Csv.Line(csv, columns, cells: false);
            var references = result!.Sources["references"]!;
            foreach (var row in rows)
                foreach (var (side, paths) in row["evidence"]!.AsObject())
                    foreach (var path in paths!.AsArray().Select(p => p!))
                        V1Csv.Line(csv, [(string)row["finding_id"]!, (string)row["kind"]!, Subject(row), (string)row["risk_id"]!, (string)row["criticality"]!, (string)row["risk"]!["risk_type"]!,
                            side, (string?)path["activity"], (string?)path["tcode"], (string?)path["matrix_transaction"], (string?)path["actual_assigned_role"] ?? "", (string?)path["matched_catalogue_pattern"],
                            (string?)path["single_role"], LocalDate((string?)path["role_valid_from"]), LocalDate((string?)path["role_valid_to"]), (string?)path["interval_status"] ?? "Not applicable",
                            (string?)path["user_group"] ?? "", (string?)path["matching_status"] ?? "Catalogue mapping", (string)row["evidence_version"]!, result.AsOf, (string)row["evaluation_policy"]!,
                            (string?)references["sod"]?["snapshot"] ?? "", (string?)references["roles"]?["snapshot"] ?? "", (string?)references["users"]?["snapshot"] ?? ""], cells: true);
            var headers = http.Response.Headers;
            headers.CacheControl = "no-store";
            headers.ContentDisposition = $"attachment; filename=\"authlens-sod-{query!.Kind}-findings-{result.AsOf}.csv\"";
            headers["X-SAP-Lens-Data-Generation"] = result.Generation;
            headers["X-SAP-Lens-As-Of"] = result.AsOf;
            headers["X-SAP-Lens-Finding-Count"] = rows.Count.ToString(CultureInfo.InvariantCulture);
            return Results.Text(csv.ToString(), "text/csv; charset=utf-8", Encoding.UTF8);
        });
    }
}
