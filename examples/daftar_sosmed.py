#!/usr/bin/env python3
"""Contoh: Daftar akun sosial media — Reddit, GitHub, Pinterest, dll."""

import sys, os, time, random, string
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from xvfb_automation import XvfbBrowser

def random_user():
    """Generate random username."""
    adj = ["cool", "fast", "wild", "mega", "ultra", "neo", "zen", "flux"]
    return f"{random.choice(adj)}_{random.randint(1000,9999)}"

# ─── Pilih platform ───────────────────────────────────────────────────────

PLATFORM = sys.argv[1] if len(sys.argv) > 1 else "reddit"
EMAIL = os.environ.get("SOCIAL_EMAIL", "your-email@gmail.com")
USER = random_user()
PASS = ''.join(random.choices(string.ascii_letters + string.digits, k=14))

PLATFORM_CONFIG = {
    "reddit": {
        "url": "https://www.reddit.com/register/",
        "fill": {
            "input[name=email]": EMAIL,
            "button:Continue": None
        }
    },
    "github": {
        "url": "https://github.com/signup",
        "fill": {
            "input[name='user[login]']": USER,
            "input[name='user[email]']": EMAIL,
            "input[name='user[password]']": PASS,
        }
    },
    "pinterest": {
        "url": "https://www.pinterest.com/_ngjs/business-signup/",
        "fill": {
            "input[name=email]": EMAIL,
            "input[name=password]": PASS,
            "input[name=age]": "25",
        }
    },
}

cfg = PLATFORM_CONFIG.get(PLATFORM)
if not cfg:
    print(f"❌ Platform '{PLATFORM}' tidak dikenal.")
    print(f"   Pilihan: {', '.join(PLATFORM_CONFIG.keys())}")
    sys.exit(1)

print(f"🚀 Mendaftar ke {PLATFORM}...")
print(f"   Email: {EMAIL}")
print(f"   Username: {USER}")
print(f"   Password: {PASS}")

browser = XvfbBrowser()
browser.start(cfg["url"])

time.sleep(3)

# Isi form
for selector, value in cfg["fill"].items():
    if value is None:
        browser.click(selector)
    else:
        browser.type(value, selector=selector)
    time.sleep(0.5)

# Screenshot hasil
browser.screenshot(f"/tmp/{PLATFORM}_daftar.png")
print(f"📸 Screenshot → /tmp/{PLATFORM}_daftar.png")

browser.stop()
print("✅ Selesai!")
