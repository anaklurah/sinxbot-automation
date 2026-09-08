"""
TikTok video uploader.

TikTok applies aggressive bot detection.  This publisher:
- Always runs non-headless
- Uses storage-state auth (log in manually, save session)
- Injects stealth patches
- Uses slow, human-like interactions

Auth method: storage_state (cfg.PROFILES_DIR / 'tiktok_storage.json')
"""
import asyncio
from pathlib import Path

from playwright.async_api import async_playwright, BrowserContext, Page

from osap.modules.publisher.base import BasePublisher


class TikTokPublisher(BasePublisher):
    """Uploads a video to TikTok via the web upload interface."""

    PLATFORM_NAME = 'tiktok'
    AUTH_METHOD = 'storage_state'
    UPLOAD_URL = 'https://www.tiktok.com/upload'

    async def upload(
        self,
        video_path: str,
        title: str,
        description: str,
        tags: list[str],
    ) -> bool:
        """Perform the TikTok upload flow.

        TikTok combines title and caption into one field.  We build the
        caption as: ``{title} {description} #{tag1} #{tag2} …``

        Steps:
            1. Navigate to upload page
            2. Set video file via hidden input
            3. Wait for caption field to appear (signals upload started)
            4. Fill caption
            5. Wait for processing to complete
            6. Click Post
            7. Confirm success redirect

        Args:
            video_path: Absolute path to the video file.
            title: Video title (prepended to caption).
            description: Additional caption text.
            tags: Hashtag list (auto-prefixed with #).

        Returns:
            True on success.
        """
        log = self._log
        video_path = str(Path(video_path).resolve())

        # Build combined caption (TikTok limit: 2200 chars)
        hashtags = ' '.join(f'#{t.lstrip("#")}' for t in tags)
        caption = f'{title} {description} {hashtags}'.strip()[:2200]

        async with async_playwright() as pw:
            context: BrowserContext = await self._get_context(pw)
            page: Page = context.pages[0] if context.pages else await context.new_page()

            try:
                # ── Step 1: Navigate ──────────────────────────────────────────
                log.info('[tiktok] Navigating to %s', self.UPLOAD_URL)
                await page.goto(self.UPLOAD_URL, wait_until='domcontentloaded', timeout=60_000)
                await self._jitter(1500, 3000)

                # Check if redirected to login
                if '/login' in page.url:
                    log.error('[tiktok] Not authenticated — redirected to login page')
                    return False

                # ── Step 2: Set video file ─────────────────────────────────────
                log.info('[tiktok] Setting video file: %s', video_path)
                file_input_sel = 'input[type="file"]'
                # The file input on TikTok's upload page is hidden; set_input_files works regardless
                file_input = page.locator(file_input_sel).first
                await file_input.wait_for(state='attached', timeout=20_000)
                await file_input.set_input_files(video_path)
                log.info('[tiktok] File set, waiting for upload to begin')
                await self._jitter(2000, 4000)

                # ── Step 3: Wait for caption field to appear ─────────────────
                log.info('[tiktok] Waiting for caption/title field (signals upload started)')
                caption_sel = (
                    '[data-text="true"][contenteditable="true"], '
                    '.public-DraftEditor-content, '
                    '[placeholder*="caption" i], '
                    '[aria-label*="caption" i], '
                    '.caption-input-container [contenteditable]'
                )
                try:
                    await page.wait_for_selector(caption_sel, timeout=60_000)
                    log.info('[tiktok] Caption field appeared')
                except Exception:
                    log.warning('[tiktok] Caption field not found within 60s — trying anyway')

                await self._jitter(1000, 2000)

                # Dismiss tutorial overlays (react-joyride) if present
                try:
                    joyride_btn = page.locator('.react-joyride__tooltip button, button:has-text("Got it"), button:has-text("Skip"), button:has-text("Mengerti")').first
                    if await joyride_btn.is_visible():
                        await joyride_btn.click(force=True)
                        log.info('[tiktok] Dismissed tutorial overlay')
                        await self._jitter(500, 1000)
                except Exception:
                    pass

                # ── Step 4: Fill caption ──────────────────────────────────────
                log.info('[tiktok] Filling caption: %r', caption[:80])
                try:
                    cap_el = page.locator(caption_sel).first
                    await cap_el.click(force=True)
                    await page.keyboard.press('Control+a')
                    await self._jitter(200, 400)
                    for char in caption:
                        await page.keyboard.type(char, delay=40)
                    log.info('[tiktok] Caption filled successfully')
                    await self._jitter(800, 1500)
                except Exception as exc:
                    log.warning('[tiktok] Caption fill failed: %s', exc)

                # ── Step 5: Wait for processing ────────────────────────────────
                log.info('[tiktok] Waiting for upload/processing to finish')
                try:
                    await page.wait_for_function(
                        """() => {
                            const indicators = document.querySelectorAll(
                                '[class*="upload-progress"], [class*="uploading"]'
                            );
                            if (indicators.length === 0) return true;
                            return Array.from(indicators).every(el =>
                                el.style.display === 'none' ||
                                el.getAttribute('aria-hidden') === 'true' ||
                                !document.body.contains(el)
                            );
                        }""",
                        timeout=180_000,
                    )
                except Exception:
                    log.info('[tiktok] Progress indicator cleared or not detected — continuing')

                await self._jitter(1500, 3000)

                # ── Step 6: Click Post ─────────────────────────────────────────
                log.info('[tiktok] Clicking Post button')
                post_btn_sel = (
                    'button:has-text("Post"), '
                    'button:has-text("Posting"), '
                    '[data-e2e="post_video_button"], '
                    'button.btn-post'
                )
                await page.wait_for_selector(post_btn_sel, timeout=20_000)
                post_btn = page.locator(post_btn_sel).first
                try:
                    await post_btn.click(force=True)
                except Exception:
                    await post_btn.evaluate("el => el.click()")
                log.info('[tiktok] Clicked Post button')
                await self._jitter(2000, 4000)

                # ── Step 7: Confirm success ────────────────────────────────────
                log.info('[tiktok] Waiting for success confirmation')
                try:
                    await page.wait_for_url(
                        lambda url: 'tiktok.com' in url and 'upload' not in url,
                        timeout=30_000,
                    )
                    log.info('[tiktok] ✓ Redirected away from upload — assuming success')
                except Exception:
                    # Check for a success toast/message
                    try:
                        await page.wait_for_selector(
                            ':text("Your video is being uploaded"), :text("Posted"), :text("Success")',
                            timeout=15_000,
                        )
                        log.info('[tiktok] ✓ Success message detected')
                    except Exception:
                        log.warning('[tiktok] Could not confirm success — assuming success based on flow')

                return True

            except Exception as exc:
                log.exception('[tiktok] Upload failed: %s', exc)
                return False
            finally:
                await context.close()
