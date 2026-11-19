using System.Text.RegularExpressions;

namespace AuthLens.Domain.Text;

/// <summary>Port of search_matching.py: literal, case-insensitive search with anchored SAP '*' patterns. No regex or glob classes.</summary>
public static class TextMatching
{
    public static bool TextMatches(string? value, string? query)
    {
        var text = (value ?? "").PyLower();
        var pattern = (query ?? "").Trim().PyLower();
        if (!pattern.Contains('*')) return text.Contains(pattern, StringComparison.Ordinal);
        var parts = pattern.Split('*');
        if (!text.StartsWith(parts[0], StringComparison.Ordinal)) return false;
        var position = parts[0].Length;
        for (var i = 1; i < parts.Length - 1; i++)
        {
            var found = text.IndexOf(parts[i], position, StringComparison.Ordinal);
            if (found < 0) return false;
            position = found + parts[i].Length;
        }
        var last = parts[^1];
        return text.EndsWith(last, StringComparison.Ordinal) && text.Length - last.Length >= position;
    }

    /// <summary>Pattern: any field matches. Plain text: contains over the space-joined fields.</summary>
    public static bool SearchFields(string query, params string?[] fields) =>
        query.Contains('*') ? fields.Any(f => TextMatches(f, query)) : TextMatches(string.Join(' ', fields.Select(f => f ?? "")), query);

    public static IReadOnlyList<string> SearchTerms(string? query) =>
        Regex.Split(query ?? "", "[,;\n]").Select(p => p.Trim()).Where(p => p.Length > 0).ToList();
}
