using System.Text.Json;
using SapLens.Application;
using SapLens.Persistence;

namespace SapLens.Api;

/// <summary>Builds the one application host used by the Server entry point, the Desktop shell and the integration tests.</summary>
public static class SapLensHost
{
    public static WebApplication Build(HostSettings settings, string[]? args = null, Action<WebApplicationBuilder>? configure = null)
    {
        settings.Validate();
        DatabaseOptions.ValidateLocal(settings.DataDirectory);
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
        // TLS handshake failures are logged by Kestrel at Debug (exception and connection id, no secrets); keep them, they are the only server-side
        // trace of a client that "just sees EOF".
        builder.Logging.AddFilter("Microsoft.AspNetCore.Server.Kestrel.Https", LogLevel.Debug);
        if (settings.JsonConsoleLogging) builder.Logging.AddJsonConsole(o => { o.IncludeScopes = true; o.UseUtcTimestamp = true; o.TimestampFormat = "yyyy-MM-ddTHH:mm:ss.fffZ"; });
        builder.Services.Configure<HostOptions>(o => o.ShutdownTimeout = TimeSpan.FromSeconds(15));
        builder.Services.ConfigureHttpJsonOptions(o => o.SerializerOptions.PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower);
        builder.Services.AddSingleton(settings);
        builder.Services.AddSapLensCore(new DatabaseOptions { DataDirectory = settings.DataDirectory }, new WorkerOptions { Enabled = settings.WorkerEnabled });
        builder.Services.AddSingleton<SessionStore>();
        builder.Services.AddSingleton<RequestBoundaryTokenCheck>();
        builder.Services.AddProblemDetails();
        builder.Services.AddExceptionHandler<ProblemMapper>();
        builder.Services.AddOpenApi("v1", o => o.AddDocumentTransformer((doc, _, _) =>
        {
            doc.Info.Title = "SAP Lens 2.0 prototype API";
            doc.Info.Version = "v1";
            return Task.CompletedTask;
        }));
        configure?.Invoke(builder);

        var app = builder.Build();
        if (tls is not null && !ReferenceEquals(tls, settings.Certificate)) app.Lifetime.ApplicationStopped.Register(tls.Dispose);
        var startup = app.Services.GetRequiredService<ILoggerFactory>().CreateLogger("SapLens.Startup");
        startup.LogInformation("Listening on {Address}:{Port} ({Scheme}), network access {Network}, allowed hosts {Hosts}", settings.ListenAddress, settings.Port,
            settings.Https ? "https" : "http", settings.NetworkAccess ? "enabled" : "disabled", settings.AllowedHosts.Count == 0 ? "loopback only" : string.Join(",", settings.AllowedHosts));
        if (settings.Certificate is { } cert)
        {
            startup.LogInformation("TLS certificate {Subject}, thumbprint {Thumbprint}, valid until {NotAfter:u}", cert.Subject, cert.Thumbprint, cert.NotAfter);
            foreach (var warning in CertificatePolicy.Validate(cert, settings.AllowedHosts, DateTimeOffset.UtcNow).Warnings) startup.LogWarning("TLS certificate: {Warning}", warning);
        }
        app.UseExceptionHandler();
        app.UseMiddleware<RequestBoundary>();
        app.UseDefaultFiles(new DefaultFilesOptions { FileProvider = ui });
        app.UseStaticFiles(new StaticFileOptions { FileProvider = ui, OnPrepareResponse = c => c.Context.Response.Headers.CacheControl = "no-cache" });
        app.MapOpenApi("/openapi/{documentName}.json");
        Endpoints.Map(app);
        V1Compatibility.Map(app);
        MapSession(app, settings);
        return app;
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
            principal = settings.PrincipalName, mode = settings.Mode.ToString().ToLowerInvariant(),
            authentication = http.Request.Headers.ContainsKey(RequestBoundary.TokenHeader) ? "token" : "session",
        }).WithName("GetSession");
        if (settings.Mode != HostMode.Server) return; // Desktop never needs a sign-in: the shell supplies the token.
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
