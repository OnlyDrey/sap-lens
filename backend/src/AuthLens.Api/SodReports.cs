using System.Globalization;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;
using Microsoft.EntityFrameworkCore;
using AuthLens.Application;
using AuthLens.Documents;
using AuthLens.Domain.Sod;
using AuthLens.Persistence;

namespace AuthLens.Api;

/// <summary>Python json.dumps(value, sort_keys=True, ensure_ascii=False) with the default separators, so a report model checksum is the one v1 computes.</summary>
public static class PythonJson
{
    public static string Dumps(JsonNode? node)
    {
        var sb = new StringBuilder();
        Write(sb, node);
        return sb.ToString();
    }

    private static void Write(StringBuilder sb, JsonNode? node)
    {
        switch (node)
        {
            case null: sb.Append("null"); break;
            case JsonObject o:
                sb.Append('{');
                var first = true;
                foreach (var (k, v) in o.OrderBy(p => p.Key, StringComparer.Ordinal))
                {
                    if (!first) sb.Append(", ");
                    first = false;
                    String(sb, k); sb.Append(": "); Write(sb, v);
                }
                sb.Append('}');
                break;
            case JsonArray a:
                sb.Append('[');
                for (var i = 0; i < a.Count; i++) { if (i > 0) sb.Append(", "); Write(sb, a[i]); }
                sb.Append(']');
                break;
            case JsonValue v:
                switch (v.GetValueKind())
                {
                    case JsonValueKind.String: String(sb, (string)v!); break;
                    case JsonValueKind.True: sb.Append("true"); break;
                    case JsonValueKind.False: sb.Append("false"); break;
                    default: sb.Append(v.ToJsonString()); break;
                }
                break;
        }
    }

    private static void String(StringBuilder sb, string s)
    {
        sb.Append('"');
        foreach (var c in s)
            sb.Append(c switch
            {
                '"' => "\\\"", '\\' => "\\\\", '\n' => "\\n", '\r' => "\\r", '\t' => "\\t", '\b' => "\\b", '\f' => "\\f",
                < ' ' => $"\\u{(int)c:x4}", _ => c.ToString(),
            });
        sb.Append('"');
    }
}

/// <summary>Port of sod_reports.py: one frozen evidence model per report (sealed with a SHA-256 of its JSON), rendered as DOCX or PDF by the native renderers,
/// and the operational remediation model (CSV, DOCX, PDF). Reports read a period's frozen snapshot only; report generation never approves a review.</summary>
public static class SodReports
{
    public static readonly string[] Sections = ["executive", "methodology", "risk_overview", "activity_results", "assignment_results", "risk_acceptance", "controls", "outstanding", "remediation", "sources", "changes", "conclusion", "appendices"];
    public static readonly string[] Headings = ["Executive Summary", "Scope and Evaluation Period", "Overall Findings and Risk Exposure", "Review Progress: Activity Decisions", "Review Progress: Role Assignment Decisions",
        "Review Progress: Risk Acceptance Decisions", "Compensating Controls and Conditions", "Outstanding Risks and Actions", "Remediation Responsibilities and Status", "Evidence Freshness and Limitations",
        "Changes Since Previous Review", "Conclusion and Approval", "Technical Appendices"];
    public const int MaxRows = 20000;
    public static readonly Dictionary<string, string> StatusStatements = new(StringComparer.Ordinal)
    {
        ["Draft"] = "Draft: this document has not been reviewed or approved.",
        ["Reviewed"] = "Reviewed: review decisions are recorded with identity provenance. SAP Lens does not authenticate Desktop/legacy profile names; server session events retain account attribution. Review completion is not approval.",
        ["Approved"] = "Approved in SAP Lens: the review period has an explicit recorded approval and is frozen. Identity provenance is retained; Desktop/legacy names are self-reported and not authenticated. This is not a digital signature. Self-approval is permitted.",
        ["Externally signed"] = "Externally signed: the preparer states that this document was signed outside SAP Lens. SAP Lens cannot verify the signature.",
    };
    private static readonly string[][] Glossary =
    [
        ["Term", "Meaning"],
        ["Segregation of duties (SoD)", "A control principle: no single person should hold access that lets them both start and approve, or both execute and conceal, a sensitive business step."],
        ["Potential conflict", "A user holds two kinds of access that the risk rules define as incompatible. It is based on the roles assigned to the user, not on proof that the access was misused."],
        ["Role", "A named bundle of SAP access rights that is assigned to a user. Roles supply the access behind each activity."],
        ["Activity", "A business capability, such as creating or approving a payment, that is made possible by one or more SAP transaction codes."],
        ["Transaction code", "The short SAP code for a screen or function. Transaction codes are listed in the technical appendices, not in the main report."],
        ["Risk acceptance", "A separate business decision to tolerate a detected conflict, normally with a justification and compensating controls."],
    ];
    public const string Limitation = "Potential conflicts are based on role-derived transaction evidence, not verified effective SAP authorization. Desktop/legacy identities are self-reported; session-authenticated events retain account provenance. These records are not verified digital signatures.";
    private static readonly Dictionary<string, string> DescriptionSources = new(StringComparer.Ordinal) { ["imported"] = "Imported", ["local"] = "Local override", ["reference"] = "Curated reference library" };
    private const string DescriptionLegend = "Sources: Imported = text supplied in the SoD Matrix CSV when the evidence was captured; Local override = business description maintained in SAP Lens, takes priority over imported metadata; Curated reference library = non-authoritative business guidance used when neither has text; Not available = no description exists. SAP Lens does not write descriptions from identifiers.";
    private static readonly Dictionary<string, string> BasisNotes = new(StringComparer.Ordinal)
    {
        ["captured"] = "These descriptions were frozen with this review period and do not change when data is imported or edited later.",
        ["legacy"] = "This review period was captured before imported descriptions were retained. Only business descriptions maintained in SAP Lens at capture time are shown; no imported descriptions are available for this period.",
        ["current"] = "Current evidence: descriptions reflect the data loaded now and can change after the next import. A review period freezes them.",
    };
    private static readonly Dictionary<string, string> SourceNames = new(StringComparer.Ordinal) { ["roles"] = "Role Catalogue", ["users"] = "User–Role Mapping", ["sod"] = "SoD Matrix", ["employees"] = "Employee Directory" };
    private static readonly string[] RemediationKeys = [.. SodViews.RemediationGroups, "Awaiting review"];

    public sealed class ReportException(int status, string message) : Exception(message) { public int Status { get; } = status; }

    // ---- options

    public sealed record Options(string Title, string PreparedBy, string Reviewer, string ReviewerRole, string Approver, string ApproverRole, DateOnly ReportDate, string DocumentVersion,
        string Status, string ManagementComments, bool IncludeAppendices, List<string> SectionList, string? PreviousPeriodId);

    public sealed record RemediationOptions(string Title, string PreparedBy, DateOnly ReportDate, string DocumentVersion, List<string> Recommended);

    private static string? Str(JsonObject o, string name, int min, int max, string? fallback, List<object> errors)
    {
        if (!o.TryGetPropertyValue(name, out var node) || node is null) return fallback;
        if (node is not JsonValue v || !v.TryGetValue<string>(out var text)) { errors.Add(V1Validation.Error("string_type", name, "Input should be a valid string", ["options"])); return null; }
        text = text.Trim();
        if (text.Length < min || text.Length > max) errors.Add(V1Validation.Error("string_too_long", name, $"String should have between {min} and {max} characters", ["options"]));
        return text;
    }

    private static DateOnly? Day(JsonObject o, string name, List<object> errors)
    {
        if (o[name] is null) return DateOnly.FromDateTime(DateTime.Now);
        if (o[name] is JsonValue v && v.TryGetValue<string>(out var t) && DateOnly.TryParseExact(t, "yyyy-MM-dd", CultureInfo.InvariantCulture, DateTimeStyles.None, out var d)) return d;
        errors.Add(V1Validation.Error("date_from_datetime_parsing", name, "Input should be a valid date", ["options"]));
        return null;
    }

    public static (Options? Value, List<object> Errors) ParseOptions(JsonNode? node)
    {
        var errors = new List<object>();
        var o = node as JsonObject ?? [];
        V1Validation.Extra(o, ["title", "language", "prepared_by", "reviewer", "reviewer_role", "approver", "approver_role", "report_date", "document_version", "status", "management_comments",
            "include_appendices", "sections", "previous_period_id"], errors);
        var title = Str(o, "title", 1, 160, "SoD Access Review", errors);
        if (Str(o, "language", 0, 10, "en", errors) is { } language && language != "en") errors.Add(V1Validation.Error("literal_error", "language", "Input should be 'en'", ["options"]));
        var status = Str(o, "status", 0, 40, "Draft", errors) ?? "Draft";
        status = status switch { "For review" => "Reviewed", "Approved snapshot" => "Approved", _ => status };
        if (!StatusStatements.ContainsKey(status)) errors.Add(V1Validation.Error("literal_error", "status", "Input should be 'Draft', 'Reviewed', 'Approved' or 'Externally signed'", ["options"]));
        var sections = Sections.ToList();
        if (o["sections"] is JsonArray list)
        {
            sections = [.. list.Select(s => s is JsonValue v && v.TryGetValue<string>(out var t) ? t : "")];
            if (sections.Count > 13 || sections.Any(s => !Sections.Contains(s))) errors.Add(V1Validation.Error("literal_error", "sections", "Choose supported report sections.", ["options"]));
            else if (sections.Distinct().Count() != sections.Count) errors.Add(V1Validation.Error("value_error", "sections", "Value error, Choose each report section once.", ["options"]));
        }
        var previous = o["previous_period_id"] is JsonValue pv && pv.TryGetValue<string>(out var p) ? p : null;
        if (previous is not null && !Regex.IsMatch(previous, "^[a-f0-9]{32}$")) errors.Add(V1Validation.Error("string_pattern_mismatch", "previous_period_id", "String should match pattern '^[a-f0-9]{32}$'", ["options"]));
        var include = o["include_appendices"] is not JsonValue iv || iv.GetValueKind() != JsonValueKind.False;
        var date = Day(o, "report_date", errors);
        var options = new Options(title ?? "", Str(o, "prepared_by", 0, 120, "", errors) ?? "", Str(o, "reviewer", 0, 120, "", errors) ?? "", Str(o, "reviewer_role", 0, 120, "", errors) ?? "",
            Str(o, "approver", 0, 120, "", errors) ?? "", Str(o, "approver_role", 0, 120, "", errors) ?? "", date ?? default, Str(o, "document_version", 1, 80, "1.0", errors) ?? "",
            status, Str(o, "management_comments", 0, 12000, "", errors) ?? "", include, sections, previous);
        return (errors.Count == 0 ? options : null, errors);
    }

    public static (RemediationOptions? Value, List<object> Errors) ParseRemediationOptions(JsonNode? node)
    {
        var errors = new List<object>();
        var o = node as JsonObject ?? [];
        V1Validation.Extra(o, ["title", "language", "prepared_by", "report_date", "document_version", "recommended"], errors);
        var recommended = RemediationKeys.ToList();
        if (o["recommended"] is JsonArray list)
        {
            recommended = [.. list.Select(s => s is JsonValue v && v.TryGetValue<string>(out var t) ? t : "")];
            if (recommended.Count > 6 || recommended.Any(r => !RemediationKeys.Contains(r))) errors.Add(V1Validation.Error("literal_error", "recommended", "Choose supported recommended handling values.", ["options"]));
        }
        if (Str(o, "language", 0, 10, "en", errors) is { } language && language != "en") errors.Add(V1Validation.Error("literal_error", "language", "Input should be 'en'", ["options"]));
        var options = new RemediationOptions(Str(o, "title", 1, 160, "Access Remediation Report", errors) ?? "", Str(o, "prepared_by", 0, 120, "", errors) ?? "", Day(o, "report_date", errors) ?? default,
            Str(o, "document_version", 1, 80, "1.0", errors) ?? "", recommended);
        return (errors.Count == 0 ? options : null, errors);
    }

    // ---- text helpers

    public static string LocalizedDate(JsonNode? value)
    {
        var text = value is JsonValue v ? v.ToString() : null;
        if (string.IsNullOrEmpty(text)) return "—";
        var d = DateOnly.ParseExact(text[..10], "yyyy-MM-dd", CultureInfo.InvariantCulture);
        return $"{d.Day:00}.{d.Month:00}.{d.Year:0000}";
    }

    public static string LocalizedStamp(JsonNode? value)
    {
        var text = value is JsonValue v ? v.ToString() : null;
        if (string.IsNullOrEmpty(text)) return "—";
        var stamp = DateTimeOffset.TryParse(text, CultureInfo.InvariantCulture, DateTimeStyles.None, out var parsed) && Regex.IsMatch(text, "([+-]\\d\\d:\\d\\d|Z)$") ? parsed.UtcDateTime
            : DateTime.Parse(text, CultureInfo.InvariantCulture);
        return $"{stamp.Day:00}.{stamp.Month:00}.{stamp.Year:0000} {stamp.Hour:00}:{stamp.Minute:00}";
    }

    private static string S(JsonNode? n) => n is JsonValue v ? v.ToString() : "";
    private static JsonArray Row(params string[] cells) => new([.. cells.Select(c => (JsonNode?)c)]);
    private static JsonArray Table(JsonArray header, IEnumerable<JsonArray> rows)
    {
        var list = rows.ToList();
        return list.Count == 0 ? [] : new JsonArray([header, .. list]);
    }
    private static int Count(SodStates state, string kind, params string[] names) => state.Items[kind].Values.Count(i => names.Contains(i.Lifecycle));
    private static IEnumerable<KeyValuePair<string, int>> Counter(IEnumerable<string> values) =>
        values.GroupBy(v => v, StringComparer.Ordinal).Select(g => KeyValuePair.Create(g.Key, g.Count())).OrderBy(p => p.Key, StringComparer.Ordinal);

    private static JsonArray StatusTable(SodStates state)
    {
        string C(string kind, params string[] names) => Count(state, kind, names).ToString(CultureInfo.InvariantCulture);
        return new JsonArray(
            Row("Review status", "Activities", "Role assignments", "Risk acceptance"),
            Row("Not reviewed (pending or outdated)", C("activity", "Pending", "Outdated"), C("assignment", "Pending", "Outdated", "Investigate"), C("acceptance", "Pending", "Outdated")),
            Row("Reviewed, no action required", C("activity", "Approved", "Conditional"), C("assignment", "Keep"), C("acceptance", "Accepted")),
            Row("Reviewed, removal recommended", C("activity", "Removal required"), C("assignment", "Removal required"), "—"),
            Row("Reviewed, risk rejected", "—", "—", C("acceptance", "Rejected")),
            Row("Under investigation (not a final decision)", "—", C("assignment", "Investigate"), "—"),
            Row(["Access assessment covered (manual or derived)", .. new[] { "activity", "assignment", "acceptance" }.Select(k => state.Coverage[k].Values.Count(v => (bool?)v["reviewed"] ?? false).ToString(CultureInfo.InvariantCulture))]),
            Row("Removal plan breaks conflict (not verified remediation)", "—", "—", state.Coverage["acceptance"].Values.Count(v => (bool?)v["removal_planned"] ?? false).ToString(CultureInfo.InvariantCulture)));
    }

    private static JsonArray FollowupTable(IEnumerable<JsonObject> rows)
    {
        var seen = new Dictionary<string, JsonObject>(StringComparer.Ordinal);
        foreach (var row in rows.Where(r => S(r["recommended"]) == "Remove assignment")) seen.TryAdd(S(row["assignment_id"]), row);
        var items = seen.Values.ToList();
        var tracked = items.Where(r => S(r["action_status"]) != "Not tracked").ToList();
        var open = tracked.Count(r => S(r["action_status"]) is "Open" or "In progress");
        var completed = tracked.Count(r => S(r["action_status"]) == "Completed");
        var verified = tracked.Count(r => S(r["verification"]) == "Not present in current evidence");
        var cancelled = tracked.Count(r => S(r["action_status"]) == "Cancelled");
        static string N(int n) => n.ToString(CultureInfo.InvariantCulture);
        return new JsonArray(Row("Removal follow-up (role assignments)", "Count"), Row("Removal recommended", N(items.Count)), Row("Recommended, no action tracked", N(items.Count - tracked.Count)),
            Row("Action tracked and open", N(open)), Row("Action completed (manually recorded, not proof of removal)", N(completed)), Row("Removal verified in later source evidence", N(verified)),
            Row("Tracked, still present or not assessable", N(tracked.Count - verified - cancelled)));
    }

    private static (string Name, string Description, string Label) Described(JsonObject? entry)
    {
        entry ??= [];
        var origins = entry["origin"] as JsonObject ?? [];
        var parts = new List<(string Field, string Value)>();
        foreach (var field in new[] { "name", "description" })
            if (S(entry[field]).Length > 0) parts.Add((field, DescriptionSources.GetValueOrDefault(S(origins[field]), "Not available")));
        var labels = parts.Select(p => p.Value).Distinct().ToList();
        var label = parts.Count == 0 ? "Not available" : labels.Count == 1 ? labels[0] : string.Join(" · ", parts.Select(p => char.ToUpperInvariant(p.Field[0]) + p.Field[1..] + ": " + p.Value));
        if (entry["alternate"]?["description"] is JsonObject alternate)
            label += " (a different " + DescriptionSources.GetValueOrDefault(S(alternate["origin"]), "Not available") + " description exists)";
        return (S(entry["name"]) is { Length: > 0 } n ? n : "—", S(entry["description"]) is { Length: > 0 } d ? d : "—", label);
    }

    private static (JsonArray Risks, JsonArray Activities) TermTables(JsonObject metadata, IEnumerable<string> riskIds, IEnumerable<string> activityIds)
    {
        JsonArray Build(string first, JsonObject source, IEnumerable<string> keys)
        {
            var rows = keys.Distinct().Order(StringComparer.Ordinal).Select(k => { var (n, d, l) = Described(source[k] as JsonObject); return Row(k, n, d, l); }).ToList();
            return rows.Any(r => S(r[1]) != "—" || S(r[2]) != "—") ? Table(Row(first, "Name", "Description", "Source"), rows) : [];
        }
        return (Build("Risk", metadata["risks"] as JsonObject ?? [], riskIds), Build("Activity", metadata["activities"] as JsonObject ?? [], activityIds));
    }

    /// <summary>sod_metadata.for_period: the snapshot's own frozen descriptions, or for an older snapshot only the local business text frozen with its risks.</summary>
    public static JsonObject ForPeriod(JsonObject saved)
    {
        if (saved["metadata"] is JsonObject copy && (int?)copy["version"] == 1)
            return new JsonObject { ["basis"] = "captured", ["risks"] = copy["risks"]?.DeepClone() ?? new JsonObject(), ["activities"] = copy["activities"]?.DeepClone() ?? new JsonObject(), ["source"] = copy["source"]?.DeepClone() ?? new JsonObject() };
        var risks = new JsonObject();
        var fields = new (string Name, string Local)[] { ("name", "display_name"), ("description", "explanation_en"), ("impact", "consequence_en"), ("business_process", "business_category"), ("controls", "mitigating_controls_en"), ("guidance", "review_guidance_en"), ("notes", "notes") };
        foreach (var item in (saved["risks"] as JsonArray ?? []).Select(r => r!.AsObject()))
        {
            var local = item["local"] as JsonObject ?? [];
            var entry = new JsonObject();
            var origins = new JsonObject();
            foreach (var (name, attribute) in fields)
                if (S(local[attribute]).Trim() is { Length: > 0 } value) { entry[name] = value; origins[name] = "local"; }
            entry["origin"] = origins;
            if (entry.Count > 1) risks[(string)item["risk_id"]!] = entry;
        }
        return new JsonObject { ["basis"] = "legacy", ["risks"] = risks, ["activities"] = new JsonObject(), ["source"] = new JsonObject() };
    }

    /// <summary>_seal: model_checksum = SHA-256 of json.dumps(model, sort_keys=True, ensure_ascii=False); at most 8 MiB.</summary>
    public static JsonObject Seal(JsonObject data)
    {
        var serialized = Encoding.UTF8.GetBytes(PythonJson.Dumps(data));
        if (serialized.Length > 8 * 1024 * 1024) throw new ReportException(413, "Report model exceeds 8 MiB. Exclude appendices and export detailed CSV evidence separately.");
        data["model_checksum"] = Convert.ToHexStringLower(SHA256.HashData(serialized));
        return data;
    }

    // ---- the formal report model

    public sealed record ModelInputs(JsonObject Period, JsonObject Saved, string Checksum, bool V2, IReadOnlyDictionary<string, SodUserEntry> View, SodStates State, List<JsonObject> Actions,
        Func<string, string, string> Verify, JsonObject? Previous, string? LogoId);

    public static JsonObject Model(ModelInputs input, Options o)
    {
        var (period, saved) = (input.Period, input.Saved);
        var frozen = SodScope.FrozenStates.Contains(S(period["state"]));
        if (o.Status is "Approved" or "Externally signed" && !frozen) throw new ReportException(422, $"Only a frozen approved period can be labelled {o.Status}.");
        var approval = saved["approval"] as JsonObject ?? [];
        if (frozen && new[] { ("reviewer", o.Reviewer), ("approver", o.Approver) }.Any(p => p.Item2.Length > 0 && p.Item2 != S(approval[p.Item1])))
            throw new ReportException(422, "A report cannot override the recorded approval identity of an approved snapshot.");
        var findings = saved["analysis"]!["users"]!.AsArray().Select(f => f!.AsObject()).ToList();
        var legacyReviews = saved["reviews"]!["items"]!.AsArray().Select(r => r!.AsObject()).ToList();
        var risks = saved["risks"]!.AsArray().Select(r => r!.AsObject()).ToList();
        var appendices = o.IncludeAppendices && o.SectionList.Contains("appendices");
        var pathCount = findings.Sum(f => f["evidence"]!.AsObject().Sum(p => p.Value!.AsArray().Count));
        var mappingCount = risks.Sum(r => r["source"]!["activities"]!.AsObject().Sum(p => p.Value!.AsArray().Count));
        if (appendices && pathCount + findings.Count + risks.Count + mappingCount + legacyReviews.Count > MaxRows)
            throw new ReportException(413, "Detailed report exceeds 20,000 rows. Exclude appendices and use complete CSV exports for detailed evidence.");
        var (v2, state) = (input.V2, input.State);
        var actions = input.Actions;
        var (rows, summary) = v2 ? SodViews.RemediationRows(input.View, state, actions, input.Verify, o.ReportDate) : ([], new JsonObject());
        var items = v2 ? SodViews.QueueItems(input.View, state) : [];
        List<JsonObject> Kind(string k) => [.. items.Where(i => S(i["kind"]) == k)];
        var byRisk = Counter(findings.Select(f => S(f["risk_id"]))).ToList();
        var byCriticality = Counter(findings.Select(f => S(f["criticality"]))).ToList();
        var byCategory = Counter(findings.Select(f => S(f["risk"]?["business_category"]) is { Length: > 0 } c ? c : "Not specified")).ToList();
        var enabled = risks.Count(r => ((bool?)r["local"]?["enabled"] ?? false) && ((bool?)r["source"]?["supported"] ?? false));
        var report = o.ReportDate.ToString("yyyy-MM-dd", CultureInfo.InvariantCulture);
        var openActions = actions.Where(a => S(a["status"]) is "Open" or "In progress").ToList();
        var overdue = openActions.Where(a => S(a["due_date"]) is { Length: > 0 } d && string.CompareOrdinal(d, report) < 0).ToList();
        var untracked = rows.Where(r => S(r["recommended"]) == "Remove assignment" && r["action"] is null).Select(r => (S(r["user"]), S(r["assignment_id"]))).Distinct().Count();
        var built = new Dictionary<string, JsonObject>(StringComparer.Ordinal);
        void Section(string key, IEnumerable<string> paragraphs, params JsonArray[] tables)
        {
            if (!o.SectionList.Contains(key)) return;
            built[key] = new JsonObject
            {
                ["key"] = key, ["title"] = Headings[Array.IndexOf(Sections, key)], ["paragraphs"] = new JsonArray([.. paragraphs.Select(p => (JsonNode?)p)]),
                ["tables"] = new JsonArray([.. tables.Where(t => t.Count > 0).Select(t => (JsonNode?)t.DeepClone())]),
            };
        }
        static string N(int n) => n.ToString(CultureInfo.InvariantCulture);
        var usersEvaluated = (int)saved["source_counts"]!["users"]!;
        var userRisk = findings.Count;
        var subjects = findings.Select(f => S(f["subject"])).Distinct().Count();
        var pending = v2 ? new Dictionary<string, int>
        {
            ["activity"] = Count(state, "activity", "Pending", "Outdated"), ["assignment"] = Count(state, "assignment", "Pending", "Outdated", "Investigate"), ["acceptance"] = Count(state, "acceptance", "Pending", "Outdated"),
        } : [];
        var reviewItems = v2 ? new[] { "activity", "assignment", "acceptance" }.Sum(k => state.Items[k].Count) : 0;
        var openItems = v2 ? state.Coverage.Values.Sum(v => v.Values.Count(i => !((bool?)i["reviewed"] ?? false))) : 0;
        JsonArray metrics;
        List<string> lead;
        if (v2)
        {
            metrics = new JsonArray(Row("Measure", "Count", "Unit"), Row("SAP users evaluated", N(usersEvaluated), "users"), Row("Users with detected potential conflicts", N(subjects), "users"),
                Row("Detected potential conflicts", N(userRisk), "user-risk findings"), Row("Activities in review scope", N(state.Items["activity"].Count), "user-activity pairs"),
                Row("Activities approved", N(Count(state, "activity", "Approved")), "activities"), Row("Activities approved conditionally", N(Count(state, "activity", "Conditional")), "activities"),
                Row("Activities marked for removal", N(Count(state, "activity", "Removal required")), "activities"), Row("Activity reviews pending or outdated", N(pending["activity"]), "activities"),
                Row("Role assignments to keep", N(Count(state, "assignment", "Keep")), "assignments"), Row("Role assignments marked for removal", N(Count(state, "assignment", "Removal required")), "assignments"),
                Row("Role assignments under investigation", N(Count(state, "assignment", "Investigate")), "assignments"), Row("Risks accepted", N(Count(state, "acceptance", "Accepted")), "user-risk findings"),
                Row("Risks rejected", N(Count(state, "acceptance", "Rejected")), "user-risk findings"), Row("Risk decisions pending or outdated", N(pending["acceptance"]), "user-risk findings"),
                Row("Open remediation actions", N(openActions.Count), "actions"), Row("Overdue remediation actions", N(overdue.Count), "actions"),
                Row("Removal recommendations without a tracked action", N(untracked), "assignments"));
            lead =
            [
                "This report shows who holds SAP access that could let one person perform conflicting duties (segregation of duties) and how those findings were reviewed.",
                $"{subjects} of {usersEvaluated} evaluated SAP users have {userRisk} potential conflicts across {enabled} active risk rules.",
                $"Review progress: {reviewItems - openItems} of {reviewItems} review items have a recorded decision and {openItems} are still open. Review period status: {S(period["state"])}.",
                $"{openActions.Count} remediation actions are open, {overdue.Count} of them overdue. A proposed removal is not completed remediation.",
            ];
        }
        else
        {
            metrics = new JsonArray(Row("Measure", "Count", "Unit"), Row("SAP users evaluated", N(usersEvaluated), "users"), Row("Users with detected potential conflicts", N(subjects), "users"),
                Row("Detected potential conflicts", N(userRisk), "user-risk findings"));
            foreach (var (k, v) in saved["reviews"]!["summary"]!.AsObject()) metrics.Add(Row($"Legacy risk decisions: {k}", S(v), "findings"));
            lead = [$"{subjects} of {usersEvaluated} evaluated SAP users have {userRisk} detected potential conflicts.", "This period predates activity, role-assignment and risk-acceptance review; only legacy risk decisions are available."];
        }
        var meta = saved["source_metadata"] as JsonObject ?? [];
        Section("executive", [.. lead, StatusStatements[o.Status], Limitation], v2 ? [metrics, StatusTable(state)] : [metrics]);
        var policy = S(saved["analysis"]!["methodology"]!["policy"]);
        Section("methodology",
        [
            $"Evaluation date: {LocalizedDate(saved["evaluation_date"])}. Review period: {LocalizedDate(period["start"])} - {LocalizedDate(period["end"])}. Policy: {policy}.",
            "Method: potential conflicts are calculated from imported role and transaction evidence and the enabled risk rules. Reviewers decide whether each user needs a conflict-relevant activity, whether each active imported role assignment is necessary, and separately whether each remaining risk is accepted. Review decisions never change the calculation.",
            S(saved["limitation"]), "Unsupported and locally disabled risks are excluded; unknown assignment validity is not treated as active.",
        ], new JsonArray([.. Glossary.Select(r => (JsonNode?)Row(r))]), Table(Row("Scope", "Count"), saved["source_counts"]!.AsObject().Select(p => Row(p.Key, S(p.Value)))));
        var described = ForPeriod(saved);
        var scopeActivities = risks.SelectMany(r => r["source"]!["activities"]!.AsObject().SelectMany(p => p.Value!.AsArray())).Select(m => S(m!["activity"])).ToHashSet(StringComparer.Ordinal);
        var (riskTerms, activityTerms) = TermTables(described, byRisk.Select(p => p.Key), appendices ? scopeActivities : []);
        var termNotes = riskTerms.Count > 0 || activityTerms.Count > 0 ? new List<string> { DescriptionLegend, BasisNotes[S(described["basis"])] } : [];
        Section("risk_overview", ["Criticality codes come from the imported risk definitions and are shown as supplied; no additional severity rating is applied. Transaction codes are listed only in the technical appendices.",
                .. riskTerms.Count > 0 ? termNotes : []],
            Table(Row("Source criticality", "Findings"), byCriticality.Select(p => Row(p.Key, N(p.Value)))), Table(Row("Risk", "Potential findings"), byRisk.Select(p => Row(p.Key, N(p.Value)))),
            riskTerms, Table(Row("Business area", "Findings"), byCategory.Select(p => Row(p.Key, N(p.Value)))));
        var detailNote = appendices ? "Each decision with its reviewer, time and justification is listed in the technical appendices." : "Decision details are not included because the technical appendices are excluded.";
        List<JsonArray> controlRows;
        static string Ev(JsonObject item, string field) => S(item["event"]?[field]);
        if (v2)
        {
            JsonArray Lifecycles(string header, List<JsonObject> list) => Table(Row("Decision", header), Counter(list.Select(i => S(i["lifecycle"]))).Select(p => Row(p.Key, N(p.Value))));
            var (a, s, r) = (Kind("activity"), Kind("assignment"), Kind("acceptance"));
            Section("activity_results", ["Each user-activity pair is reviewed once and may contribute to several risks. " + detailNote], Lifecycles("Activities", a));
            Section("assignment_results", ["An approved activity does not mean every role assignment that supplies it is necessary. A removal decision is a recommendation, not confirmed removal in SAP. " + detailNote], Lifecycles("Assignments", s));
            Section("risk_acceptance", ["Risk acceptance is a separate business decision. Accepted risks remain detected conflicts. " + detailNote], Lifecycles("Risks", r));
            controlRows = [.. a.Concat(r).Where(i => i["event"] is JsonObject && Ev(i, "controls").Length > 0).Select(i => Row(S(i["user"]) + " / " + S(i["ref"]), Ev(i, "controls"), Ev(i, "reviewer")))];
        }
        else
        {
            Section("activity_results", ["Not recorded: this period predates activity review."]);
            Section("assignment_results", ["Not recorded: this period predates role-assignment review."]);
            static JsonObject Legacy(JsonObject row) => row["event"]?["annotation"] as JsonObject ?? [];
            Section("risk_acceptance", ["Legacy risk decisions are retained as recorded and were not converted to risk acceptance."],
                Table(Row("SAP user / risk", "Legacy decision", "Reviewer / rationale"), legacyReviews.Where(r => r["event"] is JsonObject).Select(r =>
                    Row(S(r["finding"]!["subject"]) + " / " + S(r["finding"]!["risk_id"]), S(r["decision"]), S(Legacy(r)["reviewer"]) + " / " + S(Legacy(r)["rationale"])))));
            controlRows = [.. legacyReviews.Where(r => S(Legacy(r)["mitigating_controls"]).Length > 0)
                .Select(r => Row(S(r["finding"]!["subject"]) + " / " + S(r["finding"]!["risk_id"]), S(Legacy(r)["mitigating_controls"]), S(Legacy(r)["reviewer"])))];
        }
        Section("controls", ["Controls are recorded by reviewers and are not independently verified by SAP Lens."], Table(Row("SAP user / risk or activity", "Controls or conditions", "Reviewer"), controlRows));
        static string Ref(JsonObject a) => S(a["user"]) + " / " + (S(a["activity"]) is { Length: > 0 } x ? x : S(a["risk_id"]) is { Length: > 0 } y ? y : S(a["role"]));
        if (v2)
            Section("outstanding",
            [
                $"{pending["activity"]} activity decisions, {pending["assignment"]} role assignment decisions and {pending["acceptance"]} risk decisions are not yet decided or are outdated because the evidence changed.",
                $"{openActions.Count} remediation actions are open, {overdue.Count} are overdue and {untracked} removal recommendations have no tracked action.",
            ], new JsonArray(Row("Open item", "Count"), Row("Activity decisions pending or outdated", N(pending["activity"])), Row("Role assignment decisions pending or outdated", N(pending["assignment"])),
                Row("Risk decisions pending or outdated", N(pending["acceptance"])), Row("Open remediation actions", N(openActions.Count)), Row("Overdue remediation actions", N(overdue.Count)),
                Row("Removal recommendations without a tracked action", N(untracked))),
                Table(Row("Overdue action", "Owner", "Due"), overdue.Select(a => Row(Ref(a), S(a["owner"]) is { Length: > 0 } w ? w : "—", LocalizedDate(a["due_date"])))));
        else Section("outstanding", ["Not recorded: this period predates activity, role-assignment and risk-acceptance review, so open items were not tracked."]);
        var overdueIds = overdue.Select(a => S(a["id"])).ToHashSet(StringComparer.Ordinal);
        var actionRows = actions.Where(a => S(a["status"]) != "Cancelled")
            .Select(a => Row(Ref(a), S(a["recommended"]), S(a["owner"]) is { Length: > 0 } w ? w : "—", LocalizedDate(a["due_date"]), S(a["status"]) + (overdueIds.Contains(S(a["id"])) ? " (overdue)" : ""))).ToList();
        Section("remediation", ["A manually completed action is not proof that access was removed. Only later source evidence can establish absence, subject to source completeness.", $"{untracked} removal recommendations have no tracked action."],
            v2 ? Table(Row("Recommended handling", "Rows"), SodViews.RemediationGroups.Select(k => Row(k, S(summary[k]) is { Length: > 0 } c ? c : "0"))) : [], v2 ? FollowupTable(rows) : [],
            Table(Row("User / reference", "Recommended", "Owner", "Due", "Status"), actionRows));
        var captured = DateOnly.ParseExact(S(saved["captured_at"])[..10], "yyyy-MM-dd", CultureInfo.InvariantCulture);
        var age = o.ReportDate.DayNumber - captured.DayNumber;
        var versions = saved["source_versions"] as JsonObject ?? [];
        Section("sources",
        [
            $"Evidence was captured {LocalizedStamp(saved["captured_at"])} UTC" + (age >= 0 ? $", {age} days before the report date." : ", after the report date.") + " Later changes in SAP are not reflected until the period is recaptured.",
            "Missing or incomplete sources are not evidence that no access or conflict exists.", Limitation, "Source versions and checksums are listed in the technical appendices.",
        ], Table(Row("Source", "Imported (UTC)", "Checked (UTC)"), versions.Select(p => Row(SourceNames.GetValueOrDefault(p.Key, p.Key), LocalizedStamp(meta[p.Key]?["imported_at"]), LocalizedStamp(meta[p.Key]?["checked_at"])))));
        var previous = input.Previous;
        if (previous is null) Section("changes", ["No previous review selected; change analysis was not calculated."]);
        else
        {
            var changed = previous["changed_risks"]!.AsArray().Select(r => S(r)).ToList();
            Section("changes", ["Missing records or changed coverage do not establish resolved access.",
                    $"Source coverage changed: {((bool)previous["source_coverage_changed"]! ? "True" : "False")}. Changed risk definitions: {(changed.Count > 0 ? string.Join(", ", changed) : "None")}."],
                Table(Row("Change classification", "Findings"), previous["summary"]!.AsObject().Select(p => Row(p.Key, S(p.Value)))));
        }
        Section("conclusion",
        [
            o.ManagementComments.Length > 0 ? o.ManagementComments : "No additional management comments recorded.",
            $"Recorded period approval: {(frozen ? "Yes" : "No")} ({S(period["state"])}). Report generation alone does not approve a review.", StatusStatements[o.Status],
            $"Reviewer: {(S(approval["reviewer"]) is { Length: > 0 } rv ? rv : o.Reviewer.Length > 0 ? o.Reviewer : "________________")} · {o.ReviewerRole}",
            $"Approver: {(S(approval["approver"]) is { Length: > 0 } ap ? ap : o.Approver.Length > 0 ? o.Approver : "________________")} · {o.ApproverRole}",
            $"Recorded approval date: {LocalizedDate(approval["date"])}", "Reviewer signature: ________________________    Date: ______________", "Approver signature: ________________________    Date: ______________", Limitation,
        ]);
        if (appendices)
        {
            var catalogue = new JsonArray(Row("Risk / source criticality / type", "Activities", "Business guidance / consequence / controls"));
            var transactions = new JsonArray(Row("Risk", "Activity slot / identifier", "Transaction", "Description"));
            foreach (var risk in risks)
            {
                var (source, local) = (risk["source"]!.AsObject(), risk["local"]!.AsObject());
                var guidance = string.Join('\n', new[] { "explanation", "consequence", "mitigating_controls", "review_guidance" }.Select(f => S(local[f + "_en"])));
                catalogue.Add(Row(S(risk["risk_id"]) + " / " + S(source["criticality"]) + " / " + S(source["risk_type"]) + " / " + ((bool?)local["enabled"] ?? false ? "Enabled" : "Disabled") + " / " + S(risk["description_review_status"]),
                    S(source["activity1"]) + " / " + S(source["activity2"]), guidance.Length > 0 ? guidance : S(source["source_text"])));
                foreach (var (slot, mappings) in source["activities"]!.AsObject())
                    foreach (var m in mappings!.AsArray()) transactions.Add(Row(S(risk["risk_id"]), slot + " / " + S(m!["activity"]), S(m["tcode"]), S(m["ttext"]) is { Length: > 0 } t ? t : "Not supplied"));
            }
            var evidence = new JsonArray(Row("SAP user / risk", "Side / T-code", "Assigned / catalogue role", "Single role / validity"));
            foreach (var f in findings)
                foreach (var (side, paths) in f["evidence"]!.AsObject())
                    foreach (var p in paths!.AsArray().Select(x => x!.AsObject()))
                        evidence.Add(Row(S(f["subject"]) + " / " + S(f["risk_id"]), side + " / " + S(p["tcode"]), S(p["actual_assigned_role"]) + "\n" + S(p["matched_catalogue_pattern"]) + " / " + S(p["matching_status"]),
                            S(p["single_role"]) + "\n" + LocalizedDate(p["role_valid_from"]) + " - " + LocalizedDate(p["role_valid_to"]) + "\n" + S(p["interval_status"]) + " / " + S(p["user_group"])));
            var decisionRows = new JsonArray(Row("Type", "SAP user / reference", "Decision", "Reviewer / approver / timestamp", "Justification / controls"));
            foreach (var i in items.Where(i => i["event"] is JsonObject))
                decisionRows.Add(Row(S(i["kind"]), S(i["user"]) + " / " + S(i["ref"]), S(i["lifecycle"]), Ev(i, "reviewer") + " / " + Ev(i, "approver") + " / " + LocalizedStamp(i["event"]!["timestamp"]),
                    Ev(i, "justification") + "\n" + Ev(i, "controls")));
            var remediationDetail = new JsonArray(Row("SAP user", "Activity / risks", "Role / assignment", "Recommended / owner / status", "Verification"));
            foreach (var r in rows)
                remediationDetail.Add(Row(S(r["user"]), S(r["activity"]) + " / " + string.Join(", ", r["risks"]!.AsArray().Select(S)), S(r["role"]) + "\n" + S(r["assignment_id"])[..12],
                    S(r["recommended"]) + " / " + (S(r["owner"]) is { Length: > 0 } w ? w : "—") + " / " + S(r["action_status"]), S(r["verification"])));
            var technical = new JsonArray(Row("Item", "Value"), Row("Snapshot SHA-256", input.Checksum), Row("Review period identifier", S(period["id"])), Row("Evaluation policy", policy),
                Row("Snapshot captured (UTC)", LocalizedStamp(saved["captured_at"])));
            foreach (var (k, v) in versions) technical.Add(Row("Source version: " + SourceNames.GetValueOrDefault(k, k), S(v)));
            foreach (var h in (period["history"] as JsonArray ?? []).Select(h => h!.AsObject()))
                technical.Add(Row("Period transition: " + S(h["to_state"]), LocalizedStamp(h["timestamp"]) + " / " + S(h["actor"]) + (S(h["note"]).Length > 0 ? " / " + S(h["note"]) : "")));
            Section("appendices", [$"Source capture: {LocalizedStamp(saved["captured_at"])} UTC. Methodology: {policy}.", Limitation, .. activityTerms.Count > 0 ? termNotes : []],
                catalogue, activityTerms, transactions, evidence, decisionRows.Count > 1 ? decisionRows : [], remediationDetail.Count > 1 ? remediationDetail : [], technical);
        }
        var sections = new JsonArray([.. Sections.Where(built.ContainsKey).Select(k => (JsonNode?)built[k])]);
        if (sections.Sum(s => s!["tables"]!.AsArray().Sum(t => t!.AsArray().Count)) > MaxRows)
            throw new ReportException(413, "Detailed report exceeds 20,000 rows. Exclude appendices and use complete CSV exports for detailed evidence.");
        return Seal(new JsonObject
        {
            ["version"] = 2, ["title"] = o.Title, ["language"] = "en", ["status"] = o.Status, ["status_statement"] = StatusStatements[o.Status], ["document_version"] = o.DocumentVersion,
            ["report_date"] = report, ["prepared_by"] = o.PreparedBy, ["period"] = period.DeepClone(), ["organization"] = saved["organization"]?.DeepClone(),
            ["logo_id"] = input.LogoId ?? (saved["logo_id"] is JsonValue lv ? lv.ToString() : null), ["snapshot_checksum"] = input.Checksum, ["sections"] = sections, ["limitation"] = Limitation,
        });
    }

    // ---- the remediation model

    public sealed record RemediationInputs(JsonObject Period, bool HasPeriod, string Snapshot, IReadOnlyDictionary<string, SodUserEntry> View, SodStates State, List<JsonObject> Actions,
        Func<string, string, string> Verify, JsonObject Described, JsonNode? Organization, string? LogoId);

    private static readonly string[] RowKeys = ["user", "activity", "risks", "role", "assignment_id", "valid_from", "valid_to", "activity_decision", "assignment_decision", "risk_acceptance", "recommended",
        "reason", "controls", "owner", "due_date", "action_status", "overdue", "verification"];

    public static JsonObject RemediationModel(RemediationInputs input, RemediationOptions o)
    {
        var (all, summary) = SodViews.RemediationRows(input.View, input.State, input.Actions, input.Verify, o.ReportDate, includePending: true);
        var rows = all.Where(r => o.Recommended.Contains(S(r["recommended"]))).ToList();
        if (rows.Count > MaxRows) throw new ReportException(413, "Remediation report exceeds 20,000 rows. Filter by recommended handling or use CSV.");
        var summaryTable = new JsonArray(Row("Recommended handling", "Rows"));
        foreach (var k in RemediationKeys) summaryTable.Add(Row(k, S(summary[k]) is { Length: > 0 } c ? c : "0"));
        summaryTable.Add(Row("Overdue tracked actions", S(summary["overdue"]) is { Length: > 0 } od ? od : "0"));
        var paragraphs = new List<string>
        {
            "This operational list shows what should happen to each access that is part of a detected conflict. A proposed removal is not completed remediation. Verification reflects source evidence only after a refresh and only when source coverage is complete.",
            Limitation,
        };
        if (input.Actions.Count == 0) paragraphs.Insert(1, "No remediation actions have been recorded for this scope. Rows below show what is recommended or still awaiting review; nothing here means access was removed.");
        var tables = new List<JsonArray> { summaryTable, StatusTable(input.State), FollowupTable(all) };
        var (riskTerms, activityTerms) = TermTables(input.Described, rows.SelectMany(r => r["risks"]!.AsArray().Select(S)), rows.Select(r => S(r["activity"])));
        if (riskTerms.Count > 0 || activityTerms.Count > 0)
        {
            paragraphs.AddRange([DescriptionLegend, BasisNotes[S(input.Described["basis"])]]);
            tables.AddRange([riskTerms, activityTerms]);
        }
        var sections = new JsonArray(new JsonObject
        {
            ["key"] = "summary", ["title"] = "Summary", ["paragraphs"] = new JsonArray([.. paragraphs.Select(p => (JsonNode?)p)]),
            ["tables"] = new JsonArray([.. tables.Where(t => t.Count > 0).Select(t => (JsonNode?)t)]),
        });
        foreach (var key in RemediationKeys.Where(o.Recommended.Contains))
        {
            var group = rows.Where(r => S(r["recommended"]) == key).ToList();
            var table = new JsonArray(Row("SAP user", "Activity / risks", "Role / validity", "Decisions", "Reason / controls", "Owner / due / status", "Verification"));
            foreach (var r in group)
                table.Add(Row(S(r["user"]), S(r["activity"]) + " / " + string.Join(", ", r["risks"]!.AsArray().Select(S)), S(r["role"]) + "\n" + LocalizedDate(r["valid_from"]) + " - " + LocalizedDate(r["valid_to"]),
                    $"Activity: {S(r["activity_decision"])}\nAssignment: {S(r["assignment_decision"])}\nRisk: {string.Join(", ", r["risk_acceptance"]!.AsArray().Select(S))}",
                    S(r["reason"]) is { Length: > 0 } reason ? reason : S(r["controls"]),
                    (S(r["owner"]) is { Length: > 0 } w ? w : "—") + " / " + LocalizedDate(r["due_date"]) + " / " + S(r["action_status"]) + ((bool)r["overdue"]! ? " (overdue)" : ""), S(r["verification"])));
            sections.Add(new JsonObject
            {
                ["key"] = key, ["title"] = key, ["paragraphs"] = new JsonArray($"{group.Count} rows."), ["tables"] = group.Count > 0 ? new JsonArray(table) : new JsonArray(),
            });
        }
        return Seal(new JsonObject
        {
            ["version"] = 2, ["kind"] = "remediation", ["title"] = o.Title, ["language"] = "en", ["status"] = "Draft", ["status_statement"] = StatusStatements["Draft"], ["document_version"] = o.DocumentVersion,
            ["report_date"] = o.ReportDate.ToString("yyyy-MM-dd", CultureInfo.InvariantCulture), ["prepared_by"] = o.PreparedBy, ["period"] = input.Period.DeepClone(),
            ["organization"] = input.Organization?.DeepClone(), ["logo_id"] = input.LogoId, ["snapshot_checksum"] = input.HasPeriod ? input.Snapshot : "live-evidence", ["sections"] = sections,
            ["limitation"] = Limitation,
            ["rows"] = new JsonArray([.. rows.Select(r => { var copy = new JsonObject(); foreach (var k in RowKeys) copy[k] = r[k]?.DeepClone(); return (JsonNode?)copy; })]),
        });
    }

    // ---- gathering inputs from storage (sod_reports.model / remediation_model)

    private static T Service<T>(IServiceProvider s) where T : notnull => s.GetRequiredService<T>();

    private static async Task<string?> CurrentReportLogoAsync(IServiceProvider services, CancellationToken ct) =>
        await V1Branding.CurrentReportLogoAsync(Service<IDbContextFactory<AuthLensDb>>(services), Service<LogoStore>(services), ct);

    public static async Task<JsonObject> BuildModelAsync(IServiceProvider services, string periodId, Options o, CancellationToken ct)
    {
        var details = await SodPeriods.DetailsAsync(services, periodId, ct);
        JsonObject? previous = null;
        if (o.PreviousPeriodId is { } previousId)
        {
            var previousDetails = await SodPeriods.DetailsAsync(services, previousId, ct);
            if (!SodScope.FrozenStates.Contains(S(previousDetails["period"]!["state"]))) throw new ReportException(422, "Choose an approved previous period for reproducible report comparison.");
            previous = await SodPeriods.CompareAsync(services, previousId, periodId, ct);
        }
        var b = await SodScope.LoadAsync(services, periodId, "active", null, ct);
        var view = SodScope.ReviewModel(b);
        var state = await SodScope.StatesAsync(services, b, view, ct);
        var actions = await SodScope.ActionsAsync(services, b, ct);
        Func<string, string, string> verify;
        if (b.FrozenDecisions is not null) { var frozen = b.FrozenDecisions["verification"] as JsonObject ?? []; verify = (_, aid) => S(frozen[aid]) is { Length: > 0 } v ? v : "Not assessed at approval"; }
        else verify = (await SodScope.VerifierAsync(services, null, ct)).Verify;
        return Model(new ModelInputs(details["period"]!.AsObject(), details["snapshot"]!.AsObject(), S(details["checksum"]), (int)details["model"]! == 2, view, state, actions, verify, previous,
            await CurrentReportLogoAsync(services, ct)), o);
    }

    public static async Task<JsonObject> BuildRemediationAsync(IServiceProvider services, string context, RemediationOptions o, CancellationToken ct)
    {
        var b = await SodScope.LoadAsync(services, context, "active", null, ct);
        var view = SodScope.ReviewModel(b);
        var state = await SodScope.StatesAsync(services, b, view, ct);
        var actions = await SodScope.ActionsAsync(services, b, ct);
        Func<string, string, string> verify;
        if (b.FrozenDecisions is not null) { var frozen = b.FrozenDecisions["verification"] as JsonObject ?? []; verify = (_, aid) => S(frozen[aid]) is { Length: > 0 } v ? v : "Not assessed at approval"; }
        else verify = (await SodScope.VerifierAsync(services, null, ct)).Verify;
        var settings = await Service<V1Settings>(services).GetAsync(ct);
        JsonObject described;
        if (b.Period is not null) described = ForPeriod((await SodPeriods.DetailsAsync(services, context, ct))["snapshot"]!.AsObject());
        else
        {
            var lookup = V1SodCatalogue.Lookup(await V1SodCatalogue.ContextAsync(services, ct));
            described = new JsonObject { ["basis"] = "current", ["risks"] = lookup["risks"]!.DeepClone(), ["activities"] = lookup["activities"]!.DeepClone() };
        }
        var period = b.Period ?? new JsonObject { ["id"] = "current", ["name"] = "Current evidence", ["start"] = b.AsOf, ["end"] = b.AsOf, ["state"] = "Current", ["history"] = new JsonArray() };
        return RemediationModel(new RemediationInputs(period, b.Period is not null, b.Generation, view, state, actions, verify, described, settings["organization"],
            await CurrentReportLogoAsync(services, ct) ?? (settings["logo_id"] is JsonValue lv ? lv.ToString() : null)), o);
    }

    /// <summary>report_logo: the frozen logo; a referenced logo that is missing or altered stops the export (409) rather than silently dropping it.</summary>
    private static byte[]? Logo(IServiceProvider services, JsonObject model)
    {
        var id = S(model["logo_id"]);
        if (id.Length == 0) return null;
        return Service<LogoStore>(services).Read(id) ?? throw new ReportException(409, "The frozen report logo is unavailable or invalid. Restore its private branding backup before exporting.");
    }

    private static byte[] Render(IServiceProvider services, JsonObject model, string kind)
    {
        IReportRenderer renderer = kind == "pdf" ? new PdfReportRenderer() : new DocxReportRenderer();
        try { return ReportText.Render(renderer, model, Logo(services, model)); }
        catch (ReportRenderException error) { throw new ReportException(error.Status, error.Message); }
    }

    /// <summary>log_report: an immutable report log entry attributed to the preparer (an authenticated identity where one exists).</summary>
    private static async Task LogAsync(HttpContext http, string periodId, string kind, JsonObject model, string? previous, CancellationToken ct)
    {
        var actor = Actors.Current(http);
        var entry = new JsonObject();
        string prepared;
        if (actor.Provenance is "server-session" or "desktop")
        {
            var (name, identity, _) = await V1SodDecisions.AttributionAsync(http, ct);
            prepared = name ?? S(model["prepared_by"]);
            if (identity is not null) entry["actor_identity"] = identity.DeepClone();
        }
        else prepared = S(model["prepared_by"]);   // a shared token identifies nobody: the typed preparer is recorded as self-reported text only
        entry["id"] = Guid.NewGuid().ToString("N"); entry["period_id"] = periodId; entry["kind"] = kind; entry["title"] = model["title"]!.DeepClone(); entry["status"] = model["status"]!.DeepClone();
        entry["document_version"] = model["document_version"]!.DeepClone(); entry["model_checksum"] = model["model_checksum"]!.DeepClone(); entry["previous_period_id"] = previous;
        entry["timestamp"] = SodDecisionStore.Stamp(Service<TimeProvider>(http.RequestServices).GetUtcNow()); entry["prepared_by"] = prepared.Length > 120 ? prepared[..120] : prepared;
        await Service<SodDecisionStore>(http.RequestServices).LogReportAsync(entry, ct);
    }

    private static async Task<IResult> Guard(Func<Task<IResult>> handler)
    {
        try { return await handler(); }
        catch (ReportException error) { return SodScope.Problem(error.Status, error.Message); }
        catch (SodDecisionException error) { return SodScope.Problem(error.Status, error.Message); }
    }

    private static (string PeriodId, string? Expected, JsonNode? Options, IResult? Error) RequestBody(JsonObject body, bool remediation)
    {
        var errors = new List<object>();
        V1Validation.Extra(body, remediation ? ["context", "expected_model", "options"] : ["period_id", "expected_model", "options"], errors);
        var id = remediation ? (body["context"] is JsonValue cv && cv.TryGetValue<string>(out var c) ? c : "current") : V1Validation.Text(body, "period_id", 32, 32, true, errors) ?? "";
        if (remediation ? !SodDecisionStore.ContextPattern().IsMatch(id) : !Regex.IsMatch(id, "^[a-f0-9]{32}$"))
            errors.Add(V1Validation.Error("string_pattern_mismatch", remediation ? "context" : "period_id", "Choose a valid review context."));
        var expected = body["expected_model"] is JsonValue ev && ev.TryGetValue<string>(out var e) ? e : null;
        if (expected is not null && !Regex.IsMatch(expected, "^[a-f0-9]{64}$")) errors.Add(V1Validation.Error("string_pattern_mismatch", "expected_model", "String should match pattern '^[a-f0-9]{64}$'"));
        return (id, expected, body["options"], errors.Count > 0 ? Results.Json(new { detail = errors }, statusCode: 422) : null);
    }

    private static IResult File(HttpContext http, byte[] payload, string kind, string name, Dictionary<string, string> headers)
    {
        http.Response.Headers["Content-Disposition"] = $"attachment; filename=\"{name}\"";
        http.Response.Headers.CacheControl = "no-store";
        foreach (var (k, v) in headers) http.Response.Headers[k] = v;
        return Results.Bytes(payload, kind == "pdf" ? "application/pdf" : "application/vnd.openxmlformats-officedocument.wordprocessingml.document");
    }

    public static void Map(RouteGroupBuilder api)
    {
        api.MapPost("/sod/reports/preview", (HttpContext http, CancellationToken ct) => Guard(async () =>
        {
            var (raw, invalid) = await V1Validation.ReadBody(http, ct);
            if (invalid is not null) return invalid;
            var (id, _, node, error) = RequestBody(raw!, false);
            if (error is not null) return error;
            var (options, errors) = ParseOptions(node);
            if (options is null) return Results.Json(new { detail = errors }, statusCode: 422);
            return Results.Content((await BuildModelAsync(http.RequestServices, id, options, ct)).ToJsonString(), "application/json");
        }));
        api.MapPost("/sod/reports/remediation/preview", (HttpContext http, CancellationToken ct) => Guard(async () =>
        {
            var (raw, invalid) = await V1Validation.ReadBody(http, ct);
            if (invalid is not null) return invalid;
            var (context, _, node, error) = RequestBody(raw!, true);
            if (error is not null) return error;
            var (options, errors) = ParseRemediationOptions(node);
            if (options is null) return Results.Json(new { detail = errors }, statusCode: 422);
            var model = await BuildRemediationAsync(http.RequestServices, context, options, ct);
            var count = model["rows"]!.AsArray().Count;
            model.Remove("rows");
            model["row_count"] = count;
            return Results.Content(model.ToJsonString(), "application/json");
        }));
        api.MapPost("/sod/reports/remediation/{kind}", (string kind, HttpContext http, CancellationToken ct) => Guard(async () =>
        {
            if (kind is not ("csv" or "docx" or "pdf")) return SodScope.Problem(422, "Choose CSV, DOCX or PDF.");
            var (raw, invalid) = await V1Validation.ReadBody(http, ct);
            if (invalid is not null) return invalid;
            var (context, expected, node, error) = RequestBody(raw!, true);
            if (error is not null) return error;
            var (options, errors) = ParseRemediationOptions(node);
            if (options is null) return Results.Json(new { detail = errors }, statusCode: 422);
            var model = await BuildRemediationAsync(http.RequestServices, context, options, ct);
            if (expected is not null && expected != S(model["model_checksum"])) throw new ReportException(409, "Remediation evidence changed. Preview again before exporting.");
            var payload = kind == "csv" ? null : Render(http.RequestServices, model, kind);
            if (context != "current") await LogAsync(http, context, "remediation-" + kind, model, null, ct);
            if (kind == "csv")
            {
                var csv = new StringBuilder("\ufeff");
                V1Csv.Line(csv, V1SodGovernance.RemediationColumns, cells: false);
                foreach (var row in V1SodGovernance.RemediationCsv(model["rows"]!.AsArray().Select(r => r!.AsObject()))) V1Csv.Line(csv, row, cells: true);
                http.Response.Headers["Content-Disposition"] = $"attachment; filename=\"sap-lens-sod-access-remediation-{DateTime.Now:yyyy-MM-dd}.csv\"";
                http.Response.Headers.CacheControl = "no-store";
                http.Response.Headers["X-SAP-Lens-Model"] = S(model["model_checksum"]);
                return Results.Text(csv.ToString(), "text/csv; charset=utf-8");
            }
            return File(http, payload!, kind, $"sap-lens-access-remediation-{context}-{S(model["report_date"])}.{kind}", new() { ["X-SAP-Lens-Model"] = S(model["model_checksum"]) });
        }));
        api.MapPost("/sod/reports/{kind}", (string kind, HttpContext http, CancellationToken ct) => Guard(async () =>
        {
            if (kind is not ("docx" or "pdf")) return SodScope.Problem(422, "Choose DOCX or PDF.");
            var (raw, invalid) = await V1Validation.ReadBody(http, ct);
            if (invalid is not null) return invalid;
            var (id, expected, node, error) = RequestBody(raw!, false);
            if (error is not null) return error;
            var (options, errors) = ParseOptions(node);
            if (options is null) return Results.Json(new { detail = errors }, statusCode: 422);
            var model = await BuildModelAsync(http.RequestServices, id, options, ct);
            if (expected is not null && expected != S(model["model_checksum"])) throw new ReportException(409, "Report evidence changed. Preview the current snapshot before exporting.");
            var payload = Render(http.RequestServices, model, kind);
            await LogAsync(http, id, kind, model, options.PreviousPeriodId, ct);
            return File(http, payload, kind, $"sap-lens-sod-report-{S(model["period"]!["id"])}-{S(model["report_date"])}.{kind}", new()
            {
                ["X-SAP-Lens-Snapshot"] = S(model["snapshot_checksum"]), ["X-SAP-Lens-Report-Model"] = S(model["model_checksum"]),
                ["X-SAP-Lens-File-SHA256"] = Convert.ToHexStringLower(SHA256.HashData(payload)),
            });
        }));
    }
}
