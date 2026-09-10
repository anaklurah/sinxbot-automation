"""
Cookie loader supporting Netscape format (.txt) and JSON format.
Auto-detects format by file extension and content.

Playwright cookie dict shape:
    {name, value, domain, path, expires, httpOnly, secure, sameSite}
"""
import json
import time
from pathlib import Path
from typing import Any

from osap.utils.logger import get_logger

_log = get_logger(__name__)

# Valid sameSite values accepted by Playwright
_VALID_SAME_SITE = {'Strict', 'Lax', 'None'}

# Mapping from common cookie-file sameSite strings → Playwright values
_SAME_SITE_MAP = {
    'strict': 'Strict',
    'lax': 'Lax',
    'none': 'None',
    'no_restriction': 'None',
    'unspecified': 'Lax',
    '': 'Lax',
}


def _normalise_same_site(raw: str) -> str:
    """Normalise a sameSite string to one of Playwright's accepted values."""
    normalised = _SAME_SITE_MAP.get(raw.lower(), 'Lax')
    return normalised


def _validate_cookie(cookie: dict) -> bool:
    """Return True if *cookie* has the minimum required fields for Playwright."""
    required = ('name', 'value', 'domain')
    for field in required:
        if field not in cookie or cookie[field] is None:
            _log.warning('Skipping invalid cookie — missing field %r: %s', field, cookie)
            return False
    return True


def _build_playwright_cookie(
    name: str,
    value: str,
    domain: str,
    path: str = '/',
    expires: float = -1,
    http_only: bool = False,
    secure: bool = False,
    same_site: str = 'Lax',
) -> dict:
    """Build a fully-formed Playwright cookie dict."""
    s_site = _normalise_same_site(same_site) if same_site not in _VALID_SAME_SITE else same_site
    # Playwright requires Secure: true if SameSite is None
    if s_site == 'None' and not secure:
        s_site = 'Lax'
    return {
        'name': name,
        'value': value,
        'domain': domain,
        'path': path,
        'expires': float(expires) if expires is not None else -1,
        'httpOnly': bool(http_only),
        'secure': bool(secure),
        'sameSite': s_site,
    }


def _parse_json_cookies(raw: Any) -> list[dict]:
    """Parse cookies from a JSON structure.

    Handles:
    - Playwright ``storage_state.json`` format: ``{"cookies": [...], ...}``
    - Raw cookie array: ``[{...}, ...]``
    - Single cookie object: ``{...}``
    """
    if isinstance(raw, dict):
        if 'cookies' in raw:
            items = raw['cookies']
        else:
            items = [raw]
    elif isinstance(raw, list):
        items = raw
    else:
        _log.error('Unrecognised JSON cookie structure: %s', type(raw))
        return []

    results: list[dict] = []
    for item in items:
        if not isinstance(item, dict):
            _log.warning('Skipping non-dict cookie entry: %r', item)
            continue

        cookie = _build_playwright_cookie(
            name=item.get('name', ''),
            value=item.get('value', ''),
            domain=item.get('domain', ''),
            path=item.get('path', '/'),
            expires=item.get('expires', item.get('expirationDate', -1)),
            http_only=item.get('httpOnly', item.get('http_only', False)),
            secure=item.get('secure', False),
            same_site=str(item.get('sameSite', item.get('same_site', 'Lax'))),
        )

        if _validate_cookie(cookie):
            results.append(cookie)

    _log.debug('Parsed %d cookies from JSON source', len(results))
    return results


def _parse_netscape_cookies(text: str) -> list[dict]:
    """Parse cookies from a Netscape/Mozilla cookie file.

    Netscape format (tab-separated, 7 fields):
        [#HttpOnly_]domain  flag  path  secure  expiry  name  value

    Lines starting with ``#`` (except ``#HttpOnly_``) or empty lines are ignored.
    """
    results: list[dict] = []
    for lineno, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue

        http_only = False
        if line.startswith('#HttpOnly_'):
            http_only = True
            line = line[len('#HttpOnly_'):].strip()
        elif line.startswith('#'):
            continue

        parts = line.split('\t', 6)
        if len(parts) == 6:
            parts.append('')
        elif len(parts) < 6:
            space_parts = line.split(None, 6)
            if len(space_parts) == 6:
                space_parts.append('')
            if len(space_parts) >= 7:
                parts = space_parts
            else:
                _log.warning(
                    'Line %d: expected at least 6-7 fields, got %d — skipping: %r',
                    lineno, len(parts), raw_line,
                )
                continue

        domain, flag, path, secure_str, expiry_str, name, value = parts[:7]

        try:
            expiry = float(expiry_str) if expiry_str.strip() else -1
        except ValueError:
            expiry = -1

        secure = secure_str.strip().upper() == 'TRUE'

        cookie = _build_playwright_cookie(
            name=name,
            value=value,
            domain=domain,
            path=path or '/',
            expires=expiry,
            http_only=http_only,
            secure=secure,
            same_site='Lax',
        )

        if _validate_cookie(cookie):
            results.append(cookie)

    _log.debug('Parsed %d cookies from Netscape source', len(results))
    return results


def export_netscape_cookies(cookies: list[dict], out_path: str | Path) -> Path:
    """Export Playwright cookie dicts to Netscape HTTP Cookie File format (yt-dlp/curl compatible).

    Properly marks HttpOnly cookies with '#HttpOnly_' prefix.
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Netscape HTTP Cookie File\n",
        "# http://curl.haxx.se/rfc/cookie_spec.html\n",
        "# Generated by OSAP / Sinxbot Automation\n\n",
    ]
    for c in cookies:
        name = c.get("name")
        value = c.get("value")
        domain = c.get("domain", "")
        if not name or value is None or not domain:
            continue

        path = c.get("path") or "/"
        secure = "TRUE" if c.get("secure") else "FALSE"
        include_subdomains = "TRUE" if domain.startswith(".") else "FALSE"

        exp = c.get("expires", c.get("expirationDate", 0))
        try:
            exp_int = int(float(exp))
        except (ValueError, TypeError):
            exp_int = -1
        if exp_int <= 0:
            exp_int = 2147483647

        http_only = bool(c.get("httpOnly", False))
        prefix = "#HttpOnly_" if http_only else ""

        lines.append(f"{prefix}{domain}\t{include_subdomains}\t{path}\t{secure}\t{exp_int}\t{name}\t{value}\n")

    out_path.write_text("".join(lines), encoding="utf-8")
    return out_path


def load_cookies(path: str | Path) -> list[dict]:
    """Load cookies from *path* and return a list of Playwright cookie dicts.

    Auto-detects format:
    - ``.json`` extension → JSON parser
    - First non-comment/non-empty line starts with ``[`` or ``{`` → JSON parser
    - Otherwise → Netscape tab-separated parser

    Args:
        path: Path to the cookie file (.json, .txt, or extension-less).

    Returns:
        List of Playwright-compatible cookie dicts.

    Raises:
        FileNotFoundError: If *path* does not exist.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f'Cookie file not found: {path}')

    raw_text = path.read_text(encoding='utf-8', errors='replace')

    # Determine format
    use_json = path.suffix.lower() == '.json'

    if not use_json:
        # Peek at the first meaningful line
        for line in raw_text.splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith('#'):
                if stripped.startswith(('[', '{')):
                    use_json = True
                break

    if use_json:
        try:
            data = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            _log.error('Failed to parse %s as JSON: %s', path, exc)
            return []
        return _parse_json_cookies(data)

    return _parse_netscape_cookies(raw_text)


def load_storage_state(path: str | Path) -> dict | None:
    """Load a full Playwright ``storage_state.json`` file.

    Args:
        path: Path to the ``storage_state.json`` file.

    Returns:
        The parsed dict, or ``None`` if the file does not exist or is invalid.
    """
    path = Path(path)
    if not path.exists():
        _log.debug('Storage state file not found: %s', path)
        return None

    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(data, dict):
            _log.warning('Storage state file is not a JSON object: %s', path)
            return None
        _log.debug('Loaded storage state from %s', path)
        return data
    except json.JSONDecodeError as exc:
        _log.error('Failed to parse storage state JSON %s: %s', path, exc)
        return None


async def save_storage_state(context, path: str | Path) -> None:
    """Persist the current browser context's storage state to *path*.

    Args:
        context: A Playwright ``BrowserContext`` instance.
        path: Destination file path (will be created/overwritten).
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    await context.storage_state(path=str(path))
    _log.info('Saved storage state → %s', path)
