using System.Text;

namespace AuthLens.Domain.Csv;

public sealed record CsvProfile(string Id = "default", int Version = 1, string Delimiter = "auto", string Encoding = "auto", IReadOnlyDictionary<string, string>? Mapping = null)
{
    public IReadOnlyDictionary<string, string> Columns => Mapping ?? new Dictionary<string, string>();
}

public sealed record CsvSpec(IReadOnlyList<string> Fields, string Required, IReadOnlyList<string> IdentifierFields, IReadOnlySet<string> LenientFields)
{
    public static readonly CsvSpec Roles = new(["FUNCTION_KEY", "AGR_NAME", "TEXT", "CHILD_AGR", "CHILD_AGR_TEXT", "PARENT_AGR", "Effective_Role", "TCODE", "TTEXT"],
        "AGR_NAME", ["AGR_NAME", "CHILD_AGR", "PARENT_AGR", "Effective_Role"], new HashSet<string>());
    public static readonly CsvSpec Users = new(["USERNAME", "ROLE_NAME", "USER_GROUP", "FIRST_NAME", "LAST_NAME", "EMAIL", "USER_VALID_FROM", "USER_VALID_TO",
        "ROLE_VALID_FROM", "ROLE_VALID_TO", "USER_LOCKED", "USER_TYPE"], "USERNAME", ["USERNAME", "ROLE_NAME", "USER_GROUP"], new HashSet<string>());
    public static readonly string[] SodHeaders = ["RISK", "CRITICITY", "TYPE", "TEXT", "ACTVT1", "ACTVT2", "ACTIVITY_SLOT", "ACTIVITY", "TCODE", "TTEXT"];
    public static readonly string[] SodOptional = ["RISK_NAME", "RISK_DESCRIPTION", "RISK_IMPACT", "BUSINESS_PROCESS", "ACTIVITY_NAME", "ACTIVITY_DESCRIPTION",
        "ACTIVITY_TYPE", "ACTIVITY_BUSINESS_PROCESS", "RULESET_ID", "RULESET_VERSION", "SOURCE_SYSTEM", "LANGUAGE", "LAST_CHANGED"];
    public static readonly CsvSpec Sod = new([.. SodHeaders, .. SodOptional], "RISK", ["RISK", "ACTVT1", "ACTVT2", "ACTIVITY", "TCODE"], new HashSet<string>(SodOptional));
}

public sealed class ImportReport
{
    public string FileName { get; init; } = "";
    public string ImportProfile { get; init; } = "default";
    public int ImportVersion { get; init; } = 1;
    public List<string> DetectedColumns { get; set; } = [];
    public Dictionary<string, string?> ResolvedMapping { get; set; } = new();
    public int ParsedRows { get; set; }
    public int UniqueRecords { get; set; }
    public int DuplicateRows { get; set; }
    public int BlankRows { get; set; }
    public List<string> Warnings { get; set; } = [];
    public string Encoding { get; set; } = "";
    public string Delimiter { get; set; } = "";
    /// <summary>The first five unique mapped records (v1 `samples`), for previews only; never stored with a dataset.</summary>
    [System.Text.Json.Serialization.JsonIgnore]
    public List<Dictionary<string, string>> Samples { get; } = [];
}

/// <summary>csv_import.CsvImport.inspect_header: the header row, the format actually used and the mapping the profile would get automatically.</summary>
public sealed record HeaderInspection(IReadOnlyList<string> DetectedColumns, string Delimiter, string Encoding, IReadOnlyDictionary<string, string> ProposedMapping,
    IReadOnlyList<string> Issues);

/// <summary>Port of csv_import.CsvImport: streaming mapped import with the same limits, validation messages, deduplication and the
/// "file changed while being read" guard. Rows are yielded lazily; nothing is applied by this class.</summary>
public sealed class CsvImport
{
    public const long MaxBytes = 128L * 1024 * 1024;
    public const int MaxRows = 1_000_000;
    private readonly string _path;
    private readonly CsvProfile _profile;
    private readonly CsvSpec _spec;
    public ImportReport Report { get; }

    static CsvImport() => System.Text.Encoding.RegisterProvider(CodePagesEncodingProvider.Instance);

    public CsvImport(string path, CsvProfile profile, CsvSpec spec)
    {
        if (!Path.IsPathFullyQualified(path) || !path.EndsWith(".csv", StringComparison.OrdinalIgnoreCase) || path.Contains("://", StringComparison.Ordinal))
            throw new Roles.DomainValidationException("Choose an absolute filesystem CSV path.");
        (_path, _profile, _spec) = (path, profile, spec);
        Report = new ImportReport { FileName = Path.GetFileName(path), ImportProfile = profile.Id, ImportVersion = profile.Version };
    }

    public static string NormalizedHeader(string value) => new(value.PyLower().Where(char.IsLetterOrDigit).ToArray());

    /// <summary>Port of inspect_header: reads only the first 64 KiB, never the records. Duplicate or empty headers and an undetected required field are
    /// reported as issues (not errors), so the user can fix the mapping before importing.</summary>
    public HeaderInspection InspectHeader()
    {
        var info = new FileInfo(_path);
        if (!info.Exists) throw new FileNotFoundException("CSV file not found.");
        if (info.Length > MaxBytes) throw new Roles.DomainValidationException("CSV exceeds its size limit.");
        var encoding = ResolveEncoding();
        string sample;
        using (var reader = new StreamReader(_path, encoding, detectEncodingFromByteOrderMarks: true))
        {
            var buffer = new char[65536];
            sample = new string(buffer, 0, reader.ReadBlock(buffer, 0, buffer.Length));
        }
        var delimiter = _profile.Delimiter == "auto" ? PythonSniffer.Sniff(sample, ",;\t|") ?? ',' : _profile.Delimiter[0];
        using var text = new StringReader(sample);
        using var rows = CsvReader.Read(text, delimiter).GetEnumerator();
        var headers = rows.MoveNext() ? rows.Current : [];
        var keys = headers.Select(NormalizedHeader).ToList();
        var issues = new List<string>();
        if (keys.Distinct().Count() != keys.Count || headers.Any(h => h.Trim().Length == 0))
            issues.Add("Duplicate, ambiguous or empty headers must be corrected before importing.");
        var proposed = new Dictionary<string, string>(StringComparer.Ordinal);
        foreach (var field in _spec.Fields)
            if (keys.Count(k => k == NormalizedHeader(field)) == 1) proposed[field] = headers[keys.IndexOf(NormalizedHeader(field))];
        if (!proposed.ContainsKey(_spec.Required) && !(_profile.Columns.TryGetValue(_spec.Required, out var manual) && headers.Contains(manual)))
            issues.Add($"Required {_spec.Required} was not detected. Choose its column manually.");
        return new HeaderInspection(headers, delimiter.ToString(), Report.Encoding, proposed, issues);
    }

    private Encoding ResolveEncoding()
    {
        var name = _profile.Encoding;
        using var stream = File.OpenRead(_path);
        var sample = new byte[65536];
        var read = stream.ReadAtLeast(sample, sample.Length, throwOnEndOfStream: false);
        if (name == "auto")
        {
            if (read >= 2 && ((sample[0] == 0xFF && sample[1] == 0xFE) || (sample[0] == 0xFE && sample[1] == 0xFF))) name = "utf-16";
            else
            {
                try { new UTF8Encoding(false, true).GetDecoder().GetCharCount(sample, 0, read, flush: false); name = "utf-8-sig"; }
                catch (DecoderFallbackException) { name = "cp1252"; }
            }
        }
        Report.Encoding = name;
        return name switch
        {
            "utf-16" => read >= 2 && sample[0] == 0xFE ? new UnicodeEncoding(true, true, true) : new UnicodeEncoding(false, true, true),
            "cp1252" => System.Text.Encoding.GetEncoding(1252),
            _ => new UTF8Encoding(false, true),
        };
    }

    public IEnumerable<Dictionary<string, string>> Records(CancellationToken cancellation = default)
    {
        var initial = new FileInfo(_path);
        if (!initial.Exists) throw new FileNotFoundException("CSV file not found.");
        if (initial.Length > MaxBytes) throw new Roles.DomainValidationException("CSV exceeds the 128 MiB safety limit.");
        var signature = (initial.Length, initial.LastWriteTimeUtc.Ticks);
        var encoding = ResolveEncoding();
        using (var reader = new StreamReader(_path, encoding, detectEncodingFromByteOrderMarks: true))
        {
            var sampleBuffer = new char[65536];
            var sampleLength = reader.ReadBlock(sampleBuffer, 0, sampleBuffer.Length);
            var sample = new string(sampleBuffer, 0, sampleLength);
            var delimiter = _profile.Delimiter == "auto" ? PythonSniffer.Sniff(sample, ",;\t|") ?? ',' : _profile.Delimiter[0];
            Report.Delimiter = delimiter.ToString();
            using var combined = new ConcatReader(sample, reader);
            using var rows = CsvReader.Read(combined, delimiter).GetEnumerator();
            var headers = rows.MoveNext() ? rows.Current : [];
            Report.DetectedColumns = [.. headers];
            var keys = headers.Select(NormalizedHeader).ToList();
            if (keys.Distinct().Count() != keys.Count || headers.Any(h => h.Trim().Length == 0))
                throw new Roles.DomainValidationException("CSV headers contain duplicate, ambiguous or empty column names.");
            var detected = keys.Zip(headers).ToDictionary(p => p.First, p => p.Second);
            var mapping = _spec.Fields.ToDictionary(f => f, f => _profile.Columns.TryGetValue(f, out var manual) ? manual : detected.GetValueOrDefault(NormalizedHeader(f)));
            foreach (var source in _profile.Columns.Values)
                if (!headers.Contains(source)) throw new Roles.DomainValidationException("A mapped source column is missing.");
            if (mapping[_spec.Required] is null) throw new Roles.DomainValidationException($"The required {_spec.Required} field is not mapped.");
            Report.ResolvedMapping = mapping;
            Report.Warnings = _spec.Fields.Where(f => mapping[f] is null).Select(f => $"Optional field {f} is not mapped.").ToList();
            var used = mapping.Values.Where(v => v is not null).ToHashSet();
            if (headers.Any(h => !used.Contains(h))) Report.Warnings.Add("Unmapped extra columns are not used; map any relationship/assignment fields before importing.");
            var index = headers.Select((h, i) => (h, i)).ToDictionary(p => p.h, p => p.i);
            var seen = new HashSet<string>(StringComparer.Ordinal);
            while (rows.MoveNext())
            {
                cancellation.ThrowIfCancellationRequested();
                var raw = rows.Current;
                Report.ParsedRows++;
                if (Report.ParsedRows > MaxRows) throw new Roles.DomainValidationException("CSV exceeds the one-million-record safety limit.");
                if (raw.Length != headers.Length) throw new Roles.DomainValidationException("CSV row width does not match its header; no data was applied.");
                var row = new Dictionary<string, string>(_spec.Fields.Count, StringComparer.Ordinal);
                foreach (var field in _spec.Fields) row[field] = mapping[field] is { } source ? raw[index[source]].Trim() : "";
                if (row.Values.All(v => v.Length == 0)) { Report.BlankRows++; continue; }
                if (row[_spec.Required].Length == 0) throw new Roles.DomainValidationException($"A nonempty record has no {_spec.Required}; no data was applied.");
                if (row.Any(p => !_spec.LenientFields.Contains(p.Key) && p.Value.Length > 4096)) throw new Roles.DomainValidationException("A CSV field exceeds its length limit.");
                if (_spec.IdentifierFields.Any(f => row[f].Length > 512)) throw new Roles.DomainValidationException("A role identifier is too long.");
                if (!seen.Add(string.Join('\u001f', _spec.Fields.Select(f => row[f])))) { Report.DuplicateRows++; continue; }
                Report.UniqueRecords++;
                if (Report.Samples.Count < 5) Report.Samples.Add(new Dictionary<string, string>(row, StringComparer.Ordinal));
                yield return row;
            }
            if (Report.DuplicateRows > 0) Report.Warnings.Add($"{Report.DuplicateRows} identical duplicate records were deduplicated.");
            if (Report.BlankRows > 0) Report.Warnings.Add($"{Report.BlankRows} empty records were ignored.");
        }
        var after = new FileInfo(_path);
        if ((after.Length, after.LastWriteTimeUtc.Ticks) != signature)
            throw new Roles.DomainValidationException("The CSV changed while being read. Wait for its export to finish and retry; previous data is retained.");
    }

    /// <summary>Re-reads the already consumed sample, then continues with the stream: one pass over the file, no second open.</summary>
    private sealed class ConcatReader(string head, TextReader tail) : TextReader
    {
        private int _position;
        public override int Peek() => _position < head.Length ? head[_position] : tail.Peek();
        public override int Read() => _position < head.Length ? head[_position++] : tail.Read();
    }
}
