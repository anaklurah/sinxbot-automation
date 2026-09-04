"""
Abstract base class for all platform publishers.

Every platform-specific publisher (YouTube, TikTok, Instagram, etc.) inherits
from BasePublisher and implements the ``upload()`` coroutine.  The base class
handles:
- Browser / context lifecycle (persistent profile or storage-state)
- Stealth patches
- Cookie / storage-state injection
- Timeout wrapping & exception handling
- Delegation to osap.utils.human_delay helpers
"""
import asyncio
from abc import ABC, abstractmethod
from pathlib import Path

from playwright.async_api import (
    async_playwright,
    Browser,
    BrowserContext,
    Page,
    Playwright,
)

from osap.modules.publisher.stealth import (
    apply_stealth,
    get_launch_options,
    get_context_options,
)
from osap.modules.publisher.cookie_loader import (
    load_cookies,
    load_storage_state,
)
from osap.config import get_config
from osap.utils.human_delay import jitter, human_type, human_click, human_move_and_click
from osap.utils.logger import get_logger

# Default upload timeout: 10 minutes
_UPLOAD_TIMEOUT_S = 600


class BasePublisher(ABC):
    """Abstract base for all OSAP platform publishers.

    Subclasses MUST override:
    - ``PLATFORM_NAME`` — unique slug used for profile/cookie path resolution
    - ``upload()`` — the actual UI automation logic

    Subclasses MAY override:
    - ``AUTH_METHOD`` — ``'persistent'`` or ``'storage_state'``
    """

    PLATFORM_NAME: str = ''
    AUTH_METHOD: str = 'storage_state'  # 'persistent' | 'storage_state'

    def __init__(self) -> None:
        if not self.PLATFORM_NAME:
            raise ValueError(
                f'{self.__class__.__name__} must define a non-empty PLATFORM_NAME'
            )
        self._cfg = get_config()
        self._log = get_logger(f'osap.publisher.{self.PLATFORM_NAME}')

    # ------------------------------------------------------------------ #
    # Abstract interface
    # ------------------------------------------------------------------ #

    @abstractmethod
    async def upload(
        self,
        video_path: str,
        title: str,
        description: str,
        tags: list[str],
    ) -> bool:
        """Perform the platform-specific upload flow.

        Args:
            video_path: Absolute path to the video file to upload.
            title: Video title / headline.
            description: Longer body text / caption.
            tags: List of hashtag strings (without ``#`` prefix).

        Returns:
            ``True`` on success, ``False`` on failure.
        """

    # ------------------------------------------------------------------ #
    # Public entry-point
    # ------------------------------------------------------------------ #

    async def run_upload(
        self,
        video_path: str,
        title: str,
        description: str,
        tags: list[str],
    ) -> bool:
        """Wrap ``upload()`` with a timeout and top-level error handling.

        Args:
            video_path: Absolute path to the video file.
            title: Video title.
            description: Video description / caption.
            tags: List of hashtag strings.

        Returns:
            ``True`` on success, ``False`` if the upload timed out or raised.
        """
        self._log.info(
            '[%s] Starting upload: %r (title=%r)', self.PLATFORM_NAME, video_path, title
        )
        try:
            result = await asyncio.wait_for(
                self.upload(video_path, title, description, tags),
                timeout=_UPLOAD_TIMEOUT_S,
            )
            if result:
                self._log.info('[%s] Upload completed successfully.', self.PLATFORM_NAME)
            else:
                self._log.warning('[%s] Upload returned False.', self.PLATFORM_NAME)
            return bool(result)
        except asyncio.TimeoutError:
            self._log.error(
                '[%s] Upload timed out after %ds.', self.PLATFORM_NAME, _UPLOAD_TIMEOUT_S
            )
            return False
        except Exception as exc:  # noqa: BLE001
            self._log.exception('[%s] Upload raised an unexpected error: %s', self.PLATFORM_NAME, exc)
            return False

    # ------------------------------------------------------------------ #
    # Browser / context factory
    # ------------------------------------------------------------------ #

    async def _get_context(self, playwright: Playwright) -> BrowserContext:
        """Create and return a configured ``BrowserContext``.

        Handles both authentication strategies transparently:
        - ``'persistent'``: Launches a persistent-profile Chromium context
          (user_data_dir = cfg.PROFILES_DIR / PLATFORM_NAME).
        - ``'storage_state'``: Launches an ephemeral context and injects
          auth data from whichever of the following files exist
          (priority: storage_state > JSON cookies > Netscape cookies).

        Stealth patches are applied to every context regardless of method.

        Returns:
            A live, stealth-patched ``BrowserContext``.
        """
        cfg = self._cfg
        launch_opts = get_launch_options(headless=getattr(cfg, 'HEADLESS', False))
        ctx_opts = get_context_options(
            locale=getattr(cfg, 'BROWSER_LOCALE', 'en-US'),
            timezone=getattr(cfg, 'BROWSER_TIMEZONE', 'America/New_York'),
        )

        if self.AUTH_METHOD == 'persistent':
            profile_dir = Path(cfg.PROFILES_DIR) / self.PLATFORM_NAME
            profile_dir.mkdir(parents=True, exist_ok=True)
            self._log.debug(
                '[%s] Launching persistent context from %s', self.PLATFORM_NAME, profile_dir
            )
            context: BrowserContext = await playwright.chromium.launch_persistent_context(
                user_data_dir=str(profile_dir),
                **{**launch_opts, **ctx_opts},
            )
            await apply_stealth(context)
            return context

        # --- storage_state path ---
        browser: Browser = await playwright.chromium.launch(**launch_opts)

        profiles_dir = Path(cfg.PROFILES_DIR)
        storage_state_path = profiles_dir / f'{self.PLATFORM_NAME}_storage.json'
        json_cookies_path = profiles_dir / f'{self.PLATFORM_NAME}_cookies.json'
        netscape_cookies_path = profiles_dir / f'{self.PLATFORM_NAME}_cookies.txt'

        context_kwargs = dict(ctx_opts)

        if storage_state_path.exists():
            self._log.debug(
                '[%s] Loading storage state from %s', self.PLATFORM_NAME, storage_state_path
            )
            context_kwargs['storage_state'] = str(storage_state_path)
            context = await browser.new_context(**context_kwargs)

        elif json_cookies_path.exists():
            self._log.debug(
                '[%s] Loading JSON cookies from %s', self.PLATFORM_NAME, json_cookies_path
            )
            context = await browser.new_context(**context_kwargs)
            cookies = load_cookies(json_cookies_path)
            if cookies:
                await context.add_cookies(cookies)

        elif netscape_cookies_path.exists():
            self._log.debug(
                '[%s] Loading Netscape cookies from %s',
                self.PLATFORM_NAME, netscape_cookies_path,
            )
            context = await browser.new_context(**context_kwargs)
            cookies = load_cookies(netscape_cookies_path)
            if cookies:
                await context.add_cookies(cookies)

        else:
            self._log.warning(
                '[%s] No auth file found in %s — launching unauthenticated context.',
                self.PLATFORM_NAME, profiles_dir,
            )
            context = await browser.new_context(**context_kwargs)

        await apply_stealth(context)
        return context

    # ------------------------------------------------------------------ #
    # Generic upload-progress waiter
    # ------------------------------------------------------------------ #

    async def _wait_for_upload_complete(
        self,
        page: Page,
        timeout_ms: int = 600_000,
    ) -> None:
        """Wait until an upload progress indicator disappears or a success
        message appears.

        This is a best-effort generic implementation.  Platform subclasses
        should override or supplement this with platform-specific selectors.

        Strategy:
        1. Wait up to ``timeout_ms`` for a ``[role="progressbar"]`` to appear
           (it might not — that is fine).
        2. Then wait for that progress bar to disappear, OR for a known
           success/done text pattern to appear.

        Args:
            page: The active Playwright page.
            timeout_ms: Maximum wait time in milliseconds (default 10 min).
        """
        progress_bar_selector = '[role="progressbar"], .progress-bar, [data-progress]'
        success_patterns = [
            'text=Upload complete',
            'text=Published',
            'text=Your video is now live',
            'text=Posted',
            'text=Done',
            'text=Success',
        ]

        try:
            # Phase 1: wait for a progress bar to appear (short timeout — may not exist)
            await page.wait_for_selector(progress_bar_selector, timeout=5_000)
            self._log.debug('[%s] Progress bar appeared, waiting for completion…', self.PLATFORM_NAME)

            # Phase 2: wait for it to disappear
            await page.wait_for_selector(
                progress_bar_selector,
                state='hidden',
                timeout=timeout_ms,
            )
            self._log.debug('[%s] Progress bar gone — upload likely complete.', self.PLATFORM_NAME)

        except Exception:  # noqa: BLE001
            # No progress bar found — try success text patterns instead
            self._log.debug(
                '[%s] No progress bar detected; waiting for success indicator.',
                self.PLATFORM_NAME,
            )
            for pattern in success_patterns:
                try:
                    await page.wait_for_selector(pattern, timeout=timeout_ms)
                    self._log.debug(
                        '[%s] Success indicator found: %r', self.PLATFORM_NAME, pattern
                    )
                    return
                except Exception:  # noqa: BLE001
                    continue

            self._log.warning(
                '[%s] Could not confirm upload completion via generic selectors.',
                self.PLATFORM_NAME,
            )

    # ------------------------------------------------------------------ #
    # Protected human_delay delegates
    # ------------------------------------------------------------------ #

    async def _jitter(
        self,
        min_ms: float = 300,
        max_ms: float = 1200,
    ) -> None:
        """Introduce a random human-like delay.

        Args:
            min_ms: Minimum delay in milliseconds.
            max_ms: Maximum delay in milliseconds.
        """
        await jitter(min_ms, max_ms)

    async def _type(self, page: Page, selector: str, text: str) -> None:
        """Type *text* into element matched by *selector* with human-like cadence.

        Args:
            page: Active Playwright page.
            selector: CSS/text selector for the target input.
            text: The string to type.
        """
        await human_type(page, selector, text)

    async def _click(self, page: Page, selector: str) -> None:
        """Click the element matched by *selector* with a human-like pause.

        Args:
            page: Active Playwright page.
            selector: CSS/text selector for the target element.
        """
        await human_click(page, selector)

    async def _move_click(self, page: Page, selector: str) -> None:
        """Move to and click the element matched by *selector*.

        Args:
            page: Active Playwright page.
            selector: CSS/text selector for the target element.
        """
        await human_move_and_click(page, selector)
