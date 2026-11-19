using System.Globalization;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;
using Microsoft.EntityFrameworkCore;
using AuthLens.Persistence;

namespace AuthLens.Api;

/// <summary>An HTTP refusal with v1's status and detail text (FastAPI HTTPException).</summary>
public sealed class V1Problem(int status, object detail) : Exception(detail as string ?? "request refused")
{
    public int Status { get; } = status;
    public object Detail { get; } = detail;
    public IResult ToResult() => Results.Json(new { detail = Detail }, statusCode: Status);
}

/// <summary>MIG-004, port of functional_groups.py: the business function a person performs, maintained locally by reviewers. One JSON document (format 2,
/// v1's `functional-groups.json` shape, kept in SQLite) holds the catalogue, the memberships of each canonical SAP user, an append-only history and the
/// advisory suggestion rules. Independent of Directory Department, Job Title and SAP User Group; nothing here changes SAP access. Format 1 documents (one
/// group per user) are accepted and migrated on read.</summary>
public sealed partial class FunctionalGroupStore(IDbContextFactory<AuthLensDb> factory, WriteCoordinator writer, TimeProvider clock)
{
    public const string Document = "functional-groups";
    public const int Format = 2, LegacyFormat = 1, MaxGroups = 500, MaxHistory = 50000, MaxHandled = 200, MaxBytes = 20 * 1024 * 1024, MaxCatalogueEvents = 10000;
    public static readonly string[] Statuses = ["Unassigned", "Confirmed", "Needs review"];
    private static readonly string[] GroupStates = ["active", "archived"];
    private static readonly string[] Events = ["assigned", "changed", "confirmed", "removed", "review_required", "reconfirmed", "manager_changed"];
    /// <summary>Catalogue audit trail (`catalogue_events`): group lifecycle actions with actor and time. A `deleted` event is also the tombstone that keeps
    /// the deleted group's identity and name resolvable for the classification history that still references it.</summary>
    private static readonly string[] CatalogueEvents = ["archived", "restored", "deleted"];
    private readonly SemaphoreSlim _lock = new(1, 1);

    [GeneratedRegex("^fg_[a-f0-9]{12}$")] public static partial Regex GroupId();
    [GeneratedRegex("^[a-f0-9]{64}$")] private static partial Regex Hex64();
    [GeneratedRegex(@"\s+")] private static partial Regex Spaces();

    public string Now() => clock.GetUtcNow().UtcDateTime.ToString("yyyy-MM-dd'T'HH:mm:ss.ffffff'+00:00'", CultureInfo.InvariantCulture);

    /// <summary>json.dumps(value, ensure_ascii=False) of a string, so identities equal v1's.</summary>
    private static string PythonJson(string value)
    {
        var text = new StringBuilder("\"");
        foreach (var c in value)
            text.Append(c switch
            {
                '"' => "\\\"", '\\' => "\\\\", '\n' => "\\n", '\r' => "\\r", '\t' => "\\t", '\b' => "\\b", '\f' => "\\f",
                < ' ' => $"\\u{(int)c:x4}", _ => c.ToString(),
            });
        return text.Append('"').ToString();
    }

    /// <summary>The canonical identity shared with Account Review decisions: sha256 of the upper-cased SAP user name as JSON.</summary>
    public static string UserKey(string username) => Convert.ToHexStringLower(SHA256.HashData(Encoding.UTF8.GetBytes(PythonJson(username.Trim().PyUpper()))));

    /// <summary>position_changes.normalize_text: NFKC, collapsed whitespace, trimmed, case-folded.</summary>
    public static string NormalizeText(string? value) => AuthLens.Domain.Directory.PositionChanges.NormalizeText(value);

    /// <summary>str.casefold for names and Directory text: case-insensitive, with the German sharp s folded to "ss" as Python does.</summary>
    public static string Fold(string value) => AuthLens.Domain.Text.PythonText.Casefold(value);

    public static JsonObject Empty() => new() { ["format"] = Format, ["groups"] = new JsonObject(), ["users"] = new JsonObject(), ["history"] = new JsonArray(), ["rules"] = new JsonArray() };

    /// <summary>Group ids of deleted groups (their `deleted` catalogue events) with the name they had.</summary>
    public static Dictionary<string, string> DeletedGroups(JsonObject data) =>
        (data["catalogue_events"] as JsonArray ?? []).OfType<JsonObject>().Where(e => (string?)e["event"] == "deleted")
            .ToDictionary(e => (string)e["group_id"]!, e => (string)e["group_name"]!);

    // --- persistence ---------------------------------------------------------------------------------------------------------

    public async Task<JsonObject> ReadAsync(CancellationToken ct)
    {
        await using var db = await factory.CreateDbContextAsync(ct);
        var row = await db.SodDocuments.AsNoTracking().FirstOrDefaultAsync(d => d.Name == Document, ct);
        return Parse(row?.Json);
    }

    private static JsonObject Parse(string? json)
    {
        if (json is null) return Empty();
        try
        {
            if (Encoding.UTF8.GetByteCount(json) > MaxBytes) throw new FormatException("size");
            return Validate(JsonNode.Parse(json));
        }
        catch (Exception error) when (error is FormatException or System.Text.Json.JsonException or InvalidOperationException or KeyNotFoundException or ArgumentException)
        { throw new V1Problem(409, "Functional Group storage could not be read. The original file is retained; review local application storage before recovery."); }
    }

    /// <summary>One read-modify-write under the store lock; <paramref name="change"/> returns whether to save.</summary>
    public async Task<T> UpdateAsync<T>(Func<JsonObject, (T Result, bool Save)> change, string actor, CancellationToken ct)
    {
        await _lock.WaitAsync(ct);
        try
        {
            var data = await ReadAsync(ct);
            var (result, save) = change(data);
            if (!save) return result;
            string json;
            try { json = Validate(data).ToJsonString(); }
            catch (FormatException) { throw new V1Problem(409, "Functional Group data could not be saved. Previous data is retained."); }
            if (Encoding.UTF8.GetByteCount(json) > MaxBytes) throw new V1Problem(409, "Functional Group storage is full. Existing data is retained.");
            await writer.WriteAsync(async (db, token) =>
            {
                var row = await db.SodDocuments.FirstOrDefaultAsync(d => d.Name == Document, token);
                if (row is null) db.SodDocuments.Add(row = new SodDocument { Name = Document, Json = "{}" });
                (row.Json, row.Revision, row.UpdatedUtc, row.UpdatedBy) = (json, row.Revision + 1, clock.GetUtcNow().UtcDateTime, actor);
            }, ct);
            return result;
        }
        finally { _lock.Release(); }
    }

    // --- persisted contract (validate_storage) ---------------------------------------------------------------------------------

    private static void Require(bool condition, string what) { if (!condition) throw new FormatException(what); }
    private static void Stamp(JsonNode? node, string what) { if (node is not null && (string?)node is { Length: > 0 } text) Require(DateTimeOffset.TryParse(text, CultureInfo.InvariantCulture, DateTimeStyles.None, out _), what); }
    private static bool IsText(JsonNode? node, int max) => node is null || node is JsonValue v && v.TryGetValue<string>(out var s) && s.Length <= max;

    /// <summary>validate_storage: format 2, or format 1 returned migrated. Throws FormatException.</summary>
    public static JsonObject Validate(JsonNode? node)
    {
        Require(node is JsonObject, "format");
        var data = node!.AsObject();
        if ((int?)data["format"] == LegacyFormat) { ValidateCatalogue(data); ValidateLegacyUsers(data); return MigrateLegacy(data); }
        Require((int?)data["format"] == Format, "format");
        ValidateCatalogue(data);
        foreach (var rule in data["rules"]!.AsArray())
            Require((string?)rule!["department_mode"] is null or "contains" or "equals" && ((string?)rule["department"] is { Length: > 0 } || (string?)rule["title_contains"] is { Length: > 0 }), "rule");
        var groups = data["groups"]!.AsObject();
        foreach (var (key, value) in data["users"]!.AsObject())
        {
            Require(Hex64().IsMatch(key) && value is JsonObject && (string?)value["username"] is { } name && UserKey(name) == key, "user identity");
            Require(value!["revision"] is JsonValue r && r.TryGetValue<int>(out var revision) && revision >= 1, "revision");
            Stamp(value["updated_at"], "updated_at");
            Require(value["handled"] is null || value["handled"] is JsonArray { Count: <= MaxHandled }, "handled");
            Require(value["memberships"] is JsonObject { Count: <= MaxGroups }, "memberships");
            foreach (var (gid, member) in value["memberships"]!.AsObject())
            {
                Require(groups.ContainsKey(gid) && member is JsonObject && (string?)member["status"] is "Confirmed" or "Needs review", "membership");
                Require(IsText(member!["confirmed_by"], 2000) && IsText(member["rationale"], 2000), "membership text");
                Stamp(member["confirmed_at"], "confirmed_at"); Stamp(member["updated_at"], "updated_at");
                var review = member["review"];
                Require(((string?)member["status"] == "Needs review") == (review is not null) && (review is null || review is JsonObject && review["change_id"] is JsonValue), "review");
            }
        }
        return data;
    }

    private static void ValidateCatalogue(JsonObject data)
    {
        Require(data["groups"] is JsonObject && data["users"] is JsonObject && data["history"] is JsonArray, "shape");
        data["rules"] ??= new JsonArray();
        // Optional, so that a store without lifecycle events keeps v1's exact shape (it is created with the first event).
        Require(data["rules"] is JsonArray && data["catalogue_events"] is null or JsonArray { Count: <= MaxCatalogueEvents }, "shape");
        var groups = data["groups"]!.AsObject();
        var deleted = new HashSet<string>();
        var eventIds = new HashSet<string>();
        foreach (var item in data["catalogue_events"] as JsonArray ?? [])
        {
            Require(item is JsonObject && CatalogueEvents.Contains((string?)item["event"]) && eventIds.Add((string?)item["id"] ?? "") && GroupId().IsMatch((string?)item["group_id"] ?? ""), "catalogue event");
            Require((string?)item!["group_name"] is { Length: > 0 and <= 80 } && item["actor"] is JsonValue a && a.TryGetValue<string>(out _), "catalogue event");
            Require(item["timestamp"] is not null, "catalogue event timestamp"); Stamp(item["timestamp"], "catalogue event timestamp");
            if ((string?)item["event"] == "deleted") Require(deleted.Add((string)item["group_id"]!), "catalogue event");
        }
        Require(groups.Count <= MaxGroups && data["history"]!.AsArray().Count <= MaxHistory, "size");
        var names = new HashSet<string>();
        foreach (var (gid, group) in groups)
        {
            Require(GroupId().IsMatch(gid) && group is JsonObject && (string?)group["id"] == gid, "group id");
            var name = (string?)group!["name"];
            Require(name is { Length: > 0 and <= 80 } && name.Trim().Length > 0 && GroupStates.Contains((string?)group["status"]), "group");
            Require(IsText(group["description"], 500), "description");
            Require(names.Add(NormalizeText(name)), "duplicate group name");
            Stamp(group["created"], "created"); Stamp(group["modified"], "modified");
            Require(group["created"] is not null && group["modified"] is not null, "group stamps");
        }
        var seen = new HashSet<string>();
        foreach (var item in data["history"]!.AsArray())
        {
            Require(item is JsonObject && Events.Contains((string?)item["event"]) && seen.Add((string?)item["id"] ?? "") && Hex64().IsMatch((string?)item["user_key"] ?? ""), "history");
            Stamp(item!["timestamp"], "history timestamp");
            foreach (var side in new[] { "previous_group", "new_group" })
                Require(item[side] is null || groups.ContainsKey((string)item[side]!) || deleted.Contains((string)item[side]!), "history group reference");
            Require(Statuses.Contains((string?)item["previous_status"]) && Statuses.Contains((string?)item["new_status"]), "history status");
            Require(item["actor"] is JsonValue a && a.TryGetValue<string>(out _) && IsText(item["reason"], 2000), "history actor");
        }
        foreach (var rule in data["rules"]!.AsArray()) Require(rule is JsonObject && groups.ContainsKey((string?)rule["group_id"] ?? ""), "rule group reference");
        foreach (var gid in deleted) Require(!groups.ContainsKey(gid), "deleted group still present");
    }

    private static void ValidateLegacyUsers(JsonObject data)
    {
        var groups = data["groups"]!.AsObject();
        foreach (var (key, user) in data["users"]!.AsObject())
        {
            Require(Hex64().IsMatch(key) && user is JsonObject && Statuses.Contains((string?)user["status"]), "user");
            Require((string?)user!["username"] is { } name && UserKey(name) == key, "user identity");
            var gid = (string?)user["group_id"];
            Require(gid is null || groups.ContainsKey(gid), "missing group reference");
            Require(((string?)user["status"] == "Unassigned") == (gid is null), "status contradicts group");
            Require(user["revision"] is JsonValue r && r.TryGetValue<int>(out var revision) && revision >= 1, "revision");
            Require(IsText(user["confirmed_by"], 2000) && IsText(user["rationale"], 2000), "text");
            Stamp(user["confirmed_at"], "confirmed_at"); Stamp(user["updated_at"], "updated_at");
            var review = user["review"];
            Require(review is null || (string?)user["status"] == "Needs review" && review is JsonObject && review["change_id"] is JsonValue, "review");
            Require((string?)user["status"] != "Needs review" || review is not null, "review");
            Require(user["handled"] is null || user["handled"] is JsonArray { Count: <= MaxHandled }, "handled");
        }
    }

    /// <summary>migrate_v1: every legacy assignment becomes one membership with its status, confirmation and review; legacy rules keep equality matching.</summary>
    private static JsonObject MigrateLegacy(JsonObject data)
    {
        var users = new JsonObject();
        foreach (var (key, user) in data["users"]!.AsObject())
        {
            var memberships = new JsonObject();
            if ((string?)user!["group_id"] is { Length: > 0 } gid)
                memberships[gid] = new JsonObject
                {
                    ["status"] = user["status"]!.DeepClone(), ["confirmed_at"] = (string?)user["confirmed_at"] is { Length: > 0 } c ? c : null,
                    ["confirmed_by"] = (string?)user["confirmed_by"] ?? "", ["rationale"] = (string?)user["rationale"] ?? "", ["review"] = user["review"]?.DeepClone(),
                    ["updated_at"] = (string?)user["updated_at"] is { Length: > 0 } u ? u : user["confirmed_at"]?.DeepClone(),
                };
            users[key] = new JsonObject
            {
                ["username"] = user["username"]!.DeepClone(), ["revision"] = user["revision"]!.DeepClone(), ["updated_at"] = user["updated_at"]?.DeepClone(),
                ["handled"] = user["handled"]?.DeepClone() ?? new JsonArray(), ["memberships"] = memberships,
            };
        }
        var migrated = data.DeepClone().AsObject();
        migrated["format"] = Format;
        migrated["users"] = users;
        foreach (var rule in migrated["rules"]!.AsArray().OfType<JsonObject>()) rule["department_mode"] = (string?)rule["department_mode"] is { Length: > 0 } mode ? mode : "equals";
        return migrated;
    }

    // --- catalogue ---------------------------------------------------------------------------------------------------------------

    private static string CleanName(string? name)
    {
        name = Spaces().Replace((name ?? "").Trim(), " ");
        if (name.Length == 0 || name.Length > 80 || name.Any(c => c < ' ')) throw new V1Problem(422, "Use a Functional Group name of 1 to 80 readable characters.");
        return name;
    }

    private static void EnsureUnique(JsonObject data, string name, string? ignore = null)
    {
        if (data["groups"]!.AsObject().Any(p => p.Key != ignore && NormalizeText((string?)p.Value!["name"]) == NormalizeText(name)))
            throw new V1Problem(409, $"A Functional Group named \"{name}\" already exists.");
    }

    public static Dictionary<string, int> Counts(JsonObject data)
    {
        var result = new Dictionary<string, int>();
        foreach (var (_, user) in data["users"]!.AsObject())
            foreach (var (gid, _) in user!["memberships"]!.AsObject()) result[gid] = result.GetValueOrDefault(gid) + 1;
        return result;
    }

    public static Dictionary<string, (int Members, int Rules, int History)> References(JsonObject data)
    {
        var result = data["groups"]!.AsObject().ToDictionary(p => p.Key, _ => (Members: 0, Rules: 0, History: 0));
        foreach (var (gid, count) in Counts(data)) result[gid] = result[gid] with { Members = count };
        foreach (var rule in data["rules"]!.AsArray()) { var gid = (string)rule!["group_id"]!; result[gid] = result[gid] with { Rules = result[gid].Rules + 1 }; }
        foreach (var item in data["history"]!.AsArray())
            foreach (var gid in new[] { (string?)item!["previous_group"], (string?)item["new_group"] }.Where(g => g is not null && result.ContainsKey(g)).Distinct())
                result[gid!] = result[gid!] with { History = result[gid!].History + 1 };
        return result;
    }

    public static List<JsonObject> ListGroups(JsonObject data, bool includeArchived = true)
    {
        var used = References(data);
        return data["groups"]!.AsObject().Select(p => p.Value!.AsObject())
            .Where(g => includeArchived || (string?)g["status"] == "active")
            .OrderBy(g => (string?)g["status"] != "active").ThenBy(g => NormalizeText((string?)g["name"]), StringComparer.Ordinal).ThenBy(g => (string?)g["id"], StringComparer.Ordinal)
            .Select(g =>
            {
                var r = used[(string)g["id"]!];
                var item = g.DeepClone().AsObject();
                item["user_count"] = r.Members;
                item["references"] = new JsonObject { ["members"] = r.Members, ["rules"] = r.Rules, ["history"] = r.History };
                item["deletable"] = (string?)g["status"] == "archived";
                return item;
            }).ToList();
    }

    public Task<JsonObject> CreateGroupAsync(string name, string description, string actor, CancellationToken ct)
    {
        name = CleanName(name);
        return UpdateAsync(data =>
        {
            var groups = data["groups"]!.AsObject();
            if (groups.Count >= MaxGroups) throw new V1Problem(409, "The maximum number of Functional Groups is reached.");
            EnsureUnique(data, name);
            var stamp = Now();
            var gid = "fg_" + Convert.ToHexStringLower(RandomNumberGenerator.GetBytes(6));
            groups[gid] = new JsonObject { ["id"] = gid, ["name"] = name, ["description"] = Trunc(description.Trim(), 500), ["status"] = "active", ["created"] = stamp, ["modified"] = stamp };
            return (groups[gid]!.DeepClone().AsObject(), true);
        }, actor, ct);
    }

    private static string Trunc(string text, int max) => text.Length > max ? text[..max] : text;

    private static JsonObject Group(JsonObject data, string gid) =>
        data["groups"]![gid] as JsonObject ?? throw new V1Problem(404, "Functional Group not found.");

    public Task<JsonObject> UpdateGroupAsync(string gid, string? name, string? description, string actor, CancellationToken ct) => UpdateAsync(data =>
    {
        var group = Group(data, gid);
        if (name is not null) { name = CleanName(name); EnsureUnique(data, name, gid); group["name"] = name; }
        if (description is not null) group["description"] = Trunc(description.Trim(), 500);
        group["modified"] = Now();
        return (group.DeepClone().AsObject(), true);
    }, actor, ct);

    public Task<JsonObject> SetStatusAsync(string gid, string status, string actor, CancellationToken ct) => UpdateAsync(data =>
    {
        var group = Group(data, gid);
        if ((string?)group["status"] == status) return (group.DeepClone().AsObject(), false);
        group["status"] = status; group["modified"] = Now();
        CatalogueEvent(data, status == "archived" ? "archived" : "restored", gid, (string)group["name"]!, actor, Counts(data).GetValueOrDefault(gid), 0);
        return (group.DeepClone().AsObject(), true);
    }, actor, ct);

    private void CatalogueEvent(JsonObject data, string kind, string gid, string name, string actor, int members, int rules)
    {
        if (data["catalogue_events"] is not JsonArray events) data["catalogue_events"] = events = [];
        if (events.Count >= MaxCatalogueEvents) throw new V1Problem(409, "The Functional Group audit trail is full. Nothing was changed.");
        events.Add(new JsonObject
        {
            ["id"] = Convert.ToHexStringLower(RandomNumberGenerator.GetBytes(16)), ["event"] = kind, ["group_id"] = gid, ["group_name"] = name,
            ["actor"] = actor, ["timestamp"] = Now(), ["members"] = members, ["rules"] = rules,
        });
    }

    /// <summary>Permanent deletion of an archived group, also with members. <paramref name="expectedMembers"/> is the member count the person confirmed: a
    /// different current count (a concurrent change) refuses the deletion with nothing changed. The group's memberships are removed (each with a `removed`
    /// classification event, and the user's revision raised so that an edit loaded earlier is refused), its suggestion rules are removed, and a `deleted`
    /// catalogue event records actor, time, identity and counts. Users, SAP roles, imports, review decisions, SoD data and the existing classification
    /// history are not changed; history keeps resolving the group's name through the catalogue event. Everything is one write: all of it or nothing.</summary>
    public Task<JsonObject> DeleteGroupAsync(string gid, int expectedMembers, string actor, CancellationToken ct) => UpdateAsync(data =>
    {
        var group = Group(data, gid);
        var name = (string)group["name"]!;
        if ((string?)group["status"] != "archived") throw new V1Problem(409, $"\"{name}\" is active. Archive the Functional Group before deleting it; nothing was changed.");
        var members = data["users"]!.AsObject().Select(p => p.Value!.AsObject()).Where(u => u["memberships"]![gid] is not null).ToList();
        if (members.Count != expectedMembers)
            throw new V1Problem(409, $"\"{name}\" now has {members.Count} member(s), not the {expectedMembers} confirmed. Review the group again; nothing was changed.");
        var reason = $"Functional Group \"{name}\" was deleted.";
        foreach (var stored in members)
        {
            var user = stored.DeepClone().AsObject();
            Remove(data, user, gid, reason, actor);
            Commit(data, user);
        }
        var rules = data["rules"]!.AsArray();
        var removedRules = rules.Count(r => (string?)r!["group_id"] == gid);
        foreach (var rule in rules.Where(r => (string?)r!["group_id"] == gid).ToList()) rules.Remove(rule);
        data["groups"]!.AsObject().Remove(gid);
        CatalogueEvent(data, "deleted", gid, name, actor, members.Count, removedRules);
        return (new JsonObject { ["status"] = "deleted", ["id"] = gid, ["name"] = name, ["members_removed"] = members.Count, ["rules_removed"] = removedRules }, true);
    }, actor, ct);

    /// <summary>The catalogue audit trail, newest first.</summary>
    public static JsonObject CatalogueHistory(JsonObject data, int offset, int limit)
    {
        var events = (data["catalogue_events"] as JsonArray ?? []).Reverse().Select(e => e!.DeepClone()).ToList();
        return new JsonObject { ["items"] = new JsonArray([.. events.Skip(offset).Take(limit)]), ["total"] = events.Count, ["offset"] = offset, ["limit"] = limit };
    }

    // --- classification ------------------------------------------------------------------------------------------------------------

    private static string Aggregate(JsonObject memberships) =>
        memberships.Count == 0 ? "Unassigned" : memberships.Any(p => (string?)p.Value!["status"] == "Needs review") ? "Needs review" : "Confirmed";

    private static JsonObject PublicMembership(JsonObject data, string gid, JsonObject member)
    {
        var group = Group(data, gid);
        return new JsonObject
        {
            ["group_id"] = gid, ["group"] = new JsonObject { ["id"] = gid, ["name"] = group["name"]!.DeepClone(), ["status"] = group["status"]!.DeepClone() },
            ["status"] = member["status"]!.DeepClone(), ["confirmed_at"] = (string?)member["confirmed_at"] is { Length: > 0 } c ? c : null,
            ["confirmed_by"] = (string?)member["confirmed_by"] ?? "", ["rationale"] = (string?)member["rationale"] ?? "", ["review"] = member["review"]?.DeepClone(),
        };
    }

    /// <summary>public_user: the user's memberships (sorted by group name); `group_id`/`group` and the top-level confirmation only with exactly one membership.</summary>
    public static JsonObject PublicUser(JsonObject data, string username)
    {
        if (data["users"]![UserKey(username)] is not JsonObject user)
            return new JsonObject
            {
                ["username"] = username, ["group_id"] = null, ["group"] = null, ["group_ids"] = new JsonArray(), ["memberships"] = new JsonArray(), ["status"] = "Unassigned",
                ["revision"] = 0, ["confirmed_at"] = null, ["confirmed_by"] = "", ["rationale"] = "", ["review"] = null,
            };
        var members = user["memberships"]!.AsObject().Select(p => PublicMembership(data, p.Key, p.Value!.AsObject()))
            .OrderBy(m => NormalizeText((string?)m["group"]!["name"]), StringComparer.Ordinal).ThenBy(m => (string?)m["group_id"], StringComparer.Ordinal).ToList();
        var sole = members.Count == 1 ? members[0] : null;
        return new JsonObject
        {
            ["username"] = user["username"]!.DeepClone(), ["group_id"] = sole?["group_id"]?.DeepClone(), ["group"] = sole?["group"]?.DeepClone(),
            ["group_ids"] = new JsonArray([.. members.Select(m => m["group_id"]!.DeepClone())]), ["memberships"] = new JsonArray([.. members]),
            ["status"] = Aggregate(user["memberships"]!.AsObject()), ["revision"] = user["revision"]!.DeepClone(),
            ["confirmed_at"] = sole?["confirmed_at"]?.DeepClone(), ["confirmed_by"] = sole is null ? "" : sole["confirmed_by"]!.DeepClone(),
            ["rationale"] = sole is null ? "" : sole["rationale"]!.DeepClone(), ["review"] = sole?["review"]?.DeepClone(),
        };
    }

    /// <summary>{UPPER SAP USER: public classification} for every user with a record.</summary>
    public static Dictionary<string, JsonObject> ClassificationMap(JsonObject data) =>
        data["users"]!.AsObject().Select(p => (string)p.Value!["username"]!).ToDictionary(n => n.Trim().PyUpper(), n => PublicUser(data, n));

    private void Event(JsonObject data, JsonObject user, string kind, string? before, string? after, string statusBefore, string statusAfter, string actor, string reason, string changeId = "")
    {
        var history = data["history"]!.AsArray();
        history.Add(new JsonObject
        {
            ["id"] = Convert.ToHexStringLower(RandomNumberGenerator.GetBytes(16)), ["event"] = kind, ["user_key"] = UserKey((string)user["username"]!), ["username"] = user["username"]!.DeepClone(),
            ["previous_group"] = before, ["new_group"] = after, ["previous_status"] = statusBefore, ["new_status"] = statusAfter,
            ["actor"] = actor, ["timestamp"] = Now(), ["reason"] = reason, ["change_id"] = changeId,
        });
        if (history.Count > MaxHistory) throw new V1Problem(409, "Functional Group history is full. Existing data is retained.");
    }

    private static JsonObject Record(JsonObject data, string username, int expectedRevision)
    {
        username = username.Trim();
        if (username.Length == 0) throw new V1Problem(422, "A SAP user is required.");
        var user = data["users"]![UserKey(username)]?.DeepClone().AsObject()
            ?? new JsonObject { ["username"] = username, ["revision"] = 0, ["updated_at"] = null, ["handled"] = new JsonArray(), ["memberships"] = new JsonObject() };
        if ((int)user["revision"]! != expectedRevision) throw new V1Problem(409, "The classification changed since it was loaded. Reload before saving.");
        return user;
    }

    private void Commit(JsonObject data, JsonObject user, string changeId = "")
    {
        user["revision"] = (int)user["revision"]! + 1;
        user["updated_at"] = Now();
        var handled = user["handled"] as JsonArray ?? [];
        if (changeId.Length > 0 && !handled.Any(h => (string?)h == changeId))
        {
            handled.Add(changeId);
            while (handled.Count > MaxHandled) handled.RemoveAt(0);
        }
        user["handled"] = handled.DeepClone();
        data["users"]![UserKey((string)user["username"]!)] = user;
    }

    private string Add(JsonObject data, JsonObject user, string groupId, string rationale, string actor, string changeId = "")
    {
        var group = Group(data, groupId);
        var memberships = user["memberships"]!.AsObject();
        var existing = memberships[groupId] as JsonObject;
        if (existing is not null && (string?)existing["status"] == "Confirmed") return "unchanged";
        if ((string?)group["status"] == "archived" && existing is null) throw new V1Problem(409, "Archived Functional Groups cannot be newly assigned. Restore the group first.");
        var stamp = Now();
        var before = existing is null ? "Unassigned" : (string)existing["status"]!;
        memberships[groupId] = new JsonObject { ["status"] = "Confirmed", ["confirmed_at"] = stamp, ["confirmed_by"] = actor, ["rationale"] = rationale.Trim(), ["review"] = null, ["updated_at"] = stamp };
        Event(data, user, existing is null ? "assigned" : "reconfirmed", existing is null ? null : groupId, groupId, before, "Confirmed", actor, rationale.Trim(), changeId);
        return existing is null ? "added" : "reconfirmed";
    }

    private void Remove(JsonObject data, JsonObject user, string groupId, string rationale, string actor, string changeId = "")
    {
        var memberships = user["memberships"]!.AsObject();
        if (memberships[groupId] is not JsonObject existing) throw new V1Problem(409, "The user is not a member of this Functional Group.");
        memberships.Remove(groupId);
        Event(data, user, "removed", groupId, null, (string)existing["status"]!, "Unassigned", actor, rationale.Trim(), changeId);
    }

    public Task<(JsonObject Classification, string Outcome)> AddMembershipAsync(string username, string groupId, string rationale, int expected, string actor, string changeId, CancellationToken ct) =>
        UpdateAsync(data =>
        {
            var user = Record(data, username, expected);
            var outcome = Add(data, user, groupId, rationale, actor, changeId);
            if (outcome != "unchanged") Commit(data, user, changeId);
            return ((PublicUser(data, username.Trim()), outcome), outcome != "unchanged");
        }, actor, ct);

    public Task<JsonObject> RemoveMembershipAsync(string username, string groupId, string rationale, int expected, string actor, string changeId, CancellationToken ct) =>
        UpdateAsync(data =>
        {
            var user = Record(data, username, expected);
            Remove(data, user, groupId, rationale, actor, changeId);
            Commit(data, user, changeId);
            return (PublicUser(data, username.Trim()), true);
        }, actor, ct);

    /// <summary>Legacy single-group operation: null clears every membership; a group becomes the only membership.</summary>
    public Task<JsonObject> ClassifyAsync(string username, string? groupId, string rationale, int expected, string actor, string changeId, CancellationToken ct) =>
        UpdateAsync(data =>
        {
            var user = Record(data, username, expected);
            var memberships = user["memberships"]!.AsObject();
            if (groupId is null && memberships.Count == 0 && (int)user["revision"]! == 0 && changeId.Length == 0) throw new V1Problem(409, "The user has no Functional Group to clear.");
            if (groupId is not null) Group(data, groupId);
            var others = memberships.Select(p => p.Key).Where(g => g != groupId).ToList();
            foreach (var gid in others) Remove(data, user, gid, rationale, actor, changeId);
            if (groupId is not null) Add(data, user, groupId, rationale, actor, changeId);
            else if (others.Count == 0 && changeId.Length > 0) Event(data, user, "removed", null, null, "Unassigned", "Unassigned", actor, rationale.Trim(), changeId);
            Commit(data, user, changeId);
            return (PublicUser(data, username.Trim()), true);
        }, actor, ct);

    public static JsonObject BulkPreview(JsonObject data, IReadOnlyList<string> groupIds, IEnumerable<string> usernames)
    {
        var groups = new JsonArray();
        foreach (var gid in groupIds) { var g = Group(data, gid); groups.Add(new JsonObject { ["id"] = g["id"]!.DeepClone(), ["name"] = g["name"]!.DeepClone(), ["status"] = g["status"]!.DeepClone() }); }
        var rows = new JsonArray();
        int additions = 0, existing = 0, unassigned = 0;
        foreach (var name in usernames)
        {
            var current = PublicUser(data, name);
            var held = current["group_ids"]!.AsArray().Select(n => (string)n!).ToHashSet();
            var add = groupIds.Where(g => !held.Contains(g)).ToList();
            var have = groupIds.Where(held.Contains).ToList();
            additions += add.Count; existing += have.Count; if (held.Count == 0) unassigned++;
            rows.Add(new JsonObject
            {
                ["username"] = (int)current["revision"]! > 0 ? current["username"]!.DeepClone() : name, ["revision"] = current["revision"]!.DeepClone(),
                ["group_ids"] = current["group_ids"]!.DeepClone(), ["group_names"] = new JsonArray([.. current["memberships"]!.AsArray().Select(m => m!["group"]!["name"]!.DeepClone())]),
                ["additions"] = new JsonArray([.. add.Select(a => (JsonNode)a)]), ["existing"] = new JsonArray([.. have.Select(a => (JsonNode)a)]),
            });
        }
        return new JsonObject
        {
            ["groups"] = groups, ["items"] = rows,
            ["counts"] = new JsonObject { ["users"] = rows.Count, ["additions"] = additions, ["existing"] = existing, ["unassigned"] = unassigned },
        };
    }

    public Task<JsonObject> BulkAssignAsync(IReadOnlyList<string> groupIds, IReadOnlyList<string> usernames, IReadOnlyDictionary<string, int> expected, string rationale, string actor,
        string operationId, CancellationToken ct)
    {
        if (operationId.Length == 0) throw new V1Problem(422, "An operation identifier is required.");
        var ids = groupIds.Distinct().ToList();
        if (ids.Count == 0) throw new V1Problem(422, "Select at least one Functional Group.");
        return UpdateAsync(data =>
        {
            if (data["history"]!.AsArray().Any(h => (string?)h!["change_id"] == operationId)) throw new V1Problem(409, "This operation was already applied.");
            foreach (var gid in ids)
                if ((string?)Group(data, gid)["status"] == "archived") throw new V1Problem(409, "Archived Functional Groups cannot be newly assigned. Restore the group first.");
            JsonArray applied = [], unchanged = [], conflicts = [];
            var seen = new HashSet<string>();
            foreach (var name in usernames)
            {
                var key = UserKey(name);
                if (!seen.Add(key)) continue;
                var existing = data["users"]![key] as JsonObject;
                var revision = existing is null ? 0 : (int)existing["revision"]!;
                if (expected.TryGetValue(key, out var seenRevision) ? revision != seenRevision : revision != 0)
                {
                    conflicts.Add(new JsonObject { ["username"] = name, ["reason"] = "changed", ["detail"] = "The classification changed since it was loaded." });
                    continue;
                }
                var user = existing?.DeepClone().AsObject()
                    ?? new JsonObject { ["username"] = name.Trim(), ["revision"] = 0, ["updated_at"] = null, ["handled"] = new JsonArray(), ["memberships"] = new JsonObject() };
                var outcomes = ids.ToDictionary(g => g, g => Add(data, user, g, rationale, actor, operationId));
                List<string> Of(string o) => outcomes.Where(p => p.Value == o).Select(p => p.Key).ToList();
                if (Of("added").Count + Of("reconfirmed").Count > 0)
                {
                    Commit(data, user, operationId);
                    applied.Add(new JsonObject
                    {
                        ["username"] = name, ["added"] = new JsonArray([.. Of("added").Select(g => (JsonNode)g)]), ["reconfirmed"] = new JsonArray([.. Of("reconfirmed").Select(g => (JsonNode)g)]),
                        ["unchanged"] = new JsonArray([.. Of("unchanged").Select(g => (JsonNode)g)]),
                    });
                }
                else unchanged.Add(new JsonObject { ["username"] = name, ["group_ids"] = new JsonArray([.. ids.Select(g => (JsonNode)g)]) });
            }
            var result = new JsonObject
            {
                ["operation_id"] = operationId, ["group_ids"] = new JsonArray([.. ids.Select(g => (JsonNode)g)]),
                ["group_names"] = new JsonArray([.. ids.Select(g => Group(data, g)["name"]!.DeepClone())]),
                ["applied"] = applied, ["unchanged"] = unchanged, ["conflicts"] = conflicts,
                ["status"] = conflicts.Count == 0 ? "applied" : applied.Count + unchanged.Count > 0 ? "partial" : "rejected",
            };
            return (result, applied.Count > 0);
        }, actor, ct);
    }

    // --- organizational changes (MIG-003 events) -------------------------------------------------------------------------------

    /// <summary>_flag: a Department or Job Title change makes every Confirmed membership "Needs review"; idempotent per change id.</summary>
    private bool Flag(JsonObject data, JsonObject user, string changeId, string reason)
    {
        var memberships = user["memberships"]!.AsObject();
        if (memberships.Count == 0 || (user["handled"] as JsonArray ?? []).Any(h => (string?)h == changeId)
            || memberships.Any(p => (string?)p.Value!["review"]?["change_id"] == changeId)) return false;
        var stamp = Now();
        var changed = false;
        foreach (var (gid, member) in memberships)
        {
            if ((string?)member!["status"] != "Confirmed") continue;
            member["status"] = "Needs review"; member["updated_at"] = stamp;
            member["review"] = new JsonObject { ["change_id"] = changeId, ["reason"] = reason, ["required_since"] = stamp };
            Event(data, user, "review_required", gid, gid, "Confirmed", "Needs review", "system", reason, changeId);
            changed = true;
        }
        if (changed) { user["revision"] = (int)user["revision"]! + 1; user["updated_at"] = stamp; }
        return changed;
    }

    private static string ChangeText(string label, string? before, string? after) =>
        $"{label} changed from {(string.IsNullOrEmpty(before) ? "empty" : before)} to {(string.IsNullOrEmpty(after) ? "empty" : after)}";

    private static string LastConfirmation(JsonObject user)
    {
        var stamps = user["memberships"]!.AsObject().Select(p => (string?)p.Value!["confirmed_at"]).Where(v => !string.IsNullOrEmpty(v)).ToList();
        return stamps.Count > 0 ? stamps.Max(StringComparer.Ordinal)! : (string?)user["updated_at"] ?? "";
    }

    /// <summary>apply_organizational_changes: Directory change events applied to classified users matched to exactly one employee (by normalized e-mail).
    /// Changes detected after the user's last confirmation flag memberships; manager changes only add a history signal. Idempotent per event id.</summary>
    public Task<int> ApplyOrganizationalChangesAsync(IReadOnlyDictionary<string, string> emailByUsername, IEnumerable<JsonObject> positionEvents, IEnumerable<JsonObject> managerEvents, CancellationToken ct)
    {
        var byEmail = positionEvents.GroupBy(e => (string)e["key"]!).ToDictionary(g => g.Key, g => g.OrderBy(e => (string)e["detected_at"]!, StringComparer.Ordinal).ThenBy(e => (string)e["id"]!, StringComparer.Ordinal).ToList());
        var managers = managerEvents.GroupBy(e => (string)e["key"]!).ToDictionary(g => g.Key, g => g.OrderBy(e => (string)e["detected_at"]!, StringComparer.Ordinal).ThenBy(e => (string)e["id"]!, StringComparer.Ordinal).ToList());
        return UpdateAsync(data =>
        {
            var users = data["users"]!.AsObject();
            if (users.Count == 0) return (0, false);
            var seen = data["history"]!.AsArray().Where(e => (string?)e!["event"] == "manager_changed").Select(e => ((string)e!["user_key"]!, (string?)e["change_id"])).ToHashSet();
            var changed = 0;
            foreach (var (key, node) in users.ToList())
            {
                var user = node!.AsObject();
                if (!emailByUsername.TryGetValue(((string)user["username"]!).Trim().PyUpper(), out var email)) continue;
                var since = LastConfirmation(user);
                foreach (var item in byEmail.GetValueOrDefault(email) ?? [])
                {
                    if (string.CompareOrdinal((string)item["detected_at"]!, since) < 0) continue;
                    var parts = new List<string>();
                    var fields = item["fields"]!.AsArray().Select(f => (string?)f).ToList();
                    if (fields.Contains("department")) parts.Add(ChangeText("Directory Department", (string?)item["previous_department"], (string?)item["current_department"]));
                    if (fields.Contains("title")) parts.Add(ChangeText("Job Title", (string?)item["previous_title"], (string?)item["current_title"]));
                    if (Flag(data, user, (string)item["id"]!, string.Join("; ", parts))) changed++;
                }
                foreach (var item in managers.GetValueOrDefault(email) ?? [])
                {
                    if (string.CompareOrdinal((string)item["detected_at"]!, since) < 0 || !seen.Add((key, (string)item["id"]!))) continue;
                    var status = Aggregate(user["memberships"]!.AsObject());
                    Event(data, user, "manager_changed", null, null, status, status, "system",
                        ChangeText("Manager", (string?)item["previous_manager"], (string?)item["current_manager"]), (string)item["id"]!);
                    changed++;
                }
            }
            return (changed, changed > 0);
        }, "system", ct);
    }

    public static JsonObject UserHistory(JsonObject data, string username, int offset, int limit)
    {
        var key = UserKey(username);
        var deleted = DeletedGroups(data);
        string? Name(JsonNode? gid) => (string?)gid is { } id ? (string?)data["groups"]![id]?["name"] ?? (deleted.TryGetValue(id, out var n) ? n : null) : null;
        var events = data["history"]!.AsArray().Reverse().Where(e => (string?)e!["user_key"] == key).Select(e =>
        {
            var item = e!.DeepClone().AsObject();
            item["previous_group_name"] = Name(item["previous_group"]); item["new_group_name"] = Name(item["new_group"]);
            item["group_deleted"] = new[] { (string?)item["previous_group"], (string?)item["new_group"] }.Any(g => g is not null && deleted.ContainsKey(g));
            return (JsonNode)item;
        }).ToList();
        return new JsonObject { ["items"] = new JsonArray([.. events.Skip(offset).Take(limit)]), ["total"] = events.Count, ["offset"] = offset, ["limit"] = limit };
    }

    // --- advisory suggestion rules -----------------------------------------------------------------------------------------------

    public static List<JsonObject> ListRules(JsonObject data) => data["rules"]!.AsArray().Select(r =>
    {
        var rule = r!.DeepClone().AsObject();
        var group = Group(data, (string)rule["group_id"]!);
        rule["department_mode"] = (string?)rule["department_mode"] is { Length: > 0 } mode ? mode : "equals";
        rule["group_name"] = group["name"]!.DeepClone();
        rule["group_status"] = group["status"]!.DeepClone();
        return rule;
    }).ToList();

    private static (string Department, string Title) CleanRule(string? department, string? title)
    {
        var d = Spaces().Replace((department ?? "").Trim(), " ");
        var t = Spaces().Replace((title ?? "").Trim(), " ");
        if (d.Length == 0 && t.Length == 0) throw new V1Problem(422, "A rule needs a Directory Department text, a Job Title text, or both.");
        return (d, t);
    }

    private static bool SameRule(JsonObject a, JsonObject b) =>
        (string?)a["group_id"] == (string?)b["group_id"] && NormalizeText((string?)a["department"]) == NormalizeText((string?)b["department"])
        && NormalizeText((string?)a["title_contains"]) == NormalizeText((string?)b["title_contains"])
        && ((string?)a["department_mode"] is { Length: > 0 } ma ? ma : "equals") == ((string?)b["department_mode"] is { Length: > 0 } mb ? mb : "equals");

    public Task<JsonObject> AddRuleAsync(string groupId, string department, string title, string mode, string actor, CancellationToken ct)
    {
        var (d, t) = CleanRule(department, title);
        if (mode is not ("contains" or "equals")) throw new V1Problem(422, "Department matching is \"contains\" or \"equals\".");
        return UpdateAsync(data =>
        {
            Group(data, groupId);
            var rule = new JsonObject
            {
                ["id"] = "fr_" + Convert.ToHexStringLower(RandomNumberGenerator.GetBytes(6)), ["group_id"] = groupId, ["department"] = d, ["title_contains"] = t, ["department_mode"] = mode, ["created"] = Now(),
            };
            var rules = data["rules"]!.AsArray();
            if (rules.Any(r => SameRule(r!.AsObject(), rule))) throw new V1Problem(409, "This rule already exists.");
            if (rules.Count >= 500) throw new V1Problem(409, "The maximum number of suggestion rules is reached.");
            rules.Add(rule);
            return (rule.DeepClone().AsObject(), true);
        }, actor, ct);
    }

    public Task<JsonObject> UpdateRuleAsync(string ruleId, string groupId, string department, string title, string mode, string actor, CancellationToken ct)
    {
        var (d, t) = CleanRule(department, title);
        if (mode is not ("contains" or "equals")) throw new V1Problem(422, "Department matching is \"contains\" or \"equals\".");
        return UpdateAsync(data =>
        {
            Group(data, groupId);
            var rules = data["rules"]!.AsArray();
            var current = rules.OfType<JsonObject>().FirstOrDefault(r => (string?)r["id"] == ruleId) ?? throw new V1Problem(404, "Rule not found.");
            var candidate = current.DeepClone().AsObject();
            (candidate["group_id"], candidate["department"], candidate["title_contains"], candidate["department_mode"]) = (groupId, d, t, mode);
            if (rules.OfType<JsonObject>().Any(r => (string?)r["id"] != ruleId && SameRule(r, candidate))) throw new V1Problem(409, "This rule already exists.");
            (current["group_id"], current["department"], current["title_contains"], current["department_mode"], current["modified"]) = (groupId, d, t, mode, Now());
            return (current.DeepClone().AsObject(), true);
        }, actor, ct);
    }

    public Task<bool> DeleteRuleAsync(string ruleId, string actor, CancellationToken ct) => UpdateAsync(data =>
    {
        var rules = data["rules"]!.AsArray();
        var rule = rules.OfType<JsonObject>().FirstOrDefault(r => (string?)r["id"] == ruleId) ?? throw new V1Problem(404, "Rule not found.");
        rules.Remove(rule);
        return (true, true);
    }, actor, ct);

    /// <summary>rule_matches: Department (contains, legacy equals) AND Job Title (contains); a stated condition never matches an empty attribute.</summary>
    public static List<string>? RuleMatches(JsonObject rule, string? department, string? title)
    {
        var wantedDepartment = NormalizeText((string?)rule["department"]);
        var wantedTitle = NormalizeText((string?)rule["title_contains"]);
        if (wantedDepartment.Length == 0 && wantedTitle.Length == 0) return null;
        var reasons = new List<string>();
        if (wantedDepartment.Length > 0)
        {
            var actual = NormalizeText(department);
            if (actual.Length == 0) return null;
            if (((string?)rule["department_mode"] is { Length: > 0 } m ? m : "equals") == "equals")
            {
                if (actual != wantedDepartment) return null;
                reasons.Add($"Directory Department = {rule["department"]}");
            }
            else
            {
                if (!actual.Contains(wantedDepartment, StringComparison.Ordinal)) return null;
                reasons.Add($"Directory Department contains {rule["department"]}");
            }
        }
        if (wantedTitle.Length > 0)
        {
            if (!NormalizeText(title).Contains(wantedTitle, StringComparison.Ordinal)) return null;
            reasons.Add($"Job Title contains {rule["title_contains"]}");
        }
        return reasons;
    }

    public static JsonObject Suggest(JsonObject data, string? department, string? title, IEnumerable<string> held)
    {
        var matches = new List<JsonObject>();
        foreach (var rule in data["rules"]!.AsArray().OfType<JsonObject>())
        {
            var group = Group(data, (string)rule["group_id"]!);
            if ((string?)group["status"] != "active" || RuleMatches(rule, department, title) is not { } reasons) continue;
            matches.Add(new JsonObject
            {
                ["rule_id"] = rule["id"]!.DeepClone(), ["group_id"] = group["id"]!.DeepClone(), ["group_name"] = group["name"]!.DeepClone(),
                ["reasons"] = new JsonArray([.. reasons.Select(r => (JsonNode)r)]),
            });
        }
        var holding = held.ToHashSet();
        var consolidated = new Dictionary<string, JsonObject>();
        foreach (var match in matches)
        {
            var gid = (string)match["group_id"]!;
            if (!consolidated.TryGetValue(gid, out var entry))
                consolidated[gid] = entry = new JsonObject
                {
                    ["group_id"] = gid, ["group_name"] = match["group_name"]!.DeepClone(), ["rule_ids"] = new JsonArray(), ["reasons"] = new JsonArray(), ["already_member"] = holding.Contains(gid),
                };
            entry["rule_ids"]!.AsArray().Add(match["rule_id"]!.DeepClone());
            foreach (var reason in match["reasons"]!.AsArray())
                if (!entry["reasons"]!.AsArray().Any(r => (string?)r == (string?)reason)) entry["reasons"]!.AsArray().Add(reason!.DeepClone());
        }
        var groups = consolidated.Values.OrderBy(e => NormalizeText((string?)e["group_name"]), StringComparer.Ordinal).ThenBy(e => (string?)e["group_id"], StringComparer.Ordinal).ToList();
        return new JsonObject
        {
            ["status"] = groups.Count > 0 ? "suggested" : "none",
            ["matches"] = new JsonArray([.. matches.OrderBy(m => NormalizeText((string?)m["group_name"]), StringComparer.Ordinal).ThenBy(m => (string?)m["rule_id"], StringComparer.Ordinal)]),
            ["groups"] = new JsonArray([.. groups]),
        };
    }
}
