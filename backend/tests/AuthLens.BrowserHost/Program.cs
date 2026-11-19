using System.Net;
using Microsoft.Data.Sqlite;
using AuthLens.Api;

// Test-only executable. Production hosts never accept test environment settings.
var data = Environment.GetEnvironmentVariable("AUTHLENS_BROWSER_DATA") ?? throw new InvalidOperationException("An owned disposable data directory is required.");
if (!Path.IsPathFullyQualified(data)) throw new InvalidOperationException("Test data must be absolute.");
var port = int.Parse(Environment.GetEnvironmentVariable("AUTHLENS_BROWSER_TEST_PORT") ?? "18745");
var token = Environment.GetEnvironmentVariable("AUTHLENS_BROWSER_TOKEN") ?? throw new InvalidOperationException("Test token required.");
await using var app = AuthLensHost.Build(new HostSettings {
    Mode = HostMode.Desktop, DataDirectory = data, ListenAddress = IPAddress.Loopback,
    Port = port, AccessToken = token, PrincipalName = "Synthetic browser reviewer", JsonConsoleLogging = false,
});
try { await app.RunAsync(); }
finally { SqliteConnection.ClearAllPools(); }
