using System.Collections;
using System.Globalization;
using System.Security.Cryptography;
using System.Text;

namespace AuthLens.Domain.Json;

/// <summary>Byte-for-byte the text of Python's json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')), so finding
/// identities and evidence versions computed by the .NET port are identical to the Python ones. Supported values: null, bool, integers, strings,
/// lists and string-keyed dictionaries. Keys are ordered by code point (ordinal UTF-16, identical for characters outside the surrogate range).</summary>
public static class CanonicalJson
{
    public static string Serialize(object? value)
    {
        var builder = new StringBuilder();
        Write(builder, value);
        return builder.ToString();
    }

    public static string Sha256(object? value) => Convert.ToHexStringLower(SHA256.HashData(Encoding.UTF8.GetBytes(Serialize(value))));

    private static void Write(StringBuilder b, object? value)
    {
        switch (value)
        {
            case null: b.Append("null"); break;
            case System.Text.Json.Nodes.JsonObject node:
                Write(b, node.ToDictionary(p => p.Key, p => (object?)p.Value, StringComparer.Ordinal));
                break;
            case System.Text.Json.Nodes.JsonArray node:
                Write(b, node.Select(v => (object?)v).ToList());
                break;
            case System.Text.Json.Nodes.JsonValue node:
                switch (node.GetValueKind())
                {
                    case System.Text.Json.JsonValueKind.String: WriteString(b, node.GetValue<string>()); break;
                    case System.Text.Json.JsonValueKind.True: b.Append("true"); break;
                    case System.Text.Json.JsonValueKind.False: b.Append("false"); break;
                    case System.Text.Json.JsonValueKind.Number when node.TryGetValue<int>(out var small): b.Append(small.ToString(CultureInfo.InvariantCulture)); break;
                    case System.Text.Json.JsonValueKind.Number when node.TryGetValue<long>(out var integer): b.Append(integer.ToString(CultureInfo.InvariantCulture)); break;
                    // Python and .NET format non-integral numbers differently; hashed evidence never contains them.
                    default: throw new ArgumentException("Unsupported canonical JSON number.");
                }
                break;
            case bool flag: b.Append(flag ? "true" : "false"); break;
            case string text: WriteString(b, text); break;
            case int or long: b.Append(Convert.ToString(value, CultureInfo.InvariantCulture)); break;
            case IDictionary<string, object?> map:
                b.Append('{');
                var first = true;
                foreach (var key in map.Keys.Order(StringComparer.Ordinal))
                {
                    if (!first) b.Append(',');
                    first = false;
                    WriteString(b, key); b.Append(':'); Write(b, map[key]);
                }
                b.Append('}');
                break;
            case IEnumerable items:
                b.Append('[');
                var firstItem = true;
                foreach (var item in items) { if (!firstItem) b.Append(','); firstItem = false; Write(b, item); }
                b.Append(']');
                break;
            default: throw new ArgumentException($"Unsupported canonical JSON value {value.GetType().Name}.");
        }
    }

    private static void WriteString(StringBuilder b, string text)
    {
        b.Append('"');
        foreach (var c in text)
        {
            switch (c)
            {
                case '"': b.Append("\\\""); break;
                case '\\': b.Append("\\\\"); break;
                case '\n': b.Append("\\n"); break;
                case '\r': b.Append("\\r"); break;
                case '\t': b.Append("\\t"); break;
                case '\b': b.Append("\\b"); break;
                case '\f': b.Append("\\f"); break;
                default:
                    if (c < 0x20) b.Append("\\u").Append(((int)c).ToString("x4", CultureInfo.InvariantCulture));
                    else b.Append(c);
                    break;
            }
        }
        b.Append('"');
    }

    /// <summary>Port of sod_analysis._unique: distinct items ordered by their canonical text.</summary>
    public static List<T> Unique<T>(IEnumerable<T> items)
    {
        var map = new SortedDictionary<string, T>(StringComparer.Ordinal);
        foreach (var item in items) map[Serialize(item)] = item;
        return [.. map.Values];
    }
}
