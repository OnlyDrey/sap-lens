using System.Collections.Concurrent;
using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;

namespace SapLens.Api;

/// <summary>Request boundary: correlation id, security headers, loopback Host header (DNS-rebinding defence), same-origin check for state-changing
/// requests, and authentication of every /api request by either the access-token header (Desktop shell, API clients) or, in Server mode only, an
/// HttpOnly session cookie obtained by submitting the token to /auth/login. Health endpoints and the static prototype UI are open and contain no data.</summary>
public sealed partial class RequestBoundary(RequestDelegate next, HostSettings settings, SessionStore sessions, RequestBoundaryTokenCheck token, ILogger<RequestBoundary> logger)
{
    public const string TokenHeader = "X-SAP-Lens-Token";
    public const string CorrelationHeader = "X-Correlation-ID";
    public const string ContentSecurityPolicy =
        "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'; object-src 'none'";
    [GeneratedRegex("^[A-Za-z0-9-]{1,64}$")]
    private static partial Regex CorrelationPattern();

    public async Task InvokeAsync(HttpContext context)
    {
        var supplied = context.Request.Headers[CorrelationHeader].ToString();
        var correlation = CorrelationPattern().IsMatch(supplied) ? supplied : Guid.NewGuid().ToString("N");
        context.TraceIdentifier = correlation;
        var headers = context.Response.Headers;
        headers[CorrelationHeader] = correlation;
        headers.XContentTypeOptions = "nosniff";
        // same-origin, not no-referrer: with no-referrer Chromium (and WebView2) sends "Origin: null" on form posts, which the origin check rejects.
        headers["Referrer-Policy"] = "same-origin";
        headers.XFrameOptions = "DENY";
        headers.ContentSecurityPolicy = ContentSecurityPolicy;
        using var scope = logger.BeginScope(new Dictionary<string, object> { ["CorrelationId"] = correlation });

        var host = context.Request.Host.Host;
        if (host is not ("127.0.0.1" or "localhost" or "[::1]" or "::1")) { await Reject(context, 421, "Unexpected host."); return; }
        var request = context.Request;
        var unsafeMethod = !HttpMethods.IsGet(request.Method) && !HttpMethods.IsHead(request.Method);
        var origin = request.Headers.Origin.ToString();
        var sameOrigin = string.Equals(origin, $"{request.Scheme}://{request.Host}", StringComparison.OrdinalIgnoreCase);
        if (unsafeMethod && origin.Length > 0 && !sameOrigin) { await Reject(context, 403, "Cross-origin request refused."); return; }

        if (request.Path.StartsWithSegments("/api"))
        {
            headers.CacheControl = "no-store";
            if (token.Matches(request.Headers[TokenHeader].ToString())) { await next(context); return; }
            if (settings.Mode == HostMode.Server && sessions.IsValid(request.Cookies[SessionStore.CookieName]))
            {
                // Cookie authentication needs proof that the request came from our own page: SameSite=Strict plus an explicit same-origin signal.
                if (unsafeMethod && !sameOrigin && request.Headers["Sec-Fetch-Site"].ToString() != "same-origin")
                { await Reject(context, 403, "State-changing requests need a same-origin signal."); return; }
                await next(context);
                return;
            }
            await Reject(context, 401, "Missing or invalid access token.");
            return;
        }
        await next(context);
    }

    private static Task Reject(HttpContext context, int status, string detail)
    {
        context.Response.StatusCode = status;
        return context.Response.WriteAsJsonAsync(new { type = "about:blank", title = detail, status, correlation_id = context.TraceIdentifier }, (System.Text.Json.JsonSerializerOptions?)null, "application/problem+json");
    }
}

/// <summary>Server-mode browser sessions: random identifiers, only their SHA-256 kept in memory, 8 hour lifetime, lost on restart (sign in again).
/// The cookie never contains the access token. Failed sign-ins are throttled (5 per minute per process).</summary>
public sealed class SessionStore(TimeProvider clock)
{
    public const string CookieName = "saplens_session";
    public static readonly TimeSpan Lifetime = TimeSpan.FromHours(8);
    private const int MaxSessions = 200;
    private const int MaxFailuresPerMinute = 5;
    private readonly ConcurrentDictionary<string, DateTimeOffset> _sessions = new(StringComparer.Ordinal);
    private readonly Queue<DateTimeOffset> _failures = new();

    private static string Hash(string id) => Convert.ToHexStringLower(SHA256.HashData(Encoding.UTF8.GetBytes(id)));

    public string Create()
    {
        var now = clock.GetUtcNow();
        foreach (var (key, expiry) in _sessions) if (expiry <= now) _sessions.TryRemove(key, out _);
        if (_sessions.Count >= MaxSessions) throw new InvalidOperationException("Too many active sessions.");
        var id = Convert.ToBase64String(RandomNumberGenerator.GetBytes(32)).TrimEnd('=').Replace('+', '-').Replace('/', '_');
        _sessions[Hash(id)] = now + Lifetime;
        return id;
    }

    public bool IsValid(string? id) => !string.IsNullOrEmpty(id) && id.Length <= 64 && _sessions.TryGetValue(Hash(id), out var expiry) && expiry > clock.GetUtcNow();

    public void Revoke(string? id) { if (!string.IsNullOrEmpty(id)) _sessions.TryRemove(Hash(id), out _); }

    public bool Throttled()
    {
        lock (_failures)
        {
            var cutoff = clock.GetUtcNow() - TimeSpan.FromMinutes(1);
            while (_failures.Count > 0 && _failures.Peek() < cutoff) _failures.Dequeue();
            return _failures.Count >= MaxFailuresPerMinute;
        }
    }

    public void RecordFailure() { lock (_failures) _failures.Enqueue(clock.GetUtcNow()); }
}
