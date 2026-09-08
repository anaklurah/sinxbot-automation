"""
Twitter / X video publisher.

Auth method: storage_state (cfg.PROFILES_DIR / 'twitter_storage.json')

Posts a tweet with an attached video.  Optionally marks content as sensitive
(NSFW) via the ``NSFW`` class attribute.
"""
import asyncio
from pathlib import Path

from playwright.async_api import async_playwright, BrowserContext, Page

from osap.modules.publisher.base import BasePublisher

_TWEET_MAX_CHARS = 280


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
            2. Click media attachment icon
            3. Set video file via file input
            4. Wait for video to upload/process
            5. Type tweet text (title + tags, max 280 chars)
            6. Optionally mark as sensitive content
            7. Click Post
            8. Wait for success

        Args:
            video_path: Absolute path to the video file.
            title: Tweet text (prepended to tags).
            description: Additional text (appended if space permits).
            tags: Hashtag list (auto-prefixed with #).

        Returns:
            True on success.
        """
        log = self._log
        video_path = str(Path(video_path).resolve())

        # Build tweet text within 280 char limit
        hashtags = ' '.join(f'#{t.lstrip("#")}' for t in tags)
        tweet_text = f'{title} {hashtags}'.strip()
        if len(tweet_text) < _TWEET_MAX_CHARS - 2:
            remaining = _TWEET_MAX_CHARS - len(tweet_text) - 1
            tweet_text = (tweet_text + ' ' + description).strip()[:_TWEET_MAX_CHARS]
        tweet_text = tweet_text[:_TWEET_MAX_CHARS]

        async with async_playwright() as pw:
            context: BrowserContext = await self._get_context(pw)
            page: Page = context.pages[0] if context.pages else await context.new_page()

            try:
                # ── Step 1: Navigate to compose ────────────────────────────────
                log.info('[twitter] Navigating to compose URL')
                await page.goto('https://x.com/compose/tweet', wait_until='domcontentloaded', timeout=60_000)
                await self._jitter(1500, 3000)

                # If redirected to login
                if '/i/flow/login' in page.url or 'login' in page.url:
                    log.error('[twitter] Not authenticated — redirected to login')
                    return False

                # Fallback: if compose URL didn't open a dialog, click compose button
                compose_dialog_sel = '[data-testid="tweetTextarea_0"], [aria-label*="Tweet text" i]'
                try:
                    await page.wait_for_selector(compose_dialog_sel, timeout=8_000)
                except Exception:
                    log.debug('[twitter] Compose dialog not open via URL — clicking compose button')
                    compose_btn_sel = '[data-testid="SideNav_NewTweet_Button"], [aria-label="Post"]'
                    await page.wait_for_selector(compose_btn_sel, timeout=10_000)
                    await self._move_click(page, compose_btn_sel)
                    await self._jitter(1000, 2000)

                # ── Step 2: Click media attachment icon ────────────────────────
                log.info('[twitter] Clicking media attachment icon')
                media_btn_sel = (
                    '[data-testid="attachments"] button, '
                    '[aria-label="Add photos or video"], '
                    '[data-testid="fileInput"] >> ..'
                )
                try:
                    await page.wait_for_selector(media_btn_sel, timeout=10_000)
                    await self._move_click(page, media_btn_sel)
                    await self._jitter(500, 1000)
                except Exception:
                    log.debug('[twitter] Media button not found — trying file input directly')

                # ── Step 3: Set video file ─────────────────────────────────────
                log.info('[twitter] Setting video file: %s', video_path)
                file_input_sel = (
                    'input[data-testid="fileInput"], '
                    'input[type="file"][accept*="video"], '
                    'input[type="file"]'
                )
                file_input = page.locator(file_input_sel).first
                await file_input.wait_for(state='attached', timeout=15_000)
                await file_input.set_input_files(video_path)
                log.info('[twitter] File set')
                await self._jitter(2000, 4000)

                # ── Step 4: Wait for video to upload / process ─────────────────
                log.info('[twitter] Waiting for video upload/processing')
                try:
                    # Twitter shows a progress bar in the compose window
                    processing_sel = (
                        '[data-testid="attachments"] [role="progressbar"], '
                        '[aria-label*="Uploading" i], '
                        '[aria-label*="Processing" i]'
                    )
                    await page.wait_for_selector(processing_sel, timeout=10_000)
                    log.info('[twitter] Upload progress detected, waiting for completion')
                    await page.wait_for_selector(
                        processing_sel, state='hidden', timeout=300_000
                    )
                    log.info('[twitter] Upload complete')
                except Exception:
                    log.warning('[twitter] Could not detect upload progress bar — waiting 15s')
                    await asyncio.sleep(15)

                await self._jitter(1000, 2000)

                # ── Step 5: Type tweet text ────────────────────────────────────
                log.info('[twitter] Typing tweet text: %r', tweet_text[:60])
                tweet_box_sel = (
                    '[data-testid="tweetTextarea_0"], '
                    '[aria-label*="Tweet text" i], '
                    '.public-DraftEditor-content'
                )
                await page.wait_for_selector(tweet_box_sel, timeout=15_000)
                await page.click(tweet_box_sel)
                await self._jitter(300, 600)
                for char in tweet_text:
                    await page.keyboard.type(char, delay=75)
                await self._jitter(600, 1200)

                # ── Step 6: Mark as sensitive (NSFW) if needed ─────────────────
                if self.NSFW:
                    await self._mark_sensitive(page)

                # ── Step 7: Click Post ─────────────────────────────────────────
                log.info('[twitter] Clicking Post button')
                post_btn_sel = (
                    '[data-testid="tweetButtonInline"], '
                    '[data-testid="tweetButton"], '
                    'button:has-text("Post"), '
                    'button:has-text("Tweet")'
                )
                await page.wait_for_selector(post_btn_sel, timeout=15_000)
                await self._move_click(page, post_btn_sel)
                await self._jitter(2000, 4000)

                # ── Step 8: Wait for success ────────────────────────────────────
                log.info('[twitter] Waiting for tweet to post')
                try:
                    # A successful post dismisses the compose dialog and may show a toast
                    await page.wait_for_selector(
                        ':text("Your post was sent"), :text("Tweet sent"), '
                        '[data-testid="toast"], [role="status"]',
                        timeout=20_000,
                    )
                    log.info('[twitter] ✓ Tweet posted successfully')
                except Exception:
                    # Check that compose dialog closed
                    try:
                        await page.wait_for_selector(
                            '[data-testid="tweetTextarea_0"]',
                            state='hidden',
                            timeout=10_000,
                        )
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
        """Enable the "Content warning / sensitive" flag on the compose modal.

        Args:
            page: The active Playwright compose page.
        """
        log = self._log
        log.info('[twitter] Marking content as sensitive (NSFW)')
        try:
            # Open the "more" / additional options menu in the compose dialog
            more_opts_sel = (
                '[aria-label="More options"], '
                '[data-testid="composeBarMoreOptions"], '
                'button[aria-label*="More" i]'
            )
            await page.wait_for_selector(more_opts_sel, timeout=8_000)
            await self._move_click(page, more_opts_sel)
            await self._jitter(500, 1000)

            # Click the sensitive content / content warning option
            sensitive_sel = (
                ':text("Flag as sensitive content"), '
                ':text("Mark as sensitive"), '
                '[role="menuitem"]:has-text("sensitive")'
            )
            await page.wait_for_selector(sensitive_sel, timeout=8_000)
            await self._click(page, sensitive_sel)
            await self._jitter(400, 800)
            log.info('[twitter] Sensitive content flag enabled')

        except Exception as exc:
            log.warning('[twitter] Could not mark as sensitive: %s', exc)
