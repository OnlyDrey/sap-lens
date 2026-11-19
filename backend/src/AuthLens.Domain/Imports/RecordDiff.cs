namespace AuthLens.Domain.Imports;

/// <summary>One changed record of a refresh report (v1 diff_records `changes`): `modified` names the changed fields with before/after values and keeps
/// both records; `added` keeps only `after`, `removed` only `before`.</summary>
public sealed record RecordChange(string Type, string Identifier, IReadOnlyList<FieldChange> Fields, IReadOnlyDictionary<string, string>? Before,
    IReadOnlyDictionary<string, string>? After);

public sealed record FieldChange(string Field, string Before, string After);

/// <param name="Records">The records of the new revision as v1 counts them (SoD: distinct matrix rows).</param>
public sealed record RecordDiffResult(DiffCounts Counts, IReadOnlyList<RecordChange> Changes, int MissingIdentifiers, int Records);

/// <summary>Port of csv_lifecycle.diff_records: a multiset comparison, stable under reordering and distinct validity intervals. Exact observations
/// cancel first; only one remaining old and one new observation of a stable identifier are a modification, ambiguous or unidentified groups stay
/// added/removed (never invented modifications). Groups are reported in v1's order (sorted identity tuples).</summary>
public static class RecordDiff
{
    public const string IdentityNote = "Exact records are compared as multisets. Ambiguous or missing identifiers are not paired into invented modifications.";
    private static readonly string[] RoleFields = ["AGR_NAME", "CHILD_AGR", "PARENT_AGR", "Effective_Role", "TCODE"];
    private static readonly string[] UserFields = ["USERNAME", "ROLE_NAME", "USER_GROUP"];
    private static readonly string[] SodFields = ["RISK", "ACTIVITY_SLOT", "ACTIVITY", "TCODE"];
    private static readonly string[] Missing = ["missing"];

    /// <summary>record_key: the stable identity of a record, or null for a directory row without DN and account name (v1 None).</summary>
    public static string[]? Key(string source, IReadOnlyDictionary<string, string> row)
    {
        if (source == "employees")
        {
            // Email is deliberately not a record identity. v1 tests the raw values (`row.get(DN) or row.get(SAM)`) and normalizes the chosen one.
            var dn = row.GetValueOrDefault("DistinguishedName", "");
            var value = dn.Length > 0 ? dn : row.GetValueOrDefault("SamAccountName", "");
            return value.Length > 0 ? [dn.Length > 0 ? "dn" : "sam", value.Trim().PyCasefold()] : null;
        }
        if (source == "sod") return SodFields.Select(f => row.GetValueOrDefault(f, "")).ToArray();
        return (source == "roles" ? RoleFields : UserFields).Select(f => row.GetValueOrDefault(f, "").Trim().PyUpper()).ToArray();
    }

    private static string Identity(IReadOnlyDictionary<string, string> row) =>
        string.Join('\u001e', row.Where(p => p.Key != "id").OrderBy(p => p.Key, StringComparer.Ordinal).Select(p => p.Key + "\u001f" + p.Value));

    /// <summary>Python tuple order: element by element, ordinal, a shorter prefix first.</summary>
    private sealed class TupleOrder : IComparer<string[]>
    {
        public static readonly TupleOrder Instance = new();
        public int Compare(string[]? x, string[]? y)
        {
            for (var i = 0; i < Math.Min(x!.Length, y!.Length); i++)
            {
                var c = string.CompareOrdinal(x[i], y[i]);
                if (c != 0) return c;
            }
            return x.Length.CompareTo(y.Length);
        }
    }

    public static RecordDiffResult Compare(string source, IReadOnlyList<IReadOnlyDictionary<string, string>> before,
        IReadOnlyList<IReadOnlyDictionary<string, string>> after, bool includeChanges = true)
    {
        if (source == "sod")
        {
            // v1 SoD records hold the ten matrix columns, once each (parse_sod drops rows that repeat them); the optional metadata columns are descriptive
            // report metadata, not record content.
            static IReadOnlyList<IReadOnlyDictionary<string, string>> Core(IEnumerable<IReadOnlyDictionary<string, string>> rows) =>
                rows.Select(row => (IReadOnlyDictionary<string, string>)Csv.CsvSpec.SodHeaders.Where(row.ContainsKey).ToDictionary(f => f, f => row[f]))
                    .DistinctBy(Identity).ToList();
            (before, after) = (Core(before), Core(after));
        }
        var oldCounts = before.GroupBy(Identity).ToDictionary(g => g.Key, g => g.Count());
        var newCounts = after.GroupBy(Identity).ToDictionary(g => g.Key, g => g.Count());
        var unchanged = oldCounts.Sum(p => Math.Min(p.Value, newCounts.GetValueOrDefault(p.Key)));
        var missing = before.Concat(after).Count(row => Key(source, row) is null);
        var keyComparer = new KeyEquality();
        Dictionary<string[], List<IReadOnlyDictionary<string, string>>> Group(IReadOnlyList<IReadOnlyDictionary<string, string>> rows, Dictionary<string, int> mine, Dictionary<string, int> other)
        {
            var groups = new Dictionary<string[], List<IReadOnlyDictionary<string, string>>>(keyComparer);
            var remaining = mine.ToDictionary(p => p.Key, p => p.Value - Math.Min(p.Value, other.GetValueOrDefault(p.Key)));
            foreach (var row in rows)
            {
                var id = Identity(row);
                if (remaining[id] <= 0) continue;
                remaining[id]--;
                // The `id` bookkeeping field of directory rows is not part of a record.
                IReadOnlyDictionary<string, string> clean = row.ContainsKey("id") ? row.Where(p => p.Key != "id").ToDictionary(p => p.Key, p => p.Value) : row;
                var key = Key(source, clean) ?? Missing;
                if (!groups.TryGetValue(key, out var list)) groups[key] = list = [];
                list.Add(clean);
            }
            return groups;
        }
        var oldGroups = Group(before, oldCounts, newCounts);
        var newGroups = Group(after, newCounts, oldCounts);
        int added = 0, removed = 0, modified = 0, ambiguous = 0;
        var changes = new List<RecordChange>();
        foreach (var key in oldGroups.Keys.Union(newGroups.Keys, keyComparer).Order(TupleOrder.Instance))
        {
            var old = oldGroups.GetValueOrDefault(key) ?? [];
            var current = newGroups.GetValueOrDefault(key) ?? [];
            var representative = (current.Count > 0 ? current : old)[0];
            string[] display = source == "employees"
                ? [representative.GetValueOrDefault("DistinguishedName", "").Length > 0 ? "DistinguishedName" : "SamAccountName"]
                : source == "roles" ? RoleFields : UserFields;
            var identifier = string.Join(" / ", display.Select(f => representative.GetValueOrDefault(f, "")).Where(v => v.Length > 0));
            if (identifier.Length == 0) identifier = "Unidentified record";
            if (old.Count == 1 && current.Count == 1 && !keyComparer.Equals(key, Missing))
            {
                modified++;
                if (!includeChanges) continue;
                var (left, right) = (old[0], current[0]);
                var fields = left.Keys.Union(right.Keys).Order(StringComparer.Ordinal)
                    .Where(f => left.TryGetValue(f, out var l) != right.TryGetValue(f, out var r) || l != r)
                    .Select(f => new FieldChange(f, left.GetValueOrDefault(f, ""), right.GetValueOrDefault(f, ""))).ToList();
                changes.Add(new RecordChange("modified", identifier, fields, left, right));
                continue;
            }
            if (old.Count > 0 && current.Count > 0) ambiguous++;
            removed += old.Count;
            added += current.Count;
            if (!includeChanges) continue;
            changes.AddRange(old.Select(row => new RecordChange("removed", identifier, [], row, null)));
            changes.AddRange(current.Select(row => new RecordChange("added", identifier, [], null, row)));
        }
        return new RecordDiffResult(new DiffCounts(added, removed, modified, unchanged, ambiguous), changes, missing, after.Count);
    }

    private sealed class KeyEquality : IEqualityComparer<string[]>
    {
        public bool Equals(string[]? x, string[]? y) => x!.SequenceEqual(y!, StringComparer.Ordinal);
        public int GetHashCode(string[] key)
        {
            var hash = new HashCode();
            foreach (var part in key) hash.Add(part, StringComparer.Ordinal);
            return hash.ToHashCode();
        }
    }
}
