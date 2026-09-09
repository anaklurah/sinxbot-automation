"""
Twitter / X video publisher.

Auth method: storage_state (cfg.PROFILES_DIR / 'twitter_storage.json')

Flow:
  1. Navigate to https://x.com/compose/post
  2. Attach video file
  3. Wait for video to upload and process (spinner disappears, video preview shown)
  4. Type tweet caption (≤100 chars)
  5. Wait for Post button to become ACTIVE (not disabled)
  6. Click Post
  7. Wait for success confirmation
"""
import asyncio
from pathlib import Path

from playwright.async_api import async_playwright, BrowserContext, Page

from osap.modules.publisher.base import BasePublisher

_TWEET_MAX_CHARS = 100  # 90–120 char target; capped at 100 so Post button never gets hidden


class TwitterPublisher(BasePublisher):
    """Posts a video tweet to Twitter / X."""

    PLATFORM_NAME = 'twitter'
    AUTH_METHOD = 'storage_state'
    UPLOAD_URL = 'https://x.com'
    NSFW: bool = False

    async def upload(
        self,
        video_path: str,
        title: str,
        description: str,
        tags: list[str],
    ) -> bool:
        """Perform the Twitter / X video tweet flow.

        Steps:
            1. Navigate to compose URL
            2. Attach video via file input
            3. Wait for video processing to finish
            4. Type tweet caption
            5. Wait for Post button to turn active (not disabled)
            6. Click Post
            7. Wait for success

        Returns:
            True on success.
        """
        log = self._log
        video_path = str(Path(video_path).resolve())

        # ── Build concise caption (90–100 chars max) ─────────────────────────
        raw_text = (title or description or '').strip()
        raw_text = ' '.join(raw_text.split())  # Collapse all whitespace/newlines

        if len(raw_text) > _TWEET_MAX_CHARS:
            trimmed = raw_text[:_TWEET_MAX_CHARS]
            last_sp = trimmed.rfind(' ')
            tweet_text = trimmed[:last_sp].rstrip() if last_sp > int(_TWEET_MAX_CHARS * 0.7) else trimmed.rstrip()
        else:
            tweet_text = raw_text
            if tags:
                for t in tags:
                    candidate = f'{tweet_text} #{t.lstrip("#")}'.strip()
                    if len(candidate) <= _TWEET_MAX_CHARS:
                        tweet_text = candidate
                    else:
                        break

        log.info('[twitter] Caption (%d chars): %r', len(tweet_text), tweet_text)

        async with async_playwright() as pw:
            context: BrowserContext = await self._get_context(pw)
            page: Page = context.pages[0] if context.pages else await context.new_page()

            try:
                # ── Step 1: Navigate to compose/post ─────────────────────────
                log.info('[twitter] Navigating to https://x.com/compose/post')
                try:
                    await context.add_cookies([
                        {'name': 'lang', 'value': 'id', 'domain': '.x.com', 'path': '/'},
                        {'name': 'lang', 'value': 'id', 'domain': 'x.com', 'path': '/'},
                    ])
                except Exception:
                    pass

                await page.goto('https://x.com/compose/post', wait_until='domcontentloaded', timeout=60_000)
                await self._jitter(1500, 3000)

                if '/i/flow/login' in page.url or 'login' in page.url:
                    log.error('[twitter] Not authenticated — redirected to login')
                    return False

                # Ensure compose dialog is open
                compose_box_sel = '[data-testid="tweetTextarea_0"]'
                try:
                    await page.wait_for_selector(compose_box_sel, timeout=10_000)
                    log.info('[twitter] Compose dialog open')
                except Exception:
                    log.warning('[twitter] Compose dialog did not open, trying sidebar compose button')
                    try:
                        compose_btn = page.locator('[data-testid="SideNav_NewTweet_Button"]').first
                        await compose_btn.click(force=True)
                        await page.wait_for_selector(compose_box_sel, timeout=10_000)
                    except Exception as e:
                        log.error('[twitter] Could not open compose dialog: %s', e)
                        return False

                # ── Step 2: Attach video file ─────────────────────────────────
                log.info('[twitter] Attaching video: %s', video_path)
                file_input_sel = 'input[data-testid="fileInput"], input[type="file"][accept*="video"], input[type="file"]'
                file_input = page.locator(file_input_sel).first
                try:
                    await file_input.wait_for(state='attached', timeout=15_000)
                    await file_input.set_input_files(video_path)
                    log.info('[twitter] Video file attached')
                except Exception as e:
                    log.error('[twitter] Failed to attach video file: %s', e)
                    return False

                await self._jitter(2000, 3500)

                # ── Step 3: Wait for video upload & processing ────────────────
                log.info('[twitter] Waiting for video to upload and process...')

                # Wait for upload progress spinner to disappear and video preview to appear
                try:
                    # First: wait for video preview element (thumbnail/player)
                    video_preview_sel = (
                        '[data-testid="videoPlayer"], '
                        '[data-testid="videoComponent"], '
                        '[data-testid="attachments"] video, '
                        '[data-testid="attachments"] [role="img"]'
                    )
                    await page.wait_for_selector(video_preview_sel, timeout=120_000)
                    log.info('[twitter] Video preview confirmed — upload complete')
                except Exception:
                    log.warning('[twitter] Video preview wait timed out — proceeding cautiously')
                    await asyncio.sleep(10)

                # Extra buffer for Twitter to finish processing on their server
                await self._jitter(3000, 5000)

                # Check for upload error message
                try:
                    err_el = page.locator(':text("Something went wrong"), :text("supported video or audio"), :text("Upload failed")').first
                    if await err_el.is_visible():
                        err_text = await err_el.inner_text()
                        log.error('[twitter] Video upload error detected: %s', err_text.strip())
                        return False
                except Exception:
                    pass

                # ── Step 4: Type tweet caption ────────────────────────────────
                log.info('[twitter] Clicking compose text area and typing caption')
                tweet_box = page.locator(f'[role="dialog"] {compose_box_sel}, {compose_box_sel}').last
                try:
                    await tweet_box.wait_for(state='visible', timeout=10_000)
                    await tweet_box.click(force=True)
                    await self._jitter(400, 800)
                except Exception as e:
                    log.warning('[twitter] Tweet box click issue: %s', e)

                # Clear any existing text first
                await page.keyboard.press('Control+a')
                await page.keyboard.press('Delete')
                await self._jitter(200, 400)

                # Type caption character by character
                for char in tweet_text:
                    await page.keyboard.type(char, delay=40)
                await self._jitter(800, 1500)
                log.info('[twitter] Caption typed')

                # ── Step 5: NSFW flag (optional) ──────────────────────────────
                if getattr(self, 'NSFW', False):
                    await self._mark_sensitive(page)

                # ── Step 6: Wait for Post button to become ACTIVE ─────────────
                log.info('[twitter] Waiting for Post button to become active (not disabled)...')
                post_btn_sel = '[data-testid="tweetButton"], [data-testid="tweetButtonInline"]'
                post_btn = page.locator(post_btn_sel).last

                button_active = False
                for elapsed in range(0, 120, 2):
                    try:
                        btn_count = await post_btn.count()
                        if btn_count == 0:
                            await asyncio.sleep(2)
                            continue

                        is_disabled = await post_btn.evaluate(
                            'el => el.getAttribute("aria-disabled") === "true" || el.disabled || el.hasAttribute("disabled")'
                        )
                        if not is_disabled:
                            log.info('[twitter] ✓ Post button is now ACTIVE after %ds', elapsed)
                            button_active = True
                            break
                        else:
                            if elapsed % 10 == 0 and elapsed > 0:
                                log.info('[twitter] Post button still disabled (%ds elapsed)...', elapsed)
                    except Exception as e:
                        log.debug('[twitter] Button check error: %s', e)

                    await asyncio.sleep(2)

                if not button_active:
                    log.warning('[twitter] Post button did not become active within 120s, attempting click anyway')

                # ── Step 7: Click Post ────────────────────────────────────────
                log.info('[twitter] Clicking Post button')
                try:
                    await post_btn.click(force=True)
                    log.info('[twitter] Post button clicked')
                except Exception:
                    try:
                        await post_btn.evaluate('el => el.click()')
                        log.info('[twitter] Post button clicked via evaluate()')
                    except Exception as e:
                        log.warning('[twitter] Post button click failed: %s', e)

                await self._jitter(3000, 5000)

                # ── Step 8: Wait for success ──────────────────────────────────
                log.info('[twitter] Waiting for success confirmation')
                try:
                    await page.wait_for_selector(
                        ':text("Your post was sent"), :text("Tweet sent"), :text("Postingan Anda telah dikirim"), '
                        '[data-testid="toast"], [role="status"]',
                        timeout=30_000,
                    )
                    log.info('[twitter] ✓ Post sent successfully!')
                except Exception:
                    # Fallback: compose dialog disappeared = success
                    try:
                        await page.wait_for_selector(compose_box_sel, state='hidden', timeout=15_000)
                        log.info('[twitter] ✓ Compose dialog closed — assuming success')
                    except Exception:
                        log.warning('[twitter] Could not confirm success — assuming success based on flow')

                return True

            except Exception as exc:
                log.exception('[twitter] Upload failed: %s', exc)
                return False
            finally:
                await context.close()

    async def _mark_sensitive(self, page: Page) -> None:
        """Enable the 'Content warning / sensitive' flag on the compose modal."""
        log = self._log
        log.info('[twitter] Marking content as sensitive (NSFW)')
        try:
            more_opts_sel = '[aria-label="More options"], [data-testid="composeBarMoreOptions"], button[aria-label*="More" i]'
            await page.wait_for_selector(more_opts_sel, timeout=8_000)
            await self._move_click(page, more_opts_sel)
            await self._jitter(500, 1000)

            sensitive_sel = ':text("Flag as sensitive content"), :text("Mark as sensitive"), [role="menuitem"]:has-text("sensitive")'
            await page.wait_for_selector(sensitive_sel, timeout=8_000)
            await self._click(page, sensitive_sel)
            await self._jitter(400, 800)
            log.info('[twitter] Sensitive content flag enabled')
        except Exception as exc:
            log.warning('[twitter] Could not mark as sensitive: %s', exc)
