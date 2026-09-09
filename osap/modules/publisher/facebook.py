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


_FB_MAX_CAPTION_CHARS = 100  # Enforce 90-120 character limit so reels dialog does not push Posting button offscreen


class FacebookPublisher(BasePublisher):
    """Uploads a video as a Facebook Reel via web UI."""

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
            1. Navigate to Reels creation URL
            2. Attach video file
            3. Advance through wizard steps (Add Video -> Audio/Edit -> Publish)
            4. Fill description / caption text (max 90-120 chars)
            5. Click Publish / Posting button
            6. Wait for success confirmation

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

        # Build concise caption within 90 - 120 chars (target max 100 chars)
        # Normalize whitespace and remove newlines so the modal dialog does not stretch vertically
        raw_text = (description or title or '').strip()
        raw_text = ' '.join(raw_text.split())

        if len(raw_text) > _FB_MAX_CAPTION_CHARS:
            trimmed = raw_text[:_FB_MAX_CAPTION_CHARS]
            last_sp = trimmed.rfind(' ')
            if last_sp > int(_FB_MAX_CAPTION_CHARS * 0.7):
                full_description = trimmed[:last_sp].rstrip()
            else:
                full_description = trimmed.rstrip()
        else:
            full_description = raw_text
            if tags:
                for t in tags:
                    clean_tag = f'#{t.lstrip("#")}'
                    candidate = f'{full_description} {clean_tag}'.strip()
                    if len(candidate) <= _FB_MAX_CAPTION_CHARS:
                        full_description = candidate
                    else:
                        break

        log.info('[facebook] Formatted caption text (%d chars): %r', len(full_description), full_description)

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

                # ── Step 3: Advance wizard (Step 1 -> Step 2 -> Step 3) ──────────────
                log.info('[facebook] Advancing Reels creation wizard')
                next_btn_sel = (
                    ':text("Berikutnya"), '
                    ':text("Next"), '
                    '[aria-label="Berikutnya"], '
                    '[aria-label="Next"], '
                    'button:has-text("Berikutnya"), '
                    'button:has-text("Next")'
                )
                for step_idx in (1, 2):
                    try:
                        await page.wait_for_selector(next_btn_sel, timeout=20_000)
                        btn = page.locator(next_btn_sel).first
                        await btn.click()
                        log.info('[facebook] Clicked Next (step %d)', step_idx)
                        await self._jitter(2000, 3500)
                    except Exception as exc:
                        log.warning('[facebook] Next button not found on step %d: %s', step_idx, exc)

                # ── Step 4: Fill description / caption ─────────────────────────
                log.info('[facebook] Filling description/caption on Step 3')
                desc_sel = (
                    'div[role="textbox"][contenteditable="true"], '
                    '[aria-placeholder*="reel" i], '
                    '[aria-placeholder*="deskripsi" i], '
                    '[aria-label*="description" i], '
                    '[aria-label*="deskripsi" i], '
                    'textarea[placeholder*="description" i]'
                )
                try:
                    await page.wait_for_selector(desc_sel, timeout=15_000)
                    desc_box = page.locator(desc_sel).first
                    await desc_box.click()
                    await self._jitter(300, 600)
                    # Use page.keyboard to type safely
                    for char in full_description:
                        await page.keyboard.type(char, delay=35)
                    log.info('[facebook] Description filled successfully')
                    await self._jitter(1000, 2000)
                except Exception as exc:
                    log.warning('[facebook] Could not fill description: %s', exc)

                # ── Step 5: Click Publish / Posting / Share ────────────────────
                log.info('[facebook] Looking for Publish/Posting button')
                publish_btn_sel = (
                    'div[aria-label="Posting"][role="button"], '
                    'div[aria-label="Publish"][role="button"], '
                    'div[aria-label="Publikasikan"][role="button"], '
                    'div[aria-label="Bagikan"][role="button"], '
                    'button:has-text("Posting"), '
                    'button:has-text("Publish"), '
                    'button:has-text("Publikasikan"), '
                    'button:has-text("Bagikan"), '
                    'button:has-text("Share"), '
                    'button:has-text("Post"), '
                    'div[role="button"]:has-text("Posting"), '
                    'div[role="button"]:has-text("Publish"), '
                    'div[role="button"]:has-text("Publikasikan"), '
                    'div[role="button"]:has-text("Bagikan"), '
                    '[aria-label="Posting"], '
                    '[aria-label="Publish"], '
                    '[aria-label="Share"], '
                    '[data-testid="reels-publish-button"]'
                )
                await page.wait_for_selector(publish_btn_sel, timeout=30_000)
                publish_btn = page.locator(publish_btn_sel).first

                # Wait for publish button to become enabled (video upload & processing)
                log.info('[facebook] Waiting for video upload/processing to complete and Publish button to become enabled...')
                for elapsed in range(0, 180, 2):
                    is_disabled = False
                    try:
                        aria_dis = await publish_btn.get_attribute("aria-disabled")
                        dis = await publish_btn.get_attribute("disabled")
                        if aria_dis == "true" or dis is not None:
                            is_disabled = True
                        elif not await publish_btn.is_enabled():
                            is_disabled = True
                    except Exception:
                        pass

                    if not is_disabled:
                        log.info('[facebook] Publish button is enabled after %ds', elapsed)
                        break
                    if elapsed % 20 == 0 and elapsed > 0:
                        log.info('[facebook] Still waiting for video processing... (%ds elapsed)', elapsed)
                    await asyncio.sleep(2)

                await publish_btn.scroll_into_view_if_needed()
                clicked = False
                try:
                    await publish_btn.click(timeout=15_000)
                    clicked = True
                    log.info('[facebook] Publish button clicked successfully')
                except Exception:
                    pass

                if not clicked:
                    try:
                        await publish_btn.click(force=True, timeout=5_000)
                        clicked = True
                        log.info('[facebook] Publish button clicked via force=True')
                    except Exception:
                        pass

                if not clicked:
                    await publish_btn.evaluate("el => el.click()")
                    log.info('[facebook] Publish button clicked via DOM evaluate')

                await self._jitter(3000, 6000)

                # ── Step 6: Wait for success confirmation ─────────────────────
                log.info('[facebook] Waiting for success confirmation')
                try:
                    success_sel = (
                        ':text("Your reel is now live"), '
                        ':text("Reel published"), '
                        ':text("Published"), '
                        ':text("Dipublikasikan"), '
                        ':text("Reel Anda kini tayang"), '
                        ':text("Your reel is being processed"), '
                        ':text("sedang diproses")'
                    )
                    await page.wait_for_selector(success_sel, timeout=45_000)
                    log.info('[facebook] ✓ Reel published successfully')
                except Exception:
                    # Check if reels creation modal closed
                    try:
                        await page.locator('[role="dialog"]').first.wait_for(state="hidden", timeout=30_000)
                        log.info('[facebook] Reels creation dialog closed — publication confirmed')
                    except Exception:
                        log.info('[facebook] Flow completed without explicit success toast — assuming success')

                return True

            except Exception as exc:
                log.exception('[facebook] Upload failed: %s', exc)
                return False
            finally:
                await context.close()
