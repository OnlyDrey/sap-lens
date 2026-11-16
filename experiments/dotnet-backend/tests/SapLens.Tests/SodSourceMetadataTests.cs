using System.Text;
using System.Text.Json.Nodes;
using Microsoft.AspNetCore.Builder;
using Microsoft.Extensions.DependencyInjection;
using SapLens.Api;
using SapLens.Application;
using SapLens.Domain.Json;
using SapLens.Domain.Sod;

namespace SapLens.Tests;

/// <summary>Optional SoD columns and risk-definition fingerprints. The expected values in Fixtures/sod/*.python.json were written by Python v1
/// (tools/sod_fingerprints_reference.py: parse_sod and sod_catalogue.definition_version) for the same synthetic CSV files.</summary>
public sealed class SodSourceMetadataTests
{
    private static string Fixture(string name) => Path.Combine(AppContext.BaseDirectory, "Fixtures", "sod", name);

    /// <summary>The importer accepts only .csv paths; the committed fixtures use .sod.txt because the repository ignores *.csv (SAP exports).</summary>
    private static string Csv(string name)
    {
        var target = Path.Combine(Directory.CreateTempSubdirectory("saplens-sodfixture-").FullName, name + ".csv");
        File.Copy(Fixture(name + ".sod.txt"), target);
        return target;
    }

    [Theory]
    [InlineData("with_meta")]
    [InlineData("no_meta")]
    [InlineData("edge")]
    public void Content_hash_metadata_warnings_and_definition_fingerprints_equal_python_v1(string name)
    {
        var (records, report) = Sources.Read(Sources.Sod, Csv(name), CancellationToken.None);
        var dataset = SodSource.Build(records.ToList(), report.Warnings.Where(w => !w.StartsWith("Optional field ", StringComparison.Ordinal)));
        var expected = JsonNode.Parse(File.ReadAllText(Fixture(name + ".python.json")))!;
        Assert.Equal((string)expected["content_hash"]!, dataset.ContentHash);
        Assert.Equal(expected["metadata"]?.ToJsonString() ?? "null", dataset.Metadata is null ? "null" : JsonNode.Parse(CanonicalJson.Serialize(dataset.Metadata.ToJson()))!.ToJsonString());
        Assert.Equal(expected["warnings"]!.AsArray().Select(w => (string)w!), dataset.Warnings);
        foreach (var risk in dataset.Risks)
            Assert.Equal((string)expected["definition_versions"]![(string)risk["risk_id"]!]!, SodCatalogueFingerprint.Of(risk));
    }

    [Fact]
    public void A_file_without_optional_columns_stores_exactly_the_ten_documented_fields()
    {
        var (records, _) = Sources.Read(Sources.Sod, Csv("no_meta"), CancellationToken.None);
        Assert.All(records, r => Assert.Equal(10, r.Count));
        var (withMeta, _) = Sources.Read(Sources.Sod, Csv("with_meta"), CancellationToken.None);
        Assert.Equal(17, withMeta.First().Count); // only the optional columns the file maps
    }

    [Fact]
    public async Task Optional_metadata_survives_import_activation_and_restart()
    {
        var root = Directory.CreateTempSubdirectory("saplens-sodmeta-").FullName;
        try
        {
            var token = HostSettings.NewToken();
            async Task<WebApplication> Start()
            {
                var app = SapLensHost.Build(new HostSettings { DataDirectory = Path.Combine(root, "data"), Port = 0, AccessToken = token, JsonConsoleLogging = false });
                await app.StartAsync();
                return app;
            }
            var app = await Start();
            using (var client = new HttpClient { BaseAddress = new Uri(app.Urls.First()) })
            {
                client.DefaultRequestHeaders.Add(RequestBoundary.TokenHeader, token);
                var job = JsonNode.Parse(await (await client.PostAsync("/api/v1/imports/sod", new StringContent(File.ReadAllText(Fixture("with_meta.sod.txt")), Encoding.UTF8, "text/csv"))).Content.ReadAsStringAsync())!;
                for (var i = 0; i < 200 && (string)JsonNode.Parse(await client.GetStringAsync($"/api/v1/jobs/{(long)job["id"]!}"))!["status"]! != "Completed"; i++) await Task.Delay(50);
            }
            Assert.Equal("Vendor fraud", (await app.Services.GetRequiredService<SnapshotService>().GetAsync()).Sod!.Metadata!.Risks["R001"]["name"]);
            await app.StopAsync();
            await app.DisposeAsync();
            Microsoft.Data.Sqlite.SqliteConnection.ClearAllPools();

            var again = await Start();
            var sod = (await again.Services.GetRequiredService<SnapshotService>().GetAsync()).Sod!;
            var expected = JsonNode.Parse(File.ReadAllText(Fixture("with_meta.python.json")))!;
            Assert.Equal((string)expected["content_hash"]!, sod.ContentHash);
            Assert.Equal("Maintain vendor", sod.Metadata!.Activities["A1"]["name"]);
            await again.StopAsync();
            await again.DisposeAsync();
        }
        finally
        {
            Microsoft.Data.Sqlite.SqliteConnection.ClearAllPools();
            try { Directory.Delete(root, true); } catch (IOException) { }
        }
    }
}
