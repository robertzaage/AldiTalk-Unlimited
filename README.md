# Aldi Talk Data Volume Watchdog and Booker

This tool keeps track of your remaining Aldi Talk data volume and automatically attempts a top-up when it falls below 1 GB. 
Designed for reliability and ease of use, it runs on a containerized setup using Playwright and a headless browser.

---

### Features

* Automatically monitors your remaining data volume
* Attempts automatic top-up when below 1 GB
* Supports random or fixed execution intervals
* Developed with Playwright & headless browser
* Containerized and configurable via environment variables

---

### Run the Aldi Talk Unlimited Container

Just run this compose or create a systemd service if using podman.

```
version: '3.8'

services:
  alditalk-unlimited:
    image: ghcr.io/robertzaage/alditalk-unlimited:latest
    container_name: alditalk-unlimited
    environment:
      PHONE: "<PHONE>"
      PASSWORD: "<PASSWORD>"
      SLEEP_MODE: "smart"
      BROWSER: "firefox"
      TZ: "Europe/Berlin"
```

### Environment Variable Reference

| Key              | Description                                                                                                                                                                                                                                                   |
| ---------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `PHONE`      | Your ALDI TALK number (starting with 0)                                                                                                                                                                                                                       |
| `PASSWORD`       | Your customer portal password                                                                                                                                                                                                                                 |
| `SLEEP_MODE`     | Controls how long to pause after each run: <br><br> `"random"` - Random interval between approx. 5–8 minutes. <br> `"fixed"` - Uses the fixed interval from `SLEEP_INTERVAL` in seconds. <br> `"smart"` - Dynamically adjusts based on remaining data volume. |
| `SLEEP_INTERVAL` | Interval in seconds (only relevant when `"fixed"` is used), **minimum 70 seconds**                                                                                                                                                                            |
| `BROWSER`        | `"chromium"` (default) or `"firefox"`                                                                                                                                                                                                                         |

**Note:** Some server configurations are more stable with `"firefox"` – ideal for lower-powered instances or when `input-6/help-text` fails to load.
