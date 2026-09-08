"""
Facebook Reels publisher.

Auth method: storage_state (cfg.PROFILES_DIR / 'facebook_storage.json')

Navigates to the Facebook Reels Creator Studio URL, uploads the video,
fills title/description, and publishes.
"""
import asyncio
from pathlib import Path

from playwright.async_api import async_playwright, BrowserContext, Page

from osap.modules.publisher.base import BasePublisher


class FacebookPublisher(BasePublisher):
    """Uploads a video as a Facebook Reel."""

    PLATFORM_NAME = 'facebook'
    AUTH_METHOD = 'storage_state'
    UPLOAD_URL = 'https://www.facebook.com/reels/create'

    async def upload(
        self,
        video_path: str,
        title: str,
        description: str,
        tags: list[str],
    ) -> bool:
        """Perform the Facebook Reels upload flow.

        Steps:
            1. Navigate to Reels creator
            2. Find video file input and set file
            3. Wait for upload progress bar to appear and complete
            4. Fill title field
            5. Fill description / caption textarea
            6. Click Publish / Share
            7. Wait for success confirmation

        Args:
            video_path: Absolute path to the video file.
            title: Reel title.
            description: Reel description / caption text.
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
                # ── Step 1: Navigate ──────────────────────────────────────────
                log.info('[facebook] Navigating to %s', self.UPLOAD_URL)
                await page.goto(self.UPLOAD_URL, wait_until='domcontentloaded', timeout=60_000)
                await self._jitter(1500, 3000)

                # Check authentication
                if '/login' in page.url:
                    log.error('[facebook] Not authenticated — redirected to login')
                    return False

                # ── Step 2: Set video file ────────────────────────────────────
                log.info('[facebook] Locating video file input')
                # Facebook's reels creator uses an accept*="video" input
                file_input_sel = 'input[accept*="video"], input[type="file"]'
                file_input = page.locator(file_input_sel).first
                await file_input.wait_for(state='attached', timeout=20_000)
                await file_input.set_input_files(video_path)
                log.info('[facebook] File set: %s', video_path)
                await self._jitter(2000, 4000)

                # ── Step 3: Wait for upload progress ─────────────────────────
                log.info('[facebook] Waiting for upload to complete')
                progress_sel = (
                    '[role="progressbar"], '
                    '[aria-label*="upload" i], '
                    '[class*="upload-progress"], '
                    '[class*="ProgressBar"]'
                )
                try:
                    # Wait for progress bar to appear
                    await page.wait_for_selector(progress_sel, timeout=15_000)
                    log.info('[facebook] Upload progress detected, waiting for completion')
                    # Wait for it to disappear (upload done)
                    await page.wait_for_selector(
                        progress_sel, state='hidden', timeout=300_000
                    )
                    log.info('[facebook] Upload progress bar gone')
                except Exception:
                    log.warning('[facebook] Progress bar not detected — waiting 20s baseline')
                    await asyncio.sleep(20)

                await self._jitter(1500, 3000)

                # ── Step 4: Fill title ────────────────────────────────────────
                log.info('[facebook] Filling title: %r', title)
                title_sel = (
                    'input[placeholder*="title" i], '
                    'input[aria-label*="title" i], '
                    'textarea[aria-label*="title" i], '
                    '[name="title"]'
                )
                try:
                    await page.wait_for_selector(title_sel, timeout=10_000)
                    await page.click(title_sel)
                    await page.keyboard.press('Control+a')
                    await self._jitter(200, 400)
                    for char in title:
                        await page.keyboard.type(char, delay=70)
                    await self._jitter(500, 1000)
                except Exception as exc:
                    log.warning('[facebook] Title field not found: %s', exc)

                # ── Step 5: Fill description ──────────────────────────────────
                log.info('[facebook] Filling description')
                desc_sel = (
                    'textarea[placeholder*="description" i], '
                    'textarea[aria-label*="description" i], '
                    '[contenteditable="true"][aria-label*="description" i], '
                    '[data-testid="reel-caption-input"], '
                    '[aria-label="Add a description"]'
                )
                try:
                    await page.wait_for_selector(desc_sel, timeout=10_000)
                    await page.click(desc_sel)
                    await self._jitter(300, 600)
                    for char in full_description:
                        await page.keyboard.type(char, delay=65)
                    await self._jitter(700, 1400)
                except Exception as exc:
                    log.warning('[facebook] Description field not found: %s', exc)

                # ── Step 6: Click Publish / Share ─────────────────────────────
                log.info('[facebook] Clicking Publish/Share button')
                publish_btn_sel = (
                    'button:has-text("Publish"), '
                    'button:has-text("Share"), '
                    'button:has-text("Post"), '
                    '[aria-label="Publish"], '
                    '[data-testid="reels-publish-button"]'
                )
                await page.wait_for_selector(publish_btn_sel, timeout=20_000)
                await self._move_click(page, publish_btn_sel)
                await self._jitter(2000, 4000)

                # ── Step 7: Wait for success ──────────────────────────────────
                log.info('[facebook] Waiting for success confirmation')
                try:
                    success_sel = (
                        ':text("Your reel is now live"), '
                        ':text("Reel published"), '
                        ':text("Published"), '
                        ':text("Your reel is being processed")'
                    )
                    await page.wait_for_selector(success_sel, timeout=30_000)
                    log.info('[facebook] ✓ Reel published successfully')
                except Exception:
                    log.warning('[facebook] Success message not detected — assuming success based on flow')

                return True

            except Exception as exc:
                log.exception('[facebook] Upload failed: %s', exc)
                return False
            finally:
                await context.close()
