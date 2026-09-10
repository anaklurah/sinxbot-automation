"""
osap/modules/pot_provider.py
────────────────────────────
YouTube PO Token (Proof of Origin) provider using Playwright.

YouTube requires PO tokens for datacenter/VPS IPs. This module uses
the already-installed Playwright (Chromium) to silently extract a valid
PO token by intercepting the YouTube player API request.

The token is cached on disk for a configurable TTL (default 6 hours).
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Optional

from osap.utils.logger import get_logger

logger = get_logger(__name__)

# Token TTL in seconds (6 hours — tokens typically valid 6-24 hours)
_TOKEN_TTL_S = 6 * 3600

# Cache file location
_CACHE_FILE = Path(__file__).resolve().parents[2] / "assets" / "profiles" / "yt_po_token_cache.json"


def _load_cached_token() -> Optional[tuple[str, str]]:
    """Load a cached (po_token, visitor_data) if still valid."""
    if not _CACHE_FILE.exists():
        return None
    try:
        data = json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
        fetched_at = data.get("fetched_at", 0)
        if time.time() - fetched_at < _TOKEN_TTL_S:
            po_token = data.get("po_token")
            visitor_data = data.get("visitor_data")
            if po_token and visitor_data:
                logger.debug("[POT] Using cached PO token (age=%ds)", int(time.time() - fetched_at))
                return po_token, visitor_data
    except Exception as e:
        logger.debug("[POT] Cache read failed: %s", e)
    return None


def _save_cached_token(po_token: str, visitor_data: str) -> None:
    """Save extracted (po_token, visitor_data) to disk cache."""
    try:
        _CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _CACHE_FILE.write_text(
            json.dumps({
                "po_token": po_token,
                "visitor_data": visitor_data,
                "fetched_at": time.time(),
            }, indent=2),
            encoding="utf-8",
        )
        logger.debug("[POT] Cached PO token to %s", _CACHE_FILE.name)
    except Exception as e:
        logger.debug("[POT] Cache write failed: %s", e)


def fetch_po_token(cookie_file: Optional[Path] = None, timeout_ms: int = 20_000) -> Optional[tuple[str, str]]:
    """
    Extract a YouTube PO Token by intercepting the youtubei/v1/player API
    request using Playwright Chromium (headless).

    Returns
    -------
    (po_token, visitor_data) tuple on success, or None on failure.
    """
    # Check cache first
    cached = _load_cached_token()
    if cached:
        return cached

    logger.info("[POT] Fetching fresh PO token via Playwright...")
    import concurrent.futures
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            return executor.submit(_fetch_po_token_worker, cookie_file, timeout_ms).result()
    except Exception as e:
        logger.warning("[POT] Thread execution failed: %s", e)
        return None


def _fetch_po_token_worker(cookie_file: Optional[Path], timeout_ms: int) -> Optional[tuple[str, str]]:
    """Worker executed in dedicated thread without asyncio loop."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.warning("[POT] Playwright not available — cannot fetch PO token.")
        return None

    po_token: Optional[str] = None
    visitor_data: Optional[str] = None

    try:
        with sync_playwright() as p:
            launch_kwargs: dict = {
                "headless": True,
                "args": [
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-extensions",
                ],
            }
            browser = p.chromium.launch(**launch_kwargs)
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/126.0.0.0 Safari/537.36"
                ),
                locale="en-US",
                timezone_id="America/New_York",
            )

            # Inject cookies if available
            if cookie_file and cookie_file.exists():
                try:
                    from osap.modules.publisher.cookie_loader import load_cookies
                    cookies = load_cookies(cookie_file)
                    if cookies:
                        context.add_cookies(cookies)
                        logger.debug("[POT] Injected %d YouTube cookies into Playwright context", len(cookies))
                except Exception as ce:
                    logger.debug("[POT] Cookie injection failed: %s", ce)

            captured: dict = {}

            def _on_request(request) -> None:
                """Intercept YouTube player API requests to extract PO token."""
                nonlocal po_token, visitor_data
                url = request.url
                if "youtubei/v1/player" not in url:
                    return
                try:
                    body_str = request.post_data or ""
                    body = json.loads(body_str)

                    # Extract visitorData from context.client
                    context_data = body.get("context", {})
                    client_data = context_data.get("client", {})
                    vis = client_data.get("visitorData") or body.get("visitorData") or ""

                    # Extract serviceIntegrityDimensions.poToken
                    sid = body.get("serviceIntegrityDimensions", {})
                    pot = sid.get("poToken", "")

                    if pot and vis:
                        captured["po_token"] = pot
                        captured["visitor_data"] = vis
                        logger.debug("[POT] Captured poToken from request: %s...", pot[:20])
                except Exception:
                    pass

            page = context.new_page()
            page.on("request", _on_request)

            # Navigate to a YouTube Shorts page — triggers player API call
            try:
                page.goto("https://www.youtube.com/shorts/dQw4w9WgXcQ", timeout=timeout_ms, wait_until="domcontentloaded")
                # Wait for network to settle
                page.wait_for_timeout(5000)
            except Exception as nav_err:
                logger.debug("[POT] Navigation error (expected on VPS): %s", nav_err)

            if not captured:
                # Fallback: Try the main YouTube page
                try:
                    page.goto("https://www.youtube.com/", timeout=timeout_ms, wait_until="domcontentloaded")
                    page.wait_for_timeout(3000)
                    # Click first video if any
                    try:
                        page.click("a#video-title-link", timeout=3000)
                        page.wait_for_timeout(5000)
                    except Exception:
                        pass
                except Exception:
                    pass

            browser.close()

            if captured.get("po_token") and captured.get("visitor_data"):
                po_token = captured["po_token"]
                visitor_data = captured["visitor_data"]
                _save_cached_token(po_token, visitor_data)
                logger.info("[POT] Successfully extracted PO token via Playwright")
                return po_token, visitor_data
            else:
                logger.warning("[POT] Could not capture PO token from YouTube requests")
                return None

    except Exception as e:
        logger.warning("[POT] PO token extraction failed: %s", e)
        return None


def invalidate_cache() -> None:
    """Remove cached PO token (force fresh extraction on next download)."""
    try:
        _CACHE_FILE.unlink(missing_ok=True)
        logger.info("[POT] PO token cache cleared.")
    except Exception:
        pass
