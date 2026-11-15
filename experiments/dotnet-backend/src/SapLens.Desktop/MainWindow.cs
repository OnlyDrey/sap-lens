using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

namespace SapLens.Desktop;

/// <summary>The WebView2 window. The access token never reaches page script: it is added to /api requests in the host's WebResourceRequested handler
/// (which also removes the bootstrap problem of passing a secret to the first page load). Navigation is confined to the loopback origin.</summary>
internal sealed class MainWindow : Form
{
    private readonly Uri _origin;
    private readonly string _token;
    private readonly string _profile;
    private readonly WebView2 _view = new() { Dock = DockStyle.Fill };

    public MainWindow(Uri origin, string token, string profile)
    {
        (_origin, _token, _profile) = (origin, token, profile);
        Text = "SAP Lens 2 prototype";
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
            MessageBox.Show("The Microsoft Edge WebView2 Runtime is not installed.", Text, MessageBoxButtons.OK, MessageBoxIcon.Error);
            Close();
            return;
        }
        var core = _view.CoreWebView2;
        core.Settings.AreDevToolsEnabled = false;
        core.Settings.IsStatusBarEnabled = false;
        core.Settings.AreDefaultContextMenusEnabled = false;
        core.AddWebResourceRequestedFilter($"{_origin.GetLeftPart(UriPartial.Authority)}/api/*", CoreWebView2WebResourceContext.All);
        core.WebResourceRequested += (_, e) => e.Request.Headers.SetHeader("X-SAP-Lens-Token", _token);
        core.NavigationStarting += (_, e) => { if (!SameOrigin(e.Uri)) e.Cancel = true; };
        core.NewWindowRequested += (_, e) => e.Handled = true;
        core.Navigate(_origin.ToString());
    }

    private bool SameOrigin(string uri) => Uri.TryCreate(uri, UriKind.Absolute, out var u) && u.Scheme == _origin.Scheme && u.Host == _origin.Host && u.Port == _origin.Port;
}
