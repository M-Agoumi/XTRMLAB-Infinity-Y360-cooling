"""
aio_daemon.pyw -- background service for the AIO pump-cap display.

Runs with no console window (.pyw), posts CPU temperature and fan RPM to the
panel once a second, and sits in the system tray with a tooltip showing the
live values. Right-click the tray icon for status or to quit.

Why it needs administrator: CPU temperature and fan tachometers live behind
the SuperIO chip and MSR registers, which need a kernel driver.
LibreHardwareMonitor provides one. Without elevation the library still loads
but reports nothing, so this logs a clear warning rather than showing zeros.

Fun mode (toggle it from the tray icon) alternates second by second:

    1s  real temp / real rpm
    2s  0        / 8008          <- fun frame
    3s  real temp / real rpm
    4s  0        / 420           <- fun frame
    ... and loops

Each frame is a [big, small] pair. **0 in the big slot is as close to blank as
this panel gets**: the field always draws a number -- the whole 0-127 range
was calibrated and every value renders something, so there is no blanking
value to send. 0 C is impossible for a running CPU, so it reads as obviously
not a measurement, which is the point: the temperature is never shown as a
plausible-but-fake number.

**null** in a slot means "leave the real reading there" instead.

Configuration lives in config.json next to this file, written with defaults
on first run:

    {
      "big":  "cpu_temp",     what the big readout shows
      "small":"cpu_fan",      what the small readout shows
      "temp": "CPU Package",  sensor name or "#index"
      "fan":  "Fan #1",       sensor name or "#index"
      "hz":   1.0,
      "smooth": 3,            median of the last N samples; 1 = raw
      "fun":  false,          alternate real readings with joke frames
      "fun_frames": [[69, 8008], [42, 420]],   [big, small] pairs
      "fahrenheit": false,
      "fan_low2_offset": 20,  fan digit correction (see fan_tune.py)
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
EXAMPLE_CONFIG = os.path.join(HERE, "config.example.json")
LOG_PATH = os.path.join(HERE, "aio_daemon.log")
PID_PATH = os.path.join(HERE, "daemon.pid")
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
    # Fun mode: alternate real readings with fixed joke frames, one second
    # each -- real, joke, real, next joke, looping through fun_frames.
    # The panel renders the fan number's last two decimal digits offset by
    # this much (measured: 20 on this unit, no carry into the hundreds).
    # The driver rolls them back so what you ask for is what appears.
    # null = send verbatim. Run fan_tune.py to measure yours.
    "fan_low2_offset": 20,
    "fun": False,
    # null = keep the real reading for that slot. Default: fan slot only, so
    # the temperature is never faked.
    "fun_frames": [[0, 8088], [0, 420]],
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


def write_pid_file():
    """
    Presence marker for the desktop shortcut.

    panel.lock alone is not enough: it is released whenever the panel handle
    is dropped (unplugged device, resume from sleep, another writer), so the
    daemon can be perfectly alive with no lock file. This one exists for the
    whole process lifetime.
    """
    try:
        with open(PID_PATH, "w", encoding="utf-8") as fh:
            fh.write(f'{{"pid": {os.getpid()}, "started": {time.time():.0f}}}\n')
    except Exception:  # noqa: BLE001
        pass


def clear_pid_file():
    try:
        if os.path.exists(PID_PATH):
            os.remove(PID_PATH)
    except Exception:  # noqa: BLE001
        pass


def load_config():
    cfg = dict(DEFAULTS)
    try:
        if os.path.exists(CONFIG_PATH):
            with open(CONFIG_PATH, encoding="utf-8") as fh:
                cfg.update(json.load(fh))
        else:
            # First run: seed from the shipped example if it is there, so the
            # documented comments survive into the user's own copy.
            if os.path.exists(EXAMPLE_CONFIG):
                with open(EXAMPLE_CONFIG, encoding="utf-8") as fh:
                    cfg.update(json.load(fh))
            with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
                json.dump(cfg, fh, indent=2)
            log(f"wrote {CONFIG_PATH} (seeded from config.example.json)")
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
        self._warned_clamp = False
        self._warned_big_fit = False
        self._last_read_at = 0.0
        self.fun = bool(cfg.get("fun", False))
        self._tick = 0

    # -- data ---------------------------------------------------------
    def _open_sensors(self):
        from sensors import LhmSensors, is_admin
        if not is_admin():
            log("WARNING: not elevated -- CPU temp and fan RPM will read 0. "
                "Install with INSTALL_STARTUP.bat so the task runs with highest privileges.")
        self.sensors = LhmSensors(self.cfg.get("dll"))
        t = self.sensors.pick_temp(self.cfg.get("temp"))
        f = self.sensors.pick_fan(self.cfg.get("fan"))
        log(f"sensors via {self.sensors.dll_path}")
        log(f"temp sensor = {t[1] if t else None!r}, fan sensor = {f[1] if f else None!r}")

    def _open_panel(self):
        from aio_screen import AioScreen
        self.screen = AioScreen(fahrenheit=self.cfg.get("fahrenheit", False),
                                role="aio_daemon.pyw",
                                fan_low2_offset=self.cfg.get("fan_low2_offset")).open()
        log(f"panel open, output report {self.screen.output_len} bytes"
            + (f", fan_low2_offset={self.screen.fan_low2_offset}"
               if self.screen.fan_low2_offset else ""))

    def read(self):
        """
        One hardware refresh, then whichever metrics the config asks for.

        A metric that is momentarily missing returns None and the previous
        value is held, rather than substituting something else -- a wrong
        number for one frame is worse than a stale one.
        """
        import metrics

        rows = self.sensors.rows()
        temp_pref, fan_pref = self.cfg.get("temp"), self.cfg.get("fan")
        big_name = self.cfg.get("big", "cpu_temp")
        small_name = self.cfg.get("small", "cpu_fan")

        if not metrics.suits("big", big_name) and not self._warned_big_fit:
            log(f"config big={big_name!r} maxes out around {metrics.typical_max(big_name)}, "
                f"but the big readout only shows 0-{metrics.BIG_MAX}; it will clamp")
            self._warned_big_fit = True

        big_v = metrics.read(rows, big_name, temp_pref, fan_pref)
        small_v = metrics.read(rows, small_name, temp_pref, fan_pref)

        if big_v is None and not self._warned_temp:
            log(f"metric {big_name!r} unavailable; holding last value")
            self._warned_temp = True
        if small_v is None and not self._warned_fan:
            log(f"metric {small_name!r} unavailable; holding last value")
            self._warned_fan = True

        big = int(round(big_v)) if big_v is not None else None
        small = int(round(small_v)) if small_v is not None else None
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

                real_big, real_small = self.read()
                big, small = real_big, real_small
                if self.cfg.get("fahrenheit") and big > 123:
                    big = 123           # the panel's 8-bit F conversion wraps past this
                joke = self.fun_frame()
                if joke is not None:
                    # None in a slot means "leave the real reading there", so a
                    # frame can be silly in one readout and honest in the other.
                    if joke[0] is not None:
                        big = joke[0]
                    if joke[1] is not None:
                        small = joke[1]
                self.screen.send(Stats(cpu_temp=big, cpu_fan=small))
                self.last = (big, small)
                self._last_read_at = time.time()
                self._tick += 1
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

    def fun_frame(self):
        """
        The joke frame for this tick, or None if this tick shows real stats.

        Ticks alternate real / fun / real / next fun, so fun_frames is walked
        one entry per fun tick rather than one per second.
        """
        if not self.fun or self._tick % 2 == 0:
            return None
        frames = self.cfg.get("fun_frames") or DEFAULTS["fun_frames"]
        if not frames:
            return None
        pair = frames[(self._tick // 2) % len(frames)]
        try:
            big = None if pair[0] is None else int(pair[0])
            small = None if pair[1] is None else int(pair[1])
        except Exception:  # noqa: BLE001
            return None
        if big is not None and big > 127 and not self._warned_clamp:
            log(f"fun frame big value {big} exceeds the panel's 7-bit field "
                f"and will display as 127")
            self._warned_clamp = True
        return big, small

    def reading_age(self):
        """Seconds since the last successful read, for the menu's timestamp."""
        return max(0.0, time.time() - self._last_read_at)

    def set_metric(self, slot, name):
        """slot is "big" or "small"."""
        self.cfg[slot] = name
        self._big_hist.clear()
        self._small_hist.clear()
        self._warned_temp = self._warned_fan = False
        self.save_config()
        log(f"{slot} readout -> {name}")

    def save_config(self):
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
                json.dump(self.cfg, fh, indent=2)
        except Exception as e:  # noqa: BLE001
            log(f"could not persist config: {e}")

    def toggle_fun(self):
        self.fun = not self.fun
        self.cfg["fun"] = self.fun
        self._tick = 0                    # restart on a real reading
        self.save_config()
        log(f"fun mode {'ON' if self.fun else 'OFF'}")
        return self.fun

    def reading(self):
        """The current values as one line, e.g. '47 C   1439 rpm'."""
        import metrics

        big, small = self.last
        big_name = self.cfg.get("big", "cpu_temp")
        small_name = self.cfg.get("small", "cpu_fan")
        bu = "F" if (self.cfg.get("fahrenheit") and big_name.endswith("temp")) else \
            metrics.METRICS.get(big_name, ("", "", "", "", ""))[3]
        su = metrics.METRICS.get(small_name, ("", "", "", "", ""))[3]
        return f"{big} {bu}".strip() + "   " + f"{small} {su}".strip()

    def tooltip(self):
        import metrics

        if self.status.startswith("retrying") or self.status.startswith("another"):
            return f"AIO screen - {self.status}"
        big, small = self.last
        big_name = self.cfg.get("big", "cpu_temp")
        small_name = self.cfg.get("small", "cpu_fan")
        bu = "F" if (self.cfg.get("fahrenheit") and big_name.endswith("temp")) else \
            metrics.METRICS.get(big_name, ("", "", "", "", ""))[3]
        su = metrics.METRICS.get(small_name, ("", "", "", "", ""))[3]
        line = f"{big} {bu}".strip() + "   " + f"{small} {su}".strip()
        suffix = "   [fun mode]" if self.fun else ""
        return f"AIO screen\n{line}{suffix}"


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

    import metrics

    image = Image.open(ICON_PATH) if os.path.exists(ICON_PATH) else \
        Image.new("RGB", (32, 32), (69, 196, 255))

    worker = threading.Thread(target=daemon.run, daemon=True)
    worker.start()

    def on_quit(icon, _item):
        daemon.stop.set()
        worker.join(timeout=3)
        icon.stop()

    def on_open_log(_icon, _item):
        if os.path.exists(LOG_PATH):
            os.startfile(LOG_PATH)

    def on_open_config(_icon, _item):
        os.startfile(CONFIG_PATH)

    def on_toggle_fun(icon, _item):
        daemon.toggle_fun()
        icon.update_menu()

    def metric_menu(slot):
        """
        Only what this readout can actually display.

        The big slot is a 7-bit field, so a CPU clock of 5300 MHz would arrive
        as 127 -- offering it is offering a broken choice. metrics.suits()
        filters by each metric's realistic maximum. In the small slot
        everything fits, but values above ~1020 hit the firmware's digit
        corruption, so those are marked rather than hidden.
        """
        def make(name):
            def choose(icon, _item):
                daemon.set_metric(slot, name)
                icon.update_menu()
            label = f"{name}  --  {metrics.describe(name)}"
            if not metrics.exact_in(slot, name):
                label += "   [last digits unreliable]"
            return pystray.MenuItem(
                label, choose,
                checked=lambda _i, n=name: daemon.cfg.get(slot) == n,
                radio=True)

        items = [make(n) for n in metrics.names(slot)]
        if slot == "big":
            items.append(pystray.Menu.SEPARATOR)
            items.append(pystray.MenuItem(
                f"(clocks, power and rpm omitted: this readout is 0-"
                f"{metrics.BIG_MAX})", None, enabled=False))
        return pystray.Menu(*items)

    icon = pystray.Icon(
        "aio_screen", image, "AIO screen",
        menu=pystray.Menu(
            # A Windows tray menu is MODAL: while it is open the shell owns a
            # snapshot of it, and nothing we do can change what is on screen.
            # So this line is the reading as of the moment the menu opened --
            # correct, but frozen until you close and reopen. The refresh loop
            # below rebuilds the menu once a second so that snapshot is always
            # fresh, and the hover tooltip is the place to watch values move.
            pystray.MenuItem(lambda _i: daemon.reading(), None, enabled=False),
            pystray.MenuItem(lambda _i: f"   (as of {time.strftime('%H:%M:%S')}"
                                        f" -- hover the icon for live values)",
                             None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Big readout", metric_menu("big")),
            pystray.MenuItem("Small readout", metric_menu("small")),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Fun mode", on_toggle_fun,
                             checked=lambda _i: daemon.fun),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Edit config.json", on_open_config),
            pystray.MenuItem("Open log", on_open_log),
            pystray.MenuItem("Quit", on_quit),
        ),
    )

    def refresh():
        while not daemon.stop.is_set():
            try:
                icon.title = daemon.tooltip()       # hover text
                icon.update_menu()                  # right-click text
            except Exception:  # noqa: BLE001
                pass
            # Once a second, matching the data rate: the menu cannot update
            # while open, so the best we can do is have a fresh snapshot ready
            # whenever it is opened.
            time.sleep(1)

    threading.Thread(target=refresh, daemon=True).start()
    icon.run()


def main():
    log("=" * 60)
    log(f"starting (python {sys.version.split()[0]}, elevated="
        f"{bool(ctypes.windll.shell32.IsUserAnAdmin())})")
    cfg = load_config()
    daemon = Daemon(cfg)
    write_pid_file()
    try:
        run_tray(daemon)
    except Exception as e:  # noqa: BLE001
        log(f"fatal: {e}\n{traceback.format_exc()}")
    finally:
        clear_pid_file()
        log("exited")


if __name__ == "__main__":
    main()
