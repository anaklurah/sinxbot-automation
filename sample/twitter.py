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
from osap.utils.human_delay import human_type_organic

_TWEET_MAX_CHARS = 120


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
            1. Navigate to compose URL (https://x.com/compose/post)
            2. Set video file directly via file input (avoids Grok menu popup)
            3. Wait for video upload / processing
            4. Type tweet text in the active modal dialog (max 120 chars)
            5. Optionally mark as sensitive content (if NSFW=True)
            6. Click Post / Posting button in the modal
            7. Wait for success confirmation or modal dismissal

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

        # Strict constraint: Twitter/X tweet text <= 120 characters
        hashtags = ' '.join(f'#{t.lstrip("#")}' for t in tags)
        primary_text = description if (description and len(description) <= _TWEET_MAX_CHARS) else title

        if hashtags and hashtags not in primary_text:
            tweet_text = f'{primary_text} {hashtags}'.strip()
        else:
            tweet_text = (primary_text or "").strip()

        if len(tweet_text) > _TWEET_MAX_CHARS:
            if len(primary_text) <= _TWEET_MAX_CHARS:
                tweet_text = primary_text.strip()
                for t in tags:
                    candidate = f"{tweet_text} #{t.lstrip('#')}"
                    if len(candidate) <= _TWEET_MAX_CHARS:
                        tweet_text = candidate
                    else:
                        break
            else:
                tweet_text = primary_text[:_TWEET_MAX_CHARS].rstrip()

        tweet_text = tweet_text[:_TWEET_MAX_CHARS]
        log.info('[twitter] Final tweet text (%d chars): %r', len(tweet_text), tweet_text)

        async with async_playwright() as pw:
            context: BrowserContext = await self._get_context(pw)
            page: Page = context.pages[0] if context.pages else await context.new_page()

            try:
                # ── Step 1: Navigate to compose ────────────────────────────────
                log.info('[twitter] Navigating to compose URL: https://x.com/compose/post')
                await page.goto('https://x.com/compose/post', wait_until='domcontentloaded', timeout=60_000)
                await self._jitter(2000, 3500)

                # If redirected to login
                if '/i/flow/login' in page.url or 'login' in page.url:
                    log.error('[twitter] Not authenticated — redirected to login')
                    return False

                # Ensure active visible modal dialog is present
                dialog_sel = 'div[role="dialog"]:visible'
                try:
                    await page.wait_for_selector(dialog_sel, timeout=12_000)
                except Exception:
                    log.debug('[twitter] Compose dialog not visible — clicking compose button')
                    compose_btn_sel = (
                        '[data-testid="SideNav_NewTweet_Button"], '
                        '[aria-label="Post"], '
                        '[aria-label="Posting"]'
                    )
                    await page.wait_for_selector(compose_btn_sel, timeout=10_000)
                    await self._move_click(page, compose_btn_sel)
                    await page.wait_for_selector(dialog_sel, timeout=15_000)

                dialog = page.locator(dialog_sel).first

                # ── Step 2: Set video file strictly in visible dialog ─────────
                log.info('[twitter] Setting video file inside active dialog: %s', video_path)
                file_input = dialog.locator('input[type="file"]').first
                await file_input.wait_for(state='attached', timeout=15_000)
                await file_input.set_input_files(video_path)
                log.info('[twitter] File set successfully')

                # ── Step 3: Wait for video preview element in dialog ──────────
                media_preview_sel = (
                    'div[role="dialog"]:visible video, '
                    'div[role="dialog"]:visible [aria-label*="Hapus"], '
                    'div[role="dialog"]:visible [aria-label*="Remove"]'
                )
                try:
                    await page.wait_for_selector(media_preview_sel, timeout=20_000)
                    log.info('[twitter] Video attachment detected in compose dialog')
                except Exception:
                    log.warning('[twitter] Video preview element not detected within 20s')

                # ── Step 4: Type tweet text inside active modal dialog ─────────
                log.info('[twitter] Typing tweet text in dialog: %r', tweet_text[:60])
                tweet_box = dialog.locator('[data-testid="tweetTextarea_0"], [role="textbox"]').first
                await tweet_box.wait_for(state='visible', timeout=15_000)
                await tweet_box.click()
                await self._jitter(400, 800)
                await human_type_organic(page, tweet_text)
                await self._jitter(800, 1500)

                # ── Step 5: Wait for video upload & processing to finish ───────
                log.info('[twitter] Waiting for video upload and processing to complete (button is disabled while uploading)...')
                post_btn = dialog.locator(
                    '[data-testid="tweetButton"], '
                    'button:has-text("Posting"), '
                    'button:has-text("Post")'
                ).first
                await post_btn.wait_for(state='attached', timeout=15_000)

                video_ready = False
                max_wait_sec = 240  # up to 4 minutes for larger videos
                for sec in range(max_wait_sec):
                    await asyncio.sleep(1)
                    is_disabled = await post_btn.get_attribute('aria-disabled')
                    is_btn_enabled = await post_btn.is_enabled()
                    has_video = await dialog.locator('video, [data-testid="attachments"] video').count()

                    # Twitter strictly enables the button (aria-disabled removed and element enabled) once video is ready
                    if has_video > 0 and (is_disabled is None or is_disabled == 'false') and is_btn_enabled:
                        video_ready = True
                        log.info('[twitter] Video upload complete! Post button is now active (enabled) after %ds', sec + 1)
                        break

                    if (sec + 1) % 5 == 0:
                        log.info('[twitter] Still processing video... (%ds elapsed, Post button is disabled)', sec + 1)

                if not video_ready:
                    log.error('[twitter] Video processing timed out after %ds or video failed to attach', max_wait_sec)
                    return False

                # ── Step 6: Mark as sensitive (NSFW) if needed ─────────────────
                if self.NSFW:
                    await self._mark_sensitive(page, dialog)

                # ── Step 7: Submit the tweet inside dialog ────────────────────
                log.info('[twitter] Submitting tweet with video...')
                post_btn = dialog.locator('[data-testid="tweetButton"]').first
                try:
                    await post_btn.scroll_into_view_if_needed()
                except Exception:
                    pass
                await self._jitter(300, 600)

                # Focus the tweet textarea and use Twitter's native submission shortcut
                tweet_box = dialog.locator('[data-testid="tweetTextarea_0"], [role="textbox"]').first
                try:
                    await tweet_box.focus()
                except Exception:
                    pass
                await self._jitter(200, 400)
                log.info('[twitter] Triggering post submission via Control+Enter shortcut')
                await page.keyboard.press('Control+Enter')

                # Secondary trigger: click the post button
                try:
                    await post_btn.click(force=True, timeout=5_000)
                except Exception:
                    try:
                        await post_btn.evaluate('b => b.click()')
                    except Exception:
                        pass

                # ── Step 8: Wait for success confirmation ──────────────────────
                log.info('[twitter] Waiting for tweet dialog to close...')
                dialog_closed = False
                try:
                    await dialog.wait_for(state='hidden', timeout=30_000)
                    dialog_closed = True
                    log.info('[twitter] Compose dialog closed — video tweet posted successfully!')
                except Exception:
                    log.debug('[twitter] Dialog not closed after 30s, attempting retry submit...')
                    try:
                        await tweet_box.focus()
                        await page.keyboard.press('Control+Enter')
                        await post_btn.click(force=True, timeout=5_000)
                    except Exception:
                        pass
                    try:
                        await dialog.wait_for(state='hidden', timeout=15_000)
                        dialog_closed = True
                        log.info('[twitter] Compose dialog closed on retry')
                    except Exception:
                        # Check toast notification
                        toast_sel = (
                            ':text("Your post was sent"), '
                            ':text("Tweet sent"), '
                            ':text("Postingan Anda telah dikirim"), '
                            '[data-testid="toast"]'
                        )
                        try:
                            await page.wait_for_selector(toast_sel, timeout=10_000)
                            dialog_closed = True
                            log.info('[twitter] Success toast notification detected')
                        except Exception:
                            pass

                if not dialog_closed:
                    log.error('[twitter] Tweet submission failed: compose dialog remained open')
                    return False

                # Cooldown to ensure network upload finalized before closing context
                log.info('[twitter] Tweet successfully published! Cooldown before closing...')
                await self._jitter(4000, 6000)
                return True

            except Exception as exc:
                log.exception('[twitter] Upload failed: %s', exc)
                return False
            finally:
                await context.close()

    async def _mark_sensitive(self, page: Page, dialog=None) -> None:
        """Enable the 'Content warning / sensitive' flag via Twitter's Edit media modal.

        Args:
            page: The active Playwright compose page.
            dialog: Optional reference to the active compose dialog locator.
        """
        log = self._log
        log.info('[twitter] Marking content as sensitive (NSFW)...')
        try:
            target_dialog = dialog if dialog is not None else page.locator('div[role="dialog"]:visible').first

            # 1. Click "Edit media" on the attached video
            edit_btn = target_dialog.locator(
                'button[aria-label*="Edit" i], button[aria-label*="Sunting" i], '
                'button:has-text("Edit"), button:has-text("Sunting")'
            ).first
            await edit_btn.wait_for(state='visible', timeout=10_000)
            await edit_btn.click()
            await self._jitter(1000, 2000)

            # 2. Click "Content warning" tab (flag icon tab)
            cw_tab = page.locator(
                '[role="tab"]:has-text("Content warning"), '
                '[role="tab"]:has-text("Peringatan konten"), '
                '[role="tab"][aria-label*="warning" i], '
                '[role="tab"]:has([data-testid="icon"])'
            ).last
            await cw_tab.wait_for(state='visible', timeout=10_000)
            await cw_tab.click()
            await self._jitter(800, 1500)

            # 3. Check Sensitive / Nudity option
            opt = page.locator(
                'label:has-text("Sensitive"), label:has-text("Sensitif"), '
                'label:has-text("Nudity"), label:has-text("Ketelanjangan")'
            ).first
            await opt.wait_for(state='visible', timeout=8_000)
            await opt.click()
            await self._jitter(600, 1200)

            # 4. Click Done on the Edit sub-modal
            done_btn = page.locator(
                'div[role="dialog"]:visible button:has-text("Done"), '
                'div[role="dialog"]:visible button:has-text("Save"), '
                'div[role="dialog"]:visible button:has-text("Selesai"), '
                'div[role="dialog"]:visible button:has-text("Simpan")'
            ).last
            await done_btn.click()
            await self._jitter(600, 1200)

            # 5. If Back arrow is visible in the edit modal header, click it to return to compose modal
            back_btn = page.locator('div[role="dialog"]:visible [data-testid="app-bar-back"]').first
            if await back_btn.count() > 0 and await back_btn.is_visible():
                await back_btn.click()
                await self._jitter(600, 1200)

            log.info('[twitter] ✓ Sensitive content flag (NSFW) successfully enabled')

        except Exception as exc:
            log.warning('[twitter] Could not mark as sensitive: %s', exc)

