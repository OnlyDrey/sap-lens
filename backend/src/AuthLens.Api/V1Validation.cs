using System.Text.Json;
using System.Text.Json.Nodes;

namespace AuthLens.Api;

/// <summary>FastAPI/Pydantic-shaped request validation for the v1 routes: 422 with <c>detail</c> as a list of {type, loc, msg}, which the React client
/// renders as "field: message". StrictModel bodies forbid unknown fields.</summary>
public static class V1Validation
{
    public static async Task<(JsonObject?, IResult?)> ReadBody(HttpContext http, CancellationToken ct)
    {
        try
        {
            var node = await JsonNode.ParseAsync(http.Request.Body, cancellationToken: ct);
            if (node is JsonObject body) return (body, null);
            return (null, Results.Json(new { detail = new[] { new { type = "model_attributes_type", loc = new[] { "body" }, msg = "Input should be a valid dictionary or object to extract fields from" } } }, statusCode: 422));
        }
        catch (JsonException)
        {
            return (null, Results.Json(new { detail = new[] { new { type = "json_invalid", loc = new[] { "body" }, msg = "JSON decode error" } } }, statusCode: 422));
        }
    }

    public static object Error(string type, string field, string message, object[]? path = null) => At(type, message, [.. (object[])["body"], .. path ?? [], field]);

    public static object At(string type, string message, params object[] loc) => new { type, loc, msg = message };

    public static void Extra(JsonObject body, string[] fields, List<object> errors, object[]? path = null)
    {
        foreach (var (key, _) in body) if (!fields.Contains(key)) errors.Add(Error("extra_forbidden", key, "Extra inputs are not permitted", path));
    }

    public static int Length(string value) => value.EnumerateRunes().Count();

    public static string? Text(JsonObject body, string field, int min, int max, bool required, List<object> errors, object[]? path = null)
    {
        if (!body.TryGetPropertyValue(field, out var node)) { if (required) errors.Add(Error("missing", field, "Field required", path)); return required ? null : ""; }
        if (node is not JsonValue value || node.GetValueKind() != JsonValueKind.String) { errors.Add(Error("string_type", field, "Input should be a valid string", path)); return null; }
        var text = value.GetValue<string>();
        if (Length(text) < min) { errors.Add(Error("string_too_short", field, $"String should have at least {min} character{(min == 1 ? "" : "s")}", path)); return null; }
        if (Length(text) > max) { errors.Add(Error("string_too_long", field, $"String should have at most {max} characters", path)); return null; }
        return text;
    }
}
