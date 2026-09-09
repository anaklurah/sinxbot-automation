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
    logger.info("[fetcher-tiktok] Navigating to TikTok...")
    await page.goto("https://www.tiktok.com/", wait_until="domcontentloaded", timeout=45_000)
    await asyncio.sleep(2)

    # 1. Navigate to user's own profile via sidebar link or header
    prof_btn = page.locator('a[data-e2e="nav-profile"], a[href*="/@"]:has-text("Profile"), a[href*="/@"]:has-text("Profil")').first
    try:
        await prof_btn.wait_for(state="attached", timeout=12_000)
        prof_href = await prof_btn.get_attribute("href")
        if prof_href and prof_href.startswith("/@"):
            clean_prof = prof_href.split("?")[0]
            logger.info("[fetcher-tiktok] Opening user profile directly: %s", clean_prof)
            await page.goto(f"https://www.tiktok.com{clean_prof}", wait_until="domcontentloaded", timeout=45_000)
        else:
            await prof_btn.click()
    except Exception:
        # Fallback: Header avatar dropdown
        avatar = page.locator('div[data-e2e="profile-icon"], img[class*="Avatar"]').first
        if await avatar.count():
            await avatar.click()
            await asyncio.sleep(1.5)
            view_prof = page.locator('a[data-e2e="profile-item"], a:has-text("View profile"), a:has-text("Lihat profil")').first
            if await view_prof.count():
                await view_prof.click()

    await asyncio.sleep(4)

    # If "Something went wrong" / "Refresh" appears, click refresh
    refresh_btn = page.locator('button:text-is("Refresh"), button:text-is("Coba lagi")').first
    if await refresh_btn.count() and await refresh_btn.is_visible():
        await refresh_btn.click()
        await asyncio.sleep(3)

    # 2. Locate first video card on profile
    # Use state="attached" because TikTok video cover anchors use accessibility focus overlays
    video_card = page.locator('div[data-e2e="user-post-item"] a[href*="/video/"], a[class*="StyledLinkVideoCover"][href*="/video/"], a[href*="/video/"]').first
    try:
        await video_card.wait_for(state="attached", timeout=15_000)
        href = await video_card.get_attribute("href")
        if href and "/video/" in href:
            clean_href = href.split("?")[0]
            return clean_href if clean_href.startswith("http") else f"https://www.tiktok.com{clean_href}"
    except Exception as exc:
        logger.warning("[fetcher-tiktok] Video card wait failed: %s", exc)

    # 3. Fallback: Check TikTok Studio content manager
    try:
        logger.info("[fetcher-tiktok] Checking TikTok Studio content list...")
        await page.goto("https://www.tiktok.com/tiktokstudio/content", wait_until="domcontentloaded", timeout=45_000)
        await asyncio.sleep(4)
        studio_video = page.locator('a[href*="/video/"]').first
        if await studio_video.count():
            s_href = await studio_video.get_attribute("href")
            if s_href and "/video/" in s_href:
                clean_s = s_href.split("?")[0]
                return clean_s if clean_s.startswith("http") else f"https://www.tiktok.com{clean_s}"
    except Exception:
        pass

    return None


async def _fetch_facebook_latest(page: Page) -> Optional[str]:
    logger.info("[fetcher-facebook] Navigating to Facebook profile...")
    await page.goto("https://www.facebook.com/me/", wait_until="domcontentloaded", timeout=45_000)
    await asyncio.sleep(4)

    # Scroll down to load profile timeline posts
    await page.evaluate("window.scrollBy(0, 1000)")
    await asyncio.sleep(3)

    # Search for latest post link strictly from profile timeline/feed, ignoring the Reels menu/tabs
    post_url = await page.evaluate('''() => {
        const anchors = Array.from(document.querySelectorAll('a[href]'));
        for (const a of anchors) {
            const href = a.getAttribute('href') || '';
            const aria = (a.getAttribute('aria-label') || '').toLowerCase();
            const text = a.innerText.trim();

            // Strictly ignore Reels navigation tabs or menus
            if (href.includes('?s=tab') || href.includes('sk=reels') || href.includes('sk=') || aria === 'reels' || text === 'Reels') {
                continue;
            }

            // 1. Notification link for processed reel
            if (href.includes('/reel/') && href.includes('notification_fb_shorts')) {
                const cleanId = href.split('/reel/')[1].split('?')[0].split('/')[0];
                if (cleanId) return `https://www.facebook.com/reel/${cleanId}`;
            }

            // 2. Direct post or video permalinks on timeline
            if (href.includes('/videos/') || href.includes('/posts/') || href.includes('story_fbid=') || href.includes('permalink.php')) {
                const base = href.split('&__cft__')[0].split('?__cft__')[0];
                return base.startsWith('http') ? base : `https://www.facebook.com${base}`;
            }

            // 3. Numeric reel post permalink on timeline
            if (href.includes('/reel/')) {
                const parts = href.split('/reel/');
                if (parts.length > 1) {
                    const candidateId = parts[1].split('?')[0].split('/')[0];
                    if (/^\\d+$/.test(candidateId)) {
                        return `https://www.facebook.com/reel/${candidateId}`;
                    }
                }
            }
        }
        return null;
    }''')

    if post_url:
        return post_url

    # Fallback: Click Share -> Copy link from first post in timeline
    try:
        share_btn = page.locator('div[role="button"]:has-text("Bagikan"), div[role="button"]:has-text("Share"), span:text-is("Bagikan"), span:text-is("Share")').first
        if await share_btn.count():
            await share_btn.click()
            await asyncio.sleep(2)
            copy_item = page.locator('div[role="menuitem"]:has-text("Salin tautan"), div[role="menuitem"]:has-text("Copy link")').first
            if await copy_item.count():
                await copy_item.click()
                await asyncio.sleep(1)
                clip = await page.evaluate("navigator.clipboard.readText().catch(() => '')")
                if clip and clip.startswith("http") and not clip.endswith("sk=reels"):
                    return clip.split("?")[0]
    except Exception:
        pass

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
    logger.info("[fetcher-youtube] Navigating to YouTube Studio...")
    await page.goto("https://studio.youtube.com/", wait_until="domcontentloaded", timeout=45_000)
    await asyncio.sleep(3)

    content_btn = page.locator('a[test-id="menu-item-content"], a[id="menu-item-content"], #menu-item-content').first
    if await content_btn.count():
        await content_btn.click()
        await asyncio.sleep(3)

    vid_link = page.locator('a#video-title, a[href*="/watch?v="], a[href*="/shorts/"]').first
    if await vid_link.count():
        href = await vid_link.get_attribute("href")
        if href:
            return href if href.startswith("http") else f"https://www.youtube.com{href}"
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