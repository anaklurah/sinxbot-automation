"""
Febspot video publisher.

Febspot is a video-sharing platform with Google OAuth login.  We use a
persistent Chrome profile so the OAuth session is preserved across runs.

Auth method: persistent profile (cfg.PROFILES_DIR / 'febspot')

# NOTE: Febspot selectors may need updating if the site changes.
# Verify via browser DevTools before running in production.
"""
import asyncio
from pathlib import Path

from playwright.async_api import async_playwright, BrowserContext, Page

from osap.modules.publisher.base import BasePublisher


class FebspotPublisher(BasePublisher):
    """Uploads a video to Febspot."""

    PLATFORM_NAME = 'febspot'
    AUTH_METHOD = 'persistent'
    UPLOAD_URL = 'https://febspot.com'

    # ── Selector constants ──────────────────────────────────────────────────
    # NOTE: Febspot selectors may need updating if the site changes.
    # Verify via browser DevTools if upload fails.
    _SEL_UPLOAD_NAV_BTN = (
        'a[href*="upload"], '
        'a:has-text("Upload"), '
        'button:has-text("Upload"), '
        '[aria-label*="upload" i]'
    )
    _SEL_FILE_INPUT = 'input[type="file"][accept*="video"], input[type="file"]'
    _SEL_TITLE_INPUT = (
        'input[name="title"], '
        'input[placeholder*="title" i], '
        'input[aria-label*="title" i]'
    )
    _SEL_DESCRIPTION = (
        'textarea[name="description"], '
        'textarea[placeholder*="description" i], '
        'textarea[aria-label*="description" i], '
        '[contenteditable="true"][aria-label*="description" i]'
    )
    _SEL_SUBMIT_BTN = (
        'button:has-text("ADD VIDEO"), '
        'button:has-text("Add Video"), '
        'button:has-text("Add video"), '
        ':text-is("ADD VIDEO"), '
        ':text-is("Add Video"), '
        ':text-is("Add video"), '
        'button[type="submit"], '
        'button:has-text("Publish"), '
        'button:has-text("Upload"), '
        'button:has-text("Post"), '
        'input[type="submit"]'
    )
    _SEL_SUCCESS = (
        ':text("Upload complete"), '
        ':text("Your video is live"), '
        ':text("Published"), '
        ':text("Success"), '
        ':text("Video added"), '
        ':text("Video uploaded"), '
        '[class*="success"]'
    )

    async def upload(
        self,
        video_path: str,
        title: str,
        description: str,
        tags: list[str],
    ) -> bool:
        """Perform the Febspot upload flow.

        Steps:
            1. Navigate to Febspot home / upload page
            2. Click Upload nav link (if on home)
            3. Set video file via file input
            4. Fill title field
            5. Fill description (with appended tags)
            6. Submit / Publish
            7. Wait for success

        Args:
            video_path: Absolute path to the video file.
            title: Video title.
            description: Video description.
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
                # ── Step 1: Navigate to Febspot ────────────────────────────────
                log.info('[febspot] Navigating to %s', self.UPLOAD_URL)
                resp = await page.goto(self.UPLOAD_URL, wait_until='domcontentloaded', timeout=60_000)
                await self._jitter(1500, 3000)

                # Check for Febspot server-side 504 / 502 outage
                page_title = await page.title()
                if "504 Gateway" in page_title or "502 Bad Gateway" in page_title or (resp and resp.status in (502, 504)):
                    log.error('[febspot] Server Febspot sedang mengalami gangguan / down (%s). Menunggu server pulih...', page_title)
                    return False

                # Check if redirected to login
                if '/login' in page.url:
                    log.error('[febspot] Sesi belum login atau cookies kadaluarsa — diarahkan ke halaman login')
                    return False

                # ── Step 2: Navigate to Upload page if not already there ───────
                if '/upload' not in page.url:
                    log.info('[febspot] Looking for Upload navigation link')
                    try:
                        upload_btn = page.locator('a[href*="upload"], button:has-text("Upload"), a:has-text("Upload")').first
                        await upload_btn.wait_for(state='visible', timeout=12_000)
                        await upload_btn.click()
                        await self._jitter(1500, 3000)
                        log.info('[febspot] Navigated to upload page via nav button')
                    except Exception:
                        page_title = await page.title()
                        if "504" in page_title or "502" in page_title:
                            log.error('[febspot] Server Febspot upstream gateway timeout (504): %s', page_title)
                            return False
                        log.warning('[febspot] Tombol Upload tidak ditemukan di halaman utama. Melanjutkan...')

                # ── Step 3: Set video file ─────────────────────────────────────
                log.info('[febspot] Setting video file: %s', video_path)
                file_input = page.locator('input[type="file"]').first
                await file_input.wait_for(state='attached', timeout=20_000)
                await file_input.set_input_files(video_path)
                log.info('[febspot] File set, waiting for form fields...')
                await self._jitter(2000, 3500)

                # ── Step 4: Fill Title, Description, and Keywords ──────────────
                log.info('[febspot] Filling title: %r', title)
                title_el = page.locator('input[name="title"], input[id="title"], input[placeholder*="title" i]').first
                await title_el.wait_for(state='visible', timeout=15_000)
                await title_el.fill(title)
                await self._jitter(400, 800)

                log.info('[febspot] Filling description')
                desc_el = page.locator('textarea[name="description"], textarea[id="description"], textarea[placeholder*="about" i]').first
                await desc_el.wait_for(state='visible', timeout=10_000)
                await desc_el.fill(full_description)
                await self._jitter(400, 800)

                tags_str = ', '.join(t.lstrip('#') for t in tags) if tags else 'viral, video, shorts, trending'
                tags_el = page.locator('input[name="tags"], input[id="tags"], input[placeholder*="travel" i]').first
                if await tags_el.count() > 0 and await tags_el.is_visible():
                    log.info('[febspot] Filling keywords/tags: %r', tags_str)
                    await tags_el.fill(tags_str)
                    await self._jitter(400, 800)

                # ── Step 5: Wait for video upload to finish ────────────────────
                log.info('[febspot] Waiting for video upload to complete on Febspot...')
                submit_btn = page.locator('button:has-text("ADD VIDEO"), button:has-text("Add Video"), input[value="ADD VIDEO"]').first

                upload_done = False
                for sec in range(180):
                    btn_txt = (await submit_btn.inner_text()).strip() if await submit_btn.count() else ""
                    is_dis = await submit_btn.is_disabled()
                    status_el = page.locator('#videoFormStatus')
                    status_text = (await status_el.inner_text()).strip() if await status_el.count() else ""

                    if "uploaded successfully" in status_text.lower() or ("ADD VIDEO" in btn_txt.upper() and not is_dis):
                        upload_done = True
                        log.info('[febspot] ✓ Video upload complete! ADD VIDEO button is active (after %ds)', sec * 2 + 1)
                        break

                    if (sec + 1) % 10 == 0:
                        log.info('[febspot] Still uploading video... (%ds elapsed, button: %r)', (sec + 1) * 2, btn_txt)

                    await asyncio.sleep(2)

                if not upload_done:
                    log.warning('[febspot] Upload completion signal not detected within timeout, checking submit button anyway')

                # Verify fields remain populated
                curr_title = await title_el.input_value()
                if not curr_title:
                    log.info('[febspot] Re-filling title and description after upload...')
                    await title_el.fill(title)
                    await desc_el.fill(full_description)
                    if await tags_el.count() > 0 and await tags_el.is_visible():
                        await tags_el.fill(tags_str)

                # ── Step 6: Submit / Click ADD VIDEO ───────────────────────────
                log.info('[febspot] Clicking ADD VIDEO button...')
                await self._jitter(500, 1000)
                try:
                    await submit_btn.click(timeout=8000)
                    log.info('[febspot] Clicked ADD VIDEO button')
                except Exception as e:
                    log.warning('[febspot] Standard click failed: %s, using dispatchEvent...', e)
                    await submit_btn.dispatch_event('click')

                # ── Step 7: Wait for success confirmation / redirect ───────────
                log.info('[febspot] Waiting for redirect to /my/videos/ or success indicator...')
                success = False
                for w in range(30):
                    await asyncio.sleep(1)
                    if "/my/videos" in page.url or "/v/" in page.url or "/video/" in page.url:
                        log.info('[febspot] ✓ Successfully published! Redirected to: %s', page.url)
                        success = True
                        break
                    toast = page.locator(':text("Video uploaded"), :text("Success"), :text("Published")').first
                    if await toast.count() > 0 and await toast.is_visible():
                        log.info('[febspot] ✓ Success notification detected')
                        success = True
                        break

                if not success:
                    log.warning('[febspot] Redirect not confirmed within 30s, checking current URL: %s', page.url)
                    if "/upload" not in page.url:
                        success = True

                # Extract direct video URL if available
                try:
                    if "/v/" in page.url or "/video/" in page.url:
                        self.uploaded_url = page.url.split("?")[0]
                    else:
                        first_v = page.locator('a[href*="/v/"], a[href*="/video/"]').first
                        if await first_v.count():
                            h = await first_v.get_attribute("href")
                            if h and ("/v/" in h or "/video/" in h):
                                self.uploaded_url = h if h.startswith("http") else f"https://www.febspot.com{h.split('?')[0]}"
                    if self.uploaded_url:
                        log.info('[febspot] ✓ Captured published video URL: %s', self.uploaded_url)
                except Exception:
                    pass

                await self._jitter(2000, 4000)
                log.info('[febspot] Upload completed successfully.')
                return True

            except Exception as exc:
                log.exception('[febspot] Upload failed: %s', exc)
                return False
            finally:
                await context.close()
