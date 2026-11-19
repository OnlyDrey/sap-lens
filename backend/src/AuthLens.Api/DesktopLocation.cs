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
}
