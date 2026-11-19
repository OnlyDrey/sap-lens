using System.Text;

namespace AuthLens.Domain.Csv;

public sealed class CsvFormatException(string message) : Exception(message);

/// <summary>Streaming RFC 4180 reader with the behaviour of Python's csv module (doublequote, strict): quoted fields may contain delimiters and
/// line breaks, a quote inside an unquoted field is literal, text after a closing quote and an unterminated quote are errors, and a completely
/// empty line yields no record.</summary>
public static class CsvReader
{
    public static IEnumerable<string[]> Read(TextReader reader, char delimiter)
    {
        var field = new StringBuilder();
        var record = new List<string>();
        var state = 0; // 0 start of field, 1 in field, 2 in quoted, 3 quote inside quoted
        var lineHasContent = false;
        int next;
        while ((next = reader.Read()) >= 0)
        {
            var c = (char)next;
            if (c == '\r' && state != 2)
            {
                if (reader.Peek() == '\n') reader.Read();
                c = '\n';
            }
            switch (state)
            {
                case 2:
                    if (c == '"') state = 3; else field.Append(c);
                    continue;
                case 3:
                    if (c == '"') { field.Append('"'); state = 2; continue; }
                    if (c == delimiter) { record.Add(field.ToString()); field.Clear(); state = 0; lineHasContent = true; continue; }
                    if (c == '\n') { record.Add(field.ToString()); field.Clear(); yield return record.ToArray(); record.Clear(); state = 0; lineHasContent = false; continue; }
                    throw new CsvFormatException("'" + delimiter + "' expected after '\"'");
                default:
                    if (c == '\n')
                    {
                        if (state == 0 && record.Count == 0 && !lineHasContent) continue; // empty line: no record, as csv.reader yields []
                        record.Add(field.ToString()); field.Clear(); yield return record.ToArray(); record.Clear(); state = 0; lineHasContent = false; continue;
                    }
                    if (c == delimiter) { record.Add(field.ToString()); field.Clear(); state = 0; lineHasContent = true; continue; }
                    if (c == '"' && state == 0) { state = 2; lineHasContent = true; continue; }
                    field.Append(c); state = 1; lineHasContent = true;
                    continue;
            }
        }
        if (state == 2) throw new CsvFormatException("unexpected end of data");
        if (lineHasContent || record.Count > 0 || field.Length > 0) { record.Add(field.ToString()); yield return record.ToArray(); }
    }

}
