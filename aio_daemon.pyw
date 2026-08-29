"""
aio_daemon.pyw -- background service for the AIO pump-cap display.

Runs with no console window (.pyw), posts CPU temperature and fan RPM to the
panel once a second, and sits in the system tray with a tooltip showing the
live values. Right-click the tray icon for status or to quit.

Why it needs administrator: CPU temperature and fan tachometers live behind
the SuperIO chip and MSR registers, which need a kernel driver.
LibreHardwareMonitor provides one. Without elevation the library still loads
but reports nothing, so this logs a clear warning rather than showing zeros.

Configuration lives in config.json next to this file, written with defaults
on first run:

    {
      "big":  "cpu_temp",     what the big readout shows
      "small":"cpu_fan",      what the small readout shows
      "temp": "CPU Package",  sensor name or "#index"
      "fan":  "Fan #1",       sensor name or "#index"
      "hz":   1.0,
      "smooth": 3,            median of the last N samples; 1 = raw
      "fahrenheit": false,
      "dll":  null            null = the copy bundled with PC Monitor
    }

Install it to start at logon with INSTALL_STARTUP.bat.
"""

import ctypes
import json
import os
import sys
import threading
import time
import traceback
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

CONFIG_PATH = os.path.join(HERE, "config.json")
LOG_PATH = os.path.join(HERE, "aio_daemon.log")
ICON_PATH = os.path.join(HERE, "icon.ico")
MAX_LOG_BYTES = 256 * 1024

DEFAULTS = {
    "big": "cpu_temp",
    "small": "cpu_fan",
    "temp": "CPU Package",
    "fan": "Fan #1",
    "hz": 1.0,
    "fahrenheit": False,
    "dll": None,
    "smooth": 3,
}


def log(msg):
    try:
        if os.path.exists(LOG_PATH) and os.path.getsize(LOG_PATH) > MAX_LOG_BYTES:
            with open(LOG_PATH, "rb") as fh:
                fh.seek(-MAX_LOG_BYTES // 2, os.SEEK_END)
                tail = fh.read()
            with open(LOG_PATH, "wb") as fh:
                fh.write(b"...log truncated...\n" + tail)
        with open(LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(f"{datetime.now():%Y-%m-%d %H:%M:%S}  {msg}\n")
    except Exception:  # noqa: BLE001
        pass


def load_config():
    cfg = dict(DEFAULTS)
    try:
        if os.path.exists(CONFIG_PATH):
            with open(CONFIG_PATH, encoding="utf-8") as fh:
                cfg.update(json.load(fh))
        else:
            with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
                json.dump(cfg, fh, indent=2)
            log(f"wrote default config to {CONFIG_PATH}")
    except Exception as e:  # noqa: BLE001
        log(f"config error, using defaults: {e}")
    return cfg


# The old private mutex here had two faults: creating a Global object needs a
# privilege a non-elevated run does not have, so the call failed and the
# daemon concluded (wrongly) that a copy was running; and it guarded only the
# daemon, while the actual collision was a leftover demo_stats.py window.
# Exclusion now lives in panel_lock.py, acquired by AioScreen.open(), so every
# script that touches the panel participates.


class Daemon:
    def __init__(self, cfg):
        self.cfg = cfg
        self.stop = threading.Event()
        self.status = "starting"
        self.last = (0, 0)
        self.screen = None
        self.sensors = None
        self._big_hist = []
        self._small_hist = []
        self._warned_temp = False
        self._warned_fan = False

    # -- data ---------------------------------------------------------
    def _open_sensors(self):
        from sensors import LhmSensors, DEFAULT_DLL, is_admin
        if not is_admin():
            log("WARNING: not elevated -- CPU temp and fan RPM will read 0. "
                "Install with INSTALL_STARTUP.bat so the task runs with highest privileges.")
        self.sensors = LhmSensors(self.cfg.get("dll") or DEFAULT_DLL)
        t = self.sensors.pick_temp(self.cfg.get("temp"))
        f = self.sensors.pick_fan(self.cfg.get("fan"))
        log(f"temp sensor = {t[1] if t else None!r}, fan sensor = {f[1] if f else None!r}")

    def _open_panel(self):
        from aio_screen import AioScreen
        self.screen = AioScreen(fahrenheit=self.cfg.get("fahrenheit", False),
                                role="aio_daemon.pyw").open()
        log(f"panel open, output report {self.screen.output_len} bytes")

    def read(self):
        """
        One hardware refresh, both values, strict sensor matching.

        Strict matters: if the configured sensor is momentarily absent from
        the refresh, returning some OTHER sensor puts a wrong number on the
        panel for one frame. Better to hold the previous value.
        """
        t, f = self.sensors.read_pair(self.cfg.get("temp"), self.cfg.get("fan"),
                                      strict=True)
        if t is None and not self._warned_temp:
            log(f"temperature sensor {self.cfg.get('temp')!r} not present; holding last value")
            self._warned_temp = True
        if f is None and not self._warned_fan:
            log(f"fan sensor {self.cfg.get('fan')!r} not present; holding last value")
            self._warned_fan = True

        big = int(round(t[2])) if t else None
        small = int(round(f[2])) if f else None
        return self._smoothed(big, small)

    def _smoothed(self, big, small):
        """Median of the last N samples. CPU package temperature is spiky by
        nature -- it is the hottest thing the die reports -- and a raw 1 Hz
        sample catches those spikes, which reads as the number jumping."""
        n = max(1, int(self.cfg.get("smooth", 3)))
        if big is not None:
            self._big_hist.append(big)
            del self._big_hist[:-n]
        if small is not None:
            self._small_hist.append(small)
            del self._small_hist[:-n]

        def med(values, fallback):
            if not values:
                return fallback
            ordered = sorted(values)
            return ordered[len(ordered) // 2]

        return med(self._big_hist, self.last[0]), med(self._small_hist, self.last[1])

    # -- loop ---------------------------------------------------------
    def run(self):
        from aio_screen import Stats
        from panel_lock import PanelBusy
        period = 1.0 / max(0.1, float(self.cfg.get("hz", 1.0)))
        backoff = 1.0
        # Pace against a fixed schedule. Sleeping `period` AFTER the work makes
        # the real interval period + read-time, and the sensor read is not
        # constant, so the cadence wanders.
        next_tick = time.monotonic()
        while not self.stop.is_set():
            try:
                if self.sensors is None:
                    self._open_sensors()
                if self.screen is None:
                    self._open_panel()

                big, small = self.read()
                if self.cfg.get("fahrenheit") and big > 123:
                    big = 123           # the panel's 8-bit F conversion wraps past this
                self.screen.send(Stats(cpu_temp=big, cpu_fan=small))
                self.last = (big, small)
                self.status = "running"
                backoff = 1.0
                next_tick += period
                delay = next_tick - time.monotonic()
                if delay < 0:                      # a slow read: resync, never burst
                    next_tick = time.monotonic()
                    delay = 0
                self.stop.wait(delay)
            except PanelBusy as busy:
                # Another writer holds the panel. Retrying forever would just
                # fight it, so back off hard and say so plainly.
                self.status = "another process is driving the panel"
                log(f"panel busy: {busy}")
                self.screen = None
                self.stop.wait(30)
                next_tick = time.monotonic()
                continue
            except Exception as e:  # noqa: BLE001
                # Unplugged panel, sleep/resume, driver hiccup: drop everything
                # and rebuild on the next pass rather than dying silently.
                self.status = f"retrying: {e}"
                log(f"error: {e}\n{traceback.format_exc()}")
                try:
                    if self.screen:
                        self.screen.close()
                except Exception:  # noqa: BLE001
                    pass
                self.screen = None
                self.stop.wait(backoff)
                backoff = min(30.0, backoff * 2)
                next_tick = time.monotonic()

        try:
            if self.screen:
                self.screen.close()
            if self.sensors:
                self.sensors.close()
        except Exception:  # noqa: BLE001
            pass
        log("stopped")

    def tooltip(self):
        big, small = self.last
        unit = "F" if self.cfg.get("fahrenheit") else "C"
        if self.status.startswith("retrying"):
            return f"AIO screen - {self.status}"
        return f"AIO screen\n{big} {unit}   {small} rpm"


def run_tray(daemon):
    """Tray icon if pystray is available; otherwise just run headless."""
    try:
        import pystray
        from PIL import Image
    except ImportError:
        log("pystray/Pillow not installed -- running headless (no tray icon). "
            "pip install pystray pillow")
        daemon.run()
        return

    image = Image.open(ICON_PATH) if os.path.exists(ICON_PATH) else \
        Image.new("RGB", (32, 32), (69, 196, 255))

    worker = threading.Thread(target=daemon.run, daemon=True)
    worker.start()

    def on_quit(icon, _item):
        daemon.stop.set()
        worker.join(timeout=3)
        icon.stop()

    def on_open_log(_icon, _item):
        os.startfile(LOG_PATH) if os.path.exists(LOG_PATH) else None

    def on_open_config(_icon, _item):
        os.startfile(CONFIG_PATH)

    icon = pystray.Icon(
        "aio_screen", image, "AIO screen",
        menu=pystray.Menu(
            pystray.MenuItem(lambda _i: daemon.tooltip().replace("\n", "  "), None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Edit config.json", on_open_config),
            pystray.MenuItem("Open log", on_open_log),
            pystray.MenuItem("Quit", on_quit),
        ),
    )

    def refresh():
        while not daemon.stop.is_set():
            try:
                icon.title = daemon.tooltip()
            except Exception:  # noqa: BLE001
                pass
            time.sleep(2)

    threading.Thread(target=refresh, daemon=True).start()
    icon.run()


def main():
    log("=" * 60)
    log(f"starting (python {sys.version.split()[0]}, elevated="
        f"{bool(ctypes.windll.shell32.IsUserAnAdmin())})")
    cfg = load_config()
    daemon = Daemon(cfg)
    try:
        run_tray(daemon)
    except Exception as e:  # noqa: BLE001
        log(f"fatal: {e}\n{traceback.format_exc()}")


if __name__ == "__main__":
    main()
