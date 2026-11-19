using System.Security.Cryptography;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;
using Microsoft.EntityFrameworkCore;
using AuthLens.Documents;
using AuthLens.Persistence;

namespace AuthLens.Api;

/// <summary>MIG-001, port of branding.py / report_branding.py: sanitized logos (decoded, bounded, re-encoded as metadata-free PNG by
/// <see cref="ImageSanitizer"/>) kept privately in &lt;data&gt;/branding/&lt;sha256&gt;.png, content-addressed and re-validated on every read, so an
/// altered or missing file is never served. Never part of release artifacts or configuration packages unless private export is requested.</summary>
public sealed partial class LogoStore(DatabaseOptions options)
{
    [GeneratedRegex("^[0-9a-f]{64}$")] private static partial Regex Identity();
    private string Folder => Path.Combine(options.DataDirectory, "branding");

    /// <summary>stage_image: stores a sanitized PNG; returns its id and data URL.</summary>
    public JsonObject Stage(byte[] untrusted, IReadOnlySet<ImageFormat>? formats = null, int maxBytes = ImageSanitizer.MaxImageBytes, int minSide = 1)
    {
        var png = ImageSanitizer.Sanitize(untrusted, formats, maxBytes, minSide);
        var id = Convert.ToHexStringLower(SHA256.HashData(png));
        Directory.CreateDirectory(Folder);
        var target = Path.Combine(Folder, id + ".png");
        if (!File.Exists(target))
        {
            var temporary = target + "." + Guid.NewGuid().ToString("N") + ".tmp";
            File.WriteAllBytes(temporary, png);
            File.Move(temporary, target, overwrite: true);
        }
        return new JsonObject { ["logo_id"] = id, ["data_url"] = "data:image/png;base64," + Convert.ToBase64String(png) };
    }

    /// <summary>logo_bytes: the stored PNG when the id is well-formed, the file matches its hash and still passes sanitizing; otherwise null.</summary>
    public byte[]? Read(string? id)
    {
        if (id is null || !Identity().IsMatch(id)) return null;
        try
        {
            var file = new FileInfo(Path.Combine(Folder, id + ".png"));
            if (!file.Exists || file.Length > ImageSanitizer.MaxImageBytes) return null;
            var data = File.ReadAllBytes(file.FullName);
            if (Convert.ToHexStringLower(SHA256.HashData(data)) != id) return null;
            ImageSanitizer.Sanitize(data);
            return data;
        }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException or ImageRejectedException) { return null; }
    }
}

public static class V1Branding
{
    private const string ReportDocument = "report-branding";
    private const int ReportMaxBytes = 1_000_000, ReportMinSide = 32;

    private static IResult Detail(int status, string detail) => Results.Json(new { detail }, statusCode: status);

    public static void Map(RouteGroupBuilder api)
    {
        // Application logo chosen by path in the Desktop file dialog. A Server never reads a path a browser names.
        api.MapPost("/branding/preview", async (HttpContext http, HostSettings host, LogoStore logos, CancellationToken ct) =>
        {
            var (body, invalid) = await V1Validation.ReadBody(http, ct);
            if (invalid is not null) return invalid;
            var errors = new List<object>();
            V1Validation.Extra(body!, ["path"], errors);
            var path = V1Validation.Text(body!, "path", 1, 4096, true, errors);
            if (errors.Count > 0) return Results.Json(new { detail = errors }, statusCode: 422);
            const string refused = "Choose a valid PNG, JPEG or WebP up to 2 MB and 4096 pixels per side. SVG is not supported.";
            if (host.Mode == HostMode.Server) return Detail(400, "On the server, custom logos cannot be read from a server path.");
            try
            {
                var extension = Path.GetExtension(path!).ToLowerInvariant();
                if (!Path.IsPathFullyQualified(path!) || path!.Contains("://", StringComparison.Ordinal) || extension is not (".png" or ".jpg" or ".jpeg" or ".webp")) return Detail(400, refused);
                var file = new FileInfo(path);
                if (file.Length > ImageSanitizer.MaxImageBytes) return Detail(400, refused);
                return Results.Content(logos.Stage(File.ReadAllBytes(file.FullName)).ToJsonString(), "application/json");
            }
            catch (Exception error) when (error is IOException or UnauthorizedAccessException or ImageRejectedException or ArgumentException or NotSupportedException)
            { return Detail(400, refused); }
        });

        api.MapGet("/branding/logo", async (V1Settings settings, LogoStore logos, CancellationToken ct) =>
        {
            var data = logos.Read((string?)(await settings.GetAsync(ct))["logo_id"]);
            return data is null ? Detail(404, "No valid custom logo; use the AuthLens default.") : Results.Json(new { data_url = "data:image/png;base64," + Convert.ToBase64String(data) });
        });

        // Report-only logo (PNG or JPEG, 32-4096 px, 1 MB), used by SoD reports.
        api.MapGet("/sod/reports/branding", async (IDbContextFactory<AuthLensDb> factory, LogoStore logos, CancellationToken ct) => Results.Content((await DescribeAsync(factory, logos, ct)).ToJsonString(), "application/json"));
        api.MapPut("/sod/reports/branding", async (HttpContext http, IDbContextFactory<AuthLensDb> factory, WriteCoordinator writer, LogoStore logos, TimeProvider clock, CancellationToken ct) =>
        {
            var (body, invalid) = await V1Validation.ReadBody(http, ct);
            if (invalid is not null) return invalid;
            var errors = new List<object>();
            V1Validation.Extra(body!, ["image_base64", "filename"], errors);
            var image = V1Validation.Text(body!, "image_base64", 1, 1_500_000, true, errors);
            var filename = V1Validation.Text(body!, "filename", 0, 200, false, errors) ?? "";
            if (errors.Count > 0) return Results.Json(new { detail = errors }, statusCode: 422);
            byte[] raw;
            try { raw = Convert.FromBase64String(image!); }
            catch (FormatException) { return Detail(422, "The image could not be read. Choose a PNG or JPEG file."); }
            JsonObject staged;
            try { staged = logos.Stage(raw, ImageSanitizer.ReportFormats, ReportMaxBytes, ReportMinSide); }
            catch (ImageRejectedException error) { return Detail(422, error.Message); }
            var record = new JsonObject { ["logo_id"] = staged["logo_id"]!.DeepClone(), ["filename"] = filename.Length > 120 ? filename[..120] : filename, ["updated"] = clock.GetUtcNow().ToString("yyyy-MM-dd'T'HH:mm:ss.ffffff'+00:00'") };
            await SaveAsync(writer, record, Actors.Name(http), clock, ct);
            return Results.Content((await DescribeAsync(factory, logos, ct)).ToJsonString(), "application/json");
        });
        api.MapDelete("/sod/reports/branding", async (HttpContext http, IDbContextFactory<AuthLensDb> factory, WriteCoordinator writer, LogoStore logos, TimeProvider clock, CancellationToken ct) =>
        {
            await SaveAsync(writer, new JsonObject(), Actors.Name(http), clock, ct);
            return Results.Content((await DescribeAsync(factory, logos, ct)).ToJsonString(), "application/json");
        });
    }

    private static JsonObject Limits() => new()
    {
        ["formats"] = new JsonArray("PNG", "JPEG"), ["max_bytes"] = ReportMaxBytes, ["min_pixels"] = ReportMinSide, ["max_pixels"] = 4096,
    };

    private static async Task SaveAsync(WriteCoordinator writer, JsonObject record, string actor, TimeProvider clock, CancellationToken ct) =>
        await writer.WriteAsync(async (db, token) =>
        {
            var row = await db.SodDocuments.FirstOrDefaultAsync(d => d.Name == ReportDocument, token);
            if (row is null) db.SodDocuments.Add(row = new SodDocument { Name = ReportDocument, Json = "{}" });
            (row.Json, row.Revision, row.UpdatedUtc, row.UpdatedBy) = (record.ToJsonString(), row.Revision + 1, clock.GetUtcNow().UtcDateTime, actor);
        }, ct);

    /// <summary>The id of a still-valid report logo, or null (a missing or altered file falls back to the application logo).</summary>
    public static async Task<string?> CurrentReportLogoAsync(IDbContextFactory<AuthLensDb> factory, LogoStore logos, CancellationToken ct)
    {
        await using var db = await factory.CreateDbContextAsync(ct);
        var row = await db.SodDocuments.AsNoTracking().FirstOrDefaultAsync(d => d.Name == ReportDocument, ct);
        var id = row is null ? null : (string?)JsonNode.Parse(row.Json)?["logo_id"];
        return logos.Read(id) is null ? null : id;
    }

    private static async Task<JsonObject> DescribeAsync(IDbContextFactory<AuthLensDb> factory, LogoStore logos, CancellationToken ct)
    {
        await using var db = await factory.CreateDbContextAsync(ct);
        var row = await db.SodDocuments.AsNoTracking().FirstOrDefaultAsync(d => d.Name == ReportDocument, ct);
        var stored = row is null ? new JsonObject() : JsonNode.Parse(row.Json) as JsonObject ?? [];
        var id = (string?)stored["logo_id"];
        var png = logos.Read(id);
        if (png is null) return new JsonObject { ["logo"] = null, ["limits"] = Limits() };
        var (width, height) = ImageSanitizer.Size(png);
        var filename = (string?)stored["filename"] ?? "";
        return new JsonObject
        {
            ["logo"] = new JsonObject
            {
                ["logo_id"] = id, ["data_url"] = "data:image/png;base64," + Convert.ToBase64String(png), ["width"] = width, ["height"] = height, ["bytes"] = png.Length,
                ["filename"] = filename.Length > 120 ? filename[..120] : filename, ["updated"] = stored["updated"]?.DeepClone(),
            },
            ["limits"] = Limits(),
        };
    }
}
