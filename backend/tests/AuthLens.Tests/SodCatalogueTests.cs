using System.Net;
using System.Net.Http.Json;
using System.Text;
using System.Text.Json.Nodes;
using Microsoft.AspNetCore.Builder;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;
using AuthLens.Api;
using AuthLens.Domain.Json;
using AuthLens.Persistence;

namespace AuthLens.Tests;

/// <summary>SoD risk catalogue (port of sod_catalogue.py, sod_metadata.lookup, sod_reference read). Fixtures/sod/catalogue.python.json was written
/// by Python v1 (tools/sod_catalogue_reference.py) for catalogue.sod.txt and the v1-format annotations in catalogue-storage.v1.json.</summary>
public sealed class SodCatalogueTests : IAsyncLifetime
{
    private static string Fixture(string name) => Path.Combine(AppContext.BaseDirectory, "Fixtures", "sod", name);
    private readonly string _root = Directory.CreateTempSubdirectory("saplens-sodcat-").FullName;
    private readonly string _token = HostSettings.NewToken();
    private WebApplication _app = null!;
    private HttpClient _client = null!;

    public async Task InitializeAsync()
    {
        _app = AuthLensHost.Build(new HostSettings { DataDirectory = Path.Combine(_root, "data"), Port = 0, AccessToken = _token, JsonConsoleLogging = false });
        await _app.StartAsync();
        _client = new HttpClient { BaseAddress = new Uri(_app.Urls.First()) };
        _client.DefaultRequestHeaders.Add(RequestBoundary.TokenHeader, _token);
    }

    public async Task DisposeAsync()
    {
        _client.Dispose();
        await _app.StopAsync();
        await _app.DisposeAsync();
        Microsoft.Data.Sqlite.SqliteConnection.ClearAllPools();
        try { Directory.Delete(_root, true); } catch (IOException) { }
    }

    private async Task Import(string csv)
    {
        var job = JsonNode.Parse(await (await _client.PostAsync("/api/v1/imports/sod", new StringContent(csv, Encoding.UTF8, "text/csv"))).Content.ReadAsStringAsync())!;
        for (var i = 0; i < 200 && (string)JsonNode.Parse(await _client.GetStringAsync($"/api/v1/jobs/{(long)job["id"]!}"))!["status"]! != "Completed"; i++) await Task.Delay(50);
    }

    /// <summary>Migrates the v1 sod-catalogue.json fixture with the real import command (AuthLens.Cli import-v1-sod).</summary>
    private Task<int> SeedV1Storage() => AuthLens.Cli.ImportV1Sod.RunAsync(Path.Combine(_root, "data"), Fixture("catalogue-storage.v1.json"), null);

    private async Task<JsonNode> Get(string path) => JsonNode.Parse(await _client.GetStringAsync(path))!;
    private static string Canonical(JsonNode? node) => CanonicalJson.Serialize(JsonDocumentToObject(node));
    private static object? JsonDocumentToObject(JsonNode? node) => node switch
    {
        null => null,
        JsonObject o => o.ToDictionary(p => p.Key, p => JsonDocumentToObject(p.Value)),
        JsonArray a => a.Select(JsonDocumentToObject).ToList(),
        JsonValue v when v.TryGetValue<bool>(out var b) => b,
        JsonValue v when v.TryGetValue<long>(out var l) => l,
        JsonValue v => v.ToString(),
        _ => node.ToJsonString(),
    };

    [Fact]
    public async Task Catalogue_activities_lookup_and_appearance_equal_python_v1_for_migrated_annotations()
    {
        await Import(File.ReadAllText(Fixture("catalogue.sod.txt")));
        Assert.Equal(0, await SeedV1Storage());
        Assert.Equal(1, await SeedV1Storage()); // existing annotations are never overwritten
        var expected = JsonNode.Parse(File.ReadAllText(Fixture("catalogue.python.json")))!;
        var catalogue = await Get("/api/sod/catalogue?limit=100");
        Assert.Equal(Canonical(expected["catalogue"]!["items"]), Canonical(catalogue["items"]));
        Assert.Equal(Canonical(expected["catalogue"]!["summary"]), Canonical(catalogue["summary"]));
        Assert.Equal(4, (int)catalogue["revision"]!);
        var activities = await Get("/api/sod/catalogue-activities?limit=100");
        Assert.Equal(Canonical(expected["activities"]!["items"]), Canonical(activities["items"]));
        Assert.Equal(Canonical(expected["lookup"]), Canonical(await Get("/api/sod/metadata")));
        Assert.Equal(Canonical(expected["appearance"]), Canonical(await Get("/api/sod/appearance")));
        // A migrated reviewed annotation keeps its status because the fingerprint is identical; a stale one is flagged, not rewritten.
        var f019 = catalogue["items"]!.AsArray().Single(i => (string)i!["risk_id"]! == "F019")!;
        Assert.Equal(("Reviewed", false), ((string)f019["description_review_status"]!, (bool)f019["source_changed"]!));
        Assert.True((bool)catalogue["items"]!.AsArray().Single(i => (string)i!["risk_id"]! == "M002")!["source_changed"]!);
    }

    private async Task<HttpResponseMessage> Post(string path, object body) => await _client.PostAsJsonAsync(path, body);

    [Fact]
    public async Task Edits_are_revisioned_fingerprint_bound_validated_and_persist_across_restart()
    {
        await Import(File.ReadAllText(Fixture("catalogue.sod.txt")));
        var item = (await Get("/api/sod/catalogue/X900"))["item"]!;
        var version = (string)item["definition_version"]!;
        Assert.Equal(HttpStatusCode.NotFound, (await _client.GetAsync("/api/sod/catalogue/NOPE")).StatusCode);
        Assert.Equal(HttpStatusCode.Conflict, (await Post("/api/sod/catalogue/X900", new { expected_revision = 3, definition_version = version, metadata = new { } })).StatusCode);
        Assert.Equal(HttpStatusCode.Conflict, (await Post("/api/sod/catalogue/X900", new { expected_revision = 0, definition_version = new string('a', 64), metadata = new { } })).StatusCode);
        Assert.Equal(HttpStatusCode.UnprocessableEntity, (await Post("/api/sod/catalogue/X900", new { expected_revision = 0, definition_version = version, metadata = new { color = "red" } })).StatusCode);
        Assert.Equal(HttpStatusCode.UnprocessableEntity, (await Post("/api/sod/catalogue/X900", new { expected_revision = 0, definition_version = version, metadata = new { notes = "bad\u0001" } })).StatusCode);
        Assert.Equal(HttpStatusCode.UnprocessableEntity, (await Post("/api/sod/catalogue/X900", new { expected_revision = 0, definition_version = version, metadata = new { unknown = "x" } })).StatusCode);
        var saved = JsonNode.Parse(await (await Post("/api/sod/catalogue/X900", new { expected_revision = 0, definition_version = version, metadata = new { display_name = "  Unsupported pair ", color = "#ABCDEF", description_review_status = "Reviewed" } })).Content.ReadAsStringAsync())!;
        Assert.Equal((1, "Unsupported pair", "#abcdef", "Reviewed"), ((int)saved["revision"]!, (string)saved["item"]!["local"]!["display_name"]!, (string)saved["item"]!["local"]!["color"]!, (string)saved["item"]!["description_review_status"]!));
        Assert.Equal("Unsupported pair", (string)(await Get("/api/sod/appearance"))["risks"]!["X900"]!["name"]!);

        // Bulk disable needs explicit confirmation and keeps the review fingerprints.
        Assert.Equal(HttpStatusCode.UnprocessableEntity, (await Post("/api/sod/catalogue/bulk", new { expected_revision = 1, enabled = false })).StatusCode);
        var bulk = JsonNode.Parse(await (await Post("/api/sod/catalogue/bulk", new { expected_revision = 1, enabled = false, confirm = true })).Content.ReadAsStringAsync())!;
        Assert.Equal((2, 3), ((int)bulk["revision"]!, (int)bulk["updated"]!));
        Assert.Equal(0, (int)(await Get("/api/sod/catalogue"))["summary"]!["enabled"]!);

        var activity = JsonNode.Parse(await (await Post("/api/sod/catalogue-activities/ZZ1", new { expected_revision = 2, metadata = new { display_name = "Local ZZ1" } })).Content.ReadAsStringAsync())!;
        Assert.Equal("Local ZZ1", (string)activity["item"]!["local"]!["display_name"]!);
        Assert.Equal(HttpStatusCode.NotFound, (await Post("/api/sod/catalogue-activities/NOPE", new { expected_revision = 3, metadata = new { } })).StatusCode);

        // A new SoD source without X900: its definition and annotation stay visible as historical; the edit survives a restart.
        await Import("RISK;CRITICITY;TYPE;TEXT;ACTVT1;ACTVT2;ACTIVITY_SLOT;ACTIVITY;TCODE;TTEXT\nF019;High;S;Pay and close;AP01;FI06;ACTVT1;AP01;F110;Payment run\nF019;High;S;Pay and close;AP01;FI06;ACTVT2;FI06;OB52;Periods\n");
        await _app.StopAsync();
        await _app.DisposeAsync();
        Microsoft.Data.Sqlite.SqliteConnection.ClearAllPools();
        _app = AuthLensHost.Build(new HostSettings { DataDirectory = Path.Combine(_root, "data"), Port = 0, AccessToken = _token, JsonConsoleLogging = false });
        await _app.StartAsync();
        _client.Dispose();
        _client = new HttpClient { BaseAddress = new Uri(_app.Urls.First()) };
        _client.DefaultRequestHeaders.Add(RequestBoundary.TokenHeader, _token);
        var historical = (await Get("/api/sod/catalogue/X900"))["item"]!;
        Assert.Equal((false, "Unsupported pair", "Reviewed"), ((bool)historical["current"]!, (string)historical["local"]!["display_name"]!, (string)historical["description_review_status"]!));
        Assert.Equal(2, (int)(await Get("/api/sod/catalogue?current=historical"))["total"]!); // M002 and X900 left the source
        var export = await _client.GetAsync("/api/sod/catalogue/export?current=historical");
        var text = Encoding.UTF8.GetString(await export.Content.ReadAsByteArrayAsync());
        Assert.StartsWith("﻿\"RISK_ID\";\"DISPLAY_NAME\"", text);
        Assert.Contains("\"X900\";\"Unsupported pair\";\"Unsupported\";\"Low\";\"C\";\"No\";\"No\";\"Reviewed\"", text);
        Assert.Contains("[{\"\"activity\"\": \"\"ZZ1\"\", \"\"tcode\"\": \"\"Z01\"\", \"\"ttext\"\": \"\"\"\"}]", text); // v1 json.dumps spacing
    }

    [Fact]
    public async Task Reference_status_reset_and_template_match_python_v1()
    {
        await Import(File.ReadAllText(Fixture("catalogue.sod.txt")));
        var status = await Get("/api/sod/reference");
        // Values computed by Python v1 sod_reference.status() for the same source and the bundled library 1.0.1.
        Assert.Equal((2, 4, 14, 14, 6, 0, "bundled", true, "1.0.1"), ((int)status["matched_risks"]!, (int)status["matched_activities"]!, (int)status["risks"]!, (int)status["activities"]!,
            (int)status["terms"]!, (int)status["revision"]!, (string)status["origin"]!, (bool)status["installed"]!, (string)status["default_version"]!));
        Assert.Equal(["X900"], status["missing_risks"]!.AsArray().Select(v => (string)v!));
        Assert.Equal(["ZZ1", "ZZ2"], status["missing_activities"]!.AsArray().Select(v => (string)v!));
        Assert.Equal((12, 10), (status["unmatched_risks"]!.AsArray().Count, status["unmatched_activities"]!.AsArray().Count));
        Assert.Equal(HttpStatusCode.Conflict, (await Post("/api/sod/reference/reset", new { expected_revision = 5 })).StatusCode);
        Assert.Equal(0, (int)JsonNode.Parse(await (await Post("/api/sod/reference/reset", new { expected_revision = 0 })).Content.ReadAsStringAsync())!["revision"]!); // already the bundled library
        var template = await _client.GetAsync("/api/sod/reference/template");
        Assert.Equal("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", template.Content.Headers.ContentType!.MediaType);
        var bytes = await template.Content.ReadAsByteArrayAsync();
        Assert.Equal((byte)'P', bytes[0]); // ZIP container
        Assert.Equal(File.ReadAllBytes(Path.Combine(AppContext.BaseDirectory, "..", "..", "..", "..", "..", "src", "AuthLens.Api", "V1Reference", "sod-reference-template.xlsx")), bytes);
    }

    [Theory]
    [InlineData("observed_definition", "\"not-a-fingerprint\"")]
    [InlineData("reviewed_definition", "\"ABC\"")]
    [InlineData("unexpected", "1")]
    public async Task The_v1_import_refuses_invalid_files_and_changes_nothing(string field, string value)
    {
        var json = JsonNode.Parse(File.ReadAllText(Fixture("catalogue-storage.v1.json")))!.AsObject();
        json["entries"]!["F019"]![field] = JsonNode.Parse(value);
        var path = Path.Combine(_root, "bad.json");
        File.WriteAllText(path, json.ToJsonString());
        Assert.Equal(1, await AuthLens.Cli.ImportV1Sod.RunAsync(Path.Combine(_root, "data"), path, null));
        Assert.Equal(0, (int)(await Get("/api/sod/catalogue"))["revision"]!);
        var badColor = JsonNode.Parse(File.ReadAllText(Fixture("catalogue-storage.v1.json")))!.AsObject();
        badColor["entries"]!["F019"]!["metadata"]!["color"] = "red";
        Assert.Throws<InvalidDataException>(() => AuthLens.Cli.ImportV1Sod.ValidateCatalogue(badColor));
    }

    private async Task<(HttpStatusCode Status, JsonNode? Body)> Upload(byte[] workbook, int revision, string name = "reference.xlsx")
    {
        var form = new MultipartFormDataContent { { new ByteArrayContent(workbook), "file", name }, { new StringContent(revision.ToString()), "revision" } };
        var response = await _client.PostAsync("/api/sod/reference/upload", form);
        return (response.StatusCode, JsonNode.Parse(await response.Content.ReadAsStringAsync()));
    }

    [Fact]
    public async Task Reference_upload_installs_atomically_keeps_annotations_and_reset_restores_the_bundled_library()
    {
        await Import(File.ReadAllText(Fixture("catalogue.sod.txt")));
        Assert.Equal(0, await SeedV1Storage());
        var annotations = Canonical((await Get("/api/sod/catalogue?limit=100"))["items"]!.AsArray().Select(i => i!["local"]).ToList() is var l ? new JsonArray([.. l.Select(x => x!.DeepClone())]) : null);
        var workbook = File.ReadAllBytes(Path.Combine(AppContext.BaseDirectory, "Fixtures", "sod", "reference", "inline_valid.xlsx.bin"));
        var expectedDigest = (string)JsonNode.Parse(File.ReadAllText(Path.Combine(AppContext.BaseDirectory, "Fixtures", "sod", "reference", "expected.python.json")))!["inline_valid"]!["library"]!["digest"]!;

        var (status, body) = await Upload(File.ReadAllBytes(Path.Combine(AppContext.BaseDirectory, "Fixtures", "sod", "reference", "formula.xlsx.bin")), 0);
        Assert.Equal((HttpStatusCode.UnprocessableEntity, "Formula cells are not supported in reference definitions."), (status, (string?)body!["detail"]));
        Assert.Equal(HttpStatusCode.UnprocessableEntity, (await Upload(workbook, 0, "reference.csv")).Status);
        Assert.Equal(HttpStatusCode.Conflict, (await Upload(workbook, 7)).Status);
        Assert.Equal("bundled", (string)(await Get("/api/sod/reference"))["origin"]!); // nothing changed by the refusals

        (status, body) = await Upload(workbook, 0);
        Assert.Equal(HttpStatusCode.OK, status);
        Assert.Equal(("custom", 1, expectedDigest, 3, 2), ((string)body!["origin"]!, (int)body["revision"]!, (string)body["digest"]!, (int)body["risks"]!, (int)body["activities"]!));
        Assert.Equal(1, (int)(await Upload(workbook, 1)).Body!["revision"]!); // the identical workbook is not installed again
        // The local annotations are untouched; X900 has no local name, so the uploaded library does not supply one (exact identifiers only).
        Assert.Equal(annotations, Canonical(new JsonArray([.. (await Get("/api/sod/catalogue?limit=100"))["items"]!.AsArray().Select(i => i!["local"]!.DeepClone())])));
        Assert.Equal("Local F019", (string)(await Get("/api/sod/metadata"))["risks"]!["F019"]!["name"]!);

        var reset = JsonNode.Parse(await (await Post("/api/sod/reference/reset", new { expected_revision = 1 })).Content.ReadAsStringAsync())!;
        Assert.Equal(("bundled", 2), ((string)reset["origin"]!, (int)reset["revision"]!));
        Assert.Equal("Payment Processing vs. Period Control", (string)(await Get("/api/sod/metadata"))["risks"]!["F019"]!["reference"]!["name"]!);

        // v1 PUT with base64: same rules.
        using var put = new HttpRequestMessage(HttpMethod.Put, "/api/sod/reference") { Content = JsonContent.Create(new { expected_revision = 2, workbook_base64 = "%%%" }) };
        Assert.Equal(HttpStatusCode.UnprocessableEntity, (await _client.SendAsync(put)).StatusCode);
        using var put2 = new HttpRequestMessage(HttpMethod.Put, "/api/sod/reference") { Content = JsonContent.Create(new { expected_revision = 2, workbook_base64 = Convert.ToBase64String(workbook) }) };
        Assert.Equal(3, (int)JsonNode.Parse(await (await _client.SendAsync(put2)).Content.ReadAsStringAsync())!["revision"]!);
    }

    [Fact]
    public void Catalogue_writes_need_administrator_permission()
    {
        Assert.Equal("admin", V1Auth.Permission("POST", "/api/sod/catalogue/F019"));
        Assert.Equal("admin", V1Auth.Permission("POST", "/api/sod/catalogue/bulk"));
        Assert.Equal("admin", V1Auth.Permission("POST", "/api/sod/catalogue-activities/AP01"));
        Assert.Equal("read", V1Auth.Permission("GET", "/api/sod/catalogue"));
        Assert.Equal("admin", V1Auth.Permission("POST", "/api/sod/reference/upload"));
        Assert.Equal("admin", V1Auth.Permission("PUT", "/api/sod/reference"));   // v1 refused every PUT for sessions; AuthLens lets administrators save it
    }
}
