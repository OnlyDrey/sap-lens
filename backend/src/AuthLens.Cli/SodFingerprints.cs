using AuthLens.Application;
using AuthLens.Domain.Json;
using AuthLens.Domain.Sod;

namespace AuthLens.Cli;

/// <summary>Equivalence probe for the SoD source: runs the same read and build path as an import and writes the content hash, the imported
/// optional metadata, the warnings and every risk definition fingerprint (v1 sod_catalogue.definition_version).</summary>
public static class SodFingerprints
{
    public static int Run(string csv, string output)
    {
        var (records, report) = Sources.Read(Sources.Sod, csv, CancellationToken.None);
        var materialized = records.ToList();
        var dataset = SodSource.Build(materialized, report.Warnings.Where(w => !w.StartsWith("Optional field ", StringComparison.Ordinal)));
        var result = new Dictionary<string, object?>
        {
            ["content_hash"] = dataset.ContentHash,
            ["metadata"] = dataset.Metadata?.ToJson(),
            ["warnings"] = dataset.Warnings,
            ["definition_versions"] = dataset.Risks.ToDictionary(r => (string)r["risk_id"]!, r => (object?)SodCatalogueFingerprint.Of(r)),
        };
        File.WriteAllText(output, CanonicalJson.Serialize(result));
        return 0;
    }
}
