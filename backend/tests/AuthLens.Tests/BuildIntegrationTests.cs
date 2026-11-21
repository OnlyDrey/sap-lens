using System.Diagnostics;
using System.Text;
using System.Xml.Linq;
using Microsoft.Extensions.FileProviders;
using AuthLens.Api;

namespace AuthLens.Tests;

/// <summary>Build integration of the embedded React UI and the release workflow. Regression coverage for the Windows release failures in which every
/// host-starting test failed with "The user interface is incomplete in this build": the UI was served through the embedded-files manifest, which
/// splits paths on the build machine's separator only and was not regenerated on every change; and the release scripts ran `dotnet test --no-build`
/// on a test project the solution build did not include. The UI is now addressed by explicit resource names (AuthLensUi/&lt;path&gt;).</summary>
public sealed class BuildIntegrationTests
{
    private static DirectoryInfo SolutionRoot()
    {
        var dir = new DirectoryInfo(AppContext.BaseDirectory);
        while (dir is not null && !File.Exists(Path.Combine(dir.FullName, "AuthLens.slnx"))) dir = dir.Parent;
        return dir ?? throw new InvalidOperationException("AuthLens.slnx not found above the test output.");
    }

    private static string FrontendDist() => Path.GetFullPath(Path.Combine(SolutionRoot().FullName, "..", "frontend", "dist"));

    [Fact]
    public void Missing_ui_files_are_refused_with_every_missing_name()
    {
        var error = Assert.Throws<InvalidOperationException>(() => UiAssets.Validate(new NullFileProvider()));
        foreach (var name in UiAssets.Required) Assert.Contains(name, error.Message);

        var partial = Directory.CreateTempSubdirectory("saplens-ui-").FullName;
        try
        {
            foreach (var name in UiAssets.Required.Where(n => n != "theme.js")) File.WriteAllText(Path.Combine(partial, name), "x");
            using var provider = new PhysicalFileProvider(partial);
            var message = Assert.Throws<InvalidOperationException>(() => UiAssets.Validate(provider)).Message;
            Assert.Contains("missing theme.js)", message);
            Assert.DoesNotContain("index.html", message);
        }
        finally { Directory.Delete(partial, true); }
    }

    [Fact]
    public void The_embedded_ui_contains_every_file_of_the_frontend_build()
    {
        var dist = FrontendDist();
        Assert.True(File.Exists(Path.Combine(dist, "index.html")), $"The frontend build is missing at {dist}; the .NET build creates it (npm run build).");
        var provider = UiAssets.Create();
        var missing = Directory.EnumerateFiles(dist, "*", SearchOption.AllDirectories)
            .Select(f => Path.GetRelativePath(dist, f).Replace('\\', '/'))
            .Where(relative => relative != UiAssets.ProductIdentityFile && !provider.GetFileInfo(relative).Exists)
            .ToList();
        Assert.True(missing.Count == 0, "Not embedded in AuthLens.Api.dll: " + string.Join(", ", missing));
        // The React build's product-version.json carries SAP Lens v1's identity; this host serves its own at that path (VERSIONING.md).
        Assert.False(provider.GetFileInfo(UiAssets.ProductIdentityFile).Exists);
        using var reader = new StreamReader(provider.GetFileInfo("index.html").CreateReadStream());
        Assert.Contains(UiAssets.Marker, reader.ReadToEnd());
    }

    /// <summary>The UI layout a provider exposes: every required file at the root, React assets in the nested "assets" directory, and every file of
    /// the frontend build resolvable. This is the Windows release failure ("missing index.html, theme.js, logo.png").</summary>
    internal static void AssertUiLayout(EmbeddedUiFileProvider provider, IEnumerable<string>? distFiles = null)
    {
        foreach (var name in UiAssets.Required) Assert.True(provider.GetFileInfo(name).Exists, name);
        var root = provider.GetDirectoryContents("").ToList();
        Assert.Contains(root, f => f.IsDirectory && f.Name == "assets");
        Assert.Contains(root, f => !f.IsDirectory && f.Name == "index.html");
        foreach (var relative in distFiles ?? []) Assert.True(provider.GetFileInfo(relative).Exists, "Not embedded: " + relative);
    }

    [Fact]
    public void The_built_assembly_names_every_ui_resource_AuthLensUi_and_serves_the_nested_layout()
    {
        var names = typeof(UiAssets).Assembly.GetManifestResourceNames();
        Assert.DoesNotContain(names, n => n.StartsWith("AuthLens.Api.wwwroot", StringComparison.Ordinal));   // no UI under SDK-generated names
        Assert.Contains("AuthLensUi/index.html", names);
        AssertUiLayout(new EmbeddedUiFileProvider(typeof(UiAssets).Assembly));
    }

    private static EmbeddedUiFileProvider Fake(params string[] names) =>
        new(names, name => new MemoryStream(Encoding.UTF8.GetBytes(name)), DateTimeOffset.UnixEpoch);

    [Fact]
    public void Resource_names_with_Windows_separators_resolve_like_Linux_names()
    {
        // RecursiveDir is "assets\" on Windows and "assets/" on Linux; both builds must serve the same paths.
        foreach (var separator in new[] { '/', '\\' })
        {
            var provider = Fake("AuthLensUi/index.html", "AuthLensUi/theme.js", "AuthLensUi/logo.png", "AuthLensUi/login.html", "AuthLensUi/login.css",
                $"AuthLensUi/assets{separator}index-1a2b.js", $"AuthLensUi/assets{separator}icons{separator}x.svg", "V1Reference.registry.json", "Other/thing.txt");
            AssertUiLayout(provider, ["assets/index-1a2b.js", "assets/icons/x.svg"]);
            Assert.True(provider.GetFileInfo("/assets/index-1a2b.js").Exists);
            Assert.True(provider.GetFileInfo("assets\\icons\\x.svg").Exists);
            using var reader = new StreamReader(provider.GetFileInfo("assets/index-1a2b.js").CreateReadStream());
            Assert.Equal($"AuthLensUi/assets{separator}index-1a2b.js", reader.ReadToEnd());     // the stream is the actual resource
            Assert.Equal(["icons", "index-1a2b.js"], provider.GetDirectoryContents("assets").Select(f => f.Name));
            Assert.False(provider.GetFileInfo("registry.json").Exists);                        // other resources are never served
            Assert.Equal(7, provider.Files.Count());
        }
    }

    [Theory]
    [InlineData("../AuthLensUi/index.html")]
    [InlineData("assets/../index.html")]
    [InlineData("./index.html")]
    [InlineData("assets//index-1a2b.js")]
    [InlineData("C:/index.html")]
    [InlineData("assets")]
    public void Paths_outside_the_ui_root_or_not_files_are_not_found(string path)
    {
        var provider = Fake("AuthLensUi/index.html", "AuthLensUi/assets/index-1a2b.js");
        Assert.False(provider.GetFileInfo(path).Exists);
    }

    [Fact]
    public void Two_resources_for_the_same_path_are_refused()
    {
        Assert.Throws<InvalidOperationException>(() => Fake("AuthLensUi/assets/x.js", "AuthLensUi/assets\\x.js"));
    }

    [Fact]
    public void The_solution_builds_every_project_so_tests_never_run_stale_binaries()
    {
        var root = SolutionRoot().FullName;
        var listed = XDocument.Load(Path.Combine(root, "AuthLens.slnx")).Descendants("Project")
            .Select(p => Path.GetFullPath(Path.Combine(root, (string)p.Attribute("Path")!))).Order(StringComparer.Ordinal).ToList();
        var present = new[] { "src", "tests" }.SelectMany(folder => Directory.EnumerateFiles(Path.Combine(root, folder), "*.csproj", SearchOption.AllDirectories))
            .Where(p => !p.Split(Path.DirectorySeparatorChar).Any(part => part is "bin" or "obj"))
            .Select(Path.GetFullPath).Order(StringComparer.Ordinal).ToList();
        Assert.Equal(present, listed);
    }

    [Theory]
    [InlineData("build-release.sh")]
    [InlineData("build-release.ps1")]
    public void The_release_scripts_let_msbuild_build_a_fresh_ui_once_then_test_and_publish_that_build(string script)
    {
        var lines = File.ReadAllLines(Path.Combine(SolutionRoot().FullName, "scripts", script)).Where(l => !l.TrimStart().StartsWith('#')).ToArray();
        int First(Predicate<string> predicate) => Array.FindIndex(lines, predicate);
        // MSBuild (AuthLensBuildFrontend) is the only frontend build: no npm step of its own, a removed dist, then one solution build that builds it.
        Assert.DoesNotContain(lines, l => System.Text.RegularExpressions.Regex.IsMatch(l, @"(^\s*|[&(;|]\s*)npm\s+(ci|run|install)\b"));   // a command, not help text
        var clean = First(l => l.Contains("dist", StringComparison.Ordinal) && (l.Contains("rm -rf", StringComparison.Ordinal) || l.Contains("Remove-Item", StringComparison.Ordinal)));
        var build = First(l => l.Contains("dotnet build", StringComparison.Ordinal) && l.Contains("AuthLens.slnx", StringComparison.Ordinal));
        var test = First(l => l.Contains("dotnet test", StringComparison.Ordinal));
        var publish = First(l => l.Contains("dotnet publish", StringComparison.Ordinal));
        Assert.True(clean >= 0 && build > clean && test > build && publish > build, $"{script}: expected remove dist ({clean}) < dotnet build ({build}) < dotnet test ({test}), publish ({publish}).");
        Assert.Contains("-p:BuildFrontend=true", lines[build]);
        // The publishes reuse that dist (BuildFrontend only on the solution build), and the tests run exactly what was built.
        Assert.Single(lines, l => l.Contains("dotnet ", StringComparison.Ordinal) && l.Contains("BuildFrontend=true", StringComparison.Ordinal));
        Assert.All(lines.Where(l => l.Contains("dotnet test", StringComparison.Ordinal)), l => Assert.Contains("--no-build", l));
        // Freshness: the dist carries this commit, and each executable embeds this run's index.html and product-version.json.
        Assert.Contains(lines, l => l.Contains("source_sha", StringComparison.Ordinal) && l.Contains("dist", StringComparison.Ordinal));
        Assert.Contains(lines, l => l.Contains("'index.html', 'product-version.json'", StringComparison.Ordinal) || l.Contains("('index.html', 'product-version.json')", StringComparison.Ordinal));
    }

    private static (int Code, string Log) Build(string frontendRoot, string artifacts)
    {
        var info = new ProcessStartInfo("dotnet") { RedirectStandardOutput = true, RedirectStandardError = true, UseShellExecute = false, WorkingDirectory = artifacts };
        foreach (var arg in new[] { "build", Path.Combine(SolutionRoot().FullName, "src", "AuthLens.Api", "AuthLens.Api.csproj"), "-c", "Release", "--artifacts-path", artifacts,
                     "-p:AuthLensFrontendRoot=" + frontendRoot, "-nologo", "-nodeReuse:false", "-p:UseSharedCompilation=false" })
            info.ArgumentList.Add(arg);
        info.Environment["MSBUILDDISABLENODEREUSE"] = "1";
        info.Environment["DOTNET_CLI_TELEMETRY_OPTOUT"] = "1";
        using var process = Process.Start(info)!;
        var stdout = process.StandardOutput.ReadToEndAsync();
        var stderr = process.StandardError.ReadToEndAsync();
        Assert.True(process.WaitForExit(TimeSpan.FromMinutes(10)), "build timed out");
        return (process.ExitCode, stdout.Result + stderr.Result);
    }

    [Fact]
    [Trait("Category", "Build")]
    public void An_incremental_build_embeds_exactly_the_current_frontend_files()
    {
        var work = Directory.CreateTempSubdirectory("saplens-uibuild-").FullName;
        try
        {
            var frontend = Path.Combine(work, "frontend");
            var dist = Path.Combine(frontend, "dist");
            Directory.CreateDirectory(Path.Combine(dist, "assets"));
            File.WriteAllText(Path.Combine(frontend, "package.json"), "{}");
            File.WriteAllText(Path.Combine(dist, "index.html"), "<html><body><div id=\"root\"></div></body></html>");
            File.WriteAllText(Path.Combine(dist, "theme.js"), "/* theme */");
            File.WriteAllBytes(Path.Combine(dist, "logo.png"), [137, 80, 78, 71]);
            File.WriteAllText(Path.Combine(dist, "assets", "first-1a2b.js"), "/* first */");
            var artifacts = Path.Combine(work, "artifacts");
            Directory.CreateDirectory(artifacts);

            var (code, log) = Build(frontend, artifacts);
            Assert.True(code == 0, log);
            var built = Directory.EnumerateFiles(Path.Combine(artifacts, "bin"), "AuthLens.Api.dll", SearchOption.AllDirectories).Single();
            // The provider over the freshly built assembly, loaded in its own collectible context (resources only, no code runs).
            List<string> Served()
            {
                var context = new System.Runtime.Loader.AssemblyLoadContext("ui-check", isCollectible: true);
                try
                {
                    using var stream = new MemoryStream(File.ReadAllBytes(built));
                    var assembly = context.LoadFromStream(stream);
                    var provider = new EmbeddedUiFileProvider(assembly);
                    AssertUiLayout(provider);
                    return [.. provider.Files.Order(StringComparer.Ordinal)];
                }
                finally { context.Unload(); }
            }
            Assert.Equal(["assets/first-1a2b.js", "index.html", "login.css", "login.html", "logo.png", "theme.js"], Served());   // clean build

            // A new frontend build replaces the hashed asset. The incremental build must follow: the new file only.
            File.Delete(Path.Combine(dist, "assets", "first-1a2b.js"));
            File.WriteAllText(Path.Combine(dist, "assets", "second-3c4d.js"), "/* second */");
            (code, log) = Build(frontend, artifacts);
            Assert.True(code == 0, log);
            Assert.Equal(["assets/second-3c4d.js", "index.html", "login.css", "login.html", "logo.png", "theme.js"], Served());   // repeat build

            // A file is only removed: nothing became newer, and the assembly must still be rebuilt without it.
            File.WriteAllText(Path.Combine(dist, "assets", "third-5e6f.js"), "/* third */");
            (code, log) = Build(frontend, artifacts);
            Assert.True(code == 0, log);
            File.Delete(Path.Combine(dist, "assets", "second-3c4d.js"));
            (code, log) = Build(frontend, artifacts);
            Assert.True(code == 0, log);
            Assert.Equal(["assets/third-5e6f.js", "index.html", "login.css", "login.html", "logo.png", "theme.js"], Served());
        }
        finally
        {
            try { Directory.Delete(work, true); } catch (IOException) { } catch (UnauthorizedAccessException) { }
        }
    }
}
