using AuthLens.Domain.Json;

namespace AuthLens.Domain.Sod;

/// <summary>v1 sod_catalogue.definition_version: SHA-256 of json.dumps(definition, sort_keys=True, ensure_ascii=False, separators=(',', ':')).
/// Local annotations record the fingerprint they observed and reviewed; it must stay byte-identical so migrated annotations keep their status.</summary>
public static class SodCatalogueFingerprint
{
    public static string Of(IReadOnlyDictionary<string, object?> definition) => CanonicalJson.Sha256(definition);
}
