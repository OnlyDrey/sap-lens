using System.Reflection;
using System.Runtime.InteropServices;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;

namespace AuthLens.Api;

/// <summary>Product version and build identity of AuthLens (.NET), read from this assembly's attributes, which Directory.Build.props derives from
/// backend/product-version.json (the only source). Version (2.0.0-alpha.1) is the product version; Commit is build identity (set by the
/// release scripts through SourceRevisionId, null for a local build without it). Desktop and Server share this class, so they cannot disagree.</summary>
public static partial class ProductIdentity
{
    public const string Product = "AuthLens";
    private static readonly Assembly Assembly = typeof(ProductIdentity).Assembly;
    private static readonly string Informational = Assembly.GetCustomAttribute<AssemblyInformationalVersionAttribute>()?.InformationalVersion ?? "0.0.0";
    /// <summary>MAJOR.MINOR.PATCH[-alpha.N|-beta.N|-rc.N], without build metadata.</summary>
    public static readonly string Version = Informational.Split('+')[0];
    /// <summary>The source commit (full SHA) the release scripts stamped, or null.</summary>
    public static readonly string? Commit = Informational.Contains('+') ? Informational[(Informational.IndexOf('+') + 1)..] : null;
    /// <summary>Windows file version: MAJOR, MINOR, PATCH and the pre-release number (0 for a stable release), the v1 contract.</summary>
    public static readonly int[] FileVersion = [.. (Assembly.GetCustomAttribute<AssemblyFileVersionAttribute>()?.Version ?? "0.0.0.0").Split('.').Select(int.Parse)];

    [GeneratedRegex(@"^\d+\.\d+\.\d+-(alpha|beta|rc)\.\d+$")]
    private static partial Regex PrereleasePattern();

    /// <summary>alpha, beta, rc or stable.</summary>
    public static string Channel => PrereleasePattern().Match(Version) is { Success: true } match ? match.Groups[1].Value : "stable";

    public static string Platform => RuntimeInformation.RuntimeIdentifier;

    /// <summary>The --version text: one stable first line ("AuthLens server 2.0.0-alpha.1"), then the identity details. No secrets, no paths.</summary>
    public static string Describe(string component) => string.Join(Environment.NewLine,
        $"{Product} {component} {Version}",
        $"Channel: {(Channel == "stable" ? "stable release" : Channel + " pre-release")}",
        $"Commit: {Commit ?? "not recorded (local build)"}",
        $"File version: {string.Join('.', FileVersion)}",
        $"Runtime: .NET {Environment.Version} ({Platform})");

    /// <summary>Machine-readable identity, served at /product-version.json and in /api/application-info.</summary>
    public static JsonObject ToJson() => new()
    {
        ["product"] = Product, ["version"] = Version, ["base_version"] = Version.Split('-')[0], ["channel"] = Channel,
        ["file_version"] = new JsonArray([.. FileVersion.Select(n => (JsonNode?)n)]), ["source_sha"] = Commit, ["mode"] = "dotnet",
    };
}
