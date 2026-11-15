using SapLens.Api;

// Server entry point (Windows and Linux): sap-lens-v2-server --data-dir <absolute path> [--port 18790] [--frontend <dist>] [--no-worker]
var options = args.Select((value, index) => (value, index)).Where(p => p.value.StartsWith("--", StringComparison.Ordinal))
    .ToDictionary(p => p.value, p => p.index + 1 < args.Length && !args[p.index + 1].StartsWith("--", StringComparison.Ordinal) ? args[p.index + 1] : "true");
var dataDirectory = options.GetValueOrDefault("--data-dir") ?? Environment.GetEnvironmentVariable("SAP_LENS_V2_DATA_DIR");
if (string.IsNullOrWhiteSpace(dataDirectory)) { Console.Error.WriteLine("--data-dir (or SAP_LENS_V2_DATA_DIR) is required."); return 2; }
var port = int.TryParse(options.GetValueOrDefault("--port"), out var p) && p is > 0 and < 65536 ? p : 18790;
Directory.CreateDirectory(dataDirectory);

// The token comes from the environment (service configuration) or is generated once and kept in a file only the service account can read.
var token = Environment.GetEnvironmentVariable("SAP_LENS_V2_TOKEN");
if (string.IsNullOrEmpty(token))
{
    var tokenFile = Path.Combine(dataDirectory, "api-token");
    if (!File.Exists(tokenFile))
    {
        var options2 = new FileStreamOptions { Mode = FileMode.CreateNew, Access = FileAccess.Write };
        // Linux: owner read/write only. Windows: the file inherits the data directory ACL, which the installer restricts to the service account.
        if (!OperatingSystem.IsWindows()) options2.UnixCreateMode = UnixFileMode.UserRead | UnixFileMode.UserWrite;
        using var stream = new FileStream(tokenFile, options2);
        using var writer = new StreamWriter(stream);
        writer.Write(HostSettings.NewToken());
    }
    token = File.ReadAllText(tokenFile).Trim();
}

try
{
    var app = SapLensHost.Build(new HostSettings
    {
        DataDirectory = Path.GetFullPath(dataDirectory), Url = $"http://127.0.0.1:{port}", AccessToken = token, FrontendDirectory = options.GetValueOrDefault("--frontend"),
        WorkerEnabled = !options.ContainsKey("--no-worker"), PrincipalName = Environment.GetEnvironmentVariable("SAP_LENS_V2_PRINCIPAL") ?? "server-operator",
    }, args);
    await app.RunAsync();
    return 0;
}
catch (InvalidOperationException error)
{
    Console.Error.WriteLine($"startup refused: {error.Message}");
    return 3;
}
