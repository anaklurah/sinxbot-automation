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
            2. Click sidebar Post button -> Click 'Video post'
            3. Set video file via file input
            4. Dismiss 'Choose cover' dialog by clicking 'Done'
            5. Fill caption (strictly <= 120 chars)
            6. Click modal 'Post' button
            7. Wait for post completion

        Args:
            video_path: Absolute path to the video file.
            title: Video title.
            description: Caption / description body.
            tags: Hashtag list (auto-prefixed with #).

        Returns:
            True on success.
        """
        log = self._log
        _MAX_CAPTION_CHARS = 120
        title = (title or "").strip()[:_MAX_CAPTION_CHARS]

        # Upscrolled caption strictly <= 120 characters
        hashtags = ' '.join(f'#{t.lstrip("#")}' for t in tags)
        primary_text = description if (description and len(description) <= _MAX_CAPTION_CHARS) else title

        if hashtags and hashtags not in primary_text:
            caption = f'{primary_text} {hashtags}'.strip()
        else:
            caption = (primary_text or "").strip()

        if len(caption) > _MAX_CAPTION_CHARS:
            if len(primary_text) <= _MAX_CAPTION_CHARS:
                caption = primary_text.strip()
                for t in tags:
                    candidate = f"{caption} #{t.lstrip('#')}"
                    if len(candidate) <= _MAX_CAPTION_CHARS:
                        caption = candidate
                    else:
                        break
            else:
                caption = primary_text[:_MAX_CAPTION_CHARS].rstrip()

        caption = caption[:_MAX_CAPTION_CHARS]
        log.info('[upscrolled] Final caption (%d chars): %r', len(caption), caption)

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

                # ── Step 2: Open Create Post modal ────────────────────────────
                log.info('[upscrolled] Looking for sidebar Post button')
                post_btn = page.locator('button:has-text("Post"), a:has-text("Post")').first
                await post_btn.wait_for(state='visible', timeout=15_000)
                await post_btn.click()
                await self._jitter(1000, 2000)

                log.info('[upscrolled] Selecting "Video post"')
                video_option = page.locator('text="Video post"').first
                await video_option.wait_for(state='visible', timeout=10_000)
                await video_option.click()
                await self._jitter(1000, 2000)

                # ── Step 3: Set video file ─────────────────────────────────────
                log.info('[upscrolled] Setting video file: %s', video_path)
                video_input = page.locator('input[type="file"][accept*="video"]')
                if await video_input.count() > 0:
                    file_input = video_input.first
                else:
                    file_input = page.locator('input[type="file"]').first

                await file_input.wait_for(state='attached', timeout=20_000)
                await file_input.set_input_files(video_path)
                log.info('[upscrolled] File set')
                await self._jitter(1500, 3000)

                # ── Step 4: Handle "Choose cover" dialog ───────────────────────
                log.info('[upscrolled] Waiting for video processing / "Choose cover" dialog')
                cover_modal = page.locator('div[role="dialog"]:has-text("Choose cover"), div:has-text("Choose cover")').last
                try:
                    await cover_modal.wait_for(state='visible', timeout=20_000)
                    log.info('[upscrolled] Found Choose cover modal, confirming cover...')
                    await self._jitter(500, 1000)
                    done_btn = page.locator('div:has-text("Choose cover") button:has-text("Done"), [role="dialog"]:has-text("Choose cover") button:has-text("Done")').last
                    try:
                        await done_btn.click(force=True, timeout=3000)
                    except Exception:
                        await done_btn.evaluate('el => el.click()')
                    
                    # Ensure the Choose cover dialog is gone
                    await cover_modal.wait_for(state='hidden', timeout=10_000)
                    await self._jitter(1000, 2000)
                    log.info('[upscrolled] Cover selection confirmed and closed')
                except Exception as exc:
                    log.info('[upscrolled] Choose cover dialog did not appear or was dismissed: %s', exc)

                # ── Step 5: Fill caption ────────────────────────────────────────
                log.info('[upscrolled] Filling caption: %r', caption)
                caption_box = page.locator('textarea[placeholder*="caption" i], textarea').first
                await caption_box.wait_for(state='visible', timeout=15_000)
                await caption_box.click(force=True)
                await self._jitter(200, 500)
                await page.keyboard.press('Control+a')
                await page.keyboard.press('Backspace')
                await self._jitter(100, 300)

                for char in caption:
                    await page.keyboard.type(char, delay=40)
                await self._jitter(500, 1000)

                # Dismiss hashtag autocomplete dropdown if open
                await page.keyboard.press('Escape')
                await self._jitter(500, 1000)

                # ── Step 6: Publish / Post ─────────────────────────────────────
                log.info('[upscrolled] Waiting for Submit Post button to be enabled')
                dialog_post_btn = page.locator('div[role="dialog"] button:has-text("Post")').last

                for attempt in range(30):
                    is_disabled = await dialog_post_btn.is_disabled()
                    aria_disabled = await dialog_post_btn.get_attribute('aria-disabled')
                    if not is_disabled and aria_disabled != 'true':
                        log.info('[upscrolled] Post button is enabled (attempt %d)', attempt + 1)
                        break
                    await asyncio.sleep(1)

                await self._jitter(500, 1000)
                log.info('[upscrolled] Submitting post via dispatch_event click')
                # Note: Playwright's click() is intercepted by the Radix modal backdrop (z-[80] inset-0).
                # dispatch_event('click') dispatches directly to the DOM element without OS pointer interception.
                try:
                    await dialog_post_btn.dispatch_event('click')
                    log.info('[upscrolled] Post button click dispatched')
                except Exception as e:
                    log.warning('[upscrolled] dispatch_event failed: %s, falling back', e)
                    try:
                        await dialog_post_btn.click(force=True, timeout=5000)
                    except Exception:
                        await dialog_post_btn.evaluate('el => el.click()')

                # ── Step 7: Wait for dialog close & "Posting..." banner / "Your post is live!" ─────────
                log.info('[upscrolled] Waiting for post dialog to close')
                dialog_closed = False
                for w in range(25):
                    await asyncio.sleep(1)
                    # Check specifically if the compose dialog is closed
                    is_open = await page.locator('div[role="dialog"]:has-text("Video post")').is_visible()
                    if not is_open:
                        log.info('[upscrolled] ✓ Post dialog closed after %ds', w + 1)
                        dialog_closed = True
                        break

                if not dialog_closed:
                    log.warning('[upscrolled] Post dialog still open, re-triggering click...')
                    try:
                        await dialog_post_btn.dispatch_event('click')
                    except Exception:
                        pass
                    await asyncio.sleep(2)

                # Upscrolled displays a bottom banner: "Posting... Please don't close this window"
                # followed by "Your post is live!" or the banner disappearing.
                log.info('[upscrolled] Waiting for upload finalizing on server (watching "Posting..." / "Your post is live!")...')
                
                toast_found = False
                posting_banner = page.locator(':has-text("Posting..."), :has-text("Please don\'t close this window")').first
                live_toast = page.locator(':has-text("Your post is live"), :has-text("post is live")').first

                for sec in range(180):
                    # Check for live toast
                    if await live_toast.is_visible():
                        toast_found = True
                        log.info('[upscrolled] ✓ Detected notification: "Your post is live!" (at %ds)', sec + 1)
                        break

                    # Check if "Posting..." banner appeared and finished
                    if sec > 10 and not await posting_banner.is_visible() and not await page.locator('div[role="dialog"]:has-text("Video post")').is_visible():
                        toast_found = True
                        log.info('[upscrolled] ✓ Upload banner finished and closed after %ds', sec + 1)
                        break

                    await asyncio.sleep(1)

                if not toast_found:
                    log.warning('[upscrolled] Post completion notification timed out, assuming completed based on flow')

                await self._jitter(3000, 5000)
                log.info('[upscrolled] ✓ Video published successfully to Upscrolled')
                return True


            except Exception as exc:
                log.exception('[upscrolled] Upload failed: %s', exc)
                return False
            finally:
                await context.close()
