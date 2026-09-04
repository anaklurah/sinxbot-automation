"""
Playwright stealth utilities — applies anti-detection patches to browser contexts.
"""
from playwright.async_api import BrowserContext
from playwright_stealth import Stealth
import platform as _platform

STEALTH_ARGS = [
    '--disable-blink-features=AutomationControlled',
    '--disable-dev-shm-usage',
    '--no-sandbox',
    '--disable-setuid-sandbox',
    '--disable-gpu-sandbox',
]

DEFAULT_VIEWPORT = {'width': 1280, 'height': 720}
DEFAULT_USER_AGENT = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
    'AppleWebKit/537.36 (KHTML, like Gecko) '
    'Chrome/125.0.0.0 Safari/537.36'
)


async def apply_stealth(context: BrowserContext) -> None:
    """Apply stealth patches to a browser context.

    Runs playwright-stealth's async helper and overlays additional
    navigator property overrides so automation signals are hidden from
    JavaScript fingerprinting scripts.
    """
    stealth = Stealth()
    await stealth.apply_stealth_async(context)

    # Additional navigator.webdriver override — belt-and-suspenders on top
    # of playwright-stealth in case a platform checks multiple signals.
    await context.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
        Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
        Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
        // Mask chrome.runtime absence
        if (!window.chrome) {
            window.chrome = {runtime: {}};
        }
        // Override permissions API to avoid headless detection
        const originalQuery = window.navigator.permissions.query;
        window.navigator.permissions.query = (parameters) => (
            parameters.name === 'notifications'
                ? Promise.resolve({state: Notification.permission})
                : originalQuery(parameters)
        );
    """)


def get_launch_options(headless: bool = False) -> dict:
    """Return browser launch keyword arguments suitable for Playwright.

    Args:
        headless: Whether to launch the browser in headless mode.
                  Defaults to False — many platforms detect headless mode.

    Returns:
        A dict suitable for unpacking into ``playwright.chromium.launch(**opts)``
        or ``playwright.chromium.launch_persistent_context(..., **opts)``.
    """
    return {
        'headless': headless,
        'args': STEALTH_ARGS,
        # Slow-motion makes human-like timing easier in some scenarios
        'slow_mo': 0,
        # Chrome channel matches the DEFAULT_USER_AGENT Chrome version
        'channel': 'chrome',
    }


def get_context_options(
    locale: str = 'en-US',
    timezone: str = 'America/New_York',
) -> dict:
    """Return browser-context keyword arguments.

    These options are passed to ``browser.new_context(**opts)`` or
    included in ``launch_persistent_context(..., **opts)``.

    Args:
        locale: Browser locale string, e.g. ``'en-US'``.
        timezone: IANA timezone identifier, e.g. ``'America/New_York'``.

    Returns:
        Dict of context options including user_agent, viewport, locale,
        timezone_id.
    """
    return {
        'user_agent': DEFAULT_USER_AGENT,
        'viewport': DEFAULT_VIEWPORT,
        'locale': locale,
        'timezone_id': timezone,
        'color_scheme': 'light',
        'device_scale_factor': 1,
        'is_mobile': False,
        'has_touch': False,
        'java_script_enabled': True,
        'bypass_csp': False,
    }
