using Microsoft.AspNetCore.Builder;
using Microsoft.Extensions.DependencyInjection;
using SapLens.Api;
using SapLens.Persistence;

namespace SapLens.Desktop;

/// <summary>Desktop lifecycle: single instance, private data directory, in-process core on an OS-assigned loopback port with a per-run token, readiness
/// before the window navigates, graceful stop when the window closes. No Python and no system-wide .NET are needed (self-contained publish).</summary>
internal static class Program
{
    [STAThread]
    private static int Main()
    {
        using var single = new Mutex(true, @"Local\SapLens2Prototype", out var first);
        if (!first) { MessageBox.Show("SAP Lens 2 prototype is already running.", "SAP Lens 2 prototype"); return 1; }
        ApplicationConfiguration.Initialize();

        var root = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "SAP Lens 2 Prototype");
        WebApplication app;
        try
        {
            app = SapLensHost.Build(new HostSettings
            {
                DataDirectory = Path.Combine(root, "data"), Mode = HostMode.Desktop, Url = "http://127.0.0.1:0", AccessToken = HostSettings.NewToken(),
                FrontendDirectory = Path.Combine(AppContext.BaseDirectory, "frontend"), PrincipalName = Environment.UserName, JsonConsoleLogging = false,
            });
            app.StartAsync().GetAwaiter().GetResult();
        }
        catch (Exception error)
        {
            MessageBox.Show($"SAP Lens 2 prototype could not start: {error.Message}", "SAP Lens 2 prototype", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 2;
        }
        var database = app.Services.GetRequiredService<DatabaseMaintenance>();
        if (!database.Ready)
        {
            MessageBox.Show($"The local database is not ready: {database.NotReadyReason}", "SAP Lens 2 prototype", MessageBoxButtons.OK, MessageBoxIcon.Error);
            app.StopAsync().GetAwaiter().GetResult();
            return 3;
        }
        var origin = new Uri(app.Urls.First());
        var token = app.Services.GetRequiredService<HostSettings>().AccessToken;
        using (var window = new MainWindow(origin, token, Path.Combine(root, "webview2"))) System.Windows.Forms.Application.Run(window);
        // Graceful stop: the worker hands an unfinished job back (Queued) and SQLite connections close before the process exits.
        app.StopAsync().GetAwaiter().GetResult();
        app.DisposeAsync().AsTask().GetAwaiter().GetResult();
        return 0;
    }
}
