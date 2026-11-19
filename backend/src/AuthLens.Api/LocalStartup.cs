using System.Net;
using System.Text;
using System.Text.Json;

namespace AuthLens.Api;

public sealed record ProbeResult(bool Ok, string? Problem);

/// <summary>Readiness as the window will experience it, checked over the real loopback listener: /health/ready answers 200 and "/" serves the embedded UI
/// entry point (not a 404). A not-ready database answers 503 with a reason, which is final and reported at once.</summary>
public static class StartupProbe
{
    /// <param name="token">Needed only against a Server, whose application document redirects anonymous clients to sign-in; the Desktop never redirects.</param>
    public static async Task<ProbeResult> WaitAsync(Uri origin, TimeSpan timeout, CancellationToken cancellation = default, string? token = null)
    {
        // Loopback only, never through a configured proxy.
        using var http = new HttpClient(new SocketsHttpHandler { UseProxy = false, ConnectTimeout = TimeSpan.FromSeconds(2), AllowAutoRedirect = false }) { BaseAddress = origin, Timeout = TimeSpan.FromSeconds(5) };
        if (token is not null) http.DefaultRequestHeaders.Add(RequestBoundary.TokenHeader, token);
        var deadline = DateTime.UtcNow + timeout;
        var last = "no answer";
        while (DateTime.UtcNow < deadline)
        {
            cancellation.ThrowIfCancellationRequested();
            try
            {
                using var ready = await http.GetAsync("/health/ready", cancellation);
                if (ready.StatusCode == HttpStatusCode.ServiceUnavailable)
                {
                    var reason = JsonDocument.Parse(await ready.Content.ReadAsStringAsync(cancellation)).RootElement.TryGetProperty("reason", out var r) ? r.GetString() : null;
                    return new ProbeResult(false, $"The local database is not ready: {reason ?? "unknown reason"}");
                }
                if (ready.IsSuccessStatusCode)
                {
                    using var page = await http.GetAsync("/", cancellation);
                    var html = await page.Content.ReadAsStringAsync(cancellation);
                    return page.StatusCode == HttpStatusCode.OK && html.Contains(UiAssets.Marker, StringComparison.Ordinal)
                        ? new ProbeResult(true, null)
                        : new ProbeResult(false, $"The AuthLens user interface is not served (GET / answered {(int)page.StatusCode}: {html[..Math.Min(html.Length, 160)].ReplaceLineEndings(" ")}).");
                }
                last = $"/health/ready answered {(int)ready.StatusCode}";
            }
            catch (HttpRequestException error) { last = error.Message; }
            catch (TaskCanceledException) when (!cancellation.IsCancellationRequested) { last = "request timed out"; }
            await Task.Delay(100, cancellation);
        }
        return new ProbeResult(false, $"The local service did not become ready within {timeout.TotalSeconds:0} s ({last}).");
    }
}

public sealed record StartupOutcome(WebApplication? App, Uri? Origin, string? Error)
{
    public bool Ok => App is not null && Error is null;
}

/// <summary>Start sequence for the in-process host (Desktop): build, start on the loopback listener, probe readiness and the UI, and on any failure stop
/// the host again and return one actionable message. Messages and logs never contain the access token.</summary>
public static class LocalStartup
{
    public static async Task<StartupOutcome> StartAsync(HostSettings settings, ILogger log, TimeSpan timeout, Action<WebApplicationBuilder>? configure = null,
        CancellationToken cancellation = default)
    {
        WebApplication? app = null;
        try
        {
            log.LogInformation("Starting local service (mode {Mode}, data directory {DataDirectory})", settings.Mode, settings.DataDirectory);
            app = AuthLensHost.Build(settings, null, configure);
            await app.StartAsync(cancellation);
        }
        catch (Exception error)
        {
            log.LogError(error, "Local service failed to start");
            await StopQuietlyAsync(app);
            return new StartupOutcome(null, null, $"The local service could not start: {error.Message}");
        }
        var origin = new Uri(app.Urls.First());
        var probe = await StartupProbe.WaitAsync(origin, timeout, cancellation);
        if (probe.Ok)
        {
            log.LogInformation("Local service ready at {Origin}", origin);
            return new StartupOutcome(app, origin, null);
        }
        log.LogError("Local service not ready: {Problem}", probe.Problem);
        await StopQuietlyAsync(app);
        return new StartupOutcome(null, origin, probe.Problem);
    }

    public static async Task StopQuietlyAsync(WebApplication? app, TimeSpan? timeout = null)
    {
        if (app is null) return;
        using var cts = new CancellationTokenSource(timeout ?? TimeSpan.FromSeconds(15));
        try { await app.StopAsync(cts.Token); } catch (Exception) { /* best effort: the process is ending */ }
        await app.DisposeAsync();
    }
}

/// <summary>Minimal append-only file logger (the Desktop is a WinExe without a console). One line per entry, UTC timestamps, exception type and
/// message without stack data from user input. The access token is never passed to a logger.</summary>
public sealed class FileLoggerProvider : ILoggerProvider
{
    private readonly object _gate = new();
    private readonly string _path;

    public FileLoggerProvider(string directory, string prefix)
    {
        Directory.CreateDirectory(directory);
        _path = Path.Combine(directory, $"{prefix}-{DateTime.UtcNow:yyyyMMdd}.log");
    }

    public string FilePath => _path;
    public ILogger CreateLogger(string categoryName) => new FileLogger(this, categoryName);
    public void Dispose() { }

    internal void Write(string line)
    {
        lock (_gate) File.AppendAllText(_path, line + Environment.NewLine, Encoding.UTF8);
    }

    private sealed class FileLogger(FileLoggerProvider owner, string category) : ILogger
    {
        public IDisposable? BeginScope<TState>(TState state) where TState : notnull => null;
        public bool IsEnabled(LogLevel logLevel) =>
            category.StartsWith("Microsoft.AspNetCore.Server.Kestrel.Https", StringComparison.Ordinal) ? logLevel >= LogLevel.Debug // TLS handshake failures
            : logLevel >= LogLevel.Information && (logLevel >= LogLevel.Warning || !category.StartsWith("Microsoft.", StringComparison.Ordinal)
                || category.StartsWith("Microsoft.Hosting.Lifetime", StringComparison.Ordinal));

        public void Log<TState>(LogLevel logLevel, EventId eventId, TState state, Exception? exception, Func<TState, Exception?, string> formatter)
        {
            if (!IsEnabled(logLevel)) return;
            var line = $"{DateTime.UtcNow:yyyy-MM-ddTHH:mm:ss.fffZ} {logLevel,-11} {category}: {formatter(state, exception)}";
            if (exception is not null) line += $" | {exception.GetType().Name}: {exception.Message}";
            try { owner.Write(line.ReplaceLineEndings(" ")); } catch (IOException) { }
        }
    }
}
