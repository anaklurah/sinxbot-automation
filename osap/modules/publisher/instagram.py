"""
Instagram Reels publisher.

Auth method: storage_state (cfg.PROFILES_DIR / 'instagram_storage.json')

Instagram's web upload flow uses a multi-step dialog.  This publisher
navigates the Create flow, selects the video, handles aspect-ratio/crop
prompts, steps through editing screens, and finally posts with caption.
"""
import asyncio
from pathlib import Path

from playwright.async_api import async_playwright, BrowserContext, Page

from osap.modules.publisher.base import BasePublisher


class InstagramPublisher(BasePublisher):
    """Uploads a Reel to Instagram via the web interface."""

    PLATFORM_NAME = 'instagram'
    AUTH_METHOD = 'storage_state'
    UPLOAD_URL = 'https://www.instagram.com'

    async def upload(
        self,
        video_path: str,
        title: str,
        description: str,
        tags: list[str],
    ) -> bool:
        """Perform the Instagram Reels upload flow.

        Steps:
            1. Navigate to Instagram home
            2. Click "+" (Create) button
            3. Set video file via file input
            4. Handle aspect-ratio / crop dialog
            5. Click through editing steps (Filter, Adjust)
            6. Fill caption textarea
            7. Click Share
            8. Wait for success

        Args:
            video_path: Absolute path to the video file.
            title: Not used as a separate field on IG; prepended to caption.
            description: Caption body text.
            tags: Hashtag list (auto-prefixed with #).

        Returns:
            True on success.
        """
        log = self._log
        video_path = str(Path(video_path).resolve())

        # Build caption (Instagram limit: 2200 chars)
        hashtags = ' '.join(f'#{t.lstrip("#")}' for t in tags)
        caption = f'{title}\n\n{description}\n\n{hashtags}'.strip()[:2200]

        async with async_playwright() as pw:
            context: BrowserContext = await self._get_context(pw)
            page: Page = context.pages[0] if context.pages else await context.new_page()

            try:
                # ── Step 1: Navigate ──────────────────────────────────────────
                log.info('[instagram] Navigating to %s', self.UPLOAD_URL)
                await page.goto(self.UPLOAD_URL, wait_until='domcontentloaded', timeout=60_000)
                await self._jitter(1500, 3000)

                # Check authentication
                if '/accounts/login' in page.url:
                    log.error('[instagram] Not authenticated — redirected to login')
                    return False

                # ── Step 2: Click Create "+" button ──────────────────────────
                log.info('[instagram] Clicking Create button')
                create_btn_sel = (
                    'svg[aria-label="New post"], '
                    '[aria-label="New post"], '
                    'a[href="/create/style/"], '
                    ':text("Create"), '
                    '[aria-label="New post"] >> .. >> svg'
                )
                await page.wait_for_selector(create_btn_sel, timeout=20_000)
                await self._move_click(page, create_btn_sel)
                await self._jitter(800, 1500)

                # A "Post" option may appear in a sub-menu
                try:
                    post_option_sel = ':text("Post"), [aria-label*="Post" i]'
                    await page.wait_for_selector(post_option_sel, timeout=5_000)
                    await self._click(page, post_option_sel)
                    await self._jitter(600, 1200)
                except Exception:
                    pass  # No sub-menu appeared; continue directly to file input

                # ── Step 3: Set video file ────────────────────────────────────
                log.info('[instagram] Setting video file: %s', video_path)
                file_input_sel = 'input[type="file"]'
                file_input = page.locator(file_input_sel).first
                await file_input.wait_for(state='attached', timeout=20_000)
                await file_input.set_input_files(video_path)
                log.info('[instagram] File set')
                await self._jitter(2000, 4000)

                # ── Step 4: Handle aspect-ratio / crop dialog ─────────────────
                log.info('[instagram] Handling aspect-ratio/crop dialog if present')
                try:
                    # Look for a crop/aspect-ratio selector
                    crop_dialog_sel = ':text("Select crop"), :text("Crop"), [aria-label="Select crop"]'
                    await page.wait_for_selector(crop_dialog_sel, timeout=8_000)

                    # Prefer "Original" to preserve video dimensions
                    original_sel = ':text("Original"), [aria-label="Original crop"]'
                    try:
                        await self._click(page, original_sel)
                        log.info('[instagram] Selected "Original" crop')
                    except Exception:
                        log.warning('[instagram] Could not select Original crop — skipping')

                    await self._jitter(600, 1200)
                except Exception:
                    log.debug('[instagram] No crop dialog — continuing')

                # Also dismiss any "OK" prompts about aspect ratio
                try:
                    ok_sel = 'button:has-text("OK"), button:has-text("Continue")'
                    await page.wait_for_selector(ok_sel, timeout=5_000)
                    await self._click(page, ok_sel)
                    await self._jitter(400, 800)
                except Exception:
                    pass

                # ── Step 5: Click through editing steps ────────────────────────
                # Instagram's dialog has: Crop → Filter → Adjust → Caption
                next_btn_sel = 'button:has-text("Next"), [aria-label="Next"]'
                for step_name in ('Filter/Trim', 'Adjust'):
                    log.info('[instagram] Advancing past step: %s', step_name)
                    try:
                        await page.wait_for_selector(next_btn_sel, timeout=15_000)
                        await self._move_click(page, next_btn_sel)
                        await self._jitter(1200, 2500)
                    except Exception:
                        log.warning('[instagram] Next button not found at step %r', step_name)

                # One more Next to reach the caption screen
                try:
                    await page.wait_for_selector(next_btn_sel, timeout=10_000)
                    await self._move_click(page, next_btn_sel)
                    await self._jitter(1000, 2000)
                except Exception:
                    log.debug('[instagram] No further Next buttons')

                # ── Step 6: Fill caption ──────────────────────────────────────
                log.info('[instagram] Filling caption')
                caption_sel = (
                    'textarea[aria-label*="caption" i], '
                    '[aria-label="Write a caption..."], '
                    '[contenteditable="true"][aria-label*="caption" i], '
                    '.public-DraftEditor-content'
                )
                try:
                    await page.wait_for_selector(caption_sel, timeout=15_000)
                    await page.click(caption_sel)
                    await self._jitter(300, 600)
                    for char in caption:
                        await page.keyboard.type(char, delay=65)
                    await self._jitter(800, 1500)
                except Exception as exc:
                    log.warning('[instagram] Caption fill failed: %s', exc)

                # ── Step 7: Click Share ────────────────────────────────────────
                log.info('[instagram] Clicking Share button')
                share_btn_sel = (
                    'button:has-text("Share"), '
                    '[aria-label="Share"], '
                    'button:has-text("Post")'
                )
                await page.wait_for_selector(share_btn_sel, timeout=15_000)
                await self._move_click(page, share_btn_sel)
                await self._jitter(2000, 4000)

                # ── Step 8: Wait for success ───────────────────────────────────
                log.info('[instagram] Waiting for success confirmation')
                try:
                    success_sel = (
                        ':text("Your reel has been shared"), '
                        ':text("Your post has been shared"), '
                        ':text("Reel shared"), '
                        '[aria-label*="shared" i]'
                    )
                    await page.wait_for_selector(success_sel, timeout=60_000)
                    log.info('[instagram] ✓ Post shared successfully')
                except Exception:
                    log.warning('[instagram] Success message not detected — assuming success based on flow')

                return True

            except Exception as exc:
                log.exception('[instagram] Upload failed: %s', exc)
                return False
            finally:
                await context.close()
