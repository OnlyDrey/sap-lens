using System.Reflection;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;
using Microsoft.AspNetCore.Builder;
using AuthLens.Api;

namespace AuthLens.Tests;

/// <summary>One product version for AuthLens (backend/product-version.json), the same in the assemblies, --version, every HTTP
/// identity and the release scripts; independent of SAP Lens v1, whose own version source and frontend mirror stay as they are.</summary>
public sealed class VersioningTests : IAsyncLifetime
{
    private static readonly DirectoryInfo Solution = FindSolution();
    private static DirectoryInfo FindSolution()
    {
        var dir = new DirectoryInfo(AppContext.BaseDirectory);
        while (dir is not null && !File.Exists(Path.Combine(dir.FullName, "AuthLens.slnx"))) dir = dir.Parent;
        return dir!;
    }
    private static string Repository => Path.GetFullPath(Path.Combine(Solution.FullName, ".."));
    private static string FileVersionOf(string version)
    {
        var match = Regex.Match(version, @"^(\d+)\.(\d+)\.(\d+)(?:-(?:alpha|beta|rc)\.(\d+))?$");
        Assert.True(match.Success, version);
        return $"{match.Groups[1].Value}.{match.Groups[2].Value}.{match.Groups[3].Value}.{(match.Groups[4].Success ? match.Groups[4].Value : "0")}";
    }

    private readonly string _root = Directory.CreateTempSubdirectory("saplens-version-").FullName;
    private WebApplication _app = null!;
    private HttpClient _client = null!;

    public async Task InitializeAsync()
    {
        var token = HostSettings.NewToken();
        _app = AuthLensHost.Build(new HostSettings { DataDirectory = Path.Combine(_root, "data"), Port = 0, AccessToken = token, JsonConsoleLogging = false, Mode = HostMode.Desktop });
        await _app.StartAsync();
        _client = new HttpClient { BaseAddress = new Uri(_app.Urls.First()) };
        _client.DefaultRequestHeaders.Add(RequestBoundary.TokenHeader, token);
    }

    public async Task DisposeAsync()
    {
        _client.Dispose();
        await _app.StopAsync();
        await _app.DisposeAsync();
        Microsoft.Data.Sqlite.SqliteConnection.ClearAllPools();
        try { Directory.Delete(_root, true); } catch (IOException) { }
    }

    [Fact]
    public void The_version_file_is_the_only_source_and_the_assemblies_follow_it()
    {
        var file = JsonNode.Parse(File.ReadAllText(Path.Combine(Solution.FullName, "product-version.json")))!;
        var version = (string)file["version"]!;
        Assert.Equal("AuthLens", (string)file["product"]!);
        Assert.Matches(@"^(0|[1-9]\d{0,4})\.(0|[1-9]\d{0,4})\.(0|[1-9]\d{0,4})(-(alpha|beta|rc)\.[1-9]\d{0,4})?$", version);
        Assert.Equal(version, ProductIdentity.Version);
        Assert.Equal(FileVersionOf(version), string.Join('.', ProductIdentity.FileVersion));
        Assert.Equal(version.Contains('-') ? version.Split('-')[1].Split('.')[0] : "stable", ProductIdentity.Channel);
        var assembly = typeof(ProductIdentity).Assembly;
        Assert.Equal(FileVersionOf(version), assembly.GetCustomAttribute<AssemblyFileVersionAttribute>()!.Version);
        Assert.Equal("AuthLens", assembly.GetCustomAttribute<AssemblyProductAttribute>()!.Product);
        Assert.StartsWith(version, assembly.GetCustomAttribute<AssemblyInformationalVersionAttribute>()!.InformationalVersion);
        Assert.Equal(version, typeof(AuthLens.Application.Backups.ApplicationBackups).Assembly.GetCustomAttribute<AssemblyInformationalVersionAttribute>()!.InformationalVersion.Split('+')[0]);
        Assert.Equal(version, AuthLens.Application.Backups.ApplicationBackups.ProductVersion);
        // Every project of the solution builds from the same props: the domain and persistence assemblies carry the same file version.
        Assert.Equal(FileVersionOf(version), typeof(AuthLens.Domain.Json.CanonicalJson).Assembly.GetCustomAttribute<AssemblyFileVersionAttribute>()!.Version);
        // No version text is maintained anywhere else in the build.
        var props = File.ReadAllText(Path.Combine(Solution.FullName, "Directory.Build.props"));
        Assert.Contains("<Version>$(AuthLensVersion)</Version>", props);                                   // derived, never a literal
        Assert.DoesNotMatch(@"<Version>\d", props);
        Assert.DoesNotContain("0.0.0-experiment", File.ReadAllText(Path.Combine(Solution.FullName, "Directory.Build.props")));
    }

    [Fact]
    public void Sap_lens_is_versioned_independently_of_v1_and_the_frontend_mirrors_its_version()
    {
        // SAP Lens 1's last product version (backend/resources/product-version.json at commit 604f21e; archived outside the repository).
        const string v1 = "1.0.0-beta.2";
        Assert.NotEqual(v1, ProductIdentity.Version);
        Assert.Equal(ProductIdentity.Version, (string)JsonNode.Parse(File.ReadAllText(Path.Combine(Repository, "frontend", "package.json")))!["version"]!);
        var locked = JsonNode.Parse(File.ReadAllText(Path.Combine(Repository, "frontend", "package-lock.json")))!;
        Assert.Equal(ProductIdentity.Version, (string)locked["version"]!);
        Assert.Equal(ProductIdentity.Version, (string)locked["packages"]![""]!["version"]!);
    }

    [Fact]
    public void Version_output_names_product_version_channel_commit_and_file_version()
    {
        var text = ServerConfiguration.Informational(["--version"])!;
        var lines = text.Split(Environment.NewLine);
        Assert.Equal($"AuthLens server {ProductIdentity.Version}", lines[0]);
        Assert.Contains(lines, l => l == $"File version: {string.Join('.', ProductIdentity.FileVersion)}");
        Assert.Contains(lines, l => l.StartsWith("Channel: ", StringComparison.Ordinal) && l.Contains(ProductIdentity.Channel == "stable" ? "stable release" : ProductIdentity.Channel + " pre-release"));
        Assert.Contains(lines, l => l == $"Commit: {ProductIdentity.Commit ?? "not recorded (local build)"}");
        Assert.Contains(lines, l => l.StartsWith("Runtime: .NET ", StringComparison.Ordinal));
    }

    [Fact]
    public async Task Every_http_identity_reports_the_same_product_version()
    {
        var version = JsonNode.Parse(await _client.GetStringAsync("/api/version"))!;
        var info = JsonNode.Parse(await _client.GetStringAsync("/api/application-info"))!;
        var identity = JsonNode.Parse(await _client.GetStringAsync("/product-version.json"))!;
        var diagnostics = JsonNode.Parse(await _client.GetStringAsync("/api/diagnostics"))!;
        foreach (var node in new[] { version, info, identity, diagnostics }) Assert.Equal(ProductIdentity.Version, (string)node["version"]!);
        Assert.Equal("AuthLens", (string)identity["product"]!);
        Assert.Equal(ProductIdentity.Channel, (string)identity["channel"]!);
        Assert.Equal(ProductIdentity.FileVersion, info["file_version"]!.AsArray().Select(n => (int)n!));
        Assert.Equal(ProductIdentity.FileVersion, identity["file_version"]!.AsArray().Select(n => (int)n!));
        Assert.Equal(ProductIdentity.Commit, (string?)identity["source_sha"]);
    }

    [Theory]
    [InlineData("build-release.ps1")]
    [InlineData("build-release.sh")]
    public void Release_scripts_take_the_version_from_the_version_file_and_check_it_in_every_executable(string script)
    {
        var text = File.ReadAllText(Path.Combine(Solution.FullName, "scripts", script));
        Assert.Contains("product-version.json", text);
        Assert.DoesNotContain("Directory.Build.props", text);                   // the props no longer hold a version
        Assert.Contains("AuthLens-", text);                                     // the folder name carries the version
        Assert.Contains("{version}+{sha}", text.Replace("$version+$sha", "{version}+{sha}"));
        Assert.Contains("ui_source_version", text);                              // the frontend mirrors the same canonical product version
    }
}
