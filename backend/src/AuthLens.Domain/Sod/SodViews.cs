using System.Text.Json.Nodes;

namespace AuthLens.Domain.Sod;

/// <summary>Port of the SoD 2.0 views of sod_governance.py: restrict, role_suffix, shown, risk_matrix, activity_matrix, aggregate_by_group,
/// place_in_groups, explorer_rows, queue_items, conflict_concentration and remediation_rows. Pure functions over the derived model and the decision
/// state; decisions are read, never written, and conflict evidence is never changed. Rows use v1's JSON shapes; an "event" is the full event JSON.</summary>
public static class SodViews
{
    private static readonly StringComparer Ordinal = StringComparer.Ordinal;
    public static readonly string[] RemediationGroups = ["Remove assignment", "Investigate assignment", "Apply compensating control", "Maintain access", "No action required"];

    private static JsonArray Array(IEnumerable<string> values) => new([.. values.Select(v => (JsonNode?)v)]);
    private static JsonObject Counts(IEnumerable<string> values)
    {
        var result = new JsonObject();
        foreach (var value in values) result[value] = (result[value] is JsonValue v ? (int)v : 0) + 1;
        return result;
    }

    /// <summary>Organizational suffix token: the text after the last ':', '_' or '-' ('' without one).</summary>
    public static string RoleSuffix(string name)
    {
        var cut = name.LastIndexOfAny([':', '_', '-']);
        return cut >= 0 ? name[(cut + 1)..] : "";
    }

    /// <summary>Assignments that pass the assignment-level filters; all of them when none apply.</summary>
    public static IEnumerable<SodAssignment> Shown(SodUserEntry entry) =>
        entry.VisibleAssignments is null ? entry.Assignments.Values : entry.Assignments.Values.Where(a => entry.VisibleAssignments.Contains(a.Id));

    /// <summary>View limited to visible (user, risk) cells; evidence versions and assignments stay complete; <paramref name="allowed"/> limits listed assignments.</summary>
    public static Dictionary<string, SodUserEntry> Restrict(IReadOnlyDictionary<string, SodUserEntry> model, IReadOnlyDictionary<string, HashSet<string>> visible,
        IReadOnlyDictionary<string, HashSet<string>>? allowed = null)
    {
        var result = new Dictionary<string, SodUserEntry>(Ordinal);
        foreach (var (user, entry) in model)
        {
            if (!visible.TryGetValue(user, out var risks) || risks.Count == 0) continue;
            var copy = new SodUserEntry { User = entry.User, Account = entry.Account, VisibleAssignments = allowed is null ? null : allowed.GetValueOrDefault(user) ?? [] };
            foreach (var (risk, finding) in entry.Findings) if (risks.Contains(risk)) copy.Findings[risk] = finding;
            foreach (var (name, activity) in entry.Activities)
            {
                if (!activity.Risks.Overlaps(risks)) continue;
                var narrowed = new SodActivity { Name = activity.Name, Key = activity.Key, EvidenceVersion = activity.EvidenceVersion };
                narrowed.Risks.UnionWith(activity.Risks.Where(risks.Contains)); narrowed.Slots.UnionWith(activity.Slots);
                narrowed.Tcodes.UnionWith(activity.Tcodes); narrowed.Assignments.UnionWith(activity.Assignments);
                copy.Activities[name] = narrowed;
            }
            foreach (var (id, a) in entry.Assignments) copy.Assignments[id] = a;
            copy.Groups.UnionWith(entry.Groups);
            result[user] = copy;
        }
        return result;
    }

    private static IEnumerable<KeyValuePair<string, SodUserEntry>> ByUser(IReadOnlyDictionary<string, SodUserEntry> model) => model.OrderBy(p => p.Key, Ordinal);
    private static JsonObject Risk(JsonObject finding) => finding["risk"] as JsonObject ?? [];
    private static string Text(JsonObject o, string name) => o[name] is JsonValue v && v.TryGetValue<string>(out var s) ? s : "";
    private static string FindingId(JsonObject f) => (string)f["finding_id"]!;
    private static JsonNode? EventJson(SodItemState item) => item.Event?.ToJson();

    public static JsonObject RiskMatrix(IReadOnlyDictionary<string, SodUserEntry> model, SodStates state)
    {
        var columns = new SortedDictionary<string, (JsonObject Column, HashSet<string> Users)>(Ordinal);
        var rows = new JsonArray();
        foreach (var (user, entry) in ByUser(model))
        {
            var cells = new JsonObject();
            foreach (var (riskId, finding) in entry.Findings.OrderBy(p => p.Key, Ordinal))
            {
                var sides = entry.Activities.Where(p => p.Value.Risks.Contains(riskId)).Select(p => p.Key).Order(Ordinal);
                var id = FindingId(finding);
                cells[riskId] = new JsonObject
                {
                    ["finding_id"] = id, ["criticality"] = finding["criticality"]?.DeepClone(), ["acceptance"] = state.Items["acceptance"][id].Lifecycle,
                    ["decision_summary"] = SodGovernance.EffectiveDecision(entry, state, "risk", id),
                    ["activities"] = Counts(sides.Select(name => state.Items["activity"][entry.Activities[name].Key].Lifecycle)),
                    ["review_coverage"] = state.Coverage["acceptance"][id].DeepClone(),
                };
                if (!columns.TryGetValue(riskId, out var column))
                {
                    var risk = Risk(finding);
                    columns[riskId] = column = (new JsonObject
                    {
                        ["risk_id"] = riskId, ["criticality"] = finding["criticality"]?.DeepClone(), ["display_name"] = Text(risk, "display_name"),
                        ["source_text"] = Text(risk, "source_text"), ["category"] = Text(risk, "business_category"),
                    }, new HashSet<string>(Ordinal));
                }
                column.Users.Add(user);
            }
            rows.Add(new JsonObject { ["user"] = user, ["groups"] = Array(entry.Groups), ["cells"] = cells });
        }
        var ordered = new JsonArray();
        var criticality = new SortedDictionary<string, (int Risks, int UserRisk, HashSet<string> Users)>(Ordinal);
        foreach (var (_, (column, users)) in columns)
        {
            var c = column.DeepClone().AsObject(); c["users"] = users.Count; ordered.Add(c);
            var level = (string?)column["criticality"] ?? "";
            var bucket = criticality.TryGetValue(level, out var found) ? found : (Risks: 0, UserRisk: 0, Users: new HashSet<string>(Ordinal));
            bucket.Users.UnionWith(users);
            criticality[level] = (bucket.Risks + 1, bucket.UserRisk + users.Count, bucket.Users);
        }
        var byLevel = new JsonObject();
        foreach (var (level, value) in criticality) byLevel[level] = new JsonObject { ["risks"] = value.Risks, ["user_risk"] = value.UserRisk, ["users"] = value.Users.Count };
        return new JsonObject
        {
            ["columns"] = ordered, ["rows"] = rows,
            ["totals"] = new JsonObject { ["users"] = rows.Count, ["user_risk"] = rows.Sum(r => r!["cells"]!.AsObject().Count), ["risks"] = ordered.Count },
            ["criticality"] = byLevel,
        };
    }

    public static JsonObject ActivityMatrix(IReadOnlyDictionary<string, SodUserEntry> model, SodStates state)
    {
        var columns = new SortedDictionary<string, (SortedSet<string> Risks, HashSet<string> Users)>(Ordinal);
        var rows = new JsonArray();
        foreach (var (user, entry) in ByUser(model))
        {
            var cells = new JsonObject();
            foreach (var (name, activity) in entry.Activities.OrderBy(p => p.Key, Ordinal))
            {
                cells[name] = new JsonObject
                {
                    ["key"] = activity.Key, ["decision"] = state.Items["activity"][activity.Key].Lifecycle,
                    ["decision_summary"] = SodGovernance.EffectiveDecision(entry, state, "activity", activity.Key), ["roles"] = activity.Assignments.Count,
                    ["risks"] = Array(activity.Risks), ["duplicate"] = activity.Assignments.Count > 1, ["review_coverage"] = state.Coverage["activity"][activity.Key].DeepClone(),
                };
                if (!columns.TryGetValue(name, out var column)) columns[name] = column = (new SortedSet<string>(Ordinal), new HashSet<string>(Ordinal));
                column.Risks.UnionWith(activity.Risks); column.Users.Add(user);
            }
            rows.Add(new JsonObject { ["user"] = user, ["groups"] = Array(entry.Groups), ["cells"] = cells });
        }
        var ordered = new JsonArray([.. columns.Select(p => (JsonNode?)new JsonObject { ["activity"] = p.Key, ["risks"] = Array(p.Value.Risks), ["users"] = p.Value.Users.Count })]);
        return new JsonObject
        {
            ["columns"] = ordered, ["rows"] = rows,
            ["totals"] = new JsonObject { ["users"] = rows.Count, ["user_activity"] = rows.Sum(r => r!["cells"]!.AsObject().Count), ["activities"] = ordered.Count },
        };
    }

    /// <summary>Rows per SAP user group (a user in several groups counts in each); totals remain distinct users.</summary>
    public static JsonObject AggregateByGroup(JsonObject matrix)
    {
        var groups = new SortedDictionary<string, (HashSet<string> Users, SortedDictionary<string, HashSet<string>> Cells)>(Ordinal);
        foreach (var row in matrix["rows"]!.AsArray())
        {
            var names = row!["groups"]!.AsArray().Select(g => (string)g!).ToList();
            foreach (var group in names.Count > 0 ? names : ["(no group)"])
            {
                if (!groups.TryGetValue(group, out var item)) groups[group] = item = (new HashSet<string>(Ordinal), new SortedDictionary<string, HashSet<string>>(Ordinal));
                item.Users.Add((string)row["user"]!);
                foreach (var (column, _) in row["cells"]!.AsObject())
                {
                    if (!item.Cells.TryGetValue(column, out var users)) item.Cells[column] = users = new HashSet<string>(Ordinal);
                    users.Add((string)row["user"]!);
                }
            }
        }
        var result = matrix.DeepClone().AsObject();
        result["rows"] = new JsonArray([.. groups.Select(p =>
        {
            var cells = new JsonObject();
            foreach (var (column, users) in p.Value.Cells) cells[column] = new JsonObject { ["users"] = users.Count };
            return (JsonNode?)new JsonObject { ["user"] = p.Key, ["groups"] = new JsonArray(p.Key), ["users"] = p.Value.Users.Count, ["cells"] = cells };
        })]);
        return result;
    }

    /// <summary>Rows ordered by SAP User Group, each user exactly once (under the first selected group, else their first group), with per-group summaries.</summary>
    public static (JsonArray Rows, JsonArray Summaries) PlaceInGroups(IEnumerable<JsonNode?> rows, IEnumerable<string> preferred, bool reverse)
    {
        var wanted = preferred.Select(Fold).ToHashSet(Ordinal);
        var buckets = new Dictionary<string, List<JsonObject>>(Ordinal);
        foreach (var node in rows)
        {
            var row = node!.AsObject();
            var groups = row["groups"]!.AsArray().Select(g => (string)g!).ToList();
            var pick = groups.FirstOrDefault(g => wanted.Contains(Fold(g))) ?? (groups.Count > 0 ? groups[0] : "(no group)");
            var copy = row.DeepClone().AsObject(); copy["group"] = pick;
            if (!buckets.TryGetValue(pick, out var list)) buckets[pick] = list = [];
            list.Add(copy);
        }
        var names = buckets.Keys.OrderBy(n => n == "(no group)").ThenBy(Fold, Ordinal).ThenBy(n => n, Ordinal).ToList();
        if (reverse) names.Reverse();
        var ordered = new JsonArray();
        var summaries = new JsonArray();
        foreach (var name in names)
        {
            var members = buckets[name];
            summaries.Add(new JsonObject { ["name"] = name, ["users"] = members.Count, ["findings"] = members.Sum(m => m["cells"]!.AsObject().Count), ["start"] = ordered.Count });
            foreach (var m in members) ordered.Add(m);
        }
        return (ordered, summaries);
    }

    /// <summary>str.casefold() for the identifiers AuthLens compares (ASCII and common Unicode letters; ß folds to ss as in Python).</summary>
    public static string Fold(string value) => AuthLens.Domain.Text.PythonText.Casefold(value);

    /// <summary>Flat investigation tables; every row traces back to user, risk, activity and assignment.</summary>
    public static JsonArray ExplorerRows(string table, IReadOnlyDictionary<string, SodUserEntry> model, SodStates state)
    {
        var rows = new JsonArray();
        if (table == "lookup")
        {
            var roles = new SortedDictionary<string, (HashSet<string> Users, SortedSet<string> Activities, SortedSet<string> Risks, SortedSet<string> Catalogue)>(Ordinal);
            foreach (var (user, entry) in model)
                foreach (var a in Shown(entry))
                {
                    if (!roles.TryGetValue(a.Role, out var role)) roles[a.Role] = role = (new(Ordinal), new(Ordinal), new(Ordinal), new(Ordinal));
                    role.Users.Add(user); role.Activities.UnionWith(a.Supplies.Keys); role.Risks.UnionWith(a.Risks); role.Catalogue.UnionWith(a.CatalogueRoles);
                }
            foreach (var (name, item) in roles)
                rows.Add(new JsonObject { ["role"] = name, ["users"] = item.Users.Count, ["activities"] = Array(item.Activities), ["risks"] = Array(item.Risks), ["catalogue_roles"] = Array(item.Catalogue) });
            return rows;
        }
        foreach (var (user, entry) in ByUser(model))
        {
            if (table == "user_risk")
            {
                var shown = Shown(entry).Select(a => a.Id).ToHashSet(Ordinal);
                foreach (var (riskId, finding) in entry.Findings.OrderBy(p => p.Key, Ordinal))
                {
                    var names = entry.Activities.Where(p => p.Value.Risks.Contains(riskId)).Select(p => p.Key).Order(Ordinal).ToList();
                    var id = FindingId(finding);
                    rows.Add(new JsonObject
                    {
                        ["user"] = user, ["risk_id"] = riskId, ["criticality"] = finding["criticality"]?.DeepClone(), ["category"] = Text(Risk(finding), "business_category"),
                        ["groups"] = Array(entry.Groups), ["activities"] = Array(names),
                        ["roles"] = Array(names.SelectMany(n => entry.Activities[n].Assignments).Where(shown.Contains).Select(aid => entry.Assignments[aid].Role).Distinct().Order(Ordinal)),
                        ["acceptance"] = state.Items["acceptance"][id].Lifecycle, ["decision_summary"] = SodGovernance.EffectiveDecision(entry, state, "risk", id), ["finding_id"] = id,
                    });
                }
            }
            else if (table == "user_activity")
                foreach (var (name, activity) in entry.Activities.OrderBy(p => p.Key, Ordinal))
                    rows.Add(new JsonObject
                    {
                        ["user"] = user, ["groups"] = Array(entry.Groups), ["activity"] = name, ["risks"] = Array(activity.Risks), ["tcodes"] = Array(activity.Tcodes),
                        ["roles"] = activity.Assignments.Count, ["duplicate"] = activity.Assignments.Count > 1, ["decision"] = state.Items["activity"][activity.Key].Lifecycle,
                        ["decision_summary"] = SodGovernance.EffectiveDecision(entry, state, "activity", activity.Key), ["key"] = activity.Key,
                    });
            else if (table == "access_list")
                foreach (var a in Shown(entry).OrderBy(a => a.Role, Ordinal).ThenBy(a => a.Id, Ordinal))
                {
                    var item = state.Items["assignment"][a.Id];
                    rows.Add(new JsonObject
                    {
                        ["user"] = user, ["id"] = a.Id, ["role"] = a.Role, ["suffix"] = RoleSuffix(a.Role), ["evidence_version"] = a.EvidenceVersion, ["valid_from"] = a.ValidFrom,
                        ["valid_to"] = a.ValidTo, ["interval_status"] = a.IntervalStatus, ["user_group"] = a.UserGroup, ["activities"] = Array(a.Supplies.Keys), ["risks"] = Array(a.Risks),
                        ["catalogue_roles"] = Array(a.CatalogueRoles), ["decision"] = item.Lifecycle, ["decision_summary"] = SodGovernance.EffectiveDecision(entry, state, "assignment", a.Id),
                        ["has_review"] = item.Event is { Decision: not "Pending" }, ["previous_decision"] = item.Event?.Decision ?? "",
                    });
                }
        }
        return rows;
    }

    /// <summary>Work-queue rows for activity, assignment and risk-acceptance reviews of the visible population.</summary>
    public static List<JsonObject> QueueItems(IReadOnlyDictionary<string, SodUserEntry> model, SodStates state)
    {
        var items = new List<JsonObject>();
        foreach (var (user, entry) in ByUser(model))
        {
            foreach (var (name, activity) in entry.Activities.OrderBy(p => p.Key, Ordinal))
            {
                var s = state.Items["activity"][activity.Key];
                items.Add(new JsonObject
                {
                    ["kind"] = "activity", ["key"] = activity.Key, ["user"] = user, ["groups"] = Array(entry.Groups), ["ref"] = name, ["risks"] = Array(activity.Risks),
                    ["lifecycle"] = s.Lifecycle, ["roles"] = activity.Assignments.Count, ["event"] = EventJson(s), ["evidence_version"] = activity.EvidenceVersion,
                });
            }
            foreach (var a in Shown(entry).OrderBy(a => a.Id, Ordinal))
            {
                var s = state.Items["assignment"][a.Id];
                items.Add(new JsonObject
                {
                    ["kind"] = "assignment", ["key"] = a.Id, ["user"] = user, ["groups"] = Array(entry.Groups), ["ref"] = a.Role, ["risks"] = Array(a.Risks),
                    ["lifecycle"] = s.Lifecycle, ["roles"] = a.Supplies.Count, ["event"] = EventJson(s), ["evidence_version"] = a.EvidenceVersion,
                });
            }
            foreach (var (riskId, finding) in entry.Findings.OrderBy(p => p.Key, Ordinal))
            {
                var id = FindingId(finding);
                var s = state.Items["acceptance"][id];
                items.Add(new JsonObject
                {
                    ["kind"] = "acceptance", ["key"] = id, ["user"] = user, ["groups"] = Array(entry.Groups), ["ref"] = riskId, ["risks"] = new JsonArray(riskId),
                    ["lifecycle"] = s.Lifecycle, ["roles"] = 0, ["event"] = EventJson(s), ["evidence_version"] = (string)finding["evidence_version"]!,
                });
            }
        }
        foreach (var item in items) item["review_coverage"] = state.Coverage[(string)item["kind"]!][(string)item["key"]!].DeepClone();
        return items;
    }

    /// <summary>Users with more than one distinct risk, and the assigned roles behind the most distinct user-risk findings.</summary>
    public static JsonObject ConflictConcentration(IReadOnlyDictionary<string, SodUserEntry> model)
    {
        var roles = new Dictionary<string, (HashSet<string> Users, HashSet<(string, string)> Findings)>(Ordinal);
        foreach (var (user, entry) in model)
            foreach (var a in entry.Assignments.Values)
                foreach (var risk in a.Risks.Where(entry.Findings.ContainsKey))
                {
                    if (!roles.TryGetValue(a.Role, out var item)) roles[a.Role] = item = (new(Ordinal), []);
                    item.Users.Add(user); item.Findings.Add((user, risk));
                }
        var ranked = roles.Select(p => (Role: p.Key, Users: p.Value.Users.Count, Findings: p.Value.Findings.Count))
            .OrderBy(r => -r.Findings).ThenBy(r => -r.Users).ThenBy(r => Fold(r.Role), Ordinal).ToList();
        return new JsonObject
        {
            ["multi_risk_users"] = model.Values.Count(e => e.Findings.Count > 1),
            ["top_roles"] = new JsonArray([.. ranked.Take(50).Select(r => (JsonNode?)new JsonObject { ["role"] = r.Role, ["users"] = r.Users, ["findings"] = r.Findings })]),
            ["top_roles_total"] = ranked.Count,
        };
    }

    /// <summary>Recommended handling per (user, activity, assignment) for decided items (pending ones only with <paramref name="includePending"/>).
    /// <paramref name="verify"/>(user, assignment id) gives the verification text of a tracked removal; a completed action is a manual claim only.</summary>
    public static (List<JsonObject> Rows, JsonObject Summary) RemediationRows(IReadOnlyDictionary<string, SodUserEntry> model, SodStates state, IEnumerable<JsonObject> actions,
        Func<string, string, string> verify, DateOnly today, bool includePending = false)
    {
        var tracked = new Dictionary<(string, string), JsonObject>();
        foreach (var action in actions.OrderBy(a => (string?)a["modified"] ?? "", Ordinal))
            if ((string?)action["assignment_id"] is { Length: > 0 } aid && (string?)action["status"] != "Cancelled") tracked[(aid, (string)action["recommended"]!)] = action;
        var rows = new List<JsonObject>();
        var undecided = 0;
        var todayText = today.ToString("yyyy-MM-dd", System.Globalization.CultureInfo.InvariantCulture);
        foreach (var (user, entry) in ByUser(model))
            foreach (var a in Shown(entry).OrderBy(a => a.Role, Ordinal).ThenBy(a => a.Id, Ordinal))
            {
                var (aState, aEvent) = (state.Items["assignment"][a.Id].Lifecycle, state.Items["assignment"][a.Id].Event);
                foreach (var name in a.Supplies.Count > 0 ? a.Supplies.Keys.ToList() : [""])
                {
                    var activity = entry.Activities.GetValueOrDefault(name);
                    if (activity is null && name.Length > 0) continue;
                    var risks = activity is null ? [] : a.Risks.Where(activity.Risks.Contains).ToList();
                    var (cState, cEvent) = activity is null ? ("Pending", null) : (state.Items["activity"][activity.Key].Lifecycle, state.Items["activity"][activity.Key].Event);
                    var accept = risks.Where(entry.Findings.ContainsKey).Select(r => state.Items["acceptance"][FindingId(entry.Findings[r])]).ToList();
                    var acceptStates = accept.Select(s => s.Lifecycle).ToHashSet(Ordinal);
                    string recommended, reason;
                    if (aState == "Removal required") (recommended, reason) = ("Remove assignment", aEvent?.Justification ?? "");
                    else if (aState == "Investigate") (recommended, reason) = ("Investigate assignment", aEvent?.Justification ?? "");
                    else if (cState == "Removal required") (recommended, reason) = ("Investigate assignment", "Activity marked for removal: " + (cEvent?.Justification ?? ""));
                    else if (acceptStates.Contains("Rejected")) (recommended, reason) = ("Investigate assignment", "Risk acceptance rejected.");
                    else if (cState == "Conditional") (recommended, reason) = ("Apply compensating control", cEvent?.Controls ?? "");
                    else if (aState == "Keep" || cState == "Approved" && aState == "Pending")
                        (recommended, reason) = (acceptStates.Count == 1 && acceptStates.Contains("Accepted") ? "No action required" : "Maintain access", (aEvent ?? cEvent)?.Justification ?? "");
                    else
                    {
                        undecided++;
                        if (!includePending) continue;
                        (recommended, reason) = ("Awaiting review", "");
                    }
                    var action = recommended is "Remove assignment" or "Investigate assignment" ? tracked.GetValueOrDefault((a.Id, recommended)) : null;
                    var due = (string?)action?["due_date"];
                    var status = (string?)action?["status"];
                    rows.Add(new JsonObject
                    {
                        ["user"] = user, ["activity"] = name, ["risks"] = Array(risks), ["role"] = a.Role, ["catalogue_roles"] = Array(a.CatalogueRoles), ["assignment_id"] = a.Id,
                        ["valid_from"] = a.ValidFrom, ["valid_to"] = a.ValidTo, ["user_group"] = a.UserGroup, ["activity_decision"] = cState, ["assignment_decision"] = aState,
                        ["activity_summary"] = activity is null ? null : SodGovernance.EffectiveDecision(entry, state, "activity", activity.Key),
                        ["assignment_summary"] = SodGovernance.EffectiveDecision(entry, state, "assignment", a.Id),
                        ["risk_acceptance"] = Array(acceptStates.Order(Ordinal)), ["recommended"] = recommended, ["reason"] = reason,
                        ["controls"] = cEvent is { Controls.Length: > 0 } ? cEvent.Controls : accept.Select(s => s.Event?.Controls).FirstOrDefault(c => !string.IsNullOrEmpty(c)) ?? "",
                        ["action"] = action?.DeepClone(), ["owner"] = (string?)action?["owner"] ?? "", ["due_date"] = due, ["action_status"] = status ?? "Not tracked",
                        ["overdue"] = action is not null && due is { Length: > 0 } && string.CompareOrdinal(due, todayText) < 0 && status is "Open" or "In progress",
                        ["verification"] = action is null ? "Not tracked" : recommended == "Remove assignment" ? verify(user, a.Id) : "Not verifiable from source evidence",
                    });
                }
            }
        var summary = new JsonObject();
        foreach (var name in includePending ? [.. RemediationGroups, "Awaiting review"] : RemediationGroups) summary[name] = rows.Count(r => (string)r["recommended"]! == name);
        summary["undecided"] = undecided;
        summary["overdue"] = rows.Count(r => (bool)r["overdue"]!);
        return (rows, summary);
    }
}
