"""
YouTube Shorts publisher.

Uses a persistent Chromium profile so the user only needs to log in once via
a manual browser session.  All subsequent runs reuse the saved session.

Auth method: persistent profile (cfg.PROFILES_DIR / 'youtube')
"""
import asyncio
from pathlib import Path

from playwright.async_api import async_playwright, BrowserContext, Page

from osap.modules.publisher.base import BasePublisher
from osap.utils.logger import get_logger


class YouTubePublisher(BasePublisher):
    """Uploads a video to YouTube Studio as a Short / regular upload."""

    PLATFORM_NAME = 'youtube'
    AUTH_METHOD = 'persistent'
    UPLOAD_URL = 'https://studio.youtube.com'

    async def upload(
        self,
        video_path: str,
        title: str,
        description: str,
        tags: list[str],
    ) -> bool:
        """Perform the full YouTube Studio upload flow.

        Steps:
            1. Navigate to YouTube Studio
            2. Trigger file-upload dialog
            3. Set input file
            4. Fill title, description, audience
            5. Step through wizard to Visibility → Public
            6. Save / Publish
            7. Confirm success

        Args:
            video_path: Absolute path to the video file.
            title: Video title (max 100 chars; truncated if longer).
            description: Video description.
            tags: List of tag strings (added to description footer).

        Returns:
            True on success.
        """
        log = self._log
        video_path = str(Path(video_path).resolve())

        async with async_playwright() as pw:
            context: BrowserContext = await self._get_context(pw)
            page: Page = context.pages[0] if context.pages else await context.new_page()

            try:
                # ── Step 1: Navigate ──────────────────────────────────────────
                log.info('[youtube] Navigating to %s', self.UPLOAD_URL)
                await page.goto(self.UPLOAD_URL, wait_until='domcontentloaded', timeout=60_000)
                await self._jitter(2000, 3500)

                # Check URL and Auth status
                curr_url = page.url
                page_title = await page.title()
                log.info('[youtube] Navigation complete. URL: %s | Title: %r', curr_url, page_title)

                if 'accounts.google.com' in curr_url:
                    log.error(
                        '[youtube] GAGAL: Terdeteksi redirect ke Google Login (%s). '
                        'Session YouTube belum aktif atau cookies expired! '
                        'Silakan upload file profil "youtube.zip" atau cookies terbaru melalui Dashboard Web.',
                        curr_url
                    )
                    await self._save_debug_screenshot(page, 'google_login')
                    return False

                # Dismiss initial modal / popup dialogs if present
                await self._dismiss_popups(page)

                # ── Step 2: Ensure Studio UI is ready & click upload ───────────
                log.info('[youtube] Preparing file upload dialog...')
                file_input_sel = 'input[type="file"]'

                # If file input is already present in DOM
                file_input_ready = False
                try:
                    if await page.locator(file_input_sel).count() > 0:
                        file_input_ready = True
                        log.info('[youtube] input[type="file"] is already present on page')
                except Exception:
                    pass

                # Strategy 1: Direct upload deep link if on channel URL
                if not file_input_ready:
                    curr_url = page.url
                    if '/channel/' in curr_url and 'd=ud' not in curr_url:
                        channel_base = curr_url.split('?')[0].rstrip('/')
                        upload_deep_link = f"{channel_base}/videos/upload?d=ud"
                        log.info('[youtube] Trying direct upload deep link: %s', upload_deep_link)
                        try:
                            await page.goto(upload_deep_link, wait_until='domcontentloaded', timeout=25_000)
                            await self._jitter(2000, 3000)
                            if await page.locator(file_input_sel).count() > 0:
                                file_input_ready = True
                                log.info('[youtube] Direct deep link opened upload dialog successfully!')
                        except Exception as dl_err:
                            log.debug('[youtube] Direct deep link failed: %s', dl_err)

                if not file_input_ready:
                    # Wait for Studio UI elements to hydrate
                    studio_ready_sel = (
                        'ytcp-button:has-text("Create"), button:has-text("Create"), '
                        'ytcp-button:has-text("Buat"), button:has-text("Buat"), '
                        '#create-icon, #create-button, [aria-label*="Create" i], '
                        '[aria-label*="Upload" i], input[type="file"]'
                    )
                    try:
                        await page.wait_for_selector(studio_ready_sel, timeout=25_000, state='attached')
                        log.info('[youtube] Studio elements attached to DOM')
                    except Exception as wait_err:
                        log.warning('[youtube] Studio indicator wait timed out: %s', wait_err)
                        if 'accounts.google.com' in page.url:
                            log.error('[youtube] Redirected to Google login: %s', page.url)
                            await self._save_debug_screenshot(page, 'google_login')
                            return False

                    # Dismiss any popups that appeared after hydration
                    await self._dismiss_popups(page)

                    upload_clicked = False

                    # Strategy 2: Click "+ Create" button in header (Visible on every YouTube Studio page)
                    create_selectors = [
                        'ytcp-button:has-text("Create")',
                        'button:has-text("Create")',
                        'ytcp-button:has-text("Buat")',
                        'button:has-text("Buat")',
                        '#create-icon',
                        '#create-button',
                        'ytcp-button#create-icon',
                        'ytcp-icon-button#create-icon',
                        '[aria-label*="Create" i]',
                        '[aria-label*="Buat" i]',
                        'ytcp-header ytcp-button',
                    ]
                    for create_sel in create_selectors:
                        try:
                            create_btn = page.locator(create_sel).first
                            if await create_btn.count() and await create_btn.is_visible():
                                log.info('[youtube] Clicking Create button: %s', create_sel)
                                await create_btn.click()
                                await self._jitter(800, 1500)

                                menu_selectors = [
                                    'tp-yt-paper-item:has-text("Upload")',
                                    'tp-yt-paper-item:has-text("Unggah")',
                                    'ytcp-text-menu tp-yt-paper-item',
                                    '#text-item-0',
                                    '[test-id="upload-action"]',
                                    '[role="menuitem"]:has-text("Upload")',
                                    '[role="menuitem"]:has-text("Unggah")',
                                ]
                                for menu_sel in menu_selectors:
                                    try:
                                        menu_item = page.locator(menu_sel).first
                                        await menu_item.wait_for(state='visible', timeout=4_000)
                                        log.info('[youtube] Clicking "Upload videos" / "Unggah video" from menu: %s', menu_sel)
                                        await menu_item.click()
                                        upload_clicked = True
                                        await self._jitter(1000, 2000)
                                        break
                                    except Exception:
                                        pass

                                if upload_clicked:
                                    break
                        except Exception as e:
                            log.debug('[youtube] Create selector %s failed: %s', create_sel, e)

                    # Strategy 3: Direct Upload icon on the dashboard (up-arrow circle button)
                    if not upload_clicked:
                        log.info('[youtube] Trying direct upload icon button on dashboard...')
                        direct_selectors = [
                            'ytcp-icon-button[aria-label*="Upload" i]',
                            'ytcp-icon-button[aria-label*="Unggah" i]',
                            '[aria-label*="Upload videos" i]',
                            '[aria-label*="Upload video" i]',
                            '[aria-label*="Unggah video" i]',
                            'ytcp-button:has-text("Upload")',
                            'ytcp-button:has-text("Unggah")',
                            'ytcp-button#upload-icon',
                            '#upload-icon',
                            'ytcp-icon-button#upload-icon',
                            'ytcp-channel-dashboard-renderer ytcp-icon-button',
                            '#channel-dashboard-header ytcp-icon-button',
                        ]
                        for direct_sel in direct_selectors:
                            try:
                                el = page.locator(direct_sel).first
                                if await el.count() and await el.is_visible():
                                    log.info('[youtube] Clicking direct upload button: %s', direct_sel)
                                    await el.click()
                                    upload_clicked = True
                                    await self._jitter(1000, 2000)
                                    break
                            except Exception:
                                pass

                # ── Step 3: Set file via input ────────────────────────────────
                log.info('[youtube] Setting input file: %s', video_path)
                try:
                    await page.wait_for_selector(file_input_sel, timeout=30_000, state='attached')
                except Exception as wait_file_err:
                    log.error('[youtube] Timeout waiting for input[type="file"]. Current URL: %s', page.url)
                    await self._save_debug_screenshot(page, 'file_input_timeout')
                    raise wait_file_err

                await page.locator(file_input_sel).first.set_input_files(video_path)
                log.info('[youtube] File attached, waiting for upload dialog to open')

                # Wait for title field to appear in the details dialog
                log.info('[youtube] Waiting for details dialog and title field...')
                title_sel = (
                    '#title-textarea #textbox, '
                    'ytcp-uploads-dialog #title-textarea #textbox, '
                    '[aria-label*="title" i] #textbox, '
                    '[aria-label*="judul" i] #textbox, '
                    '#textbox[aria-label*="title" i], '
                    '#textbox[aria-label*="judul" i], '
                    'ytcp-video-title #textbox'
                )
                try:
                    title_box = page.locator(title_sel).first
                    await title_box.wait_for(state='visible', timeout=45_000)
                except Exception:
                    # Fallback: wait for any textbox inside dialog
                    log.warning('[youtube] Primary title selector timed out, trying generic textbox')
                    title_box = page.locator('#textbox').first
                    await title_box.wait_for(state='visible', timeout=20_000)

                await self._jitter(1000, 2000)

                # ── Step 4a: Fill title ───────────────────────────────────────
                log.info('[youtube] Filling title: %r', title[:100])
                await title_box.click()
                await title_box.press('Control+a')
                await self._jitter(200, 400)
                await human_type_locator(title_box, title[:100])
                await self._jitter(400, 800)

                # ── Step 4b: Fill description ─────────────────────────────────
                log.info('[youtube] Filling description')
                desc_sel = (
                    'ytcp-uploads-dialog #description-textarea #textbox, '
                    '#description-textarea #textbox, '
                    '[aria-label="Description"] #textbox'
                )
                desc_text = description
                if tags:
                    desc_text += '\n' + ' '.join(f'#{t.lstrip("#")}' for t in tags)

                desc_box = page.locator(desc_sel).first
                await desc_box.click()
                await desc_box.press('Control+a')
                await self._jitter(200, 400)
                await human_type_locator(desc_box, desc_text)
                await self._jitter(400, 900)

                # ── Step 5: Audience — "Not for kids" ─────────────────────────
                log.info('[youtube] Selecting "Not for kids"')
                not_for_kids_sel = (
                    '[name="VIDEO_MADE_FOR_KIDS_NOT_MFK"], '
                    '#radioLabel-made-for-kids-no, '
                    'tp-yt-paper-radio-button[name="VIDEO_MADE_FOR_KIDS_NOT_MFK"]'
                )
                try:
                    await page.wait_for_selector(not_for_kids_sel, timeout=10_000)
                    await self._move_click(page, not_for_kids_sel)
                    await self._jitter(300, 700)
                except Exception:
                    log.warning('[youtube] Could not find "Not for kids" radio — skipping')

                # ── Steps 6–8: Click through wizard ───────────────────────────
                next_btn_sel = (
                    'ytcp-button#next-button, '
                    '#next-button, '
                    '[aria-label="Next"], '
                    '[aria-label="Berikutnya"], '
                    'ytcp-button:has-text("Next"), '
                    'ytcp-button:has-text("Berikutnya")'
                )
                for step_name in ('Video elements', 'Checks', 'Visibility'):
                    log.info('[youtube] Advancing to step: %s', step_name)
                    try:
                        await page.wait_for_selector(next_btn_sel, timeout=15_000)
                        await self._move_click(page, next_btn_sel)
                        await self._jitter(1500, 3000)
                    except Exception:
                        log.warning('[youtube] Next button not found at step %r', step_name)

                # ── Step 9: Select "Public" visibility ────────────────────────
                log.info('[youtube] Selecting Public visibility')
                public_sel = (
                    '[name="PUBLIC"], '
                    '#radioLabel-visibility-public, '
                    'tp-yt-paper-radio-button[name="PUBLIC"]'
                )
                try:
                    await page.wait_for_selector(public_sel, timeout=15_000)
                    await self._move_click(page, public_sel)
                    await self._jitter(500, 1000)
                except Exception:
                    log.warning('[youtube] Could not find Public radio button')

                # ── Step 10: Wait for upload transfer to finish ────────────────
                log.info('[youtube] Ensuring video file upload is complete before publishing...')
                progress_label_sel = (
                    'ytcp-video-upload-progress span, '
                    '.progress-label, '
                    'span:has-text("Uploading"), '
                    'span:has-text("Mengunggah")'
                )
                for elapsed in range(0, 180, 2):
                    still_uploading = False
                    try:
                        progress_el = page.locator(progress_label_sel).first
                        if await progress_el.count() and await progress_el.is_visible():
                            txt = (await progress_el.inner_text()).lower()
                            if "uploading" in txt or "mengunggah" in txt:
                                still_uploading = True
                                if elapsed % 10 == 0:
                                    log.info('[youtube] Still uploading file to YouTube: %s (%ds elapsed)', txt, elapsed)
                    except Exception:
                        pass

                    if not still_uploading:
                        log.info('[youtube] File upload transfer complete!')
                        break
                    await asyncio.sleep(2)

                save_sel = (
                    'ytcp-button#done-button, '
                    '#done-button, '
                    '[aria-label="Publish"], '
                    '[aria-label="Publikasikan"], '
                    '[aria-label="Save"], '
                    '[aria-label="Simpan"], '
                    'ytcp-button:has-text("Publish"), '
                    'ytcp-button:has-text("Publikasikan")'
                )
                # Wait up to 30s for save button to be active
                for _ in range(20):
                    try:
                        btn = page.locator(save_sel).first
                        if await btn.is_visible() and await btn.is_enabled():
                            log.info('[youtube] Save/Publish button is active and ready')
                            break
                    except Exception:
                        pass
                    await asyncio.sleep(1.5)

                await self._jitter(800, 1500)

                # ── Step 11: Click Save / Publish ─────────────────────────────
                log.info('[youtube] Clicking Save/Publish')
                await page.wait_for_selector(save_sel, timeout=15_000)
                await self._move_click(page, save_sel)
                await self._jitter(2000, 4000)

                # ── Step 12: Confirm success ──────────────────────────────────
                log.info('[youtube] Waiting for success confirmation')
                success_sel = (
                    ':text("Your video is published"), '
                    ':text("Video published"), '
                    ':text("Your video is now live"), '
                    ':text("Video dipublikasikan"), '
                    ':text("dipublikasikan"), '
                    'ytcp-video-published-dialog, '
                    '[class*="published"]'
                )
                try:
                    await page.wait_for_selector(success_sel, timeout=25_000)
                    log.info('[youtube] ✓ Upload published successfully')
                except Exception:
                    log.warning('[youtube] Could not detect explicit success dialog — assuming success')

                # Extract direct video link from YouTube Studio upload/success dialog
                try:
                    link_loc = page.locator('a[href*="youtu.be"], a.ytcp-video-info, [class*="video-url-link"] a, a[href*="/shorts/"]').first
                    if await link_loc.count():
                        href = await link_loc.get_attribute("href")
                        if href and ("youtu.be" in href or "/shorts/" in href or "/watch" in href):
                            self.uploaded_url = href.strip()
                            log.info('[youtube] ✓ Captured direct video URL: %s', self.uploaded_url)
                except Exception as ex:
                    log.debug('[youtube] Could not extract video URL from dialog: %s', ex)

                # Hold context open 5 seconds to ensure backend persistence
                await self._jitter(4000, 6000)
                return True

            except Exception as exc:
                log.exception('[youtube] Upload failed: %s', exc)
                try:
                    await self._save_debug_screenshot(page, 'error')
                except Exception:
                    pass
                return False
            finally:
                await context.close()

    async def _dismiss_popups(self, page: Page) -> None:
        """Dismiss common YouTube Studio welcome modals, privacy banners, and prompts."""
        dismiss_selectors = [
            'ytcp-confirmation-dialog #confirm-button',
            'ytcp-button#dismiss-button',
            'button:has-text("Continue")',
            'button:has-text("Lanjutkan")',
            'button:has-text("Dismiss")',
            'button:has-text("Tutup")',
            'button:has-text("Mengerti")',
            'button:has-text("Got it")',
            'tp-yt-paper-dialog button:has-text("Lanjutkan")',
            'tp-yt-paper-dialog button:has-text("Continue")',
            'button:has-text("Accept all")',
            'button:has-text("Setuju semua")',
            'button:has-text("I agree")',
            'button:has-text("Saya setuju")',
        ]
        for sel in dismiss_selectors:
            try:
                btn = page.locator(sel).first
                if await btn.count() and await btn.is_visible():
                    self._log.info('[youtube] Dismissing popup dialog: %s', sel)
                    await btn.click()
                    await asyncio.sleep(1)
            except Exception:
                pass



async def human_type_locator(locator, text: str, delay_ms: float = 60) -> None:
    """Type *text* character by character into a Playwright Locator.

    Used internally because human_type from osap.utils expects a selector
    string, but here we already have a resolved Locator.

    Args:
        locator: A Playwright ``Locator`` instance.
        text: The string to type.
        delay_ms: Average inter-keystroke delay in milliseconds.
    """
    import random
    for char in text:
        await locator.press_sequentially(char, delay=int(delay_ms + random.uniform(-20, 40)))
