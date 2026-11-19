namespace AuthLens.Domain.Catalogue;

public sealed record AssignmentSource(string? ChildAgr, string? ParentAgr, string? EffectiveRole);

public sealed class TCode
{
    public required string Code { get; init; }
    public string? Text { get; set; }
    public List<AssignmentSource> AssignmentSources { get; } = [];
    public List<string> AlternateTexts { get; } = [];
}

public sealed class SingleRole
{
    public required string AssignmentKind { get; init; }
    public required string ChildAgr { get; init; }
    public string? ChildAgrText { get; init; }
    public required List<TCode> Tcodes { get; init; }
    public string FunctionKey { get; init; } = "UNCLASSIFIED";
    public string ModuleName { get; init; } = "Unclassified";
    public List<string> AlternateDescriptions { get; init; } = [];
}

public sealed class Role
{
    public required string AgrName { get; init; }
    public string? Text { get; init; }
    public required string FunctionKey { get; init; }
    public required string ModuleName { get; init; }
    public int TcodeCount { get; init; }
    public required List<SingleRole> SingleRoles { get; init; }
    public required List<AssignmentSource> Relationships { get; init; }
    public List<string> AlternateDescriptions { get; init; } = [];
    public bool ModuleAmbiguous { get; init; }
    public List<string> SourceModules { get; init; } = [];
}

public sealed class RoleCatalogue
{
    public List<Role> Ordered { get; } = [];
    public Dictionary<string, Role> Roles { get; } = new(StringComparer.Ordinal);
    /// <summary>Upper-cased T-code to the roles that hold it (port of tcode_index).</summary>
    public Dictionary<string, HashSet<string>> TcodeIndex { get; } = new(StringComparer.Ordinal);
    public List<string> Warnings { get; } = [];
    public int UniqueTransactions { get; set; }
    public int TransactionAssignments { get; set; }
    public int RelationshipCount { get; set; }
}

/// <summary>Port of cache._build_catalog for the roles CSV: composite roles, single roles, transactions with source provenance, relationships,
/// SAP area resolution and the transaction index. No area is inferred from names or descriptions.</summary>
public static class CatalogueBuilder
{
    private sealed class SingleDraft
    {
        public string? Text; public readonly HashSet<string> Texts = new(StringComparer.Ordinal);
        public readonly List<TCode> Tcodes = []; public readonly Dictionary<string, TCode> ByCode = new(StringComparer.Ordinal);
        public readonly HashSet<string> Kinds = new(StringComparer.Ordinal);
    }

    private sealed class RoleDraft
    {
        public string? Text; public readonly List<string> Modules = [];
        public readonly List<string> SingleOrder = []; public readonly Dictionary<string, SingleDraft> Singles = new(StringComparer.Ordinal);
        public readonly HashSet<(string, string, string)> Relationships = []; public readonly HashSet<string> Texts = new(StringComparer.Ordinal);
    }

    /// <param name="moduleName">Display name per module id (v1 module_definition with the saved module_overrides); the registry name by default.</param>
    public static RoleCatalogue Build(IEnumerable<IReadOnlyDictionary<string, string>> records, Func<string, string>? moduleName = null)
    {
        moduleName ??= ModuleRegistry.Name;
        var order = new List<string>();
        var raw = new Dictionary<string, RoleDraft>(StringComparer.Ordinal);
        var assignments = new HashSet<string>(StringComparer.Ordinal);
        var warnings = new List<string>();
        foreach (var row in records)
        {
            var name = row["AGR_NAME"];
            if (!raw.TryGetValue(name, out var data)) { raw[name] = data = new RoleDraft { Text = Null(row["TEXT"]) }; order.Add(name); }
            if (row["FUNCTION_KEY"].Length > 0 && !data.Modules.Contains(row["FUNCTION_KEY"])) data.Modules.Add(row["FUNCTION_KEY"]);
            if (row["TEXT"].Length > 0) data.Texts.Add(row["TEXT"]);
            if (row["TEXT"].Length > 0 && data.Text is null) data.Text = row["TEXT"];
            data.Relationships.Add((row["CHILD_AGR"], row["PARENT_AGR"], row["Effective_Role"]));
            var child = row["CHILD_AGR"].Length > 0 ? row["CHILD_AGR"] : row["Effective_Role"].Length > 0 ? row["Effective_Role"] : row["TCODE"].Length > 0 ? name : "";
            if (child.Length == 0) continue;
            if (!data.Singles.TryGetValue(child, out var single)) { data.Singles[child] = single = new SingleDraft { Text = Null(row["CHILD_AGR_TEXT"]) }; data.SingleOrder.Add(child); }
            single.Kinds.Add(row["CHILD_AGR"].Length > 0 ? "child" : row["Effective_Role"].Length > 0 ? "effective" : "direct");
            if (row["CHILD_AGR_TEXT"].Length > 0) single.Texts.Add(row["CHILD_AGR_TEXT"]);
            if (single.Text is null && row["CHILD_AGR_TEXT"].Length > 0) single.Text = row["CHILD_AGR_TEXT"];
            if (row["TCODE"].Length == 0) continue;
            if (row["CHILD_AGR"].Length == 0 && row["Effective_Role"].Length == 0)
                warnings.Add("Transactions without CHILD_AGR/Effective_Role are retained as direct composite assignments.");
            var source = new AssignmentSource(Null(row["CHILD_AGR"]), Null(row["PARENT_AGR"]), Null(row["Effective_Role"]));
            if (!single.ByCode.TryGetValue(row["TCODE"], out var tc)) { single.ByCode[row["TCODE"]] = tc = new TCode { Code = row["TCODE"], Text = Null(row["TTEXT"]) }; single.Tcodes.Add(tc); }
            if (tc.Text is null && row["TTEXT"].Length > 0) tc.Text = row["TTEXT"];
            if (row["TTEXT"].Length > 0 && row["TTEXT"] != tc.Text && !tc.AlternateTexts.Contains(row["TTEXT"]))
            {
                tc.AlternateTexts.Add(row["TTEXT"]);
                warnings.Add("Conflicting transaction descriptions are retained as alternate texts.");
            }
            if (!tc.AssignmentSources.Contains(source)) tc.AssignmentSources.Add(source);
            assignments.Add(string.Join('\u001f', name, row["CHILD_AGR"], row["PARENT_AGR"], row["Effective_Role"], row["TCODE"]));
        }
        var catalogue = new RoleCatalogue();
        var transactionCodes = new HashSet<string>(StringComparer.Ordinal);
        foreach (var name in order)
        {
            var data = raw[name];
            var normalized = data.Modules.Select(m => ModuleRegistry.Resolve(m) ?? "UNCLASSIFIED").ToHashSet(StringComparer.Ordinal);
            var moduleId = normalized.Count == 1 ? normalized.First() : "UNCLASSIFIED";
            var ambiguous = data.Modules.Distinct().Count() > 1 && normalized.Count > 1;
            if (ambiguous) warnings.Add("Some roles have conflicting CSV SAP areas; shown as Unclassified.");
            var singles = data.SingleOrder.Select(child => data.Singles[child]).Zip(data.SingleOrder, (s, child) => new SingleRole
            {
                AssignmentKind = s.Kinds.Count == 1 ? s.Kinds.First() : "mixed", ChildAgr = child, ChildAgrText = s.Text, Tcodes = s.Tcodes,
                AlternateDescriptions = s.Texts.Where(t => t != s.Text).Order(StringComparer.Ordinal).ToList(),
            }).ToList();
            var codes = singles.SelectMany(s => s.Tcodes).Select(t => t.Code).ToHashSet(StringComparer.Ordinal);
            var relationships = data.Relationships.OrderBy(r => r.Item1, StringComparer.Ordinal).ThenBy(r => r.Item2, StringComparer.Ordinal).ThenBy(r => r.Item3, StringComparer.Ordinal)
                .Select(r => new AssignmentSource(Null(r.Item1), Null(r.Item2), Null(r.Item3))).ToList();
            var role = new Role
            {
                AgrName = name, Text = data.Text, FunctionKey = moduleId, ModuleName = moduleName(moduleId), TcodeCount = codes.Count, SingleRoles = singles,
                Relationships = relationships, ModuleAmbiguous = ambiguous, SourceModules = data.Modules,
                AlternateDescriptions = data.Texts.Where(t => t != data.Text).Order(StringComparer.Ordinal).ToList(),
            };
            catalogue.Ordered.Add(role);
            catalogue.Roles[name] = role;
            foreach (var code in codes)
            {
                transactionCodes.Add(code);
                var key = code.PyUpper();
                if (!catalogue.TcodeIndex.TryGetValue(key, out var holders)) catalogue.TcodeIndex[key] = holders = new HashSet<string>(StringComparer.Ordinal);
                holders.Add(name);
            }
        }
        if (catalogue.Ordered.Any(r => r.AlternateDescriptions.Count > 0 || r.SingleRoles.Any(s => s.AlternateDescriptions.Count > 0)))
            warnings.Add("Conflicting role descriptions are retained as alternate descriptions.");
        catalogue.Warnings.AddRange(warnings.Distinct());
        catalogue.UniqueTransactions = transactionCodes.Count;
        catalogue.TransactionAssignments = assignments.Count;
        catalogue.RelationshipCount = catalogue.Ordered.Sum(r => r.Relationships.Count);
        return catalogue;
    }

    private static string? Null(string value) => value.Length > 0 ? value : null;
}
