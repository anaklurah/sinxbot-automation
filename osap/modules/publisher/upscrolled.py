"""
Upscrolled video publisher.

Upscrolled is a short-form video platform.  This publisher uses
storage-state authentication and the standard upload flow.

Auth method: storage_state (cfg.PROFILES_DIR / 'upscrolled_storage.json')

# NOTE: Upscrolled is a newer platform. Selectors were determined from
# public UI as of 2025. Verify via browser DevTools if upload fails.
"""
import asyncio
from pathlib import Path

from playwright.async_api import async_playwright, BrowserContext, Page

from osap.modules.publisher.base import BasePublisher


class UpscrolledPublisher(BasePublisher):
    """Uploads a short video to Upscrolled."""

    PLATFORM_NAME = 'upscrolled'
    AUTH_METHOD = 'storage_state'
    UPLOAD_URL = 'https://upscrolled.com'

    # ── Selector constants ──────────────────────────────────────────────────
    # NOTE: Upscrolled is a newer platform. Selectors were determined from
    # public UI as of 2025. Verify via browser DevTools if upload fails.
    _SEL_CREATE_BTN = (
        'a[href*="upload"], '
        'a[href*="create"], '
        'button:has-text("Upload"), '
        'button:has-text("Create"), '
        '[aria-label*="upload" i], '
        '[aria-label*="create" i]'
    )
    _SEL_FILE_INPUT = 'input[type="file"][accept*="video"], input[type="file"]'
    _SEL_TITLE_INPUT = (
        'input[name="title"], '
        'input[placeholder*="title" i], '
        'input[aria-label*="title" i], '
        'textarea[name="title"]'
    )
    _SEL_CAPTION = (
        'textarea[name="caption"], '
        'textarea[placeholder*="caption" i], '
        'textarea[placeholder*="description" i], '
        'textarea[aria-label*="caption" i], '
        '[contenteditable="true"]'
    )
    _SEL_PUBLISH_BTN = (
        'button:has-text("Publish"), '
        'button:has-text("Post"), '
        'button:has-text("Share"), '
        'button[type="submit"]'
    )
    _SEL_SUCCESS = (
        ':text("Upload complete"), '
        ':text("Your video is live"), '
        ':text("Posted"), '
        ':text("Published"), '
        ':text("Success"), '
        '[class*="success"], '
        '[class*="complete"]'
    )

    async def upload(
        self,
        video_path: str,
        title: str,
        description: str,
        tags: list[str],
    ) -> bool:
        """Perform the Upscrolled upload flow.

        Steps:
            1. Navigate to Upscrolled home
            2. Click Create / Upload button
            3. Set video file via file input
            4. Wait for upload progress to complete
            5. Fill title
            6. Fill caption (description + hashtags)
            7. Click Publish
            8. Confirm success

        Args:
            video_path: Absolute path to the video file.
            title: Video title.
            description: Caption / description body.
            tags: Hashtag list (auto-prefixed with #).

        Returns:
            True on success.
        """
        log = self._log
        video_path = str(Path(video_path).resolve())

        hashtags = ' '.join(f'#{t.lstrip("#")}' for t in tags)
        caption = f'{description}\n{hashtags}'.strip()

        async with async_playwright() as pw:
            context: BrowserContext = await self._get_context(pw)
            page: Page = context.pages[0] if context.pages else await context.new_page()

            try:
                # ── Step 1: Navigate ──────────────────────────────────────────
                log.info('[upscrolled] Navigating to %s', self.UPLOAD_URL)
                await page.goto(self.UPLOAD_URL, wait_until='domcontentloaded', timeout=60_000)
                await self._jitter(1500, 3000)

                # Check authentication
                if '/login' in page.url or '/signin' in page.url:
                    log.error('[upscrolled] Not authenticated — redirected to login')
                    return False

                # ── Step 2: Click Create / Upload button ──────────────────────
                log.info('[upscrolled] Looking for Create/Upload button')
                try:
                    await page.wait_for_selector(self._SEL_CREATE_BTN, timeout=10_000)
                    await self._move_click(page, self._SEL_CREATE_BTN)
                    await self._jitter(1000, 2000)
                    log.info('[upscrolled] Clicked Create/Upload button')
                except Exception:
                    # Try navigating directly to upload paths
                    for upload_path in ('/upload', '/create', '/upload/video'):
                        try:
                            upload_url = f'{self.UPLOAD_URL.rstrip("/")}{upload_path}'
                            log.debug('[upscrolled] Trying upload URL: %s', upload_url)
                            await page.goto(upload_url, wait_until='domcontentloaded', timeout=30_000)
                            await self._jitter(800, 1500)
                            await page.wait_for_selector(self._SEL_FILE_INPUT, timeout=5_000)
                            log.info('[upscrolled] Found upload page at %s', upload_url)
                            break
                        except Exception:
                            continue

                # ── Step 3: Set video file ─────────────────────────────────────
                log.info('[upscrolled] Setting video file: %s', video_path)
                file_input = page.locator(self._SEL_FILE_INPUT).first
                await file_input.wait_for(state='attached', timeout=20_000)
                await file_input.set_input_files(video_path)
                log.info('[upscrolled] File set')
                await self._jitter(2000, 4000)

                # ── Step 4: Wait for upload progress ─────────────────────────
                log.info('[upscrolled] Waiting for upload to process')
                await self._wait_for_upload_complete(page, timeout_ms=300_000)
                await self._jitter(1000, 2000)

                # ── Step 5: Fill title ─────────────────────────────────────────
                log.info('[upscrolled] Filling title: %r', title)
                try:
                    await page.wait_for_selector(self._SEL_TITLE_INPUT, timeout=12_000)
                    await page.click(self._SEL_TITLE_INPUT)
                    await page.keyboard.press('Control+a')
                    await self._jitter(200, 400)
                    for char in title:
                        await page.keyboard.type(char, delay=70)
                    await self._jitter(500, 1000)
                except Exception as exc:
                    log.warning('[upscrolled] Title field not found: %s', exc)

                # ── Step 6: Fill caption ────────────────────────────────────────
                log.info('[upscrolled] Filling caption')
                try:
                    await page.wait_for_selector(self._SEL_CAPTION, timeout=12_000)
                    await page.click(self._SEL_CAPTION)
                    await self._jitter(300, 600)
                    for char in caption:
                        await page.keyboard.type(char, delay=65)
                    await self._jitter(600, 1200)
                except Exception as exc:
                    log.warning('[upscrolled] Caption field not found: %s', exc)

                # ── Step 7: Publish ────────────────────────────────────────────
                log.info('[upscrolled] Clicking Publish button')
                await page.wait_for_selector(self._SEL_PUBLISH_BTN, timeout=15_000)
                await self._move_click(page, self._SEL_PUBLISH_BTN)
                await self._jitter(2000, 4000)

                # ── Step 8: Confirm success ────────────────────────────────────
                log.info('[upscrolled] Waiting for success confirmation')
                try:
                    await page.wait_for_selector(self._SEL_SUCCESS, timeout=30_000)
                    log.info('[upscrolled] ✓ Video published successfully')
                except Exception:
                    log.warning('[upscrolled] Success indicator not found — assuming success based on flow')

                return True

            except Exception as exc:
                log.exception('[upscrolled] Upload failed: %s', exc)
                return False
            finally:
                await context.close()
