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
                await page.goto(self.UPLOAD_URL, wait_until='networkidle', timeout=60_000)
                await self._jitter(1500, 3000)

                # ── Step 2: Click Upload nav link ──────────────────────────────
                log.info('[febspot] Looking for Upload navigation link')
                try:
                    await page.wait_for_selector(self._SEL_UPLOAD_NAV_BTN, timeout=10_000)
                    await self._move_click(page, self._SEL_UPLOAD_NAV_BTN)
                    await self._jitter(1000, 2000)
                    log.info('[febspot] Navigated to upload page via nav button')
                except Exception:
                    # Try navigating directly to common upload paths
                    for upload_path in ('/upload', '/upload/video', '/videos/upload', '/create'):
                        try:
                            upload_url = f'{self.UPLOAD_URL.rstrip("/")}{upload_path}'
                            log.debug('[febspot] Trying upload URL: %s', upload_url)
                            await page.goto(upload_url, wait_until='networkidle', timeout=30_000)
                            await self._jitter(800, 1500)
                            # Check if a file input is present
                            await page.wait_for_selector(self._SEL_FILE_INPUT, timeout=5_000)
                            log.info('[febspot] Found upload page at %s', upload_url)
                            break
                        except Exception:
                            continue

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
                log.info('[febspot] Clicking Publish/Submit button')
                await page.wait_for_selector(self._SEL_SUBMIT_BTN, timeout=20_000)
                await self._move_click(page, self._SEL_SUBMIT_BTN)
                await self._jitter(2000, 4000)

                # ── Step 7: Wait for success ────────────────────────────────────
                log.info('[febspot] Waiting for success confirmation')
                try:
                    await page.wait_for_selector(self._SEL_SUCCESS, timeout=30_000)
                    log.info('[febspot] ✓ Video published successfully')
                except Exception:
                    log.warning('[febspot] Success indicator not found — assuming success based on flow')

                return True

            except Exception as exc:
                log.exception('[febspot] Upload failed: %s', exc)
                return False
            finally:
                await context.close()
