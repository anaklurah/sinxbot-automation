"""
osap/modules/post_fetcher.py
────────────────────────────
Post-Publish Profile Verification & Latest Content Link Extractor.
Opens the profile/channel of each published platform, extracts the permalink
of the newly published post, validates against stale/pinned/stranger posts,
and formats direct links for notification reporting.
"""

from __future__ import annotations

import asyncio
from typing import Dict, List, Optional

from playwright.async_api import async_playwright, BrowserContext, Page

from osap.modules.publisher import _load_publishers
from osap.utils.logger import get_logger

logger = get_logger("osap.post_fetcher")


async def _fetch_twitter_latest(page: Page) -> Optional[str]:
    logger.info("[fetcher-twitter] Navigating to X/Twitter...")
    try:
        await page.goto("https://x.com/home", wait_until="domcontentloaded", timeout=45_000)
        await asyncio.sleep(2)

        # Resolve authenticated user's handle from sidebar Profile link
        prof_link = page.locator('a[data-testid="AppTabBar_Profile_Link"]').first
        username = None
        if await prof_link.count():
            href = await prof_link.get_attribute("href")
            if href and href.strip("/"):
                username = href.strip("/").split("/")[0]

        if not username:
            prof_fallback = page.locator('a[href*="/"][role="link"]:has([data-testid*="Avatar"])').first
            if await prof_fallback.count():
                href = await prof_fallback.get_attribute("href")
                if href and href.strip("/"):
                    username = href.strip("/").split("/")[0]

        # SAFETY CHECK: If username could not be determined, NEVER inspect the home feed!
        if not username:
            logger.warning("[fetcher-twitter] Could not resolve user handle. Aborting to avoid capturing stranger tweets.")
            return None

        # Navigate strictly to the user's own profile
        profile_url = f"https://x.com/{username}"
        logger.info("[fetcher-twitter] Navigating to user profile: %s", profile_url)
        await page.goto(profile_url, wait_until="domcontentloaded", timeout=35_000)
        await asyncio.sleep(3)

        # Inspect tweets on user profile timeline, explicitly skipping PINNED tweets
        articles = page.locator('article[data-testid="tweet"]')
        count = await articles.count()
        for idx in range(min(count, 5)):
            art = articles.nth(idx)
            # Skip pinned tweet
            social_context = art.locator('[data-testid="socialContext"]').first
            if await social_context.count():
                txt = (await social_context.text_content() or "").lower()
                if "pinned" in txt or "disematkan" in txt:
                    logger.info("[fetcher-twitter] Skipping pinned tweet at index %d", idx)
                    continue

            # Extract status link inside tweet
            status_link = art.locator("time").locator("xpath=..")
            if not await status_link.count():
                status_link = art.locator('a[href*="/status/"]').first

            href = await status_link.get_attribute("href")
            if href and f"/{username}/status/" in href:
                return f"https://x.com{href}" if href.startswith("/") else href

    except Exception as e:
        logger.warning("[fetcher-twitter] Error: %s", e)

    return None


async def _fetch_instagram_latest(page: Page) -> Optional[str]:
    logger.info("[fetcher-instagram] Navigating to Instagram...")
    try:
        await page.goto("https://www.instagram.com/", wait_until="domcontentloaded", timeout=45_000)
        await asyncio.sleep(3)

        # Dismiss any popups
        for btn_text in ["Not Now", "Lain Kali", "Cancel", "Batal"]:
            btn = page.locator(f'button:text-is("{btn_text}")').first
            if await btn.count() and await btn.is_visible():
                await btn.click()
                await asyncio.sleep(1)

        # Locate user profile handle from sidebar
        prof_href = None
        try:
            prof_links = await page.eval_on_selector_all(
                'a[role="link"]',
                """els => els.map(e => ({
                    href: e.getAttribute('href'),
                    imgAlt: e.querySelector('img') ? e.querySelector('img').getAttribute('alt') : ''
                })).filter(e => e.href && e.imgAlt && (
                    e.imgAlt.toLowerCase().includes('profile') || 
                    e.imgAlt.toLowerCase().includes('profil')
                ))"""
            )
            if prof_links and prof_links[0].get('href'):
                prof_href = prof_links[0]['href']
        except Exception:
            pass

        if not prof_href:
            prof_btn = page.locator('a[role="link"]:has-text("Profile"), a[role="link"]:has-text("Profil")').first
            if await prof_btn.count():
                prof_href = await prof_btn.get_attribute("href")

        # SAFETY CHECK: If profile could not be identified, DO NOT search on instagram.com (Home Feed)!
        if not prof_href:
            logger.warning("[fetcher-instagram] Could not identify user profile. Aborting to prevent capturing stranger posts from home feed.")
            return None

        clean_user = prof_href.strip("/").split("/")[0].split("?")[0]
        reels_url = f"https://www.instagram.com/{clean_user}/reels/"
        logger.info("[fetcher-instagram] Navigating to user reels tab: %s", reels_url)
        await page.goto(reels_url, wait_until="domcontentloaded", timeout=45_000)
        await asyncio.sleep(3)

        # On reels tab, inspect reels and skip pinned items
        reel_info = await page.evaluate(r'''() => {
            const anchors = Array.from(document.querySelectorAll('main a[href*="/reel/"], article a[href*="/reel/"]'));
            const results = [];
            for (const a of anchors) {
                const href = a.getAttribute('href') || '';
                if (!href.includes('/reel/')) continue;
                const container = a.closest('div');
                const hasPin = !!(container && (
                    container.querySelector('svg[aria-label*="Pin" i]') ||
                    container.querySelector('svg[aria-label*="Semat" i]') ||
                    container.querySelector('[aria-label*="Pin" i]')
                ));
                results.push({ href: href.split('?')[0], isPinned: hasPin });
            }
            return results;
        }''')

        if reel_info:
            for item in reel_info:
                if not item.get("isPinned"):
                    href = item["href"]
                    return href if href.startswith("http") else f"https://www.instagram.com{href}"
            href = reel_info[0]["href"]
            return href if href.startswith("http") else f"https://www.instagram.com{href}"

    except Exception as exc:
        logger.warning("[fetcher-instagram] Error locating latest post: %s", exc)

    return None


async def _fetch_tiktok_latest(page: Page) -> Optional[str]:
    logger.info("[fetcher-tiktok] Checking TikTok for latest post...")

    # Priority 1: Check TikTok Studio content manager directly
    try:
        logger.info("[fetcher-tiktok] Checking TikTok Studio content list...")
        await page.goto("https://www.tiktok.com/tiktokstudio/content", wait_until="domcontentloaded", timeout=35_000)
        await asyncio.sleep(4)
        studio_href = await page.evaluate(r'''() => {
            const links = Array.from(document.querySelectorAll('a[href*="/video/"]'));
            for (const a of links) {
                const href = a.getAttribute('href') || '';
                const m = href.match(/\/video\/(\d+)/);
                if (m) return href.startsWith('http') ? href.split('?')[0] : `https://www.tiktok.com${href.split('?')[0]}`;
            }
            return null;
        }''')
        if studio_href:
            return studio_href
    except Exception as e:
        logger.debug("[fetcher-tiktok] TikTok Studio check error: %s", e)

    # Priority 2: Navigate strictly to authenticated user's profile
    clean_prof = None
    try:
        await page.goto("https://www.tiktok.com/", wait_until="domcontentloaded", timeout=35_000)
        await asyncio.sleep(2)

        prof_btn = page.locator('a[data-e2e="nav-profile"], a[href*="/@"]:has-text("Profile"), a[href*="/@"]:has-text("Profil")').first
        if await prof_btn.count():
            prof_href = await prof_btn.get_attribute("href")
            if prof_href and "/@" in prof_href:
                clean_prof = prof_href.split("?")[0].strip()
                if not clean_prof.startswith("/"):
                    clean_prof = f"/{clean_prof}"
                logger.info("[fetcher-tiktok] Opening user profile: %s", clean_prof)
                await page.goto(f"https://www.tiktok.com{clean_prof}", wait_until="domcontentloaded", timeout=35_000)
                await asyncio.sleep(3)

        # SAFETY CHECK: If not on user profile (@username), NEVER extract from tiktok.com home feed!
        curr_url = page.url
        if not clean_prof or "/@" not in curr_url:
            logger.warning("[fetcher-tiktok] Not on user profile page (current URL: %s). Aborting to prevent capturing stranger videos.", curr_url)
            return None

        # Extract video from user's profile grid, skipping PINNED videos
        video_url = await page.evaluate(r'''() => {
            const items = Array.from(document.querySelectorAll('div[data-e2e="user-post-item"], div[class*="DivItemContainer"]'));
            for (const item of items) {
                const isPinned = !!(item.querySelector('[data-e2e="video-pin-tag"]') || item.innerText.includes('Pinned') || item.innerText.includes('Disematkan'));
                if (isPinned) continue; // Skip pinned video!

                const a = item.querySelector('a[href*="/video/"]');
                if (a) {
                    const href = a.getAttribute('href') || '';
                    const match = href.match(/\/video\/(\d+)/);
                    if (match) return href.startsWith('http') ? href.split('?')[0] : `https://www.tiktok.com${href.split('?')[0]}`;
                }
            }
            const fallbackLink = document.querySelector('div[data-e2e="user-post-item"] a[href*="/video/"]');
            if (fallbackLink) {
                const href = fallbackLink.getAttribute('href') || '';
                const m = href.match(/\/video\/(\d+)/);
                if (m) return href.startsWith('http') ? href.split('?')[0] : `https://www.tiktok.com${href.split('?')[0]}`;
            }
            return null;
        }''')
        if video_url:
            return video_url
    except Exception as e:
        logger.warning("[fetcher-tiktok] Error extracting TikTok post: %s", e)

    return None


async def _fetch_facebook_latest(page: Page) -> Optional[str]:
    logger.info("[fetcher-facebook] Navigating to Facebook user reels...")
    try:
        await page.goto("https://www.facebook.com/me/reels/", wait_until="domcontentloaded", timeout=40_000)
        await asyncio.sleep(4)

        curr_url = page.url
        if "/login" in curr_url or "checkpoint" in curr_url:
            logger.warning("[fetcher-facebook] Redirected to login page. Aborting.")
            return None

        # Check for user's reels strictly matching /reel/{digits}
        reel_url = await page.evaluate(r'''() => {
            const anchors = Array.from(document.querySelectorAll('a[href*="/reel/"]'));
            for (const a of anchors) {
                const href = a.getAttribute('href') || '';
                if (href.includes('/reels/create') || href.includes('/reel/create') || href.includes('?s=tab')) continue;
                const match = href.match(/\/reel\/(\d+)/);
                if (match && match[1]) {
                    return `https://www.facebook.com/reel/${match[1]}`;
                }
            }
            return null;
        }''')
        if reel_url:
            return reel_url

    except Exception as e:
        logger.warning("[fetcher-facebook] Error: %s", e)

    return None


async def _fetch_upscrolled_latest(page: Page) -> Optional[str]:
    logger.info("[fetcher-upscrolled] Navigating to Upscrolled...")
    try:
        await page.goto("https://upscrolled.com/home", wait_until="domcontentloaded", timeout=45_000)
        await asyncio.sleep(2)

        prof_link = page.locator('a[aria-label="Profile"], a:has-text("Profile"), a[href*="/@"]').first
        prof_href = None
        if await prof_link.count():
            prof_href = await prof_link.get_attribute("href")

        if prof_href and prof_href.startswith("/@"):
            profile_url = f"https://upscrolled.com{prof_href}"
            logger.info("[fetcher-upscrolled] Navigating directly to profile: %s", profile_url)
            await page.goto(profile_url, wait_until="domcontentloaded", timeout=45_000)
        elif await prof_link.count():
            try:
                await prof_link.click()
            except Exception:
                pass
        await asyncio.sleep(3)

        art = page.locator("article").first
        if await art.count():
            anchor = await art.get_attribute("data-home-anchor")
            current_url = page.url
            if anchor and "/@" in current_url:
                username = current_url.split("/@")[1].split("/")[0].split("?")[0]
                direct_link = f"https://upscrolled.com/@{username}/{anchor}"
                logger.info("[fetcher-upscrolled] Found latest post link via anchor: %s", direct_link)
                return direct_link

            try:
                share_btn = art.locator('button[aria-label="Share"]').first
                if await share_btn.count():
                    await share_btn.click()
                    await asyncio.sleep(1)
                    copy_btn = page.locator('div[role="menuitem"]:has-text("Copy link")').first
                    if await copy_btn.count():
                        await copy_btn.click()
                        await asyncio.sleep(1)
                        clipboard_text = await page.evaluate("navigator.clipboard.readText()")
                        if clipboard_text and "upscrolled.com/@" in clipboard_text:
                            return clipboard_text
            except Exception:
                pass

    except Exception as e:
        logger.warning("[fetcher-upscrolled] Error: %s", e)

    # NEVER return page.url if it is the home page
    return None


async def _fetch_febspot_latest(page: Page) -> Optional[str]:
    logger.info("[fetcher-febspot] Navigating to Febspot My Videos...")
    try:
        await page.goto("https://www.febspot.com/my/videos/", wait_until="domcontentloaded", timeout=45_000)
        await asyncio.sleep(3)

        video_link = page.locator('a[href*="/video/"], a[href*="/v/"], .table-responsive a[href*="/video/"]').first
        if await video_link.count():
            href = await video_link.get_attribute("href")
            if href:
                return href if href.startswith("http") else f"https://www.febspot.com{href}"
    except Exception as e:
        logger.warning("[fetcher-febspot] Error: %s", e)
    return None


async def _fetch_youtube_latest(page: Page) -> Optional[str]:
    logger.info("[fetcher-youtube] Resolving YouTube channel...")
    try:
        await page.goto("https://studio.youtube.com", wait_until="domcontentloaded", timeout=40_000)
        await asyncio.sleep(4)

        channel_id = None
        current_url = page.url
        if "/channel/" in current_url:
            channel_id = current_url.split("/channel/")[1].split("/")[0].split("?")[0]

        if not channel_id:
            channel_id = await page.evaluate(r'''() => {
                const a = document.querySelector('a[href*="/channel/"]');
                if (a) {
                    const m = a.href.match(/\/channel\/([^\/\?]+)/);
                    if (m) return m[1];
                }
                return null;
            }''')

        # Priority 1: Public channel shorts page
        if channel_id:
            logger.info("[fetcher-youtube] Found channel ID: %s. Checking public shorts...", channel_id)
            try:
                await page.goto(f"https://www.youtube.com/channel/{channel_id}/shorts", wait_until="domcontentloaded", timeout=35_000)
                await asyncio.sleep(3)

                short_link = await page.evaluate(r'''() => {
                    const anchors = Array.from(document.querySelectorAll('a[href*="/shorts/"]'));
                    for (const a of anchors) {
                        const href = a.getAttribute('href') || '';
                        const m = href.match(/\/shorts\/([a-zA-Z0-9_-]{11})/);
                        if (m && m[1]) {
                            return `https://www.youtube.com/shorts/${m[1]}`;
                        }
                    }
                    return null;
                }''')
                if short_link:
                    return short_link
            except Exception as e:
                logger.debug("[fetcher-youtube] Public shorts check failed: %s", e)

        # Priority 2: Studio shorts content list (specifically /videos/short)
        if channel_id:
            studio_shorts_url = f"https://studio.youtube.com/channel/{channel_id}/videos/short"
            logger.info("[fetcher-youtube] Checking YouTube Studio shorts list: %s", studio_shorts_url)
            await page.goto(studio_shorts_url, wait_until="domcontentloaded", timeout=35_000)
            await asyncio.sleep(4)

            studio_link = await page.evaluate(r'''() => {
                const rows = Array.from(document.querySelectorAll('ytcp-video-row'));
                for (const row of rows) {
                    const a = row.querySelector('a[href*="/video/"]');
                    if (a) {
                        const m = a.getAttribute('href').match(/\/video\/([^\/]+)\/edit/);
                        if (m && m[1]) return `https://www.youtube.com/shorts/${m[1]}`;
                    }
                }
                return null;
            }''')
            if studio_link:
                return studio_link

    except Exception as e:
        logger.warning("[fetcher-youtube] Error: %s", e)

    return None


_EXTRACTORS = {
    "twitter": _fetch_twitter_latest,
    "x": _fetch_twitter_latest,
    "twitter_nsfw": _fetch_twitter_latest,
    "instagram": _fetch_instagram_latest,
    "tiktok": _fetch_tiktok_latest,
    "facebook": _fetch_facebook_latest,
    "upscrolled": _fetch_upscrolled_latest,
    "febspot": _fetch_febspot_latest,
    "youtube": _fetch_youtube_latest,
}


async def fetch_latest_post_url(platform: str, target_key: Optional[str] = None, account_id: int = 1) -> Optional[str]:
    """
    Launch the platform's browser session, navigate to the user profile,
    and extract the latest post/video URL.
    """
    target_key = target_key or platform
    base_platform = platform.lower().split("_")[0]

    extractor = _EXTRACTORS.get(base_platform) or _EXTRACTORS.get(platform)
    if not extractor:
        logger.warning("[fetcher] No latest link extractor for platform: %s", platform)
        return None

    registry = _load_publishers()
    publisher_cls = registry.get(base_platform) or registry.get(platform)
    if not publisher_cls:
        logger.warning("[fetcher] Publisher class not found for: %s", platform)
        return None

    try:
        publisher = publisher_cls(account_id=account_id, target_key=target_key)
        async with async_playwright() as pw:
            context: BrowserContext = await publisher._get_context(pw)
            page: Page = context.pages[0] if context.pages else await context.new_page()
            try:
                url = await extractor(page)
                if url:
                    logger.info("[fetcher] ✓ Successfully retrieved latest %s post link: %s", target_key, url)
                else:
                    logger.warning("[fetcher] ⚠️ Could not extract latest link for %s", target_key)
                return url
            finally:
                await context.close()
    except Exception as exc:
        logger.warning("[fetcher] Error extracting latest post for %s: %s", target_key, exc)
        return None


async def fetch_all_latest_posts(
    successful_targets: List[Dict[str, any]],
    account_id: int = 1,
    db_path: Optional[str] = None,
) -> Dict[str, str]:
    """
    Sequentially visit profiles of all successfully published targets
    and retrieve their direct content links, rejecting old/stale links.
    """
    results: Dict[str, str] = {}
    if not successful_targets:
        return results

    from osap.config import get_config
    from osap.db.queue import get_existing_upload_urls

    cfg = get_config()
    db_path = db_path or cfg.DB_PATH

    logger.info("[fetcher] 🔍 Starting profile check for %d successful target(s)...", len(successful_targets))

    for target in successful_targets:
        target_key = target.get("target_key") or target.get("platform")
        platform = target.get("platform") or target_key
        target_name = target.get("name") or target_key

        try:
            # Load previously recorded upload_urls for this platform from DB
            existing_urls = get_existing_upload_urls(platform, db_path=db_path)

            url = await fetch_latest_post_url(platform=platform, target_key=target_key, account_id=account_id)

            if url:
                clean_url = url.strip()
                # Deduplication check: Was this URL already recorded from a previous upload?
                if clean_url in existing_urls:
                    logger.warning(
                        "[fetcher] ⚠️ Detected stale link from a PREVIOUS video on %s: %s. Rejecting old post.",
                        target_name, clean_url
                    )
                    results[target_name] = "(Postingan terbaru masih diproses platform / belum muncul di profil)"
                else:
                    results[target_name] = clean_url
            else:
                results[target_name] = "(Link tidak terdeteksi di profil)"
        except Exception as exc:
            logger.error("[fetcher] Failed to get link for %s: %s", target_name, exc)
            results[target_name] = "(Gagal membuka profil)"

    return results
