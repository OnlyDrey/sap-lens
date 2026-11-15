using SapLens.Api;

// Server entry point (Windows and Linux). Defaults to http://127.0.0.1:18790. LAN access only with --network, one private --listen address,
// --allowed-hosts and an HTTPS certificate. Runs as a console process, a Windows service or a systemd notify service. See ServerConfiguration.
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
