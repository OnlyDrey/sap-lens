using System.Globalization;
using System.Text.RegularExpressions;

namespace AuthLens.Domain.Scheduling;

/// <summary>A parsed five-field cron rule. Day-of-week 0 is Sunday (7 is accepted as Sunday).</summary>
public sealed record CronRule(IReadOnlySet<int> Minute, IReadOnlySet<int> Hour, IReadOnlySet<int> DayOfMonth, IReadOnlySet<int> Month, IReadOnlySet<int> DayOfWeek,
    bool DayOfMonthAny, bool DayOfWeekAny);

/// <summary>Port of cron_schedule.py: a daily time or a five-field cron expression, evaluated in a chosen time zone ("local", "UTC" or an IANA name).
/// Spring-forward gaps are skipped and a repeated hour runs once (its first occurrence). Errors are <see cref="ArgumentException"/> with v1's messages.</summary>
public static partial class CronSchedule
{
    public static readonly TimeSpan MinInterval = TimeSpan.FromMinutes(5);
    private const int HorizonDays = 366 * 5;
    private static readonly (string Label, int Low, int High)[] Fields = [("minute", 0, 59), ("hour", 0, 23), ("day of month", 1, 31), ("month", 1, 12), ("day of week", 0, 6)];
    private static readonly string[] MonthAbbreviations = "JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC".Split(' ');
    private static readonly string[] DayAbbreviations = "SUN MON TUE WED THU FRI SAT".Split(' ');
    private static readonly string[] MonthNames = "January February March April May June July August September October November December".Split(' ');
    private static readonly string[] DayNames = "Sunday Monday Tuesday Wednesday Thursday Friday Saturday".Split(' ');

    [GeneratedRegex("^([01][0-9]|2[0-3]):([0-5][0-9])$")]
    private static partial Regex DailyTime();

    /// <summary>The zone for "local", "UTC" or an IANA name (TimeZoneInfo.Local, Utc, the platform database).</summary>
    public static TimeZoneInfo Zone(string name, TimeZoneInfo? localZone = null)
    {
        if (name == "local") return localZone ?? TimeZoneInfo.Local;
        if (name == "UTC") return TimeZoneInfo.Utc;
        try { return TimeZoneInfo.FindSystemTimeZoneById(name); }
        catch (Exception error) when (error is TimeZoneNotFoundException or InvalidTimeZoneException or ArgumentException)
        { throw new ArgumentException($"Time zone '{name}' is not available on this system. Choose Local time, UTC, or an installed IANA zone such as Europe/Oslo."); }
    }

    private static int Number(string token, int low, int high, string[]? names, string label, bool dow)
    {
        token = token.ToUpperInvariant();
        int? value = names is not null && Array.IndexOf(names, token) is >= 0 and var index ? index + (names == MonthAbbreviations ? 1 : 0)
            : token.Length > 0 && token.All(char.IsAsciiDigit) && int.TryParse(token, NumberStyles.None, CultureInfo.InvariantCulture, out var parsed) ? parsed : null;
        if (value is null) throw new ArgumentException($"Invalid {label} value '{token}'.");
        if (dow && value == 7) value = 0;
        if (value < low || value > high) throw new ArgumentException($"The {label} must be between {low} and {high}.");
        return value.Value;
    }

    private static HashSet<int> Field(string text, int index)
    {
        var (label, low, high) = Fields[index];
        var names = index == 3 ? MonthAbbreviations : index == 4 ? DayAbbreviations : null;
        var top = high + (index == 4 ? 1 : 0);
        var values = new HashSet<int>();
        if (text.Length == 0) throw new ArgumentException($"The {label} field is empty.");
        foreach (var piece in text.Split(','))
        {
            var part = piece;
            var step = 1;
            var slash = part.IndexOf('/');
            if (slash >= 0)
            {
                var raw = part[(slash + 1)..];
                part = part[..slash];
                if (raw.Length == 0 || !raw.All(char.IsAsciiDigit) || !int.TryParse(raw, NumberStyles.None, CultureInfo.InvariantCulture, out step) || step < 1)
                    throw new ArgumentException($"Invalid step in the {label} field.");
            }
            int start, end;
            if (part == "*") (start, end) = (low, high);
            else if (part.IndexOf('-') is var dash and >= 0)
            {
                start = Number(part[..dash], low, top, names, label, index == 4);
                end = Number(part[(dash + 1)..], low, top, names, label, index == 4);
                if (start > end) throw new ArgumentException($"The range in the {label} field is reversed.");
            }
            else
            {
                start = Number(part, low, top, names, label, index == 4);
                end = step > 1 ? high : start;
            }
            for (var value = start; value <= end; value += step) values.Add(value);
        }
        return values;
    }

    public static CronRule Parse(string expression)
    {
        var parts = expression.Split((char[]?)null, StringSplitOptions.RemoveEmptyEntries);
        if (parts.Length != 5) throw new ArgumentException("A cron expression has five fields: minute hour day-of-month month day-of-week.");
        var sets = parts.Select(Field).ToArray();
        return new CronRule(sets[0], sets[1], sets[2], sets[3], sets[4], parts[2] == "*", parts[4] == "*");
    }

    public static string DailyCron(string? time)
    {
        var match = DailyTime().Match(time ?? "");
        if (!match.Success) throw new ArgumentException("Enter the daily time as HH:MM (24-hour).");
        return $"{int.Parse(match.Groups[2].Value, CultureInfo.InvariantCulture)} {int.Parse(match.Groups[1].Value, CultureInfo.InvariantCulture)} * * *";
    }

    private static bool DayMatches(CronRule rule, DateOnly day)
    {
        var dow = (int)day.DayOfWeek;   // Sunday = 0, as cron
        bool inDom = rule.DayOfMonth.Contains(day.Day), inDow = rule.DayOfWeek.Contains(dow);
        if (rule.DayOfMonthAny && rule.DayOfWeekAny) return true;
        if (rule.DayOfMonthAny) return inDow;
        if (rule.DayOfWeekAny) return inDom;
        return inDom || inDow;   // standard cron: either restriction may match
    }

    /// <summary>Wall-clock time to UTC: a nonexistent time (spring-forward gap) has none; a repeated time takes its first occurrence (Python fold=0).</summary>
    private static DateTimeOffset? ToUtc(DateTime local, TimeZoneInfo zone)
    {
        if (zone.IsInvalidTime(local)) return null;
        var offset = zone.IsAmbiguousTime(local) ? zone.GetAmbiguousTimeOffsets(local).Max() : zone.GetUtcOffset(local);
        return new DateTimeOffset(DateTime.SpecifyKind(local, DateTimeKind.Unspecified), offset).ToUniversalTime();
    }

    /// <summary>The next <paramref name="count"/> UTC run times strictly after <paramref name="after"/>.</summary>
    public static List<DateTimeOffset> NextRuns(string expression, string zoneName, DateTimeOffset after, int count = 1, TimeZoneInfo? localZone = null)
    {
        var rule = Parse(expression);
        var zone = Zone(zoneName, localZone);
        var local = TimeZoneInfo.ConvertTime(after, zone).DateTime;
        local = new DateTime(local.Year, local.Month, local.Day, local.Hour, local.Minute, 0);
        var day = DateOnly.FromDateTime(local);
        var found = new List<DateTimeOffset>();
        var hours = rule.Hour.Order().ToArray();
        var minutes = rule.Minute.Order().ToArray();
        for (var i = 0; i < HorizonDays; i++, day = day.AddDays(1))
        {
            if (!rule.Month.Contains(day.Month) || !DayMatches(rule, day)) continue;
            foreach (var hour in hours)
                foreach (var minute in minutes)
                {
                    var candidate = new DateTime(day.Year, day.Month, day.Day, hour, minute, 0);
                    if (i == 0 && candidate <= local) continue;
                    if (ToUtc(candidate, zone) is not { } utc || utc <= after) continue;
                    found.Add(utc);
                    if (found.Count == count) return found;
                }
        }
        return found;
    }

    /// <summary>Validation: parse, time zone and the minimum interval. The next five runs.</summary>
    public static List<DateTimeOffset> Check(string expression, string zoneName, DateTimeOffset now, TimeZoneInfo? localZone = null)
    {
        var runs = NextRuns(expression, zoneName, now, 6, localZone);
        if (runs.Count == 0) throw new ArgumentException("The expression never runs within the next five years.");
        if (runs.Zip(runs.Skip(1)).Any(pair => pair.Second - pair.First < MinInterval)) throw new ArgumentException("Refreshes must be at least 5 minutes apart.");
        return runs.Take(5).ToList();
    }

    private static string List(IEnumerable<int> values, string[]? names = null, int offset = 0) =>
        string.Join(", ", values.Order().Select(v => names is not null ? names[v - offset] : v.ToString(CultureInfo.InvariantCulture)));

    /// <summary>A readable sentence, for example "At 06:30 every day (Europe/Oslo)".</summary>
    public static string Describe(string expression, string zoneName)
    {
        var rule = Parse(expression);
        var parts = expression.Split((char[]?)null, StringSplitOptions.RemoveEmptyEntries);
        var zoneText = zoneName switch { "local" => "local time", "UTC" => "UTC", _ => zoneName };
        var minutes = rule.Minute.Order().ToArray();
        var hours = rule.Hour.Order().ToArray();
        string when;
        if (minutes.Length == 1 && hours.Length == 1) when = $"At {hours[0]:00}:{minutes[0]:00}";
        else if (parts[1] == "*" && parts[0].StartsWith("*/", StringComparison.Ordinal)) when = $"Every {parts[0][2..]} minutes";
        else if (parts[1] == "*" && minutes.Length == 1) when = $"Every hour at minute {minutes[0]}";
        else if (parts[1].StartsWith("*/", StringComparison.Ordinal) && minutes.Length == 1) when = $"Every {parts[1][2..]} hours at minute {minutes[0]}";
        else if (minutes.Length == 1) when = $"At minute {minutes[0]} past hour {List(hours)}";
        else when = $"At minutes {List(minutes)} past hour {(hours.Length < 24 ? List(hours) : "every hour")}";
        var scope = new List<string>();
        if (!rule.DayOfMonthAny) scope.Add($"on day {List(rule.DayOfMonth)} of the month");
        if (!rule.DayOfWeekAny)
        {
            var weekdays = rule.DayOfWeek.Order().ToArray();
            scope.Add(weekdays.SequenceEqual([1, 2, 3, 4, 5]) ? "on weekdays" : weekdays.SequenceEqual([0, 6]) ? "on weekends" : "on " + List(weekdays, DayNames));
        }
        if (parts[3] != "*") scope.Add("in " + List(rule.Month, MonthNames, 1));
        return $"{when} {(scope.Count > 0 ? string.Join(' ', scope) : "every day")} ({zoneText})";
    }
}
