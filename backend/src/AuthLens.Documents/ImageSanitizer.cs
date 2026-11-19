using SkiaSharp;

namespace AuthLens.Documents;

public enum ImageFormat { Png, Jpeg, Webp }

/// <summary>An untrusted image that cannot be accepted; the message is safe to show (v1 wording).</summary>
public sealed class ImageRejectedException(string message) : Exception(message);

/// <summary>Port of branding.sanitize_image: untrusted raster images are size-checked, identified from their content (never their name), bounded
/// (1..4096 pixels per side, a single frame), decoded once and re-encoded as a fresh RGBA PNG without any metadata, downscaled to fit 1024 (512 when the
/// PNG would exceed 2 MB). Nothing of the input except its pixels reaches the output.</summary>
public static class ImageSanitizer
{
    public const int MaxImageBytes = 2_000_000;
    public static readonly IReadOnlySet<ImageFormat> LogoFormats = new HashSet<ImageFormat> { ImageFormat.Png, ImageFormat.Jpeg, ImageFormat.Webp };
    public static readonly IReadOnlySet<ImageFormat> ReportFormats = new HashSet<ImageFormat> { ImageFormat.Png, ImageFormat.Jpeg };

    private static string Limit(int maxBytes) => maxBytes >= 1_000_000 ? $"{maxBytes / 1_000_000} MB" : $"{maxBytes / 1000} KB";

    public static byte[] Sanitize(ReadOnlySpan<byte> data, IReadOnlySet<ImageFormat>? formats = null, int maxBytes = MaxImageBytes, int minSide = 1)
    {
        formats ??= LogoFormats;
        if (data.Length > maxBytes) throw new ImageRejectedException($"Logo must be at most {Limit(maxBytes)}.");
        var undecodable = "Logo could not be decoded safely. Choose a valid PNG, JPEG or WebP.";
        using var stream = new SKMemoryStream(data.ToArray());
        using var codec = SKCodec.Create(stream) ?? throw new ImageRejectedException(undecodable);
        ImageFormat? format = codec.EncodedFormat switch
        {
            SKEncodedImageFormat.Png => ImageFormat.Png, SKEncodedImageFormat.Jpeg => ImageFormat.Jpeg, SKEncodedImageFormat.Webp => ImageFormat.Webp, _ => null,
        };
        if (format is null || !formats.Contains(format.Value))
            throw new ImageRejectedException(formats.Contains(ImageFormat.Webp) ? "Use PNG, JPEG or WebP; SVG is not accepted." : "Use a PNG or JPEG image; SVG and WebP are not accepted.");
        var (width, height) = (codec.Info.Width, codec.Info.Height);
        if (width > 4096 || height > 4096 || width < minSide || height < minSide)
            throw new ImageRejectedException($"Logo dimensions must be between {minSide} and 4096 pixels.");
        if (codec.FrameCount > 1) throw new ImageRejectedException("Animated logos are not accepted.");
        // Decode into a fresh, unpremultiplied RGBA bitmap: the only thing carried over from the input.
        using var decoded = new SKBitmap(new SKImageInfo(width, height, SKColorType.Rgba8888, SKAlphaType.Unpremul));
        // A truncated or corrupt stream is refused, never padded (Pillow raises on load()).
        if (codec.GetPixels(decoded.Info, decoded.GetPixels()) != SKCodecResult.Success) throw new ImageRejectedException(undecodable);
        var png = Encode(decoded, 1024);
        return png.Length > MaxImageBytes ? Encode(decoded, 512) : png;
    }

    /// <summary>The pixel size of an already sanitized PNG.</summary>
    public static (int Width, int Height) Size(ReadOnlySpan<byte> png)
    {
        using var codec = SKCodec.Create(new SKMemoryStream(png.ToArray())) ?? throw new ImageRejectedException("Logo could not be decoded safely. Choose a valid PNG, JPEG or WebP.");
        return (codec.Info.Width, codec.Info.Height);
    }

    private static byte[] Encode(SKBitmap source, int box)
    {
        var (width, height) = Thumbnail(source.Width, source.Height, box);
        using var scaled = width == source.Width && height == source.Height
            ? source.Copy()
            : source.Resize(new SKImageInfo(width, height, SKColorType.Rgba8888, SKAlphaType.Unpremul), new SKSamplingOptions(SKCubicResampler.CatmullRom));
        using var image = SKImage.FromBitmap(scaled);
        using var encoded = image.Encode(SKEncodedImageFormat.Png, 100);
        return encoded.ToArray();
    }

    /// <summary>Pillow Image.thumbnail: the largest size within the box that keeps the aspect ratio (Pillow's rounding), never enlarging.</summary>
    public static (int Width, int Height) Thumbnail(int width, int height, int box)
    {
        if (width <= box && height <= box) return (width, height);
        double aspect = width / (double)height;
        static int Round(double number, Func<int, double> key)
        {
            var (low, high) = ((int)Math.Floor(number), (int)Math.Ceiling(number));
            return Math.Max(key(low) <= key(high) ? low : high, 1);
        }
        int x = box, y = box;
        if (x / (double)y >= aspect) x = Round(y * aspect, n => Math.Abs(aspect - n / (double)y));
        else y = Round(x / aspect, n => n == 0 ? 0 : Math.Abs(aspect - x / (double)n));
        return (x, y);
    }
}
