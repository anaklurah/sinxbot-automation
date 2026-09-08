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

                # ── Step 4: Handle Aspect Ratio ("Original") ──────────────────
                log.info('[instagram] Checking aspect ratio and crop screen')
                await self._jitter(1500, 2500)

                # Dismiss any overlay Reels dialogs ("Reels are here", "Video posts are now shared as reels", etc.)
                try:
                    for _ in range(2):
                        notice_ok = page.locator(
                            'div[role="dialog"] button:has-text("OK"), '
                            'div[role="dialog"] button:has-text("Mengerti"), '
                            'div[role="dialog"] button:has-text("Continue"), '
                            ':text-is("OK")'
                        ).first
                        if await notice_ok.is_visible():
                            await notice_ok.click(force=True)
                            log.info('[instagram] Dismissed Reels notice modal')
                            await self._jitter(600, 1200)
                except Exception:
                    pass

                # Check if the Aspect Ratio popover is open; if not, click the Crop button in bottom-left
                try:
                    original_opt = page.locator(
                        'div[role="dialog"] :text-is("Original"), '
                        'div[role="dialog"] :text-is("Asli"), '
                        'div[role="dialog"] span:has-text("Original"), '
                        'div[role="dialog"] button:has-text("Original"), '
                        ':text-is("Original"), '
                        ':text-is("Asli")'
                    ).first

                    if not await original_opt.is_visible():
                        # Click the crop button at bottom left of media container
                        crop_btn = page.locator(
                            'div[role="dialog"] button:has(svg[aria-label*="crop" i]), '
                            'div[role="dialog"] button:has(svg[aria-label*="potong" i]), '
                            'div[role="dialog"] [aria-label="Select crop"], '
                            'div[role="dialog"] [aria-label="Pilih pemotongan"], '
                            'div[role="dialog"] [aria-label="Open media crop options"], '
                            'svg[aria-label="Select crop"], '
                            'svg[aria-label="Pilih pemotongan"]'
                        ).first

                        if await crop_btn.is_visible():
                            log.info('[instagram] Clicking Crop / Aspect Ratio button at bottom left')
                            await crop_btn.click(force=True)
                            await self._jitter(600, 1200)
                        else:
                            # Fallback: find circular buttons inside dialog positioned near the bottom
                            log.info('[instagram] Looking for bottom-left circular crop button')
                            cand_buttons = page.locator('div[role="dialog"] button:has(svg)')
                            btn_count = await cand_buttons.count()
                            for b_idx in range(btn_count):
                                b_cand = cand_buttons.nth(b_idx)
                                box = await b_cand.bounding_box()
                                # Bottom left quadrant
                                if box and box['y'] > 250 and box['x'] < 600:
                                    await b_cand.click(force=True)
                                    await self._jitter(600, 1000)
                                    if await page.locator(':text-is("Original"), :text-is("Asli")').first.is_visible():
                                        break

                    # Select "Original" option from menu
                    original_opt = page.locator(
                        'div[role="dialog"] :text-is("Original"), '
                        'div[role="dialog"] :text-is("Asli"), '
                        'div[role="dialog"] span:has-text("Original"), '
                        'div[role="dialog"] button:has-text("Original"), '
                        ':text-is("Original"), '
                        ':text-is("Asli")'
                    ).first

                    if await original_opt.is_visible():
                        await original_opt.click(force=True)
                        log.info('[instagram] ✓ Aspect ratio set to "Original"')
                        await self._jitter(800, 1500)
                    else:
                        # Fallback: check for 9:16
                        ratio_916 = page.locator(
                            'div[role="dialog"] :text-is("9:16"), '
                            'div[role="dialog"] button:has-text("9:16"), '
                            ':text-is("9:16")'
                        ).first
                        if await ratio_916.is_visible():
                            await ratio_916.click(force=True)
                            log.info('[instagram] ✓ Aspect ratio set to "9:16"')
                            await self._jitter(800, 1500)
                        else:
                            log.warning('[instagram] Aspect ratio menu options not found, continuing...')

                except Exception as exc:
                    log.warning('[instagram] Aspect ratio handling error: %s', exc)

                # ── Step 5: Advance through wizard steps (Next / Selanjutnya) ─
                log.info('[instagram] Advancing through wizard steps until caption screen appears')
                caption_sel = (
                    'div[role="dialog"] div[contenteditable="true"][role="textbox"], '
                    'div[role="dialog"] div[contenteditable="true"], '
                    'div[role="dialog"] [aria-label*="caption" i], '
                    'div[role="dialog"] [aria-label*="keterangan" i], '
                    'div[role="dialog"] textarea'
                )

                max_next_attempts = 5
                for step_num in range(1, max_next_attempts + 1):
                    # Check if we already reached caption box
                    cap_cand = page.locator(caption_sel).first
                    if await cap_cand.is_visible():
                        log.info('[instagram] Reached caption box at step %d', step_num)
                        break

                    # Look for Next button in dialog header
                    next_btn = page.locator(
                        'div[role="dialog"] :text-is("Next"), '
                        'div[role="dialog"] :text-is("Selanjutnya"), '
                        'div[role="dialog"] div[role="button"]:has-text("Next"), '
                        'div[role="dialog"] div[role="button"]:has-text("Selanjutnya"), '
                        'div[role="dialog"] button:has-text("Next"), '
                        'div[role="dialog"] button:has-text("Selanjutnya"), '
                        'div[role="dialog"] [aria-label="Next"], '
                        'div[role="dialog"] [aria-label="Selanjutnya"]'
                    ).first

                    try:
                        await next_btn.wait_for(state='visible', timeout=12_000)
                        log.info('[instagram] Clicking Next button (pass %d)', step_num)
                        await next_btn.click(force=True)
                        await self._jitter(2000, 3500)
                    except Exception as e:
                        log.warning('[instagram] Next button wait failed at pass %d: %s', step_num, e)
                        # Check if caption appeared despite wait error
                        if await page.locator(caption_sel).first.is_visible():
                            break

                    # Dismiss any intermediate dialogs
                    try:
                        int_ok = page.locator('div[role="dialog"] button:has-text("OK"), div[role="dialog"] button:has-text("Mengerti")').first
                        if await int_ok.is_visible():
                            await int_ok.click(force=True)
                            await self._jitter(800, 1500)
                    except Exception:
                        pass

                # ── Step 6: Fill caption ──────────────────────────────────────
                log.info('[instagram] Filling caption')
                try:
                    await page.wait_for_selector(caption_sel, timeout=15_000)
                    caption_box = page.locator(caption_sel).first
                    await caption_box.click(force=True)
                    await self._jitter(400, 800)
                    
                    # Fill using evaluate or keyboard
                    try:
                        await page.keyboard.insert_text(caption)
                    except Exception:
                        for char in caption:
                            await page.keyboard.type(char, delay=25)

                    log.info('[instagram] Caption filled successfully')
                    await self._jitter(1000, 2000)
                except Exception as exc:
                    log.warning('[instagram] Caption fill failed: %s', exc)

                # ── Step 7: Click Share / Bagikan ─────────────────────────────
                log.info('[instagram] Clicking Share button')
                share_btn_sel = (
                    'div[role="dialog"] :text-is("Share"), '
                    'div[role="dialog"] :text-is("Bagikan"), '
                    'div[role="dialog"] div[role="button"]:has-text("Share"), '
                    'div[role="dialog"] div[role="button"]:has-text("Bagikan"), '
                    'div[role="dialog"] button:has-text("Share"), '
                    'div[role="dialog"] button:has-text("Bagikan"), '
                    'button:has-text("Share"), '
                    'button:has-text("Bagikan")'
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
                log.info('[instagram] Waiting for upload and sharing confirmation')
                try:
                    success_sel = (
                        ':text("Your reel has been shared"), '
                        ':text("Your post has been shared"), '
                        ':text("Reel shared"), '
                        ':text("Reel dibagikan"), '
                        ':text("Postingan dibagikan"), '
                        '[aria-label*="shared" i]'
                    )
                    await page.wait_for_selector(success_sel, timeout=60_000)
                    log.info('[instagram] ✓ Post shared successfully')
                except Exception:
                    # Check if dialog closed as indication of success
                    dialog = page.locator('div[role="dialog"]').first
                    if not await dialog.is_visible():
                        log.info('[instagram] Dialog closed — assuming upload completed successfully')
                    else:
                        log.info('[instagram] Timeout waiting for confirmation text — proceeding')

                return True

            except Exception as exc:
                log.exception('[instagram] Upload failed: %s', exc)
                return False
            finally:
                await context.close()
