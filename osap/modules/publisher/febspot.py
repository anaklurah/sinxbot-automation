"""
Febspot video publisher.

Febspot is a video-sharing platform with Google OAuth login.  We use a
persistent Chrome profile so the OAuth session is preserved across runs.

Auth method: persistent profile (cfg.PROFILES_DIR / 'febspot')

# NOTE: Febspot selectors may need updating if the site changes.
# Verify via browser DevTools before running in production.
"""
import asyncio
from pathlib import Path

from playwright.async_api import async_playwright, BrowserContext, Page

from osap.modules.publisher.base import BasePublisher


class FebspotPublisher(BasePublisher):
    """Uploads a video to Febspot."""

    PLATFORM_NAME = 'febspot'
    AUTH_METHOD = 'persistent'
    UPLOAD_URL = 'https://febspot.com'

    # ── Selector constants ──────────────────────────────────────────────────
    # NOTE: Febspot selectors may need updating if the site changes.
    # Verify via browser DevTools if upload fails.
    _SEL_UPLOAD_NAV_BTN = (
        'a[href*="upload"], '
        'a:has-text("Upload"), '
        'button:has-text("Upload"), '
        '[aria-label*="upload" i]'
    )
    _SEL_FILE_INPUT = 'input[type="file"][accept*="video"], input[type="file"]'
    _SEL_TITLE_INPUT = (
        'input[name="title"], '
        'input[placeholder*="title" i], '
        'input[aria-label*="title" i]'
    )
    _SEL_DESCRIPTION = (
        'textarea[name="description"], '
        'textarea[placeholder*="description" i], '
        'textarea[aria-label*="description" i], '
        '[contenteditable="true"][aria-label*="description" i]'
    )
    _SEL_SUBMIT_BTN = (
        'button:has-text("ADD VIDEO"), '
        'button:has-text("Add Video"), '
        'button:has-text("Add video"), '
        ':text-is("ADD VIDEO"), '
        ':text-is("Add Video"), '
        ':text-is("Add video"), '
        'button[type="submit"], '
        'button:has-text("Publish"), '
        'button:has-text("Upload"), '
        'button:has-text("Post"), '
        'input[type="submit"]'
    )
    _SEL_SUCCESS = (
        ':text("Upload complete"), '
        ':text("Your video is live"), '
        ':text("Published"), '
        ':text("Success"), '
        ':text("Video added"), '
        ':text("Video uploaded"), '
        '[class*="success"]'
    )

    async def upload(
        self,
        video_path: str,
        title: str,
        description: str,
        tags: list[str],
    ) -> bool:
        """Perform the Febspot upload flow.

        Steps:
            1. Navigate to Febspot home / upload page
            2. Click Upload nav link (if on home)
            3. Set video file via file input
            4. Fill title field
            5. Fill description (with appended tags)
            6. Submit / Publish
            7. Wait for success

        Args:
            video_path: Absolute path to the video file.
            title: Video title.
            description: Video description.
            tags: Hashtag list (appended to description).

        Returns:
            True on success.
        """
        log = self._log
        video_path = str(Path(video_path).resolve())

        hashtags = ' '.join(f'#{t.lstrip("#")}' for t in tags)
        full_description = f'{description}\n\n{hashtags}'.strip()

        async with async_playwright() as pw:
            context: BrowserContext = await self._get_context(pw)
            page: Page = context.pages[0] if context.pages else await context.new_page()

            try:
                # ── Step 1: Navigate to Febspot ────────────────────────────────
                log.info('[febspot] Navigating to %s', self.UPLOAD_URL)
                resp = await page.goto(self.UPLOAD_URL, wait_until='domcontentloaded', timeout=60_000)
                await self._jitter(1500, 3000)

                # Check for Febspot server-side 504 / 502 outage
                title = await page.title()
                if "504 Gateway" in title or "502 Bad Gateway" in title or (resp and resp.status in (502, 504)):
                    log.error('[febspot] Server Febspot sedang mengalami gangguan / down (%s). Menunggu server pulih...', title)
                    return False

                # Check if redirected to login
                if '/login' in page.url:
                    log.error('[febspot] Sesi belum login atau cookies kadaluarsa — diarahkan ke halaman login')
                    return False

                # ── Step 2: Click Upload nav link ──────────────────────────────
                log.info('[febspot] Looking for Upload navigation link')
                try:
                    await page.wait_for_selector(self._SEL_UPLOAD_NAV_BTN, timeout=12_000)
                    await self._move_click(page, self._SEL_UPLOAD_NAV_BTN)
                    await self._jitter(1500, 3000)
                    log.info('[febspot] Navigated to upload page via nav button')
                except Exception:
                    # Check title again in case nav click triggered 504
                    cur_title = await page.title()
                    if "504" in cur_title or "502" in cur_title:
                        log.error('[febspot] Server Febspot upstream gateway timeout (504): %s', cur_title)
                        return False
                    log.warning('[febspot] Tombol Upload tidak ditemukan di halaman utama. Pastikan akun sudah login di profile Febspot.')

                # ── Step 3: Set video file ─────────────────────────────────────
                log.info('[febspot] Setting video file: %s', video_path)
                file_input = page.locator(self._SEL_FILE_INPUT).first
                await file_input.wait_for(state='attached', timeout=20_000)
                await file_input.set_input_files(video_path)
                log.info('[febspot] File set, waiting for upload to begin')
                await self._jitter(2000, 4000)

                # ── Step 4: Fill title ─────────────────────────────────────────
                log.info('[febspot] Filling title: %r', title)
                try:
                    await page.wait_for_selector(self._SEL_TITLE_INPUT, timeout=15_000)
                    await page.click(self._SEL_TITLE_INPUT)
                    await page.keyboard.press('Control+a')
                    await self._jitter(200, 400)
                    for char in title:
                        await page.keyboard.type(char, delay=70)
                    await self._jitter(500, 1000)
                except Exception as exc:
                    log.warning('[febspot] Title field not found: %s', exc)

                # ── Step 5: Fill description ────────────────────────────────────
                log.info('[febspot] Filling description')
                try:
                    await page.wait_for_selector(self._SEL_DESCRIPTION, timeout=10_000)
                    await page.click(self._SEL_DESCRIPTION)
                    await self._jitter(300, 600)
                    for char in full_description:
                        await page.keyboard.type(char, delay=65)
                    await self._jitter(600, 1200)
                except Exception as exc:
                    log.warning('[febspot] Description field not found: %s', exc)

                # ── Optional: Wait for upload progress to complete ─────────────
                log.info('[febspot] Waiting for upload to finish processing')
                await self._wait_for_upload_complete(page, timeout_ms=300_000)
                await self._jitter(1000, 2000)

                # ── Step 6: Submit / Publish ────────────────────────────────────
                log.info('[febspot] Looking for ADD VIDEO / Publish button')
                submit_btn = page.locator(self._SEL_SUBMIT_BTN).first
                await submit_btn.wait_for(state='attached', timeout=30_000)
                await submit_btn.scroll_into_view_if_needed()

                # Wait for button to be enabled (upload processing complete)
                log.info('[febspot] Waiting for ADD VIDEO button to become enabled...')
                for _ in range(60):
                    if await submit_btn.is_enabled():
                        aria_dis = await submit_btn.get_attribute("aria-disabled")
                        dis = await submit_btn.get_attribute("disabled")
                        if aria_dis != "true" and dis is None:
                            break
                    await asyncio.sleep(1)
                    await submit_btn.scroll_into_view_if_needed()

                await self._jitter(500, 1000)

                clicked = False
                try:
                    await submit_btn.click(timeout=10_000)
                    clicked = True
                    log.info('[febspot] ADD VIDEO button clicked successfully')
                except Exception:
                    pass

                if not clicked:
                    try:
                        await submit_btn.click(force=True, timeout=5_000)
                        clicked = True
                        log.info('[febspot] ADD VIDEO button clicked via force=True')
                    except Exception:
                        pass

                if not clicked:
                    await submit_btn.evaluate("el => el.click()")
                    log.info('[febspot] ADD VIDEO button clicked via DOM evaluate')

                await self._jitter(2000, 4000)

                # ── Step 7: Wait for success ────────────────────────────────────
                log.info('[febspot] Waiting for success confirmation')
                try:
                    await page.wait_for_selector(self._SEL_SUCCESS, timeout=45_000)
                    log.info('[febspot] ✓ Video published successfully')
                except Exception:
                    # Check if navigated away from upload or URL changed
                    if "/my/videos" in page.url or "/v/" in page.url or "/video/" in page.url:
                        log.info('[febspot] ✓ URL indicates successful publish: %s', page.url)
                    else:
                        log.warning('[febspot] Success indicator not found — assuming success based on flow')

                return True

            except Exception as exc:
                log.exception('[febspot] Upload failed: %s', exc)
                return False
            finally:
                await context.close()
