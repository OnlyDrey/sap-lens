using System.Diagnostics;
using System.Text;
using System.Xml.Linq;
using Microsoft.Extensions.FileProviders;
using SapLens.Api;

namespace SapLens.Tests;

/// <summary>Build integration of the embedded React UI and the release workflow. Regression coverage for the Windows release failure in which
/// every host-starting test failed with "The user interface is incomplete in this build": (1) the embedded-files manifest was not regenerated when
/// the frontend dist changed, because the dist files were added after Microsoft.Extensions.FileProviders.Embedded hashed its inputs, and (2) the
/// release scripts ran `dotnet test --no-build` on a test project the solution build did not include.</summary>
public sealed class BuildIntegrationTests
{
    private static DirectoryInfo SolutionRoot()
    {
        var dir = new DirectoryInfo(AppContext.BaseDirectory);
        while (dir is not null && !File.Exists(Path.Combine(dir.FullName, "SapLens.slnx"))) dir = dir.Parent;
        return dir ?? throw new InvalidOperationException("SapLens.slnx not found above the test output.");
    }

    private static string FrontendDist() => Path.GetFullPath(Path.Combine(SolutionRoot().FullName, "..", "..", "frontend", "dist"));

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
            .Where(relative => !provider.GetFileInfo(relative).Exists)
            .ToList();
        Assert.True(missing.Count == 0, "Not embedded in SapLens.Api.dll: " + string.Join(", ", missing));
        using var reader = new StreamReader(provider.GetFileInfo("index.html").CreateReadStream());
        Assert.Contains(UiAssets.Marker, reader.ReadToEnd());
    }

    /// <summary>Every file of the embedded-files manifest must sit in a directory element: a file name containing a separator means the build passed a
    /// path with the other OS's separator to GenerateEmbeddedResourcesManifest (it splits on Path.DirectorySeparatorChar only) and the file is
    /// invisible to the provider. This is the Windows release failure ("missing index.html, theme.js, sap-lens.png").</summary>
    internal static void AssertNestedManifest(XDocument manifest)
    {
        var flat = manifest.Descendants("File").Select(f => (string)f.Attribute("Name")!).Where(n => n.Contains('/') || n.Contains('\\')).ToList();
        Assert.True(flat.Count == 0, "Embedded files with a separator in their name (not under a directory): " + string.Join(", ", flat.Take(10)));
        var root = manifest.Root!.Element("FileSystem")!.Elements("Directory").SingleOrDefault(d => (string?)d.Attribute("Name") == "wwwroot");
        Assert.NotNull(root);
        foreach (var name in UiAssets.Required) Assert.Contains(root!.Elements("File"), f => (string)f.Attribute("Name")! == name);
    }

    [Fact]
    public void The_built_assembly_embeds_the_ui_under_wwwroot_with_nested_directories()
    {
        using var stream = typeof(UiAssets).Assembly.GetManifestResourceStream("Microsoft.Extensions.FileProviders.Embedded.Manifest.xml");
        Assert.NotNull(stream);
        AssertNestedManifest(XDocument.Load(stream!));
    }

    [Fact]
    public void The_solution_builds_every_project_so_tests_never_run_stale_binaries()
    {
        var root = SolutionRoot().FullName;
        var listed = XDocument.Load(Path.Combine(root, "SapLens.slnx")).Descendants("Project")
            .Select(p => Path.GetFullPath(Path.Combine(root, (string)p.Attribute("Path")!))).Order(StringComparer.Ordinal).ToList();
        var present = new[] { "src", "tests" }.SelectMany(folder => Directory.EnumerateFiles(Path.Combine(root, folder), "*.csproj", SearchOption.AllDirectories))
            .Where(p => !p.Split(Path.DirectorySeparatorChar).Any(part => part is "bin" or "obj"))
            .Select(Path.GetFullPath).Order(StringComparer.Ordinal).ToList();
        Assert.Equal(present, listed);
    }

    [Theory]
    [InlineData("build-release.sh")]
    [InlineData("build-release.ps1")]
    public void The_release_scripts_build_the_ui_then_the_solution_then_test_that_build(string script)
    {
        var lines = File.ReadAllLines(Path.Combine(SolutionRoot().FullName, "scripts", script));
        int First(Func<string, bool> predicate) => Array.FindIndex(lines, l => !l.TrimStart().StartsWith('#') && predicate(l));
        var ui = First(l => l.Contains("npm run build", StringComparison.Ordinal));
        var build = First(l => l.Contains("dotnet build", StringComparison.Ordinal) && l.Contains("SapLens.slnx", StringComparison.Ordinal));
        var test = First(l => l.Contains("dotnet test", StringComparison.Ordinal));
        Assert.True(ui >= 0 && build > ui && test > build, $"{script}: expected npm run build ({ui}) < dotnet build SapLens.slnx ({build}) < dotnet test ({test}).");
        Assert.All(lines.Where(l => l.Contains("dotnet test", StringComparison.Ordinal)), l => Assert.Contains("--no-build", l));
    }

    private static (int Code, string Log) Build(string frontendRoot, string artifacts)
    {
        var info = new ProcessStartInfo("dotnet") { RedirectStandardOutput = true, RedirectStandardError = true, UseShellExecute = false, WorkingDirectory = artifacts };
        foreach (var arg in new[] { "build", Path.Combine(SolutionRoot().FullName, "src", "SapLens.Api", "SapLens.Api.csproj"), "-c", "Release", "--artifacts-path", artifacts,
                     "-p:SapLensFrontendRoot=" + frontendRoot, "-nologo", "-nodeReuse:false", "-p:UseSharedCompilation=false" })
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
            File.WriteAllBytes(Path.Combine(dist, "sap-lens.png"), [137, 80, 78, 71]);
            File.WriteAllText(Path.Combine(dist, "assets", "first-1a2b.js"), "/* first */");
            var artifacts = Path.Combine(work, "artifacts");
            Directory.CreateDirectory(artifacts);

            var (code, log) = Build(frontend, artifacts);
            Assert.True(code == 0, log);
            string Manifest() => File.ReadAllText(Directory.EnumerateFiles(artifacts, "Microsoft.Extensions.FileProviders.Embedded.Manifest.xml", SearchOption.AllDirectories).Single());
            byte[] Assembly() => File.ReadAllBytes(Directory.EnumerateFiles(Path.Combine(artifacts, "bin"), "SapLens.Api.dll", SearchOption.AllDirectories).Single());
            static bool Has(byte[] bytes, string text) => bytes.AsSpan().IndexOf(Encoding.UTF8.GetBytes(text)) >= 0;
            Assert.Contains("first-1a2b.js", Manifest());
            Assert.Contains("theme.js", Manifest());
            AssertNestedManifest(XDocument.Parse(Manifest()));   // clean build

            // A new frontend build replaces the hashed asset. The incremental build must follow: the manifest and the resources name the new file only.
            File.Delete(Path.Combine(dist, "assets", "first-1a2b.js"));
            File.WriteAllText(Path.Combine(dist, "assets", "second-3c4d.js"), "/* second */");
            (code, log) = Build(frontend, artifacts);
            Assert.True(code == 0, log);
            var manifest = Manifest();
            Assert.Contains("second-3c4d.js", manifest);
            Assert.DoesNotContain("first-1a2b.js", manifest);
            AssertNestedManifest(XDocument.Parse(manifest));     // repeat (incremental) build
            var assets = XDocument.Parse(manifest).Descendants("Directory").Single(d => (string?)d.Attribute("Name") == "assets");
            Assert.Contains(assets.Elements("File"), f => (string)f.Attribute("Name")! == "second-3c4d.js");
            var dll = Assembly();
            Assert.True(Has(dll, "wwwroot.assets.second-3c4d.js"), "the new asset is not embedded");
            Assert.False(Has(dll, "wwwroot.assets.first-1a2b.js"), "a removed asset is still embedded");
        }
        finally
        {
            try { Directory.Delete(work, true); } catch (IOException) { } catch (UnauthorizedAccessException) { }
        }
    }
}
