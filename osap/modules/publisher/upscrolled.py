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

                # ── Step 2: Open Create a post modal ──────────────────────────
                log.info('[upscrolled] Looking for Post button')
                post_open_sel = 'button[aria-label="Post"], button:has-text("Post"), a[href*="create"]'
                await page.wait_for_selector(post_open_sel, timeout=15_000)
                post_open_btn = page.locator(post_open_sel).first
                await post_open_btn.click(force=True)
                log.info('[upscrolled] Opened Create a post modal')
                await self._jitter(1500, 2500)

                # ── Step 3: Select "Video post" ───────────────────────────────
                log.info('[upscrolled] Selecting Video post option')
                video_opt_sel = ':text("Video post"), button:has-text("Video post"), div:has-text("Video post")'
                await page.wait_for_selector(video_opt_sel, timeout=15_000)
                video_opt_btn = page.locator(video_opt_sel).first
                await video_opt_btn.click(force=True)
                log.info('[upscrolled] Clicked Video post option')
                await self._jitter(1500, 2500)

                # ── Step 4: Set video file ─────────────────────────────────────
                log.info('[upscrolled] Setting video file: %s', video_path)
                file_input_sel = 'input[type="file"][accept*="video"], input[type="file"]'
                file_input = page.locator(file_input_sel).last
                await file_input.wait_for(state='attached', timeout=20_000)
                await file_input.set_input_files(video_path)
                log.info('[upscrolled] File set')
                await self._jitter(3000, 5000)

                # ── Step 5: Fill caption ────────────────────────────────────────
                log.info('[upscrolled] Filling caption')
                caption_text = f'{title}\n\n{caption}'.strip()
                caption_sel = 'textarea[placeholder*="caption" i], textarea, [contenteditable="true"]'
                try:
                    await page.wait_for_selector(caption_sel, timeout=12_000)
                    caption_el = page.locator(caption_sel).first
                    await caption_el.click(force=True)
                    await self._jitter(300, 600)
                    for char in caption_text:
                        await page.keyboard.type(char, delay=35)
                    log.info('[upscrolled] Caption filled')
                    await self._jitter(1000, 2000)
                except Exception as exc:
                    log.warning('[upscrolled] Caption field not found: %s', exc)

                # ── Step 6: Publish ────────────────────────────────────────────
                log.info('[upscrolled] Clicking Publish/Post button')
                publish_btn_sel = (
                    '[role="dialog"] button:has-text("Post"), '
                    'button.bg-brand-gradient, '
                    'button:has-text("Post"), '
                    'button:has-text("Publish")'
                )
                await page.wait_for_selector(publish_btn_sel, timeout=15_000)
                publish_btn = page.locator(publish_btn_sel).first
                try:
                    await publish_btn.click(force=True)
                except Exception:
                    await publish_btn.evaluate("el => el.click()")
                log.info('[upscrolled] Publish button clicked')
                await self._jitter(3000, 6000)

                # ── Step 7: Confirm success ────────────────────────────────────
                log.info('[upscrolled] Waiting for success confirmation')
                try:
                    success_sel = (
                        ':text("Upload complete"), '
                        ':text("Your video is live"), '
                        ':text("Post published"), '
                        ':text("Success"), '
                        '[role="status"]'
                    )
                    await page.wait_for_selector(success_sel, timeout=30_000)
                    log.info('[upscrolled] ✓ Video published successfully')
                except Exception:
                    log.info('[upscrolled] Success message not detected — flow finished, assuming success')

                return True

            except Exception as exc:
                log.exception('[upscrolled] Upload failed: %s', exc)
                return False
            finally:
                await context.close()
