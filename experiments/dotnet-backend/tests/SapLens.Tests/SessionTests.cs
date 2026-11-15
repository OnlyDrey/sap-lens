using System.Net;
using Microsoft.AspNetCore.Builder;
using SapLens.Api;

namespace SapLens.Tests;

/// <summary>Server-mode browser sign-in: the token is exchanged once for an HttpOnly, SameSite=Strict session cookie that never contains it; cookie
/// requests that change state need a same-origin signal; Desktop mode has no sign-in at all.</summary>
public sealed class SessionTests : IAsyncLifetime
{
    private readonly string _root = Directory.CreateTempSubdirectory("saplens-session-").FullName;
    private readonly string _token = HostSettings.NewToken();
    private readonly List<WebApplication> _apps = [];

    public Task InitializeAsync() => Task.CompletedTask;

    public async Task DisposeAsync()
    {
        foreach (var app in _apps) { await app.StopAsync(); await app.DisposeAsync(); }
        Microsoft.Data.Sqlite.SqliteConnection.ClearAllPools();
        try { Directory.Delete(_root, true); } catch (IOException) { }
    }

    private async Task<Uri> StartAsync(HostMode mode)
    {
        var app = SapLensHost.Build(new HostSettings
        {
            DataDirectory = Path.Combine(_root, mode.ToString()), Url = "http://127.0.0.1:0", AccessToken = _token, Mode = mode, JsonConsoleLogging = false,
        });
        await app.StartAsync();
        _apps.Add(app);
        return new Uri(app.Urls.First());
    }

    private static HttpClient Client(Uri origin) => new(new HttpClientHandler { AllowAutoRedirect = false, UseCookies = false, UseProxy = false }) { BaseAddress = origin };

    private static Task<HttpResponseMessage> Login(HttpClient client, string token) =>
        client.PostAsync("/auth/login", new FormUrlEncodedContent([new KeyValuePair<string, string>("token", token)]));

    [Fact]
    public async Task Sign_in_sets_an_httponly_strict_cookie_that_does_not_contain_the_token()
    {
        using var client = Client(await StartAsync(HostMode.Server));
        var response = await Login(client, _token);
        Assert.Equal(HttpStatusCode.Redirect, response.StatusCode);
        var cookie = response.Headers.GetValues("Set-Cookie").Single();
        Assert.StartsWith(SessionStore.CookieName + "=", cookie);
        Assert.Contains("httponly", cookie, StringComparison.OrdinalIgnoreCase);
        Assert.Contains("samesite=strict", cookie, StringComparison.OrdinalIgnoreCase);
        Assert.DoesNotContain(_token, cookie);

        var pair = cookie.Split(';')[0];
        using var withCookie = new HttpRequestMessage(HttpMethod.Get, "/api/v1/session");
        withCookie.Headers.Add("Cookie", pair);
        Assert.Equal(HttpStatusCode.OK, (await client.SendAsync(withCookie)).StatusCode);

        // State change by cookie without a same-origin signal is refused; with Origin it reaches validation (400 for an empty body).
        using var noSignal = new HttpRequestMessage(HttpMethod.Post, "/api/v1/admin/backups");
        noSignal.Headers.Add("Cookie", pair);
        Assert.Equal(HttpStatusCode.Forbidden, (await client.SendAsync(noSignal)).StatusCode);
        using var sameOrigin = new HttpRequestMessage(HttpMethod.Post, "/api/v1/admin/backups");
        sameOrigin.Headers.Add("Cookie", pair);
        sameOrigin.Headers.Add("Origin", client.BaseAddress!.GetLeftPart(UriPartial.Authority));
        Assert.Equal(HttpStatusCode.OK, (await client.SendAsync(sameOrigin)).StatusCode);

        using var forged = new HttpRequestMessage(HttpMethod.Get, "/api/v1/session");
        forged.Headers.Add("Cookie", SessionStore.CookieName + "=forged-value");
        Assert.Equal(HttpStatusCode.Unauthorized, (await client.SendAsync(forged)).StatusCode);
    }

    [Fact]
    public async Task Failed_sign_ins_are_rejected_and_throttled()
    {
        using var client = Client(await StartAsync(HostMode.Server));
        for (var i = 0; i < 5; i++) Assert.Equal(HttpStatusCode.Unauthorized, (await Login(client, "wrong-token-wrong-token-wrong-token")).StatusCode);
        Assert.Equal(HttpStatusCode.TooManyRequests, (await Login(client, _token)).StatusCode);
    }

    [Fact]
    public async Task Desktop_mode_has_no_sign_in_and_ignores_session_cookies()
    {
        using var client = Client(await StartAsync(HostMode.Desktop));
        Assert.Equal(HttpStatusCode.NotFound, (await Login(client, _token)).StatusCode);
        using var request = new HttpRequestMessage(HttpMethod.Get, "/api/v1/session");
        request.Headers.Add("Cookie", SessionStore.CookieName + "=anything");
        Assert.Equal(HttpStatusCode.Unauthorized, (await client.SendAsync(request)).StatusCode);
    }
}
