using System.Net;

namespace SapLens.Api;

/// <summary>Server configuration from command-line options and environment variables (options win). No secret is accepted on the command line, where
/// any local user could read it from the process list: the certificate password comes from SAP_LENS_V2_CERT_PASSWORD or a file
/// (--cert-password-file, for example a systemd credential), the access token from SAP_LENS_V2_TOKEN or the protected api-token file.
/// Unknown options are errors, so a typo never silently falls back to a default.</summary>
public static class ServerConfiguration
{
    public static readonly string[] ValueOptions = ["--data-dir", "--listen", "--port", "--allowed-hosts", "--cert", "--cert-key", "--cert-password-file", "--auth"];
    public static readonly string[] FlagOptions = ["--network", "--no-worker"];

    /// <summary>--help (-h) and --version: answered before any configuration is read, so they create no directory or token, open no certificate and
    /// never print a secret. Any other argument keeps the fail-closed parsing below.</summary>
    public static string? Informational(string[] args)
    {
        if (args.Any(a => a is "--help" or "-h")) return Help;
        if (args.Contains("--version")) return $"SAP Lens 2 server {V1Compatibility.Version}" + (V1Compatibility.SourceSha is { } sha ? $" (commit {sha})" : "");
        return null;
    }

    public const string Help = """
        SAP Lens 2 server (.NET prototype)

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
          --no-worker                                              Do not run the background import worker.
                                       SAP_LENS_V2_TOKEN           API access token (at least 32 characters); otherwise <data-dir>/api-token.
                                       SAP_LENS_V2_PRINCIPAL       Name recorded for API clients using the token. Default server-operator.
          --help, -h                                               Show this text and exit.
          --version                                                Show the version and exit.

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
        Directory.CreateDirectory(dataDirectory);
        return new HostSettings
        {
            DataDirectory = Path.GetFullPath(dataDirectory), ListenAddress = listen, Port = port, NetworkAccess = network, AllowedHosts = hosts, Certificate = certificate,
            AccessToken = Token(dataDirectory, environment), WorkerEnabled = !options.ContainsKey("--no-worker"), Authentication = auth,
            PrincipalName = environment("SAP_LENS_V2_PRINCIPAL") ?? "server-operator",
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
