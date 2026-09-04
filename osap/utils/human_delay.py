"""
Human-simulation delay and interaction utilities for Playwright.
================================================================
Provides async helpers that mimic organic human behaviour when controlling
a browser via Playwright.  Using these instead of instant ``click()`` /
``fill()`` calls makes automation harder to detect by bot-protection systems.

All functions are ``async`` and must be called from within an async context
(e.g. an ``asyncio`` event loop or an ``async def`` function).

Usage::

    from playwright.async_api import async_playwright
    from osap.utils.human_delay import human_type, human_click, random_scroll

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()
        await page.goto("https://example.com")

        await human_type(page, "#search", "hello world")
        await human_click(page, "button[type='submit']")
        await random_scroll(page)
"""
from __future__ import annotations

import asyncio
import random
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.async_api import Locator, Page


# ---------------------------------------------------------------------------
# Primitive delay helpers
# ---------------------------------------------------------------------------


async def jitter(min_ms: float = 100, max_ms: float = 500) -> None:
    """
    Sleep for a uniformly random duration between *min_ms* and *max_ms*
    milliseconds.

    Parameters
    ----------
    min_ms:
        Minimum sleep time in **milliseconds** (default ``100``).
    max_ms:
        Maximum sleep time in **milliseconds** (default ``500``).

    Example
    -------
    ::

        await jitter(200, 800)   # sleep between 0.2 s and 0.8 s
    """
    await asyncio.sleep(random.uniform(min_ms, max_ms) / 1000.0)


# ---------------------------------------------------------------------------
# Keyboard simulation
# ---------------------------------------------------------------------------


async def human_type(
    page: "Page",
    selector: str,
    text: str,
    char_delay_min: float = 50,
    char_delay_max: float = 200,
) -> None:
    """
    Type *text* into the element matched by *selector* character-by-character,
    with a random inter-keystroke delay to simulate natural typing speed.

    The element is clicked once (to focus it) before typing begins.

    Parameters
    ----------
    page:
        The Playwright :class:`~playwright.async_api.Page` instance.
    selector:
        CSS or XPath selector identifying the target input element.
    text:
        The full string to type.
    char_delay_min:
        Minimum delay between keystrokes in **milliseconds** (default ``50``).
    char_delay_max:
        Maximum delay between keystrokes in **milliseconds** (default ``200``).

    Notes
    -----
    * Uses :meth:`~playwright.async_api.Page.type` with ``delay`` set per
      character to avoid triggering rate-limit heuristics that flag uniformly
      fast typing.
    * For very long texts this will be noticeably slow — adjust the defaults
      or use ``page.fill()`` for non-sensitive fields where speed matters.
    """
    # Focus the element first
    await page.click(selector)
    await jitter(80, 200)

    for char in text:
        # Type one character at a time so we can vary the delay per keystroke
        delay_ms = random.uniform(char_delay_min, char_delay_max)
        await page.keyboard.type(char, delay=delay_ms)

        # Occasionally insert a longer "thinking" pause (≈ 5 % of keystrokes)
        if random.random() < 0.05:
            await jitter(300, 900)


# ---------------------------------------------------------------------------
# Mouse click simulation
# ---------------------------------------------------------------------------


async def human_click(
    page: "Page",
    selector: str,
    pre_delay_min: float = 200,
    pre_delay_max: float = 600,
) -> None:
    """
    Click the element identified by *selector* with realistic pre- and
    post-click delays.

    Parameters
    ----------
    page:
        The Playwright :class:`~playwright.async_api.Page` instance.
    selector:
        CSS or XPath selector of the element to click.
    pre_delay_min:
        Minimum time to wait **before** clicking, in milliseconds (default ``200``).
    pre_delay_max:
        Maximum time to wait **before** clicking, in milliseconds (default ``600``).

    Notes
    -----
    A short post-click jitter (50–200 ms) is also applied to simulate the
    reaction time after clicking before the next action begins.
    """
    # Pre-click hesitation
    await jitter(pre_delay_min, pre_delay_max)

    await page.click(selector)

    # Post-click micro-pause
    await jitter(50, 200)


# ---------------------------------------------------------------------------
# Mouse movement + click with waypoints
# ---------------------------------------------------------------------------


async def human_move_and_click(page: "Page", selector: str) -> None:
    """
    Move the mouse cursor from its current position to the target element
    via several intermediate waypoints, then click.

    This multi-step movement path is more realistic than teleporting the
    cursor directly onto the element, and helps defeat simple mouse-movement
    analysis performed by some bot-detection services.

    Algorithm
    ---------
    1. Retrieve the bounding box of the target element.
    2. Choose a target point near the centre of the element (with ±10 px
       random offset so clicks aren't perfectly centred every time).
    3. Generate 3–5 intermediate waypoints along a slightly curved path
       between the current cursor position and the target.
    4. Move through each waypoint with a random inter-step delay.
    5. Perform the final click.

    Parameters
    ----------
    page:
        The Playwright :class:`~playwright.async_api.Page` instance.
    selector:
        CSS or XPath selector of the element to click.

    Notes
    -----
    * The "current" mouse position is tracked internally by Playwright and
      starts at ``(0, 0)`` for a fresh page.  We read the viewport size and
      assume a reasonable starting area if no prior moves have been made.
    * If the element has no bounding box (e.g. it is ``display:none``),
      Playwright will raise an error before this function attempts to move.
    """
    locator = page.locator(selector).first
    await locator.wait_for(state="visible", timeout=10_000)

    bbox = await locator.bounding_box()
    if bbox is None:
        # Fall back to a plain click if we cannot determine the bounding box
        await page.click(selector)
        return

    # Target: centre of bounding box with slight random offset
    target_x = bbox["x"] + bbox["width"] / 2 + random.uniform(-10, 10)
    target_y = bbox["y"] + bbox["height"] / 2 + random.uniform(-10, 10)

    # Estimate current cursor position — use viewport centre as a safe default
    viewport = page.viewport_size or {"width": 1280, "height": 720}
    start_x: float = viewport["width"] / 2
    start_y: float = viewport["height"] / 2

    # Generate 3–5 intermediate waypoints
    num_waypoints = random.randint(3, 5)
    waypoints: list[tuple[float, float]] = []

    for i in range(1, num_waypoints + 1):
        # Linear interpolation with random perpendicular offset for curvature
        t = i / (num_waypoints + 1)
        interp_x = start_x + (target_x - start_x) * t
        interp_y = start_y + (target_y - start_y) * t

        # Add curvature: perpendicular offset decays toward the target
        curve_magnitude = random.uniform(-40, 40) * (1 - t)
        waypoints.append((
            interp_x + curve_magnitude,
            interp_y + curve_magnitude * 0.5,
        ))

    # Move through waypoints
    for wx, wy in waypoints:
        await page.mouse.move(wx, wy)
        await jitter(20, 80)

    # Final move onto the target
    await page.mouse.move(target_x, target_y)
    await jitter(50, 150)

    # Click
    await page.mouse.click(target_x, target_y)
    await jitter(80, 250)


# ---------------------------------------------------------------------------
# Scroll simulation
# ---------------------------------------------------------------------------


async def random_scroll(
    page: "Page",
    min_px: int = 100,
    max_px: int = 500,
) -> None:
    """
    Scroll the page by a random pixel amount to simulate organic reading behaviour.

    The scroll direction is **downward** (positive Y) by default.  The scroll
    is performed via ``window.scrollBy`` so it respects the page's current
    scroll position.

    Parameters
    ----------
    page:
        The Playwright :class:`~playwright.async_api.Page` instance.
    min_px:
        Minimum scroll distance in pixels (default ``100``).
    max_px:
        Maximum scroll distance in pixels (default ``500``).
    """
    scroll_amount = random.randint(min_px, max_px)
    await page.evaluate(f"window.scrollBy(0, {scroll_amount})")
    # Brief pause after scrolling — simulates reading time
    await jitter(400, 1200)


# ---------------------------------------------------------------------------
# Post-navigation delay
# ---------------------------------------------------------------------------


async def wait_for_navigation_jitter(
    page: "Page",
    min_ms: int = 1000,
    max_ms: int = 3000,
) -> None:
    """
    Wait for a random duration after a page navigation to simulate the time
    a human takes to visually process the new page before interacting.

    This should be called after ``page.goto()``, form submissions, or any
    other action that triggers a full-page navigation.

    Parameters
    ----------
    page:
        The Playwright :class:`~playwright.async_api.Page` instance.
        The page is expected to have already settled into its ``load`` state.
    min_ms:
        Minimum wait time in **milliseconds** (default ``1000``).
    max_ms:
        Maximum wait time in **milliseconds** (default ``3000``).

    Notes
    -----
    This function does **not** call ``page.wait_for_load_state()`` — the
    caller is responsible for ensuring the page has finished loading before
    invoking this helper.  The sleep here is purely an additional human-
    simulation delay on top of any structural waits.
    """
    await jitter(float(min_ms), float(max_ms))
