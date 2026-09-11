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
                # ── Step 5: Wait for Posting button to turn BLUE ───────────────
                log.info('[facebook] Waiting for video upload to finish and Posting button to turn BLUE...')

                check_blue_js = """() => {
                    function isBlueRgb(colorStr) {
                        if (!colorStr) return false;
                        const m = colorStr.match(/rgba?\\((\\d+),\\s*(\\d+),\\s*(\\d+)/);
                        if (!m) return false;
                        const r = parseInt(m[1]), g = parseInt(m[2]), b = parseInt(m[3]);
                        return b > 140 && b > r + 30 && b > g + 15;
                    }

                    // Look exclusively for Posting / Publish action buttons inside the dialog
                    const candidates = Array.from(document.querySelectorAll(
                        'div[role="dialog"] div[role="button"], div[role="dialog"] button'
                    )).filter(el => {
                        const text = (el.innerText || '').trim().toLowerCase();
                        const aria = (el.getAttribute('aria-label') || '').trim().toLowerCase();
                        return text === 'posting' || aria === 'posting' ||
                               text === 'publish' || aria === 'publish' ||
                               text === 'publikasikan' || aria === 'publikasikan';
                    });

                    if (!candidates.length) return { ready: false, reason: 'no_posting_button_found' };

                    for (const btn of candidates) {
                        if (btn.offsetWidth === 0 || btn.offsetHeight === 0) continue;
                        if (btn.getAttribute('aria-disabled') === 'true' || btn.disabled || btn.hasAttribute('disabled')) {
                            return { ready: false, reason: 'posting_button_still_disabled' };
                        }

                        // Check self background
                        const selfStyle = window.getComputedStyle(btn);
                        let isBlue = isBlueRgb(selfStyle.backgroundColor);

                        // Check child background
                        if (!isBlue) {
                            for (const child of btn.querySelectorAll('*')) {
                                if (isBlueRgb(window.getComputedStyle(child).backgroundColor)) {
                                    isBlue = true;
                                    break;
                                }
                            }
                        }

                        // Check parent background (up to 2 levels)
                        if (!isBlue) {
                            let p = btn.parentElement;
                            for (let d = 0; d < 2 && p && p !== document.body; d++) {
                                if (isBlueRgb(window.getComputedStyle(p).backgroundColor)) {
                                    isBlue = true;
                                    break;
                                }
                                p = p.parentElement;
                            }
                        }

                        if (isBlue) {
                            btn.setAttribute('data-target-post-ready', 'true');
                            return { ready: true, color: 'blue_active' };
                        }
                    }

                    return { ready: false, reason: 'posting_button_not_blue_yet' };
                }"""

                button_ready = False
                for elapsed in range(0, 180, 2):
                    try:
                        status = await page.evaluate(check_blue_js)
                        if status and status.get("ready"):
                            log.info('[facebook] ✓ Posting button has turned BLUE (%s) after %ds! Ready to post.', status.get("color"), elapsed)
                            button_ready = True
                            break
                        else:
                            if elapsed % 10 == 0 and elapsed > 0:
                                log.info('[facebook] Still waiting for video upload... Posting button is grey (%s, %ds elapsed)', status.get("reason"), elapsed)
                    except Exception as e:
                        log.debug('[facebook] Check blue error: %s', e)

                    await asyncio.sleep(2)

                if not button_ready:
                    log.warning('[facebook] Button did not turn blue within 180s, attempting click anyway')

                # Click the blue Posting button
                clicked = False
                publish_btn_sel = (
                    '[data-target-post-ready="true"], '
                    'div[role="dialog"] div[aria-label="Posting"][role="button"], '
                    'div[role="dialog"] div[role="button"]:has-text("Posting"), '
                    'div[role="dialog"] button:has-text("Posting"), '
                    'div[role="button"]:has-text("Posting"), '
                    'button:has-text("Posting"), '
                    'div[role="button"]:has-text("Publish"), '
                    'button:has-text("Publish")'
                )
                try:
                    btn = page.locator(publish_btn_sel).last
                    if await btn.count() and await btn.is_visible():
                        await btn.scroll_into_view_if_needed()
                        await btn.click(timeout=10_000)
                        clicked = True
                        log.info('[facebook] Clicked blue Posting button via locator click')
                except Exception as e:
                    log.debug('[facebook] Locator click error: %s', e)

                if not clicked:
                    click_blue_js = """() => {
                        const marked = document.querySelector('[data-target-post-ready="true"]');
                        if (marked) {
                            marked.click();
                            return true;
                        }
                        const candidates = Array.from(document.querySelectorAll(
                            'div[role="dialog"] div[role="button"], div[role="dialog"] button, div[role="button"], button'
                        )).filter(el => {
                            const text = (el.innerText || '').trim().toLowerCase();
                            const aria = (el.getAttribute('aria-label') || '').trim().toLowerCase();
                            return ['posting', 'publish', 'publikasikan', 'bagikan', 'share', 'post'].includes(text) ||
                                   ['posting', 'publish', 'publikasikan', 'bagikan', 'share', 'post'].includes(aria);
                        });
                        for (let i = candidates.length - 1; i >= 0; i--) {
                            const btn = candidates[i];
                            if (btn.offsetWidth === 0 || btn.offsetHeight === 0) continue;
                            if (btn.getAttribute('aria-disabled') === 'true' || btn.disabled || btn.hasAttribute('disabled')) continue;
                            btn.click();
                            return true;
                        }
                        return false;
                    }"""
                    res = await page.evaluate(click_blue_js)
                    if res:
                        clicked = True
                        log.info('[facebook] Clicked blue Posting button via evaluate click')

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
                    await page.wait_for_selector(success_sel, timeout=30_000)
                    log.info('[facebook] ✓ Reel published successfully')
                except Exception:
                    # Check if reels creation modal closed
                    try:
                        modal = page.locator('div[role="dialog"]:has-text("Buat reel"), div[role="dialog"]:has-text("Create reel")').first
                        if await modal.count():
                            await modal.wait_for(state="hidden", timeout=30_000)
                            log.info('[facebook] Reels creation dialog closed — publication confirmed')
                    except Exception:
                        log.info('[facebook] Flow completed without explicit success toast — checking URL')

                # Check if current URL or redirected URL is a reel permalink
                current_url = page.url
                if "/reel/" in current_url and not any(x in current_url for x in ["/create", "?s=tab"]):
                    clean_reel = current_url.split("?")[0]
                    self.uploaded_url = clean_reel
                    log.info('[facebook] ✓ Captured direct Reel URL: %s', self.uploaded_url)

                return True

            except Exception as exc:
                log.exception('[facebook] Upload failed: %s', exc)
                return False
            finally:
                await context.close()
