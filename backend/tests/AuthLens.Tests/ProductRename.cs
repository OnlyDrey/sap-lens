using System.Text.RegularExpressions;

namespace AuthLens.Tests;

/// <summary>SAP Lens 1's reference output names the product in report text, footers, metadata and the configuration export format. AuthLens
/// renders its own name in exactly those places; nothing else changes. Equivalence tests apply this rename to the v1 reference text, never to the
/// AuthLens output, and leave historical names ("SAP Lens 1", "SAP Lens 2", key-derivation labels) as they are.</summary>
internal static partial class ProductRename
{
    [GeneratedRegex(@"SAP Lens(?! (?:1|2|v1)\b)(?! portable archive)")] private static partial Regex Name();

    public static string Apply(string v1Text) => Name().Replace(v1Text, "AuthLens");
}
