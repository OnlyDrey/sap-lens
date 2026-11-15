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
        // Content root is the application directory (never the current working directory); no file is read from it at runtime.
        var builder = WebApplication.CreateSlimBuilder(new WebApplicationOptions { Args = args ?? [], ContentRootPath = AppContext.BaseDirectory });
        builder.WebHost.UseUrls(settings.Url);
        builder.WebHost.ConfigureKestrel(k => { k.AddServerHeader = false; k.Limits.MaxRequestBodySize = 1024 * 1024; });
        builder.Logging.ClearProviders();
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
        app.UseExceptionHandler();
        app.UseMiddleware<RequestBoundary>();
        app.UseDefaultFiles(new DefaultFilesOptions { FileProvider = ui });
        app.UseStaticFiles(new StaticFileOptions { FileProvider = ui, OnPrepareResponse = c => c.Context.Response.Headers.CacheControl = "no-cache" });
        app.MapOpenApi("/openapi/{documentName}.json");
        Endpoints.Map(app);
        MapSession(app, settings);
        return app;
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
            if (sessions.Throttled()) return Results.Problem("Too many failed sign-ins. Wait a minute.", statusCode: 429);
            var form = await http.Request.ReadFormAsync(http.RequestAborted);
            var boundary = http.RequestServices.GetRequiredService<RequestBoundaryTokenCheck>();
            if (!boundary.Matches(form["token"].ToString()))
            {
                sessions.RecordFailure();
                log.LogWarning("Failed sign-in");
                return Results.Problem("Invalid access token.", statusCode: 401);
            }
            http.Response.Cookies.Append(SessionStore.CookieName, sessions.Create(), new CookieOptions
            {
                HttpOnly = true, SameSite = SameSiteMode.Strict, Secure = http.Request.IsHttps, Path = "/", MaxAge = SessionStore.Lifetime, IsEssential = true,
            });
            return Results.Redirect("/", permanent: false, preserveMethod: false);
        }).DisableAntiforgery().ExcludeFromDescription();
        app.MapPost("/auth/logout", (HttpContext http, SessionStore sessions) =>
        {
            sessions.Revoke(http.Request.Cookies[SessionStore.CookieName]);
            http.Response.Cookies.Delete(SessionStore.CookieName, new CookieOptions { Path = "/" });
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
