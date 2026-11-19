using System.Text.RegularExpressions;

namespace AuthLens.Domain.Csv;

/// <summary>Port of CPython's csv.Sniffer delimiter detection (_guess_quote_and_delimiter, then _guess_delimiter with the preferred list), restricted
/// to the delimiters AuthLens accepts. Only the delimiter is used, as in csv_import.py. Returns null where Python raises "Could not determine delimiter".</summary>
public static class PythonSniffer
{
    private static readonly char[] Preferred = [',', '\t', ';', ' ', ':'];
    private static readonly Regex[] QuotePatterns =
    [
        new(@"(?<delim>[^\w\n""'])(?<space> ?)(?<quote>[""']).*?\k<quote>\k<delim>", RegexOptions.Singleline | RegexOptions.Multiline),
        new(@"(?:^|\n)(?<quote>[""']).*?\k<quote>(?<delim>[^\w\n""'])(?<space> ?)", RegexOptions.Singleline | RegexOptions.Multiline),
        new(@"(?<delim>[^\w\n""'])(?<space> ?)(?<quote>[""']).*?\k<quote>(?:$|\n)", RegexOptions.Singleline | RegexOptions.Multiline),
        new(@"(?:^|\n)(?<quote>[""']).*?\k<quote>(?:$|\n)", RegexOptions.Singleline | RegexOptions.Multiline),
    ];

    public static char? Sniff(string sample, string delimiters)
    {
        var fromQuotes = GuessQuoteAndDelimiter(sample, delimiters);
        if (!string.IsNullOrEmpty(fromQuotes)) return fromQuotes[0];
        return GuessDelimiter(sample, delimiters);
    }

    private static string? GuessQuoteAndDelimiter(string data, string delimiters)
    {
        MatchCollection? matches = null;
        Regex? used = null;
        foreach (var pattern in QuotePatterns)
        {
            matches = pattern.Matches(data);
            if (matches.Count > 0) { used = pattern; break; }
        }
        if (matches is null || matches.Count == 0 || used is null) return null;
        var hasDelim = used.GetGroupNames().Contains("delim");
        var delims = new List<(string Key, int Count)>();
        foreach (Match m in matches)
        {
            if (!hasDelim) continue;
            var key = m.Groups["delim"].Value;
            if (key.Length > 0 && delimiters.Contains(key, StringComparison.Ordinal))
            {
                var index = delims.FindIndex(d => d.Key == key);
                if (index < 0) delims.Add((key, 1)); else delims[index] = (key, delims[index].Count + 1);
            }
        }
        if (delims.Count == 0) return "";
        var best = delims[0];
        foreach (var d in delims) if (d.Count > best.Count) best = d; // max() keeps the first maximum
        return best.Key == "\n" ? "" : best.Key;
    }

    private static char? GuessDelimiter(string text, string delimiters)
    {
        var data = text.Split('\n').Where(l => l.Length > 0).ToList();
        var chunkLength = Math.Min(10, data.Count);
        var iteration = 0;
        var charFrequency = new Dictionary<char, List<(int Freq, int Count)>>();
        var modes = new Dictionary<char, (int Freq, int Count)>();
        var delims = new Dictionary<char, (int Freq, int Count)>();
        int start = 0, end = chunkLength;
        while (start < data.Count)
        {
            iteration++;
            foreach (var line in data.Skip(start).Take(end - start))
                for (var c = (char)0; c < 127; c++)
                {
                    if (!charFrequency.TryGetValue(c, out var meta)) charFrequency[c] = meta = [];
                    var freq = line.Count(x => x == c);
                    var at = meta.FindIndex(m => m.Freq == freq);
                    if (at < 0) meta.Add((freq, 1)); else meta[at] = (freq, meta[at].Count + 1);
                }
            foreach (var (c, meta) in charFrequency)
            {
                var items = meta.ToList();
                if (items.Count == 1 && items[0].Freq == 0) continue;
                if (items.Count > 1)
                {
                    var mode = items[0];
                    foreach (var item in items) if (item.Count > mode.Count) mode = item;
                    items.Remove(mode);
                    modes[c] = (mode.Freq, mode.Count - items.Sum(i => i.Count));
                }
                else modes[c] = items[0];
            }
            double total = Math.Min(chunkLength * iteration, data.Count);
            var consistency = 1.0;
            const double threshold = 0.9;
            while (delims.Count == 0 && consistency >= threshold)
            {
                foreach (var (k, v) in modes)
                    if (v.Freq > 0 && v.Count > 0 && v.Count / total >= consistency && delimiters.Contains(k)) delims[k] = v;
                consistency -= 0.01;
            }
            if (delims.Count == 1) return delims.Keys.First();
            start = end;
            end += chunkLength;
        }
        if (delims.Count == 0) return null;
        foreach (var d in Preferred) if (delims.ContainsKey(d)) return d;
        return delims.OrderBy(p => p.Value.Freq).ThenBy(p => p.Value.Count).ThenBy(p => p.Key).Last().Key;
    }
}
