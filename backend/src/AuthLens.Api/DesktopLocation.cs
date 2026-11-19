namespace AuthLens.Api;

/// <summary>Where the .NET Desktop keeps its data, logs and WebView2 profile, and which single-instance mutex guards it. New installations use
/// %LOCALAPPDATA%\SAP Lens Desktop. A folder from the earlier prototype builds (%LOCALAPPDATA%\SAP Lens 2 Prototype) is kept and used as it is:
/// it is never renamed or moved, so its data, logs and backups stay where they were. %LOCALAPPDATA%\SAP Lens belongs to SAP Lens v1 and is never used.
/// The mutex follows the folder, so a prototype build and this build never open the same data at the same time.</summary>
public static class DesktopLocation
{
    public const string FolderName = "SAP Lens Desktop", LegacyFolderName = "SAP Lens 2 Prototype", V1FolderName = "SAP Lens";
    public const string MutexName = @"Local\AuthLensDotnetDesktop", LegacyMutexName = @"Local\SapLens2Prototype";

    public sealed record Location(string Root, string Mutex, bool Legacy);

    public static Location Resolve(string localApplicationData)
    {
        var current = Path.Combine(localApplicationData, FolderName);
        var legacy = Path.Combine(localApplicationData, LegacyFolderName);
        return !Directory.Exists(current) && Directory.Exists(legacy) ? new(legacy, LegacyMutexName, true) : new(current, MutexName, false);
    }
}
