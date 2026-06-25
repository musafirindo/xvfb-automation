#!/usr/bin/env python3
"""Contoh: Login ke Google / Gemini via Xvfb Browser."""

import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from xvfb_automation import XvfbBrowser

EMAIL = os.environ.get("GOOGLE_EMAIL", "your-email@gmail.com")
PASSWORD = os.environ.get("GOOGLE_PASSWORD", "")

browser = XvfbBrowser()
browser.start("https://accounts.google.com/signin")

# Step 1: Email
time.sleep(3)
browser.type(EMAIL, selector="input[type=email]")
browser.click("text=Berikutnya")  # atau "Next"

# Step 2: Password
time.sleep(3)
browser.type(PASSWORD, selector="input[type=password]")
browser.click("text=Berikutnya")

# Step 3: 2FA — tunggu user approve dari HP
print("⏳ Tunggu 2FA approval di HP... (60 detik)")
time.sleep(60)

# Step 4: Verifikasi
browser.navigate("https://myaccount.google.com")
title = browser.eval("document.title")
print(f"✅ Login berhasil: {title}")

browser.screenshot("/tmp/google_login_result.png")
print("📸 Screenshot → /tmp/google_login_result.png")

browser.stop()
