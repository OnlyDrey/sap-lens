using System.Collections;
using System.Reflection;
using Microsoft.Extensions.FileProviders;
using Microsoft.Extensions.Primitives;

namespace AuthLens.Api;

/// <summary>The production React UI (frontend/dist) and the server sign-in page are embedded in this assembly (see AuthLens.Api.csproj) under the logical
/// names "AuthLensUi/&lt;relative path&gt;". A build without them fails at startup with a clear message instead of serving 404 for "/".</summary>
public static class UiAssets
{
    /// <summary>The React mount point in frontend/index.html: proves "/" is the AuthLens application, not an error page.</summary>
    public const string Marker = "<div id=\"root\">";
    public const string ResourcePrefix = "AuthLensUi/";
    public const string ProductIdentityFile = "product-version.json";
    public static readonly string[] Required = ["index.html", "theme.js", "logo.png", "login.html", "login.css"];

    public static IFileProvider Create() => Validate(new EmbeddedUiFileProvider(typeof(UiAssets).Assembly));

    /// <summary>Refuses a provider that lacks any required file, naming every missing one.</summary>
    internal static IFileProvider Validate(IFileProvider provider)
    {
        var missing = Required.Where(name => !provider.GetFileInfo(name).Exists).ToList();
        if (missing.Count > 0) throw new InvalidOperationException($"The user interface is incomplete in this build (missing {string.Join(", ", missing)}); rebuild with -p:BuildFrontend=true.");
        return provider;
    }
}

/// <summary>Serves the UI from manifest resources named "AuthLensUi/&lt;relative path&gt;". The build sets these names explicitly (LogicalName), so the
/// layout no longer depends on the embedded-files manifest task, which splits paths on the build machine's separator only and keeps a stale manifest
/// across incremental builds (both broke Windows release builds). Separators in resource names are normalized to '/', so a name written with
/// RecursiveDir on Windows ("AuthLensUi/assets\x.js") resolves like one written on Linux. Paths with "..", empty or rooted segments never match.</summary>
public sealed class EmbeddedUiFileProvider : IFileProvider
{
    private readonly Dictionary<string, string> _files = new(StringComparer.Ordinal);   // relative path ('/' separated) -> resource name
    private readonly Func<string, Stream?> _open;
    private readonly DateTimeOffset _lastModified;

    public EmbeddedUiFileProvider(Assembly assembly)
        : this(assembly.GetManifestResourceNames(), assembly.GetManifestResourceStream, LastModified(assembly)) { }

    internal EmbeddedUiFileProvider(IEnumerable<string> resourceNames, Func<string, Stream?> open, DateTimeOffset lastModified)
    {
        (_open, _lastModified) = (open, lastModified);
        foreach (var name in resourceNames)
        {
            var normalized = name.Replace('\\', '/');
            if (!normalized.StartsWith(UiAssets.ResourcePrefix, StringComparison.Ordinal)) continue;
            var relative = Normalize(normalized[UiAssets.ResourcePrefix.Length..]);
            // The React build emits SAP Lens v1's product identity; this host answers /product-version.json with its own (ProductIdentity).
            if (relative == UiAssets.ProductIdentityFile) continue;
            if (relative is not null && !_files.TryAdd(relative, name))
                throw new InvalidOperationException($"The user interface contains the file '{relative}' twice in this build.");
        }
    }

    /// <summary>The UI is part of the executable (single-file packages have no assembly path), so its files change only with a new process: the start
    /// time, to the second, is their modification time. Responses are no-cache, so clients revalidate after every restart.</summary>
    private static DateTimeOffset LastModified(Assembly assembly)
    {
        _ = assembly;
        var now = DateTimeOffset.UtcNow;
        return new DateTimeOffset(now.Ticks - now.Ticks % TimeSpan.TicksPerSecond, TimeSpan.Zero);
    }

    /// <summary>"/assets/x.js", "assets\x.js" -> "assets/x.js"; null for anything that leaves the UI root or has empty segments.</summary>
    internal static string? Normalize(string? path)
    {
        if (path is null) return null;
        var segments = path.Replace('\\', '/').TrimStart('/').Split('/');
        if (segments.Length == 1 && segments[0].Length == 0) return "";
        return segments.Any(s => s.Length == 0 || s == "." || s == ".." || s.Contains(':')) ? null : string.Join('/', segments);
    }

    public IEnumerable<string> Files => _files.Keys;

    public IFileInfo GetFileInfo(string subpath)
    {
        var relative = Normalize(subpath);
        if (relative is null || !_files.TryGetValue(relative, out var resource)) return new NotFoundFileInfo(subpath ?? "");
        return new UiFile(resource, relative[(relative.LastIndexOf('/') + 1)..], _lastModified, _open);
    }

    public IDirectoryContents GetDirectoryContents(string subpath)
    {
        var relative = Normalize(subpath);
        if (relative is null) return NotFoundDirectoryContents.Singleton;
        var prefix = relative.Length == 0 ? "" : relative + "/";
        var files = new List<IFileInfo>();
        var directories = new SortedSet<string>(StringComparer.Ordinal);
        foreach (var (path, resource) in _files)
        {
            if (!path.StartsWith(prefix, StringComparison.Ordinal)) continue;
            var rest = path[prefix.Length..];
            var slash = rest.IndexOf('/');
            if (slash < 0) files.Add(new UiFile(resource, rest, _lastModified, _open));
            else directories.Add(rest[..slash]);
        }
        if (files.Count == 0 && directories.Count == 0) return NotFoundDirectoryContents.Singleton;
        return new Contents([.. directories.Select(d => (IFileInfo)new UiDirectory(d, _lastModified)), .. files]);
    }

    public IChangeToken Watch(string filter) => NullChangeToken.Singleton;

    private sealed class Contents(List<IFileInfo> entries) : IDirectoryContents
    {
        public bool Exists => true;
        public IEnumerator<IFileInfo> GetEnumerator() => entries.GetEnumerator();
        IEnumerator IEnumerable.GetEnumerator() => GetEnumerator();
    }

    private sealed class UiDirectory(string name, DateTimeOffset modified) : IFileInfo
    {
        public bool Exists => true;
        public long Length => -1;
        public string? PhysicalPath => null;
        public string Name => name;
        public DateTimeOffset LastModified => modified;
        public bool IsDirectory => true;
        public Stream CreateReadStream() => throw new InvalidOperationException("Cannot read a directory.");
    }

    private sealed class UiFile(string resource, string name, DateTimeOffset modified, Func<string, Stream?> open) : IFileInfo
    {
        private long? _length;
        public bool Exists => true;
        public long Length => _length ??= Measure();
        public string? PhysicalPath => null;
        public string Name => name;
        public DateTimeOffset LastModified => modified;
        public bool IsDirectory => false;
        public Stream CreateReadStream() => open(resource) ?? throw new FileNotFoundException("Embedded UI resource is missing.", resource);
        private long Measure() { using var stream = CreateReadStream(); return stream.Length; }
    }
}
