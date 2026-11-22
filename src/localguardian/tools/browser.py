"""Browser automation with Google Chrome as Priority #1.

Uses Playwright with `channel="chrome"` first so commands like
"go to Chrome and type Elon Musk" control real installed Google Chrome
via semantic DOM locators (falling back to Edge/Chromium only if Chrome
is not installed).
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import quote_plus

from localguardian.config import LocalGuardianConfig


def find_chrome_executable(config: Optional[LocalGuardianConfig] = None) -> Optional[str]:
    """Locate installed Google Chrome binary on Windows."""
    candidates = [
        r"%ProgramFiles%\Google\Chrome\Application\chrome.exe",
        r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe",
        r"%LocalAppData%\Google\Chrome\Application\chrome.exe",
    ]
    if config and "chrome" in config.safety.allowed_apps:
        candidates = list(config.safety.allowed_apps["chrome"].candidates) + candidates

    for raw in candidates:
        p = Path(os.path.expandvars(os.path.expanduser(raw)))
        if p.is_file():
            return str(p)
    return None


class ChromeController:
    """Persistent Google Chrome session controller (Priority #1 browser)."""

    def __init__(self, config: LocalGuardianConfig) -> None:
        self.config = config
        self._pw = None
        self._browser = None
        self._context = None
        self._page = None
        self._active_channel: Optional[str] = None

    def _ensure_page(self):
        """Launch or reuse a visible Google Chrome window via Playwright."""
        if self._page is not None:
            try:
                if not self._page.is_closed():
                    return self._page
            except Exception:
                self._page = None

        from playwright.sync_api import sync_playwright  # type: ignore

        if self._pw is None:
            self._pw = sync_playwright().start()

        # Priority order: Google Chrome (#1), then configured fallback (msedge), then bundled chromium
        channels = []
        if self.config.browser.priority:
            channels.append(self.config.browser.priority)
        if self.config.browser.fallback and self.config.browser.fallback not in channels:
            channels.append(self.config.browser.fallback)
        channels.append(None)  # bundled Playwright chromium as last resort

        last_err: Optional[Exception] = None
        if self._browser is None or not self._browser.is_connected():
            for ch in channels:
                try:
                    launch_kwargs: Dict[str, Any] = {
                        "headless": False,
                        "args": ["--start-maximized"],
                    }
                    if ch:
                        launch_kwargs["channel"] = ch
                    self._browser = self._pw.chromium.launch(**launch_kwargs)
                    self._active_channel = ch or "chromium"
                    break
                except Exception as exc:
                    last_err = exc
                    continue

        if self._browser is None:
            raise RuntimeError(f"Could not launch Chrome/Playwright browser: {last_err}")

        if self._context is None:
            self._context = self._browser.new_context(no_viewport=True)

        self._page = self._context.new_page()
        return self._page

    def _launch_native_chrome_url(self, url: str) -> Dict[str, Any]:
        """Fallback launcher if Playwright is unavailable: opens real Chrome directly."""
        chrome_exe = find_chrome_executable(self.config)
        if not chrome_exe:
            raise FileNotFoundError(
                "Google Chrome not found and Playwright browser backend is unavailable."
            )
        proc = subprocess.Popen(
            [chrome_exe, url],
            shell=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return {
            "browser": "chrome-native",
            "url": url,
            "pid": proc.pid,
            "message": f"Opened Google Chrome to {url}.",
        }

    def open_url(self, url: str, *, keep_open_after_exit: bool = False) -> Dict[str, Any]:
        """Open a validated http(s) URL in Google Chrome."""
        if keep_open_after_exit:
            return self._launch_native_chrome_url(url)
        try:
            page = self._ensure_page()
            page.goto(url, wait_until="domcontentloaded", timeout=20000)
            try:
                page.bring_to_front()
            except Exception:
                pass
            title = page.title()
            return {
                "browser": self._active_channel or "chrome",
                "url": page.url,
                "title": title,
                "message": f"Opened {page.url} in {self._active_channel or 'chrome'} ({title}).",
            }
        except ImportError:
            return self._launch_native_chrome_url(url)

    def search(self, query: str, *, keep_open_after_exit: bool = False) -> Dict[str, Any]:
        """Open Google Chrome (#1 priority) and search for `query`."""
        search_url = self.config.browser.default_search_engine.format(query=quote_plus(query))
        if keep_open_after_exit:
            res = self._launch_native_chrome_url(search_url)
            res["query"] = query
            res["message"] = f"Opened Google Chrome and searched for '{query}'."
            return res

        try:
            page = self._ensure_page()
            # Navigate directly to Google homepage & type into search box cleanly;
            # fall back to direct search URL if Google consent/selector varies.
            try:
                page.goto("https://www.google.com", wait_until="domcontentloaded", timeout=15000)
                box = page.locator("textarea[name='q'], input[name='q']").first
                box.wait_for(state="visible", timeout=4000)
                box.click()
                box.fill(query)
                box.press("Enter")
                page.wait_for_load_state("domcontentloaded", timeout=10000)
            except Exception:
                page.goto(search_url, wait_until="domcontentloaded", timeout=20000)

            try:
                page.bring_to_front()
            except Exception:
                pass

            title = page.title()
            return {
                "browser": self._active_channel or "chrome",
                "query": query,
                "url": page.url,
                "title": title,
                "message": f"Opened {self._active_channel or 'chrome'} and searched for '{query}'.",
            }
        except ImportError:
            res = self._launch_native_chrome_url(search_url)
            res["query"] = query
            res["message"] = f"Opened Google Chrome and searched for '{query}'."
            return res

    def get_page_info(self) -> Dict[str, Any]:
        """Return title, URL, and clipped readable text of the active Playwright Chrome tab."""
        if self._page is None or self._page.is_closed():
            return {
                "active": False,
                "message": "No active LocalGuardian Chrome tab is open yet.",
            }
        title = self._page.title()
        url = self._page.url
        snippet = ""
        try:
            text = self._page.inner_text("body")
            snippet = " ".join(text.split())[:1200]
        except Exception:
            pass
        return {
            "active": True,
            "browser": self._active_channel or "chrome",
            "title": title,
            "url": url,
            "snippet": snippet,
            "message": f"Active tab: {title} ({url})",
        }

    def close(self) -> None:
        try:
            if self._context is not None:
                self._context.close()
        except Exception:
            pass
        try:
            if self._browser is not None:
                self._browser.close()
        except Exception:
            pass
        try:
            if self._pw is not None:
                self._pw.stop()
        except Exception:
            pass
        self._page = None
        self._context = None
        self._browser = None
        self._pw = None
