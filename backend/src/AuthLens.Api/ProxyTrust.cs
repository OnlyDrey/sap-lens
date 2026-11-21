using System.Net;
using System.Net.Sockets;
using Microsoft.AspNetCore.HttpOverrides;
using IPNetwork = System.Net.IPNetwork;

namespace AuthLens.Api;

/// <summary>Same-origin comparison between an Origin header and the request's effective scheme and authority. Exact, never suffix or wildcard based:
/// scheme equal, host equal (DNS names case-insensitively, IP literals by value, IPv6 with or without brackets), port equal after the scheme's default
/// port is filled in (https 443, http 80). Anything that is not a bare <c>scheme://host[:port]</c> (path, query, user info, "null") is invalid.</summary>
public static class OriginPolicy
{
    public enum Result { Match, Absent, Invalid, SchemeMismatch, HostMismatch, PortMismatch }

    public static Result Compare(string? origin, string scheme, HostString host)
    {
        if (string.IsNullOrEmpty(origin)) return Result.Absent;
        if (!TryParse(origin, out var originScheme, out var originHost, out var originPort)) return Result.Invalid;
        if (!string.Equals(originScheme, scheme, StringComparison.OrdinalIgnoreCase)) return Result.SchemeMismatch;
        if (!host.HasValue || !HostsEqual(originHost, host.Host)) return Result.HostMismatch;
        return (host.Port ?? DefaultPort(scheme)) == originPort ? Result.Match : Result.PortMismatch;
    }

    public static bool TryParse(string origin, out string scheme, out string host, out int port)
    {
        (scheme, host, port) = ("", "", 0);
        if (origin.Length > 512 || !Uri.TryCreate(origin, UriKind.Absolute, out var uri)) return false;
        if (uri.Scheme is not ("http" or "https") || uri.UserInfo.Length > 0 || uri.Query.Length > 0 || uri.Fragment.Length > 0) return false;
        // Nothing after the authority: no path, not even "/" (browsers never send one).
        var authorityStart = origin.IndexOf("://", StringComparison.Ordinal) + 3;
        if (origin.IndexOfAny(['/', '?', '#', '@', '\\'], authorityStart) >= 0) return false;
        (scheme, host, port) = (uri.Scheme, uri.Host, uri.Port);
        return host.Length > 0;
    }

    public static int DefaultPort(string scheme) => string.Equals(scheme, "https", StringComparison.OrdinalIgnoreCase) ? 443 : 80;

    public static bool HostsEqual(string a, string b)
    {
        a = a.Trim('[', ']');
        b = b.Trim('[', ']');
        if (IPAddress.TryParse(a, out var x) && IPAddress.TryParse(b, out var y)) return x.Equals(y);
        return a.Length > 0 && string.Equals(a, b, StringComparison.OrdinalIgnoreCase);
    }

    /// <summary>Origin reduced to scheme, host and port for logs; anything else is summarised, never echoed.</summary>
    public static string Describe(string? origin) =>
        string.IsNullOrEmpty(origin) ? "(none)" : TryParse(origin, out var s, out var h, out var p) ? $"{s}://{(h.Contains(':') && !h.StartsWith('[') ? $"[{h}]" : h)}:{p}" : $"(invalid, {origin.Length} characters)";
}

/// <summary>Reverse-proxy trust (opt-in). Forwarded headers (X-Forwarded-For, -Proto, -Host) are applied by ASP.NET Core's ForwardedHeadersMiddleware only
/// when the TCP peer is inside a configured trusted network, for at most the configured number of hops, each of which must itself be trusted; the
/// forwarded host must be one of the allowed hosts. Without configuration nothing is trusted (not even loopback), and forwarded headers are ignored.
/// The RFC 7239 Forwarded header is not processed.</summary>
public static class ProxyTrust
{
    public const int MaxHops = 5;
    public const string PeerItem = "AuthLens.Peer";
    public const string RawSchemeItem = "AuthLens.RawScheme";
    public const string RawHostItem = "AuthLens.RawHost";
    public const string ForwardedSummaryItem = "AuthLens.ForwardedSummary";
    private static readonly string[] ForwardedHeaderNames = ["X-Forwarded-For", "X-Forwarded-Proto", "X-Forwarded-Host", "Forwarded"];

    public static IPNetwork ParseNetwork(string text)
    {
        var value = text.Trim();
        if (value.Contains('/'))
        {
            if (!IPNetwork.TryParse(value, out var network)) throw new InvalidOperationException($"'{value}' is not an IP address or CIDR network for --trusted-proxies.");
            return network;
        }
        if (!IPAddress.TryParse(value, out var address)) throw new InvalidOperationException($"'{value}' is not an IP address or CIDR network for --trusted-proxies.");
        if (address.IsIPv4MappedToIPv6) address = address.MapToIPv4();
        if (address.AddressFamily == AddressFamily.InterNetworkV6) address.ScopeId = 0;
        return new IPNetwork(address, address.AddressFamily == AddressFamily.InterNetwork ? 32 : 128);
    }

    /// <summary>Refuses networks that cannot be a deliberate proxy boundary: unspecified, loopback, multicast, or wider than /24 (IPv4) or /64 (IPv6).</summary>
    public static void Validate(IReadOnlyList<IPNetwork> networks, int hops)
    {
        if (hops is < 1 or > MaxHops) throw new InvalidOperationException($"--trusted-proxy-hops must be between 1 and {MaxHops}.");
        foreach (var network in networks)
        {
            var address = network.BaseAddress;
            var minimum = address.AddressFamily == AddressFamily.InterNetwork ? 24 : 64;
            if (network.PrefixLength < minimum)
                throw new InvalidOperationException($"Trusted proxy network {network} is too wide; name the proxy addresses (at least /{minimum}).");
            if (address.Equals(IPAddress.Any) || address.Equals(IPAddress.IPv6Any) || IPAddress.IsLoopback(address) || address.IsIPv6Multicast ||
                (address.AddressFamily == AddressFamily.InterNetwork && address.GetAddressBytes()[0] is >= 224))
                throw new InvalidOperationException($"{network} cannot be a trusted proxy (unspecified, loopback or multicast).");
        }
    }

    public static bool Trusted(HostSettings settings, IPAddress? peer)
    {
        if (peer is null || settings.TrustedProxies.Count == 0) return false;
        if (peer.IsIPv4MappedToIPv6) peer = peer.MapToIPv4();
        return settings.TrustedProxies.Any(n => n.Contains(peer));
    }

    public static bool HasForwardedHeaders(HttpRequest request) => ForwardedHeaderNames.Any(request.Headers.ContainsKey);

    // Capture before middleware consumes the headers. Never echo arbitrary header text, URLs, cookies or credentials.
    public static string DescribeForwarded(HttpRequest request)
    {
        string Values(string name, Func<string, string> describe) => string.Join(",", request.Headers[name].ToString().Split(',').Take(MaxHops)
            .Select(v => v.Trim()).Select(v => v.Length == 0 ? "(absent)" : describe(v)));
        return $"host={Values("X-Forwarded-Host", v => OriginPolicy.TryParse("https://" + v, out _, out _, out _) ? OriginPolicy.Describe("https://" + v) : "(invalid)")}; " +
               $"proto={Values("X-Forwarded-Proto", v => v is "https" or "http" ? v : "(invalid)")}; " +
               $"for={Values("X-Forwarded-For", v => IPAddress.TryParse(v, out var ip) ? ip.ToString() : "(invalid)")}";
    }

    /// <summary>Registers the pipeline start: records the TCP peer and the raw scheme and Host for diagnostics, then (only with trusted proxies)
    /// ForwardedHeadersMiddleware. Must run before the request boundary.</summary>
    public static void Use(WebApplication app, HostSettings settings)
    {
        app.Use((context, next) =>
        {
            context.Items[PeerItem] = context.Connection.RemoteIpAddress;
            context.Items[RawSchemeItem] = context.Request.Scheme;
            context.Items[RawHostItem] = context.Request.Host.Value;
            context.Items[ForwardedSummaryItem] = DescribeForwarded(context.Request);
            return next(context);
        });
        if (settings.TrustedProxies.Count == 0) return;
        var options = new ForwardedHeadersOptions
        {
            ForwardedHeaders = ForwardedHeaders.XForwardedFor | ForwardedHeaders.XForwardedProto | ForwardedHeaders.XForwardedHost,
            ForwardLimit = settings.TrustedProxyHops,
            RequireHeaderSymmetry = false,
            // Exactly the allowed hosts (IPv6 literals in brackets, as they appear in a Host value); the middleware compares host names, not ports.
            AllowedHosts = [.. settings.AllowedHosts.Concat(settings.ProxyHosts).Select(h => IPAddress.TryParse(h, out var ip) && ip.AddressFamily == AddressFamily.InterNetworkV6 ? $"[{h}]" : h)],
        };
        options.KnownProxies.Clear();          // the defaults trust loopback; nothing is trusted implicitly
        options.KnownIPNetworks.Clear();
        foreach (var network in settings.TrustedProxies) options.KnownIPNetworks.Add(network);
        app.UseForwardedHeaders(options);
    }
}
