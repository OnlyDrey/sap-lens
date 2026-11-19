using System.Globalization;
using System.Text;
using System.Text.Json.Nodes;
using SkiaSharp;

namespace AuthLens.Documents;

/// <summary>render_pdf on SkiaSharp's PDF backend: A4, bundled Bitstream Vera (the fonts v1 embeds through ReportLab; characters they cannot show are
/// refused, as v1), logo, cover page, sections with tables whose header row repeats on every page and whose rows split across pages, a footer with the
/// document version and page number on every page, the integrity section and document metadata. Text is real (extractable) PDF text, fonts subset.</summary>
public sealed class PdfReportRenderer : IReportRenderer
{
    public string Kind => "pdf";
    public string MediaType => "application/pdf";

    private const float PageWidth = 595.2756f, PageHeight = 841.8898f, Left = 40, Right = 40, Top = 48, Bottom = 48;
    private const float Width = PageWidth - Left - Right;
    private static readonly SKColor Ink = new(0, 0, 0), HeaderFill = SKColor.Parse("#e8edf3"), HeaderRule = SKColor.Parse("#758296"), RowRule = SKColor.Parse("#d4dae2");
    private static readonly Lazy<SKTypeface> Regular = new(() => SKTypeface.FromData(SKData.CreateCopy(ReportText.Font("Vera.ttf"))));
    private static readonly Lazy<SKTypeface> Bold = new(() => SKTypeface.FromData(SKData.CreateCopy(ReportText.Font("VeraBd.ttf"))));

    public byte[] Render(JsonObject data, byte[]? logo)
    {
        CheckCoverage(data);
        using var output = new MemoryStream();
        var stamp = DateTime.SpecifyKind(DateTime.Parse((string)data["report_date"]!, CultureInfo.InvariantCulture, DateTimeStyles.AdjustToUniversal), DateTimeKind.Utc);
        var metadata = new SKDocumentPdfMetadata
        {
            Title = ReportText.Clean(data["title"]), Author = ReportText.Clean(data["prepared_by"]), Creator = "AuthLens", Producer = "AuthLens",
            Creation = stamp, Modified = stamp, RasterDpi = 72, EncodingQuality = 101,
        };
        using (var document = SKDocument.CreatePdf(output, metadata))
        {
            var layout = new Layout(document, ReportText.Clean(data["document_version"]));
            if (logo is not null)
            {
                var (w, h) = ImageSanitizer.Size(logo);
                var scale = Math.Min(100f / w, 70f / h);
                using var image = SKImage.FromEncodedData(logo);
                layout.Image(image, w * scale, h * scale);
            }
            layout.Paragraph(ReportText.Clean(data["title"]), 18, bold: true, leading: 22, after: 18, center: true);
            foreach (var line in ReportText.CoverLines(data)) layout.Paragraph(line, 9, after: 10);
            layout.Paragraph(ReportText.References(data), 9, after: 10);
            layout.PageBreak();
            foreach (var item in data["sections"]!.AsArray())
            {
                layout.Paragraph(ReportText.Clean(item!["title"]), 18, bold: true, leading: 22, before: 6, after: 6, keepWithNext: true);
                foreach (var paragraph in item["paragraphs"]!.AsArray()) layout.Paragraph(ReportText.Clean(paragraph), 9, after: 8);
                foreach (var rows in item["tables"]!.AsArray())
                {
                    layout.Table(rows!.AsArray().Select(r => r!.AsArray().Select(ReportText.Clean).ToList()).ToList());
                    layout.Space(12);
                }
            }
            layout.Paragraph("Document integrity", 18, bold: true, leading: 22, before: 6, after: 6, keepWithNext: true);
            layout.Paragraph("Snapshot SHA-256: " + (string)data["snapshot_checksum"]!, 9, after: 6);
            layout.Paragraph("Report model SHA-256: " + (string)data["model_checksum"]!, 9, after: 6);
            layout.Finish();
            document.Close();
        }
        return output.ToArray();
    }

    private static void CheckCoverage(JsonObject data)
    {
        var strings = new List<string?> { (string?)data["title"], (string?)data["prepared_by"], (string?)data["period"]!["name"] };
        foreach (var key in new[] { "name", "platform", "system_id", "client" }) strings.Add(data["organization"]![key]?.ToString());
        foreach (var section in data["sections"]!.AsArray())
        {
            strings.Add((string?)section!["title"]);
            strings.AddRange(section["paragraphs"]!.AsArray().Select(p => p?.ToString()));
            strings.AddRange(section["tables"]!.AsArray().SelectMany(t => t!.AsArray().SelectMany(r => r!.AsArray().Select(c => c?.ToString()))));
        }
        var face = Regular.Value;
        if (strings.Any(s => ReportText.Clean(s).EnumerateRunes().Any(r => r.Value is not ('\n' or '\r' or '\t') && face.GetGlyph(r.Value) == 0)))
            throw new ReportRenderException(422, "Some report characters are outside the bundled PDF font coverage. Use editable DOCX for this content or replace unsupported symbols explicitly.");
    }

    /// <summary>A minimal flow layout: wrapped paragraphs, tables with repeating header rows, page breaks and the page footer.</summary>
    private sealed class Layout(SKDocument document, string version)
    {
        private SKCanvas? _canvas;
        private float _y;
        private int _page;

        private SKCanvas Canvas => _canvas ?? NewPage();

        private SKCanvas NewPage()
        {
            if (_canvas is not null) EndPage();
            _canvas = document.BeginPage(PageWidth, PageHeight);
            _page++;
            _y = Top;
            return _canvas;
        }

        private void EndPage()
        {
            using var font = Font(false, 8);
            using var paint = new SKPaint { Color = Ink, IsAntialias = true };
            _canvas!.DrawText("AuthLens · " + version, Left, PageHeight - 26, SKTextAlign.Left, font, paint);
            _canvas.DrawText(_page.ToString(CultureInfo.InvariantCulture), PageWidth - Right, PageHeight - 26, SKTextAlign.Right, font, paint);
            document.EndPage();
            _canvas = null;
        }

        public void Finish() { if (_canvas is null) NewPage(); EndPage(); }
        public void PageBreak() { _ = Canvas; NewPage(); }
        public void Space(float points) => _y += points;
        private bool Fits(float height) => _y + height <= PageHeight - Bottom;

        private static SKFont Font(bool bold, float size) => new((bold ? Bold : Regular).Value, size) { Subpixel = true, LinearMetrics = true, Hinting = SKFontHinting.None, Edging = SKFontEdging.Antialias };

        /// <summary>Word wrap with explicit line breaks kept; a word wider than the line is broken by characters (ReportLab's CJK word wrap in cells).</summary>
        private static List<string> Wrap(string text, SKFont font, float width)
        {
            var lines = new List<string>();
            foreach (var raw in text.Replace("\r\n", "\n").Split('\n'))
            {
                var line = new StringBuilder();
                foreach (var word in raw.Split(' '))
                {
                    var candidate = line.Length == 0 ? word : line + " " + word;
                    if (font.MeasureText(candidate) <= width) { line.Clear().Append(candidate); continue; }
                    if (line.Length > 0) { lines.Add(line.ToString()); line.Clear(); }
                    var rest = word;
                    while (font.MeasureText(rest) > width && rest.Length > 1)
                    {
                        var take = rest.Length - 1;
                        while (take > 1 && font.MeasureText(rest[..take]) > width) take--;
                        lines.Add(rest[..take]);
                        rest = rest[take..];
                    }
                    line.Append(rest);
                }
                lines.Add(line.ToString());
            }
            return lines;
        }

        public void Paragraph(string text, float size, bool bold = false, float? leading = null, float before = 0, float after = 0, bool center = false, bool keepWithNext = false)
        {
            using var font = Font(bold, size);
            using var paint = new SKPaint { Color = Ink, IsAntialias = true };
            var lineHeight = leading ?? 13;
            var lines = Wrap(text, font, Width);
            _y += before;
            // A heading is never left alone at the bottom of a page.
            if (keepWithNext && !Fits(lineHeight * lines.Count + 40)) NewPage();
            foreach (var line in lines)
            {
                if (!Fits(lineHeight)) NewPage();
                Canvas.DrawText(line, center ? PageWidth / 2 : Left, _y + size, center ? SKTextAlign.Center : SKTextAlign.Left, font, paint);
                _y += lineHeight;
            }
            _y += after;
        }

        public void Image(SKImage image, float width, float height)
        {
            if (!Fits(height)) NewPage();
            Canvas.DrawImage(image, SKRect.Create(Left + (Width - width) / 2, _y, width, height), new SKSamplingOptions(SKCubicResampler.CatmullRom));
            _y += height;
        }

        public void Table(List<List<string>> rows)
        {
            if (rows.Count == 0) return;
            const float size = 7.5f, leading = 10, padX = 6, padY = 5;
            var columns = rows[0].Count;
            var column = Width / columns;
            using var font = Font(false, size);
            using var paint = new SKPaint { Color = Ink, IsAntialias = true };
            List<List<string>> Cells(List<string> row) => Enumerable.Range(0, columns).Select(c => Wrap(c < row.Count ? row[c] : "", font, column - 2 * padX)).ToList();
            var header = Cells(rows[0]);
            float Height(List<List<string>> cells) => cells.Max(c => c.Count) * leading + 2 * padY;

            void DrawRow(List<List<string>> cells, int from, int count, bool isHeader)
            {
                var height = count * leading + 2 * padY;
                using var fill = new SKPaint { Color = HeaderFill, Style = SKPaintStyle.Fill };
                using var rule = new SKPaint { Color = isHeader ? HeaderRule : RowRule, StrokeWidth = isHeader ? 0.5f : 0.2f, Style = SKPaintStyle.Stroke };
                if (isHeader) Canvas.DrawRect(Left, _y, Width, height, fill);
                for (var c = 0; c < columns; c++)
                    for (var l = from; l < Math.Min(from + count, cells[c].Count); l++)
                        Canvas.DrawText(cells[c][l], Left + c * column + padX, _y + padY + (l - from) * leading + size, SKTextAlign.Left, font, paint);
                _y += height;
                Canvas.DrawLine(Left, _y, Left + Width, _y, rule);
            }

            void Header() => DrawRow(header, 0, header.Max(c => c.Count), true);

            if (!Fits(Height(header) + leading + 2 * padY)) NewPage();
            Header();
            foreach (var row in rows.Skip(1))
            {
                var cells = Cells(row);
                var lines = cells.Max(c => c.Count);
                var done = 0;
                while (done < lines)
                {
                    var room = (int)Math.Floor((PageHeight - Bottom - _y - 2 * padY) / leading);
                    if (room < 1 || done == 0 && room < lines && lines * leading + 2 * padY <= PageHeight - Top - Bottom - Height(header))
                    {
                        // Start the row on a new page when it fits there whole; otherwise split it across pages (ReportLab splitInRow).
                        NewPage();
                        Header();
                        continue;
                    }
                    var take = Math.Min(room, lines - done);
                    DrawRow(cells, done, take, false);
                    done += take;
                    if (done < lines) { NewPage(); Header(); }
                }
            }
        }
    }
}
