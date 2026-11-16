using Microsoft.Extensions.FileProviders;

namespace SapLens.Api;

/// <summary>The production React UI (frontend/dist) and the server sign-in page are embedded in this assembly (see SapLens.Api.csproj). A build without
/// them fails at startup with a clear message instead of serving 404 for "/".</summary>
public static class UiAssets
{
    /// <summary>The React mount point in frontend/index.html: proves "/" is the SAP Lens application, not an error page.</summary>
    public const string Marker = "<div id=\"root\">";
    public static readonly string[] Required = ["index.html", "theme.js", "sap-lens.png", "login.html", "login.css"];

    public static IFileProvider Create() => Validate(new ManifestEmbeddedFileProvider(typeof(UiAssets).Assembly, "wwwroot"));

    /// <summary>Refuses a provider that lacks any required file, naming every missing one.</summary>
    internal static IFileProvider Validate(IFileProvider provider)
    {
        var missing = Required.Where(name => !provider.GetFileInfo(name).Exists).ToList();
        if (missing.Count > 0) throw new InvalidOperationException($"The user interface is incomplete in this build (missing {string.Join(", ", missing)}); rebuild with -p:BuildFrontend=true.");
        return provider;
    }
}
