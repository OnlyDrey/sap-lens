using Microsoft.Extensions.Logging;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

namespace AuthLens.Desktop;

/// <summary>The WebView2 window. Navigation starts only after the service and the UI were probed ready. The access token never reaches page script: it
/// is added to /api requests in WebResourceRequested. Navigation is confined to the loopback origin; failures are logged and shown with the log path.</summary>
internal sealed class MainWindow : Form
{
    private readonly Uri _origin;
    private readonly string _token;
    private readonly string _profile;
    private readonly ILogger _log;
    private readonly string _logFile;
    private readonly WebView2 _view = new() { Dock = DockStyle.Fill };

    public MainWindow(Uri origin, string token, string profile, ILogger log, string logFile)
    {
        (_origin, _token, _profile, _log, _logFile) = (origin, token, profile, log, logFile);
        Text = "AuthLens";
        Icon = Icon.ExtractAssociatedIcon(Environment.ProcessPath!);   // the embedded application icon (assets/branding/app.ico)
        Width = 1400;
        Height = 900;
        Controls.Add(_view);
        Load += async (_, _) => await InitializeAsync();
    }

    private async Task InitializeAsync()
    {
        try
        {
            var environment = await CoreWebView2Environment.CreateAsync(userDataFolder: _profile);
            await _view.EnsureCoreWebView2Async(environment);
        }
        catch (WebView2RuntimeNotFoundException)
        {
            Fail("The Microsoft Edge WebView2 Runtime is not installed. Install it from Microsoft or ask IT, then start AuthLens again.");
            return;
        }
        catch (Exception error)
        {
            _log.LogError(error, "WebView2 initialization failed");
            Fail($"The embedded browser could not start: {error.Message}");
            return;
        }
        var core = _view.CoreWebView2;
        _log.LogInformation("WebView2 {Version} initialized", core.Environment.BrowserVersionString);
        core.Settings.AreDevToolsEnabled = false;
        core.Settings.IsStatusBarEnabled = false;
        core.Settings.AreDefaultContextMenusEnabled = false;
        core.Settings.IsPasswordAutosaveEnabled = false;
        core.Settings.IsGeneralAutofillEnabled = false;
        var authority = _origin.GetLeftPart(UriPartial.Authority);
        core.AddWebResourceRequestedFilter($"{authority}/api/*", CoreWebView2WebResourceContext.All);
        core.WebResourceRequested += (_, e) => e.Request.Headers.SetHeader("X-SAP-Lens-Token", _token);
        core.NavigationStarting += (_, e) =>
        {
            if (SameOrigin(e.Uri)) return;
            e.Cancel = true;
            _log.LogWarning("Blocked navigation outside the local origin");
        };
        core.NewWindowRequested += (_, e) => e.Handled = true;
        core.NavigationCompleted += (_, e) =>
        {
            if (e.IsSuccess && e.HttpStatusCode is 200 or 0) { _log.LogInformation("UI loaded"); return; }
            _log.LogError("UI navigation failed: status {Status}, HTTP {Http}", e.WebErrorStatus, e.HttpStatusCode);
            Fail($"The user interface could not be loaded ({e.WebErrorStatus}, HTTP {e.HttpStatusCode}).");
        };
        core.ProcessFailed += (_, e) =>
        {
            _log.LogError("WebView2 process failed: {Kind} ({Reason})", e.ProcessFailedKind, e.Reason);
            if (e.ProcessFailedKind == CoreWebView2ProcessFailedKind.BrowserProcessExited) Fail("The embedded browser stopped unexpectedly.");
        };
        core.Navigate(_origin.ToString());
    }

    private void Fail(string message)
    {
        MessageBox.Show(this, $"{message}\n\nLog: {_logFile}", Text, MessageBoxButtons.OK, MessageBoxIcon.Error);
        Close();
    }

    private bool SameOrigin(string uri) => Uri.TryCreate(uri, UriKind.Absolute, out var u) && u.Scheme == _origin.Scheme && u.Host == _origin.Host && u.Port == _origin.Port;
}
