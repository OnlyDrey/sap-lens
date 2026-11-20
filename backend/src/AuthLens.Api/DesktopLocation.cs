namespace AuthLens.Api;

/// <summary>Where the AuthLens Desktop keeps its data, logs and WebView2 profile (%LOCALAPPDATA%\AuthLens), and the single-instance mutex that
/// guards it. Folders of earlier products (SAP Lens Desktop, the SAP Lens 2 prototype, SAP Lens 1) are never opened, moved or changed: their data
/// comes to AuthLens through a backup restore. They are only reported, so the log can say that earlier data exists.</summary>
public static class DesktopLocation
{
    public const string FolderName = "AuthLens", MutexName = @"Local\AuthLensDesktop";
    public static readonly string[] EarlierProductFolders = ["SAP Lens Desktop", "SAP Lens 2 Prototype", "SAP Lens"];

    public sealed record Location(string Root, string Mutex, string[] EarlierProductData);

    public static Location Resolve(string localApplicationData) =>
        new(Path.Combine(localApplicationData, FolderName), MutexName,
            [.. EarlierProductFolders.Select(f => Path.Combine(localApplicationData, f)).Where(Directory.Exists)]);

    /// <summary>An explicit data folder isolates logs, WebView2 and the mutex as well as SQLite. The normal Desktop profile is untouched.</summary>
    public static Location ResolveForDataDirectory(string localApplicationData, string dataDirectory)
    {
        AuthLens.Persistence.DatabaseOptions.ValidateLocal(dataDirectory);
        var data = Path.GetFullPath(dataDirectory).TrimEnd(Path.DirectorySeparatorChar);
        if (data.Length < Path.GetPathRoot(Path.GetFullPath(dataDirectory))!.Length)
            throw new InvalidOperationException("Desktop data must not be a drive root.");
        for (string? item = data; item is not null; item = Path.GetDirectoryName(item))
            if ((File.Exists(item) || Directory.Exists(item)) && (File.GetAttributes(item) & FileAttributes.ReparsePoint) != 0)
                throw new InvalidOperationException("Desktop data paths must not traverse links.");
        var normal = Resolve(localApplicationData);
        var comparison = OperatingSystem.IsWindows() ? StringComparison.OrdinalIgnoreCase : StringComparison.Ordinal;
        foreach (var folder in EarlierProductFolders)
        {
            var earlier = Path.GetFullPath(Path.Combine(localApplicationData, folder));
            if (data.Equals(earlier, comparison) || data.StartsWith(earlier + Path.DirectorySeparatorChar, comparison))
                throw new InvalidOperationException("Desktop never writes into an earlier product's profile. Restore a backup into a separate AuthLens folder.");
        }
        AuthLens.Persistence.DatabaseOptions.RefuseUnadoptedLegacy(data);
        if (data.Equals(Path.Combine(normal.Root, "data"), comparison)) return normal;
        var identity = OperatingSystem.IsWindows() ? data.ToUpperInvariant() : data;
        var hash = Convert.ToHexString(System.Security.Cryptography.SHA256.HashData(System.Text.Encoding.UTF8.GetBytes(identity)))[..16];
        return new Location(Path.Combine(data, ".desktop"), MutexName + "-" + hash, normal.EarlierProductData);
    }
}
