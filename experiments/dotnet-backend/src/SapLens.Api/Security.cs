using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;

namespace SapLens.Api;

/// <summary>Request boundary: correlation id, loopback Host header (DNS-rebinding defence), same-origin check for state-changing requests, and a constant-time
/// token check for every /api request. Health endpoints are open and expose no data.</summary>
public sealed partial class RequestBoundary(RequestDelegate next, HostSettings settings, ILogger<RequestBoundary> logger)
{
    public const string TokenHeader = "X-SAP-Lens-Token";
    public const string CorrelationHeader = "X-Correlation-ID";
    private readonly byte[] _token = Encoding.UTF8.GetBytes(settings.AccessToken);

    [GeneratedRegex("^[A-Za-z0-9-]{1,64}$")]
    private static partial Regex CorrelationPattern();

    public async Task InvokeAsync(HttpContext context)
    {
        var supplied = context.Request.Headers[CorrelationHeader].ToString();
        var correlation = CorrelationPattern().IsMatch(supplied) ? supplied : Guid.NewGuid().ToString("N");
        context.TraceIdentifier = correlation;
        context.Response.Headers[CorrelationHeader] = correlation;
        context.Response.Headers.XContentTypeOptions = "nosniff";
        context.Response.Headers["Referrer-Policy"] = "no-referrer";
        using var scope = logger.BeginScope(new Dictionary<string, object> { ["CorrelationId"] = correlation });

        var host = context.Request.Host.Host;
        if (host is not ("127.0.0.1" or "localhost" or "[::1]" or "::1")) { await Reject(context, 421, "Unexpected host."); return; }
        var path = context.Request.Path;
        if (path.StartsWithSegments("/api"))
        {
            context.Response.Headers.CacheControl = "no-store";
            var origin = context.Request.Headers.Origin.ToString();
            if (!HttpMethods.IsGet(context.Request.Method) && !HttpMethods.IsHead(context.Request.Method) && origin.Length > 0
                && !string.Equals(origin, $"{context.Request.Scheme}://{context.Request.Host}", StringComparison.OrdinalIgnoreCase))
            { await Reject(context, 403, "Cross-origin request refused."); return; }
            var token = Encoding.UTF8.GetBytes(context.Request.Headers[TokenHeader].ToString());
            if (!CryptographicOperations.FixedTimeEquals(token, _token)) { await Reject(context, 401, "Missing or invalid access token."); return; }
        }
        await next(context);
    }

    private static Task Reject(HttpContext context, int status, string detail)
    {
        context.Response.StatusCode = status;
        return context.Response.WriteAsJsonAsync(new { type = "about:blank", title = detail, status, correlation_id = context.TraceIdentifier }, (System.Text.Json.JsonSerializerOptions?)null, "application/problem+json");
    }
}
