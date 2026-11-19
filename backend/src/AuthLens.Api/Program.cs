using AuthLens.Api;

// Server entry point (Windows and Linux). Defaults to http://127.0.0.1:18790. LAN access only with --network, one private --listen address,
// --allowed-hosts and an HTTPS certificate. Runs as a console process, a Windows service or a systemd notify service. See ServerConfiguration.
if (ServerConfiguration.Informational(args) is { } information)
{
    Console.Out.WriteLine(information);
    return 0;
}
// Earlier product names' variables are never read; report them so a setting is never lost silently (AuthLens can run beside SAP Lens).
if (ServerConfiguration.RenamedEnvironment(Environment.GetEnvironmentVariables()) is { } renamed) Console.Error.WriteLine($"warning: {renamed}");
if (MaintenanceCommands.Handles(args)) return MaintenanceCommands.Run(args);
if (args.Contains("--migrate-v1"))
{
    // SAP Lens 1 to AuthLens data migration, step by step; local, the server must not be running for activate/rollback to take effect at its next start.
    try
    {
        string? Value(string name) { var i = Array.IndexOf(args, name); return i >= 0 && i + 1 < args.Length && !args[i + 1].StartsWith("--", StringComparison.Ordinal) ? args[i + 1] : null; }
        var step = Value("--migrate-v1") ?? throw new InvalidOperationException("--migrate-v1 needs preview, run, activate, rollback or status.");
        var data = Value("--data-dir") ?? Environment.GetEnvironmentVariable("AUTHLENS_DATA_DIR") ?? throw new InvalidOperationException("--data-dir (or AUTHLENS_DATA_DIR) is required.");
        if (!Path.IsPathFullyQualified(data)) throw new InvalidOperationException("--data-dir must be an absolute path.");
        var actor = Environment.UserName;
        var now = DateTimeOffset.UtcNow;
        System.Text.Json.Nodes.JsonObject result;
        switch (step)
        {
            case "preview":
                var source = Value("--source") ?? throw new InvalidOperationException("--source <SAP Lens 1 data directory or .slbak/.tar.gz> is required.");
                var secret = "";
                if (File.Exists(source) && Value("--v1-key-file") is { } keyFile)
                {
                    // The escrowed SAP Lens 1 recovery key file (base64 text) for a host-key archive; read, never printed.
                    if (!Path.IsPathFullyQualified(keyFile) || new FileInfo(keyFile).Length > 4096) throw new InvalidOperationException("--v1-key-file must be an absolute path to the SAP Lens 1 recovery key file.");
                    secret = File.ReadAllText(keyFile).Trim();
                }
                else if (File.Exists(source) && !source.EndsWith(".tar.gz", StringComparison.OrdinalIgnoreCase))
                {
                    string mode;
                    using (var probe = File.OpenRead(source)) mode = AuthLens.Application.Backups.BackupArchive.V1KeyMode(probe);
                    Console.Error.Write(mode == "passphrase" ? "SAP Lens 1 backup passphrase: " : "SAP Lens 1 recovery key (or use --v1-key-file <file>): ");
                    secret = ServerConfiguration.ReadSecret();
                    Console.Error.WriteLine();
                }
                result = V1DataMigration.Preview(source, data, secret, args.Contains("--replace-existing"), now);
                result.Remove("inventory");
                break;
            case "run":
                result = await V1DataMigration.RunAsync(data, Value("--id") ?? "", Value("--approve") ?? "", actor, now);
                break;
            case "activate":
                result = V1DataMigration.RequestActivation(data, Value("--id") ?? "", Value("--approve") ?? "", actor, now);
                break;
            case "rollback":
                result = V1DataMigration.RequestRollback(data, Value("--id") ?? "", actor, now);
                break;
            case "status":
                result = V1DataMigration.Status(data, Value("--id") ?? "");
                break;
            default: throw new InvalidOperationException("--migrate-v1 needs preview, run, activate, rollback or status.");
        }
        Console.Out.WriteLine(result.ToJsonString(new System.Text.Json.JsonSerializerOptions { WriteIndented = true, Encoder = System.Text.Encodings.Web.JavaScriptEncoder.UnsafeRelaxedJsonEscaping }));
        return 0;
    }
    catch (Exception error) when (error is InvalidOperationException or MigrationException or AuthLens.Application.Backups.BackupException or IOException or UnauthorizedAccessException)
    {
        Console.Error.WriteLine($"migration refused: {error.Message}");
        return 3;
    }
}
if (args.Contains("--backup-key"))
{
    // Local host backup key management: no listener; the key value is never printed.
    try
    {
        var (action, path, data) = ServerConfiguration.BackupKey(args, Environment.GetEnvironmentVariable);
        var result = action switch
        {
            "create" => AuthLens.Application.Backups.BackupKeys.Create(path, data),
            "use" => AuthLens.Application.Backups.BackupKeys.Use(path, data),
            "export" => AuthLens.Application.Backups.BackupKeys.Export(path, data),
            "verify" => AuthLens.Application.Backups.BackupKeys.VerifyFile(path, data, Environment.UserName, DateTimeOffset.UtcNow),
            _ => AuthLens.Application.Backups.BackupKeys.Status(data),
        };
        Console.Out.WriteLine(result.ToJsonString());
        return 0;
    }
    catch (Exception error) when (error is InvalidOperationException or AuthLens.Application.Backups.BackupException or IOException or UnauthorizedAccessException)
    {
        Console.Error.WriteLine($"backup key refused: {error.Message}");
        return 3;
    }
}
if (args.Contains("--check-sign-in"))
{
    // Local, read-only sign-in diagnosis: no listener, no writes; the password is read from the console without echo (or from redirected input).
    try
    {
        var (store, username) = ServerConfiguration.SignInCheck(args, Environment.GetEnvironmentVariable);
        Console.Error.Write($"Password for '{username}': ");
        var password = ServerConfiguration.ReadSecret();
        Console.Error.WriteLine();
        Console.Out.WriteLine(AuthLens.Application.Accounts.AccountDiagnostics.Report(AuthLens.Application.Accounts.AccountDiagnostics.Check(store, username, password)));
        return 0;
    }
    catch (InvalidOperationException error)
    {
        Console.Error.WriteLine($"check refused: {error.Message}");
        return 3;
    }
}
try
{
    var settings = ServerConfiguration.Parse(args, Environment.GetEnvironmentVariable);
    var app = AuthLensHost.Build(settings, [], builder =>
    {
        // Canonical name for new own-process services. Legacy SCM registrations remain supported by deployment detection.
        builder.Services.AddWindowsService(o => o.ServiceName = "AuthLens");
        // A Windows service has no console: keep the same (secret-free) log lines in <data-dir>\logs.
        if (Microsoft.Extensions.Hosting.WindowsServices.WindowsServiceHelpers.IsWindowsService())
            builder.Logging.AddProvider(new FileLoggerProvider(Path.Combine(settings.DataDirectory, "logs"), "server"));
        builder.Services.AddSystemd();
    });
    await app.RunAsync();
    return 0;
}
catch (InvalidOperationException error)
{
    Console.Error.WriteLine($"startup refused: {error.Message}");
    return 3;
}
