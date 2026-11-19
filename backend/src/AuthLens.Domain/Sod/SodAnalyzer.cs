using AuthLens.Domain.Catalogue;
using AuthLens.Domain.Json;
using AuthLens.Domain.Roles;
using AuthLens.Domain.Users;

namespace AuthLens.Domain.Sod;

public sealed class SodFinding
{
    public required string FindingId { get; init; }
    public required object Subject { get; init; }
    public required string Kind { get; init; }
    public required string RiskId { get; init; }
    public required string Criticality { get; init; }
    public required Dictionary<string, object?> Evidence { get; init; }
    public bool CurrentPotential { get; init; }
    public Dictionary<string, object?>? Account { get; init; }
    public required string EvidenceVersion { get; init; }
}

public sealed class SodResult
{
    public required List<SodFinding> Users { get; init; }
    public required List<SodFinding> Roles { get; init; }
    public int EligibleAssignments { get; init; }
    public int MappedAssignments { get; init; }
    public int SupportedRisks { get; init; }
    public bool UsersAvailable { get; init; }
    public string? SodContentHash { get; init; }
    public string Validity { get; init; } = "active";
    public string AsOf { get; init; } = "";
}

/// <summary>Port of sod_analysis.analyze (directory matching disabled): potential, transaction-derived SoD findings with stable finding identity
/// and evidence versions. Byte-identical canonical JSON makes the identities equal to the Python ones.</summary>
public static class SodAnalyzer
{
    public static SodResult Analyze(RoleCatalogue catalogue, UserDirectory users, SodDataset? sod, DateOnly asOf, string validity = "active",
        IReadOnlyCollection<string>? selectedRoles = null, IReadOnlyDictionary<string, bool>? riskEnabled = null,
        Directory.EmployeeDirectory? directory = null, bool directoryEnabled = false)
    {
        if (validity is not ("active" or "expired" or "future" or "unknown" or "all")) throw new ArgumentException("Unsupported assignment validity filter.");
        var risks = new Dictionary<string, Dictionary<string, object?>>(StringComparer.Ordinal);
        var index = new Dictionary<string, List<(string RiskId, string Slot, string Activity, string Tcode)>>(StringComparer.Ordinal);
        foreach (var risk in sod?.Risks ?? [])
        {
            var id = (string)risk["risk_id"]!;
            if (riskEnabled?.GetValueOrDefault(id, true) == false || !(bool)risk["supported"]! || (string?)risk["evaluation_policy"] != SodSource.EvaluationPolicy) continue;
            risks[id] = risk;
            foreach (var (slot, mappings) in (Dictionary<string, object?>)risk["activities"]!)
                foreach (var item in (List<object?>)mappings!)
                {
                    var mapping = (Dictionary<string, object?>)item!;
                    var code = ((string)mapping["tcode"]!).PyUpper();
                    if (!index.TryGetValue(code, out var list)) index[code] = list = [];
                    list.Add((id, slot, (string)mapping["activity"]!, (string)mapping["tcode"]!));
                }
        }
        var cataloguePaths = catalogue.Roles.ToDictionary(p => p.Key, p => Paths(p.Value, p.Key).ToList(), StringComparer.Ordinal);

        Dictionary<string, Dictionary<string, object?>> Group(IEnumerable<Dictionary<string, object?>> paths)
        {
            var grouped = new Dictionary<string, Dictionary<string, List<Dictionary<string, object?>>>>(StringComparer.Ordinal);
            foreach (var path in paths)
                foreach (var (riskId, slot, activity, matrixTransaction) in index.GetValueOrDefault(((string)path["tcode"]!).PyUpper()) ?? [])
                {
                    if (!grouped.TryGetValue(riskId, out var sides)) grouped[riskId] = sides = new() { ["ACTVT1"] = [], ["ACTVT2"] = [] };
                    sides[slot].Add(new Dictionary<string, object?>(path) { ["activity_slot"] = slot, ["activity"] = activity, ["matrix_transaction"] = matrixTransaction });
                }
            return grouped.Where(g => g.Value.Values.All(v => v.Count > 0))
                .ToDictionary(g => g.Key, g => g.Value.ToDictionary(s => s.Key, s => (object?)CanonicalJson.Unique(s.Value).Cast<object?>().ToList()), StringComparer.Ordinal);
        }

        List<SodFinding> Findings(object subject, string kind, IEnumerable<Dictionary<string, object?>> paths, Dictionary<string, object?>? account = null)
        {
            var result = new List<SodFinding>();
            foreach (var (riskId, evidence) in Group(paths).OrderBy(p => p.Key, StringComparer.Ordinal))
            {
                var current = kind == "user" && evidence.Values.All(items => ((List<object?>)items!).Any(i => (string?)((Dictionary<string, object?>)i!)["interval_status"] == "active"));
                result.Add(new SodFinding
                {
                    FindingId = CanonicalJson.Sha256(new List<object?> { 1, kind, subject, riskId, SodSource.EvaluationPolicy }),
                    Subject = subject, Kind = kind, RiskId = riskId, Criticality = (string)risks[riskId]["criticality"]!, Evidence = evidence,
                    CurrentPotential = current, Account = account,
                    EvidenceVersion = CanonicalJson.Sha256(new List<object?> { risks[riskId], evidence, account }),
                });
            }
            return result;
        }

        var roleResults = new List<SodFinding>();
        foreach (var name in cataloguePaths.Keys.Order(StringComparer.Ordinal)) roleResults.AddRange(Findings(name, "role", cataloguePaths[name]));
        if (selectedRoles is not null)
        {
            if (selectedRoles.Count > 25) throw new ArgumentException("Select at most 25 existing catalogue roles.");
            var selected = selectedRoles.Distinct().Order(StringComparer.Ordinal).ToList();
            if (selected.Any(n => !cataloguePaths.ContainsKey(n))) throw new ArgumentException("A selected catalogue role is unavailable in the current dataset.");
            if (selected.Count > 1) roleResults.AddRange(Findings(selected.Cast<object?>().ToList(), "role_combination", selected.SelectMany(n => cataloguePaths[n])));
        }
        var available = users.Users.Count > 0 && catalogue.Roles.Count > 0 && sod is not null;
        var userResults = new List<SodFinding>();
        int eligible = 0, mapped = 0;
        // v1: the directory is used only when the Employee Directory feature is on; an enabled feature without a directory reads as unavailable.
        var owners = directoryEnabled && directory is not null ? Directory.EmployeeDirectory.SapEmailOwners(users.Users.Values) : null;
        if (available)
        {
            foreach (var key in users.Users.Keys.Order(StringComparer.Ordinal))
            {
                var user = users.Users[key];
                var match = owners is not null ? directory!.MatchSapIdentity(user, owners)
                    : (Status: directoryEnabled ? "directory_unavailable" : "directory_disabled", Employee: (Dictionary<string, object?>?)null);
                var paths = new List<Dictionary<string, object?>>();
                foreach (var assignment in user.Assignments)
                {
                    var status = SapDates.IntervalStatus(assignment.ValidFrom, assignment.ValidTo, asOf);
                    if (validity != "all" && status != validity) continue;
                    eligible++;
                    if (!assignment.Resolved) continue;
                    var assignmentPaths = assignment.CatalogueRoles.SelectMany(n => cataloguePaths.GetValueOrDefault(n) ?? []).ToList();
                    if (assignmentPaths.Count > 0) mapped++;
                    foreach (var path in assignmentPaths)
                        paths.Add(new Dictionary<string, object?>(path)
                        {
                            ["actual_assigned_role"] = assignment.RoleName, ["matching_status"] = assignment.MatchStatus, ["role_valid_from"] = assignment.ValidFrom,
                            ["role_valid_to"] = assignment.ValidTo, ["interval_status"] = status, ["user_group"] = assignment.UserGroup,
                        });
                }
                var account = new Dictionary<string, object?>
                {
                    ["accounts"] = CanonicalJson.Unique(user.Accounts.Select(a => (object?)new Dictionary<string, object?>
                    {
                        ["valid_from"] = a.ValidFrom, ["valid_to"] = a.ValidTo, ["locked"] = a.Locked, ["user_type"] = a.UserType, ["user_group"] = a.UserGroup,
                    })),
                    ["directory_match"] = match.Status, ["ad_status"] = match.Employee is { } employee ? employee["account_status"] : "Unknown",
                };
                userResults.AddRange(Findings(RoleNames.NormalizeUsername(key), "user", paths, account));
            }
        }
        return new SodResult
        {
            Users = userResults, Roles = roleResults, EligibleAssignments = eligible, MappedAssignments = mapped, SupportedRisks = risks.Count,
            UsersAvailable = available, SodContentHash = sod?.ContentHash, Validity = validity, AsOf = asOf.ToString("yyyy-MM-dd"),
        };
    }

    private static IEnumerable<Dictionary<string, object?>> Paths(Role role, string pattern)
    {
        foreach (var single in role.SingleRoles)
            foreach (var code in single.Tcodes)
                yield return new Dictionary<string, object?>
                {
                    ["matched_catalogue_pattern"] = pattern, ["single_role"] = single.ChildAgr, ["assignment_kind"] = single.AssignmentKind, ["tcode"] = code.Code,
                    ["source_provenance"] = CanonicalJson.Unique(code.AssignmentSources.Select(s => (object?)new Dictionary<string, object?>
                    {
                        ["child_agr"] = s.ChildAgr, ["parent_agr"] = s.ParentAgr, ["effective_role"] = s.EffectiveRole,
                    })),
                };
    }
}
