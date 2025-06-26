# -*- coding: utf-8 -*-
import json
import time
import requests
import logging
import random
import os
import sys
import io
import re

try:
    import psutil
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "psutil"])
    import psutil

from playwright.sync_api import sync_playwright, TimeoutError

def is_low_memory():
    # Detect low memory systems (less than 2GB RAM)
    total_ram = psutil.virtual_memory().total / (1024**3)
    return total_ram <= 2.0

def get_launch_args(browser):
    if browser == "chromium" and is_low_memory():
        return ["--no-sandbox", "--disable-dev-shm-usage"]
    else:
        return []

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

LOGIN_URL = "https://login.alditalk-kundenbetreuung.de/signin/XUI/#login/"
DASHBOARD_URL = "https://www.alditalk-kundenportal.de/portal/auth/uebersicht/"

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:137.0) Gecko/20100101 Firefox/139.0"
HEADLESS = True
browser = None

valid_browsers = ["chromium", "firefox", "webkit"]
BROWSER = os.getenv("BROWSER", "chromium").lower()
if BROWSER not in valid_browsers:
    logging.warning(f"Invalid browser value '{BROWSER}' in environment - defaulting to 'chromium'")
    BROWSER = "chromium"

PHONE_NUMBER = os.getenv("PHONE")
PASSWORD = os.getenv("PASSWORD")
SLEEP_MODE = os.getenv("SLEEP_MODE", "random")
SLEEP_INTERVAL = os.getenv("SLEEP_INTERVAL", "90")

if not PHONE_NUMBER or not PASSWORD:
    logging.critical("Environment variables PHONE and PASSWORD must be set.")
    sys.exit(1)

LAST_DATA_GB = 0.0

try:
    with open("state.json", "r") as f:
        data = json.load(f)
        if isinstance(data, dict) and "last_gb" in data:
            LAST_DATA_GB = float(data["last_gb"])
        else:
            raise ValueError("Invalid format in state.json - resetting.")
except Exception as e:
    try:
        with open("state.json", "w") as f:
            json.dump({"last_gb": 0.0}, f)
    except Exception as save_error:
        logging.error(f"Could not recreate 'state.json': {save_error}")

def wait_and_click(page, selector, timeout=5000, retries=5):
    for attempt in range(retries):
        try:
            logging.info(f"Attempting to click {selector} (Attempt {attempt+1}/{retries})...")
            page.wait_for_selector(selector, timeout=timeout)
            page.click(selector)
            return True
        except TimeoutError:
            logging.warning(f"{selector} not found. Retrying...")
            time.sleep(1)
    logging.error(f"Could not click {selector}.")
    return False

def get_data_volume(page):
    logging.info("Reading available data volume...")

    try:
        label_selectors = [
            'one-stack.usage-meter:nth-child(1) > one-usage-meter:nth-child(1) > one-button:nth-child(2)',
            'one-stack.usage-meter:nth-child(1) > one-stack:nth-child(1) > one-usage-meter:nth-child(1) > one-button:nth-child(2)'
        ]

        label_text = ""
        is_community_plus = False

        for sel in label_selectors:
            try:
                element = page.query_selector(sel)
                if element:
                    label_text = element.text_content().strip()
                    if label_text:
                        break
            except Exception as e:
                logging.warning(f"Selector {sel} for Community+ label not found: {e}")

        if "Inland & EU" in label_text:
            is_community_plus = True
            logging.info("Community+ detected")
            data_selectors = [
                'one-stack.usage-meter:nth-child(2) > one-usage-meter:nth-child(1) > one-group:nth-child(1) > one-heading:nth-child(2)',
                'one-stack.usage-meter:nth-child(2) > one-stack:nth-child(1) > one-usage-meter:nth-child(1) > one-group:nth-child(1) > one-heading:nth-child(2)'
            ]
        else:
            data_selectors = [
                'one-stack.usage-meter:nth-child(1) > one-usage-meter:nth-child(1) > one-group:nth-child(1) > one-heading:nth-child(2)',
                'one-stack.usage-meter:nth-child(1) > one-stack:nth-child(1) > one-usage-meter:nth-child(1) > one-group:nth-child(1) > one-heading:nth-child(2)'
            ]
    except Exception as e:
        logging.warning(f"Error while detecting Community+: {e}")
        is_community_plus = False
        data_selectors = [
            'one-stack.usage-meter:nth-child(1) > one-usage-meter:nth-child(1) > one-group:nth-child(1) > one-heading:nth-child(2)',
            'one-stack.usage-meter:nth-child(1) > one-stack:nth-child(1) > one-usage-meter:nth-child(1) > one-group:nth-child(1) > one-heading:nth-child(2)'
        ]

    data_text_raw = None
    for sel in data_selectors:
        try:
            element = page.query_selector(sel)
            if element:
                data_text_raw = element.text_content()
                if data_text_raw:
                    break
        except Exception as e:
            logging.warning(f"Selector {sel} not available: {e}")
            continue

    if not data_text_raw:
        raise Exception("Could not read data volume - no valid selector found.")

    match = re.search(r"([\d\.,]+)\s?(GB|MB)", data_text_raw)
    if not match:
        raise ValueError(f"Unexpected format for data volume: {data_text_raw}")

    value, unit = match.groups()
    value = value.replace(",", ".")

    if unit == "MB":
        gb = float(value) / 1024
    else:
        gb = float(value)

    return gb, is_community_plus

def login_and_check_data():
    global LAST_DATA_GB
    with sync_playwright() as p:
        for attempt in range(3):
            try:
                COOKIE_FILE = "cookies.json"
                logging.info(f"Starting {BROWSER}...")
                LAUNCH_ARGS = get_launch_args(BROWSER)

                if BROWSER == "firefox":
                    browser = p.firefox.launch(headless=HEADLESS, args=LAUNCH_ARGS)
                elif BROWSER == "webkit":
                    browser = p.webkit.launch(headless=HEADLESS, args=LAUNCH_ARGS)
                else:
                    browser = p.chromium.launch(headless=HEADLESS, args=LAUNCH_ARGS)

                if os.path.exists(COOKIE_FILE):
                    logging.info("Loading saved cookies...")
                    context = browser.new_context(user_agent=USER_AGENT, storage_state=COOKIE_FILE)
                else:
                    logging.info("No cookies found - creating new context.")
                    context = browser.new_context(user_agent=USER_AGENT)

                page = context.new_page()

                def login_successful(p):
                    try:
                        p.wait_for_selector('one-heading[level="h1"]', timeout=8000)
                        heading = p.text_content('one-heading[level="h1"]')
                        return heading and "Übersicht" in heading
                    except:
                        return False

                page.goto(DASHBOARD_URL, wait_until="domcontentloaded")
                time.sleep(3)

                if "login" in page.url:
                    logging.info("Not logged in - performing login...")
                    page.goto(LOGIN_URL)
                    page.wait_for_load_state("domcontentloaded")
                    wait_and_click(page, 'button[data-testid="uc-deny-all-button"]')

                    logging.info("Filling login form...")
                    page.fill('#input-5', PHONE_NUMBER)
                    page.fill('#input-6', PASSWORD)

                    if not wait_and_click(page, '[class="button button--solid button--medium button--color-default button--has-label"]'):
                        raise Exception("Could not click login button.")

                    logging.info("Waiting for login...")
                    time.sleep(8)
                    page.wait_for_load_state("domcontentloaded")

                    if login_successful(page):
                        logging.info("Login successful - saving cookies.")
                        context.storage_state(path=COOKIE_FILE)
                    else:
                        raise Exception("Login failed - dashboard not visible.")
                else:
                    logging.info("Already logged in - accessing dashboard.")

                    if not login_successful(page):
                        logging.warning("Session may be expired or invalid - retrying login...")

                        if os.path.exists(COOKIE_FILE):
                            os.remove(COOKIE_FILE)
                            logging.info("Old cookies deleted due to invalid session.")

                        page.goto(LOGIN_URL)
                        page.wait_for_load_state("domcontentloaded")
                        wait_and_click(page, 'button[data-testid="uc-deny-all-button"]')

                        logging.info("Filling login form (fallback)...")
                        page.fill('#input-5', PHONE_NUMBER)
                        page.fill('#input-6', PASSWORD)

                        if not wait_and_click(page, '[class="button button--solid button--medium button--color-default button--has-label"]'):
                            raise Exception("Fallback login: could not click login button.")

                        logging.info("Waiting for login... (fallback)")
                        time.sleep(8)
                        page.wait_for_load_state("domcontentloaded")

                        if login_successful(page):
                            logging.info("Fallback login successful - saving cookies.")
                            context.storage_state(path=COOKIE_FILE)
                        else:
                            raise Exception("Fallback login failed - session could not be restored.")

                    try:
                        page.hover('one-heading[level="h1"]')
                        logging.info("Simulated session activity via hover.")
                    except:
                        logging.warning("Could not simulate session activity.")

                    logging.info("Updating cookies.")
                    context.storage_state(path=COOKIE_FILE)

                gb, is_community_plus = get_data_volume(page)
                LAST_DATA_GB = gb

                try:
                    with open("state.json", "w") as f:
                        json.dump({"last_gb": LAST_DATA_GB}, f)
                except Exception as e:
                    logging.warning(f"Error saving GB value: {e}")

                if gb < 1.0:
                    logging.info("Attempting to book additional 1 GB...")

                    selectors = [
                        'one-stack.usage-meter:nth-child(2) > one-usage-meter:nth-child(1) > one-button:nth-child(3)',
                        'one-stack.usage-meter:nth-child(2) > one-stack:nth-child(1) > one-usage-meter:nth-child(1) > one-button:nth-child(3)'
                    ] if is_community_plus else [
                        'one-stack.usage-meter:nth-child(1) > one-usage-meter:nth-child(1) > one-button:nth-child(3)',
                        'one-stack.usage-meter:nth-child(1) > one-stack:nth-child(1) > one-usage-meter:nth-child(1) > one-button:nth-child(3)'
                    ]

                    for selector in selectors:
                        try:
                            button = page.query_selector(selector)
                            if button and "1 GB" in button.text_content():
                                if wait_and_click(page, selector):
                                    logging.info(f"Clicked 1 GB add-on button via selector: {selector}")
                                    break
                        except Exception as e:
                            logging.warning(f"Error using selector {selector}: {e}")
                    return get_interval()
                else:
                    logging.info(f"Current data volume: {gb:.2f} GB")

                return get_interval()

            except Exception as e:
                logging.error(f"Error in attempt {attempt+1}: {e}")
            finally:
                if browser:
                    browser.close()
                    logging.info("Browser closed.")

            time.sleep(2)
        logging.error("Script failed after 3 attempts.")

def get_smart_interval():
    if LAST_DATA_GB >= 10:
        return random.randint(3600, 5400)
    elif LAST_DATA_GB >= 5:
        return random.randint(900, 1800)
    elif LAST_DATA_GB >= 3:
        return random.randint(600, 900)
    elif LAST_DATA_GB >= 2:
        return random.randint(300, 450)
    elif LAST_DATA_GB >= 1.2:
        return random.randint(150, 240)
    elif LAST_DATA_GB >= 1.0:
        return random.randint(60, 90)
    else:
        return 60  # Fallback

def get_interval():
    mode = SLEEP_MODE
    if mode == "smart":
        return get_smart_interval()
    elif mode == "fixed":
        try:
            return int(SLEEP_INTERVAL)
        except ValueError:
            return 90
    elif mode.startswith("random_"):
        try:
            _, range_str = mode.split("_", 1)
            min_val, max_val = map(int, range_str.split("-"))
            if min_val >= max_val:
                raise ValueError("Min must be less than Max")
            return random.randint(min_val, max_val)
        except Exception:
            return random.randint(300, 500)
    else:
        return random.randint(300, 500)

if __name__ == "__main__":
    while True:
        logging.info("Starting new cycle...")
        interval = login_and_check_data()
        logging.info(f"Waiting {interval} seconds before next run...")
        time.sleep(interval)
