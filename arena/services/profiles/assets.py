"""Public profile assets served alongside the Community endpoint."""
from pathlib import Path
from urllib.parse import urlsplit
import re

DEFAULT_ICON_PATH = '/ngi/assets/avatar.png'
DEFAULT_ICON_URL = 'http://new.arena.n-gage.com:8194' + DEFAULT_ICON_PATH
DEFAULT_ICON = (Path(__file__).parent / 'assets' / 'avatar.png').read_bytes()


def default_icon_url(authority, secure=False):
    if not authority:
        return DEFAULT_ICON_URL
    parsed = urlsplit('//'+authority)
    if (not parsed.hostname or parsed.username is not None or parsed.password is not None
            or parsed.path or parsed.query or parsed.fragment
            or not re.fullmatch(r'[A-Za-z0-9.\-:\[\]]+', authority)
            or (parsed.port is not None and not 1 <= parsed.port <= 65535)):
        raise ValueError('Invalid profile asset host')
    return ('https://' if secure else 'http://') + authority + DEFAULT_ICON_PATH
