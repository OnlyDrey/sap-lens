using System.Collections.Concurrent;
using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;

namespace AuthLens.Api;

/// <summary>Request boundary: correlation id, security headers, loopback Host header (DNS-rebinding defence), same-origin check for state-changing
/// requests, and authentication of every /api request by either the access-token header (Desktop shell, API clients) or, in Server mode only, an
/// HttpOnly session cookie obtained by submitting the token to /auth/login. Health endpoints and the static prototype UI are open and contain no data.</summary>
public sealed partial class RequestBoundary(RequestDelegate next, HostSettings settings, SessionStore sessions, RequestBoundaryTokenCheck token, ILogger<RequestBoundary> logger, IServiceProvider services)
{
    public const string TokenHeader = "X-SAP-Lens-Token";
    public const string CorrelationHeader = "X-Correlation-ID";
    /// <summary>The policy SAP Lens v1 serves this React UI with: scripts only from this origin (no inline script), inline styles allowed (React style
    /// attributes and component libraries use them), no framing, no foreign connections.</summary>
    public const string ContentSecurityPolicy =
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'";
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

        if (context.Request.IsHttps) headers.StrictTransportSecurity = "max-age=31536000";
        var request = context.Request;
        var origin = request.Headers.Origin.ToString();
        // Scheme and Host are the effective values: the connection's own, or those a trusted proxy forwarded (ProxyTrust runs earlier).
        var peer = context.Items[ProxyTrust.PeerItem] as System.Net.IPAddress ?? context.Connection.RemoteIpAddress;
        var proxyHost = ProxyTrust.Trusted(settings, peer) && settings.ProxyHosts.Any(h => OriginPolicy.HostsEqual(h, request.Host.Host));
        if (!settings.HostAllowed(request.Host.Host) && !proxyHost) { await Reject(context, 421, "Unexpected host.", origin); return; }
        // An HTTPS listener serves HTTPS only: a trusted proxy reporting a plain-HTTP client is refused, never downgraded to insecure cookies.
        if (settings.Https && !request.IsHttps) { await Reject(context, 403, "HTTPS is required.", origin); return; }
        var unsafeMethod = !HttpMethods.IsGet(request.Method) && !HttpMethods.IsHead(request.Method) && !HttpMethods.IsOptions(request.Method);
        var comparison = OriginPolicy.Compare(origin, request.Scheme, request.Host);
        var sameOrigin = comparison == OriginPolicy.Result.Match;
        if (unsafeMethod && origin.Length > 0 && !sameOrigin) { await Reject(context, 403, "Cross-origin request refused.", origin, comparison); return; }
        var tokenAuthenticated = token.Matches(request.Headers[TokenHeader].ToString());
        // CSRF: a state change that is not authenticated by the custom header (which browsers never attach cross-site) must carry a same-origin signal
        // (Origin equal to this server, or Sec-Fetch-Site: same-origin). SameSite=Strict on the session cookie is the second layer.
        if (unsafeMethod && !tokenAuthenticated && !sameOrigin && !(origin.Length == 0 && request.Headers["Sec-Fetch-Site"].ToString() == "same-origin"))
        { await Reject(context, 403, "State-changing requests need a same-origin signal.", origin, comparison); return; }

        if (settings.Authentication == AuthenticationMode.Accounts)
        {
            // v1 session boundary: public auth routes, then session cookie, route permission and per-session CSRF. The React UI renders sign-in.
            if (request.Path.StartsWithSegments("/api")) headers.CacheControl = "no-store";
            if (await V1Auth.AuthorizeAsync(context, services.GetRequiredService<AuthLens.Application.Accounts.AccountStore>(), tokenAuthenticated) is { } refusal)
            {
                await refusal.ExecuteAsync(context);
                return;
            }
            await next(context);
            return;
        }
        var sessionValid = settings.Mode == HostMode.Server && sessions.IsValid(request.Cookies[SessionStore.CookieNameFor(request.IsHttps)]);
        // Server mode: the application document needs a session; without one the browser is sent to the sign-in page (assets stay public, they hold no data).
        if (settings.Mode == HostMode.Server && HttpMethods.IsGet(request.Method) && request.Path.Value is "/" or "/index.html" && !tokenAuthenticated && !sessionValid)
        {
            context.Response.Redirect("/login.html");
            return;
        }

        if (request.Path.StartsWithSegments("/api"))
        {
            headers.CacheControl = "no-store";
            if (tokenAuthenticated || sessionValid)
            {
                await next(context);
                return;
            }
            await Reject(context, 401, "Missing or invalid access token.");
            return;
        }
        await next(context);
    }

    /// <summary>Boundary refusal with a server-side diagnostic: reason, peer and whether it is a trusted proxy, whether forwarded headers were present
    /// and applied, the raw and effective scheme and host, and the origin reduced to scheme://host:port. No cookie, token or credential is logged; the
    /// response carries only the reason and the correlation id.</summary>
    private Task Reject(HttpContext context, int status, string detail, string? origin, OriginPolicy.Result? comparison = null)
    {
        var request = context.Request;
        var peer = context.Items[ProxyTrust.PeerItem] as System.Net.IPAddress ?? context.Connection.RemoteIpAddress;
        var rawScheme = context.Items[ProxyTrust.RawSchemeItem] as string ?? request.Scheme;
        var rawHost = context.Items[ProxyTrust.RawHostItem] as string ?? request.Host.Value;
        var applied = !string.Equals(rawScheme, request.Scheme, StringComparison.Ordinal) || !string.Equals(rawHost, request.Host.Value, StringComparison.Ordinal) ||
                      !Equals(peer, context.Connection.RemoteIpAddress);
        logger.LogWarning("Request refused ({Status} {Reason}): {Method} {Path}; peer {Peer} trusted proxy {PeerTrusted}; client {Client}; forwarded headers present {ForwardedPresent} applied {ForwardedApplied}; " +
                          "raw {RawScheme}://{RawHost}; effective {Scheme}://{Host}; origin {Origin} comparison {Comparison}; forwarded {ForwardedSummary}",
            status, detail, request.Method, Clip(request.Path.Value), peer, ProxyTrust.Trusted(settings, peer), context.Connection.RemoteIpAddress, ProxyTrust.HasForwardedHeaders(request), applied,
            rawScheme, Clip(rawHost), request.Scheme, Clip(request.Host.Value), OriginPolicy.Describe(origin), comparison?.ToString() ?? OriginPolicy.Compare(origin, request.Scheme, request.Host).ToString(),
            context.Items[ProxyTrust.ForwardedSummaryItem] as string ?? "(unavailable)");
        return Reject(context, status, detail);
    }

    private static string Clip(string? value) => value is null ? "" : new string([.. value.Take(200).Select(c => char.IsControl(c) ? '?' : c)]);

    private static Task Reject(HttpContext context, int status, string detail)
    {
        context.Response.StatusCode = status;
        return context.Response.WriteAsJsonAsync(new { type = "about:blank", title = detail, detail, status, correlation_id = context.TraceIdentifier }, (System.Text.Json.JsonSerializerOptions?)null, "application/problem+json");
    }
}

/// <summary>Server-mode browser sessions: random identifiers, only their SHA-256 kept in memory, 8 hour lifetime, lost on restart (sign in again).
/// The cookie never contains the access token; over HTTPS it is named with the __Host- prefix (Secure, Path=/, no Domain enforced by browsers).
/// Failed sign-ins are throttled per client address (5 per minute) and in total (30 per minute).</summary>
public sealed class SessionStore(TimeProvider clock)
{
    public const string CookieName = "saplens_session";
    public const string SecureCookieName = "__Host-saplens_session";
    public static string CookieNameFor(bool https) => https ? SecureCookieName : CookieName;
    public static readonly TimeSpan Lifetime = TimeSpan.FromHours(8);
    private const int MaxSessions = 200;
    private const int MaxFailuresPerClient = 5;
    private const int MaxFailuresTotal = 30;
    private readonly ConcurrentDictionary<string, DateTimeOffset> _sessions = new(StringComparer.Ordinal);
    private readonly Queue<(DateTimeOffset At, string Client)> _failures = new();

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

    public bool Throttled(string client)
    {
        lock (_failures)
        {
            var cutoff = clock.GetUtcNow() - TimeSpan.FromMinutes(1);
            while (_failures.Count > 0 && _failures.Peek().At < cutoff) _failures.Dequeue();
            return _failures.Count >= MaxFailuresTotal || _failures.Count(f => f.Client == client) >= MaxFailuresPerClient;
        }
    }

    public void RecordFailure(string client) { lock (_failures) _failures.Enqueue((clock.GetUtcNow(), client)); }
}
