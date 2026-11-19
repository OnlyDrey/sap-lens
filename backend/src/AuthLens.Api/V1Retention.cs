using System.Text.Json;
using System.Text.Json.Nodes;
using AuthLens.Application.Retention;

namespace AuthLens.Api;

/// <summary>Port of routers/retention.py: status, per-category preview, one-time approval bound to the previewed digest, and the policy. Administrator only
/// (a Server needs an authenticated administrator account, as for backups).</summary>
public static class V1Retention
{
    public static void Map(RouteGroupBuilder api)
    {
        api.MapGet("/retention", (HttpContext http, DataRetention retention) => Guard(http) ?? Json(retention.Status()));

        api.MapGet("/retention/preview", async (HttpContext http, string? category, DataRetention retention, CancellationToken ct) =>
        {
            if (Guard(http) is { } refused) return refused;
            category ??= "source";
            if (!DataRetention.Categories.Contains(category)) return Invalid("query", "category", "literal_error", "Input should be 'source', 'review' or 'backup'");
            return Json(await retention.PreviewAsync(category, ct));
        });

        api.MapPut("/retention/policy", async (HttpContext http, DataRetention retention, CancellationToken ct) =>
        {
            if (Guard(http) is { } refused) return refused;
            var (body, invalid) = await V1Validation.ReadBody(http, ct);
            if (invalid is not null) return invalid;
            if (body!.Select(p => p.Key).FirstOrDefault(k => k is not ("enabled" or "months" or "review_months" or "backup_days")) is { } extra) return Invalid("body", extra, "extra_forbidden", "Extra inputs are not permitted");
            if (body!["enabled"] is not { } e || e.GetValueKind() is not (JsonValueKind.True or JsonValueKind.False)) return Invalid("body", "enabled", "bool_type", "Input should be a valid boolean");
            int? Number(string name, int min, int max, bool required, out IResult? error)
            {
                error = null;
                if (body[name] is null) { if (required) error = Invalid("body", name, "missing", "Field required"); return null; }
                if (body[name] is not JsonValue v || v.GetValueKind() != JsonValueKind.Number || !int.TryParse(v.ToJsonString(), out var n)) { error = Invalid("body", name, "int_type", "Input should be a valid integer"); return null; }
                if (n < min || n > max) { error = Invalid("body", name, n < min ? "greater_than_equal" : "less_than_equal", n < min ? $"Input should be greater than or equal to {min}" : $"Input should be less than or equal to {max}"); return null; }
                return n;
            }
            var months = Number("months", DataRetention.MinMonths, DataRetention.MaxMonths, true, out var problem);
            if (problem is not null) return problem;
            var review = Number("review_months", DataRetention.MinMonths, DataRetention.MaxMonths, false, out problem);
            if (problem is not null) return problem;
            var days = Number("backup_days", DataRetention.MinDays, DataRetention.MaxDays, false, out problem);
            if (problem is not null) return problem;
            return Json(retention.SetPolicy(e.GetValue<bool>(), months!.Value, review, days, Actors.Name(http)));
        });

        api.MapPost("/retention/review/undo", UndoAsync);

        api.MapPost("/retention/approve", async (HttpContext http, DataRetention retention, CancellationToken ct) =>
        {
            if (Guard(http) is { } refused) return refused;
            var (body, invalid) = await V1Validation.ReadBody(http, ct);
            if (invalid is not null) return invalid;
            if (body!.Select(p => p.Key).FirstOrDefault(k => k is not ("confirm" or "category" or "preview_digest")) is { } extra) return Invalid("body", extra, "extra_forbidden", "Extra inputs are not permitted");
            if (body!["confirm"] is not { } c || c.GetValueKind() is not (JsonValueKind.True or JsonValueKind.False)) return Invalid("body", "confirm", "bool_type", "Input should be a valid boolean");
            var category = body["category"] is null ? "source" : body["category"] is JsonValue cv && cv.GetValueKind() == JsonValueKind.String ? cv.GetValue<string>() : "";
            if (!DataRetention.Categories.Contains(category)) return Invalid("body", "category", "literal_error", "Input should be 'source', 'review' or 'backup'");
            var digest = body["preview_digest"] is JsonValue dv && dv.GetValueKind() == JsonValueKind.String ? dv.GetValue<string>() : "";
            if (digest.Length != 64 || !digest.All(ch => ch is >= '0' and <= '9' or >= 'a' and <= 'f')) return Invalid("body", "preview_digest", "string_pattern_mismatch", "String should match pattern '^[a-f0-9]{64}$'");
            if (!c.GetValue<bool>()) return Results.Json(new { detail = "Confirm that the previewed data may be removed." }, statusCode: 422);
            try
            {
                var result = await retention.ApproveAsync(category, digest, Actors.Name(http), ct);
                result["status"] = retention.Status();
                return Json(result);
            }
            catch (RetentionException error) { return Results.Json(new { detail = error.Message }, statusCode: error.Status); }
        });
    }

    /// <summary>POST /api/retention/review/undo: restores review periods removed by a review cleanup. AuthLens never removes review periods (they are
    /// immutable audit evidence), so there is never a cleanup to undo; the request is validated as in v1 and answered 409 without changing anything.</summary>
    private static async Task<IResult> UndoAsync(HttpContext http, CancellationToken ct)
    {
        if (Guard(http) is { } refused) return refused;
        var (body, invalid) = await V1Validation.ReadBody(http, ct);
        if (invalid is not null) return invalid;
        if (body!.Select(p => p.Key).FirstOrDefault(k => k is not ("operation" or "confirm")) is { } extra) return Invalid("body", extra, "extra_forbidden", "Extra inputs are not permitted");
        var operation = body!["operation"] is JsonValue o && o.TryGetValue<string>(out var text) ? text : "";
        if (!AuthLens.Application.Backups.ApplicationBackups.Identity().IsMatch(operation)) return Invalid("body", "operation", "string_pattern_mismatch", "String should match pattern '^[a-f0-9]{32}$'");
        if (body["confirm"] is not { } c || c.GetValueKind() is not (JsonValueKind.True or JsonValueKind.False)) return Invalid("body", "confirm", "bool_type", "Input should be a valid boolean");
        if (!c.GetValue<bool>()) return Results.Json(new { detail = "Confirm that the removed review periods should be restored." }, statusCode: 422);
        return Results.Json(new { detail = "There is no review cleanup to undo: AuthLens keeps completed review periods as immutable audit evidence." }, statusCode: 409);
    }

    private static IResult? Guard(HttpContext http) => V1Backups.Guard(http);

    private static IResult Invalid(string where, string field, string type, string message) =>
        Results.Json(new { detail = new[] { new { type, loc = new[] { where, field }, msg = message } } }, statusCode: 422);

    private static IResult Json(JsonNode value) => Results.Content(value.ToJsonString(), "application/json");
}
