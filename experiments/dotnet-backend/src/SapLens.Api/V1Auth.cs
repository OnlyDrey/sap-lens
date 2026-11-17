using System.Net;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;
using SapLens.Application.Accounts;

namespace SapLens.Api;

public enum AuthenticationMode { SharedToken, Accounts }

/// <summary>Who is acting in this request. Accounts mode: the signed-in v1 account (server session). Otherwise, and for API clients that present the
/// protected access token, the configured operator principal, labelled with how it was established.</summary>
public static class Actors
{
    private const string Key = "SapLens.Principal";

    public static void Set(HttpContext http, Principal principal) => http.Items[Key] = principal;

    public static Principal Current(HttpContext http)
    {
        if (http.Items[Key] is Principal principal) return principal;
        var host = http.RequestServices.GetRequiredService<HostSettings>();
        return new Principal("operator", host.PrincipalName, host.PrincipalName, "administrator", "", host.Mode == HostMode.Desktop ? "desktop" : "access-token");
    }

    public static string Name(HttpContext http) => Current(http).Username;
}

/// <summary>Port of routers/authentication.py and session_boundary.py: the v1 account API and its route permission map.</summary>
public static partial class V1Auth
{
    public const string SessionCookie = "sap-lens-session", CsrfCookie = "sap-lens-csrf", CsrfHeader = "X-SAP-Lens-CSRF";
    public static readonly HashSet<string> PublicPaths = ["/api/auth/state", "/api/auth/login", "/api/auth/reset", "/api/auth/activate", "/api/auth/recover"];
    private static readonly string[] AdminRead = ["/api/v1/admin", "/api/backups", "/api/storage", "/api/retention", "/api/diagnostics", "/api/configuration", "/api/settings"];
    private static readonly string[] AdminWrite = ["/api/settings", "/api/configuration", "/api/refresh", "/api/server/", "/api/data-sources", "/api/sources", "/api/branding", "/api/storage",
        "/api/retention", "/api/backups", "/api/import", "/api/sod/configuration", "/api/sod/reference", "/api/sod/periods", "/api/saved-filters", "/api/functional-groups",
        "/api/user-import", "/api/employees", "/api/data/cancel", "/api/refresh-schedule", "/api/sod/catalogue", "/api/sod/reports/branding"];
    private static readonly HashSet<string> ReadOnlyPosts = ["/api/sod/reports/preview", "/api/sod/reports/pdf", "/api/sod/reports/docx", "/api/sod/reports/remediation/preview",
        "/api/sod/reports/remediation/pdf", "/api/sod/reports/remediation/csv", "/api/sod/simulate"];
    private static readonly HashSet<string> ReviewerPosts = ["/api/sod/decisions/activity", "/api/sod/decisions/assignment", "/api/sod/decisions/assignment/bulk",
        "/api/sod/decisions/acceptance", "/api/sod/decisions/risk", "/api/sod/remediation/actions"];

    [GeneratedRegex("^/api/account-review/decision/[^/]+$")] private static partial Regex ReviewDecision();
    [GeneratedRegex("^/api/sod/reviews/[^/]+$")] private static partial Regex SodReview();
    [GeneratedRegex("^/api/sod/periods/[^/]+/reviews/[^/]+$")] private static partial Regex PeriodReview();
    [GeneratedRegex("^/api/sod/periods/[^/]+/transition$")] private static partial Regex PeriodTransition();

    /// <summary>session_boundary.permission: deny by default. Unknown methods and unknown writes map to "unknown", which no role holds.
    /// Native /api/v1 routes are for API clients with the access token; a browser session may only read them.</summary>
    public static string Permission(string method, string path)
    {
        if (path == "/api/branding/preview") return "unknown";
        if (path.StartsWith("/api/auth/users", StringComparison.Ordinal) || path.StartsWith("/api/auth/migration", StringComparison.Ordinal) || path is "/api/auth/audit" or "/api/auth/policy") return "accounts";
        if (path.StartsWith("/api/auth/", StringComparison.Ordinal)) return "profile";
        if (method is "GET" or "HEAD") return AdminRead.Any(p => path.StartsWith(p, StringComparison.Ordinal)) ? "admin" : "read";
        // v1 answered "unknown" for every PUT, PATCH and DELETE, so in Server account mode no session could save the retention policy, the SoD reference
        // library, report branding or a functional group rename. Here they are administrator writes on the administrator paths only; other methods and paths stay denied.
        if (method is "PUT" or "PATCH" or "DELETE") return AdminWrite.Any(p => path.StartsWith(p, StringComparison.Ordinal)) ? "admin" : "unknown";
        if (method != "POST") return "unknown";
        if (path == "/api/compare" || ReadOnlyPosts.Contains(path)) return path == "/api/compare" ? "read" : "export";
        if (PeriodTransition().IsMatch(path)) return "approve";
        if (ReviewDecision().IsMatch(path) || SodReview().IsMatch(path) || PeriodReview().IsMatch(path) || ReviewerPosts.Contains(path)) return "review";
        if (AdminWrite.Any(p => path.StartsWith(p, StringComparison.Ordinal))) return "admin";
        // Access Package preview/export are reads with a POST body (any signed-in role may build and copy a package).
        if (path.StartsWith("/api/roles/package/", StringComparison.Ordinal)) return "export";
        return "unknown";
    }

    public static IResult Refused(AuthException error) => Results.Json(new { detail = error.Code, code = error.Code }, statusCode: error.Status);

    private static IResult Invalid() => Results.Json(new { detail = "Invalid authentication request", code = "invalid_request" }, statusCode: 422);

    /// <summary>A strict v1 request model: only the listed fields, the listed JSON kinds and bounds. Any violation is the same opaque 422 as v1.</summary>
    private sealed class Body(JsonObject json)
    {
        public bool Valid { get; private set; } = true;
        private readonly HashSet<string> _seen = [];

        public string Text(string name, int min, int max, string? fallback = null)
        {
            _seen.Add(name);
            if (!json.TryGetPropertyValue(name, out var node)) { Valid &= fallback is not null; return fallback ?? ""; }
            if (node?.GetValueKind() != JsonValueKind.String) { Valid = false; return ""; }
            var value = node.GetValue<string>();
            Valid &= Passwords.Length(value) >= min && Passwords.Length(value) <= max;
            return value;
        }

        public long Integer(string name, long min = long.MinValue)
        {
            _seen.Add(name);
            if (!json.TryGetPropertyValue(name, out var node) || node?.GetValueKind() != JsonValueKind.Number || !long.TryParse(node.ToJsonString(), out var value) || value < min) { Valid = false; return 0; }
            return value;
        }

        public bool Flag(string name)
        {
            _seen.Add(name);
            if (!json.TryGetPropertyValue(name, out var node) || node?.GetValueKind() is not (JsonValueKind.True or JsonValueKind.False)) { Valid = false; return false; }
            return node.GetValue<bool>();
        }

        public bool Done() => Valid && json.All(p => _seen.Contains(p.Key));
    }

    private static async Task<Body?> Read(HttpContext http)
    {
        try { return await JsonNode.ParseAsync(http.Request.Body, cancellationToken: http.RequestAborted) is JsonObject json ? new Body(json) : null; }
        catch (JsonException) { return null; }
    }

    private static string Client(HttpContext http) => http.Connection.RemoteIpAddress?.ToString() ?? "unknown";

    private static IResult Json(object? value) => Results.Content(JsonSerializer.Serialize(value), "application/json");

    private static void Clear(HttpContext http)
    {
        foreach (var (name, httpOnly) in new[] { (SessionCookie, true), (CsrfCookie, false) })
            http.Response.Cookies.Delete(name, new CookieOptions { Path = "/", Secure = http.Request.IsHttps, HttpOnly = httpOnly, SameSite = SameSiteMode.Strict });
    }

    private delegate Task<IResult> Handler(HttpContext http, AccountStore store, Principal actor);

    public static void Map(RouteGroupBuilder api, HostSettings settings)
    {
        if (settings.Authentication != AuthenticationMode.Accounts) return;

        // Every handler: no-store, AuthException -> {detail: code, code}; signed-in routes receive the principal the request boundary established.
        void Route(string method, string pattern, Handler handler, bool signedIn = true) =>
            api.MapMethods(pattern, [method], async (HttpContext http, AccountStore store) =>
            {
                http.Response.Headers.CacheControl = "no-store";
                try { return await handler(http, store, signedIn ? Actors.Current(http) : null!); }
                catch (AuthException error) { return Refused(error); }
            });

        Route("POST", "/auth/activate", async (http, store, _) =>
        {
            if (await Read(http) is not { } b) return Invalid();
            var (username, password, code, display) = (b.Text("username", 0, 100), b.Text("password", 0, 1024), b.Text("code", 20, 128), b.Text("display_name", 1, 120));
            if (!b.Done()) return Invalid();
            await store.CompleteAsync(code, username, display, password, recovery: false);
            return Json(new { ok = true, login_required = true });
        }, signedIn: false);

        Route("POST", "/auth/recover", async (http, store, _) =>
        {
            if (await Read(http) is not { } b) return Invalid();
            var (code, password) = (b.Text("code", 20, 128), b.Text("password", 12, 1024));
            if (!b.Done()) return Invalid();
            await store.CompleteAsync(code, "", "", password, recovery: true);
            return Json(new { ok = true, login_required = true });
        }, signedIn: false);

        Route("POST", "/auth/login", async (http, store, _) =>
        {
            if (await Read(http) is not { } b) return Invalid();
            var (username, password) = (b.Text("username", 0, 100), b.Text("password", 0, 1024));
            if (!b.Done()) return Invalid();
            var (principal, token, csrf) = await store.LoginAsync(username, password, Client(http));
            foreach (var (name, value, httpOnly) in new[] { (SessionCookie, token, true), (CsrfCookie, csrf, false) })
                http.Response.Cookies.Append(name, value, new CookieOptions { HttpOnly = httpOnly, Secure = http.Request.IsHttps, SameSite = SameSiteMode.Strict, Path = "/", IsEssential = true });
            var result = principal.Snapshot();
            result["role"] = principal.Role;
            return Json(result);
        }, signedIn: false);

        Route("POST", "/auth/reset", async (http, store, _) =>
        {
            if (await Read(http) is not { } b) return Invalid();
            var (code, password) = (b.Text("code", 20, 128), b.Text("password", 12, 1024));
            if (!b.Done()) return Invalid();
            await store.CompleteResetAsync(code, password, Client(http));
            return Json(new { ok = true, login_required = true });
        }, signedIn: false);

        Route("GET", "/auth/me", async (_, store, actor) => Json(await store.MeAsync(actor)));
        Route("GET", "/auth/sessions", async (_, store, actor) => Json(new { items = await store.SessionsAsync(actor) }));
        Route("POST", "/auth/logout", async (http, store, actor) => { await store.LogoutAsync(actor); Clear(http); return Json(new { ok = true }); });
        Route("POST", "/auth/logout-all", async (http, store, actor) => { await store.LogoutAsync(actor, true); Clear(http); return Json(new { ok = true }); });
        Route("POST", "/auth/logout-others", async (_, store, actor) => { await store.LogoutOthersAsync(actor); return Json(new { ok = true }); });

        Route("POST", "/auth/password", async (http, store, actor) =>
        {
            if (await Read(http) is not { } b) return Invalid();
            var (current, next) = (b.Text("current_password", 0, 1024), b.Text("new_password", 12, 1024));
            if (!b.Done()) return Invalid();
            await store.ChangePasswordAsync(actor, current, next);
            Clear(http);
            return Json(new { ok = true, login_required = true });
        });

        Route("POST", "/auth/profile", async (http, store, actor) =>
        {
            if (await Read(http) is not { } b) return Invalid();
            var (revision, display) = (b.Integer("expected_revision", 0), b.Text("display_name", 1, 120));
            if (!b.Done()) return Invalid();
            return Json(await store.ProfileAsync(actor, display, revision));
        });

        Route("GET", "/auth/users", async (_, store, actor) => Json(new { items = await store.UsersAsync(actor) }));

        Route("POST", "/auth/users", async (http, store, actor) =>
        {
            if (await Read(http) is not { } b) return Invalid();
            var (username, password, display, role) = (b.Text("username", 0, 100), b.Text("password", 0, 1024), b.Text("display_name", 1, 120), b.Text("role", 0, int.MaxValue));
            if (!b.Done()) return Invalid();
            return Json(await store.CreateUserAsync(actor, username, display, role, password));
        });

        Route("POST", "/auth/users/{identity}", async (http, store, actor) =>
        {
            if (await Read(http) is not { } b) return Invalid();
            var (revision, display, role, enabled) = (b.Integer("expected_revision", 0), b.Text("display_name", 1, 120), b.Text("role", 0, int.MaxValue), b.Flag("enabled"));
            if (!b.Done()) return Invalid();
            return Json(await store.UpdateUserAsync(actor, (string)http.GetRouteValue("identity")!, revision, role, enabled, display));
        });

        Route("POST", "/auth/users/{identity}/revoke", async (http, store, actor) =>
        {
            await store.RevokeAsync(actor, (string)http.GetRouteValue("identity")!);
            return Json(new { ok = true });
        });

        Route("POST", "/auth/users/{identity}/reset", async (http, store, actor) =>
        {
            if (await Read(http) is not { } b) return Invalid();
            var (revision, confirm) = (b.Integer("expected_revision", 0), b.Flag("confirm"));
            if (!b.Done()) return Invalid();
            if (!confirm) throw new AuthException("confirmation_required");
            var (code, expires) = await store.IssueResetAsync(actor, (string)http.GetRouteValue("identity")!, revision);
            return Json(new { code, expires });
        });

        Route("GET", "/auth/audit", async (http, store, actor) =>
        {
            var limit = int.TryParse(http.Request.Query["limit"].FirstOrDefault() ?? "100", out var l) ? l : -1;
            if (limit == -1) return Invalid();
            return Json(new { items = await store.AuditAsync(actor, limit) });
        });

        // v1 identity_migration: records of the legacy shared-access to local-session migration. The .NET server adopts a v1 account store as is
        // and never performs that legacy migration, so it holds no records; confirmation and archive deletion answer exactly as v1 does without one.
        Route("GET", "/auth/migration", async (_, store, actor) => { await store.AuthorizeAsync(actor, "accounts"); return Json(new { items = Array.Empty<object>() }); });
        foreach (var kind in new[] { "confirm", "delete" })
            Route("POST", "/auth/migration/{identifier}/" + kind, async (http, store, actor) =>
            {
                if (await Read(http) is not { } b) return Invalid();
                var confirm = b.Flag("confirm");
                if (!b.Done()) return Invalid();
                if (!confirm) throw new AuthException("migration_confirmation_required");
                await store.AuthorizeAsync(actor, "accounts");
                throw new AuthException("migration_confirmation_required", 409);
            });

        Route("GET", "/auth/policy", async (_, store, actor) => Json(await store.PolicyAsync(actor)));

        Route("POST", "/auth/policy", async (http, store, actor) =>
        {
            if (await Read(http) is not { } b) return Invalid();
            var (revision, idle, absolute) = (b.Integer("expected_revision", 0), b.Integer("idle"), b.Integer("absolute"));
            if (!b.Done()) return Invalid();
            return Json(await store.UpdatePolicyAsync(actor, revision, idle, absolute));
        });
    }

    /// <summary>session_boundary.authorize for one request in Accounts mode. Returns null when the request may proceed (principal recorded), or the
    /// refusal to send. Plain HTTP is accepted only from a loopback peer: on the network the server is HTTPS-only.</summary>
    public static async Task<IResult?> AuthorizeAsync(HttpContext http, AccountStore store, bool tokenAuthenticated)
    {
        var request = http.Request;
        if (!request.IsHttps && !(http.Connection.RemoteIpAddress is { } peer && IPAddress.IsLoopback(peer)))
            return Refused(new AuthException("secure_transport_required", 403));
        var path = request.Path.Value ?? "";
        if (tokenAuthenticated || PublicPaths.Contains(path) || !path.StartsWith("/api/", StringComparison.Ordinal)) return null;
        try
        {
            var actor = await store.SessionAsync(request.Cookies[SessionCookie]);
            AccountStore.Require(actor, Permission(request.Method, path));
            if (!HttpMethods.IsGet(request.Method) && !HttpMethods.IsHead(request.Method) && !HttpMethods.IsOptions(request.Method))
                await store.CsrfAsync(actor, request.Headers[CsrfHeader].ToString());
            Actors.Set(http, actor);
            return null;
        }
        catch (AuthException error) { return Refused(error); }
    }
}
