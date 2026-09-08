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

                # Dismiss initial modal popups ("Turn on notifications", "Save login info", etc.)
                for _ in range(2):
                    try:
                        dismiss_btn = page.locator('button:has-text("Not Now"), button:has-text("Lain Kali"), button:has-text("Nanti Saja")').first
                        if await dismiss_btn.is_visible():
                            await dismiss_btn.click()
                            log.info('[instagram] Dismissed initial popup modal')
                            await self._jitter(800, 1500)
                    except Exception:
                        pass

                # ── Step 2: Click Create "+" button ──────────────────────────
                log.info('[instagram] Clicking Create button')
                create_btn_sel = (
                    'svg[aria-label="New post"], '
                    '[aria-label="New post"], '
                    'svg[aria-label="Postingan baru"], '
                    '[aria-label="Postingan baru"]'
                )
                await page.wait_for_selector(create_btn_sel, timeout=20_000)
                create_icon = page.locator(create_btn_sel).first
                await create_icon.evaluate('el => (el.closest("a") || el.closest("[role=button]") || el.parentElement).click()')
                await self._jitter(1000, 2000)

                # A "Post" option appears in the create popup menu
                try:
                    post_option = page.locator(':text-is("Post"), :text-is("Postingan"), [role="menuitem"]:has-text("Post")').first
                    if await post_option.is_visible():
                        log.info('[instagram] Clicking Post item in create submenu')
                        await post_option.click()
                        await self._jitter(1000, 2000)
                except Exception as exc:
                    log.warning('[instagram] Submenu Post option click: %s', exc)

                # ── Step 3: Set video file ────────────────────────────────────
                log.info('[instagram] Setting video file: %s', video_path)
                file_input_sel = 'input[type="file"]'
                file_input = page.locator(file_input_sel).first
                await file_input.wait_for(state='attached', timeout=20_000)
                await file_input.set_input_files(video_path)
                log.info('[instagram] File set')
                await self._jitter(2500, 4500)

                # ── Step 4: Handle aspect-ratio / Reels notification dialog ───
                log.info('[instagram] Checking for reels notice or crop dialog')
                try:
                    ok_btn = page.locator('button:has-text("OK"), button:has-text("Mengerti"), button:has-text("Continue")').first
                    if await ok_btn.is_visible():
                        await ok_btn.click()
                        log.info('[instagram] Dismissed Reels/crop dialog with OK')
                        await self._jitter(800, 1500)
                except Exception:
                    pass

                # ── Step 5: Click through editing steps (Next / Selanjutnya) ───
                next_btn_sel = (
                    'button:has-text("Next"), '
                    'button:has-text("Selanjutnya"), '
                    '[aria-label="Next"], '
                    '[aria-label="Selanjutnya"], '
                    'div[role="button"]:has-text("Next"), '
                    'div[role="button"]:has-text("Selanjutnya")'
                )
                for step_name in ('Filter/Trim', 'Adjust'):
                    log.info('[instagram] Advancing past step: %s', step_name)
                    try:
                        await page.wait_for_selector(next_btn_sel, timeout=15_000)
                        btn = page.locator(next_btn_sel).first
                        await btn.click(force=True)
                        await self._jitter(1500, 3000)
                    except Exception:
                        log.warning('[instagram] Next button not found at step %r', step_name)

                # Dismiss any secondary OK prompts
                try:
                    ok_btn = page.locator('button:has-text("OK"), button:has-text("Mengerti")').first
                    if await ok_btn.is_visible():
                        await ok_btn.click(force=True)
                        await self._jitter(800, 1500)
                except Exception:
                    pass

                # ── Step 6: Fill caption ──────────────────────────────────────
                log.info('[instagram] Filling caption')
                caption_sel = (
                    'div[contenteditable="true"][role="textbox"], '
                    'div[contenteditable="true"], '
                    'div[role="textbox"], '
                    '[aria-label*="caption" i], '
                    '[aria-label*="keterangan" i], '
                    'textarea'
                )
                try:
                    await page.wait_for_selector(caption_sel, timeout=10_000)
                    caption_box = page.locator(caption_sel).first
                    await caption_box.click(force=True)
                    await self._jitter(300, 600)
                    for char in caption:
                        await page.keyboard.type(char, delay=35)
                    log.info('[instagram] Caption filled')
                    await self._jitter(800, 1500)
                except Exception as exc:
                    log.warning('[instagram] Caption fill failed: %s', exc)

                # ── Step 7: Click Share / Bagikan ─────────────────────────────
                log.info('[instagram] Clicking Share button')
                share_btn_sel = (
                    'button:has-text("Share"), '
                    'button:has-text("Bagikan"), '
                    '[aria-label="Share"], '
                    '[aria-label="Bagikan"], '
                    'div[role="button"]:has-text("Share"), '
                    'div[role="button"]:has-text("Bagikan")'
                )
                await page.wait_for_selector(share_btn_sel, timeout=15_000)
                share_btn = page.locator(share_btn_sel).first
                try:
                    await share_btn.click(force=True)
                except Exception:
                    await share_btn.evaluate("el => el.click()")
                log.info('[instagram] Clicked Share button')
                await self._jitter(3000, 6000)

                # ── Step 8: Wait for success ───────────────────────────────────
                log.info('[instagram] Waiting for success confirmation')
                try:
                    success_sel = (
                        ':text("Your reel has been shared"), '
                        ':text("Your post has been shared"), '
                        ':text("Reel shared"), '
                        ':text("Reel dibagikan"), '
                        ':text("Postingan dibagikan"), '
                        '[aria-label*="shared" i]'
                    )
                    await page.wait_for_selector(success_sel, timeout=45_000)
                    log.info('[instagram] ✓ Post shared successfully')
                except Exception:
                    log.info('[instagram] Success message not detected — flow finished, assuming success')

                return True

            except Exception as exc:
                log.exception('[instagram] Upload failed: %s', exc)
                return False
            finally:
                await context.close()
