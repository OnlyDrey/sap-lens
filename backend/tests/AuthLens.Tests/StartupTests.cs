using System.Net;
using System.Net.Sockets;
using Microsoft.Data.Sqlite;
using Microsoft.Extensions.Logging;
using AuthLens.Api;

namespace AuthLens.Tests;

/// <summary>The Desktop start sequence (LocalStartup), exercised on any OS: ready only when the database is ready AND the UI entry point is served; every
/// failure stops the host, returns one actionable message and never logs the token.</summary>
// These wall-clock startup probes clear process-wide SQLite pools; keep them outside concurrent host/build fixtures.
[Collection("process-concurrency")]
public sealed class StartupTests : IDisposable
{
    private readonly string _root = Directory.CreateTempSubdirectory("saplens-startup-").FullName;
    private readonly string _token = HostSettings.NewToken();

    public void Dispose()
    {
        SqliteConnection.ClearAllPools();
        try { Directory.Delete(_root, true); } catch (IOException) { }
    }

    private HostSettings Settings(string data) => new()
    {
        DataDirectory = data, Mode = HostMode.Desktop, Port = 0, AccessToken = _token, JsonConsoleLogging = false,
    };

    private (FileLoggerProvider Logs, ILoggerFactory Factory, ILogger Log) Logging()
    {
        var logs = new FileLoggerProvider(Path.Combine(_root, "logs"), "test");
        var factory = LoggerFactory.Create(b => b.AddProvider(logs));
        return (logs, factory, factory.CreateLogger("test"));
    }

    private static async Task<bool> Listening(Uri origin)
    {
        using var socket = new TcpClient();
        try { await socket.ConnectAsync(origin.Host, origin.Port); return true; } catch (SocketException) { return false; }
    }

    [Fact]
    public async Task Successful_start_is_ready_and_serves_the_ui_and_shutdown_releases_the_port()
    {
        var (logs, factory, log) = Logging();
        using var _ = factory;
        var outcome = await LocalStartup.StartAsync(Settings(Path.Combine(_root, "data")), log, TimeSpan.FromSeconds(20), b => b.Logging.AddProvider(logs));
        Assert.True(outcome.Ok, outcome.Error);
        using var http = new HttpClient { BaseAddress = outcome.Origin };
        Assert.Equal(HttpStatusCode.OK, (await http.GetAsync("/")).StatusCode);
        Assert.Equal(HttpStatusCode.Unauthorized, (await http.GetAsync("/api/v1/roles")).StatusCode);
        await LocalStartup.StopQuietlyAsync(outcome.App);
        Assert.False(await Listening(outcome.Origin!));
        var text = await File.ReadAllTextAsync(logs.FilePath);
        Assert.Contains("Local service ready", text);
        Assert.DoesNotContain(_token, text);
    }

    [Fact]
    public async Task Database_from_a_newer_version_fails_with_the_reason_and_stops_the_host()
    {
        var data = Path.Combine(_root, "newer");
        var first = await LocalStartup.StartAsync(Settings(data), Logging().Log, TimeSpan.FromSeconds(20));
        Assert.True(first.Ok, first.Error);
        await LocalStartup.StopQuietlyAsync(first.App);
        SqliteConnection.ClearAllPools();
        await using (var c = new SqliteConnection($"Data Source={Path.Combine(data, "authlens.sqlite3")};Pooling=False"))
        {
            await c.OpenAsync();
            await using var cmd = c.CreateCommand();
            cmd.CommandText = "INSERT INTO __EFMigrationsHistory VALUES ('29991231000000_FromTheFuture', '99.0');";
            await cmd.ExecuteNonQueryAsync();
        }
        var (logs, factory, log) = Logging();
        using var _ = factory;
        var outcome = await LocalStartup.StartAsync(Settings(data), log, TimeSpan.FromSeconds(20));
        Assert.False(outcome.Ok);
        Assert.Contains("newer version", outcome.Error);
        Assert.False(await Listening(outcome.Origin!));
        Assert.DoesNotContain(_token, await File.ReadAllTextAsync(logs.FilePath));
    }

    [Theory]
    [InlineData("relative/data")]
    [InlineData("//server/share/data")]
    public async Task Invalid_data_directory_fails_before_listening_with_an_actionable_message(string data)
    {
        var outcome = await LocalStartup.StartAsync(Settings(data), Logging().Log, TimeSpan.FromSeconds(5));
        Assert.False(outcome.Ok);
        Assert.Null(outcome.Origin);
        Assert.StartsWith("The local service could not start:", outcome.Error);
    }

    [Fact]
    public async Task Probe_times_out_with_a_message_when_nothing_answers()
    {
        using var listener = new TcpListener(IPAddress.Loopback, 0);
        listener.Start();
        var port = ((IPEndPoint)listener.LocalEndpoint).Port;
        listener.Stop(); // a port that is not served
        var result = await StartupProbe.WaitAsync(new Uri($"http://127.0.0.1:{port}"), TimeSpan.FromSeconds(1));
        Assert.False(result.Ok);
        Assert.Contains("did not become ready", result.Problem);
    }
}
