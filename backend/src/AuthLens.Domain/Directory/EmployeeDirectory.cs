using System.Security.Cryptography;
using System.Text;
using AuthLens.Domain.Csv;
using AuthLens.Domain.Users;

namespace AuthLens.Domain.Directory;

/// <summary>Port of employee_directory.py: optional local employee enrichment from an AD export with a fixed, documented schema (16 semicolon headers,
/// UTF-8). No name guessing and no recursive manager traversal: managers resolve by ManagerMail, then ManagerDN, then ManagerSamAccountName, and a
/// present but ambiguous or unresolved preferred key never falls back. SAP identities match by normalized exact email only.</summary>
public sealed class EmployeeDirectory
{
    public static readonly string[] Headers = "Site;Name;SamAccountName;UserPrincipalName;Mail;Department;Title;Enabled;DistinguishedName;ManagerDN;ManagerName;ManagerSamAccountName;ManagerMail;ManagerDepartment;ManagerTitle;ManagerLookupStatus".Split(';');
    public const long MaxBytes = 50L * 1024 * 1024;
    public const int MaxRecords = 100_000, MaxField = 4096;

    public IReadOnlyList<IReadOnlyDictionary<string, string>> Rows { get; }
    public string FileName { get; }
    public string Digest { get; }
    public string ImportedAt { get; }
    public Dictionary<string, Dictionary<string, List<int>>> Indexes { get; } = new(StringComparer.Ordinal);

    /// <summary>Python str.strip().casefold() for the identifiers in this file (emails, DNs, account names).</summary>
    public static string Normalized(string? value) => (value ?? "").Trim().PyCasefold();

    public EmployeeDirectory(IReadOnlyList<IReadOnlyDictionary<string, string>> rows, string fileName, string digest, string importedAt)
    {
        (Rows, FileName, Digest, ImportedAt) = (rows, fileName, digest, importedAt);
        foreach (var field in new[] { "Mail", "DistinguishedName", "SamAccountName" })
        {
            var index = new Dictionary<string, List<int>>(StringComparer.Ordinal);
            for (var i = 0; i < rows.Count; i++)
                if (Normalized(rows[i][field]) is { Length: > 0 } key)
                {
                    if (!index.TryGetValue(key, out var list)) index[key] = list = [];
                    list.Add(i);
                }
            Indexes[field] = index;
        }
    }

    /// <summary>parse_directory: the whole file is read once (at most 50 MB), every header present exactly once (case-insensitive), strict quoting,
    /// blank lines skipped, no NUL or oversized fields, at most 100 000 records, at least one.</summary>
    public static List<Dictionary<string, string>> Parse(byte[] raw)
    {
        if (raw.LongLength > MaxBytes) throw new CsvFormatException("Employee Directory CSV exceeds the 50 MB limit.");
        string text;
        try { text = new UTF8Encoding(false, true).GetString(raw.AsSpan(raw.AsSpan().StartsWith("﻿"u8) ? 3 : 0)); }
        catch (DecoderFallbackException) { throw new CsvFormatException("Employee Directory must be valid UTF-8 semicolon CSV with correctly quoted fields."); }
        var lines = Records(text);
        var header = lines.FirstOrDefault() ?? [];
        var keys = header.Select(Normalized).ToList();
        var expected = Headers.ToDictionary(Normalized, h => h, StringComparer.Ordinal);
        if (keys.Count != expected.Count || keys.Distinct(StringComparer.Ordinal).Count() != keys.Count || !keys.All(expected.ContainsKey))
            throw new CsvFormatException("Employee Directory requires all 16 documented headers, without duplicates, separated by semicolons.");
        var rows = new List<Dictionary<string, string>>();
        foreach (var row in lines.Skip(1))
        {
            if (row.Count == 0 || row.All(v => v.Trim().Length == 0)) continue;
            if (row.Count != keys.Count || row.Any(v => v.Length > MaxField || v.Contains('\0'))) throw new CsvFormatException("Employee Directory contains malformed rows or oversized fields.");
            if (rows.Count >= MaxRecords) throw new CsvFormatException("Employee Directory exceeds the 100,000 record limit.");
            var record = new Dictionary<string, string>(StringComparer.Ordinal);
            for (var i = 0; i < keys.Count; i++) record[expected[keys[i]]] = row[i].Trim();
            rows.Add(record);
        }
        if (rows.Count == 0) throw new CsvFormatException("Employee Directory contains no employee records.");
        return rows;
    }

    public static string Sha256(byte[] raw) => Convert.ToHexStringLower(SHA256.HashData(raw));

    /// <summary>Python csv.reader(delimiter=';', strict=True): quoted fields may contain delimiters, doubled quotes and line breaks; text after a closing
    /// quote or an unterminated quote is an error.</summary>
    private static List<List<string>> Records(string text)
    {
        var records = new List<List<string>>();
        var row = new List<string>();
        var field = new StringBuilder();
        var (quoted, afterQuote, fieldStarted) = (false, false, false);
        void EndField() { row.Add(field.ToString()); field.Clear(); (quoted, afterQuote, fieldStarted) = (false, false, false); }
        void EndRow() { if (fieldStarted || row.Count > 0) EndField(); records.Add(row); row = []; }
        for (var i = 0; i < text.Length; i++)
        {
            var c = text[i];
            if (quoted)
            {
                if (c == '"')
                {
                    if (i + 1 < text.Length && text[i + 1] == '"') { field.Append('"'); i++; }
                    else (quoted, afterQuote) = (false, true);
                }
                else field.Append(c);
                continue;
            }
            if (c == ';') { EndField(); fieldStarted = true; continue; }
            if (c is '\r' or '\n')
            {
                if (c == '\r' && i + 1 < text.Length && text[i + 1] == '\n') i++;
                EndRow();
                continue;
            }
            if (afterQuote) throw new CsvFormatException("Employee Directory contains malformed CSV quoting. Correct the export before importing.");
            if (c == '"' && field.Length == 0)
            {
                (quoted, fieldStarted) = (true, true); // a quote inside an unquoted field is literal text, as in Python's csv module
                continue;
            }
            field.Append(c);
            fieldStarted = true;
        }
        if (quoted) throw new CsvFormatException("Employee Directory contains malformed CSV quoting. Correct the export before importing.");
        if (fieldStarted || row.Count > 0) EndRow();
        return records;
    }

    public (string Status, int? Manager) Manager(int id)
    {
        var record = Rows[id];
        foreach (var (source, target) in new[] { ("ManagerMail", "Mail"), ("ManagerDN", "DistinguishedName"), ("ManagerSamAccountName", "SamAccountName") })
        {
            if (Normalized(record[source]) is not { Length: > 0 } key) continue;
            var matches = Indexes[target].GetValueOrDefault(key) ?? [];
            if (matches.Count == 1) return matches[0] == id ? ("self_reference", null) : ("resolved", matches[0]);
            return matches.Count > 1 ? ("ambiguous", null) : ("unresolved", null);
        }
        return ("missing", null);
    }

    public static string AccountStatus(string enabled) => Normalized(enabled) switch { "true" or "1" => "Enabled", "false" or "0" => "Disabled", _ => "Unknown" };

    public Dictionary<string, object?> View(int id)
    {
        var r = Rows[id];
        var (status, manager) = Manager(id);
        return new()
        {
            ["id"] = id.ToString(System.Globalization.CultureInfo.InvariantCulture), ["name"] = r["Name"], ["email"] = r["Mail"], ["department"] = r["Department"], ["title"] = r["Title"],
            ["site"] = r["Site"], ["username"] = r["SamAccountName"], ["account_status"] = AccountStatus(r["Enabled"]),
            ["manager"] = new Dictionary<string, object?>
            {
                ["name"] = r["ManagerName"], ["email"] = r["ManagerMail"], ["department"] = r["ManagerDepartment"], ["title"] = r["ManagerTitle"], ["username"] = r["ManagerSamAccountName"],
                ["status"] = status, ["employee_id"] = manager?.ToString(System.Globalization.CultureInfo.InvariantCulture),
            },
        };
    }

    public (string Status, Dictionary<string, object?>? Employee) Match(IEnumerable<string> emails)
    {
        var keys = emails.Where(e => e.Trim().Length > 0).Select(Normalized).ToHashSet(StringComparer.Ordinal);
        if (keys.Count == 0) return ("missing_email", null);
        if (keys.Any(k => (Indexes["Mail"].GetValueOrDefault(k)?.Count ?? 0) > 1)) return ("duplicate_email", null);
        var records = keys.SelectMany(k => Indexes["Mail"].GetValueOrDefault(k) ?? []).Distinct().ToList();
        if (keys.Count > 1 || records.Count > 1) return ("ambiguous_sap_email", null);
        return records.Count == 1 ? ("matched", View(records[0])) : ("unmatched", null);
    }

    public static Dictionary<string, int> SapEmailOwners(IEnumerable<SapUser> users)
    {
        var counts = new Dictionary<string, int>(StringComparer.Ordinal);
        foreach (var user in users)
            foreach (var email in user.Emails.Where(e => e.Trim().Length > 0).Select(Normalized).Distinct(StringComparer.Ordinal))
                counts[email] = counts.GetValueOrDefault(email) + 1;
        return counts;
    }

    /// <summary>match_sap_identity: a SAP email shared by several SAP users never establishes a one-person identity.</summary>
    public (string Status, Dictionary<string, object?>? Employee) MatchSapIdentity(SapUser user, IReadOnlyDictionary<string, int> owners) =>
        user.Emails.Where(e => e.Trim().Length > 0).Any(e => owners.GetValueOrDefault(Normalized(e)) > 1) ? ("ambiguous_sap_email", null) : Match(user.Emails);

    private Dictionary<string, object?>? _report;

    public Dictionary<string, object?> Report()
    {
        if (_report is null)
        {
            var managers = new Dictionary<string, int>(StringComparer.Ordinal);
            for (var i = 0; i < Rows.Count; i++) { var status = Manager(i).Status; managers[status] = managers.GetValueOrDefault(status) + 1; }
            _report = new()
            {
                ["records"] = Rows.Count, ["file_name"] = FileName, ["imported_at"] = ImportedAt,
                ["duplicate_emails"] = Indexes["Mail"].Values.Count(v => v.Count > 1),
                ["missing_identifiers"] = Rows.Count(r => r["DistinguishedName"].Length == 0 && r["SamAccountName"].Length == 0),
                ["duplicate_identifiers"] = new Dictionary<string, int> { ["usernames"] = Indexes["SamAccountName"].Values.Count(v => v.Count > 1), ["distinguished_names"] = Indexes["DistinguishedName"].Values.Count(v => v.Count > 1) },
                ["missing_emails"] = Rows.Count(r => r["Mail"].Length == 0), ["managers"] = managers,
                ["validation"] = "Valid UTF-8 semicolon CSV; all required headers present",
            };
        }
        return new Dictionary<string, object?>(_report);
    }
}
