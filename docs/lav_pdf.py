"""Bygger PDF'erne i denne mappe fra HTML-filerne med Chromium (Playwright).
Kør:  python docs/lav_pdf.py
"""
import os
from pathlib import Path

from playwright.sync_api import sync_playwright

HER = Path(__file__).resolve().parent
FILER = ["spillervejledning", "arrangoer"]

with sync_playwright() as p:
    exe = os.environ.get("CHROMIUM_PATH")
    browser = p.chromium.launch(executable_path=exe) if exe else p.chromium.launch()
    page = browser.new_page()
    for navn in FILER:
        page.goto((HER / f"{navn}.html").as_uri())
        page.pdf(path=str(HER / f"{navn}.pdf"), format="A4", print_background=True, prefer_css_page_size=True)
        print("skrev", navn + ".pdf")
    browser.close()
