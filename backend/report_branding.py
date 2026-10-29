"""Report-only logo (PNG or JPEG). Stored privately beside other branding assets, never in release artifacts or configuration packages."""
import base64
import binascii
from datetime import datetime, timezone
import hashlib
import json
from io import BytesIO
import threading
from PIL import Image
from branding import logo_bytes, sanitize_image
from config import atomic_write, config_dir

lock = threading.RLock()
MAX_BYTES = 1_000_000
MIN_SIDE = 32
MAX_SIDE = 4096
FORMATS = frozenset({'PNG', 'JPEG'})
LIMITS = dict(formats=['PNG', 'JPEG'], max_bytes=MAX_BYTES, min_pixels=MIN_SIDE, max_pixels=MAX_SIDE)


def _path():
    return config_dir() / 'report-branding.json'


def _read():
    try:
        value = json.loads(_path().read_text(encoding='utf-8'))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def current_logo_id():
    """Identifier of a still-valid report logo, or None. A missing or altered file falls back to the application logo."""
    identity = _read().get('logo_id')
    return identity if isinstance(identity, str) and logo_bytes(identity) is not None else None


def describe():
    stored = _read()
    identity = current_logo_id()
    if not identity:
        return dict(logo=None, limits=LIMITS)
    png = logo_bytes(identity)
    with Image.open(BytesIO(png)) as image:
        width, height = image.size
    return dict(logo=dict(logo_id=identity, data_url='data:image/png;base64,' + base64.b64encode(png).decode(), width=width, height=height,
                          bytes=len(png), filename=str(stored.get('filename', ''))[:120], updated=stored.get('updated')), limits=LIMITS)


def store(image_base64, filename=''):
    try:
        raw = base64.b64decode(image_base64, validate=True)
    except (binascii.Error, ValueError):
        raise ValueError('The image could not be read. Choose a PNG or JPEG file.') from None
    png = sanitize_image(raw, formats=FORMATS, max_bytes=MAX_BYTES, min_side=MIN_SIDE)
    identity = hashlib.sha256(png).hexdigest()
    with lock:
        atomic_write(config_dir() / 'branding' / f'{identity}.png', png)
        atomic_write(_path(), json.dumps(dict(logo_id=identity, filename=filename[:120], updated=datetime.now(timezone.utc).isoformat())).encode())
    return describe()


def remove():
    with lock:
        try:
            _path().unlink(missing_ok=True)
        except OSError:
            raise ValueError('The report logo could not be removed.') from None
    return describe()
