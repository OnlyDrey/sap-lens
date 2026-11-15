using Microsoft.Extensions.FileProviders;

namespace SapLens.Api;

/// <summary>The prototype UI is embedded in this assembly (see SapLens.Api.csproj). A build without its assets fails at startup with a clear message
/// instead of serving 404 for "/".</summary>
public static class UiAssets
{
    public const string Marker = "prototype-ui-v1";
    public static readonly string[] Required = ["index.html", "app.js", "app.css", "login.html"];

    public static IFileProvider Create()
    {
        var provider = new ManifestEmbeddedFileProvider(typeof(UiAssets).Assembly, "wwwroot");
        var missing = Required.Where(name => !provider.GetFileInfo(name).Exists).ToList();
        if (missing.Count > 0) throw new InvalidOperationException($"The prototype UI is incomplete in this build (missing {string.Join(", ", missing)}).");
        return provider;
    }
}
