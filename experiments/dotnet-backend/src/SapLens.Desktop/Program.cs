using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Logging;
using SapLens.Api;
using WinFormsApp = System.Windows.Forms.Application;

namespace SapLens.Desktop;

/// <summary>Desktop lifecycle: single instance, private data and log directories, in-process core on an OS-assigned loopback port with a per-run token,
/// readiness and UI probe before the window navigates, an actionable message on failure, graceful stop when the window closes.
/// Arguments: [--data-dir ABSOLUTE_PATH] [--self-check]. --self-check starts the service, probes it, logs the result and exits without a window
/// (exit code 0 ready, 2 start or readiness failure, 1 already running): the SSH-verifiable part of the Desktop.</summary>
internal static class Program
{
    private const string Title = "SAP Lens 2 prototype";
    private static readonly TimeSpan StartupTimeout = TimeSpan.FromSeconds(30);

    [STAThread]
    private static int Main(string[] args)
    {
        var selfCheck = args.Contains("--self-check", StringComparer.OrdinalIgnoreCase);
        var index = Array.FindIndex(args, a => string.Equals(a, "--data-dir", StringComparison.OrdinalIgnoreCase));
        var root = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "SAP Lens 2 Prototype");
        var dataDirectory = index >= 0 && index + 1 < args.Length ? Path.GetFullPath(args[index + 1]) : Path.Combine(root, "data");
        using var logs = new FileLoggerProvider(Path.Combine(root, "logs"), selfCheck ? "self-check" : "desktop");
        using var factory = LoggerFactory.Create(b => b.AddProvider(logs));
        var log = factory.CreateLogger("SapLens.Desktop");
        log.LogInformation("Desktop starting (version {Version}, self-check {SelfCheck})", typeof(Program).Assembly.GetName().Version, selfCheck);

        using var single = new Mutex(true, @"Local\SapLens2Prototype", out var first);
        if (!first)
        {
            log.LogWarning("Another instance is already running");
            if (!selfCheck) MessageBox.Show("SAP Lens 2 prototype is already running.", Title);
            return 1;
        }
        if (!selfCheck)
        {
            ApplicationConfiguration.Initialize();
            WinFormsApp.SetUnhandledExceptionMode(UnhandledExceptionMode.CatchException);
            WinFormsApp.ThreadException += (_, e) => Fatal(log, logs, e.Exception);
            AppDomain.CurrentDomain.UnhandledException += (_, e) => log.LogCritical("Unhandled exception: {Type}", e.ExceptionObject.GetType().Name);
        }

        var settings = new HostSettings
        {
            DataDirectory = dataDirectory, Mode = HostMode.Desktop, Port = 0, AccessToken = HostSettings.NewToken(),
            PrincipalName = Environment.UserName, JsonConsoleLogging = false,
        };
        var outcome = LocalStartup.StartAsync(settings, log, StartupTimeout, b => b.Logging.AddProvider(logs)).GetAwaiter().GetResult();
        if (!outcome.Ok)
        {
            if (!selfCheck)
                MessageBox.Show($"{outcome.Error}\n\nDetails are in the log file:\n{logs.FilePath}\n\nClose other SAP Lens 2 windows, check that the data folder is on a local disk and writable, then start again.",
                    Title, MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 2;
        }
        var app = outcome.App!;
        try
        {
            if (selfCheck)
            {
                log.LogInformation("Self-check passed: service ready and UI served at {Origin}", outcome.Origin);
                return 0;
            }
            using var window = new MainWindow(outcome.Origin!, app.Services.GetRequiredService<HostSettings>().AccessToken,
                Path.Combine(root, "webview2"), log, logs.FilePath);
            WinFormsApp.Run(window);
            return 0;
        }
        finally
        {
            // Graceful stop: a running import is handed back (Queued) and SQLite connections close before the process exits.
            log.LogInformation("Desktop stopping");
            LocalStartup.StopQuietlyAsync(app).GetAwaiter().GetResult();
            log.LogInformation("Desktop stopped");
        }
    }

    private static void Fatal(ILogger log, FileLoggerProvider logs, Exception error)
    {
        log.LogCritical(error, "Unhandled UI exception");
        MessageBox.Show($"An unexpected error occurred: {error.Message}\n\nLog: {logs.FilePath}", Title, MessageBoxButtons.OK, MessageBoxIcon.Error);
    }
}
