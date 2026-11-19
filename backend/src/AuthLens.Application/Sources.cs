using System.Security.Cryptography;
using System.Text;
using System.Text.Encodings.Web;
using System.Text.Json;
using AuthLens.Domain.Csv;
using AuthLens.Domain.Roles;
using AuthLens.Domain.Users;

namespace AuthLens.Application;

/// <summary>The three import sources of the prototype and how a CSV becomes canonical records (the same mapping the equivalence harness checks).</summary>
public static class Sources
{
    public const string Roles = "roles", Users = "users", Sod = "sod", Employees = "employees";
    public static readonly string[] All = [Roles, Users, Sod, Employees];
    public static readonly JsonSerializerOptions Json = new() { Encoder = JavaScriptEncoder.UnsafeRelaxedJsonEscaping, PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower };

    public static bool IsKnown(string source) => All.Contains(source, StringComparer.Ordinal);

    /// <summary>Streams the canonical records of a CSV. SoD keeps only the core headers, exactly as the v1 SoD source does.</summary>
    public static (IEnumerable<IReadOnlyDictionary<string, string>> Records, ImportReport Report) Read(string source, string path, CancellationToken cancellation, CsvProfile? profile = null)
    {
        if (source == Employees)
        {
            // Fixed documented schema (no import profile), read once and parsed as a whole, like v1 parse_directory.
            var length = new FileInfo(path).Length;
            if (length > Domain.Directory.EmployeeDirectory.MaxBytes) throw new CsvFormatException("Employee Directory CSV exceeds the 50 MB limit.");
            var rows = Domain.Directory.EmployeeDirectory.Parse(File.ReadAllBytes(path));
            return (rows, new ImportReport { FileName = Path.GetFileName(path), ParsedRows = rows.Count, UniqueRecords = rows.Count, DetectedColumns = [.. Domain.Directory.EmployeeDirectory.Headers] });
        }
        var import = source switch
        {
            Roles => new CsvImport(path, profile ?? new CsvProfile(), CsvSpec.Roles),
            Users => new CsvImport(path, profile ?? new CsvProfile(), CsvSpec.Users),
            Sod => new CsvImport(path, profile ?? new CsvProfile(Id: "sod"), CsvSpec.Sod),
            _ => throw new DomainValidationException("Unknown import source."),
        };
        // SoD keeps the ten documented columns plus the optional descriptive columns that the file actually maps (v1 SodCsvImport): an unmapped
        // optional column is absent from the stored record, so files without optional columns store exactly what they stored before.
        IEnumerable<IReadOnlyDictionary<string, string>> records = source == Sod
            ? import.Records(cancellation).Select(r => (IReadOnlyDictionary<string, string>)CsvSpec.SodHeaders
                .Concat(CsvSpec.SodOptional.Where(f => import.Report.ResolvedMapping.GetValueOrDefault(f) is not null))
                .ToDictionary(h => h, h => r.GetValueOrDefault(h, ""), StringComparer.Ordinal))
            : import.Records(cancellation);
        return (records, import.Report);
    }

    public static string Serialize(IReadOnlyDictionary<string, string> record) => JsonSerializer.Serialize(record, Json);

    public static Dictionary<string, string> Deserialize(string payload) => JsonSerializer.Deserialize<Dictionary<string, string>>(payload, Json)!;

    /// <summary>Identity of an assignment for review purposes: the user key and the NORMALIZED role name (Assignment.RoleName keeps the exported spelling,
    /// as v1 does). U+001F cannot occur in either (normalization strips it).</summary>
    public static string AssignmentKey(Assignment assignment) => AssignmentKey(assignment.UserKey, assignment.RoleName);

    public static string AssignmentKey(string user, string role) => RoleNames.NormalizeUsername(user) + "\u001f" + RoleNames.Normalize(role);

    public static HashSet<string> AssignmentKeys(UserDirectory users) => users.Assignments.Select(AssignmentKey).ToHashSet(StringComparer.Ordinal);

    /// <summary>Identity of an SAP account for Account Review. The U+001E prefix keeps it apart from assignment keys in the shared invalidation log.</summary>
    public static string AccountKey(string username) => "\u001eaccount\u001f" + RoleNames.NormalizeUsername(username);

    /// <summary>Everything a users revision can make disappear: assignments and accounts. A disappearance is recorded as an invalidation, so a decision
    /// made before it no longer applies when the subject returns.</summary>
    public static HashSet<string> ReviewKeys(UserDirectory users)
    {
        var keys = AssignmentKeys(users);
        foreach (var name in users.Users.Keys) keys.Add(AccountKey(name));
        return keys;
    }
}

/// <summary>Incremental SHA-256 over the ordered canonical payloads: the dataset content hash.</summary>
public sealed class ContentHasher : IDisposable
{
    private readonly IncrementalHash _hash = IncrementalHash.CreateHash(HashAlgorithmName.SHA256);

    public void Add(string payload)
    {
        _hash.AppendData(Encoding.UTF8.GetBytes(payload));
        _hash.AppendData("\n"u8);
    }

    public string Finish() => Convert.ToHexStringLower(_hash.GetHashAndReset());
    public void Dispose() => _hash.Dispose();
}
