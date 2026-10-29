"""Untrusted raster images are decoded, bounded and re-encoded without metadata."""
import base64
import hashlib
from io import BytesIO
from pathlib import Path
from PIL import Image, UnidentifiedImageError
from config import atomic_write, config_dir

MAX_IMAGE_BYTES = 2_000_000


def sanitize_image(data: bytes, formats=frozenset({'PNG','JPEG','WEBP'}), max_bytes: int = MAX_IMAGE_BYTES, min_side: int = 1) -> bytes:
    if len(data) > max_bytes: raise ValueError(f'Logo must be at most {max_bytes // 1_000_000 if max_bytes >= 1_000_000 else max_bytes // 1000} {"MB" if max_bytes >= 1_000_000 else "KB"}.')
    try:
        with Image.open(BytesIO(data)) as image:
            if image.format not in formats: raise ValueError('Use PNG, JPEG or WebP; SVG is not accepted.' if 'WEBP' in formats else 'Use a PNG or JPEG image; SVG and WebP are not accepted.')
            if image.width > 4096 or image.height > 4096 or image.width < min_side or image.height < min_side:
                raise ValueError(f'Logo dimensions must be between {min_side} and 4096 pixels.')
            if getattr(image,'n_frames',1) != 1: raise ValueError('Animated logos are not accepted.')
            image.load()
            clean = image.convert('RGBA')
            clean.info.clear()
            clean.thumbnail((1024,1024),Image.Resampling.LANCZOS)
            output = BytesIO()
            clean.save(output,format='PNG')
            if output.tell() > MAX_IMAGE_BYTES:
                clean.thumbnail((512,512),Image.Resampling.LANCZOS)
                output = BytesIO(); clean.save(output,format='PNG')
            return output.getvalue()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValueError('Logo could not be decoded safely. Choose a valid PNG, JPEG or WebP.') from exc


def stage_image(data: bytes):
    png = sanitize_image(data)
    identity = hashlib.sha256(png).hexdigest()
    atomic_write(config_dir() / 'branding' / f'{identity}.png', png)
    return dict(logo_id=identity, data_url='data:image/png;base64,'+base64.b64encode(png).decode())


def image_from_path(path: str):
    file = Path(path)
    if not file.is_absolute() or '://' in path or file.suffix.lower() not in {'.png','.jpg','.jpeg','.webp'}:
        raise ValueError('Choose an absolute PNG, JPEG or WebP file path.')
    if file.stat().st_size > MAX_IMAGE_BYTES: raise ValueError('Logo must be at most 2 MB.')
    with file.open('rb') as stream: data = stream.read(MAX_IMAGE_BYTES+1)
    return stage_image(data)


def logo_bytes(identity: str | None):
    if not identity or len(identity) != 64 or any(c not in '0123456789abcdef' for c in identity): return None
    try:
        file = config_dir() / 'branding' / f'{identity}.png'
        if file.stat().st_size > MAX_IMAGE_BYTES: return None
        with file.open('rb') as stream: data = stream.read(MAX_IMAGE_BYTES+1)
        if hashlib.sha256(data).hexdigest() != identity: return None
        sanitize_image(data)
        return data
    except (OSError, ValueError): return None
