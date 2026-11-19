using System.Text.Encodings.Web;
using System.Text.Json;
using System.Text.Json.Nodes;
using AuthLens.Domain.Analysis;
using AuthLens.Domain.Catalogue;
using AuthLens.Domain.Csv;
using AuthLens.Domain.Imports;
using AuthLens.Domain.Roles;
using AuthLens.Domain.Sod;
using AuthLens.Domain.Users;

namespace AuthLens.Cli;

/// <summary>Writes the neutral JSON of tools/python_reference.py from the .NET port, for tools/compare_equivalence.py.</summary>
public static class Equivalence
{
    public static readonly JsonSerializerOptions Json = new() { WriteIndented = true, Encoder = JavaScriptEncoder.UnsafeRelaxedJsonEscaping };

    public static (RoleCatalogue Catalogue, ImportReport Report) LoadCatalogue(string path)
    {
        var import = new CsvImport(path, new CsvProfile(), CsvSpec.Roles);
        var catalogue = CatalogueBuilder.Build(import.Records());
        return (catalogue, import.Report);
    }

    public static (UserDirectory Users, ImportReport Report) LoadUsers(string path, RoleCatalogue catalogue)
    {
        var import = new CsvImport(path, new CsvProfile(), CsvSpec.Users);
        return (UserDirectoryBuilder.Build(import.Records(), catalogue), import.Report);
    }

    public static SodDataset LoadSod(string path)
    {
        var import = new CsvImport(path, new CsvProfile(Id: "sod"), CsvSpec.Sod);
        var rows = import.Records().Select(r => (IReadOnlyDictionary<string, string>)CsvSpec.SodHeaders.ToDictionary(h => h, h => r[h])).ToList();
        var warnings = import.Report.Warnings.Where(w => !CsvSpec.SodOptional.Any(f => w == $"Optional field {f} is not mapped."));
        return SodSource.Build(rows, warnings);
    }

    public static List<IReadOnlyDictionary<string, string>> Records(string source, string path) => source switch
    {
        "roles" => new CsvImport(path, new CsvProfile(), CsvSpec.Roles).Records().Cast<IReadOnlyDictionary<string, string>>().ToList(),
        "users" => new CsvImport(path, new CsvProfile(), CsvSpec.Users).Records().Cast<IReadOnlyDictionary<string, string>>().ToList(),
        _ => LoadSod(path).Records.Select(r => (IReadOnlyDictionary<string, string>)r.ToDictionary(p => p.Key, p => (string)p.Value!)).ToList(),
    };

    public static int Run(string data, string scenariosPath, string malformedDir, string outPath, string dataset = "small")
    {
        var today = DateOnly.FromDateTime(DateTime.Now);
        var scenarios = JsonNode.Parse(File.ReadAllText(scenariosPath))!.AsObject();
        var watch = System.Diagnostics.Stopwatch.StartNew();
        var (catalogue, roleReport) = LoadCatalogue(Path.Combine(data, dataset, "roles.csv"));
        var catalogueMs = watch.Elapsed.TotalMilliseconds;
        watch.Restart();
        var (users, userReport) = LoadUsers(Path.Combine(data, dataset, "users.csv"), catalogue);
        var usersMs = watch.Elapsed.TotalMilliseconds;
        var sod = LoadSod(Path.Combine(data, dataset, "sod.csv"));
        var output = new Dictionary<string, object?>
        {
            ["implementation"] = "dotnet-v2", ["today"] = today.ToString("yyyy-MM-dd"),
            ["catalogue"] = CatalogueJson(catalogue, roleReport), ["users"] = UsersJson(users, userReport),
            ["sod_source"] = new Dictionary<string, object?> { ["content_hash"] = sod.ContentHash, ["warnings"] = sod.Warnings, ["risks"] = sod.Risks.Count },
            ["role_lookup"] = scenarios["role_lookup"]!.AsArray().Select(q => RoleLookup.Find(catalogue, RoleQuery(q!)).Select(RoleSummaryJson).ToList()).ToList(),
            ["user_lookup"] = scenarios["user_lookup"]!.AsArray().Select(q => UserLookup.Find(users, catalogue.Roles.Count > 0, UserQuery(q!), today).Select(UserSummaryJson).ToList()).ToList(),
        };
        var pairs = scenarios["comparison"]!.AsArray();
        output["comparison"] = pairs.Select(p => ComparisonJson(catalogue, users, p!, today)).ToList();
        output["comparison_listing"] = scenarios["comparison_listing"]!.AsArray().Select(spec =>
        {
            var pair = pairs[(int)spec!["pair"]!]!;
            var result = UserComparison.Compare(catalogue, users, (string)pair["user_a"]!, (string)pair["user_b"]!, (string)pair["validity"]!, today);
            var areas = spec["areas"]!.AsArray().Select(a => (string)a!).ToHashSet();
            var (difference, search, sort, descending) = ((string)spec["difference"]!, (string)spec["search"]!, (string)spec["sort"]!, (bool)spec["descending"]!);
            return (string)spec["kind"]! == "roles"
                ? UserComparison.Select(result.Roles, difference, areas, search, sort, descending, r => r.Identifier, r => r.Difference, r => r.Areas, r => r.Description, r => r.A.Count, r => r.B.Count).Select(r => r.Identifier).ToList()
                : UserComparison.Select(result.Transactions, difference, areas, search, sort, descending, r => r.Identifier, r => r.Difference, r => r.Areas, r => "", r => r.A.Count, r => r.B.Count).Select(r => r.Identifier).ToList();
        }).ToList();
        output["sod"] = scenarios["sod"]!.AsArray().Select(spec => SodJson(catalogue, users, sod, spec!, today)).ToList();
        output["import_checks"] = scenarios["import_checks"]!.AsArray().Select(spec =>
        {
            var source = (string)spec!["source"]!;
            var before = Records(source, Path.Combine(data, dataset, source + ".csv"));
            var after = Records(source, Path.Combine(data, ((string)spec["after"]!).Replace("small", dataset, StringComparison.Ordinal), source + ".csv"));
            var evaluation = ImportChecks.Evaluate(source, before, after, new ImportCheckSettings());
            var diff = ImportChecks.Diff(source, before, after);
            return new Dictionary<string, object?>
            {
                ["suspicious"] = evaluation.Suspicious, ["anomalies"] = evaluation.Anomalies.Select(a => a.Message).ToList(), ["old"] = evaluation.Old, ["new"] = evaluation.New,
                ["diff"] = new Dictionary<string, object?> { ["added"] = diff.Added, ["removed"] = diff.Removed, ["modified"] = diff.Modified, ["unchanged"] = diff.Unchanged, ["ambiguous"] = diff.AmbiguousIdentifiers },
            };
        }).ToList();
        output["malformed"] = Malformed(malformedDir);
        output["timings"] = new Dictionary<string, object?> { ["catalogue_ms"] = Math.Round(catalogueMs, 1), ["users_ms"] = Math.Round(usersMs, 1) };
        File.WriteAllText(outPath, JsonSerializer.Serialize(output, Json));
        Console.WriteLine($"wrote {outPath}");
        return 0;
    }

    private static List<string> L(JsonNode? node) => node?.AsArray().Select(v => (string)v!).ToList() ?? [];
    private static string S(JsonNode q, string key, string fallback = "") => q[key] is { } v ? (string)v! : fallback;

    private static RoleLookupQuery RoleQuery(JsonNode q) => new(q["search"] is { } s ? (string)s! : null, L(q["function_keys"]), q["function_key"] is { } f ? (string)f! : null,
        L(q["tcodes"]), S(q, "transaction_mode", "and"), q["exclude_matching"] is { } e && (bool)e, q["tcode"] is { } t ? (string)t! : null, L(q["exclude_tcodes"]), S(q, "exclude_mode", "any"));

    private static UserLookupQuery UserQuery(JsonNode q) => new(S(q, "search"), S(q, "group"), L(q["groups"]), S(q, "role"), L(q["roles"]), S(q, "tcode"), L(q["tcodes"]),
        S(q, "transaction_mode", "and"), q["exclude_transactions"] is { } x && (bool)x, L(q["exclude_tcodes"]), S(q, "exclude_mode", "any"), S(q, "status"),
        q["show_expired"] is { } e && (bool)e, S(q, "sort", "username"), q["descending"] is { } d && (bool)d);

    public static Dictionary<string, object?> RoleSummaryJson(RoleSummary r) => new()
    {
        ["agr_name"] = r.AgrName, ["text"] = r.Text, ["function_key"] = r.FunctionKey, ["module_name"] = r.ModuleName, ["tcode_count"] = r.TcodeCount,
        ["single_role_count"] = r.SingleRoleCount, ["matching_tcodes"] = r.MatchingTcodes,
    };

    public static Dictionary<string, object?> UserSummaryJson(UserSummary u) => new()
    {
        ["username"] = u.Username, ["user_key"] = u.UserKey, ["groups"] = u.Groups, ["first_name"] = u.FirstName, ["last_name"] = u.LastName, ["email"] = u.Email,
        ["account_status"] = u.AccountStatus, ["lock_status"] = u.LockStatus, ["relevant_roles"] = u.RelevantRoles,
    };

    private static object? Src(AssignmentSource s) => new List<string?> { s.ChildAgr, s.ParentAgr, s.EffectiveRole };

    private static Dictionary<string, object?> CatalogueJson(RoleCatalogue c, ImportReport report) => new()
    {
        ["roles"] = c.Ordered.Select(r => new Dictionary<string, object?>
        {
            ["agr_name"] = r.AgrName, ["text"] = r.Text, ["function_key"] = r.FunctionKey, ["module_name"] = r.ModuleName, ["tcode_count"] = r.TcodeCount,
            ["module_ambiguous"] = r.ModuleAmbiguous, ["source_modules"] = r.SourceModules, ["alternate_descriptions"] = r.AlternateDescriptions,
            ["relationships"] = r.Relationships.Select(Src).ToList(),
            ["single_roles"] = r.SingleRoles.Select(s => new Dictionary<string, object?>
            {
                ["child_agr"] = s.ChildAgr, ["assignment_kind"] = s.AssignmentKind, ["child_agr_text"] = s.ChildAgrText, ["alternate_descriptions"] = s.AlternateDescriptions,
                ["tcodes"] = s.Tcodes.Select(t => new Dictionary<string, object?> { ["tcode"] = t.Code, ["ttext"] = t.Text, ["alternate_texts"] = t.AlternateTexts, ["sources"] = t.AssignmentSources.Select(Src).ToList() }).ToList(),
            }).ToList(),
        }).ToList(),
        ["tcode_index"] = c.TcodeIndex.OrderBy(p => p.Key, StringComparer.Ordinal).ToDictionary(p => p.Key, p => p.Value.Order(StringComparer.Ordinal).ToList()),
        ["counts"] = new Dictionary<string, object?>
        {
            ["unique_roles"] = c.Ordered.Count, ["unique_transactions"] = c.UniqueTransactions, ["transaction_assignments"] = c.TransactionAssignments,
            ["relationship_count"] = c.RelationshipCount, ["parsed_rows"] = report.ParsedRows, ["unique_records"] = report.UniqueRecords, ["duplicate_rows"] = report.DuplicateRows,
        },
        ["warnings"] = report.Warnings.Concat(c.Warnings).Distinct().ToList(),
    };

    private static Dictionary<string, object?> Release(ReleaseRole? r) => r is null ? null! : r.Parsed
        ? new() { ["parsed"] = true, ["document_type"] = r.DocumentType, ["release_group"] = r.ReleaseGroup, ["release_strategy"] = r.ReleaseStrategy, ["opaque_scope"] = r.OpaqueScope, ["opaque_suffix"] = r.OpaqueSuffix }
        : new() { ["parsed"] = false, ["document_type"] = null, ["release_group"] = null, ["release_strategy"] = null };

    private static Dictionary<string, object?> UsersJson(UserDirectory u, ImportReport report) => new()
    {
        ["users"] = u.UserOrder.Select(key => u.Users[key]).Select(user => new Dictionary<string, object?>
        {
            ["key"] = RoleNames.NormalizeUsername(user.Username), ["username"] = user.Username, ["names"] = user.Names.Select(n => new List<string> { n.First, n.Last }).ToList(),
            ["emails"] = user.Emails, ["groups"] = user.Groups,
            ["accounts"] = user.Accounts.Select(a => new Dictionary<string, object?> { ["valid_from"] = a.ValidFrom, ["valid_to"] = a.ValidTo, ["locked"] = a.Locked, ["user_type"] = a.UserType, ["user_group"] = a.UserGroup }).ToList(),
            ["assignments"] = user.Assignments.Select(a => new Dictionary<string, object?>
            {
                ["id"] = a.Id, ["role_name"] = a.RoleName, ["user_group"] = a.UserGroup, ["scope"] = a.Scope, ["valid_from"] = a.ValidFrom, ["valid_to"] = a.ValidTo,
                ["user_valid_from"] = a.UserValidFrom, ["user_valid_to"] = a.UserValidTo, ["user_locked"] = a.UserLocked, ["user_type"] = a.UserType,
                ["match_status"] = a.MatchStatus, ["catalogue_roles"] = a.CatalogueRoles, ["tcodes"] = a.Tcodes, ["release"] = a.Release is null ? null : Release(a.Release),
            }).ToList(),
        }).ToList(),
        ["role_index"] = u.RoleIndex.OrderBy(p => p.Key, StringComparer.Ordinal).ToDictionary(p => p.Key, p => p.Value.Select(a => a.Id).ToList()),
        ["tcode_index"] = u.TcodeIndex.OrderBy(p => p.Key, StringComparer.Ordinal).ToDictionary(p => p.Key, p => p.Value),
        ["counts"] = new Dictionary<string, object?>
        {
            ["unique_users"] = u.Users.Count, ["assignments"] = u.Assignments.Count, ["relevant_assignments"] = u.RelevantAssignments, ["directory_only_users"] = u.DirectoryOnlyUsers,
            ["invalid_catalogue_patterns"] = u.InvalidCataloguePatterns, ["group_count"] = u.GroupCount, ["parsed_rows"] = report.ParsedRows,
            ["unique_records"] = report.UniqueRecords, ["duplicate_rows"] = report.DuplicateRows,
        },
        ["warnings"] = report.Warnings,
    };

    private static Dictionary<string, object?> ComparisonJson(RoleCatalogue catalogue, UserDirectory users, JsonNode pair, DateOnly today)
    {
        try
        {
            var result = UserComparison.Compare(catalogue, users, (string)pair["user_a"]!, (string)pair["user_b"]!, (string)pair["validity"]!, today);
            return new()
            {
                ["users"] = result.Users.Select(u => { var d = UserSummaryJson(u.Summary); d["identity_ambiguous"] = u.IdentityAmbiguous; return d; }).ToList(),
                ["roles"] = result.Roles.Select(r => new Dictionary<string, object?> { ["identifier"] = r.Identifier, ["a"] = r.A, ["b"] = r.B, ["areas"] = r.Areas, ["description"] = r.Description, ["difference"] = r.Difference }).ToList(),
                ["transactions"] = result.Transactions.Select(t => new Dictionary<string, object?> { ["identifier"] = t.Identifier, ["a"] = t.A.ToList(), ["b"] = t.B.ToList(), ["areas"] = t.Areas, ["difference"] = t.Difference }).ToList(),
            };
        }
        catch (Exception e) when (e is DomainValidationException or NotFoundException) { return new() { ["error"] = e.Message }; }
    }

    private static Dictionary<string, object?> SodJson(RoleCatalogue catalogue, UserDirectory users, SodDataset sod, JsonNode spec, DateOnly today)
    {
        try
        {
            var result = SodAnalyzer.Analyze(catalogue, users, sod, today, (string)spec["validity"]!, spec["selected_roles"] is { } s ? L(s) : null);
            static Dictionary<string, object?> F(SodFinding f) => new()
            {
                ["finding_id"] = f.FindingId, ["subject"] = f.Subject, ["kind"] = f.Kind, ["risk_id"] = f.RiskId, ["criticality"] = f.Criticality,
                ["current_potential"] = f.CurrentPotential, ["evidence_version"] = f.EvidenceVersion,
            };
            return new()
            {
                ["users"] = result.Users.Select(F).ToList(), ["roles"] = result.Roles.Select(F).ToList(),
                ["coverage"] = new Dictionary<string, object?> { ["eligible"] = result.EligibleAssignments, ["mapped"] = result.MappedAssignments, ["supported_risks"] = result.SupportedRisks, ["status"] = result.UsersAvailable ? "available" : "unavailable" },
                ["sod_content_hash"] = result.SodContentHash,
            };
        }
        catch (ArgumentException e) { return new() { ["error"] = e.Message }; }
    }

    private static SortedDictionary<string, object?> Malformed(string directory)
    {
        var cases = JsonSerializer.Deserialize<Dictionary<string, string>>(File.ReadAllText(Path.Combine(directory, "cases.json")))!;
        var result = new SortedDictionary<string, object?>(StringComparer.Ordinal);
        foreach (var (name, source) in cases)
        {
            var path = Path.Combine(directory, name + ".csv");
            try
            {
                if (source == "roles")
                {
                    var (catalogue, report) = LoadCatalogue(path);
                    result[name] = new Dictionary<string, object?> { ["ok"] = true, ["roles"] = catalogue.Ordered.Select(r => r.AgrName).ToList(), ["texts"] = catalogue.Ordered.Select(r => r.Text).ToList(),
                        ["warnings"] = report.Warnings.Concat(catalogue.Warnings).Distinct().ToList(), ["parsed_rows"] = report.ParsedRows };
                }
                else
                {
                    var (users, report) = LoadUsers(path, new RoleCatalogue());
                    result[name] = new Dictionary<string, object?> { ["ok"] = true, ["users"] = users.UserOrder, ["assignments"] = users.Assignments.Count, ["warnings"] = report.Warnings };
                }
            }
            catch (DomainValidationException e) { result[name] = new Dictionary<string, object?> { ["ok"] = false, ["error"] = e.Message }; }
            catch (Exception e) when (e is CsvFormatException or System.Text.DecoderFallbackException) { result[name] = new Dictionary<string, object?> { ["ok"] = false, ["error"] = "csv-format-error" }; }
        }
        return result;
    }
}
