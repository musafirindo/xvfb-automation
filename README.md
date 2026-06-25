# 🔥 Xvfb Automation

**Headless browser automation toolkit for VPS — no desktop environment needed.**

Bundles Xvfb + Chrome CDP + xdotool into a clean Python API. Auto-login, form filling, social media account creation, native file dialogs, and more.

## Why This Exists

Standard headless Chrome (`--headless`) is detected as a bot by Google, Cloudflare, and most modern sites. This toolkit uses **real Chrome on a virtual display** (Xvfb) — indistinguishable from a normal user's browser. Combined with CDP (Chrome DevTools Protocol) for JS injection and xdotool for native OS dialogs, it can automate practically any web flow.

## Installation

```bash
# From PyPI (coming soon)
pip install xvfb-automation

# From GitHub
pip install git+https://github.com/musafirindo/xvfb-automation.git

# Or clone + dev install
git clone https://github.com/musafirindo/xvfb-automation
cd xvfb-automation
pip install -e .
```

### System Dependencies

```bash
sudo apt-get install -y xvfb fluxbox xdotool xclip scrot google-chrome-stable
```

## Quick Start

```python
from xvfb_automation import XvfbBrowser

browser = XvfbBrowser()
browser.start("https://example.com/login")

# CDP-based interaction (fast, reliable for JS-rendered pages)
browser.type("user@email.com", selector="input[type=email]")
browser.type("password123", selector="input[type=password]")
browser.click("text=Sign in")

# xdotool for native dialogs (file upload, OS popups)
browser.xdotool.type_text("/path/to/file.jpg")
browser.xdotool.key("Return")

# Take a screenshot
browser.screenshot("/tmp/page.png")

browser.stop()
```

## Features

| Capability | Method | Works on |
|---|---|---|
| Navigate | `browser.navigate(url)` | All sites |
| Click by text | `browser.click("text=Sign in")` | JS-rendered buttons |
| Click by CSS | `browser.click("css=#myid")` | Any selector |
| Fill form fields | `browser.type(text, selector)` | Standard inputs |
| Fill entire form | `browser.fill_form({...})` | Multi-field forms |
| JS injection | `browser.eval("document.title")` | Full DOM access |
| Screenshot | `browser.screenshot(path)` | Debugging |
| Mouse click (coord) | `browser.xdotool.click_at(x, y)` | Native dialogs |
| Keyboard type | `browser.xdotool.type_text("...")` | Any focused window |
| Key combo | `browser.xdotool.key("ctrl+v")` | Shortcuts, paste |
| Clipboard image | `browser.xdotool.clipboard_set_image(p)` | Paste via Ctrl+V |
| Window search | `browser.xdotool.search_window()` | Find popups |
| Cookies export | `browser.cdp.get_cookies()` | Session export |
| Cookies inject | `browser.cdp.set_cookies([])` | Session restore |

## Platform Compatibility

| Site | Login | Form Fill | File Upload | Notes |
|---|---|---|---|---|
| Google / Gemini | ✅ | ✅ | ❌ | `showOpenFilePicker()` un-interceptable |
| GitHub | ✅ | ✅ | ✅ | Standard forms |
| Reddit | ✅ | ✅ | ✅ | No anti-bot |
| Instagram | ✅ | ⚠️ | ⚠️ | Fingerprinting, rate limits |
| TikTok Web | ✅ | ⚠️ | ⚠️ | Redirect bot checks |
| X / Twitter | ✅ | ✅ | ✅ | Rate limit + email verify |
| WhatsApp Web | ❌ | N/A | N/A | QR scan mandatory |
| Apple ID | ❌ | N/A | N/A | Hardware attestation |

## Examples

```bash
# Google account login
python examples/google_login.py

# Social media account creation
python examples/daftar_sosmed.py

# CLI usage
xvfb-browser https://example.com --screenshot /tmp/out.png --eval "document.title"
```

## Architecture

```
┌──────────────────────────────────────────────┐
│ Xvfb (virtual display 1920x1080)             │
│  └─ fluxbox (window manager)                 │
│  └─ google-chrome --remote-debugging-port=9223│
│      └─ CDP WebSocket ← Python websockets    │
│  └─ xdotool (mouse/keyboard simulation)       │
│  └─ xclip (clipboard management)              │
│  └─ scrot (screenshot)                        │
└──────────────────────────────────────────────┘
```

## Known Limitations

- **Gemini file upload**: `showOpenFilePicker()` + dynamic file input with `nodeId=0` is not automatable
- **Cloudflare Turnstile**: Enterprise-grade challenge blocks even real Chrome on VPS IP
- **Google OAuth GSIs**: `postMessage` popup flow can't be replicated via HTTP
- **CAPTCHA**: Visual/audio challenges require human, not automatable

## License

MIT — use it, fork it, build on it.

---

Made with ☕ by [musafirindo](https://github.com/musafirindo)
