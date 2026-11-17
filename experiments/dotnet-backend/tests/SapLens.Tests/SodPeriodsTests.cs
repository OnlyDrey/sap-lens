using System.Net;
using System.Text;
using System.Text.Json.Nodes;
using Microsoft.AspNetCore.Builder;
using SapLens.Api;

namespace SapLens.Tests;

/// <summary>MIG-016: review periods (sod_periods.py). A period captures an immutable snapshot; decisions in an open period are its own; approval needs every
/// activity review and risk acceptance decided and freezes a copy of all decisions and actions; frozen periods refuse decisions, recapture and actions;
/// deletion archives a period with recorded work and erases only an empty draft; a shared access token never records attributable period changes.</summary>
public sealed class SodPeriodsTests : IAsyncLifetime
{
    private readonly string _root = Directory.CreateTempSubdirectory("saplens-periods-").FullName;
    private readonly string _token = HostSettings.NewToken();
    private WebApplication _app = null!;
    private HttpClient _client = null!;

    private static string Fixture(params string[] path) => Path.Combine([AppContext.BaseDirectory, "Fixtures", "sod", .. path]);

    public Task InitializeAsync() => StartAsync(HostMode.Desktop, true);

    private async Task StartAsync(HostMode mode, bool import)
    {
        _app = SapLensHost.Build(new HostSettings { DataDirectory = Path.Combine(_root, "data"), Port = 0, AccessToken = _token, JsonConsoleLogging = false, Mode = mode,
            Authentication = AuthenticationMode.SharedToken });
        await _app.StartAsync();
        _client = new HttpClient { BaseAddress = new Uri(_app.Urls.First()) };
        _client.DefaultRequestHeaders.Add(RequestBoundary.TokenHeader, _token);
        if (!import) return;
        foreach (var source in new[] { "roles", "users", "sod" })
        {
            var job = JsonNode.Parse(await (await _client.PostAsync($"/api/v1/imports/{source}", new StringContent(File.ReadAllText(Fixture("analysis", source + ".sod.txt")), Encoding.UTF8, "text/csv"))).Content.ReadAsStringAsync())!;
            for (var i = 0; i < 400 && (string)JsonNode.Parse(await _client.GetStringAsync($"/api/v1/jobs/{(long)job["id"]!}"))!["status"]! != "Completed"; i++) await Task.Delay(50);
        }
        var settings = JsonNode.Parse(await _client.GetStringAsync("/api/configuration"))!["settings"]!.AsObject();
        settings["features"]!["sod"] = true;
        Assert.Equal(HttpStatusCode.OK, (await Post("/api/configuration", settings)).Status);
    }

    public async Task DisposeAsync()
    {
        _client.Dispose();
        await _app.StopAsync();
        await _app.DisposeAsync();
        Microsoft.Data.Sqlite.SqliteConnection.ClearAllPools();
        try { Directory.Delete(_root, true); } catch (IOException) { }
    }

    private async Task<(HttpStatusCode Status, JsonNode? Body)> Post(string path, JsonNode body)
    {
        var request = new HttpRequestMessage(HttpMethod.Post, path) { Content = new StringContent(body.ToJsonString(), Encoding.UTF8, "application/json") };
        request.Headers.Add("Origin", _client.BaseAddress!.GetLeftPart(UriPartial.Authority));
        var response = await _client.SendAsync(request);
        var text = await response.Content.ReadAsStringAsync();
        return (response.StatusCode, text.Length == 0 ? null : JsonNode.Parse(text));
    }

    private async Task<JsonObject> Get(string path)
    {
        var response = await _client.GetAsync(path);
        var text = await response.Content.ReadAsStringAsync();
        Assert.True(response.IsSuccessStatusCode, $"{path}: {(int)response.StatusCode} {text}");
        return JsonNode.Parse(text)!.AsObject();
    }

    private async Task<int> Revision() => (int)(await Get("/api/sod/periods"))["revision"]!;

    private async Task<JsonObject> Create(string name)
    {
        var (status, body) = await Post("/api/sod/periods", new JsonObject { ["name"] = name, ["start"] = "2026-01-01", ["end"] = "2026-12-31", ["evaluation_date"] = "2026-06-01", ["expected_revision"] = await Revision() });
        Assert.True(status == HttpStatusCode.OK, body?.ToJsonString());
        return body!["period"]!.AsObject();
    }

    private async Task<(HttpStatusCode Status, JsonNode? Body)> Transition(string id, string state, JsonObject? extra = null)
    {
        var context = await Get($"/api/sod/context?context={id}");
        var body = new JsonObject { ["state"] = state, ["expected_revision"] = await Revision(), ["expected_review_revision"] = (int)context["revision"]! };
        foreach (var (k, v) in extra ?? []) body[k] = v?.DeepClone();
        return await Post($"/api/sod/periods/{id}/transition", body);
    }

    /// <summary>Decides every queue item of one kind in the context (batches of 100), as a reviewer would.</summary>
    private async Task DecideAll(string context, string kind, string decision, JsonObject? extra = null)
    {
        var queue = await Get($"/api/sod/queue?context={context}&kind={kind}&limit=200");
        var items = queue["items"]!.AsArray().Select(i => i!.AsObject()).ToList();
        for (var offset = 200; offset < (int)queue["total"]!; offset += 200)
            items.AddRange((await Get($"/api/sod/queue?context={context}&kind={kind}&limit=200&offset={offset}"))["items"]!.AsArray().Select(i => i!.AsObject()));
        foreach (var chunk in items.Chunk(100))
        {
            var info = await Get($"/api/sod/context?context={context}");
            var body = new JsonObject
            {
                ["context"] = context, ["expected_revision"] = (int)info["revision"]!, ["expected_generation"] = (string)info["generation"]!, ["decision"] = decision,
                ["justification"] = "Synthetic review", ["items"] = new JsonArray([.. chunk.Select(i => (JsonNode?)new JsonObject
                {
                    ["key"] = i["key"]!.DeepClone(), ["user"] = i["user"]!.DeepClone(), ["ref"] = i["ref"]!.DeepClone(), ["evidence_version"] = i["evidence_version"]!.DeepClone(),
                })]),
            };
            foreach (var (k, v) in extra ?? []) body[k] = v?.DeepClone();
            var (status, response) = await Post($"/api/sod/decisions/{kind}", body);
            Assert.True(status == HttpStatusCode.OK, response?.ToJsonString());
        }
    }

    [Fact]
    public async Task A_period_is_captured_reviewed_approved_frozen_compared_and_archived()
    {
        var period = await Create("Q2 2026");
        var id = (string)period["id"]!;
        Assert.Equal("Draft", (string)period["state"]!);
        Assert.Matches("^[a-f0-9]{64}$", (string)period["snapshot"]!);
        var listed = (await Get("/api/sod/periods"))["items"]!.AsArray().Single()!;
        Assert.Equal(0, (int)listed["progress"]!["decided"]!);
        Assert.True((int)listed["progress"]!["blocking"]! > 0);
        var details = await Get($"/api/sod/periods/{id}?limit=5");
        Assert.Equal(2, (int)details["model"]!);
        Assert.Equal(146, (int)details["total"]!);
        Assert.Equal(5, details["snapshot"]!["analysis"]!["users"]!.AsArray().Count);
        var context = await Get($"/api/sod/context?context={id}");
        Assert.Equal(("Q2 2026", false, true), ((string)context["period"]!["name"]!, (bool)context["frozen"]!, (bool)context["reviewable"]!));
        Assert.Equal("2026-06-01", (string)context["as_of"]!);

        // The period's views read its snapshot; the live context is unaffected by decisions recorded in the period.
        Assert.Equal(90, (int)(await Get($"/api/sod/matrix/risk?context={id}&limit=5"))["total_rows"]!);
        Assert.Equal(HttpStatusCode.UnprocessableEntity, (await Transition(id, "Ready for approval")).Status);   // not a transition from Draft
        Assert.Equal(HttpStatusCode.OK, (await Transition(id, "In review")).Status);
        Assert.Equal(HttpStatusCode.Conflict, (await Transition(id, "Ready for approval")).Status);   // activities and acceptances pending
        await DecideAll(id, "activity", "Approved");
        await DecideAll(id, "acceptance", "Accepted", new JsonObject { ["approver"] = "Approver", ["expires"] = "2099-12-31" });
        Assert.Equal(0, (int)(await Get("/api/sod/periods"))["items"]![0]!["progress"]!["blocking"]!);
        Assert.Equal(0, (int)(await Get("/api/sod/queue?kind=activity&status=Reviewed&limit=1"))["total"]!);   // the live context has no decisions
        Assert.Equal(HttpStatusCode.OK, (await Transition(id, "Ready for approval")).Status);
        Assert.Equal(HttpStatusCode.UnprocessableEntity, (await Transition(id, "Approved")).Status);    // needs confirmation and an approval date
        var approved = await Transition(id, "Approved", new JsonObject { ["confirm"] = true, ["approval_date"] = "2026-06-30" });
        Assert.True(approved.Status == HttpStatusCode.OK, approved.Body?.ToJsonString());
        var frozenPeriod = approved.Body!["period"]!;
        Assert.Equal("Approved", (string)frozenPeriod["state"]!);
        Assert.Equal(2, frozenPeriod["snapshots"]!.AsArray().Count);
        Assert.False(string.IsNullOrWhiteSpace((string)frozenPeriod["approver"]!));                   // the Desktop reviewer profile (v1 actor())
        Assert.Equal((string)frozenPeriod["reviewer"]!, (string)frozenPeriod["approver"]!);

        // Frozen: read-only, decisions come from the snapshot, recapture and actions are refused.
        var frozen = await Get($"/api/sod/context?context={id}");
        Assert.True((bool)frozen["frozen"]!);
        Assert.False((bool)frozen["reviewable"]!);
        Assert.True((int)(await Get($"/api/sod/queue?context={id}&kind=activity&status=Reviewed&limit=1"))["total"]! > 0);
        var item = (await Get($"/api/sod/queue?context={id}&kind=assignment&limit=1"))["items"]![0]!;
        var refused = await Post("/api/sod/decisions/assignment", new JsonObject
        {
            ["context"] = id, ["expected_revision"] = (int)frozen["revision"]!, ["expected_generation"] = (string)frozen["generation"]!, ["decision"] = "Keep", ["justification"] = "Late",
            ["items"] = new JsonArray(new JsonObject { ["key"] = item["key"]!.DeepClone(), ["user"] = item["user"]!.DeepClone(), ["ref"] = item["ref"]!.DeepClone(), ["evidence_version"] = item["evidence_version"]!.DeepClone() }),
        });
        Assert.Equal(HttpStatusCode.Conflict, refused.Status);
        Assert.Equal(HttpStatusCode.Conflict, (await Post($"/api/sod/periods/{id}/recapture", new JsonObject { ["expected_revision"] = await Revision(), ["confirm"] = true })).Status);
        Assert.Equal(HttpStatusCode.Conflict, (await Transition(id, "In review")).Status);

        // Compare with a later period: same evidence, nothing changed; the decisions of the new open period differ.
        var later = await Create("Q3 2026");
        var comparison = await Get($"/api/sod/periods/compare?left={id}&right={(string)later["id"]!}");
        Assert.Equal(146, (int)comparison["summary"]!["Unchanged"]!);
        Assert.True(comparison["decision_changes"]!.AsArray().Count > 0);

        // Reports read the frozen snapshot: preview, then PDF and DOCX that match the previewed model; a stale model is refused; each export is logged.
        var preview = await Post("/api/sod/reports/preview", new JsonObject { ["period_id"] = id, ["options"] = new JsonObject { ["status"] = "Approved", ["report_date"] = "2026-07-01" } });
        Assert.True(preview.Status == HttpStatusCode.OK, preview.Body?.ToJsonString());
        var checksum = (string)preview.Body!["model_checksum"]!;
        Assert.Equal(13, preview.Body["sections"]!.AsArray().Count);
        foreach (var kind in new[] { "pdf", "docx" })
        {
            var request = new HttpRequestMessage(HttpMethod.Post, $"/api/sod/reports/{kind}")
            {
                Content = new StringContent(new JsonObject { ["period_id"] = id, ["expected_model"] = checksum, ["options"] = new JsonObject { ["status"] = "Approved", ["report_date"] = "2026-07-01" } }.ToJsonString(), Encoding.UTF8, "application/json"),
            };
            request.Headers.Add("Origin", _client.BaseAddress!.GetLeftPart(UriPartial.Authority));
            var response = await _client.SendAsync(request);
            Assert.True(response.IsSuccessStatusCode, await response.Content.ReadAsStringAsync());
            var bytes = await response.Content.ReadAsByteArrayAsync();
            Assert.Equal(checksum, response.Headers.GetValues("X-SAP-Lens-Report-Model").Single());
            Assert.Equal(Convert.ToHexStringLower(System.Security.Cryptography.SHA256.HashData(bytes)), response.Headers.GetValues("X-SAP-Lens-File-SHA256").Single());
            Assert.True(kind == "pdf" ? bytes.AsSpan(0, 5).SequenceEqual("%PDF-"u8) : bytes[0] == (byte)'P' && bytes[1] == (byte)'K');
        }
        var stale = await Post("/api/sod/reports/pdf", new JsonObject { ["period_id"] = id, ["expected_model"] = new string('0', 64), ["options"] = new JsonObject { ["report_date"] = "2026-07-01" } });
        Assert.Equal(HttpStatusCode.Conflict, stale.Status);
        var remediation = await Post("/api/sod/reports/remediation/preview", new JsonObject { ["context"] = id });
        Assert.True(remediation.Status == HttpStatusCode.OK, remediation.Body?.ToJsonString());
        Assert.Equal("remediation", (string)remediation.Body!["kind"]!);
        Assert.Equal(HttpStatusCode.UnprocessableEntity, (await Post("/api/sod/reports/preview", new JsonObject { ["period_id"] = (string)later["id"]!, ["options"] = new JsonObject { ["status"] = "Approved" } })).Status);
        Assert.Equal(2, (int)(await Get($"/api/sod/periods/{id}/deletion-impact"))["counts"]!["reports"]!);

        // Deletion: an approved period is archived (reason and history confirmation required); the empty draft is erased.
        var impact = await Get($"/api/sod/periods/{id}/deletion-impact");
        Assert.Equal("archive", (string)impact["mode"]!);
        Assert.True((bool)impact["requires_reason"]!);
        Assert.Equal(HttpStatusCode.UnprocessableEntity, (await Post($"/api/sod/periods/{id}/delete", new JsonObject { ["expected_revision"] = await Revision(), ["confirm_name"] = "Q2 2026", ["confirm_impact"] = true, ["confirm_history"] = true })).Status);
        var archived = await Post($"/api/sod/periods/{id}/delete", new JsonObject
        {
            ["expected_revision"] = await Revision(), ["confirm_name"] = "Q2 2026", ["confirm_impact"] = true, ["confirm_history"] = true, ["reason"] = "Superseded by Q3",
        });
        Assert.True(archived.Status == HttpStatusCode.OK, archived.Body?.ToJsonString());
        Assert.Equal("archived", (string)archived.Body!["deleted"]!["mode"]!);
        Assert.Equal(HttpStatusCode.NotFound, (await _client.GetAsync($"/api/sod/context?context={id}")).StatusCode);
        Assert.Equal(2, (await Get("/api/sod/periods?include_archived=true"))["items"]!.AsArray().Count);
        var laterId = (string)later["id"]!;
        Assert.Equal("permanent", (string)(await Get($"/api/sod/periods/{laterId}/deletion-impact"))["mode"]!);
        var erased = await Post($"/api/sod/periods/{laterId}/delete", new JsonObject { ["expected_revision"] = await Revision(), ["confirm_name"] = "Q3 2026" }); Assert.True(erased.Status == HttpStatusCode.OK, erased.Body?.ToJsonString());
        var after = await Get("/api/sod/periods?include_archived=true");
        Assert.Single(after["items"]!.AsArray());
        Assert.Equal(2, after["deletions"]!.AsArray().Count);
    }

    [Fact]
    public async Task Period_validation_concurrency_and_overview()
    {
        Assert.Equal(HttpStatusCode.UnprocessableEntity, (await Post("/api/sod/periods", new JsonObject { ["name"] = "Bad", ["start"] = "2026-06-01", ["end"] = "2026-01-01", ["evaluation_date"] = "2026-03-01", ["expected_revision"] = 0 })).Status);
        Assert.Equal(HttpStatusCode.Conflict, (await Post("/api/sod/periods", new JsonObject { ["name"] = "Stale", ["start"] = "2026-01-01", ["end"] = "2026-12-31", ["evaluation_date"] = "2026-06-01", ["expected_revision"] = 7 })).Status);
        var period = await Create("Q4");
        Assert.Equal(HttpStatusCode.UnprocessableEntity, (await Transition((string)period["id"]!, "Approved")).Status);   // not a transition from Draft
        var overview = await Get("/api/sod/overview");
        Assert.True((bool)overview["governance"]!["available"]!);
        Assert.Equal(90, (int)overview["governance"]!["users_with_conflicts"]!);
        Assert.Equal("Q4", (string)overview["governance"]!["periods"]![0]!["name"]!);
        Assert.Equal(146, (int)overview["counts"]!["user_findings"]!);
        Assert.Equal(HttpStatusCode.NotFound, (await _client.GetAsync("/api/sod/context?context=0123456789abcdef0123456789abcdef")).StatusCode);
    }

    [Fact]
    public async Task A_shared_access_token_cannot_change_period_state()
    {
        var id = (string)(await Create("Shared"))["id"]!;
        _client.Dispose();
        await _app.StopAsync();
        await _app.DisposeAsync();
        await StartAsync(HostMode.Server, false);
        var (status, _) = await Transition(id, "In review");
        Assert.Equal(HttpStatusCode.Forbidden, status);
    }
}
