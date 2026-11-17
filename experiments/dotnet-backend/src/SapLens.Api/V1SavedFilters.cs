using System.Globalization;
using System.Numerics;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using Microsoft.EntityFrameworkCore;
using SapLens.Persistence;

namespace SapLens.Api;

/// <summary>Port of routers/saved_filters.py and saved_filters.py: bounded saved investigations with optimistic concurrency on the
/// <c>modified</c> stamp. Stored in SQLite instead of saved-filters.json, with the same limits (250 entries, 1 MB serialized, 16 000 characters per
/// definition), the same per-view field allow-lists, the same error codes and messages, and the v1 list order (a saved entry moves to the end).</summary>
public static class V1SavedFilters
{
    public const int MaxItems = 250, MaxBytes = 1_000_000;

    public static readonly string[] Views = ["users", "roles", "release", "review", "comparison", "sod_users", "sod_roles", "sod_risk_matrix", "sod_activity_matrix", "sod_explorer", "sod_queue"];

    public static readonly IReadOnlyDictionary<string, HashSet<string>> Allowed = BuildAllowed();

    private static Dictionary<string, HashSet<string>> BuildAllowed()
    {
        var allowed = new Dictionary<string, HashSet<string>>
        {
            ["users"] = ["search", "group", "groups", "roles", "sort", "descending", "role", "tcodes", "transactionMode", "transactionExclude", "excludeTcodes", "excludeMode", "missingRoles", "missingMode", "expired", "assignmentBand", "usernames"],
            ["roles"] = ["search", "activeModules", "transactionMode", "transactionExclude", "transactionOperator", "tcodes", "notTcodes", "excludeTcodes", "excludeMode", "sortBy"],
            ["release"] = ["group", "userGroups", "kind", "releaseGroup", "releaseAreas", "releaseGroups", "strategy", "strategies", "username", "role", "status", "sort", "descending", "valid_from_min", "valid_from_max", "valid_to_min", "valid_to_max", "include_missing_end"],
            ["review"] = ["search", "finding", "license", "state", "findings", "licenses", "states", "sort", "descending"],
            ["comparison"] = ["validity", "kind", "difference", "search", "area", "areas", "sort", "descending"],
        };
        foreach (var view in new[] { "sod_users", "sod_roles" })
            allowed[view] = ["search", "usernames", "risks", "criticalities", "categories", "groups", "tcodes", "risk", "criticality", "risk_type", "category", "username", "group", "composite_role", "single_role", "tcode", "account_status", "sort", "descending", "validity", "as_of", "selected_roles"];
        string[] matrix = ["search", "risk", "criticality", "risk_type", "category", "username", "usernames", "role_suffixes", "risks", "activities", "groups", "roles", "tcodes", "categories", "criticalities", "group", "composite_role", "single_role", "tcode", "role", "role_suffix", "activity", "account_status", "multiple_risks", "tracking",
            "activity_decision", "assignment_decision", "review_status", "acceptance", "validity", "as_of", "sort", "descending", "group_by", "table", "kind", "status", "queue_sort", "role_match", "assignment_scope", "role_families", "role_exact"];
        foreach (var view in new[] { "sod_risk_matrix", "sod_activity_matrix", "sod_explorer", "sod_queue" }) allowed[view] = [.. matrix];
        // Organizational filters: Functional Group and Manager (Account Review keeps its own `groups` key).
        foreach (var view in new[] { "users", "review", "sod_users", "sod_roles", "sod_risk_matrix", "sod_activity_matrix", "sod_explorer", "sod_queue" })
        {
            allowed[view].UnionWith(["functional_groups", "managers", "functional_group", "manager"]);
            if (view == "review") allowed[view].UnionWith(["groups", "includeCompleted"]);
        }
        return allowed;
    }

    private sealed class Refusal(int status, string detail) : Exception(detail) { public int Status { get; } = status; }

    public sealed record Request(string Name, string View, JsonObject Filters, string Id, string Expected, bool Rename);

    public static void Map(RouteGroupBuilder api)
    {
        api.MapGet("/saved-filters", async (IDbContextFactory<SapLensDb> factory, CancellationToken ct) =>
        {
            await using var db = await factory.CreateDbContextAsync(ct);
            var rows = await db.SavedFilters.AsNoTracking().OrderBy(f => f.Sequence).ToListAsync(ct);
            return Json(new JsonObject { ["items"] = new JsonArray([.. rows.Select(Item)]) });
        });

        api.MapPost("/saved-filters", async (HttpContext http, WriteCoordinator writer, HostSettings host, TimeProvider clock, CancellationToken ct) =>
        {
            var (body, invalid) = await V1Validation.ReadBody(http, ct);
            if (invalid is not null) return invalid;
            var (request, errors) = ParseSave(body!);
            if (errors.Count > 0) return Results.Json(new { detail = errors }, statusCode: 422);
            if (!request!.Rename && request.Filters.Select(p => p.Key).Any(k => !Allowed[request.View].Contains(k)))
                return Results.Json(new { detail = "Unsupported filter fields; result datasets cannot be saved." }, statusCode: 422);
            try
            {
                var saved = await writer.WriteAsync((db, token) => SaveAsync(db, request, Actors.Name(http), Stamp(clock), token), ct);
                return Json(saved);
            }
            catch (Refusal refusal) { return Results.Json(new { detail = refusal.Message }, statusCode: refusal.Status); }
        });

        api.MapPost("/saved-filters/delete", async (HttpContext http, WriteCoordinator writer, CancellationToken ct) =>
        {
            var (body, invalid) = await V1Validation.ReadBody(http, ct);
            if (invalid is not null) return invalid;
            var errors = new List<object>();
            V1Validation.Extra(body!, ["id", "expected"], errors);
            var id = V1Validation.Text(body!, "id", 1, 64, true, errors);
            var expected = V1Validation.Text(body!, "expected", 1, 64, true, errors);
            if (errors.Count > 0) return Results.Json(new { detail = errors }, statusCode: 422);
            try
            {
                await writer.WriteAsync(async (db, token) =>
                {
                    var item = await db.SavedFilters.FirstOrDefaultAsync(f => f.Id == id, token) ?? throw new Refusal(404, "Saved filter no longer exists.");
                    if (item.Modified != expected) throw new Refusal(409, "Saved filter changed. Reload before deleting.");
                    db.SavedFilters.Remove(item);
                    return true;
                }, ct);
                return Results.Ok(new { status = "deleted" });
            }
            catch (Refusal refusal) { return Results.Json(new { detail = refusal.Message }, statusCode: refusal.Status); }
        });
    }

    private static async Task<JsonObject> SaveAsync(SapLensDb db, Request request, string actor, string stamp, CancellationToken ct)
    {
        var items = await db.SavedFilters.OrderBy(f => f.Sequence).ToListAsync(ct);
        var previous = items.FirstOrDefault(i => i.Id == request.Id);
        if (request.Id.Length > 0 && previous is null) throw new Refusal(404, "Saved filter no longer exists.");
        if (previous is not null && previous.Modified != request.Expected) throw new Refusal(409, "Saved filter changed. Reload before updating.");
        if (previous is not null && previous.View != request.View) throw new Refusal(422, "Cannot move a saved filter to another view.");
        var key = Fold(request.Name);
        if (items.Any(i => i.View == request.View && i.NameKey == key && i.Id != request.Id)) throw new Refusal(409, "A filter with this name already exists in this view.");
        if (previous is null && items.Count >= MaxItems) throw new Refusal(422, $"The {MaxItems} saved-filter limit has been reached.");
        if (request.Rename && previous is null) throw new Refusal(422, "Select an existing filter to rename.");
        var entry = previous ?? new SavedFilter
        {
            Id = request.Id.Length > 0 ? request.Id : Guid.NewGuid().ToString("N"), Name = "", NameKey = "", View = request.View, FiltersJson = "{}", Created = stamp, Modified = stamp, CreatedBy = actor,
        };
        (entry.Name, entry.NameKey, entry.Modified, entry.ModifiedBy) = (request.Name, key, stamp, actor);
        if (!request.Rename) (entry.FiltersJson, entry.FilterSchema) = (request.Filters.ToJsonString(), 1);
        entry.Sequence = (items.Count == 0 ? 0 : items.Max(i => i.Sequence)) + 1;
        // v1 refuses a save whose whole serialized store would exceed 1 MB; the previous state is kept.
        var document = new JsonObject { ["schema_version"] = 1, ["items"] = new JsonArray([.. items.Where(i => i.Id != entry.Id).Append(entry).Select(Item)]) };
        if (Encoding.UTF8.GetByteCount(PyJson(document, ensureAscii: false)) > MaxBytes) throw new Refusal(422, "Saved filters exceed the local storage limit.");
        if (previous is null) db.SavedFilters.Add(entry);
        return Item(entry);
    }

    private static JsonObject Item(SavedFilter f) => new()
    {
        ["id"] = f.Id, ["name"] = f.Name, ["view"] = f.View, ["filters"] = JsonNode.Parse(f.FiltersJson), ["filter_schema"] = f.FilterSchema, ["created"] = f.Created, ["modified"] = f.Modified,
    };

    private static IResult Json(JsonNode node) => Results.Content(node.ToJsonString(), "application/json");

    /// <summary>Python str.casefold() for the names people type; ToUpperInvariant then ToLowerInvariant also folds ß/ẞ and final sigma forms.</summary>
    public static string Fold(string value) => SapLens.Domain.Text.PythonText.Casefold(value);

    /// <summary>datetime.now(timezone.utc).isoformat(): microseconds, omitted when zero, and a +00:00 offset.</summary>
    private static string Stamp(TimeProvider clock)
    {
        var now = clock.GetUtcNow().UtcDateTime;
        var micro = now.Ticks % TimeSpan.TicksPerSecond / 10;
        return now.ToString("yyyy-MM-dd'T'HH:mm:ss", CultureInfo.InvariantCulture) + (micro == 0 ? "" : "." + micro.ToString("D6", CultureInfo.InvariantCulture)) + "+00:00";
    }

    public static (Request?, List<object>) ParseSave(JsonObject body)
    {
        var errors = new List<object>();
        V1Validation.Extra(body, ["name", "view", "filters", "id", "expected", "rename"], errors);
        var name = V1Validation.Text(body, "name", 1, 80, true, errors);
        if (name is not null)
        {
            name = name.Trim();
            if (name.Length == 0 || name.Any(c => c < 32)) { errors.Add(V1Validation.Error("value_error", "name", "Value error, Use a nonempty readable name.")); name = null; }
        }
        string? view = null;
        if (!body.TryGetPropertyValue("view", out var viewNode)) errors.Add(V1Validation.Error("missing", "view", "Field required"));
        else if (viewNode?.GetValueKind() == JsonValueKind.String && Views.Contains(viewNode.GetValue<string>())) view = viewNode.GetValue<string>();
        else errors.Add(V1Validation.Error("literal_error", "view", "Input should be " + string.Join(", ", Views[..^1].Select(v => $"'{v}'")) + $" or '{Views[^1]}'"));
        JsonObject? filters = null;
        if (!body.TryGetPropertyValue("filters", out var filtersNode)) errors.Add(V1Validation.Error("missing", "filters", "Field required"));
        else if (filtersNode is not JsonObject candidate) errors.Add(V1Validation.Error("dict_type", "filters", "Input should be a valid dictionary"));
        else if (candidate.Count > 40) errors.Add(V1Validation.Error("too_long", "filters", $"Dictionary should have at most 40 items after validation, not {candidate.Count}"));
        else if (FilterError(candidate) is { } message) errors.Add(V1Validation.Error("value_error", "filters", "Value error, " + message));
        else filters = candidate;
        var id = V1Validation.Text(body, "id", 0, 64, false, errors);
        var expected = V1Validation.Text(body, "expected", 0, 64, false, errors);
        var rename = false;
        if (body.TryGetPropertyValue("rename", out var renameNode))
        {
            if (renameNode?.GetValueKind() is JsonValueKind.True or JsonValueKind.False) rename = renameNode.GetValue<bool>();
            else if (renameNode?.GetValueKind() == JsonValueKind.Number && renameNode.ToJsonString() is "0" or "1") rename = renameNode.ToJsonString() == "1";
            else errors.Add(V1Validation.Error("bool_type", "rename", "Input should be a valid boolean"));
        }
        return errors.Count > 0 ? (null, errors) : (new Request(name!, view!, filters!, id!, expected!, rename), errors);
    }

    /// <summary>filters_valid: bounded scalars (string, bool, integer) or lists of at most 100 strings of at most 512 characters.</summary>
    private static string? FilterError(JsonObject filters)
    {
        if (PyJson(filters, ensureAscii: true).Length > 16000) return "Filter definition is too large.";
        foreach (var (key, value) in filters)
        {
            var kind = value?.GetValueKind();
            var scalar = kind is JsonValueKind.String or JsonValueKind.True or JsonValueKind.False || kind == JsonValueKind.Number && IsInteger(value!);
            var list = value is JsonArray items && items.Count <= 100 && items.All(x => x?.GetValueKind() == JsonValueKind.String && V1Validation.Length(x.GetValue<string>()) <= 512);
            if (V1Validation.Length(key) > 64 || !(scalar || list)) return "Only bounded scalar filters or string lists are supported.";
            if (kind == JsonValueKind.String && V1Validation.Length(value!.GetValue<string>()) > (key == "usernames" ? 12000 : 512)) return "Filter text is too long.";
        }
        return null;
    }

    private static bool IsInteger(JsonNode number) => number.ToJsonString().IndexOfAny(['.', 'e', 'E']) < 0;

    /// <summary>The length-relevant part of Python json.dumps: ", " and ": " separators, ASCII escaping when ensure_ascii, Python's integer text.</summary>
    public static string PyJson(JsonNode? node, bool ensureAscii)
    {
        var builder = new StringBuilder();
        void Write(JsonNode? n)
        {
            switch (n)
            {
                case null: builder.Append("null"); break;
                case JsonObject o:
                    builder.Append('{');
                    var first = true;
                    foreach (var (k, v) in o) { if (!first) builder.Append(", "); first = false; String(k); builder.Append(": "); Write(v); }
                    builder.Append('}');
                    break;
                case JsonArray a:
                    builder.Append('[');
                    for (var i = 0; i < a.Count; i++) { if (i > 0) builder.Append(", "); Write(a[i]); }
                    builder.Append(']');
                    break;
                default:
                    switch (n.GetValueKind())
                    {
                        case JsonValueKind.String: String(n.GetValue<string>()); break;
                        case JsonValueKind.True: builder.Append("true"); break;
                        case JsonValueKind.False: builder.Append("false"); break;
                        case JsonValueKind.Number:
                            var raw = n.ToJsonString();
                            builder.Append(IsInteger(n) && BigInteger.TryParse(raw, NumberStyles.AllowLeadingSign, CultureInfo.InvariantCulture, out var big) ? big.ToString(CultureInfo.InvariantCulture) : raw);
                            break;
                        default: builder.Append(n.ToJsonString()); break;
                    }
                    break;
            }
        }
        void String(string s)
        {
            builder.Append('"');
            foreach (var c in s)
            {
                switch (c)
                {
                    case '"': builder.Append("\\\""); break;
                    case '\\': builder.Append("\\\\"); break;
                    case '\n': builder.Append("\\n"); break;
                    case '\r': builder.Append("\\r"); break;
                    case '\t': builder.Append("\\t"); break;
                    case '\b': builder.Append("\\b"); break;
                    case '\f': builder.Append("\\f"); break;
                    default:
                        if (c < 0x20 || ensureAscii && c > 0x7e) builder.Append("\\u").Append(((int)c).ToString("x4", CultureInfo.InvariantCulture));
                        else builder.Append(c);
                        break;
                }
            }
            builder.Append('"');
        }
        Write(node);
        return builder.ToString();
    }
}
