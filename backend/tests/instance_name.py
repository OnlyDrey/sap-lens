"""The single-instance mutex name used by backend/instance.py, read from the source so the smoke script and the application cannot drift apart."""
import re
from pathlib import Path

NAME = re.search(r"CreateMutexW\(None, False, '([^']+)'\)", (Path(__file__).resolve().parents[1] / 'instance.py').read_text(encoding='utf-8')).group(1).replace('\\\\', '\\')
