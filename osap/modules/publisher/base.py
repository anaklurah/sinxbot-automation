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

    def __init__(self, account_id: int = 1, target_key: str | None = None) -> None:
        if not self.PLATFORM_NAME:
            raise ValueError(
                f'{self.__class__.__name__} must define a non-empty PLATFORM_NAME'
            )
        self._cfg = get_config()
        self.target_key = target_key or self.PLATFORM_NAME
        self._log = get_logger(f'osap.publisher.{self.target_key}')
        self.account_id = account_id

    def _get_profiles_dir(self) -> Path:
        base_dir = Path(self._cfg.PROFILES_DIR)
        if self.account_id and self.account_id > 1:
            p_dir = base_dir / f"account_{self.account_id}"
            p_dir.mkdir(parents=True, exist_ok=True)
            return p_dir
        return base_dir


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
        t_name = getattr(self, "target_key", None) or self.PLATFORM_NAME
        self._log.info(
            '[%s] Starting upload: %r (title=%r)', t_name, video_path, title
        )
        try:
            result = await asyncio.wait_for(
                self.upload(video_path, title, description, tags),
                timeout=_UPLOAD_TIMEOUT_S,
            )
            if result:
                self._log.info('[%s] Upload completed successfully.', t_name)
            else:
                self._log.warning('[%s] Upload returned False.', t_name)
            return bool(result)
        except asyncio.TimeoutError:
            self._log.error(
                '[%s] Upload timed out after %ds.', t_name, _UPLOAD_TIMEOUT_S
            )
            return False
        except Exception as exc:  # noqa: BLE001
            self._log.exception('[%s] Upload raised an unexpected error: %s', t_name, exc)

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
        
        # Inject proxy if configured
        proxy_url = getattr(cfg, 'PROXY_URL', None) or os.environ.get('PROXY_URL')
        if proxy_url:
            self._log.info('[%s] Routing browser traffic through proxy: %s', self.PLATFORM_NAME, proxy_url)
            launch_opts['proxy'] = {'server': proxy_url}

        ctx_opts = get_context_options(
            locale=getattr(cfg, 'BROWSER_LOCALE', 'en-US'),
            timezone=getattr(cfg, 'BROWSER_TIMEZONE', 'America/New_York'),
        )

        profiles_dir = self._get_profiles_dir()
        profile_key = getattr(self, "target_key", None) or self.PLATFORM_NAME
        use_camoufox = getattr(cfg, 'BROWSER_ENGINE', 'camoufox') == 'camoufox'

        if self.AUTH_METHOD == 'persistent':
            profile_dir = profiles_dir / profile_key
            profile_dir.mkdir(parents=True, exist_ok=True)
            context: BrowserContext | None = None

            if use_camoufox:
                try:
                    from camoufox.async_api import AsyncCamoufox
                    cf_kwargs: dict[str, Any] = {
                        'headless': getattr(cfg, 'HEADLESS', False),
                        'humanize': True,
                    }
                    if proxy_url:
                        cf_kwargs['proxy'] = {'server': proxy_url}
                    self._log.info('[%s] Launching anti-detect Camoufox persistent context: %s', profile_key, profile_dir)
                    cf = AsyncCamoufox(
                        persistent_context=True,
                        user_data_dir=str(profile_dir),
                        **cf_kwargs,
                    )
                    context = await cf.start()
                except Exception as cf_err:
                    self._log.warning('[%s] Camoufox persistent context failed (%s), falling back to Chromium', profile_key, cf_err)
                    context = None

            if context is None:
                self._log.debug(
                    '[%s] Launching persistent Chromium context from %s', profile_key, profile_dir
                )
                context = await playwright.chromium.launch_persistent_context(
                    user_data_dir=str(profile_dir),
                    **{**launch_opts, **ctx_opts},
                )
            await apply_stealth(context)

            # Inject uploaded cookies if available so persistent profile is authenticated
            candidate_files = [
                profiles_dir / f'{profile_key}_storage.json',
                profiles_dir / f'{profile_key}_cookies.json',
                profiles_dir / f'{profile_key}_cookies.txt',
                profiles_dir / f'{self.PLATFORM_NAME}_storage.json',
                profiles_dir / f'{self.PLATFORM_NAME}_cookies.txt',
            ]
            for cf in candidate_files:
                if cf.exists() and cf.stat().st_size > 0:
                    try:
                        cookies = load_cookies(cf)
                        if cookies:
                            self._log.info('[%s] Injected %d uploaded cookies into persistent context from %s', profile_key, len(cookies), cf.name)
                            await context.add_cookies(cookies)
                            break
                    except Exception as e:
                        self._log.warning('[%s] Failed injecting cookies into persistent context: %s', profile_key, e)

            return context

        # --- storage_state path ---
        browser: Browser | None = None
        if use_camoufox:
            try:
                from camoufox.async_api import AsyncCamoufox
                cf_kwargs = {
                    'headless': getattr(cfg, 'HEADLESS', False),
                    'humanize': True,
                }
                if proxy_url:
                    cf_kwargs['proxy'] = {'server': proxy_url}
                self._log.info('[%s] Launching anti-detect Camoufox browser...', profile_key)
                cf = AsyncCamoufox(**cf_kwargs)
                browser = await cf.start()
            except Exception as cf_err:
                self._log.warning('[%s] Camoufox launch failed (%s), falling back to Chromium', profile_key, cf_err)
                browser = None

        if browser is None:
            browser = await playwright.chromium.launch(**launch_opts)

        storage_state_path = profiles_dir / f'{profile_key}_storage.json'
        json_cookies_path = profiles_dir / f'{profile_key}_cookies.json'
        netscape_cookies_path = profiles_dir / f'{profile_key}_cookies.txt'

        # Fallback to base platform auth file if target-specific file not yet created
        if not (storage_state_path.exists() or json_cookies_path.exists() or netscape_cookies_path.exists()):
            base_storage = profiles_dir / f'{self.PLATFORM_NAME}_storage.json'
            base_json = profiles_dir / f'{self.PLATFORM_NAME}_cookies.json'
            base_txt = profiles_dir / f'{self.PLATFORM_NAME}_cookies.txt'
            if base_storage.exists():
                storage_state_path = base_storage
            elif base_json.exists():
                json_cookies_path = base_json
            elif base_txt.exists():
                netscape_cookies_path = base_txt

        context_kwargs = dict(ctx_opts)

        context = None
        # Priority 1: Try Playwright native storage_state
        if storage_state_path.exists():
            try:
                self._log.debug(
                    '[%s] Attempting to load native storage state from %s', profile_key, storage_state_path
                )
                context_kwargs['storage_state'] = str(storage_state_path)
                context = await browser.new_context(**context_kwargs)
            except Exception as err:
                self._log.warning('[%s] Native storage_state failed (%s), falling back to cookie_loader', profile_key, err)
                context = None
                context_kwargs.pop('storage_state', None)

        if context is None:
            context = await browser.new_context(**context_kwargs)
            # Find candidate cookie file
            target_cookie_file = None
            if storage_state_path.exists():
                target_cookie_file = storage_state_path
            elif json_cookies_path.exists():
                target_cookie_file = json_cookies_path
            elif netscape_cookies_path.exists():
                target_cookie_file = netscape_cookies_path

            if target_cookie_file:
                cookies = load_cookies(target_cookie_file)
                if cookies:
                    await context.add_cookies(cookies)
                    self._log.info('[%s] Injected %d normalized cookies from %s', profile_key, len(cookies), target_cookie_file.name)
                else:
                    self._log.warning('[%s] No valid cookies parsed from %s', profile_key, target_cookie_file)
            else:
                self._log.warning(
                    '[%s] No auth file found in %s — launching unauthenticated context.',
                    profile_key, profiles_dir,
                )


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
