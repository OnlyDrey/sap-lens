using SapLens.Api;

// Server entry point (Windows and Linux). Defaults to http://127.0.0.1:18790. LAN access only with --network, one private --listen address,
// --allowed-hosts and an HTTPS certificate. Runs as a console process, a Windows service or a systemd notify service. See ServerConfiguration.
if (ServerConfiguration.Informational(args) is { } information)
{
    Console.Out.WriteLine(information);
    return 0;
}
if (args.Contains("--backup-key"))
{
    // Local host backup key management: no listener; the key value is never printed.
    try
    {
        var (action, path, data) = ServerConfiguration.BackupKey(args, Environment.GetEnvironmentVariable);
        var result = action switch
        {
            "create" => SapLens.Application.Backups.BackupKeys.Create(path, data),
            "use" => SapLens.Application.Backups.BackupKeys.Use(path, data),
            "export" => SapLens.Application.Backups.BackupKeys.Export(path, data),
            _ => SapLens.Application.Backups.BackupKeys.Status(data),
        };
        Console.Out.WriteLine(result.ToJsonString());
        return 0;
    }
    catch (Exception error) when (error is InvalidOperationException or SapLens.Application.Backups.BackupException or IOException or UnauthorizedAccessException)
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
        Console.Out.WriteLine(SapLens.Application.Accounts.AccountDiagnostics.Report(SapLens.Application.Accounts.AccountDiagnostics.Check(store, username, password)));
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
    var app = SapLensHost.Build(settings, [], builder =>
    {
        builder.Services.AddWindowsService(o => o.ServiceName = "SapLens2");
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
