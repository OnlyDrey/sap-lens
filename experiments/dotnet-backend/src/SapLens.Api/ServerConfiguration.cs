using System.Net;

namespace SapLens.Api;

/// <summary>Server configuration from command-line options and environment variables (options win). No secret is accepted on the command line, where
/// any local user could read it from the process list: the certificate password comes from SAP_LENS_V2_CERT_PASSWORD or a file
/// (--cert-password-file, for example a systemd credential), the access token from SAP_LENS_V2_TOKEN or the protected api-token file.
/// Unknown options are errors, so a typo never silently falls back to a default.</summary>
public static class ServerConfiguration
{
    public static readonly string[] ValueOptions = ["--data-dir", "--listen", "--port", "--allowed-hosts", "--cert", "--cert-key", "--cert-password-file", "--auth", "--trusted-proxies", "--trusted-proxy-hops"];
    public static readonly string[] FlagOptions = ["--network", "--no-worker"];

    /// <summary>--help (-h) and --version: answered before any configuration is read, so they create no directory or token, open no certificate and
    /// never print a secret. Any other argument keeps the fail-closed parsing below.</summary>
    public static string? Informational(string[] args)
    {
        if (args.Any(a => a is "--help" or "-h")) return Help;
        if (args.Contains("--version")) return ProductIdentity.Describe("server");
        return null;
    }

    /// <summary>--check-sign-in USERNAME with --data-dir (or SAP_LENS_V2_DATA_DIR): the account store path and the username to diagnose.</summary>
    public static (string Store, string Username) SignInCheck(string[] args, Func<string, string?> environment)
    {
        string? Value(string name) { var i = Array.IndexOf(args, name); return i >= 0 && i + 1 < args.Length && !args[i + 1].StartsWith("--", StringComparison.Ordinal) ? args[i + 1] : null; }
        var username = Value("--check-sign-in") ?? throw new InvalidOperationException("--check-sign-in needs a username.");
        var data = Value("--data-dir") ?? environment("SAP_LENS_V2_DATA_DIR") ?? throw new InvalidOperationException("--data-dir (or SAP_LENS_V2_DATA_DIR) is required.");
        if (!Path.IsPathFullyQualified(data)) throw new InvalidOperationException("--data-dir must be an absolute path.");
        return (SapLens.Application.Accounts.AccountStore.For(data), username);
    }

    /// <summary>--backup-key create|use|export PATH with --data-dir: a LOCAL host backup key operation. The key itself is never printed.</summary>
    public static (string Action, string Path, string Data) BackupKey(string[] args, Func<string, string?> environment)
    {
        var i = Array.IndexOf(args, "--backup-key");
        var action = i + 1 < args.Length ? args[i + 1] : "";
        if (action is not ("create" or "use" or "export" or "status")) throw new InvalidOperationException("--backup-key needs create, use, export or status.");
        var path = action == "status" ? "" : i + 2 < args.Length && !args[i + 2].StartsWith("--", StringComparison.Ordinal) ? args[i + 2] : throw new InvalidOperationException($"--backup-key {action} needs a file path.");
        var d = Array.IndexOf(args, "--data-dir");
        var data = (d >= 0 && d + 1 < args.Length ? args[d + 1] : null) ?? environment("SAP_LENS_V2_DATA_DIR") ?? throw new InvalidOperationException("--data-dir (or SAP_LENS_V2_DATA_DIR) is required.");
        if (!System.IO.Path.IsPathFullyQualified(data) || (path.Length > 0 && !System.IO.Path.IsPathFullyQualified(path))) throw new InvalidOperationException("--data-dir and the key path must be absolute paths.");
        return (action, path, data);
    }

    /// <summary>A secret from the console without echo, or one line of redirected input.</summary>
    public static string ReadSecret()
    {
        if (Console.IsInputRedirected) return Console.In.ReadLine() ?? "";
        var sb = new System.Text.StringBuilder();
        while (true)
        {
            var key = Console.ReadKey(intercept: true);
            if (key.Key == ConsoleKey.Enter) return sb.ToString();
            if (key.Key == ConsoleKey.Backspace) { if (sb.Length > 0) sb.Length--; continue; }
            if (!char.IsControl(key.KeyChar)) sb.Append(key.KeyChar);
        }
    }

    public const string Help = """
        SAP Lens server (.NET)

        Usage: SapLens.Api --data-dir <absolute path> [options]

        Options (each also read from the environment variable shown; a command-line option wins):
          --data-dir <path>            SAP_LENS_V2_DATA_DIR        Required. Absolute, local path (no network share). Created if missing.
          --listen <ip>                SAP_LENS_V2_LISTEN          IP address to bind. Default 127.0.0.1. Non-loopback needs --network.
          --port <1-65535>             SAP_LENS_V2_PORT            Default 18790.
          --network                    SAP_LENS_V2_NETWORK=true    Allow LAN access: one private --listen address, --cert and --allowed-hosts.
          --allowed-hosts <a,b>        SAP_LENS_V2_ALLOWED_HOSTS   Host names or addresses clients use (no wildcards). Required with --network.
          --cert <file>                SAP_LENS_V2_CERT            .pfx/.p12 or PEM certificate; enables HTTPS. Required with --network.
          --cert-key <file>            SAP_LENS_V2_CERT_KEY        PEM private key file (PEM certificates only).
          --cert-password-file <file>  SAP_LENS_V2_CERT_PASSWORD_FILE  File holding the certificate password.
                                       SAP_LENS_V2_CERT_PASSWORD   Password from the environment, used only without a password file.
          --auth <mode>                SAP_LENS_V2_AUTH            accounts (default) or shared-token.
          --trusted-proxies <a,b>      SAP_LENS_V2_TRUSTED_PROXIES Reverse proxies (IP or CIDR, at most /24 or /64 wide) whose X-Forwarded-For,
                                                                   -Proto and -Host are applied. Default none. Needs --network.
          --trusted-proxy-hops <1-5>   SAP_LENS_V2_TRUSTED_PROXY_HOPS  Trusted proxy hops to walk back through. Default 1.
          --no-worker                                              Do not run the background import worker.
                                       SAP_LENS_V2_TOKEN           API access token (at least 32 characters); otherwise <data-dir>/api-token.
                                       SAP_LENS_V2_PRINCIPAL       Name recorded for API clients using the token. Default server-operator.
          --help, -h                                               Show this text and exit.
          --version                                                Show the version and exit.
          --check-sign-in <username>                               With --data-dir: explain locally why a sign-in is refused, then exit.
                                                                   Read-only (opens the account store read-only, starts no server); the
                                                                   password is typed without echo and never printed.
          --backup-key create <file>                               With --data-dir: create a new private host backup key file outside the data
                                                                   directory and use it, then exit. The key is never printed.
          --backup-key use <file>                                  With --data-dir: use an existing host backup key file, then exit.
          --backup-key export <file>                               With --data-dir: write a recovery copy to a new private file (store it separately,
                                                                   then verify it in Settings > Backups), then exit.
          --backup-key status                                      With --data-dir: show whether a key is configured and its fingerprint.
          --schema-info                                            With --data-dir: migrations this build knows and the database applied (read-only).
          --backup-local <folder>                                  With --data-dir: a verified, host-key encrypted archive of the data (online copy).
          --backup-verify <file>                                   With --data-dir: decrypt and validate an archive like a restore would.
          --migrate-v1 preview --source <dir|.slbak|.tar.gz>       With --data-dir: dry run of a SAP Lens 1 data migration (read-only for the source;
                                                                   add --replace-existing to allow replacing existing SAP Lens 2 data). Prints a digest.
                                                                   An encrypted .slbak asks for its passphrase, or for the recovery key of a
                                                                   host-key archive; --v1-key-file <file> reads that recovery key from its file.
          --migrate-v1 run --id <id> --approve <digest>            Build and verify the migrated data separately, with a migration backup.
          --migrate-v1 activate --id <id> --approve <digest>       Activate the verified migration at the next start (previous data is kept).
          --migrate-v1 rollback --id <id>                          Return to the previous SAP Lens 2 data at the next start.
          --migrate-v1 status --id <id>                            Show a migration report.

        Secrets are never accepted as options: --cert-password and --token are refused.
        Unknown options, missing values and invalid settings stop startup with exit code 3 and "startup refused: <reason>".
        """;

    public static HostSettings Parse(string[] args, Func<string, string?> environment)
    {
        var options = new Dictionary<string, string>(StringComparer.Ordinal);
        for (var i = 0; i < args.Length; i++)
        {
            var name = args[i];
            if (name is "--cert-password" or "--token") throw new InvalidOperationException($"{name} is not accepted on the command line; use the environment or a protected file.");
            if (FlagOptions.Contains(name)) { options[name] = "true"; continue; }
            if (!ValueOptions.Contains(name)) throw new InvalidOperationException($"Unknown option '{name}'.");
            if (i + 1 >= args.Length || args[i + 1].StartsWith("--", StringComparison.Ordinal)) throw new InvalidOperationException($"{name} needs a value.");
            options[name] = args[++i];
        }
        string? Get(string option, string variable) => options.TryGetValue(option, out var v) ? v : environment(variable) is { Length: > 0 } e ? e : null;

        var dataDirectory = Get("--data-dir", "SAP_LENS_V2_DATA_DIR") ?? throw new InvalidOperationException("--data-dir (or SAP_LENS_V2_DATA_DIR) is required.");
        if (!Path.IsPathFullyQualified(dataDirectory)) throw new InvalidOperationException("--data-dir must be an absolute path.");
        var listenText = Get("--listen", "SAP_LENS_V2_LISTEN") ?? "127.0.0.1";
        if (!IPAddress.TryParse(listenText, out var listen)) throw new InvalidOperationException($"--listen must be an IP address, not '{listenText}'.");
        var portText = Get("--port", "SAP_LENS_V2_PORT");
        var port = 18790;
        if (portText is not null && (!int.TryParse(portText, out port) || port is < 1 or > 65535)) throw new InvalidOperationException("--port must be between 1 and 65535.");
        var network = options.ContainsKey("--network") || string.Equals(environment("SAP_LENS_V2_NETWORK"), "true", StringComparison.OrdinalIgnoreCase);
        var hosts = (Get("--allowed-hosts", "SAP_LENS_V2_ALLOWED_HOSTS") ?? "").Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);

        var certificatePath = Get("--cert", "SAP_LENS_V2_CERT");
        var certificate = certificatePath is null ? null : CertificatePolicy.Load(Path.GetFullPath(certificatePath), Get("--cert-key", "SAP_LENS_V2_CERT_KEY"), Password(Get("--cert-password-file", "SAP_LENS_V2_CERT_PASSWORD_FILE"), environment));
        var auth = (Get("--auth", "SAP_LENS_V2_AUTH") ?? "accounts") switch
        {
            "accounts" => AuthenticationMode.Accounts,
            "shared-token" => AuthenticationMode.SharedToken,
            var other => throw new InvalidOperationException($"--auth must be 'accounts' or 'shared-token', not '{other}'."),
        };
        var proxies = (Get("--trusted-proxies", "SAP_LENS_V2_TRUSTED_PROXIES") ?? "").Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries)
            .Select(ProxyTrust.ParseNetwork).ToList();
        var hopsText = Get("--trusted-proxy-hops", "SAP_LENS_V2_TRUSTED_PROXY_HOPS");
        var hops = 1;
        if (hopsText is not null && (!int.TryParse(hopsText, out hops) || hops is < 1 or > ProxyTrust.MaxHops))
            throw new InvalidOperationException($"--trusted-proxy-hops must be between 1 and {ProxyTrust.MaxHops}.");
        if (hopsText is not null && proxies.Count == 0) throw new InvalidOperationException("--trusted-proxy-hops needs --trusted-proxies.");
        Directory.CreateDirectory(dataDirectory);
        return new HostSettings
        {
            DataDirectory = Path.GetFullPath(dataDirectory), ListenAddress = listen, Port = port, NetworkAccess = network, AllowedHosts = hosts, Certificate = certificate,
            AccessToken = Token(dataDirectory, environment), WorkerEnabled = !options.ContainsKey("--no-worker"), Authentication = auth,
            PrincipalName = environment("SAP_LENS_V2_PRINCIPAL") ?? "server-operator", TrustedProxies = proxies, TrustedProxyHops = hops,
        };
    }

    private static string? Password(string? file, Func<string, string?> environment)
    {
        if (file is null) return environment("SAP_LENS_V2_CERT_PASSWORD");
        if (!File.Exists(file)) throw new InvalidOperationException($"The certificate password file '{file}' does not exist.");
        return File.ReadAllText(file).TrimEnd('\r', '\n');
    }

    /// <summary>The token comes from the environment (service configuration) or is generated once into a file only the service account can read.</summary>
    private static string Token(string dataDirectory, Func<string, string?> environment)
    {
        if (environment("SAP_LENS_V2_TOKEN") is { Length: > 0 } token) return token;
        var tokenFile = Path.Combine(dataDirectory, "api-token");
        if (!File.Exists(tokenFile))
        {
            var create = new FileStreamOptions { Mode = FileMode.CreateNew, Access = FileAccess.Write };
            // Linux: owner read/write only. Windows: inherits the data directory ACL, which the deployment restricts to the service account and admins.
            if (!OperatingSystem.IsWindows()) create.UnixCreateMode = UnixFileMode.UserRead | UnixFileMode.UserWrite;
            using var writer = new StreamWriter(new FileStream(tokenFile, create));
            writer.Write(HostSettings.NewToken());
        }
        return File.ReadAllText(tokenFile).Trim();
    }
}
