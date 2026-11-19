using AuthLens.Api;

namespace AuthLens.Tests;

/// <summary>The Desktop data folder: AuthLens uses only %LOCALAPPDATA%\AuthLens; folders of earlier products are reported, never used or changed.</summary>
public sealed class DesktopLocationTests : IDisposable
{
    private readonly string _root = Directory.CreateTempSubdirectory("authlens-desktop-location-").FullName;

    public void Dispose() => Directory.Delete(_root, recursive: true);

    [Fact]
    public void AuthLens_uses_its_own_folder_and_mutex()
    {
        var location = DesktopLocation.Resolve(_root);
        Assert.Equal((Path.Combine(_root, "AuthLens"), @"Local\AuthLensDesktop"), (location.Root, location.Mutex));
        Assert.Empty(location.EarlierProductData);
        Assert.False(Directory.Exists(location.Root));                                         // resolving creates nothing
    }

    [Fact]
    public void Earlier_product_folders_are_reported_and_never_used()
    {
        foreach (var folder in new[] { "SAP Lens Desktop", "SAP Lens 2 Prototype", "SAP Lens" }) Directory.CreateDirectory(Path.Combine(_root, folder, "data"));
        var location = DesktopLocation.Resolve(_root);
        Assert.Equal(Path.Combine(_root, "AuthLens"), location.Root);
        Assert.Equal(3, location.EarlierProductData.Length);
        Assert.Equal(["data"], Directory.GetDirectories(Path.Combine(_root, "SAP Lens Desktop")).Select(Path.GetFileName));   // unchanged
    }
}
