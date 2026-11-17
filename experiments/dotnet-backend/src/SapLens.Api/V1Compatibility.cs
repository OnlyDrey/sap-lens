using System.Reflection;
using System.Security.Cryptography;
using System.Text.Json;
using System.Text.Json.Nodes;
using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;
using SapLens.Application;
using SapLens.Domain.Analysis;
using SapLens.Domain.Catalogue;
using SapLens.Domain.Roles;
using SapLens.Persistence;

namespace SapLens.Api;

/// <summary>The v1 HTTP contract the production React UI (frontend/, unchanged) calls, served from the C# domain. Response shapes follow the Python v1
/// routers and models field by field. A route that is not migrated yet answers 501 with a FastAPI-style "detail" that the UI shows: never invented data.
/// Authentication, host, origin and CSRF checks are the same RequestBoundary as /api/v1.</summary>
public static class V1Compatibility
{
    /// <summary>Changes with every process start, like v1's instance id: the UI treats a new boot as newer data.</summary>
    public static readonly string Boot = Convert.ToHexStringLower(RandomNumberGenerator.GetBytes(8));
    private static readonly Lazy<JsonObject> Registry = new(() => Load("registry.json"));
    private static readonly Lazy<JsonObject> DefaultSettings = new(() => Load("default-settings.json"));
    /// <summary>The SAP Lens 2 product version (see ProductIdentity; never v1's).</summary>
    public static readonly string Version = ProductIdentity.Version;
    /// <summary>The commit the build was made from (release scripts pass -p:SourceRevisionId); null for builds without it.</summary>
    public static readonly string? SourceSha = ProductIdentity.Commit;

    /// <summary>A fresh copy of v1's default settings document.</summary>
    public static JsonObject DefaultSettingsDocument() => DefaultSettings.Value.DeepClone().AsObject();

    private static JsonObject Load(string name)
    {
        using var stream = typeof(V1Compatibility).Assembly.GetManifestResourceStream("V1Reference." + name)
                           ?? throw new InvalidOperationException($"Embedded v1 reference data '{name}' is missing from this build.");
        return JsonNode.Parse(stream)!.AsObject();
    }

    /// <summary>The routes the React UI references that this server implements; everything else under /api (outside /api/v1) is "not migrated".</summary>
    public static readonly string[] Migrated =
    [
        "GET /api/auth/state", "GET /api/configuration", "GET /api/presentation", "GET /api/registry/modules", "GET /api/version", "GET /api/application-info",
        "GET /api/runtime", "GET /api/modules", "GET /api/roles", "GET /api/roles/{agr_name}",
        "POST /api/configuration", "POST /api/configuration/theme", "GET /api/data-sources/history", "POST /api/refresh", "GET /api/refresh-schedule", "POST /api/refresh-schedule/preview", "GET /api/functional-groups", "POST /api/branding/preview", "GET /api/branding/logo", "GET /api/sod/reports/branding", "PUT /api/sod/reports/branding", "DELETE /api/sod/reports/branding", "GET /api/data-sources/reports/{id}", "GET /api/data-sources/reports/{id}/export", "GET /api/data-sources/{source}/preview", "POST /api/data/cancel",
        "POST /api/data-sources/{source}/select", "POST /api/server/uploads/{source}/activate",
        "GET /api/access/users", "GET /api/access/users/{username}", "GET /api/access/users-selection", "GET /api/access/exports/users",
        "GET /api/access/release-options", "GET /api/access/release-roles", "GET /api/access/exports/release-roles", "GET /api/access/exports/releases", "GET /api/access/releases", "GET /api/access/release-assignments", "GET /api/user-comparison", "GET /api/user-comparison/evidence",
        "GET /api/data-health", "GET /api/dashboard",
        "GET /api/roles/naming", "POST /api/roles/package/preview", "POST /api/roles/package/export",
        "GET /api/saved-filters", "POST /api/saved-filters", "POST /api/saved-filters/delete",
        "GET /api/employees/status", "GET /api/employees", "GET /api/employees/record/{employee_id}", "GET /api/employees/match/{username}", "POST /api/employees/clear",
        "POST /api/employees/persist", "POST /api/data-sources/employees/inspect", "POST /api/employees/preview", "POST /api/employees/import",
        "GET /api/sod/catalogue", "GET /api/sod/catalogue/{risk_id}", "POST /api/sod/catalogue/{risk_id}", "POST /api/sod/catalogue/bulk", "GET /api/sod/catalogue/export",
        "GET /api/sod/catalogue-activities", "GET /api/sod/catalogue-activities/{activity}", "POST /api/sod/catalogue-activities/{activity}", "GET /api/sod/appearance", "GET /api/sod/metadata",
        "GET /api/sod/reference", "POST /api/sod/reference/reset", "POST /api/sod/reference/upload", "PUT /api/sod/reference", "GET /api/sod/reference/template",
        "GET /api/sod/analysis", "GET /api/sod/analysis/evidence", "GET /api/sod/analysis/export",
        "POST /api/configuration/export", "POST /api/configuration/import", "POST /api/configuration/reset", "GET /api/reviewer-profile", "POST /api/reviewer-profile", "GET /api/diagnostics", "GET /api/diagnostics/export", "POST /api/compare",
        "POST /api/sod/decisions/{kind}", "GET /api/sod/decisions/{kind}/history", "GET /api/sod/decisions/{kind}/evidence", "GET /api/sod/subject", "POST /api/sod/remediation/actions", "POST /api/sod/decisions/assignment/bulk", "POST /api/import/headers", "POST /api/import/preview", "POST /api/user-import/headers", "POST /api/user-import/preview", "GET /api/sod/review-subjects", "POST /api/sod/simulate", "POST /api/storage/lifecycle/rebaseline",
        "GET /api/sod/context", "GET /api/sod/overview", "GET /api/sod/matrix/{kind}", "GET /api/sod/matrix/{kind}/group-export", "GET /api/sod/filter-options",
        "GET /api/sod/explorer/{table}", "GET /api/sod/explorer/{table}/export", "GET /api/sod/explorer/access_list", "GET /api/sod/explorer/access_list/selection",
        "GET /api/sod/queue", "GET /api/sod/queue/users", "GET /api/sod/queue/export", "GET /api/sod/remediation", "GET /api/sod/remediation/export", "POST /api/sod/decisions/assignment",
        "GET /api/sod/periods", "POST /api/sod/periods", "GET /api/sod/periods/compare", "GET /api/sod/periods/{id}", "POST /api/sod/periods/{id}/transition",
        "POST /api/sod/periods/{id}/recapture", "POST /api/sod/periods/{id}/reviews/{finding_id}", "GET /api/sod/periods/{id}/deletion-impact", "POST /api/sod/periods/{id}/delete",
        "POST /api/sod/reviews/{finding_id}", "GET /api/sod/reviews/{finding_id}/history",
        "POST /api/sod/reports/preview", "POST /api/sod/reports/{kind}", "POST /api/sod/reports/remediation/preview", "POST /api/sod/reports/remediation/{kind}", "POST /api/sod/reports/remediation/csv",
        "GET /api/account-review", "POST /api/account-review/decision/{username}", "GET /api/account-review/history/{username}",
        // Accounts mode (the Server default); in shared-token mode these answer 501.
        "POST /api/auth/activate", "POST /api/auth/recover", "POST /api/auth/login", "POST /api/auth/reset", "GET /api/auth/me", "GET /api/auth/sessions",
        "POST /api/auth/logout", "POST /api/auth/logout-all", "POST /api/auth/logout-others", "POST /api/auth/password", "POST /api/auth/profile",
        "GET /api/auth/users", "POST /api/auth/users", "POST /api/auth/users/{identity}", "POST /api/auth/users/{identity}/revoke", "POST /api/auth/users/{identity}/reset",
        "GET /api/auth/audit", "GET /api/auth/policy", "POST /api/auth/policy", "GET /api/auth/migration", "POST /api/auth/migration/{identifier}/{action}",
    ];

    public static void Map(WebApplication app)
    {
        var api = app.MapGroup("/api").ExcludeFromDescription().AddEndpointFilter(async (context, next) =>
        {
            // X-Data-Revision as v1 sends it ("boot.publication.directory"): publication grows with every activated dataset in this process.
            var factory = context.HttpContext.RequestServices.GetRequiredService<IDbContextFactory<SapLensDb>>();
            await using (var db = await factory.CreateDbContextAsync(context.HttpContext.RequestAborted))
            {
                var ids = await SnapshotService.ActiveAsync(db, context.HttpContext.RequestAborted);
                context.HttpContext.Response.Headers["X-Data-Revision"] = $"{Boot}.{(ids.Roles ?? 0) + (ids.Users ?? 0) + (ids.Sod ?? 0)}.{(ids.Employees ?? 0)}";
            }
            return await next(context);
        });

        api.MapGet("/auth/state", async (HttpContext http, HostSettings settings) => settings.Authentication == AuthenticationMode.Accounts
            ? Results.Json(await http.RequestServices.GetRequiredService<SapLens.Application.Accounts.AccountStore>().StateAsync())
            : Results.Json(new
        {
            // Not "local-sessions": the React sign-in form for v1 accounts is not shown. The server's shared-token sign-in happened before the page loaded.
            provider = settings.Mode == HostMode.Desktop ? "desktop" : "shared-token", setup_required = false,
        }));
        api.MapGet("/configuration", Configuration);
        api.MapGet("/presentation", Configuration);
        // registry_list(overrides): effective entries with the saved overrides, plus the canonical defaults the Settings editor needs.
        api.MapGet("/registry/modules", async (V1Settings store, CancellationToken ct) =>
        {
            var overrides = (await store.GetAsync(ct))["module_overrides"] as JsonObject;
            var registry = Registry.Value.DeepClone().AsObject();
            registry["modules"] = new JsonArray([.. registry["modules"]!.AsArray().Select(m => (JsonNode)Effective(m!.AsObject(), overrides))]);
            return Results.Content(registry.ToJsonString(), "application/json");
        });
        api.MapGet("/version", () => new { app = "SAP Lens", version = Version, mode = "dotnet-preview" });
        api.MapGet("/application-info", () => new
        {
            version = Version, mode = "dotnet-preview", source_sha = SourceSha, file_version = ProductIdentity.FileVersion, python = (string?)null,
            product = ProductIdentity.Product, channel = ProductIdentity.Channel,
            runtime = $".NET {Environment.Version}", platform = System.Runtime.InteropServices.RuntimeInformation.OSDescription,
        });
        api.MapGet("/runtime", (HttpContext http, HostSettings settings) => new
        {
            // Browser uploads are migrated (Phase 2A). The .NET Desktop has no native file dialogs; WebView2 uses the browser file picker. A Server never
            // accepts server file paths from a browser (selection answers 400), so its policy is the restrictive one.
            deployment_mode = settings.Mode == HostMode.Server ? "server" : "desktop", browser_upload = true, username = Actors.Name(http),
            role = settings.Authentication == AuthenticationMode.Accounts ? Actors.Current(http).Role : "",
            native_dialogs = false, source_path_policy = settings.Mode == HostMode.Server ? "configured_root" : "desktop_filesystem",
        });

        api.MapGet("/modules", async (SnapshotService snapshots, V1Settings store, CancellationToken ct) =>
        {
            var snapshot = await snapshots.GetAsync(ct);
            var overrides = (await store.GetAsync(ct))["module_overrides"] as JsonObject;
            return snapshot.Catalogue.Ordered.Select(r => r.FunctionKey).Distinct(StringComparer.Ordinal).Order(StringComparer.Ordinal).Select(k => ModuleInfo(k, overrides)).ToList();
        });

        api.MapGet("/roles", async (SnapshotService snapshots, [FromQuery(Name = "function_key")] string? functionKey, [FromQuery(Name = "function_keys")] string[]? functionKeys,
            [FromQuery(Name = "transaction_mode")] string? transactionMode, [FromQuery] string? search, [FromQuery] string[]? tcodes,
            [FromQuery(Name = "exclude_matching")] bool? excludeMatching, [FromQuery] string? tcode, [FromQuery(Name = "exclude_tcodes")] string[]? excludeTcodes,
            [FromQuery(Name = "exclude_mode")] string? excludeMode, CancellationToken ct) =>
        {
            if (transactionMode is not (null or "and" or "or") || excludeMode is not (null or "any" or "all")) return Unprocessable("Unsupported transaction mode.");
            if ((functionKeys?.Length ?? 0) > 100 || (tcodes?.Length ?? 0) > 21 || (excludeTcodes?.Length ?? 0) > 21) return Unprocessable("Too many filter values.");
            var snapshot = await snapshots.GetAsync(ct);
            var rows = RoleLookup.Find(snapshot.Catalogue, new RoleLookupQuery(search, functionKeys, functionKey, tcodes, transactionMode ?? "and", excludeMatching ?? false, tcode,
                excludeTcodes, excludeMode ?? "any"));
            return Results.Ok(rows.Select(r => RoleSummary(snapshot.Catalogue.Roles[r.AgrName], r)).ToList());
        });

        api.MapGet("/roles/{**agrName}", async (HttpContext http, string agrName, SnapshotService snapshots, CancellationToken ct) =>
        {
            var snapshot = await snapshots.GetAsync(ct);
            return snapshot.Catalogue.Roles.TryGetValue(agrName, out var role)
                ? Results.Ok(RoleDetail(role))
                : Results.Json(new { detail = $"Role '{agrName}' not found." }, statusCode: 404);
        });

        V1DataSources.Map(api);
        V1RefreshReports.Map(api);
        V1Refresh.Map(api);
        V1RefreshSchedule.Map(api);
        V1FunctionalGroups.Map(api);
        V1Branding.Map(api);
        SodPeriods.Map(api);
        V1SodGovernance.Map(api);
        SodReports.Map(api);
        V1ImportPreview.Map(api);
        V1Access.Map(api);
        V1DataHealth.Map(api);
        V1Dashboard.Map(api);
        V1SavedFilters.Map(api);
        V1AccessPackage.Map(api);
        V1Employees.Map(api);
        V1AccountReview.Map(api);
        V1SodCatalogue.Map(api);
        V1SodAnalysis.Map(api);
        V1Configuration.Map(api);
        V1ReleaseRoles.Map(api);
        V1Diagnostics.Map(api);
        V1Compare.Map(api);
        V1SodDecisions.Map(api);
        V1Auth.Map(api, app.Services.GetRequiredService<HostSettings>());

        // Everything else the UI may call: explicit, visible "not migrated" (except /api/v1, which keeps its own 404s).
        api.Map("/{**rest}", (HttpContext http, string? rest) =>
            rest is not null && (rest == "v1" || rest.StartsWith("v1/", StringComparison.Ordinal))
                ? Results.Json(new { detail = "Not found.", status = 404 }, statusCode: 404)
                : NotMigrated(http, rest ?? ""));
    }

    public static IResult NotMigrated(HttpContext? http, string rest) => Results.Json(new
    {
        detail = $"This SAP Lens function is not available in the .NET server yet ({http?.Request.Method ?? "GET"} /api/{rest}). No data was changed.",
        code = "not_migrated", status = 501,
    }, statusCode: 501);

    private static IResult Unprocessable(string message) => Results.Json(new { detail = message }, statusCode: 422);

    private static async Task<IResult> Configuration(V1Settings store, IDbContextFactory<SapLensDb> factory, CancellationToken ct) =>
        Results.Content((await ConfigurationResponse(store, factory, ct)).ToJsonString(), "application/json");

    public static async Task<JsonObject> ConfigurationResponse(V1Settings store, IDbContextFactory<SapLensDb> factory, CancellationToken ct)
    {
        await using var db = await factory.CreateDbContextAsync(ct);
        var ids = await SnapshotService.ActiveAsync(db, ct);
        return new JsonObject
        {
            ["settings"] = await store.GetAsync(ct),
            ["notice"] = null,
            ["error"] = null, ["loading"] = false, ["progress"] = null, ["analysis"] = new JsonObject(),
            ["data_revision"] = $"{Boot}.{(ids.Roles ?? 0) + (ids.Users ?? 0) + (ids.Sod ?? 0)}.{(ids.Employees ?? 0)}", ["instance_id"] = Boot,
        };
    }

    private static JsonObject? RegistryEntry(string id) =>
        Registry.Value["modules"]!.AsArray().Select(m => m!.AsObject()).FirstOrDefault(m => (string?)m["id"] == id);

    /// <summary>The registry ids a module override may use (v1: stable registry identifiers only).</summary>
    internal static bool IsRegistryId(string id) => RegistryEntry(id) is not null;
    internal static IEnumerable<string> RegistryIcons() => Registry.Value["icons"]!.AsArray().Select(i => (string)i!);

    /// <summary>module_definition: the registry entry with its saved override applied (non-null fields), named by display_name when one is set.</summary>
    private static JsonObject Effective(JsonObject entry, JsonObject? overrides)
    {
        var item = entry.DeepClone().AsObject();
        if (overrides?[(string)entry["id"]!] is JsonObject chosen)
            foreach (var (key, value) in chosen)
                if (value is not null) item[key] = value.DeepClone();
        if (item["display_name"] is JsonValue name && name.TryGetValue<string>(out var text) && text.Length > 0) item["name"] = text;
        return item;
    }

    internal static bool ModuleEnabled(string functionKey, JsonObject? overrides = null) =>
        (bool?)Effective(RegistryEntry(functionKey) ?? RegistryEntry("UNCLASSIFIED")!, overrides)["enabled"] ?? true;

    private static object ModuleInfo(string functionKey, JsonObject? overrides)
    {
        var entry = Effective(RegistryEntry(functionKey) ?? RegistryEntry("UNCLASSIFIED")!, overrides);
        return new
        {
            function_key = (string?)entry["id"], module_name = (string?)entry["name"], icon = (string?)entry["icon"], color = (string?)entry["color"],
            enabled = (bool?)entry["enabled"] ?? true, category = (string?)entry["category"],
        };
    }

    private static Dictionary<string, object?> RoleSummary(Role role, RoleSummary? match = null) => new()
    {
        ["agr_name"] = role.AgrName, ["text"] = role.Text, ["function_key"] = role.FunctionKey, ["module_name"] = role.ModuleName, ["tcode_count"] = role.TcodeCount,
        ["single_role_count"] = role.SingleRoles.Count, ["matching_tcodes"] = match?.MatchingTcodes ?? [], ["module_ambiguous"] = role.ModuleAmbiguous,
        ["source_modules"] = role.SourceModules,
    };

    private static object Source(AssignmentSource s) => new { child_agr = s.ChildAgr, parent_agr = s.ParentAgr, effective_role = s.EffectiveRole };

    private static Dictionary<string, object?> RoleDetail(Role role)
    {
        var detail = RoleSummary(role);
        detail["single_roles"] = role.SingleRoles.Select(s => new
        {
            assignment_kind = s.AssignmentKind, child_agr = s.ChildAgr, child_agr_text = s.ChildAgrText, function_key = s.FunctionKey, module_name = s.ModuleName,
            alternate_descriptions = s.AlternateDescriptions,
            tcodes = s.Tcodes.Select(t => new { tcode = t.Code, ttext = t.Text, assignment_sources = t.AssignmentSources.Select(Source).ToList(), alternate_texts = t.AlternateTexts }).ToList(),
        }).ToList();
        detail["relationships"] = role.Relationships.Select(Source).ToList();
        detail["alternate_descriptions"] = role.AlternateDescriptions;
        detail["analysis"] = new { module_source = "CSV FUNCTION_KEY", import_profile_id = "default", import_profile_version = 1, configuration_revision = 0 };
        return detail;
    }
}
