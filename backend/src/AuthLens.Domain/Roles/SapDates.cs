using System.Globalization;
using System.Text.RegularExpressions;

namespace AuthLens.Domain.Roles;

public sealed class DomainValidationException(string message) : Exception(message);

/// <summary>Port of user_access.sap_date / interval_status. Today is always passed explicitly so results are reproducible.</summary>
public static partial class SapDates
{
    [GeneratedRegex(@"^\d{8}$")] private static partial Regex Compact();
    [GeneratedRegex(@"^\d{4}-\d{2}-\d{2}$")] private static partial Regex Iso();

    public static DateOnly? Parse(string? value)
    {
        if (string.IsNullOrEmpty(value) || value is "00000000" or "0000-00-00") return null;
        if (Compact().IsMatch(value) && DateOnly.TryParseExact(value, "yyyyMMdd", CultureInfo.InvariantCulture, DateTimeStyles.None, out var a)) return a;
        if (Iso().IsMatch(value) && DateOnly.TryParseExact(value, "yyyy-MM-dd", CultureInfo.InvariantCulture, DateTimeStyles.None, out var b)) return b;
        throw new DomainValidationException("Invalid SAP date. Use YYYY-MM-DD or YYYYMMDD; no data was applied.");
    }

    public static string? Iso8601(DateOnly? value) => value?.ToString("yyyy-MM-dd", CultureInfo.InvariantCulture);

    public static string IntervalStatus(DateOnly? start, DateOnly? end, DateOnly today)
    {
        if (end is { } e && e < today) return "expired";
        if (start is { } s && s > today) return "future";
        if (start is null || end is null) return "unknown";
        return "active";
    }

    public static string IntervalStatus(string? start, string? end, DateOnly today) => IntervalStatus(Parse(start), Parse(end), today);
}
