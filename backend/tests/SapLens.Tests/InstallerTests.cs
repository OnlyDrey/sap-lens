using System.Text.RegularExpressions;
using SapLens.Api;

namespace SapLens.Tests;

/// <summary>Static checks of the Inno Setup installers (installer/*.iss). They are compiled and accepted on Windows only (scripts/build-installers.ps1,
/// WINDOWS_DEPLOYMENT.md); these checks keep their identity, icon, privileges, file layout and data-preservation rules from drifting.</summary>
public sealed partial class InstallerTests
{
    private static readonly string Repo = FindRepo();
    private static readonly string Desktop = File.ReadAllText(Path.Combine(Repo, "backend", "installer", "SapLens-Desktop.iss"));
    private static readonly string Server = File.ReadAllText(Path.Combine(Repo, "backend", "installer", "SapLens-Server.iss"));

    private static string FindRepo()
    {
        var dir = new DirectoryInfo(AppContext.BaseDirectory);
        while (dir is not null && !File.Exists(Path.Combine(dir.FullName, "backend", "SapLens.slnx"))) dir = dir.Parent;
        return dir!.FullName;
    }

    private static string Setting(string script, string key) => Regex.Match(script, $@"^{key}=(.*)$", RegexOptions.Multiline).Groups[1].Value.Trim();
    private static string Define(string script, string name) => Regex.Match(script, $@"^#define {name} ""([^""]*)""", RegexOptions.Multiline).Groups[1].Value;

    [GeneratedRegex(@"^\[(UninstallDelete|InstallDelete)\]", RegexOptions.Multiline)] private static partial Regex DeleteSection();
    [GeneratedRegex(@"\b(DelTree|DeleteFile|RemoveDir|taskkill|Stop-Process|TerminateProcess)\b", RegexOptions.IgnoreCase)] private static partial Regex Destructive();

    [Fact]
    public void Each_installer_has_its_own_identity_distinct_from_sap_lens_v1()
    {
        var v1 = Define(File.ReadAllText(Path.Combine(Repo, "legacy", "v1", "deploy", "windows", "desktop-installer.iss")), "ProductionAppId");
        string[] ids = [Define(Desktop, "AppIdGuid"), Define(Server, "AppIdGuid")];
        Assert.All(ids, id => Assert.True(Guid.TryParse(id, out _)));
        Assert.Equal(3, ids.Append(v1).Distinct(StringComparer.OrdinalIgnoreCase).Count());
        Assert.Equal(v1, Define(Desktop, "V1AppIdGuid"));                                   // detected, never upgraded or removed
        Assert.Equal("{{{#AppIdGuid}}", Setting(Desktop, "AppId"));
        Assert.Equal("{{{#AppIdGuid}}", Setting(Server, "AppId"));
        // Never v1's program folder.
        Assert.Equal(@"{localappdata}\Programs\SAP Lens Desktop", Setting(Desktop, "DefaultDirName"));
        Assert.Equal(@"{autopf}\SAP Lens Server", Setting(Server, "DefaultDirName"));
    }

    [Fact]
    public void Both_use_the_official_multi_size_icon_and_the_product_name()
    {
        Assert.All([Desktop, Server], s => Assert.Equal("{#ProductIcon}", Setting(s, "SetupIconFile")));
        Assert.All([Desktop, Server], s => Assert.Contains(@"#define ProductIcon RepoRoot + ""\assets\sap-lens.ico""", s));
        Assert.All([Desktop, Server], s => Assert.Equal("SAP Lens", Setting(s, "VersionInfoProductName")));
        Assert.Equal("SAP Lens", Setting(Desktop, "AppName"));
        Assert.Equal("SAP Lens Server", Setting(Server, "AppName"));
        var ico = File.ReadAllBytes(Path.Combine(Repo, "assets", "sap-lens.ico"));
        Assert.Equal([0, 0, 1, 0], ico[..4]);                                                  // ICONDIR, type icon
        var sizes = Enumerable.Range(0, BitConverter.ToUInt16(ico, 4)).Select(i => ico[6 + 16 * i] == 0 ? 256 : ico[6 + 16 * i]).Order().ToArray();
        Assert.Equal([16, 24, 32, 48, 64, 128, 256], sizes);
    }

    [Fact]
    public void Installer_file_names_follow_the_product_version()
    {
        Assert.Equal("SAP-Lens-{#FullVersion}-Setup", Setting(Desktop, "OutputBaseFilename"));
        Assert.Equal("SAP-Lens-Server-{#FullVersion}-Setup", Setting(Server, "OutputBaseFilename"));
        Assert.Equal("SAP-Lens-2.0.0-alpha.1-Setup", Setting(Desktop, "OutputBaseFilename").Replace("{#FullVersion}", ProductIdentity.Version));
    }

    [Fact]
    public void Installers_ship_exactly_the_release_executables()
    {
        Assert.Contains(@"Source: ""{#ReleaseDir}\desktop\SapLens.exe""", Desktop);
        foreach (var file in new[] { "SapLens.Api.exe", "e_sqlite3.dll", "libSkiaSharp.dll" }) Assert.Contains($@"Source: ""{{#ReleaseDir}}\server\{file}""; DestDir: ""{{app}}\server""", Server);
        Assert.DoesNotContain("SapLens2Prototype.exe", Desktop + Server);
        Assert.Equal(@"{app}\SapLens.exe", Setting(Desktop, "UninstallDisplayIcon"));
    }

    [Fact]
    public void Data_is_never_deleted_and_no_process_is_killed()
    {
        Assert.All([Desktop, Server], s => Assert.DoesNotMatch(DeleteSection(), s));
        Assert.All([Desktop, Server], s => Assert.DoesNotMatch(Destructive(), s));
        Assert.All([Desktop, Server], s => Assert.Equal("no", Setting(s, "CloseApplications")));
        Assert.DoesNotContain("SAP Lens\\data", Desktop + Server);
        // Desktop: per user, and Setup waits for a running Desktop (current or earlier folder) instead of closing it.
        Assert.Equal("lowest", Setting(Desktop, "PrivilegesRequired"));
        Assert.Equal($"{DesktopLocation.MutexName},{DesktopLocation.LegacyMutexName}", Setting(Desktop, "AppMutex"));
        // Server: machine-wide; stops only its own service through the SCM and never creates or deletes a service.
        Assert.Equal("admin", Setting(Server, "PrivilegesRequired"));
        Assert.Contains("'stop ' + Names[I]", Server);
        Assert.DoesNotMatch(@"Exec\([^)]*sc\.exe", Server);
        Assert.Contains("Result[0] := 'SapLens';", Server);
        Assert.Contains("Result[1] := 'SapLens2';", Server);
        Assert.Contains("function InitializeUninstall", Server);
    }

    [Fact]
    public void The_build_script_verifies_the_release_and_passes_every_required_define()
    {
        var script = File.ReadAllText(Path.Combine(Repo, "backend", "scripts", "build-installers.ps1"));
        Assert.Contains("verify-release.ps1", script);
        foreach (var define in new[] { "FullVersion", "NumericVersion", "ReleaseDir" })
        {
            Assert.Contains($"/D{define}=", script);
            Assert.All([Desktop, Server], s => Assert.Contains($"#ifndef {define}", s));
        }
        Assert.Contains("source_dirty", script);
        Assert.DoesNotContain("signtool", script, StringComparison.OrdinalIgnoreCase);       // signing is a separate, authorized step
    }
}
