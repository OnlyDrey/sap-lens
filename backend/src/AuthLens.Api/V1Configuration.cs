using System.Text.Json;
using System.Text.Json.Nodes;
using Microsoft.AspNetCore.Http.Features;
using Microsoft.EntityFrameworkCore;
using AuthLens.Application;
using AuthLens.Persistence;

namespace AuthLens.Api;

/// <summary>Port of configuration_routes.py (export, import, reset), portable_config.py and review_identity.py (the Desktop reviewer profile).
/// Portable packages never carry data, paths or dataset references. Custom logos are not migrated (branding): a package that carries one is refused
/// with its logo sanitized and staged (MIG-001).</summary>
public static class V1Configuration
{
    public const string ProfileDocument = "reviewer-profile";
    private const string SettingsBackupDocument = "settings-backup";

    private static IResult Detail(int status, string detail) => Results.Json(new { detail }, statusCode: status);
    private static IResult Json(JsonNode node) => Results.Content(node.ToJsonString(), "application/json");

    /// <summary>portable_config.export_configuration. Without include_private only the theme survives on top of the defaults.</summary>
    public static JsonObject Export(JsonObject current, bool includePrivate, LogoStore? logos = null)
    {
        var defaults = V1Compatibility.DefaultSettingsDocument();
        JsonObject exported;
        if (includePrivate) exported = current.DeepClone().AsObject();
        else
        {
            exported = defaults.DeepClone().AsObject();
            exported["theme"] = current["theme"]?.DeepClone();
            exported["theme_colors"] = current["theme_colors"]?.DeepClone();
        }
        exported["desktop"] = defaults["desktop"]?.DeepClone();
        foreach (var field in V1Settings.PathFields) exported[field] = "";
        exported["employee_snapshot_id"] = null;
        exported["data_lifecycle"] = defaults["data_lifecycle"]?.DeepClone();
        exported["revision"] = 0;
        // The logo travels only in a private export, as its validated image; a missing or altered file drops the reference (v1).
        var image = includePrivate ? logos?.Read((string?)current["logo_id"]) : null;
        exported["logo_id"] = image is null ? null : current["logo_id"]?.DeepClone();
        return new JsonObject { ["format"] = "AuthLens configuration", ["package_version"] = 1, ["settings"] = exported, ["logo_base64"] = image is null ? null : Convert.ToBase64String(image) };
    }

    /// <summary>portable_config.read_portable plus the import route: validates the package and returns the settings to apply, or the refusal.</summary>
    public static (JsonObject? Settings, IResult? Error) ReadPortable(JsonNode? body, JsonObject current, LogoStore? logos = null)
    {
        const string invalid = "Invalid configuration package or logo; nothing was applied.";
        if (body is not JsonObject package) return (null, Detail(422, "A configuration package is required."));
        foreach (var (key, _) in package)
            if (key is not ("format" or "package_version" or "settings" or "logo_base64")) return (null, Detail(422, $"Unknown package field '{key}'."));
        if (package.TryGetPropertyValue("format", out var format) && (format?.GetValueKind() != JsonValueKind.String || (string?)format is not ("AuthLens configuration" or "SAP Lens configuration")))
            return (null, Detail(422, "format must be 'AuthLens configuration'."));
        if (package.TryGetPropertyValue("package_version", out var version) && (version is not JsonValue v || !v.TryGetValue<int>(out var number) || number != 1))
            return (null, Detail(422, "package_version must be 1."));
        if (package["settings"] is not JsonObject settings) return (null, Detail(422, "settings is required."));
        var logo = package["logo_base64"];
        if (logo is not null && logo.GetValueKind() != JsonValueKind.String) return (null, Detail(422, "logo_base64 must be a string."));
        if (logo is not null && ((string)logo!).Length > 3_000_000) return (null, Detail(422, "logo_base64 is too long."));

        var defaults = V1Compatibility.DefaultSettingsDocument();
        if (V1Settings.Validate(settings, defaults) is { } problem && !problem.StartsWith("Source files", StringComparison.Ordinal)) return (null, Detail(422, problem));
        var lifecycle = settings["data_lifecycle"] as JsonObject;
        bool NonEmpty(string key) => lifecycle?[key] switch { JsonObject o => o.Count > 0, JsonArray a => a.Count > 0, _ => false };
        if (NonEmpty("sources") || NonEmpty("history") || NonEmpty("history_metadata") || NonEmpty("sod_history")) return (null, Detail(400, invalid));
        if (V1Settings.PathFields.Any(f => settings[f] is JsonValue p && p.GetValueKind() == JsonValueKind.String && ((string)p!).Length > 0)
            || settings["employee_snapshot_id"] is JsonValue s && s.GetValueKind() != JsonValueKind.Null) return (null, Detail(400, invalid));
        string? stagedLogo = null;
        if (logo is not null && ((string)logo!).Length > 0)
        {
            // read_portable: the logo is decoded, sanitized and staged; the package's own logo_id is replaced by the staged one.
            if (logos is null) return (null, Detail(400, invalid));
            try { stagedLogo = (string?)logos.Stage(Convert.FromBase64String((string)logo!))["logo_id"]; }
            catch (Exception error) when (error is FormatException or AuthLens.Documents.ImageRejectedException or IOException or UnauthorizedAccessException) { return (null, Detail(400, invalid)); }
        }
        else if (settings["logo_id"] is JsonValue id && id.GetValueKind() == JsonValueKind.String && ((string)id!).Length > 0) return (null, Detail(400, invalid));

        // Missing fields take v1 defaults (the package is a full AppConfig); local, server-managed state is kept.
        var candidate = defaults;
        foreach (var (key, value) in settings) candidate[key] = value?.DeepClone();
        foreach (var key in new[] { "desktop", "data_csv_path", "user_csv_path", "sod_csv_path", "employee_csv_path", "employee_snapshot_id", "data_lifecycle", "revision", "schema_version" })
            candidate[key] = current[key]?.DeepClone();
        if (stagedLogo is not null) candidate["logo_id"] = stagedLogo;
        return (candidate, null);
    }

    /// <summary>The Desktop reviewer profile (review_identity.profile): a stable, passwordless attribution for the single local user, never authentication.</summary>
    public static async Task<JsonObject> ProfileAsync(AuthLensDb db, CancellationToken ct)
    {
        var row = await db.SodDocuments.AsNoTracking().FirstOrDefaultAsync(d => d.Name == ProfileDocument, ct);
        return row is null ? NewProfile() : JsonNode.Parse(row.Json)!.AsObject();
    }

    private static JsonObject NewProfile() => new()
    {
        ["version"] = 1, ["revision"] = 0,
        ["identity"] = new JsonObject { ["id"] = Guid.NewGuid().ToString("N"), ["username"] = "", ["display_name"] = "Local reviewer", ["provenance"] = "desktop-local" },
    };

    /// <summary>Reads the profile, creating and storing it on first use, like v1 (the identity id must stay stable once a decision cites it).</summary>
    public static Task<JsonObject> EnsureProfileAsync(WriteCoordinator writer, TimeProvider clock, string? displayName, int? expectedRevision, CancellationToken ct) =>
        writer.WriteAsync(async (db, token) =>
        {
            var row = await db.SodDocuments.FirstOrDefaultAsync(d => d.Name == ProfileDocument, token);
            var profile = row is null ? NewProfile() : JsonNode.Parse(row.Json)!.AsObject();
            if (displayName is not null)
            {
                if (expectedRevision != (int)profile["revision"]!) throw new ImportConflictException("Reviewer profile changed. Reload before saving.");
                profile["identity"]!["display_name"] = displayName.Trim();
                profile["revision"] = (int)profile["revision"]! + 1;
                profile["modified"] = clock.GetUtcNow().ToString("yyyy-MM-dd'T'HH:mm:ss.ffffffzzz");
            }
            if (row is null || displayName is not null)
            {
                if (row is null) db.SodDocuments.Add(row = new SodDocument { Name = ProfileDocument, Json = "{}" });
                (row.Revision, row.Json, row.UpdatedUtc, row.UpdatedBy) = ((int)profile["revision"]!, profile.ToJsonString(), clock.GetUtcNow().UtcDateTime, "desktop-local");
            }
            return profile;
        }, ct);

    private static async Task<IResult> ApplyAsync(HttpContext http, V1Settings store, IDbContextFactory<AuthLensDb> factory, JsonObject current, JsonObject candidate, bool unloadData, CancellationToken ct)
    {
        try
        {
            await store.UpdateAsync((int)current["revision"]!, settings =>
            {
                foreach (var key in settings.Select(p => p.Key).ToList()) settings.Remove(key);
                foreach (var (key, value) in candidate) settings[key] = value?.DeepClone();
            }, Actors.Name(http), async (db, token) =>
            {
                // "A backup will be kept": the previous settings document is retained (one generation, like v1's settings backup file).
                var backup = await db.SodDocuments.FirstOrDefaultAsync(d => d.Name == SettingsBackupDocument, token);
                if (backup is null) db.SodDocuments.Add(backup = new SodDocument { Name = SettingsBackupDocument, Json = "{}" });
                (backup.Revision, backup.Json, backup.UpdatedUtc, backup.UpdatedBy) = ((int)current["revision"]!, current.ToJsonString(), DateTime.UtcNow, Actors.Name(http));
                // Reset unloads the datasets: active datasets are retired (kept as history, never deleted), in the same transaction.
                if (unloadData)
                    foreach (var active in await db.Datasets.Where(d => d.Status == DatasetStatus.Active).ToListAsync(token)) active.Status = DatasetStatus.Retired;
            }, ct);
        }
        catch (ImportConflictException) { return Detail(409, "Settings changed. Reload before applying your edits."); }
        return Json(await V1Compatibility.ConfigurationResponse(store, factory, ct));
    }

    public static void Map(RouteGroupBuilder api)
    {
        api.MapPost("/configuration/export", async (V1Settings store, LogoStore logos, HttpContext http, CancellationToken ct) =>
        {
            var raw = http.Request.Query["include_private"].ToString();
            if (raw.Length > 0 && !bool.TryParse(raw, out _) && raw is not ("0" or "1")) return Detail(422, "include_private must be a boolean.");
            var includePrivate = raw is "1" || (bool.TryParse(raw, out var flag) && flag);
            return Json(Export(await store.GetAsync(ct), includePrivate, logos));
        });

        api.MapPost("/configuration/import", async (HttpContext http, V1Settings store, LogoStore logos, IDbContextFactory<AuthLensDb> factory, CancellationToken ct) =>
        {
            var limit = http.Features.Get<IHttpMaxRequestBodySizeFeature>();
            if (limit is { IsReadOnly: false }) limit.MaxRequestBodySize = 4_000_000;
            JsonNode? body;
            try { body = await JsonNode.ParseAsync(http.Request.Body, cancellationToken: ct); }
            catch (JsonException) { return Detail(422, "The configuration package is not valid JSON."); }
            var current = await store.GetAsync(ct);
            var (candidate, error) = ReadPortable(body, current, logos);
            return error ?? await ApplyAsync(http, store, factory, current, candidate!, unloadData: false, ct);
        });

        api.MapPost("/configuration/reset", async (HttpContext http, V1Settings store, IDbContextFactory<AuthLensDb> factory, CancellationToken ct) =>
        {
            var current = await store.GetAsync(ct);
            var candidate = V1Compatibility.DefaultSettingsDocument();
            candidate["data_lifecycle"] = current["data_lifecycle"]?.DeepClone();
            candidate["revision"] = current["revision"]?.DeepClone();
            return await ApplyAsync(http, store, factory, current, candidate, unloadData: true, ct);
        });

        api.MapGet("/reviewer-profile", async (HostSettings host, WriteCoordinator writer, TimeProvider clock, CancellationToken ct) =>
            host.Mode == HostMode.Server ? Detail(403, "Use the authenticated account profile.") : Json(await EnsureProfileAsync(writer, clock, null, null, ct)));

        api.MapPost("/reviewer-profile", async (HttpContext http, HostSettings host, WriteCoordinator writer, TimeProvider clock, CancellationToken ct) =>
        {
            if (host.Mode == HostMode.Server) return Detail(403, "Use the authenticated account profile.");
            if (await JsonNode.ParseAsync(http.Request.Body, cancellationToken: ct) is not JsonObject body || body.Count != 2 || !body.ContainsKey("display_name") || !body.ContainsKey("expected_revision"))
                return Detail(422, "Specify display name and revision only.");
            var revision = body["expected_revision"] is JsonValue r && r.GetValueKind() == JsonValueKind.Number && r.TryGetValue<int>(out var n) ? n : (int?)null;
            var name = body["display_name"] is JsonValue d && d.GetValueKind() == JsonValueKind.String ? (string)d! : null;
            var current = await EnsureProfileAsync(writer, clock, null, null, ct);
            if (revision != (int)current["revision"]!) return Detail(409, "Reviewer profile changed. Reload before saving.");
            if (name is null || name.Trim().Length is < 1 or > 120) return Detail(422, "Use a display name of 1–120 characters.");
            try { return Json(await EnsureProfileAsync(writer, clock, name, revision, ct)); }
            catch (ImportConflictException error) { return Detail(409, error.Message); }
        });
    }
}
