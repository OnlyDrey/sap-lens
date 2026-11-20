using System.Net;
using System.Net.Http.Json;
using System.Text.Json.Nodes;
using Microsoft.AspNetCore.Builder;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;
using AuthLens.Api;
using AuthLens.Domain.Scheduling;

namespace AuthLens.Tests;

/// <summary>MIG-008: cron rules, schedule preview, manual refresh of Dynamic path sources and the scheduled refresh, against Python v1
/// (tools/cron_reference.py) where a comparison is possible and against the v1 contract otherwise.</summary>
public sealed class RefreshTests : IAsyncLifetime
{
    private static readonly string Fixtures = Path.Combine(AppContext.BaseDirectory, "Fixtures");
    private static readonly JsonObject Reference = JsonNode.Parse(File.ReadAllText(Path.Combine(Fixtures, "schedule", "cron.python.json")))!.AsObject();
    private readonly string _root = Directory.CreateTempSubdirectory("saplens-refresh-").FullName;
    private readonly string _token = HostSettings.NewToken();
    // The committed Python reference was generated with local=UTC. Inject the same clock zone;
    // never change the developer PC's timezone or adjust the fixture's expected answers.
    private readonly ManualClock _clock = new(DateTimeOffset.Parse((string)Reference["now"]!, System.Globalization.CultureInfo.InvariantCulture), TimeZoneInfo.Utc);
    private WebApplication _app = null!;
    private HttpClient _client = null!;

    public async Task InitializeAsync()
    {
        _app = AuthLensHost.Build(new HostSettings { DataDirectory = Path.Combine(_root, "data"), Port = 0, AccessToken = _token, JsonConsoleLogging = false, PrincipalName = "operator", Mode = HostMode.Desktop },
            configure: b => b.Services.AddSingleton<TimeProvider>(_clock));
        await _app.StartAsync();
        _client = new HttpClient { BaseAddress = new Uri(_app.Urls.First()) };
        _client.DefaultRequestHeaders.Add(RequestBoundary.TokenHeader, _token);
        _client.DefaultRequestHeaders.Add("Origin", _client.BaseAddress.GetLeftPart(UriPartial.Authority));
    }

    public async Task DisposeAsync()
    {
        _client.Dispose();
        await _app.StopAsync();
        await _app.DisposeAsync();
        Microsoft.Data.Sqlite.SqliteConnection.ClearAllPools();
        try { Directory.Delete(_root, true); } catch (IOException) { }
    }

    private static string Iso(DateTimeOffset value) => V1RefreshSchedule.Iso(value);

    [Fact]
    public void Next_runs_descriptions_and_errors_equal_python_v1()
    {
        var compared = 0;
        foreach (var run in Reference["runs"]!.AsArray())
        {
            var after = DateTimeOffset.Parse((string)run!["after"]!, System.Globalization.CultureInfo.InvariantCulture);
            var actual = CronSchedule.NextRuns((string)run["expression"]!, (string)run["zone"]!, after, 4).Select(Iso);
            Assert.True(run["next"]!.AsArray().Select(n => (string)n!).SequenceEqual(actual), $"{run["expression"]} {run["zone"]} {run["after"]}: {string.Join(", ", actual)}");
            compared++;
        }
        foreach (var item in Reference["describe"]!.AsArray())
        {
            Assert.Equal((string)item!["text"]!, CronSchedule.Describe((string)item["expression"]!, (string)item["zone"]!));
            compared++;
        }
        foreach (var item in Reference["errors"]!.AsArray())
        {
            var expected = (string?)item!["error"];
            var error = Record.Exception(() => CronSchedule.Parse((string)item["expression"]!));
            Assert.Equal(expected, error?.Message);
            compared++;
        }
        var now = DateTimeOffset.Parse((string)Reference["now"]!, System.Globalization.CultureInfo.InvariantCulture);
        foreach (var item in Reference["checks"]!.AsArray())
        {
            try
            {
                var runs = CronSchedule.Check((string)item!["expression"]!, (string)item["zone"]!, now).Select(Iso);
                Assert.Equal(item["runs"]!.AsArray().Select(n => (string)n!), runs);
            }
            catch (ArgumentException error) { Assert.Equal((string?)item!["error"], error.Message); }
            compared++;
        }
        foreach (var item in Reference["daily"]!.AsArray())
        {
            var error = Record.Exception(() => Assert.Equal((string?)item!["cron"], CronSchedule.DailyCron((string)item["time"]!)));
            Assert.Equal((string?)item!["error"], error?.Message);
            compared++;
        }
        Assert.Equal(665 + 57 + 15 + 5 + 7, compared);
    }

    [Fact]
    public async Task Schedule_preview_equals_python_v1_and_invalid_schedules_are_not_saved()
    {
        foreach (var item in Reference["previews"]!.AsArray())
        {
            var response = await _client.PostAsJsonAsync("/api/refresh-schedule/preview", item!["draft"]);
            Assert.Equal(HttpStatusCode.OK, response.StatusCode);
            var actual = JsonNode.Parse(await response.Content.ReadAsStringAsync());
            Assert.True(JsonNode.DeepEquals(item["result"], actual), $"{item["draft"]!.ToJsonString()}\nexpected {item["result"]!.ToJsonString()}\nactual   {actual!.ToJsonString()}");
        }
        var settings = JsonNode.Parse(await _client.GetStringAsync("/api/configuration"))!["settings"]!.AsObject();
        settings["refresh_schedule"] = new JsonObject { ["enabled"] = true, ["mode"] = "cron", ["cron"] = "61 * * * *", ["time"] = "06:00", ["timezone"] = "UTC" };
        var saved = await _client.PostAsJsonAsync("/api/configuration", settings);
        Assert.Equal(HttpStatusCode.UnprocessableEntity, saved.StatusCode);
        Assert.Contains("minute must be between 0 and 59", await saved.Content.ReadAsStringAsync());
    }

    private async Task Select(string source, string path, string mode = "dynamic")
    {
        var revision = (int)JsonNode.Parse(await _client.GetStringAsync("/api/configuration"))!["settings"]!["revision"]!;
        var response = await _client.PostAsJsonAsync($"/api/data-sources/{source}/select", new { path, revision, mode, confirm_anomalies = true });
        Assert.True(response.IsSuccessStatusCode, await response.Content.ReadAsStringAsync());
    }

    private async Task<JsonObject> Refresh()
    {
        var response = await _client.PostAsync("/api/refresh", null);
        var text = await response.Content.ReadAsStringAsync();
        Assert.True(response.IsSuccessStatusCode, text);
        return JsonNode.Parse(text)!.AsObject();
    }

    private static JsonObject Result(JsonObject body, string source) => body["refresh"]!["sources"]!.AsArray().OfType<JsonObject>().Single(r => (string)r["source"]! == source);

    [Theory]
    [InlineData(true, 30, 20, true, true)]
    [InlineData(false, 30, 20, true, false)]
    [InlineData(true, 60, 20, true, false)]
    [InlineData(true, 30, 121, true, false)]
    [InlineData(true, 30, 20, false, true)]
    [InlineData(false, 30, 20, false, false)]
    [InlineData(true, 60, 20, false, false)]
    [InlineData(true, 30, 121, false, false)]
    public async Task Saved_import_policy_controls_refresh_and_explicit_selection(bool enabled, int percent, int minimum, bool refresh, bool held)
    {
        var file = Path.Combine(_root, "policy-roles.csv");
        await File.WriteAllTextAsync(file, Csv.Roles(40));
        await Select("roles", file);
        var settings = JsonNode.Parse(await _client.GetStringAsync("/api/configuration"))!["settings"]!.AsObject();
        settings["import_checks"] = new JsonObject { ["enabled"] = enabled, ["max_drop_percent"] = percent, ["min_previous_records"] = minimum };
        Assert.Equal(HttpStatusCode.OK, (await _client.PostAsJsonAsync("/api/configuration", settings)).StatusCode);
        await File.WriteAllTextAsync(file, Csv.Roles(20));
        if (refresh)
        {
            var result = Result(await Refresh(), "roles");
            Assert.Equal(held ? "failed" : "updated", (string)result["status"]!);
            if (held) Assert.Equal("needs_confirmation", (string)result["category"]!);
        }
        else
        {
            var revision = (int)JsonNode.Parse(await _client.GetStringAsync("/api/configuration"))!["settings"]!["revision"]!;
            var response = await _client.PostAsJsonAsync("/api/data-sources/roles/select", new { path = file, revision, mode = "dynamic" });
            Assert.Equal(held ? HttpStatusCode.Conflict : HttpStatusCode.OK, response.StatusCode);
            if (held) Assert.Contains("import_needs_confirmation", await response.Content.ReadAsStringAsync());
        }
        var catalogue = await _app.Services.GetRequiredService<AuthLens.Application.SnapshotService>().GetAsync();
        Assert.Equal(held ? 40 : 20, catalogue.Catalogue.Roles.Count);
    }

    [Theory]
    [InlineData("{\"enabled\":false,\"max_drop_percent\":0,\"min_previous_records\":20}")]
    [InlineData("{\"enabled\":true,\"max_drop_percent\":96,\"min_previous_records\":20}")]
    [InlineData("{\"enabled\":true,\"max_drop_percent\":30,\"min_previous_records\":-1}")]
    [InlineData("{\"enabled\":\"false\",\"max_drop_percent\":30,\"min_previous_records\":20}")]
    public async Task Invalid_import_policy_is_refused_without_saving(string policy)
    {
        var before = JsonNode.Parse(await _client.GetStringAsync("/api/configuration"))!["settings"]!.AsObject();
        var candidate = before.DeepClone().AsObject(); candidate["import_checks"] = JsonNode.Parse(policy);
        Assert.Equal(HttpStatusCode.UnprocessableEntity, (await _client.PostAsJsonAsync("/api/configuration", candidate)).StatusCode);
        Assert.True(JsonNode.DeepEquals(before, JsonNode.Parse(await _client.GetStringAsync("/api/configuration"))!["settings"]));
    }

    [Fact]
    public async Task A_dynamic_source_whose_export_became_empty_keeps_its_data_on_refresh()
    {
        var file = Path.Combine(_root, "roles.csv");
        File.Copy(Path.Combine(Fixtures, "imports", "report_roles_before.txt"), file);
        await Select("roles", file);
        var before = JsonNode.Parse(await _client.GetStringAsync("/api/roles"))!.AsArray().Count;
        Assert.True(before > 0);
        // The exporter wrote only the header (an interrupted or empty export): the scheduled or manual refresh must not wipe the catalogue.
        File.WriteAllText(file, File.ReadLines(Path.Combine(Fixtures, "imports", "report_roles_before.txt")).First() + "\n");
        var response = await _client.PostAsync("/api/refresh", null);
        var text = await response.Content.ReadAsStringAsync();
        Assert.True(response.IsSuccessStatusCode, text);
        var roles = Result(JsonNode.Parse(text)!.AsObject(), "roles");
        Assert.Equal(("failed", "validation", true), ((string)roles["status"]!, (string)roles["category"]!, (bool)roles["previous_preserved"]!));
        Assert.Equal(before, JsonNode.Parse(await _client.GetStringAsync("/api/roles"))!.AsArray().Count);
    }

    [Fact]
    public async Task Refresh_rereads_dynamic_sources_reports_changes_and_keeps_previous_data_on_failure()
    {
        var file = Path.Combine(_root, "roles.csv");
        File.Copy(Path.Combine(Fixtures, "imports", "report_roles_before.txt"), file);
        await Select("roles", file);

        // Unchanged file: no new revision, the fast path; unconfigured sources are skipped.
        var body = await Refresh();
        Assert.Equal("ok", (string)body["status"]!);
        Assert.True((int)body["cached_roles"]! > 0);
        var roles = Result(body, "roles");
        Assert.Equal("unchanged", (string)roles["status"]!);
        Assert.True((bool)roles["fast_path"]!);
        Assert.Equal(400, (int)roles["unchanged"]!);
        Assert.Equal(["unconfigured", "unconfigured"], new[] { "users", "employees" }.Select(s => (string)Result(body, s)["reason"]!));
        Assert.Equal("Source skipped: unconfigured.", (string)Result(body, "users")["message"]!);
        Assert.Equal("unchanged", (string)body["refresh"]!["status"]!);
        Assert.Equal(1, (int)body["refresh"]!["checked"]!);
        Assert.Null(roles["changes"]);
        var history = JsonNode.Parse(await _client.GetStringAsync("/api/data-sources/history"))!["items"]!.AsArray();
        Assert.Equal("refresh", (string)history[0]!["operation"]!);

        // Changed file: the counts v1 reports for the same change (reports.python.json), and the change report.
        File.Copy(Path.Combine(Fixtures, "imports", "report_roles_after.txt"), file, overwrite: true);
        body = await Refresh();
        roles = Result(body, "roles");
        var v1 = JsonNode.Parse(File.ReadAllText(Path.Combine(Fixtures, "imports", "reports.python.json")))!["roles"]!["pages"]![0]!["source"]!;
        foreach (var key in new[] { "status", "records", "added", "removed", "modified", "unchanged", "ambiguous_identifiers", "missing_identifiers" })
            Assert.True(JsonNode.DeepEquals(v1[key], roles[key]), key);
        Assert.Equal("changed", (string)body["refresh"]!["status"]!);
        var details = JsonNode.Parse(await _client.GetStringAsync($"/api/data-sources/reports/{(string)body["refresh"]!["id"]!}"))!;
        Assert.Equal(11, (int)details["total"]!);
        var lifecycle = JsonNode.Parse(await _client.GetStringAsync("/api/configuration"))!["settings"]!["data_lifecycle"]!;
        Assert.NotNull(lifecycle["last_successful_refresh"]);

        // A suspicious replacement is never activated by a refresh.
        File.WriteAllText(file, string.Join('\n', File.ReadAllLines(Path.Combine(Fixtures, "imports", "report_roles_after.txt")).Take(30)) + "\n");
        body = await Refresh();
        roles = Result(body, "roles");
        Assert.Equal("failed", (string)roles["status"]!);
        Assert.Equal("needs_confirmation", (string)roles["category"]!);
        Assert.True((bool)roles["confirmable"]!);
        Assert.NotEmpty(roles["anomalies"]!.AsArray());
        Assert.Equal("failed", (string)body["refresh"]!["status"]!);
        var cached = (int)body["cached_roles"]!;

        // Invalid and missing files: categorized failures, previous data kept.
        File.WriteAllText(file, "FUNCTION_KEY;TEXT\nFI;x\n");
        roles = Result(await Refresh(), "roles");
        Assert.Equal(("failed", "headers", true), ((string)roles["status"]!, (string)roles["category"]!, (bool)roles["previous_preserved"]!));
        File.Delete(file);
        body = await Refresh();
        roles = Result(body, "roles");
        Assert.Equal(("failed", "missing"), ((string)roles["status"]!, (string)roles["category"]!));
        Assert.Equal("The configured CSV is missing. Reconnect the share or choose an existing file.", (string)roles["message"]!);
        Assert.Equal(cached, (int)body["cached_roles"]!);
        Assert.NotNull(JsonNode.Parse(await _client.GetStringAsync("/api/configuration"))!["settings"]!["data_lifecycle"]!["last_failed_refresh"]);
    }

    [Fact]
    public async Task Static_sources_are_skipped_and_the_scheduler_runs_due_slots_once_and_records_its_outcome()
    {
        var file = Path.Combine(_root, "roles.csv");
        File.Copy(Path.Combine(Fixtures, "imports", "report_roles_before.txt"), file);
        await Select("roles", file, mode: "static");
        Assert.Equal("static", (string)Result(await Refresh(), "roles")["reason"]!);

        var scheduler = _app.Services.GetServices<IHostedService>().OfType<RefreshScheduler>().Single();
        var settings = JsonNode.Parse(await _client.GetStringAsync("/api/configuration"))!["settings"]!.AsObject();
        settings["refresh_schedule"] = new JsonObject { ["enabled"] = true, ["mode"] = "cron", ["cron"] = "*/15 * * * *", ["time"] = "06:00", ["timezone"] = "UTC" };
        Assert.Equal(HttpStatusCode.OK, (await _client.PostAsJsonAsync("/api/configuration", settings)).StatusCode);

        var now = new DateTimeOffset(2026, 11, 16, 8, 1, 0, TimeSpan.Zero);
        Assert.Equal("idle", await scheduler.TickAsync(now, CancellationToken.None));                    // a changed definition starts from now
        Assert.Equal("idle", await scheduler.TickAsync(now.AddMinutes(10), CancellationToken.None));     // 08:15 not reached yet
        Assert.Equal("succeeded", await scheduler.TickAsync(now.AddMinutes(15), CancellationToken.None)); // 08:15 due
        Assert.Equal("idle", await scheduler.TickAsync(now.AddMinutes(16), CancellationToken.None));     // the slot runs once
        // Missed slots (stopped for hours) are skipped, not replayed: one run at the next tick.
        Assert.Equal("succeeded", await scheduler.TickAsync(now.AddHours(5), CancellationToken.None));
        Assert.Equal("idle", await scheduler.TickAsync(now.AddHours(5).AddSeconds(20), CancellationToken.None));

        _clock.Now = now.AddHours(5);
        var status = JsonNode.Parse(await _client.GetStringAsync("/api/refresh-schedule"))!;
        Assert.Equal("succeeded", (string)status["state"]!["last_status"]!);
        Assert.Equal("Refresh completed.", (string)status["state"]!["last_message"]!);
        Assert.Equal(0, (int)status["state"]!["consecutive_failures"]!);
        Assert.Equal(Iso(now.AddHours(5)), (string)status["state"]!["last_success"]!);
        Assert.Equal("Every 15 minutes every day (UTC)", (string)status["description"]!);
        Assert.Equal(5, status["next_runs"]!.AsArray().Count);
        Assert.Equal((string)status["next_runs"]![0]!, (string)status["next_run"]!);
        Assert.Equal("desktop", (string)status["runtime"]!["deployment_mode"]!);
        Assert.True((bool)status["runtime"]!["requires_running_application"]!);
        var diagnostics = JsonNode.Parse(await _client.GetStringAsync("/api/diagnostics"))!["scheduled_refresh"]!;
        Assert.Equal("succeeded", (string)diagnostics["last_status"]!);
        Assert.Equal(Iso(now.AddHours(5)), (string)diagnostics["last_attempt"]!);

        // Disabled: nothing runs, no next run is announced.
        settings = JsonNode.Parse(await _client.GetStringAsync("/api/configuration"))!["settings"]!.AsObject();
        settings["refresh_schedule"]!["enabled"] = false;
        Assert.Equal(HttpStatusCode.OK, (await _client.PostAsJsonAsync("/api/configuration", settings)).StatusCode);
        Assert.Equal("idle", await scheduler.TickAsync(now.AddHours(6), CancellationToken.None));
        Assert.Null(JsonNode.Parse(await _client.GetStringAsync("/api/refresh-schedule"))!["next_run"]);
    }
}
