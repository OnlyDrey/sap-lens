namespace AuthLens.Domain.Catalogue;

/// <summary>Port of module_registry.py: stable SAP area identifiers, names and aliases (resolve_module / module_definition).</summary>
public static class ModuleRegistry
{
    private static readonly (string Id, string Name, string[] Aliases)[] Rows =
    [
        ("FI","Financial Accounting",["Finance"]),("FI-AA","Asset Accounting",[]),("FI-AP","Accounts Payable",[]),("FI-AR","Accounts Receivable",[]),
        ("CO","Controlling",[]),("CO-PA","Profitability Analysis",[]),("TRM","Treasury and Risk Management",[]),("FSCM","Financial Supply Chain Management",[]),
        ("BPC","SAP Business Planning and Consolidation",[]),("MM","Materials Management",[]),("MM-PUR","Purchasing",[]),("MM-IM","Inventory Management",[]),
        ("SD","Sales and Distribution",[]),("LE","Logistics Execution",[]),("LE-TRA","Transportation",[]),("WM","Warehouse Management",[]),
        ("EWM","Extended Warehouse Management",[]),("TM","Transportation Management",[]),("SCM","SAP Supply Chain Management",[]),
        ("APO","Advanced Planning and Optimization",[]),("SRM","SAP Supplier Relationship Management",[]),("PP","Production Planning and Control",[]),
        ("PP-PI","Production Planning for Process Industries",[]),("PM","Plant Maintenance",[]),("QM","Quality Management",[]),
        ("PLM","Product Lifecycle Management",[]),("EHS","Environment, Health and Safety",[]),("EHSM","Environment, Health and Safety Management",[]),
        ("PS","Project System",[]),("RE-FX","Flexible Real Estate Management",[]),("PSM","Public Sector Management",[]),("CS","Customer Service",[]),
        ("CRM","SAP Customer Relationship Management",[]),("HCM","Human Capital Management",["SAP HCM"]),("HR","Human Resources",[]),
        ("PA","Personnel Administration",[]),("OM","Organizational Management",[]),("PY","Payroll",[]),("CA","Cross-Application Components",[]),
        ("BC","Basis Components",["BASIS"]),("ABAP","ABAP Platform",[]),("BW","SAP Business Warehouse",[]),("BI","Business Intelligence",[]),
        ("GRC","Governance, Risk and Compliance",[]),("MDG","SAP Master Data Governance",[]),("DMS","Document Management",[]),
        ("BTP","SAP Business Technology Platform",[]),("IS-U","SAP Utilities",["Utilities"]),("UNCLASSIFIED","Unclassified",[]),
    ];

    private static readonly Dictionary<string, string> Lookup = Rows.SelectMany(r => new[] { r.Id }.Concat(r.Aliases).Select(a => (Key: Normalize(a), r.Id)))
        .ToDictionary(x => x.Key, x => x.Id, StringComparer.Ordinal);
    private static readonly Dictionary<string, string> Names = Rows.ToDictionary(r => r.Id, r => r.Name, StringComparer.Ordinal);

    public static string Normalize(string? value) => (value ?? "").Trim().PyUpper().Replace('_', '-').Replace(" ", "", StringComparison.Ordinal);
    public static string? Resolve(string? value) => Lookup.GetValueOrDefault(Normalize(value));
    public static string Name(string id) => Names.GetValueOrDefault(id, id);
}
