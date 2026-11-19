using System.Globalization;
using System.IO.Compression;
using System.Text;
using System.Text.Json.Nodes;
using DocumentFormat.OpenXml;
using DocumentFormat.OpenXml.Packaging;
using DocumentFormat.OpenXml.Wordprocessing;
using A = DocumentFormat.OpenXml.Drawing;
using DW = DocumentFormat.OpenXml.Drawing.Wordprocessing;
using PIC = DocumentFormat.OpenXml.Drawing.Pictures;
using W = DocumentFormat.OpenXml.Wordprocessing;

namespace AuthLens.Documents;

/// <summary>A report that cannot be rendered; status and message follow v1 (422 coverage or layout, 413 size).</summary>
public sealed class ReportRenderException(int status, string message) : Exception(message)
{
    public int Status { get; } = status;
}

public interface IReportRenderer
{
    string Kind { get; }
    string MediaType { get; }
    /// <summary>Renders a frozen report model (v1 sod_reports.model / remediation_model shape) with its already validated report logo.</summary>
    byte[] Render(JsonObject model, byte[]? logo);
}

/// <summary>Shared text rules of sod_reports.py: XML-safe characters, local dates, the cover lines and the output limit.</summary>
public static class ReportText
{
    public const int MaxOutput = 32 * 1024 * 1024;
    private static readonly System.Threading.Lock RenderLock = new();

    public static string Clean(JsonNode? value)
    {
        var text = value is null ? "" : value is JsonValue v && v.TryGetValue<string>(out var s) ? s : value.ToString();
        var output = new StringBuilder(text.Length);
        foreach (var rune in text.EnumerateRunes())
        {
            var c = rune.Value;
            output.Append(c is '\t' or '\r' or '\n' || c is >= 0x20 and <= 0xD7FF || c is >= 0xE000 and <= 0xFFFD || c is >= 0x10000 and <= 0x10FFFF ? rune.ToString() : "�");
        }
        return output.ToString();
    }

    public static string LocalizedDate(JsonNode? value)
    {
        var text = (string?)value;
        if (string.IsNullOrEmpty(text)) return "—";
        var day = DateOnly.ParseExact(text[..10], "yyyy-MM-dd", CultureInfo.InvariantCulture);
        return $"{day.Day:00}.{day.Month:00}.{day.Year:0000}";
    }

    public static List<string> CoverLines(JsonObject data)
    {
        var o = data["organization"]!;
        var p = data["period"]!;
        return [Clean(o["name"]), Clean(o["platform"]) + " · " + Clean(o["system_id"]) + " / " + Clean(o["client"]), Clean(p["name"]),
            LocalizedDate(p["start"]) + " - " + LocalizedDate(p["end"]), Clean(data["status"]) + " · " + Clean(data["document_version"]), Clean(data["status_statement"]),
            "Prepared by: " + (Clean(data["prepared_by"]) is { Length: > 0 } by ? by : "Not specified"), "Report date: " + LocalizedDate(data["report_date"]), Clean(data["limitation"])];
    }

    public static string References(JsonObject data) =>
        "Snapshot reference: " + ((string)data["snapshot_checksum"]!)[..12] + " · Report model reference: " + ((string)data["model_checksum"]!)[..12];

    /// <summary>render(): one rendering at a time, the v1 error mapping and the 32 MiB limit.</summary>
    public static byte[] Render(IReportRenderer renderer, JsonObject model, byte[]? logo)
    {
        byte[] payload;
        lock (RenderLock)
        {
            try { payload = renderer.Render(model, logo); }
            catch (ReportRenderException) { throw; }
            catch (Exception error) when (error is ArgumentException or InvalidOperationException or IOException or FormatException or KeyNotFoundException or NullReferenceException)
            { throw new ReportRenderException(422, "Report layout could not be generated safely. Exclude appendices or shorten unusually long content and retry."); }
        }
        if (payload.Length > MaxOutput) throw new ReportRenderException(413, "Report exceeds 32 MiB. Exclude detailed appendices and use CSV for evidence.");
        return payload;
    }

    public static byte[] Font(string name)
    {
        using var stream = typeof(ReportText).Assembly.GetManifestResourceStream("AuthLens.Documents.Fonts." + name) ?? throw new InvalidOperationException("font missing");
        using var copy = new MemoryStream();
        stream.CopyTo(copy);
        return copy.ToArray();
    }
}

/// <summary>render_docx: Arial 10 pt, 0.65 in margins, core properties, header with organization, footer with page field, logo, title, cover lines,
/// sections with repeating table headers (8 pt), integrity section; the package is normalized (sorted entries, fixed timestamps) so an identical
/// frozen model renders byte-identically.</summary>
public sealed class DocxReportRenderer : IReportRenderer
{
    public string Kind => "docx";
    public string MediaType => "application/vnd.openxmlformats-officedocument.wordprocessingml.document";

    private static OpenXmlElement[] Some(params OpenXmlElement?[] elements) => elements.OfType<OpenXmlElement>().ToArray();

    private static W.Paragraph Para(string text, string? style = null, bool pageBreakBefore = false)
    {
        var paragraph = new W.Paragraph();
        if (style is not null || pageBreakBefore)
            paragraph.Append(new ParagraphProperties(Some(style is null ? null : new ParagraphStyleId { Val = style }, pageBreakBefore ? new PageBreakBefore() : null)));
        var run = new W.Run();
        var lines = text.Replace("\r\n", "\n").Split('\n');
        for (var i = 0; i < lines.Length; i++)
        {
            if (i > 0) run.Append(new W.Break());
            run.Append(new W.Text(lines[i]) { Space = SpaceProcessingModeValues.Preserve });
        }
        paragraph.Append(run);
        return paragraph;
    }

    private static Style ParagraphStyle(string id, string name, int sizeHalfPoints, bool bold, string? color = null, int before = 0, int after = 120) => new(
        new StyleName { Val = name }, new BasedOn { Val = "Normal" }, new NextParagraphStyle { Val = "Normal" }, new PrimaryStyle(),
        new StyleParagraphProperties(new KeepNext(), new SpacingBetweenLines { Before = before.ToString(CultureInfo.InvariantCulture), After = after.ToString(CultureInfo.InvariantCulture) }),
        new StyleRunProperties(Some(bold ? new Bold() : null, color is null ? null : new W.Color { Val = color }, new FontSize { Val = sizeHalfPoints.ToString(CultureInfo.InvariantCulture) })))
    { Type = StyleValues.Paragraph, StyleId = id };

    public byte[] Render(JsonObject data, byte[]? logo)
    {
        using var stream = new MemoryStream();
        using (var package = WordprocessingDocument.Create(stream, WordprocessingDocumentType.Document))
        {
            var created = DateTime.SpecifyKind(DateTime.Parse((string)data["report_date"]!, CultureInfo.InvariantCulture, DateTimeStyles.AdjustToUniversal), DateTimeKind.Utc);
            // docProps/core.xml written explicitly (fixed part name; the packaging API would name it randomly).
            var core = package.AddCoreFilePropertiesPart();
            var x = (string text) => System.Security.SecurityElement.Escape(text);
            var when = created.ToString("yyyy-MM-dd'T'HH:mm:ss'Z'", CultureInfo.InvariantCulture);
            using (var writer = new StreamWriter(core.GetStream(FileMode.Create), new UTF8Encoding(false)))
                writer.Write("<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?><cp:coreProperties xmlns:cp=\"http://schemas.openxmlformats.org/package/2006/metadata/core-properties\" "
                    + "xmlns:dc=\"http://purl.org/dc/elements/1.1/\" xmlns:dcterms=\"http://purl.org/dc/terms/\" xmlns:xsi=\"http://www.w3.org/2001/XMLSchema-instance\">"
                    + $"<dc:title>{x(ReportText.Clean(data["title"]))}</dc:title><dc:creator>{x(ReportText.Clean(data["prepared_by"]))}</dc:creator>"
                    + $"<dcterms:created xsi:type=\"dcterms:W3CDTF\">{when}</dcterms:created><dcterms:modified xsi:type=\"dcterms:W3CDTF\">{when}</dcterms:modified></cp:coreProperties>");
            var main = package.AddMainDocumentPart();
            var styles = main.AddNewPart<StyleDefinitionsPart>("rIdStyles");
            styles.Styles = new Styles(
                new DocDefaults(new RunPropertiesDefault(new RunPropertiesBaseStyle(new RunFonts { Ascii = "Arial", HighAnsi = "Arial", ComplexScript = "Arial", EastAsia = "Arial" },
                    new FontSize { Val = "20" })), new ParagraphPropertiesDefault(new SpacingBetweenLines { After = "120" })),
                new Style(new StyleName { Val = "Normal" }, new PrimaryStyle()) { Type = StyleValues.Paragraph, StyleId = "Normal", Default = true },
                ParagraphStyle("Title", "Title", 52, false, "17365D", after: 300),
                ParagraphStyle("Heading1", "heading 1", 28, true, "365F91", before: 480, after: 120),
                new Style(new StyleName { Val = "Table Grid" }, new StyleTableProperties(new TableBorders(
                    new TopBorder { Val = BorderValues.Single, Size = 4, Color = "4F81BD" }, new BottomBorder { Val = BorderValues.Single, Size = 4, Color = "4F81BD" },
                    new InsideHorizontalBorder { Val = BorderValues.Single, Size = 2, Color = "D4DAE2" })))
                { Type = StyleValues.Table, StyleId = "TableGrid" });

            var header = main.AddNewPart<HeaderPart>("rIdHeader");
            header.Header = new Header(Para(ReportText.Clean(data["organization"]!["name"]) + " · AuthLens"));
            var footer = main.AddNewPart<FooterPart>("rIdFooter");
            footer.Footer = new Footer(new W.Paragraph(new W.Run(new W.Text("AuthLens · ") { Space = SpaceProcessingModeValues.Preserve }), new SimpleField { Instruction = "PAGE" }));

            var body = new Body();
            if (logo is not null)
            {
                var (w, h) = ImageSanitizer.Size(logo);
                var scale = Math.Min(1.4 / w, 0.9 / h);
                long cx = (long)Math.Round(w * scale * 914400), cy = (long)Math.Round(h * scale * 914400);
                var image = main.AddImagePart(ImagePartType.Png, "rIdLogo");
                using (var png = new MemoryStream(logo)) image.FeedData(png);
                body.Append(new W.Paragraph(new W.Run(new W.Drawing(new DW.Inline(
                    new DW.Extent { Cx = cx, Cy = cy }, new DW.DocProperties { Id = 1U, Name = "Report logo" },
                    new A.Graphic(new A.GraphicData(new PIC.Picture(
                        new PIC.NonVisualPictureProperties(new PIC.NonVisualDrawingProperties { Id = 0U, Name = "logo.png" }, new PIC.NonVisualPictureDrawingProperties()),
                        new PIC.BlipFill(new A.Blip { Embed = main.GetIdOfPart(image) }, new A.Stretch(new A.FillRectangle())),
                        new PIC.ShapeProperties(new A.Transform2D(new A.Offset { X = 0, Y = 0 }, new A.Extents { Cx = cx, Cy = cy }), new A.PresetGeometry { Preset = A.ShapeTypeValues.Rectangle })))
                    { Uri = "http://schemas.openxmlformats.org/drawingml/2006/picture" })) { DistanceFromTop = 0U, DistanceFromBottom = 0U, DistanceFromLeft = 0U, DistanceFromRight = 0U }))));
            }
            body.Append(Para(ReportText.Clean(data["title"]), "Title"));
            foreach (var line in ReportText.CoverLines(data)) body.Append(Para(line));
            body.Append(Para(ReportText.References(data)));
            var firstSection = true;
            foreach (var item in data["sections"]!.AsArray())
            {
                body.Append(Para(ReportText.Clean(item!["title"]), "Heading1", pageBreakBefore: firstSection));
                firstSection = false;
                foreach (var paragraph in item["paragraphs"]!.AsArray()) body.Append(Para(ReportText.Clean(paragraph)));
                foreach (var rowsNode in item["tables"]!.AsArray())
                {
                    var rows = rowsNode!.AsArray();
                    var columns = rows[0]!.AsArray().Count;
                    var table = new W.Table(new TableProperties(new TableStyle { Val = "TableGrid" }, new TableWidth { Type = TableWidthUnitValues.Pct, Width = "5000" }));
                    table.Append(new TableGrid(Enumerable.Range(0, columns).Select(_ => new GridColumn())));
                    for (var r = 0; r < rows.Count; r++)
                    {
                        var row = new TableRow();
                        if (r == 0) row.Append(new TableRowProperties(new TableHeader()));
                        var cells = rows[r]!.AsArray();
                        for (var c = 0; c < columns; c++)
                        {
                            var cell = new TableCell();
                            if (r == 0) cell.Append(new TableCellProperties(new Shading { Val = ShadingPatternValues.Clear, Fill = "E8EDF3" }));
                            var paragraph = Para(ReportText.Clean(c < cells.Count ? cells[c] : null));
                            foreach (var run in paragraph.Elements<W.Run>()) run.PrependChild(new W.RunProperties(Some(new FontSize { Val = "16" }, r == 0 ? new Bold() : null)));
                            cell.Append(paragraph);
                            row.Append(cell);
                        }
                        table.Append(row);
                    }
                    body.Append(table);
                    body.Append(new W.Paragraph());
                }
            }
            body.Append(Para("Document integrity", "Heading1"));
            body.Append(Para("Snapshot SHA-256: " + (string)data["snapshot_checksum"]!));
            body.Append(Para("Report model SHA-256: " + (string)data["model_checksum"]!));
            body.Append(new SectionProperties(
                new HeaderReference { Type = HeaderFooterValues.Default, Id = main.GetIdOfPart(header) }, new FooterReference { Type = HeaderFooterValues.Default, Id = main.GetIdOfPart(footer) },
                new W.PageSize { Width = 11906U, Height = 16838U }, new PageMargin { Top = 936, Bottom = 936, Left = 1440U, Right = 1440U, Header = 720U, Footer = 720U }));
            main.Document = new W.Document(body);
        }
        return Normalize(stream.ToArray());
    }

    /// <summary>Sorted entries with a fixed 1980-01-01 timestamp (v1 normalizes the same way), so the bytes depend only on the content.</summary>
    private static byte[] Normalize(byte[] package)
    {
        using var source = new ZipArchive(new MemoryStream(package), ZipArchiveMode.Read);
        using var output = new MemoryStream();
        using (var target = new ZipArchive(output, ZipArchiveMode.Create, leaveOpen: true))
            foreach (var entry in source.Entries.OrderBy(e => e.FullName, StringComparer.Ordinal))
            {
                var copy = target.CreateEntry(entry.FullName, CompressionLevel.Optimal);
                copy.LastWriteTime = new DateTimeOffset(1980, 1, 1, 0, 0, 0, TimeSpan.Zero);
                using var from = entry.Open();
                using var to = copy.Open();
                if (entry.FullName == "_rels/.rels")
                {
                    // The SDK names package-level relationships randomly; nothing refers to them by id, so they are numbered in order.
                    var rels = System.Xml.Linq.XDocument.Load(from);
                    var n = 0;
                    foreach (var rel in rels.Root!.Elements().OrderBy(e => (string?)e.Attribute("Type"), StringComparer.Ordinal)) rel.SetAttributeValue("Id", "rIdPackage" + ++n);
                    rels.Save(to, System.Xml.Linq.SaveOptions.DisableFormatting);
                }
                else from.CopyTo(to);
            }
        return output.ToArray();
    }
}
