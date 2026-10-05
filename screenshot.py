#!/usr/bin/env python3
"""
Hourly website screenshots (Playwright + headless Chromium).

Every run saves one full-page screenshot per page listed in SITES to:

    screenshots/YYYY-MM-DD/HHMM_<name>.jpg

The date/time in the names is the machine's local time (on GitHub, the
workflow sets TZ so it is Eastern time). HHMM is when the run started.

One-time setup on your own computer:
    pip install playwright
    playwright install chromium

Usage:
    python screenshot.py          # take one round of screenshots right now
    python screenshot.py --loop   # keep running; capture at the top of every hour
"""
import os
import sys
import time
from datetime import datetime
from pathlib import Path

from playwright.sync_api import TimeoutError as PlaywrightTimeout
from playwright.sync_api import sync_playwright

# ----------------------------------------------------------------------------
# Settings
# ----------------------------------------------------------------------------
SITES = {
    # name used in the file name : page to capture
    "the-numbers_2026-09-25": "https://www.the-numbers.com/box-office-chart/daily/2026/09/25",
    "the-numbers_2026-09-26": "https://www.the-numbers.com/box-office-chart/daily/2026/09/26",
    "the-numbers_2026-09-27": "https://www.the-numbers.com/box-office-chart/daily/2026/09/27",
    "the-numbers_2026-10-02": "https://www.the-numbers.com/box-office-chart/daily/2026/10/02",
    "the-numbers_2026-10-03": "https://www.the-numbers.com/box-office-chart/daily/2026/10/03",
    "the-numbers_2026-10-04": "https://www.the-numbers.com/box-office-chart/daily/2026/10/04",
    "boxofficemojo_home": "https://www.boxofficemojo.com/",
}

OUT_DIR = Path("screenshots")
VIEWPORT = {"width": 1440, "height": 900}
FULL_PAGE = True        # False = only the first screen
IMAGE_FORMAT = "jpeg"   # "jpeg" = small files, "png" = lossless but much bigger
JPEG_QUALITY = 80
ATTEMPTS = 2            # tries per page before giving up on it
NAV_TIMEOUT_MS = 30_000

EXT = "jpg" if IMAGE_FORMAT == "jpeg" else "png"
IMAGE_OPTS = (
    {"type": "jpeg", "quality": JPEG_QUALITY} if IMAGE_FORMAT == "jpeg" else {"type": "png"}
)


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------
def log(msg):
    print(msg, flush=True)


def warn(msg):
    # On GitHub Actions, "::warning::" becomes a yellow note on the run page.
    prefix = "::warning::" if os.getenv("GITHUB_ACTIONS") else "WARNING: "
    print(f"{prefix}{msg}", flush=True)


def first_line(exc):
    lines = str(exc).strip().splitlines()
    return lines[0] if lines else exc.__class__.__name__


def scroll_through(page):
    """Scroll down and back up so lazy-loaded images/rows get a chance to render."""
    page.evaluate(
        """async () => {
            const maxY = Math.min(document.documentElement.scrollHeight, 30000);
            for (let y = 0; y < maxY; y += 700) {
                window.scrollTo(0, y);
                await new Promise(r => setTimeout(r, 120));
            }
            window.scrollTo(0, 0);
        }"""
    )
    page.wait_for_timeout(1000)


def capture(context, url, path):
    """Load one page and save a screenshot. Returns the HTTP status (or None)."""
    page = context.new_page()
    try:
        response = page.goto(url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
        try:
            # Ads/trackers can keep the network busy forever, so only wait a bit.
            page.wait_for_load_state("networkidle", timeout=10_000)
        except PlaywrightTimeout:
            pass
        scroll_through(page)
        page.screenshot(path=str(path), full_page=FULL_PAGE, **IMAGE_OPTS)
        return response.status if response else None
    finally:
        page.close()


def run_once():
    """Capture every page in SITES once. Returns how many screenshots were saved."""
    now = datetime.now()
    day_dir = OUT_DIR / now.strftime("%Y-%m-%d")
    day_dir.mkdir(parents=True, exist_ok=True)
    stamp = now.strftime("%H%M")
    saved = 0

    with sync_playwright() as p:
        browser = p.chromium.launch()

        # Headless Chromium calls itself "HeadlessChrome", which some sites block.
        # Keep the real version number but drop the "Headless" label.
        probe = browser.new_page()
        user_agent = probe.evaluate("navigator.userAgent").replace("HeadlessChrome", "Chrome")
        probe.close()
        context = browser.new_context(viewport=VIEWPORT, user_agent=user_agent, locale="en-US")

        for name, url in SITES.items():
            path = day_dir / f"{stamp}_{name}.{EXT}"
            for attempt in range(1, ATTEMPTS + 1):
                try:
                    status = capture(context, url, path)
                except Exception as exc:  # timeout, DNS error, etc.
                    warn(f"{name}: attempt {attempt}/{ATTEMPTS} failed: {first_line(exc)}")
                    time.sleep(3)
                    continue
                saved += 1
                log(f"saved {path} (HTTP {status})")
                if status and status >= 400:
                    warn(
                        f"{name}: the site answered HTTP {status}; the screenshot may "
                        "show an error or bot-check page instead of the real page"
                    )
                break
            else:
                warn(f"{name}: no screenshot saved after {ATTEMPTS} attempts")

        context.close()
        browser.close()

    log(f"Done: {saved}/{len(SITES)} screenshots saved at {now:%Y-%m-%d %H:%M}.")
    return saved


def seconds_until_next_hour():
    # Works with any UTC offset and is unaffected by daylight-saving changes.
    offset = datetime.now().astimezone().utcoffset().total_seconds()
    return 3600 - (time.time() + offset) % 3600


def main():
    if "--loop" not in sys.argv:
        # One-shot mode (what GitHub Actions uses). Fail only if nothing was saved.
        sys.exit(0 if run_once() else 1)

    while True:
        wait = seconds_until_next_hour()
        log(f"Next capture at the top of the hour, in {wait / 60:.1f} min. Ctrl+C to stop.")
        time.sleep(wait + 1)  # +1s so the HHMM label is never the previous hour
        try:
            run_once()
        except Exception as exc:
            warn(f"capture round failed: {first_line(exc)}")


if __name__ == "__main__":
    main()
