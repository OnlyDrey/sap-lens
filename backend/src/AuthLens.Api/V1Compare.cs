using System.Text.Json;
using System.Text.Json.Nodes;
using AuthLens.Application;
using AuthLens.Domain.Catalogue;

namespace AuthLens.Api;

/// <summary>Port of routers/comparison.py (POST /api/compare): 2-5 composite roles compared by single roles and by transaction codes, with shared and
/// exclusive sets and pairwise overlap counts.</summary>
public static class V1Compare
{
    private static IResult Detail(int status, object detail) => Results.Json(new { detail }, statusCode: status);

    private static object SingleRoleInfo(SingleRole s) => new
    {
        function_key = s.FunctionKey, module_name = s.ModuleName, child_agr = s.ChildAgr, child_agr_text = s.ChildAgrText, tcode_count = s.Tcodes.Count,
    };

    private static object Tcode(TCode t) => new
    {
        tcode = t.Code, ttext = t.Text, assignment_sources = t.AssignmentSources.Select(s => new { child_agr = s.ChildAgr, parent_agr = s.ParentAgr, effective_role = s.EffectiveRole }).ToList(),
        alternate_texts = t.AlternateTexts,
    };

    public static void Map(RouteGroupBuilder api)
    {
        api.MapPost("/compare", async (HttpContext http, SnapshotService snapshots, CancellationToken ct) =>
        {
            JsonNode? body;
            try { body = await JsonNode.ParseAsync(http.Request.Body, cancellationToken: ct); }
            catch (JsonException) { return Detail(422, "A JSON body with roles is required."); }
            if (body?["roles"] is not JsonArray list || list.Any(v => v?.GetValueKind() != JsonValueKind.String))
                return Detail(422, new[] { V1Validation.Error("list_type", "roles", "Input should be a valid list of strings") });
            if (list.Count < 2) return Detail(422, new[] { V1Validation.Error("too_short", "roles", "List should have at least 2 items after validation, not " + list.Count) });
            if (list.Count > 5) return Detail(422, new[] { V1Validation.Error("too_long", "roles", "List should have at most 5 items after validation, not " + list.Count) });
            var names = list.Select(v => (string)v!).ToList();
            if (names.Distinct(StringComparer.Ordinal).Count() != names.Count) return Detail(400, "Duplicate role names are not allowed.");
            var snapshot = await snapshots.GetAsync(ct);
            var roles = new List<Role>();
            foreach (var name in names)
            {
                if (!snapshot.Catalogue.Roles.TryGetValue(name, out var role)) return Detail(404, $"Role '{name}' not found.");
                roles.Add(role);
            }

            var srSets = new List<HashSet<string>>();
            var srLookups = new List<Dictionary<string, SingleRole>>();
            var tcSets = new List<HashSet<string>>();
            var tcLookups = new List<Dictionary<string, TCode>>();
            foreach (var role in roles)
            {
                var lookup = new Dictionary<string, SingleRole>(StringComparer.Ordinal);
                foreach (var s in role.SingleRoles) lookup[s.ChildAgr] = s;
                srLookups.Add(lookup);
                srSets.Add([.. lookup.Keys]);
                var codes = new Dictionary<string, TCode>(StringComparer.Ordinal);
                foreach (var s in role.SingleRoles) foreach (var t in s.Tcodes) codes.TryAdd(t.Code, t);
                tcLookups.Add(codes);
                tcSets.Add([.. codes.Keys]);
            }
            HashSet<string> Intersection(List<HashSet<string>> sets) { var all = new HashSet<string>(sets[0], StringComparer.Ordinal); foreach (var s in sets.Skip(1)) all.IntersectWith(s); return all; }
            List<object> Pairwise(List<HashSet<string>> sets)
            {
                var pairs = new List<object>();
                for (var i = 0; i < roles.Count; i++)
                    for (var j = i + 1; j < roles.Count; j++)
                        pairs.Add(new { role_a = roles[i].AgrName, role_b = roles[j].AgrName, shared_count = sets[i].Count(sets[j].Contains) });
                return pairs;
            }
            HashSet<string> Others(List<HashSet<string>> sets, int i) => sets.Where((_, j) => j != i).SelectMany(s => s).ToHashSet(StringComparer.Ordinal);

            var result = new Dictionary<string, object?>
            {
                ["analysis"] = new { module_source = "CSV FUNCTION_KEY", import_profile_id = "default", import_profile_version = 1, configuration_revision = 0 },
                ["roles"] = roles.Select((role, i) => new
                {
                    agr_name = role.AgrName, text = role.Text, function_key = role.FunctionKey, module_name = role.ModuleName, tcode_count = role.TcodeCount,
                    single_role_count = srSets[i].Count,
                    exclusive_single_roles = srSets[i].Except(Others(srSets, i)).Order(StringComparer.Ordinal).Select(c => SingleRoleInfo(srLookups[i][c])).ToList(),
                    unique_tcodes = tcSets[i].Except(Others(tcSets, i)).Order(StringComparer.Ordinal).Select(c => Tcode(tcLookups[i][c])).ToList(),
                }).ToList(),
                ["shared_single_roles"] = Intersection(srSets).Order(StringComparer.Ordinal).Select(c => SingleRoleInfo(srLookups[0][c])).ToList(),
                ["pairwise_single_overlaps"] = Pairwise(srSets),
                ["shared_tcodes"] = Intersection(tcSets).Order(StringComparer.Ordinal).Select(c => Tcode(tcLookups[0][c])).ToList(),
                ["pairwise_overlaps"] = Pairwise(tcSets),
            };
            return Results.Ok(result);
        });
    }
}
