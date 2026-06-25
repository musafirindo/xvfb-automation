# xvfb-automation — Headless Browser Automation Toolkit
# Xvfb + Chrome CDP + xdotool hybrid for VPS without desktop environment
#
# pip install xvfb-automation
#   atau
# git clone https://github.com/musafirindo/xvfb-automation

__version__ = "1.0.0"

import os, sys, time, signal, subprocess, json, atexit, logging, asyncio
from pathlib import Path

logger = logging.getLogger("xvfb_automation")

# ─── Platform-specific defaults ──────────────────────────────────────────

DEFAULTS = {
    "display": ":99",
    "screen": "1920x1080x24",
    "cdp_port": 9223,
    "chrome_bin": None,           # auto-detect (google-chrome > chromium-browser > chromium)
    "profile_dir": "/tmp/xvfb-chrome-profile",
    "window_manager": "fluxbox",  # fluxbox recommended; "none" for no WM
    "startup_timeout": 15,        # seconds to wait for Chrome CDP
    "implicit_wait": 5,           # seconds after navigation
}

# ─── Process registry for cleanup ─────────────────────────────────────────

_procs: list[subprocess.Popen] = []
_atexit_registered = False

def _cleanup():
    """Kill all spawned processes on exit."""
    for p in reversed(_procs):
        try:
            if p.poll() is None:
                p.terminate()
                try: p.wait(timeout=2)
                except subprocess.TimeoutExpired: p.kill()
        except Exception:
            pass
    _procs.clear()

def _register_cleanup():
    global _atexit_registered
    if not _atexit_registered:
        atexit.register(_cleanup)
        signal.signal(signal.SIGTERM, lambda *_: _cleanup())
        _atexit_registered = True

def _spawn(cmd, **kwargs) -> subprocess.Popen:
    """Spawn a process and register for cleanup."""
    p = subprocess.Popen(cmd, **kwargs)
    _procs.append(p)
    return p


# ─── Public API ───────────────────────────────────────────────────────────

class XvfbBrowser:
    """Headless browser instance backed by Xvfb + Chrome + CDP.

    Usage:
        from xvfb_automation import XvfbBrowser

        browser = XvfbBrowser()
        browser.start()
        page = browser.cdp  # CDP client for JS injection, navigation, etc.

        # Login via CDP + keyboard
        browser.navigate("https://example.com/login")
        browser.click("text=Sign in")          # semantic click via CDP
        browser.type("email@example.com", selector="input[type=email]")
        browser.type("password123", selector="input[type=password]")
        browser.press("Enter")

        # Use xdotool for native dialogs
        browser.xdotool.click_at(400, 300)
        browser.xdotool.type_text("/path/to/file")
        browser.xdotool.key("Return")

        # Screenshot
        browser.screenshot("/tmp/page.png")

        browser.stop()
    """

    def __init__(self, **kwargs):
        for k, v in DEFAULTS.items():
            setattr(self, k, kwargs.get(k, v))
        self._started = False
        self._cdp = None
        self._sid = None          # CDP session ID (for send(... sessionId=...))
        self._ws_url = None       # webSocketDebuggerUrl

    # ── Start / Stop ──────────────────────────────────────────────────

    def start(self, url: str = "about:blank"):
        """Start Xvfb, fluxbox, Chrome, and connect CDP. Returns self."""
        if self._started:
            return self
        _register_cleanup()

        # --- Xvfb ---
        logger.info(f"Starting Xvfb on display {self.display}")
        display_num = self.display.lstrip(":")
        lock_file = f"/tmp/.X{display_num}-lock"
        if os.path.exists(lock_file):
            os.unlink(lock_file)
        _spawn(["Xvfb", self.display, "-screen", "0", self.screen],
               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(1)

        env = {**os.environ, "DISPLAY": self.display}

        # --- Window Manager ---
        if self.window_manager.lower() != "none":
            wm_bin = self.window_manager
            logger.info(f"Starting window manager: {wm_bin}")
            _spawn([wm_bin, "-display", self.display],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)
            time.sleep(2)

        # --- Chrome ---
        chrome = self._find_chrome()
        profile = self.profile_dir
        os.makedirs(profile, exist_ok=True)

        logger.info(f"Launching Chrome on port {self.cdp_port}, profile={profile}")
        _spawn([
            chrome,
            f"--remote-debugging-port={self.cdp_port}",
            f"--user-data-dir={profile}",
            "--no-sandbox",
            "--disable-gpu",
            "--disable-dev-shm-usage",
            "--disable-features=TranslateUI",
            "--disable-session-crashed-bubble",
            "--disable-restore-session-state",
            "--window-size=1920,1080",
            url,
        ], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        # --- Wait for CDP ---
        self._wait_cdp()
        self._started = True
        return self

    def stop(self):
        """Kill all browser processes."""
        _cleanup()
        self._started = False
        self._cdp = None
        self._ws_url = None
        logger.info("XvfbBrowser stopped.")

    def restart(self, url: str = "about:blank"):
        """Stop and start fresh."""
        self.stop()
        self.start(url=url)

    # ── Navigation ────────────────────────────────────────────────────

    def navigate(self, url: str):
        """Navigate to URL via JS location.href (preserves CDP connection)."""
        self._ensure_started()
        self._js(f"window.location.href = {json.dumps(url)}")
        time.sleep(self.implicit_wait)

    def new_tab(self, url: str = "about:blank"):
        """Open a new tab via CDP and switch to it."""
        self._ensure_started()
        import urllib.request
        resp = urllib.request.urlopen(f"http://localhost:{self.cdp_port}/json/new?{urllib.parse.quote(url)}")
        data = json.loads(resp.read())
        self._ws_url = data["webSocketDebuggerUrl"]
        self._sid = None
        time.sleep(2)

    # ── CDP shortcuts ─────────────────────────────────────────────────

    @property
    def cdp(self):
        """Get the CDP controller (for advanced JS injection, network, etc.)."""
        self._ensure_started()
        return CDPController(self)

    def _js(self, expression: str, timeout: int = 10) -> any:
        """Low-level: execute JavaScript via CDP websocket. Auto-handles event loops."""
        import asyncio
        try:
            loop = asyncio.get_running_loop()
            # Already inside event loop — create task in new thread
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                fut = ex.submit(asyncio.run, self._async_js(expression, timeout))
                return fut.result(timeout=timeout + 5)
        except RuntimeError:
            # No event loop — use asyncio.run directly
            return asyncio.run(self._async_js(expression, timeout))

    async def _async_js(self, expression: str, timeout: int = 10):
        """Execute JS via CDP WebSocket with proper error handling."""
        import websockets
        if not self._ws_url:
            self._wait_cdp()
            if not self._ws_url:
                logger.error("No CDP WebSocket URL available")
                return None
        last_err = None
        for attempt in range(2):  # 1 retry
            try:
                async with websockets.connect(
                    self._ws_url,
                    open_timeout=min(10, timeout),
                    close_timeout=5,
                ) as ws:
                    msg = {
                        "id": 1,
                        "method": "Runtime.evaluate",
                        "params": {
                            "expression": expression,
                            "returnByValue": True,
                            "awaitPromise": False,
                        },
                    }
                    await ws.send(json.dumps(msg))
                    resp_raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
                    resp = json.loads(resp_raw)

                    # Check for CDP-level error
                    if "error" in resp:
                        err = resp["error"]
                        logger.warning(f"CDP error: {err.get('message', err)}")
                        # Page context lost — try reconnecting
                        if "context" in str(err).lower():
                            self._ws_url = None
                            self._wait_cdp()
                            continue
                        return None

                    # Extract value
                    result = resp.get("result", {})
                    inner = result.get("result", {})
                    if "value" in inner:
                        return inner["value"]
                    # Some expressions return object with objectId
                    if "objectId" in inner:
                        return f"[object:{inner.get('type','unknown')}]"
                    if "description" in inner:
                        return inner["description"]
                    # Exception thrown in JS
                    if inner.get("subtype") == "error":
                        desc = inner.get("description", "unknown error")
                        logger.warning(f"JS exception: {desc}")
                        return None
                    return None

            except asyncio.TimeoutError:
                last_err = f"Timeout after {timeout}s"
                logger.warning(f"CDP timeout (attempt {attempt+1}/2): {expression[:60]}...")
                # Refresh WS URL and retry
                self._ws_url = None
                try:
                    self._wait_cdp()
                except Exception:
                    pass
            except Exception as e:
                last_err = str(e)
                logger.warning(f"CDP error (attempt {attempt+1}/2): {e}")
                self._ws_url = None
                try:
                    self._wait_cdp()
                except Exception:
                    pass

        logger.error(f"CDP failed after 2 attempts: {last_err}")
        return None

    def eval(self, expression: str, timeout: int = 10):
        """Execute JavaScript and return the value."""
        return self._js(expression, timeout)

    # ── Semantic interaction (via CDP JS) ──────────────────────────────

    def click(self, target: str):
        """Click an element. target can be:
           - "text=Sign in"  → click button containing text
           - "css=#myid"     → document.querySelector
           - "xpath=//..."   → document.evaluate
        """
        self._ensure_started()
        if target.startswith("text="):
            text = target[5:]
            js = f"""
            (function() {{
                const els = document.querySelectorAll('button, a, [role="button"], span, div');
                for (const e of els) {{
                    if (e.textContent && e.textContent.trim().includes({json.dumps(text)})) {{
                        e.click(); return 'clicked ' + e.tagName;
                    }}
                }}
                return 'not found';
            }})()
            """
        elif target.startswith("css="):
            sel = target[4:]
            js = f"""(function() {{ const e = document.querySelector({json.dumps(sel)});
                if (e) {{ e.click(); return 'clicked'; }} return 'not found'; }})()"""
        elif target.startswith("xpath="):
            xpath = target[6:]
            js = f"""(function() {{ const e = document.evaluate({json.dumps(xpath)}, document, null,
                XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
                if (e) {{ e.click(); return 'clicked'; }} return 'not found'; }})()"""
        else:
            raise ValueError(f"Unknown target format: {target}. Use text=, css=, or xpath=")
        return self._js(js)

    def type(self, text: str, selector: str = "input:not([type=hidden]):not([readonly])"):
        """Type text into a form field by CSS selector."""
        self._ensure_started()
        js = f"""(function() {{ const e = document.querySelector({json.dumps(selector)});
            if (!e) return 'selector not found';
            e.focus(); e.value = {json.dumps(text)};
            e.dispatchEvent(new Event('input', {{ bubbles: true }}));
            e.dispatchEvent(new Event('change', {{ bubbles: true }}));
            return 'typed';
        }})()"""
        return self._js(js)

    def press(self, key: str):
        """Dispatch a keyboard event on the active element."""
        self._ensure_started()
        js = f"""(function() {{
            const e = document.activeElement || document.body;
            e.dispatchEvent(new KeyboardEvent('keydown', {{ key: {json.dumps(key)}, bubbles: true }}));
            e.dispatchEvent(new KeyboardEvent('keypress', {{ key: {json.dumps(key)}, bubbles: true }}));
            e.dispatchEvent(new KeyboardEvent('keyup', {{ key: {json.dumps(key)}, bubbles: true }}));
            return 'pressed ' + {json.dumps(key)};
        }})()"""
        return self._js(js)

    def fill_form(self, fields: dict):
        """Fill multiple form fields at once. fields = {'input[type=email]': '...', 'input[type=password]': '...'}"""
        results = {}
        for selector, value in fields.items():
            results[selector] = self.type(value, selector)
        return results

    # ── Screenshot ────────────────────────────────────────────────────

    def screenshot(self, path: str):
        """Take a screenshot of the Xvfb display."""
        self._ensure_started()
        env = {**os.environ, "DISPLAY": self.display}
        result = subprocess.run(
            ["scrot", path], env=env, capture_output=True, text=True, timeout=10
        )
        if result.returncode != 0:
            # Fallback to xdotool
            subprocess.run(
                ["xdotool", "getactivewindow"], env=env, capture_output=True, timeout=5
            )
        return Path(path).exists()

    # ── xdotool ───────────────────────────────────────────────────────

    @property
    def xdotool(self):
        """Get the xdotool controller for mouse/keyboard/native dialog automation."""
        self._ensure_started()
        return XdoTool(self)

    # ── Internals ─────────────────────────────────────────────────────

    def _ensure_started(self):
        if not self._started:
            raise RuntimeError("XvfbBrowser not started. Call .start() first.")

    def _find_chrome(self) -> str:
        if self.chrome_bin:
            return self.chrome_bin
        for name in ["google-chrome", "google-chrome-stable", "chromium-browser", "chromium"]:
            path = subprocess.run(["which", name], capture_output=True, text=True).stdout.strip()
            if path:
                return path
        raise FileNotFoundError("No Chrome/Chromium found. Install: apt install google-chrome-stable")

    def _wait_cdp(self):
        import urllib.request, urllib.error
        deadline = time.time() + self.startup_timeout
        while time.time() < deadline:
            try:
                resp = urllib.request.urlopen(f"http://localhost:{self.cdp_port}/json/version")
                data = json.loads(resp.read())
                self._ws_url = data.get("webSocketDebuggerUrl")
                if self._ws_url:
                    logger.info(f"CDP ready: {self._ws_url[:60]}...")
                    return
            except (urllib.error.URLError, ConnectionRefusedError, OSError):
                pass
            time.sleep(0.5)
        raise TimeoutError(f"Chrome CDP not ready after {self.startup_timeout}s on port {self.cdp_port}")


class CDPController:
    """Fine-grained CDP control: inject JS, capture network, manage cookies."""
    def __init__(self, browser: XvfbBrowser):
        self._browser = browser

    def js(self, expression: str, timeout: int = 10):
        return self._browser._js(expression, timeout)

    async def send(self, method: str, params: dict = None, timeout: int = 10):
        """Send arbitrary CDP command with error handling."""
        import websockets
        if not self._browser._ws_url:
            self._browser._wait_cdp()
            if not self._browser._ws_url:
                logger.error("No CDP WebSocket URL available for send()")
                return {"error": "no websocket url"}
        async with websockets.connect(self._browser._ws_url, open_timeout=10) as ws:
            msg = {"id": 1, "method": method, "params": params or {}}
            await ws.send(json.dumps(msg))
            resp_raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
            resp = json.loads(resp_raw)
            if "error" in resp:
                logger.warning(f"CDP error in {method}: {resp['error'].get('message', resp['error'])}")
            return resp

    def get_cookies(self):
        """Get all browser cookies as JSON."""
        import asyncio
        return asyncio.run(self.send("Network.getAllCookies"))

    def set_cookies(self, cookies: list):
        """Inject cookies into the browser."""
        import asyncio
        return asyncio.run(self.send("Network.setCookies", {"cookies": cookies}))

    def navigate_cdp(self, url: str):
        """Navigate via CDP Page.navigate (may disconnect — prefer browser.navigate)."""
        import asyncio
        return asyncio.run(self.send("Page.navigate", {"url": url}))


class XdoTool:
    """xdotool wrapper: mouse clicks, keyboard, clipboard, window management."""
    def __init__(self, browser: XvfbBrowser):
        self._b = browser
        self._env = {**os.environ, "DISPLAY": browser.display}

    def _run(self, args: list, timeout: int = 10) -> str:
        result = subprocess.run(args, env=self._env, capture_output=True, text=True, timeout=timeout)
        return result.stdout.strip()

    def click_at(self, x: int, y: int):
        """Move mouse to (x, y) and click."""
        self._run(["xdotool", "mousemove", str(x), str(y)])
        self._run(["xdotool", "click", "1"])
        return f"clicked at ({x}, {y})"

    def double_click_at(self, x: int, y: int):
        self._run(["xdotool", "mousemove", str(x), str(y)])
        self._run(["xdotool", "click", "--repeat", "2", "1"])
        return f"double-clicked at ({x}, {y})"

    def right_click_at(self, x: int, y: int):
        self._run(["xdotool", "mousemove", str(x), str(y)])
        self._run(["xdotool", "click", "3"])
        return f"right-clicked at ({x}, {y})"

    def type_text(self, text: str):
        """Type text into the focused window (handles spaces)."""
        self._run(["xdotool", "type", "--", text])
        return f"typed: {text[:50]}..."

    def key(self, keys: str):
        """Send key combination, e.g. 'ctrl+v', 'Return', 'Escape'."""
        self._run(["xdotool", "key", keys])
        return f"pressed: {keys}"

    def search_window(self, name_contains: str = "") -> list:
        """Search for visible windows. Returns list of (id, name)."""
        args = ["xdotool", "search", "--onlyvisible"]
        if name_contains:
            args.extend(["--name", name_contains])
        else:
            args.append(".")
        ids = self._run(args).splitlines()
        result = []
        for wid in ids:
            name = self._run(["xdotool", "getwindowname", wid])
            result.append((wid, name))
        return result

    def focus_window(self, window_id: str):
        """Activate a window by ID."""
        self._run(["xdotool", "windowactivate", window_id])
        self._run(["xdotool", "windowfocus", window_id])
        return f"focused: {window_id}"

    def clipboard_set_image(self, image_path: str):
        """Set an image to the X11 clipboard (for Ctrl+V paste). Auto-converts to PNG."""
        from PIL import Image
        png_path = "/tmp/xvfb_clipboard_temp.png"
        Image.open(image_path).save(png_path, "PNG")
        subprocess.run(
            ["xclip", "-selection", "clipboard", "-t", "image/png", "-i"],
            input=Path(png_path).read_bytes(),
            env=self._env, timeout=10
        )
        Path(png_path).unlink(missing_ok=True)
        return f"clipboard ← {image_path}"

    def clipboard_set_text(self, text: str):
        """Set text to X11 clipboard."""
        subprocess.run(
            ["xclip", "-selection", "clipboard"],
            input=text.encode(), env=self._env, timeout=5
        )
        return f"clipboard ← text ({len(text)} chars)"


# ─── CLI ──────────────────────────────────────────────────────────────────

def main():
    """CLI: xvfb-browser <url> [--screenshot path.png]"""
    import argparse
    parser = argparse.ArgumentParser(description="Xvfb Browser Automation")
    parser.add_argument("url", nargs="?", default="about:blank")
    parser.add_argument("--screenshot", help="Save screenshot to file")
    parser.add_argument("--eval", help="JavaScript to evaluate")
    parser.add_argument("--port", type=int, default=9223)
    parser.add_argument("--display", default=":99")
    args = parser.parse_args()

    browser = XvfbBrowser(cdp_port=args.port, display=args.display)
    browser.start(url=args.url)

    if args.eval:
        result = browser.eval(args.eval)
        print(json.dumps(result, indent=2))

    if args.screenshot:
        ok = browser.screenshot(args.screenshot)
        print(f"Screenshot → {args.screenshot}  {'✅' if ok else '❌'}")

    browser.stop()


if __name__ == "__main__":
    main()
