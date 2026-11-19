using System.IO.Compression;
using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;
using System.Xml;
using System.Xml.Linq;

namespace AuthLens.Domain.Sod;

/// <summary>A refused reference workbook; the message is what v1 sod_reference.parse reports (shown to the administrator as the 422 detail).</summary>
public sealed class ReferenceWorkbookException(string message, bool fieldValidation = false) : Exception(message)
{
    /// <summary>A field failed the metadata model (v1 raises a Pydantic ValidationError there, whose text differs from this message).</summary>
    public bool FieldValidation { get; } = fieldValidation;
}

public sealed record ReferenceLibrary(string Digest, SortedDictionary<string, SortedDictionary<string, string>> Risks,
    SortedDictionary<string, SortedDictionary<string, string>> Activities, SortedDictionary<string, string> Terms);

/// <summary>Port of sod_reference.parse: bounded XLSX reading with no formulas, external entities, links, macros or inferred identifiers. Only the
/// Risks, Activities and Definitions sheets are read; headers must be exactly the documented ones; identifiers are exact (no case folding, no
/// prefixes); every value goes through the same field rules as a local annotation.</summary>
public static partial class SodReferenceWorkbook
{
    public const int MaxBytes = 2 * 1024 * 1024, MaxExpanded = 12 * 1024 * 1024, MaxField = 12000, MaxRecords = 5001;
    private const string S = "http://schemas.openxmlformats.org/spreadsheetml/2006/main";
    private const string Rel = "http://schemas.openxmlformats.org/officeDocument/2006/relationships";
    private static readonly XNamespace Ns = S;
    public const string Generic = "The file is not a supported reference XLSX workbook.";

    public static readonly (string Header, string Field, int Max)[] Risk =
    [
        ("Display name", "display_name", 200), ("Business area", "business_category", 120), ("Business explanation", "explanation_en", 12000),
        ("Risk consequence", "consequence_en", 8000), ("Mitigating controls", "mitigating_controls_en", 12000), ("Review Guidance", "review_guidance_en", 8000), ("Local notes", "notes", 8000),
    ];
    public static readonly (string Header, string Field, int Max)[] Activity = [.. Risk.Where(c => c.Header is not ("Risk consequence" or "Mitigating controls"))];

    [GeneratedRegex("^([A-Z]{1,2})[0-9]+$")] private static partial Regex CellReference();
    [GeneratedRegex("^[A-Za-z0-9_:-]{1,128}$")] public static partial Regex Identifier();

    private static int Length(string value) => value.EnumerateRunes().Count();

    public static ReferenceLibrary Parse(byte[] raw)
    {
        if (raw.Length == 0 || raw.Length > MaxBytes) throw new ReferenceWorkbookException("Choose a non-empty XLSX workbook up to 2 MB.");
        try
        {
            using var archive = new ZipArchive(new MemoryStream(raw), ZipArchiveMode.Read);
            var files = archive.Entries;
            if (files.Count > 100 || files.Select(f => f.FullName).Distinct(StringComparer.Ordinal).Count() != files.Count || files.Sum(f => f.Length) > MaxExpanded)
                throw new ReferenceWorkbookException("Workbook exceeds safe archive limits.");
            if (files.Any(f => f.FullName.PyLower().Contains("externallinks/") || f.FullName.PyLower().Contains("vbaproject")))
                throw new ReferenceWorkbookException("External links and macros are not supported.");

            XElement Xml(string name)
            {
                var entry = archive.GetEntry(name) ?? throw new KeyNotFoundException(name);
                using var stream = entry.Open();
                using var memory = new MemoryStream();
                stream.CopyTo(memory);
                var data = memory.ToArray();
                var upper = Encoding.Latin1.GetString(data).PyUpper();
                if (upper.Contains("<!DOCTYPE", StringComparison.Ordinal) || upper.Contains("<!ENTITY", StringComparison.Ordinal))
                    throw new ReferenceWorkbookException("XML declarations are not supported.");
                using var reader = XmlReader.Create(new MemoryStream(data), new XmlReaderSettings { DtdProcessing = DtdProcessing.Prohibit, XmlResolver = null });
                return XDocument.Load(reader).Root!;
            }
            static string Text(XElement element) => string.Concat(element.DescendantNodes().OfType<XText>().Select(t => t.Value));

            var strings = archive.GetEntry("xl/sharedStrings.xml") is null ? [] : Xml("xl/sharedStrings.xml").Elements(Ns + "si").Select(Text).ToList();
            var rels = new Dictionary<string, string?>(StringComparer.Ordinal);
            foreach (var item in Xml("xl/_rels/workbook.xml.rels").Elements()) rels[(string?)item.Attribute("Id") ?? ""] = (string?)item.Attribute("Target");
            var sheets = new Dictionary<string, List<Dictionary<string, string>>>(StringComparer.Ordinal);
            long budget = 0;
            foreach (var sheet in Xml("xl/workbook.xml").Elements(Ns + "sheets").Elements(Ns + "sheet"))
            {
                var name = (string?)sheet.Attribute("name");
                if (name is not ("Risks" or "Activities" or "Definitions")) continue;
                var target = rels[(string?)sheet.Attribute(XName.Get("id", Rel)) ?? throw new KeyNotFoundException("r:id")] ?? throw new KeyNotFoundException("Target");
                var path = target.StartsWith('/') ? target.TrimStart('/') : "xl/" + target;
                if (path.Split('/').Contains("..")) throw new ReferenceWorkbookException("Invalid workbook reference.");
                if (sheets.ContainsKey(name)) throw new ReferenceWorkbookException("Duplicate reference sheet.");
                var rows = new List<Dictionary<string, string>>();
                foreach (var row in Xml(path).Elements(Ns + "sheetData").Elements(Ns + "row"))
                {
                    var cells = new Dictionary<string, string>(StringComparer.Ordinal);
                    foreach (var cell in row.Elements())
                    {
                        if (cell.Element(Ns + "f") is not null) throw new ReferenceWorkbookException("Formula cells are not supported in reference definitions.");
                        var match = CellReference().Match((string?)cell.Attribute("r") ?? "");
                        if (!match.Success) throw new ReferenceWorkbookException("Invalid cell reference.");
                        var value = cell.Element(Ns + "v");
                        var text = value is null ? "" : value.Value;
                        var type = (string?)cell.Attribute("t");
                        if (type == "s") text = strings[int.Parse(text, System.Globalization.CultureInfo.InvariantCulture)];
                        else if (type == "inlineStr") text = Text(cell.Element(Ns + "is") ?? throw new KeyNotFoundException("is"));
                        budget += Length(text);
                        if (budget > MaxExpanded) throw new ReferenceWorkbookException("Workbook expanded text exceeds its safe limit.");
                        if (Length(text) > MaxField) throw new ReferenceWorkbookException("A reference field exceeds its size limit.");
                        cells[match.Groups[1].Value] = text.Trim();
                    }
                    if (cells.Values.Any(v => v.Length > 0)) rows.Add(cells);
                }
                if (rows.Count > MaxRecords) throw new ReferenceWorkbookException("Too many reference records.");
                sheets[name] = rows;
            }

            var risks = Records(sheets, "Risks", "Risk", Risk);
            var activities = Records(sheets, "Activities", "Activity", Activity);
            var terms = new SortedDictionary<string, string>(StringComparer.Ordinal);
            if (sheets.TryGetValue("Definitions", out var definitions) && definitions.Count > 0)
            {
                var head = definitions[0];
                if (head.Count != 2 || head.GetValueOrDefault("A") != "Term" || head.GetValueOrDefault("B") != "Definition") throw new ReferenceWorkbookException("Definitions headers must be Term and Definition.");
                foreach (var row in definitions.Skip(1))
                {
                    var (term, definition) = (row.GetValueOrDefault("A", ""), row.GetValueOrDefault("B", ""));
                    if (term.Length == 0 || definition.Length == 0 || terms.ContainsKey(term)) throw new ReferenceWorkbookException("Definitions contain missing or duplicate terms.");
                    terms[term] = definition;
                }
                // Library.validate_terms: at most 100 terms, each term up to 200 characters.
                if (terms.Count > 100 || terms.Any(t => Length(t.Key) > 200)) throw new ReferenceWorkbookException("Invalid reference terminology.", fieldValidation: true);
            }
            return new ReferenceLibrary(Convert.ToHexStringLower(SHA256.HashData(raw)), risks, activities, terms);
        }
        catch (Exception error) when (error is InvalidDataException or KeyNotFoundException or ArgumentException or XmlException or FormatException or IndexOutOfRangeException or IOException or NotSupportedException or OverflowException)
        {
            throw new ReferenceWorkbookException(Generic);
        }
    }

    private static SortedDictionary<string, SortedDictionary<string, string>> Records(Dictionary<string, List<Dictionary<string, string>>> sheets, string title, string idHeader, (string Header, string Field, int Max)[] mapping)
    {
        var rows = sheets.GetValueOrDefault(title) ?? [];
        if (rows.Count < 2) throw new ReferenceWorkbookException($"{title} must contain a header and definitions.");
        var header = rows[0];
        var expected = mapping.Select(m => m.Header).Append(idHeader).ToHashSet(StringComparer.Ordinal);
        if (header.Values.Distinct(StringComparer.Ordinal).Count() != header.Count || !header.Values.ToHashSet(StringComparer.Ordinal).SetEquals(expected))
            throw new ReferenceWorkbookException($"{title} headers do not match the supported reference workbook.");
        var destination = new SortedDictionary<string, SortedDictionary<string, string>>(StringComparer.Ordinal);
        foreach (var row in rows.Skip(1))
        {
            if (row.Keys.Any(k => !header.ContainsKey(k))) throw new ReferenceWorkbookException("Reference row contains an unheaded column.");
            var values = new Dictionary<string, string>(StringComparer.Ordinal);
            foreach (var (column, value) in row) values[header.GetValueOrDefault(column, "")] = value;
            var identifier = values.GetValueOrDefault(idHeader, "");
            if (!Identifier().IsMatch(identifier) || destination.ContainsKey(identifier)) throw new ReferenceWorkbookException($"{title} contains a missing, invalid or duplicate exact identifier.");
            var record = new SortedDictionary<string, string>(StringComparer.Ordinal);
            foreach (var (column, field, max) in mapping)
            {
                var value = values.GetValueOrDefault(column, "");
                // LocalMetadata / ActivityMetadata: length on the value as read, no control characters except tab and line breaks, then trimmed.
                if (Length(value) > max) throw new ReferenceWorkbookException($"{title} record {identifier}: {column} exceeds {max} characters.", fieldValidation: true);
                if (value.Any(c => c < 32 && c is not ('\n' or '\r' or '\t'))) throw new ReferenceWorkbookException($"{title} record {identifier}: {column} contains unsupported control characters.", fieldValidation: true);
                if (value.Trim().Length > 0) record[field] = value.Trim();
            }
            destination[identifier] = record;
        }
        if (destination.Count > 5000) throw new ReferenceWorkbookException("Too many reference records.", fieldValidation: true);
        return destination;
    }
}
