using System.Diagnostics;
using System.IO.Compression;
using System.Text.Json.Nodes;
using DocumentFormat.OpenXml.Packaging;
using AuthLens.Documents;
using SkiaSharp;
using W = DocumentFormat.OpenXml.Wordprocessing;

namespace AuthLens.Tests;

/// <summary>REPORTING_ARCHITECTURE.md evidence: the native renderers and the image sanitizer against Python v1 (tools/reporting_reference.py) on the same
/// synthetic frozen report models and crafted images. PDF text is compared with poppler's pdftotext (an independent parser) where it is installed;
/// SAPLENS_REPORT_OUT=dir keeps the generated files for manual and python-docx review.</summary>
public sealed class ReportingTests
{
    private static readonly string Fixtures = Path.Combine(AppContext.BaseDirectory, "Fixtures", "reporting");
    private static readonly JsonObject Reference = JsonNode.Parse(ProductRename.Apply(File.ReadAllText(Path.Combine(Fixtures, "reporting.python.json"))))!.AsObject();
    private static readonly byte[] Logo = File.ReadAllBytes(Path.Combine(Fixtures, "logo.png"));

    private static void Keep(string name, byte[] payload)
    {
        if (Environment.GetEnvironmentVariable("SAPLENS_REPORT_OUT") is { Length: > 0 } dir) { Directory.CreateDirectory(dir); File.WriteAllBytes(Path.Combine(dir, name), payload); }
    }

    private static string? Tool(string name, byte[] input, params string[] args)
    {
        var info = new ProcessStartInfo(name) { RedirectStandardInput = true, RedirectStandardOutput = true, RedirectStandardError = true };
        foreach (var arg in args) info.ArgumentList.Add(arg);
        using var run = Process.Start(info)!;
        var reading = run.StandardOutput.ReadToEndAsync();
        run.StandardInput.BaseStream.Write(input);
        run.StandardInput.Close();
        run.WaitForExit(60000);
        return reading.Result;
    }

    private static bool Installed(string name) => (Environment.GetEnvironmentVariable("PATH") ?? "").Split(Path.PathSeparator).Any(p => File.Exists(Path.Combine(p, name)));

    [Fact]
    public void Image_sanitizing_follows_v1_for_every_crafted_image()
    {
        var files = Directory.GetFiles(Path.Combine(Fixtures, "images")).ToDictionary(f => Path.GetFileName(f), File.ReadAllBytes);
        files["big-file.png"] = [.. new byte[] { 0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A }, .. new byte[2_000_100]];
        var compared = 0;
        foreach (var (key, expected) in Reference["images"]!.AsObject())
        {
            var (file, profile) = (key.Split('|')[0], key.Split('|')[1]);
            byte[]? output = null;
            string? error = null;
            try
            {
                output = profile == "logo" ? ImageSanitizer.Sanitize(files[file!])
                    : ImageSanitizer.Sanitize(files[file!], ImageSanitizer.ReportFormats, 1_000_000, 32);
            }
            catch (ImageRejectedException rejected) { error = rejected.Message; }
            if (!(bool)expected!["ok"]!) { Assert.True(error == (string)expected["error"]!, $"{key}: expected '{expected["error"]}', got '{error ?? "accepted"}'"); compared++; continue; }
            Assert.True(output is not null, $"{key}: refused '{error}'");
            using var codec = SKCodec.Create(new SKMemoryStream(output));
            Assert.Equal(SKEncodedImageFormat.Png, codec.EncodedFormat);
            Assert.Equal(expected["size"]!.AsArray().Select(n => (int)n!), new[] { codec.Info.Width, codec.Info.Height });
            Assert.True(codec.FrameCount <= 1);                                               // Skia reports 0 for a still image
            // No metadata chunk survives: only the critical chunks of an RGBA PNG.
            var chunks = new List<string>();
            for (var i = 8; i + 8 <= output!.Length;)
            {
                var length = (output[i] << 24) | (output[i + 1] << 16) | (output[i + 2] << 8) | output[i + 3];
                chunks.Add(System.Text.Encoding.ASCII.GetString(output, i + 4, 4));
                i += 12 + length;
            }
            // sBIT (significant bits) is written by the encoder itself; no ancillary chunk is copied from the input.
            Assert.True(chunks.All(c => c is "IHDR" or "IDAT" or "IEND" or "sBIT"), $"{key}: {string.Join(',', chunks)}");
            Assert.Equal(6, output[25]);                                                      // colour type 6: RGBA
            Assert.Equal(output, profile == "logo" ? ImageSanitizer.Sanitize(files[file!]) : ImageSanitizer.Sanitize(files[file!], ImageSanitizer.ReportFormats, 1_000_000, 32));
            compared++;
        }
        Assert.Equal(26, compared);
    }

    [Theory]
    [InlineData(1600, 900, 1024, 1024, 576)]
    [InlineData(3000, 200, 1024, 1024, 68)]
    [InlineData(333, 1000, 512, 170, 512)]
    [InlineData(5000, 3, 1024, 1024, 1)]
    [InlineData(7, 4096, 1024, 2, 1024)]
    [InlineData(1001, 999, 1024, 1001, 999)]
    [InlineData(40, 40, 1024, 40, 40)]
    public void Thumbnail_sizes_follow_pillow(int width, int height, int box, int expectedWidth, int expectedHeight) =>
        Assert.Equal((expectedWidth, expectedHeight), ImageSanitizer.Thumbnail(width, height, box));

    private static JsonObject Model(string name) => Reference["reports"]![name]!["model"]!.DeepClone().AsObject();

    [Fact]
    public void Pdf_reports_carry_the_v1_content_metadata_and_coverage_rules()
    {
        var poppler = Installed("pdftotext") && Installed("pdfinfo");
        foreach (var (name, entry) in Reference["reports"]!.AsObject())
        {
            var expected = entry!["pdf"]!;
            var model = Model(name);
            var logo = model["logo_id"] is null ? null : Logo;
            if ((int)expected["status"]! != 200)
            {
                var refused = Assert.Throws<ReportRenderException>(() => ReportText.Render(new PdfReportRenderer(), model, logo));
                Assert.Equal(((int)expected["status"]!, (string)expected["detail"]!), (refused.Status, refused.Message));
                continue;
            }
            var pdf = ReportText.Render(new PdfReportRenderer(), model, logo);
            Keep($"{name}.net.pdf", pdf);
            Assert.Equal("%PDF-", System.Text.Encoding.ASCII.GetString(pdf, 0, 5));
            Assert.Equal(pdf, ReportText.Render(new PdfReportRenderer(), Model(name), logo));     // reproducible for an identical frozen model
            if (!poppler) continue;
            var info = Tool("pdfinfo", pdf, "-")!.Split('\n').Where(l => l.Contains(':')).ToDictionary(l => l[..l.IndexOf(':')], l => l[(l.IndexOf(':') + 1)..].Trim());
            Assert.Equal((string)expected["title"]!, info["Title"]);
            Assert.Equal((string)expected["author"]!, info["Author"]);
            int pages = int.Parse(info["Pages"]), v1Pages = (int)expected["pages"]!;
            Assert.InRange(pages, Math.Max(1, (int)(v1Pages * 0.7)), (int)Math.Ceiling(v1Pages * 1.3) + 1);
            // The same words in the same numbers; footer words and page numbers depend on the page count and are left out.
            static Dictionary<string, int> Words(IEnumerable<string> words, int pageCount) => words
                .Where(w => w is not ("AuthLens" or "·" or "v1.2") && !(int.TryParse(w, out var n) && n >= 1 && n <= pageCount))
                .GroupBy(w => w).ToDictionary(g => g.Key, g => g.Count());
            var actual = Words(Tool("pdftotext", pdf, "-enc", "UTF-8", "-", "-")!.Split((char[]?)null, StringSplitOptions.RemoveEmptyEntries), pages);
            // v1's words are split; the rename applies to the joined text ("SAP Lens" in the footer becomes the single word "AuthLens").
            var wanted = Words(ProductRename.Apply(string.Join(' ', expected["words"]!.AsArray().Select(w => (string)w!))).Split(' ', StringSplitOptions.RemoveEmptyEntries), v1Pages);
            var missing = wanted.Where(p => actual.GetValueOrDefault(p.Key) != p.Value).Select(p => $"{p.Key}:{p.Value}/{actual.GetValueOrDefault(p.Key)}").ToList();
            var extra = actual.Where(p => !wanted.ContainsKey(p.Key)).Select(p => p.Key).ToList();
            Assert.True(missing.Count == 0 && extra.Count == 0, $"{name}: differs {string.Join(' ', missing.Take(20))} extra {string.Join(' ', extra.Take(20))}");
        }
    }

    [Fact]
    public void Docx_reports_have_the_v1_structure_and_are_reproducible()
    {
        foreach (var (name, entry) in Reference["reports"]!.AsObject())
        {
            var expected = entry!["docx"]!;
            var model = Model(name);
            var logo = model["logo_id"] is null ? null : Logo;
            var docx = ReportText.Render(new DocxReportRenderer(), model, logo);
            Keep($"{name}.net.docx", docx);
            Assert.Equal(docx, ReportText.Render(new DocxReportRenderer(), Model(name), logo));
            using (var zip = new ZipArchive(new MemoryStream(docx)))
                Assert.All(zip.Entries, e => Assert.Equal(new DateTime(1980, 1, 1), e.LastWriteTime.DateTime.Date));
            using var package = WordprocessingDocument.Open(new MemoryStream(docx), false);
            var body = package.MainDocumentPart!.Document!.Body!;
            Assert.Equal(expected["paragraphs"]!.AsArray().Select(p => (string)p!), body.Elements<W.Paragraph>().Select(p => p.InnerText.Length == 0 ? null : string.Concat(p.Descendants().Select(d => d is W.Text t ? t.Text : d is W.Break ? "\n" : ""))).Where(t => !string.IsNullOrEmpty(t)));
            Assert.True(JsonNode.DeepEquals(expected["tables"], new JsonArray([.. body.Elements<W.Table>().Select(t => (JsonNode)new JsonArray([.. t.Elements<W.TableRow>()
                .Select(r => (JsonNode)new JsonArray([.. r.Elements<W.TableCell>().Select(c => (JsonNode)string.Join("\n", c.Elements<W.Paragraph>().Select(p => string.Concat(p.Descendants().Select(d => d is W.Text x ? x.Text : d is W.Break ? "\n" : "")))))]))]))])), name);
            Assert.Equal(expected["header"]!.AsArray().Select(p => (string)p!), package.MainDocumentPart.HeaderParts.Single().Header!.Elements<W.Paragraph>().Select(p => p.InnerText));
            Assert.Equal((string)expected["title"]!, package.PackageProperties.Title);
            Assert.Equal((string)expected["author"]!, package.PackageProperties.Creator);
            Assert.Equal("docProps/core.xml", package.CoreFilePropertiesPart!.Uri.OriginalString.TrimStart('/'));
            Assert.Equal((int)expected["images"]!, package.MainDocumentPart.ImageParts.Count());
            Assert.Contains("PAGE", package.MainDocumentPart.FooterParts.Single().Footer!.OuterXml);
            Assert.All(body.Elements<W.Table>(), t => Assert.NotNull(t.Elements<W.TableRow>().First().TableRowProperties?.GetFirstChild<W.TableHeader>()));   // header row repeats
        }
    }
}
