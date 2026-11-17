using SapLens.Api;

namespace SapLens.Tests;

/// <summary>The Desktop data folder: new installations get their own folder, an earlier prototype folder is kept in place, v1's folder is never used.</summary>
public sealed class DesktopLocationTests : IDisposable
{
    private readonly string _root = Directory.CreateTempSubdirectory("saplens-desktop-location-").FullName;

    public void Dispose() => Directory.Delete(_root, recursive: true);

    [Fact]
    public void A_new_installation_uses_its_own_folder_and_never_the_v1_folder()
    {
        Directory.CreateDirectory(Path.Combine(_root, DesktopLocation.V1FolderName));
        var location = DesktopLocation.Resolve(_root);
        Assert.Equal((Path.Combine(_root, "SAP Lens Desktop"), @"Local\SapLensDotnetDesktop", false), (location.Root, location.Mutex, location.Legacy));
    }

    [Fact]
    public void An_earlier_prototype_folder_is_kept_in_place_with_its_mutex()
    {
        Directory.CreateDirectory(Path.Combine(_root, "SAP Lens 2 Prototype", "data"));
        var location = DesktopLocation.Resolve(_root);
        Assert.Equal((Path.Combine(_root, "SAP Lens 2 Prototype"), @"Local\SapLens2Prototype", true), (location.Root, location.Mutex, location.Legacy));
        Assert.False(Directory.Exists(Path.Combine(_root, DesktopLocation.FolderName)));   // nothing is moved or created
    }

    [Fact]
    public void The_current_folder_wins_when_both_exist()
    {
        Directory.CreateDirectory(Path.Combine(_root, DesktopLocation.LegacyFolderName));
        Directory.CreateDirectory(Path.Combine(_root, DesktopLocation.FolderName));
        Assert.False(DesktopLocation.Resolve(_root).Legacy);
    }
}
