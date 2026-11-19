using System.Text.Json;
using AuthLens.Application;
using AuthLens.Application.Accounts;
using AuthLens.Application.Backups;
using AuthLens.Persistence;

namespace AuthLens.Api;

/// <summary>Builds the one application host used by the Server entry point, the Desktop shell and the integration tests.</summary>
public static class AuthLensHost
{
    public static WebApplication Build(HostSettings settings, string[]? args = null, Action<WebApplicationBuilder>? configure = null)
    {
        settings.Validate();
        var icu = AuthLens.Domain.Text.PythonText.VerifyRuntime();    // Unicode text handling needs ICU; refuse to start without it
        DatabaseOptions.ValidateLocal(settings.DataDirectory);
        RefuseInsideApplication(settings.DataDirectory);
        // A confirmed restore is applied before anything opens the database or the account store; it rolls back by itself on failure.
        ApplicationBackups.ProductVersion = V1Compatibility.Version;
        var migrated = V1DataMigration.ApplyPending(settings.DataDirectory, DateTimeOffset.UtcNow);
        var restored = ApplicationBackups.ApplyPending(settings.DataDirectory, DateTimeOffset.UtcNow);
        DatabaseOptions.RefuseUnadoptedLegacy(settings.DataDirectory);   // never start beside an unconverted SAP Lens database
        var ui = UiAssets.Create();
        var tls = PrepareCertificate(settings);
        // Content root is the application directory (never the current working directory); no file is read from it at runtime.
        var builder = WebApplication.CreateSlimBuilder(new WebApplicationOptions { Args = args ?? [], ContentRootPath = AppContext.BaseDirectory });
        builder.WebHost.ConfigureKestrel(k =>
        {
            k.AddServerHeader = false;
            k.Limits.MaxRequestBodySize = 1024 * 1024;
            // Exactly one endpoint, from validated settings; ASPNETCORE_URLS and similar are not used.
            k.Listen(settings.ListenAddress, settings.Port, listen =>
            {
                if (tls is not null)
                    listen.UseHttps(https => { https.ServerCertificate = tls; https.SslProtocols = CertificatePolicy.ServerProtocols; });
            });
        });
        builder.Logging.ClearProviders();
        // Log levels are part of the executable (no appsettings.json is shipped or required next to it).
        builder.Logging.SetMinimumLevel(LogLevel.Information);
        builder.Logging.AddFilter("Microsoft.AspNetCore", LogLevel.Warning);
        builder.Logging.AddFilter("Microsoft.EntityFrameworkCore", LogLevel.Warning);
        // TLS handshake failures are logged by Kestrel at Debug (exception and connection id, no secrets); keep them, they are the only server-side
        // trace of a client that "just sees EOF".
        builder.Logging.AddFilter("Microsoft.AspNetCore.Server.Kestrel.Https", LogLevel.Debug);
        if (settings.JsonConsoleLogging) builder.Logging.AddJsonConsole(o => { o.IncludeScopes = true; o.UseUtcTimestamp = true; o.TimestampFormat = "yyyy-MM-ddTHH:mm:ss.fffZ"; });
        builder.Services.Configure<HostOptions>(o => o.ShutdownTimeout = TimeSpan.FromSeconds(15));
        builder.Services.ConfigureHttpJsonOptions(o => o.SerializerOptions.PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower);
        builder.Services.AddSingleton(settings);
        builder.Services.AddAuthLensCore(new DatabaseOptions { DataDirectory = settings.DataDirectory }, new WorkerOptions { Enabled = settings.WorkerEnabled });
        builder.Services.AddSingleton<SessionStore>();
        builder.Services.AddSingleton<V1Settings>();
        builder.Services.AddSingleton<DataLoadGate>();
        builder.Services.AddSingleton<RefreshScheduleState>();
        builder.Services.AddSingleton<FunctionalGroupStore>();
        builder.Services.AddSingleton<LogoStore>();
        builder.Services.AddSingleton<SodPeriodStore>();
        builder.Services.AddSingleton<SodReviewStore>();
        builder.Services.AddSingleton<ApplicationBackups>();
        builder.Services.AddSingleton<AuthLens.Application.Retention.DataRetention>();
        builder.Services.AddHostedService<BackupScheduler>();
        // The scheduled refresh imports through the job worker; without a worker (--no-worker) nothing would process it.
        if (settings.WorkerEnabled) builder.Services.AddHostedService<RefreshScheduler>();
        builder.Services.AddSingleton<RequestBoundaryTokenCheck>();
        if (settings.Authentication == AuthenticationMode.Accounts)
        {
            // Created empty for a fresh installation (setup required), validated otherwise; an unusable store stops startup.
            var accounts = new AccountStore(AccountStore.For(settings.DataDirectory), TimeProvider.System);
            accounts.Prepare();
            builder.Services.AddSingleton(accounts);
        }
        builder.Services.AddProblemDetails();
        builder.Services.AddExceptionHandler<ProblemMapper>();
        builder.Services.AddOpenApi("v1", o => o.AddDocumentTransformer((doc, _, _) =>
        {
            doc.Info.Title = "AuthLens API";
            doc.Info.Version = "v1";
            return Task.CompletedTask;
        }));
        configure?.Invoke(builder);

        var app = builder.Build();
        if (tls is not null && !ReferenceEquals(tls, settings.Certificate)) app.Lifetime.ApplicationStopped.Register(tls.Dispose);
        var startup = app.Services.GetRequiredService<ILoggerFactory>().CreateLogger("AuthLens.Startup");
        startup.LogInformation("Listening on {Address}:{Port} ({Scheme}), network access {Network}, allowed hosts {Hosts}", settings.ListenAddress, settings.Port,
            settings.Https ? "https" : "http", settings.NetworkAccess ? "enabled" : "disabled", settings.AllowedHosts.Count == 0 ? "loopback only" : string.Join(",", settings.AllowedHosts));
        startup.LogInformation("Unicode: ICU {Icu}, casefold table Unicode {Unicode}", icu, AuthLens.Domain.Text.PythonText.UnicodeVersion);
        if (migrated is not null) startup.LogWarning("SAP Lens 1 migration: {Outcome}", migrated);
        if (restored is not null) startup.LogWarning("Pending restore: {Outcome}", restored);
        if (settings.TrustedProxies.Count > 0)
            startup.LogInformation("Trusted reverse proxies {Proxies} ({Hops} hop(s)): X-Forwarded-For, -Proto and -Host applied from these peers only", string.Join(",", settings.TrustedProxies), settings.TrustedProxyHops);
        if (settings.Certificate is { } cert)
        {
            startup.LogInformation("TLS certificate {Subject}, thumbprint {Thumbprint}, valid until {NotAfter:u}", cert.Subject, cert.Thumbprint, cert.NotAfter);
            foreach (var warning in CertificatePolicy.Validate(cert, settings.AllowedHosts, DateTimeOffset.UtcNow).Warnings) startup.LogWarning("TLS certificate: {Warning}", warning);
        }
        ProxyTrust.Use(app, settings);   // first: peer capture, then forwarded headers from trusted proxies only
        app.UseExceptionHandler();
        app.UseMiddleware<RequestBoundary>();
        app.UseDefaultFiles(new DefaultFilesOptions { FileProvider = ui });
        app.UseStaticFiles(new StaticFileOptions { FileProvider = ui, OnPrepareResponse = c => c.Context.Response.Headers.CacheControl = "no-cache" });
        app.MapOpenApi("/openapi/{documentName}.json");
        // Product identity of this host (the embedded React build's v1 identity file is not served; see UiAssets).
        app.MapGet("/" + UiAssets.ProductIdentityFile, () => Results.Content(ProductIdentity.ToJson().ToJsonString(), "application/json"));
        Endpoints.Map(app);
        V1Compatibility.Map(app);
        MapSession(app, settings);
        return app;
    }

    /// <summary>Runtime data (database, token, accounts, logs) never lives in the application folder, which is replaced on every upgrade and readable by
    /// everyone who can run the program.</summary>
    internal static void RefuseInsideApplication(string dataDirectory, string? applicationDirectory = null)
    {
        var app = Path.GetFullPath(applicationDirectory ?? AppContext.BaseDirectory).TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
        var data = Path.GetFullPath(dataDirectory).TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
        var comparison = OperatingSystem.IsWindows() ? StringComparison.OrdinalIgnoreCase : StringComparison.Ordinal;
        if (data.Equals(app, comparison) || data.StartsWith(app + Path.DirectorySeparatorChar, comparison))
            throw new InvalidOperationException($"The data directory must be outside the application directory ({app}).");
    }

    /// <summary>The certificate Kestrel will use, prepared for this operating system's TLS stack and proven by a real handshake before the host is built:
    /// an unusable certificate stops startup with the server-side reason instead of producing EOF failures for every client.</summary>
    private static System.Security.Cryptography.X509Certificates.X509Certificate2? PrepareCertificate(HostSettings settings)
    {
        if (settings.Certificate is null) return null;
        var prepared = CertificatePolicy.PrepareForServer(settings.Certificate);
        var problem = CertificatePolicy.VerifyTlsHandshakeAsync(prepared, TimeSpan.FromSeconds(15)).GetAwaiter().GetResult();
        if (problem is null) return prepared;
        if (!ReferenceEquals(prepared, settings.Certificate)) prepared.Dispose();
        throw new InvalidOperationException($"The TLS certificate cannot be used by this system's TLS stack ({problem}).");
    }

    private static void MapSession(WebApplication app, HostSettings settings)
    {
        app.MapGet("/api/v1/session", (HttpContext http) => new
        {
            principal = Actors.Name(http), mode = settings.Mode.ToString().ToLowerInvariant(),
            authentication = http.Request.Headers.ContainsKey(RequestBoundary.TokenHeader) ? "token" : "session",
        }).WithName("GetSession");
        // Desktop never needs a sign-in (the shell supplies the token); Accounts mode signs in through the React UI and /api/auth/login.
        if (settings.Mode != HostMode.Server || settings.Authentication == AuthenticationMode.Accounts) return;
        app.MapPost("/auth/login", async (HttpContext http, SessionStore sessions, ILogger<SessionStore> log) =>
        {
            var client = http.Connection.RemoteIpAddress?.ToString() ?? "unknown";
            if (sessions.Throttled(client)) return Results.Problem("Too many failed sign-ins. Wait a minute.", statusCode: 429);
            var form = await http.Request.ReadFormAsync(http.RequestAborted);
            var boundary = http.RequestServices.GetRequiredService<RequestBoundaryTokenCheck>();
            if (!boundary.Matches(form["token"].ToString()))
            {
                sessions.RecordFailure(client);
                log.LogWarning("Failed sign-in from {Client}", client);
                return Results.Problem("Invalid access token.", statusCode: 401);
            }
            http.Response.Cookies.Append(SessionStore.CookieNameFor(http.Request.IsHttps), sessions.Create(), new CookieOptions
            {
                HttpOnly = true, SameSite = SameSiteMode.Strict, Secure = http.Request.IsHttps, Path = "/", MaxAge = SessionStore.Lifetime, IsEssential = true,
            });
            return Results.Redirect("/", permanent: false, preserveMethod: false);
        }).DisableAntiforgery().ExcludeFromDescription();
        app.MapPost("/auth/logout", (HttpContext http, SessionStore sessions) =>
        {
            var name = SessionStore.CookieNameFor(http.Request.IsHttps);
            sessions.Revoke(http.Request.Cookies[name]);
            http.Response.Cookies.Delete(name, new CookieOptions { Path = "/", Secure = http.Request.IsHttps, HttpOnly = true, SameSite = SameSiteMode.Strict });
            return Results.Redirect("/login.html");
        }).ExcludeFromDescription();
    }
}

/// <summary>Constant-time comparison of a submitted token, shared by the sign-in endpoint.</summary>
public sealed class RequestBoundaryTokenCheck(HostSettings settings)
{
    private readonly byte[] _token = System.Text.Encoding.UTF8.GetBytes(settings.AccessToken);
    public bool Matches(string? supplied) => System.Security.Cryptography.CryptographicOperations.FixedTimeEquals(System.Text.Encoding.UTF8.GetBytes(supplied ?? ""), _token);
}
