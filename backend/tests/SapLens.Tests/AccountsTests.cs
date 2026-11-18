using System.Net;
using System.Net.Http.Json;
using System.Text.Json.Nodes;
using Microsoft.AspNetCore.Builder;
using Microsoft.AspNetCore.Http;
using Microsoft.Data.Sqlite;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Time.Testing;
using SapLens.Api;
using SapLens.Application.Accounts;

namespace SapLens.Tests;

/// <summary>Port of the v1 account tests (test_auth_store.py, test_auth_provisioning.py, test_session_auth_api.py): verifier compatibility with
/// argon2-cffi, activation, sessions, CSRF, roles, credential versions, last-administrator protection, throttling, resets, audit hygiene, and the
/// HTTP boundary with per-user attribution. Synthetic accounts and temporary directories only.</summary>
public sealed class AccountsTests : IDisposable
{
    private const string Password = "Synthetic HTTP password 123!";
    // Written by Python argon2-cffi PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2) for "Correct horse battery 1".
    private const string PythonVerifier = "$argon2id$v=19$m=65536,t=3,p=2$d0afxEn9t+YX3vkt2Xe+hQ$29MRHuM2oRTyLUlQlbtusbHYJ6T4N1Kvi+dlMEu60oI";
    private readonly string _root = Directory.CreateTempSubdirectory("saplens-accounts-").FullName;

    public void Dispose()
    {
        SqliteConnection.ClearAllPools();
        try { Directory.Delete(_root, true); } catch (IOException) { }
    }

    private (AccountStore Store, FakeTimeProvider Clock) NewStore()
    {
        var clock = new FakeTimeProvider(DateTimeOffset.UtcNow);
        var store = new AccountStore(AccountStore.For(Path.Combine(_root, Guid.NewGuid().ToString("N"))), clock);
        store.Prepare();
        return (store, clock);
    }

    private static async Task<Principal> Bootstrap(AccountStore store, string username = "admin")
    {
        var (code, _, purpose) = await store.IssueAsync();
        Assert.Equal("bootstrap", purpose);
        await store.CompleteAsync(code, username, "Admin", Password, recovery: false);
        return (await store.LoginAsync(username, Password, "fixture")).Principal;
    }

    [Fact]
    public async Task Recovery_copy_authorization_requires_password_and_expires_is_session_bound_and_single_use()
    {
        var (store, clock) = NewStore();
        var admin = await Bootstrap(store);
        await Assert.ThrowsAsync<AuthException>(() => store.IssueBackupVerificationAsync(admin, "wrong"));
        var code = await store.IssueBackupVerificationAsync(admin, Password);
        var other = (await store.LoginAsync("admin", Password, "another-client")).Principal;
        await Assert.ThrowsAsync<AuthException>(() => store.ConsumeBackupVerificationAsync(other, code));
        await store.ConsumeBackupVerificationAsync(admin, code);
        await Assert.ThrowsAsync<AuthException>(() => store.ConsumeBackupVerificationAsync(admin, code));
        var expired = await store.IssueBackupVerificationAsync(admin, Password);
        clock.Advance(TimeSpan.FromMinutes(6));
        await Assert.ThrowsAsync<AuthException>(() => store.ConsumeBackupVerificationAsync(admin, expired));
        var audit = System.Text.Json.JsonSerializer.Serialize(await store.AuditAsync(admin, 100));
        Assert.Contains("backup.reauthenticated", audit);
        Assert.DoesNotContain(code, audit); Assert.DoesNotContain(Password, audit);
    }

    [Fact]
    public async Task Recovery_copy_http_verification_requires_csrf_current_password_and_one_use_proof()
    {
        await using var server = await StartServer();
        await Bootstrap(server.Store);
        Assert.Equal(HttpStatusCode.OK, (await server.Post("/api/auth/login", new { username = "admin", password = Password })).StatusCode);
        var data = server.App.Services.GetRequiredService<SapLens.Persistence.DatabaseOptions>().DataDirectory;
        var file = Path.Combine(_root, "host-" + Guid.NewGuid().ToString("N") + ".key");
        SapLens.Application.Backups.BackupKeys.Create(file, data);
        var recovery = File.ReadAllText(file).Trim();
        Assert.Equal(HttpStatusCode.Forbidden, (await server.Post("/api/backups/key/verify", new { recovery_key = recovery })).StatusCode);
        Assert.Equal(HttpStatusCode.Forbidden, (await server.Post("/api/auth/backup-reauth", new { current_password = Password }, csrf: false)).StatusCode);
        Assert.Equal(HttpStatusCode.Unauthorized, (await server.Post("/api/auth/backup-reauth", new { current_password = "wrong" })).StatusCode);
        var issued = await server.Post("/api/auth/backup-reauth", new { current_password = Password });
        Assert.Equal(HttpStatusCode.OK, issued.StatusCode);
        var proof = (string)JsonNode.Parse(await issued.Content.ReadAsStringAsync())!["code"]!;
        Assert.Equal(HttpStatusCode.OK, (await server.Post("/api/backups/key/verify", new { recovery_key = recovery, reauth_code = proof })).StatusCode);
        Assert.Equal(HttpStatusCode.Forbidden, (await server.Post("/api/backups/key/verify", new { recovery_key = recovery, reauth_code = proof })).StatusCode);
        var status = await server.Client.GetStringAsync("/api/backups");
        Assert.True((bool)JsonNode.Parse(status)!["key_provider"]!["escrow_verified"]!);
        Assert.DoesNotContain(recovery, status); Assert.DoesNotContain(file, status);
    }

    [Fact]
    public void Verifiers_interoperate_with_python_argon2_and_v1_pbkdf2()
    {
        Assert.True(Passwords.Verify(PythonVerifier, "Correct horse battery 1"));
        Assert.False(Passwords.Verify(PythonVerifier, "Correct horse battery 2"));
        Assert.False(Passwords.NeedsRehash(PythonVerifier));
        var own = Passwords.Hash("Correct horse battery 1");
        Assert.StartsWith("$argon2id$v=19$m=65536,t=3,p=2$", own);
        Assert.True(Passwords.Verify(own, "Correct horse battery 1"));
        Assert.True(Passwords.NeedsRehash("$argon2id$v=19$m=32768,t=2,p=1$d0afxEn9t+YX3vkt2Xe+hQ$29MRHuM2oRTyLUlQlbtusbHYJ6T4N1Kvi+dlMEu60oI"));
        var salt = new byte[32];
        var hash = System.Security.Cryptography.Rfc2898DeriveBytes.Pbkdf2("Legacy password 123"u8.ToArray(), salt, 600_000, System.Security.Cryptography.HashAlgorithmName.SHA256, 32);
        var legacy = "pbkdf2:" + System.Text.Json.JsonSerializer.Serialize(new { iterations = 600_000, salt = Convert.ToBase64String(salt), hash = Convert.ToBase64String(hash) });
        Assert.True(Passwords.Verify(legacy, "Legacy password 123"));
        Assert.False(Passwords.Verify(legacy.Replace("600000", "1000"), "Legacy password 123"));
        Assert.Throws<AuthException>(() => Passwords.Hash("short"));
        Assert.False(Passwords.Verify(PythonVerifier, new string('x', 1025)));
    }

    [Fact]
    public async Task Activation_is_single_use_and_closes_setup_atomically()
    {
        var (store, _) = NewStore();
        Assert.True((bool)(await store.StateAsync())["setup_required"]!);
        Assert.Equal("invalid_activation", (await Assert.ThrowsAsync<AuthException>(() => store.CompleteAsync(new string('x', 43), "admin", "Admin", Password, false))).Code);
        var (code, _, _) = await store.IssueAsync();
        Assert.Equal("invalid_username", (await Assert.ThrowsAsync<AuthException>(() => store.CompleteAsync(code, "bad name", "Admin", Password, false))).Code);
        await store.CompleteAsync(code, "admin", " Admin ", Password, false);
        Assert.False((bool)(await store.StateAsync())["setup_required"]!);
        Assert.Equal("bootstrap_closed", (await Assert.ThrowsAsync<AuthException>(() => store.IssueAsync())).Code);
        Assert.Equal("invalid_activation", (await Assert.ThrowsAsync<AuthException>(() => store.CompleteAsync(code, "second", "Second", Password, false))).Code);
        // Recovery: local code for an existing administrator; sign-in is blocked until it is used, then the new password works.
        var (recovery, _, purpose) = await store.IssueAsync("admin");
        Assert.Equal("recovery", purpose);
        Assert.Equal("invalid_credentials", (await Assert.ThrowsAsync<AuthException>(() => store.LoginAsync("admin", Password, "c1"))).Code);
        await store.CompleteAsync(recovery, "", "", Password + " new", recovery: true);
        Assert.Equal("Admin", (await store.LoginAsync("admin", Password + " new", "c1")).Principal.DisplayName);
    }

    [Fact]
    public async Task Sessions_csrf_roles_credential_versions_and_last_administrator()
    {
        var (store, clock) = NewStore();
        var admin = await Bootstrap(store);
        var viewer = await store.CreateUserAsync(admin, "viewer", "Viewer", "viewer", Password);
        Assert.Equal("username_exists", (await Assert.ThrowsAsync<AuthException>(() => store.CreateUserAsync(admin, "viewer", "Again", "viewer", Password))).Code);
        var (principal, token, csrf) = await store.LoginAsync("viewer", Password, "client");
        Assert.Equal("viewer", (await store.SessionAsync(token)).Role);
        await store.CsrfAsync(principal, csrf);
        Assert.Equal("csrf_required", (await Assert.ThrowsAsync<AuthException>(() => store.CsrfAsync(principal, "wrong"))).Code);
        Assert.Equal("permission_denied", (await Assert.ThrowsAsync<AuthException>(() => store.UsersAsync(principal))).Code);
        // A role change ends every session of that account.
        var updated = await store.UpdateUserAsync(admin, (string)viewer["id"]!, 0, "reviewer", true, "Viewer");
        Assert.Equal(1L, updated["revision"]);
        Assert.Equal("authentication_required", (await Assert.ThrowsAsync<AuthException>(() => store.SessionAsync(token))).Code);
        Assert.Equal("stale_user", (await Assert.ThrowsAsync<AuthException>(() => store.UpdateUserAsync(admin, (string)viewer["id"]!, 0, "viewer", true, "Viewer"))).Code);
        Assert.Equal("last_administrator", (await Assert.ThrowsAsync<AuthException>(() => store.UpdateUserAsync(admin, admin.Id, 0, "viewer", true, "Admin"))).Code);
        // Idle timeout (policy 1800 s) and absolute lifetime.
        var (_, idleToken, _) = await store.LoginAsync("viewer", Password, "client");
        clock.Advance(TimeSpan.FromSeconds(1801));
        Assert.Equal("authentication_required", (await Assert.ThrowsAsync<AuthException>(() => store.SessionAsync(idleToken))).Code);
        var fresh = (await store.LoginAsync("admin", Password, "client")).Principal;
        Assert.Equal("invalid_session_policy", (await Assert.ThrowsAsync<AuthException>(() => store.UpdatePolicyAsync(fresh, 0, 100, 3600))).Code);
        Assert.Equal(1L, (await store.UpdatePolicyAsync(fresh, 0, 600, 3600))["revision"]);
        Assert.Equal("stale_policy", (await Assert.ThrowsAsync<AuthException>(() => store.UpdatePolicyAsync(fresh, 0, 600, 3600))).Code);
    }

    [Fact]
    public async Task Failed_sign_ins_throttle_the_client_and_resets_are_single_use()
    {
        var (store, clock) = NewStore();
        var admin = await Bootstrap(store);
        for (var i = 0; i < 5; i++) await Assert.ThrowsAsync<AuthException>(() => store.LoginAsync("admin", "Wrong password 1234", "attacker"));
        Assert.Equal("temporarily_throttled", (await Assert.ThrowsAsync<AuthException>(() => store.LoginAsync("admin", Password, "attacker"))).Code);
        Assert.Equal("admin", (await store.LoginAsync("admin", Password, "other client")).Principal.Username); // only the failing client is held
        clock.Advance(TimeSpan.FromSeconds(31));
        await store.LoginAsync("admin", Password, "attacker");

        var reviewer = await store.CreateUserAsync(admin, "reviewer", "Reviewer", "reviewer", Password);
        Assert.Equal("use_own_password_change", (await Assert.ThrowsAsync<AuthException>(() => store.IssueResetAsync(admin, admin.Id, 0))).Code);
        var (code, _) = await store.IssueResetAsync(admin, (string)reviewer["id"]!, 0);
        Assert.Equal("invalid_credentials", (await Assert.ThrowsAsync<AuthException>(() => store.LoginAsync("reviewer", Password, "c"))).Code); // pending reset blocks the old password
        await store.CompleteResetAsync(code, Password + " reset", "c");
        Assert.Equal("invalid_reset", (await Assert.ThrowsAsync<AuthException>(() => store.CompleteResetAsync(code, Password + " again", "c"))).Code);
        Assert.Equal("reviewer", (await store.LoginAsync("reviewer", Password + " reset", "c")).Principal.Role);

        // The audit holds operations and public metadata, never verifiers, codes or tokens.
        var audit = await store.AuditAsync((await store.LoginAsync("admin", Password, "c")).Principal, 200);
        var text = System.Text.Json.JsonSerializer.Serialize(audit);
        Assert.Contains("password.reset_requested", text);
        Assert.Contains("session.login_denied", text);
        Assert.DoesNotContain("argon2", text);
        Assert.DoesNotContain(code, text);
    }

    [Fact]
    public async Task Plain_http_from_the_network_is_refused_before_any_credential_is_read()
    {
        var (store, _) = NewStore();
        var context = new DefaultHttpContext();
        context.Request.Path = "/api/auth/login";
        context.Request.Method = "POST";
        context.Connection.RemoteIpAddress = IPAddress.Parse("192.0.2.10");
        var refusal = await V1Auth.AuthorizeAsync(context, store, tokenAuthenticated: false);
        Assert.NotNull(refusal);
        context.Connection.RemoteIpAddress = IPAddress.Loopback;
        Assert.Null(await V1Auth.AuthorizeAsync(context, store, tokenAuthenticated: false));
    }

    [Theory]
    [InlineData("GET", "/api/roles", "read")]
    [InlineData("GET", "/api/configuration", "admin")]
    [InlineData("GET", "/api/auth/users", "accounts")]
    [InlineData("POST", "/api/auth/password", "profile")]
    [InlineData("POST", "/api/configuration", "admin")]
    [InlineData("POST", "/api/saved-filters", "admin")]
    [InlineData("POST", "/api/account-review/decision/USER1", "review")]
    [InlineData("POST", "/api/sod/periods/p1/transition", "approve")]
    [InlineData("POST", "/api/sod/decisions/assignment", "review")]
    [InlineData("POST", "/api/sod/decisions/acceptance", "review")]
    [InlineData("POST", "/api/sod/decisions/assignment/bulk", "review")]
    [InlineData("POST", "/api/sod/decisions/role", "unknown")]
    [InlineData("GET", "/api/sod/decisions/assignment/history", "read")]
    [InlineData("POST", "/api/storage/lifecycle/rebaseline", "admin")]
    [InlineData("GET", "/api/data-sources/reports/abc", "read")]
    [InlineData("POST", "/api/refresh", "admin")]
    [InlineData("POST", "/api/branding/preview", "unknown")]
    [InlineData("GET", "/api/branding/logo", "read")]
    [InlineData("PUT", "/api/sod/reports/branding", "admin")]
    [InlineData("DELETE", "/api/sod/reports/branding", "admin")]
    [InlineData("PUT", "/api/retention/policy", "admin")]
    [InlineData("PUT", "/api/sod/reference", "admin")]
    [InlineData("PUT", "/api/roles", "unknown")]
    [InlineData("DELETE", "/api/sod/decisions/assignment", "unknown")]
    [InlineData("PATCH", "/api/functional-groups/g1", "admin")]
    [InlineData("PATCH", "/api/roles/x", "unknown")]
    [InlineData("GET", "/api/v1/admin/backups", "admin")]
    [InlineData("GET", "/api/v1/admin/integrity", "admin")]
    [InlineData("GET", "/api/v1/datasets", "read")]
    [InlineData("GET", "/api/sod/reports/branding", "read")]
    [InlineData("GET", "/api/refresh-schedule", "read")]
    [InlineData("POST", "/api/refresh-schedule/preview", "admin")]
    [InlineData("GET", "/api/data-sources/reports/abc/export", "read")]
    [InlineData("POST", "/api/import/headers", "admin")]
    [InlineData("POST", "/api/import/preview", "admin")]
    [InlineData("POST", "/api/user-import/headers", "admin")]
    [InlineData("POST", "/api/user-import/preview", "admin")]
    [InlineData("POST", "/api/sod/remediation/actions", "review")]
    [InlineData("POST", "/api/sod/simulate", "export")]
    [InlineData("POST", "/api/sod/reports/pdf", "export")]
    [InlineData("POST", "/api/roles/package/preview", "export")]
    [InlineData("POST", "/api/not-a-permitted-operation", "unknown")]
    [InlineData("DELETE", "/api/roles", "unknown")]
    [InlineData("POST", "/api/v1/imports/roles", "unknown")]
    public void Route_permissions_follow_the_v1_session_boundary(string method, string path, string expected) => Assert.Equal(expected, V1Auth.Permission(method, path));

    private sealed class Server : IAsyncDisposable
    {
        public required WebApplication App { get; init; }
        public required HttpClient Client { get; init; }
        public required CookieContainer Cookies { get; init; }
        public required string Token { get; init; }
        public AccountStore Store => App.Services.GetRequiredService<AccountStore>();

        public async ValueTask DisposeAsync()
        {
            Client.Dispose();
            await App.StopAsync();
            await App.DisposeAsync();
        }

        public string Csrf => Cookies.GetCookies(Client.BaseAddress!)[V1Auth.CsrfCookie]!.Value;

        public async Task<HttpResponseMessage> Post(string path, object? body = null, bool csrf = true)
        {
            using var request = new HttpRequestMessage(HttpMethod.Post, path) { Content = JsonContent.Create(body ?? new { }) };
            request.Headers.Add("Origin", Client.BaseAddress!.GetLeftPart(UriPartial.Authority));
            if (csrf && Cookies.GetCookies(Client.BaseAddress)[V1Auth.CsrfCookie] is not null) request.Headers.Add(V1Auth.CsrfHeader, Csrf);
            return await Client.SendAsync(request);
        }
    }

    private async Task<Server> StartServer()
    {
        var token = HostSettings.NewToken();
        var app = SapLensHost.Build(new HostSettings
        {
            DataDirectory = Path.Combine(_root, "server-" + Guid.NewGuid().ToString("N")), Port = 0, AccessToken = token, JsonConsoleLogging = false, Authentication = AuthenticationMode.Accounts,
        });
        await app.StartAsync();
        var cookies = new CookieContainer();
        var client = new HttpClient(new HttpClientHandler { CookieContainer = cookies }) { BaseAddress = new Uri(app.Urls.First()) };
        return new Server { App = app, Client = client, Cookies = cookies, Token = token };
    }

    [Fact]
    public async Task Http_activation_sign_in_csrf_permissions_and_attribution()
    {
        await using var server = await StartServer();
        var state = JsonNode.Parse(await server.Client.GetStringAsync("/api/auth/state"))!;
        Assert.Equal("local-sessions", (string)state["provider"]!);
        Assert.True((bool)state["setup_required"]!);
        Assert.Equal(HttpStatusCode.Unauthorized, (await server.Client.GetAsync("/api/roles")).StatusCode); // nothing without a session

        var (code, _, _) = await server.Store.IssueAsync();
        Assert.Equal(HttpStatusCode.OK, (await server.Post("/api/auth/activate", new { username = "admin", display_name = "Admin", password = Password, code })).StatusCode);
        var secret = new string('s', 1100);
        var tooLong = await server.Post("/api/auth/login", new { username = "admin", password = secret });
        Assert.Equal(HttpStatusCode.UnprocessableEntity, tooLong.StatusCode);
        Assert.DoesNotContain(secret, await tooLong.Content.ReadAsStringAsync());
        using (var evil = new HttpRequestMessage(HttpMethod.Post, "/api/auth/login") { Content = JsonContent.Create(new { username = "admin", password = Password }) })
        {
            evil.Headers.Add("Origin", "https://evil.example.invalid");
            Assert.Equal(HttpStatusCode.Forbidden, (await server.Client.SendAsync(evil)).StatusCode);
        }

        var login = await server.Post("/api/auth/login", new { username = "admin", password = Password });
        Assert.Equal(HttpStatusCode.OK, login.StatusCode);
        var cookies = login.Headers.GetValues("Set-Cookie").ToList();
        var session = cookies.Single(c => c.StartsWith("sap-lens-session=", StringComparison.Ordinal));
        Assert.Contains("httponly", session, StringComparison.OrdinalIgnoreCase);
        Assert.Contains("samesite=strict", session, StringComparison.OrdinalIgnoreCase);
        Assert.DoesNotContain("secure", session, StringComparison.OrdinalIgnoreCase); // loopback HTTP only
        Assert.DoesNotContain("httponly", cookies.Single(c => c.StartsWith("sap-lens-csrf=", StringComparison.Ordinal)), StringComparison.OrdinalIgnoreCase);
        var me = await server.Client.GetAsync("/api/auth/me");
        Assert.Equal("no-store", me.Headers.CacheControl!.ToString());
        Assert.Equal("server-session", (string)JsonNode.Parse(await me.Content.ReadAsStringAsync())!["provenance"]!);

        // Writes need the per-session CSRF header; attribution is the signed-in account.
        Assert.Equal(HttpStatusCode.Forbidden, (await server.Post("/api/saved-filters", new { name = "Mine", view = "roles", filters = new { } }, csrf: false)).StatusCode);
        Assert.Equal(HttpStatusCode.OK, (await server.Post("/api/saved-filters", new { name = "Mine", view = "roles", filters = new { } })).StatusCode);
        await using (var db = await server.App.Services.GetRequiredService<Microsoft.EntityFrameworkCore.IDbContextFactory<SapLens.Persistence.SapLensDb>>().CreateDbContextAsync())
            Assert.Equal("admin", db.SavedFilters.Single().CreatedBy);
        Assert.Equal("admin", (string)JsonNode.Parse(await server.Client.GetStringAsync("/api/runtime"))!["username"]!);

        Assert.Equal("[]", JsonNode.Parse(await server.Client.GetStringAsync("/api/auth/migration"))!["items"]!.ToJsonString());
        Assert.Equal(HttpStatusCode.Conflict, (await server.Post("/api/auth/migration/0123/confirm", new { confirm = true })).StatusCode);
        var created = await server.Post("/api/auth/users", new { username = "viewer", display_name = "Viewer", role = "viewer", password = Password });
        Assert.Equal(HttpStatusCode.OK, created.StatusCode);
        Assert.Equal(HttpStatusCode.Forbidden, (await server.Post("/api/not-a-permitted-operation")).StatusCode);
        Assert.Equal(HttpStatusCode.OK, (await server.Post("/api/auth/logout")).StatusCode);
        Assert.Equal(HttpStatusCode.Unauthorized, (await server.Client.GetAsync("/api/auth/me")).StatusCode);

        // Viewer: reads, presentation settings and package preview; no account administration, settings writes or saved-filter writes.
        Assert.Equal(HttpStatusCode.OK, (await server.Post("/api/auth/login", new { username = "viewer", password = Password })).StatusCode);
        Assert.Equal(HttpStatusCode.Forbidden, (await server.Client.GetAsync("/api/auth/users")).StatusCode);
        Assert.Equal(HttpStatusCode.Forbidden, (await server.Client.GetAsync("/api/auth/migration")).StatusCode);
        Assert.Equal(HttpStatusCode.Forbidden, (await server.Client.GetAsync("/api/configuration")).StatusCode);
        Assert.Equal(HttpStatusCode.OK, (await server.Client.GetAsync("/api/presentation")).StatusCode);
        Assert.Equal(HttpStatusCode.Forbidden, (await server.Post("/api/configuration", new { })).StatusCode);
        Assert.Equal(HttpStatusCode.Forbidden, (await server.Post("/api/saved-filters", new { name = "Viewer", view = "roles", filters = new { } })).StatusCode);
        Assert.Equal(HttpStatusCode.OK, (await server.Post("/api/roles/package/preview", new { items = Array.Empty<object>() })).StatusCode);
        var runtime = JsonNode.Parse(await server.Client.GetStringAsync("/api/runtime"))!;
        Assert.Equal(("viewer", "viewer"), ((string)runtime["username"]!, (string)runtime["role"]!));
        Assert.Equal(HttpStatusCode.OK, (await server.Post("/api/auth/password", new { current_password = Password, new_password = Password + " new" })).StatusCode);
        Assert.Equal(HttpStatusCode.Unauthorized, (await server.Client.GetAsync("/api/auth/me")).StatusCode); // a password change ends the session

        // API clients holding the protected access token act as the operator principal.
        using var api = new HttpRequestMessage(HttpMethod.Get, "/api/runtime");
        api.Headers.Add(RequestBoundary.TokenHeader, server.Token);
        Assert.Equal(HttpStatusCode.OK, (await server.Client.SendAsync(api)).StatusCode);
        using var form = new HttpRequestMessage(HttpMethod.Post, "/auth/login") { Content = new FormUrlEncodedContent([new("token", server.Token)]) };
        form.Headers.Add("Origin", server.Client.BaseAddress!.GetLeftPart(UriPartial.Authority));
        Assert.Equal(HttpStatusCode.NotFound, (await server.Client.SendAsync(form)).StatusCode); // no shared-token web sign-in in Accounts mode
    }
}
