"""
osap/modules/post_fetcher.py
────────────────────────────
Post-Publish Profile Verification & Latest Content Link Extractor.
Opens the profile/channel of each published platform, extracts the permalink
of the latest post, and formats direct links for notification reporting.
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
    await page.goto("https://x.com/home", wait_until="domcontentloaded", timeout=45_000)
    await asyncio.sleep(2)

    # Click Profile button in sidebar
    prof_link = page.locator('a[data-testid="AppTabBar_Profile_Link"]').first
    if await prof_link.count():
        await prof_link.click()
    else:
        prof_fallback = page.locator('a[href*="/"][role="link"]:has([data-testid*="Avatar"])').first
        if await prof_fallback.count():
            await prof_fallback.click()
    await asyncio.sleep(3)

    # First tweet in timeline
    tweet = page.locator('article[data-testid="tweet"]').first
    await tweet.wait_for(state="visible", timeout=15_000)

    # Extract timestamp link inside tweet
    status_link = tweet.locator("time").locator("xpath=..")
    if not await status_link.count():
        status_link = tweet.locator('a[href*="/status/"]').first

    href = await status_link.get_attribute("href")
    if href:
        return f"https://x.com{href}" if href.startswith("/") else href
    return None


async def _fetch_instagram_latest(page: Page) -> Optional[str]:
    logger.info("[fetcher-instagram] Navigating to Instagram...")
    await page.goto("https://www.instagram.com/", wait_until="domcontentloaded", timeout=45_000)
    await asyncio.sleep(3)

    # Dismiss any popups
    for btn_text in ["Not Now", "Lain Kali", "Cancel", "Batal"]:
        btn = page.locator(f'button:text-is("{btn_text}")').first
        if await btn.count() and await btn.is_visible():
            await btn.click()
            await asyncio.sleep(1)

    # Locate user profile link from sidebar:
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

    if prof_href:
        clean_user = prof_href.strip("/")
        logger.info("[fetcher-instagram] Found user profile: %s", clean_user)
        await page.goto(f"https://www.instagram.com/{clean_user}/", wait_until="domcontentloaded", timeout=45_000)
        await asyncio.sleep(3)
    else:
        logger.warning("[fetcher-instagram] Could not identify profile link, staying on current page")

    # Locate latest post or reel on profile grid
    # Notice: Instagram profile grid links have hrefs like "/{username}/reel/{id}/" or "/{username}/p/{id}/" or "/reel/{id}/" or "/p/{id}/"
    post_link = page.locator('main a[href*="/reel/"], main a[href*="/p/"], article a[href*="/reel/"], article a[href*="/p/"]').first
    try:
        await post_link.wait_for(state="attached", timeout=15_000)
        href = await post_link.get_attribute("href")
        if href:
            clean_href = href.split("?")[0]
            return f"https://www.instagram.com{clean_href}" if clean_href.startswith("/") else clean_href
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

    # Priority 2: Navigate to profile
    try:
        await page.goto("https://www.tiktok.com/", wait_until="domcontentloaded", timeout=35_000)
        await asyncio.sleep(2)

        prof_btn = page.locator('a[data-e2e="nav-profile"], a[href*="/@"]:has-text("Profile"), a[href*="/@"]:has-text("Profil")').first
        if await prof_btn.count():
            prof_href = await prof_btn.get_attribute("href")
            if prof_href and prof_href.startswith("/@"):
                clean_prof = prof_href.split("?")[0]
                logger.info("[fetcher-tiktok] Opening user profile: %s", clean_prof)
                await page.goto(f"https://www.tiktok.com{clean_prof}", wait_until="domcontentloaded", timeout=35_000)
                await asyncio.sleep(3)

        # Extract video from profile grid
        video_url = await page.evaluate(r'''() => {
            const anchors = Array.from(document.querySelectorAll('a[href*="/video/"]'));
            for (const a of anchors) {
                const href = a.getAttribute('href') || '';
                const match = href.match(/\/video\/(\d+)/);
                if (match) return href.startsWith('http') ? href.split('?')[0] : `https://www.tiktok.com${href.split('?')[0]}`;
            }
            return null;
        }''')
        if video_url:
            return video_url
    except Exception as e:
        logger.warning("[fetcher-tiktok] Error extracting TikTok post: %s", e)

    return None


async def _fetch_facebook_latest(page: Page) -> Optional[str]:
    logger.info("[fetcher-facebook] Navigating to Facebook profile...")
    try:
        await page.goto("https://www.facebook.com/me", wait_until="domcontentloaded", timeout=40_000)
        await asyncio.sleep(4)

        # Priority 1: Check user's Reels tab
        try:
            reels_tab = page.locator('a[role="tab"]:has-text("Reels"), a:has-text("Reels")').first
            if await reels_tab.count():
                logger.info("[fetcher-facebook] Clicking Reels tab on profile...")
                await reels_tab.click()
                await asyncio.sleep(3)
                await page.evaluate("window.scrollBy(0, 600)")
                await asyncio.sleep(2)

                reel_url = await page.evaluate(r'''() => {
                    const anchors = Array.from(document.querySelectorAll('a[href*="/reel/"]'));
                    for (const a of anchors) {
                        const href = a.getAttribute('href') || '';
                        if (href.includes('?s=tab') || href.includes('/reels/create') || href.includes('/reel/create')) continue;
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
            logger.debug("[fetcher-facebook] Reels tab check failed: %s", e)

        # Priority 2: Check timeline feed posts & videos
        logger.info("[fetcher-facebook] Checking timeline feed for latest post/reel...")
        await page.goto("https://www.facebook.com/me", wait_until="domcontentloaded", timeout=40_000)
        await asyncio.sleep(3)
        await page.evaluate("window.scrollBy(0, 1000)")
        await asyncio.sleep(2)

        post_url = await page.evaluate(r'''() => {
            const anchors = Array.from(document.querySelectorAll('a[href]'));
            for (const a of anchors) {
                const href = a.getAttribute('href') || '';
                if (href.includes('?s=tab') || href.includes('sk=reels') || href.includes('sk=') || href.includes('/reels/create')) continue;
                if (href.includes('/reel/')) {
                    const m = href.match(/\/reel\/(\d+)/);
                    if (m && m[1]) return `https://www.facebook.com/reel/${m[1]}`;
                }
                if (href.includes('/videos/') || href.includes('/posts/') || href.includes('story_fbid=') || href.includes('fbid=')) {
                    const base = href.split('&__cft__')[0].split('?__cft__')[0];
                    return base.startsWith('http') ? base : `https://www.facebook.com${base}`;
                }
            }
            return null;
        }''')
        if post_url:
            return post_url

    except Exception as e:
        logger.warning("[fetcher-facebook] Error: %s", e)

    return None


async def _fetch_upscrolled_latest(page: Page) -> Optional[str]:
    logger.info("[fetcher-upscrolled] Navigating to Upscrolled...")
    await page.goto("https://upscrolled.com/home", wait_until="domcontentloaded", timeout=45_000)
    await asyncio.sleep(2)

    # Locate Profile link (e.g. href="/@username")
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

    # Locate first article on profile
    art = page.locator("article").first
    if await art.count():
        anchor = await art.get_attribute("data-home-anchor")
        current_url = page.url
        if anchor and "/@" in current_url:
            username = current_url.split("/@")[1].split("/")[0].split("?")[0]
            direct_link = f"https://upscrolled.com/@{username}/{anchor}"
            logger.info("[fetcher-upscrolled] Found latest post link via anchor: %s", direct_link)
            return direct_link

        # Fallback: click share button and Copy link
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
                    if clipboard_text and clipboard_text.startswith("http"):
                        return clipboard_text
        except Exception:
            pass

    return page.url


async def _fetch_febspot_latest(page: Page) -> Optional[str]:
    logger.info("[fetcher-febspot] Navigating to Febspot My Videos...")
    await page.goto("https://www.febspot.com/my/videos/", wait_until="domcontentloaded", timeout=45_000)
    await asyncio.sleep(3)

    video_link = page.locator('a[href*="/video/"], a[href*="/v/"], .table-responsive a[href*="/video/"]').first
    if await video_link.count():
        href = await video_link.get_attribute("href")
        if href:
            return href if href.startswith("http") else f"https://www.febspot.com{href}"
    return None


async def _fetch_youtube_latest(page: Page) -> Optional[str]:
    logger.info("[fetcher-youtube] Resolving YouTube channel...")
    try:
        # Navigate to Studio root to resolve channel ID
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

        # Priority 1: Public channel shorts page (instant & reliable)
        if channel_id:
            logger.info("[fetcher-youtube] Found channel ID: %s. Checking public shorts...", channel_id)
            try:
                await page.goto(f"https://www.youtube.com/channel/{channel_id}/shorts", wait_until="domcontentloaded", timeout=35_000)
                await asyncio.sleep(3)

                short_link = await page.evaluate(r'''() => {
                    const anchors = Array.from(document.querySelectorAll('a[href*="/shorts/"]'));
                    for (const a of anchors) {
                        const href = a.getAttribute('href') || '';
                        const m = href.match(/\/shorts\/([a-zA-Z0-9_-]+)/);
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

        # Priority 2: Studio shorts content list
        logger.info("[fetcher-youtube] Checking YouTube Studio shorts content list...")
        studio_shorts_url = f"https://studio.youtube.com/channel/{channel_id}/videos/short" if channel_id else "https://studio.youtube.com"
        await page.goto(studio_shorts_url, wait_until="domcontentloaded", timeout=35_000)
        await asyncio.sleep(4)

        studio_link = await page.evaluate(r'''() => {
            const anchors = Array.from(document.querySelectorAll('a[href*="/video/"], a[href*="/watch"], a[href*="/shorts/"]'));
            for (const a of anchors) {
                const href = a.getAttribute('href') || '';
                const m = href.match(/\/video\/([^\/]+)\/edit/) || href.match(/\/shorts\/([a-zA-Z0-9_-]+)/) || href.match(/v=([a-zA-Z0-9_-]+)/);
                if (m && m[1]) {
                    return `https://www.youtube.com/shorts/${m[1]}`;
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
    account_id: int = 1
) -> Dict[str, str]:
    """
    Sequentially visit profiles of all successfully published targets
    and retrieve their direct content links.
    """
    results: Dict[str, str] = {}
    if not successful_targets:
        return results

    logger.info("[fetcher] 🔍 Starting profile check for %d successful target(s)...", len(successful_targets))

    for target in successful_targets:
        target_key = target.get("target_key") or target.get("platform")
        platform = target.get("platform") or target_key
        target_name = target.get("name") or target_key

        try:
            url = await fetch_latest_post_url(platform=platform, target_key=target_key, account_id=account_id)
            if url:
                results[target_name] = url
            else:
                results[target_name] = "(Link tidak terdeteksi di profil)"
        except Exception as exc:
            logger.error("[fetcher] Failed to get link for %s: %s", target_name, exc)
            results[target_name] = "(Gagal membuka profil)"

    return results