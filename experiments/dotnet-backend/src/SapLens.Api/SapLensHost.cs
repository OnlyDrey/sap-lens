using System.Text.Json;
using Microsoft.Extensions.FileProviders;
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
        var builder = WebApplication.CreateSlimBuilder(new WebApplicationOptions { Args = args ?? [], ContentRootPath = AppContext.BaseDirectory });
        builder.WebHost.UseUrls(settings.Url);
        builder.WebHost.ConfigureKestrel(k => { k.AddServerHeader = false; k.Limits.MaxRequestBodySize = 1024 * 1024; });
        builder.Logging.ClearProviders();
        if (settings.JsonConsoleLogging) builder.Logging.AddJsonConsole(o => { o.IncludeScopes = true; o.UseUtcTimestamp = true; o.TimestampFormat = "yyyy-MM-ddTHH:mm:ss.fffZ"; });
        else builder.Logging.AddSimpleConsole(o => o.IncludeScopes = true);
        builder.Services.Configure<HostOptions>(o => o.ShutdownTimeout = TimeSpan.FromSeconds(15));
        builder.Services.ConfigureHttpJsonOptions(o => o.SerializerOptions.PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower);
        builder.Services.AddSingleton(settings);
        builder.Services.AddSapLensCore(new DatabaseOptions { DataDirectory = settings.DataDirectory }, new WorkerOptions { Enabled = settings.WorkerEnabled });
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
        app.MapOpenApi("/openapi/{documentName}.json");
        Endpoints.Map(app);
        if (settings.FrontendDirectory is { } dist && File.Exists(Path.Combine(dist, "index.html")))
        {
            var files = new PhysicalFileProvider(Path.GetFullPath(dist));
            app.UseDefaultFiles(new DefaultFilesOptions { FileProvider = files });
            app.UseStaticFiles(new StaticFileOptions { FileProvider = files });
            app.MapFallback(async context =>
            {
                if (context.Request.Path.StartsWithSegments("/api")) { context.Response.StatusCode = 404; return; }
                context.Response.ContentType = "text/html; charset=utf-8";
                await context.Response.SendFileAsync(files.GetFileInfo("index.html"));
            });
        }
        return app;
    }
}
