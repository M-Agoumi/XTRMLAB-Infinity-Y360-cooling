"""
doctor.py -- check this machine has everything the project needs, and say
exactly what is missing and how to fix it.

Run it first, or any time something does not work:

    python doctor.py          (elevated, for the full picture)

Every check prints OK / MISSING / WARN with a one-line fix. Exit code is the
number of hard failures, so a .bat can branch on it.
"""

from __future__ import annotations

import ctypes
import importlib
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

OK, BAD, WARN = "  OK   ", " MISSING", " WARN  "


class Check:
    def __init__(self):
        self.failures = 0
        self.warnings = 0

    def ok(self, name, detail=""):
        print(f"[{OK}] {name}" + (f"  --  {detail}" if detail else ""))

    def bad(self, name, detail, fix):
        self.failures += 1
        print(f"[{BAD}] {name}  --  {detail}")
        print(f"          fix: {fix}")

    def warn(self, name, detail, fix=""):
        self.warnings += 1
        print(f"[{WARN}] {name}  --  {detail}")
        if fix:
            print(f"          fix: {fix}")


def main():
    c = Check()
    print("=" * 72)
    print(" aio_screen environment check")
    print("=" * 72)

    # --- python ---------------------------------------------------------
    v = sys.version_info
    if v >= (3, 8):
        c.ok("Python", f"{v.major}.{v.minor}.{v.micro} "
                       f"({'64' if sys.maxsize > 2**32 else '32'}-bit)")
    else:
        c.bad("Python", f"{v.major}.{v.minor} is too old", "install Python 3.8 or newer")

    if sys.platform != "win32":
        c.bad("Platform", f"{sys.platform}", "this project is Windows-only (winhid.py uses Win32)")
        print()
        return c.failures

    # --- admin ----------------------------------------------------------
    try:
        elevated = bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:  # noqa: BLE001
        elevated = False
    if elevated:
        c.ok("Administrator", "elevated")
    else:
        c.warn("Administrator", "not elevated",
               "CPU temp and fan RPM will read 0. Use RUN_CPU_DEMO.bat or "
               "INSTALL_STARTUP.bat, which elevate for you.")

    # --- packages -------------------------------------------------------
    print()
    frozen = bool(getattr(sys, "frozen", False))
    if frozen:
        print("  (running from the bundled .exe -- its libraries are built in)")

    # required = the app cannot work without it. optional = only the extra
    # command-line scripts use it, and those are not part of the .exe, so a
    # missing one is not a fault when frozen.
    needed = {
        "clr":     ("pythonnet", True,  "CPU temp + fan RPM"),
        "pystray": ("pystray",   True,  "tray icon"),
        "PIL":     ("pillow",    True,  "tray icon rendering"),
        "psutil":  ("psutil",    False, "demo_stats.py only"),
    }
    for mod, (pip_name, required, why) in needed.items():
        try:
            if mod == "clr":
                try:
                    from pythonnet import load as _load
                    _load("netfx")
                except Exception:  # noqa: BLE001
                    pass
            importlib.import_module(mod)
            c.ok(f"package {pip_name}", why)
        except ImportError:
            if required:
                c.bad(f"package {pip_name}", f"not installed; needed for {why}",
                      f"pip install {pip_name}   (or run INSTALL.bat)")
            elif frozen:
                c.ok(f"package {pip_name}", f"not bundled -- not needed ({why})")
            else:
                c.warn(f"package {pip_name}", f"not installed; only affects {why}",
                       f"pip install {pip_name}")

    # --- the sensor library --------------------------------------------
    print()
    try:
        from sensors import find_dll, DLL_CANDIDATES
        dll = find_dll()
        if dll:
            c.ok("LibreHardwareMonitorLib.dll", dll)
        else:
            c.bad("LibreHardwareMonitorLib.dll", "not found in any known location",
                  "run INSTALL.bat to download it (it is not bundled -- MPL-2.0), "
                  "or set \"dll\" in config.json")
            for cand in DLL_CANDIDATES:
                print(f"                looked in: {cand}")
    except Exception as e:  # noqa: BLE001
        c.bad("sensors.py", f"could not import ({e})", "check the files are all present")

    # --- the panel itself ----------------------------------------------
    print()
    try:
        from aio_screen import VENDOR_ID, PRODUCT_ID, REPORT_LEN, find_panel, list_devices
        total = len(list_devices())
        hits = find_panel()
        if hits:
            usable = [h for h in hits if h.get("output_len", 0) >= REPORT_LEN + 1]
            detail = f"{VENDOR_ID:04X}:{PRODUCT_ID:04X} on {len(hits)} interface(s)"
            if usable:
                c.ok("AIO panel", detail + f", {len(usable)} accept {REPORT_LEN}-byte reports")
            else:
                c.warn("AIO panel", detail + ", but none report a long enough output report",
                       "run list_hid.py and send the out= values")
        else:
            c.bad("AIO panel", f"no HID device {VENDOR_ID:04X}:{PRODUCT_ID:04X} "
                               f"among {total} HID interfaces",
                  "check the cooler's USB header is plugged in; run list_hid.py to see "
                  "what IS present")
    except Exception as e:  # noqa: BLE001
        c.bad("HID access", f"{e}", "check winhid.py is present")

    # --- is something else driving it? ----------------------------------
    try:
        from panel_lock import PanelLock, PanelBusy
        try:
            lock = PanelLock("doctor.py").acquire()
            lock.release()
            c.ok("Panel is free", "nothing else is driving it")
        except PanelBusy as busy:
            holder = (busy.holder or {}).get("script") or "an unknown process"
            pid = (busy.holder or {}).get("pid")
            # Our own daemon holding the panel is the normal, healthy state --
            # reporting it as a problem sends people looking for a fault.
            if "aio_daemon" in str(holder) or "AIO Screen" in str(holder):
                c.ok("Panel in use", f"by our own daemon ({holder}, pid {pid}) -- expected")
            else:
                c.warn("Panel in use", f"held by {holder} (pid {pid})",
                       "close it -- two writers interleave frames. "
                       "If it is the vendor app, run DISABLE_PC_MONITOR.bat")
    except Exception:  # noqa: BLE001
        pass

    # --- autostart ------------------------------------------------------
    try:
        r = subprocess.run(["schtasks", "/Query", "/TN", "AIO_Screen"],
                           capture_output=True, text=True, timeout=15)
        if r.returncode == 0:
            c.ok("Autostart task", "'AIO_Screen' is registered")
        else:
            c.warn("Autostart task", "'AIO_Screen' is not registered",
                   "run INSTALL_STARTUP.bat if you want it at logon")
    except Exception:  # noqa: BLE001
        pass

    print()
    print("=" * 72)
    if c.failures:
        print(f" {c.failures} thing(s) need fixing"
              + (f", {c.warnings} warning(s)" if c.warnings else ""))
        if not getattr(sys, "frozen", False):
            print(" INSTALL.bat handles the packages and the DLL automatically.")
    elif c.warnings:
        print(f" Ready, with {c.warnings} warning(s) above.")
    else:
        print(" Everything checks out.")
    print("=" * 72)
    return c.failures


if __name__ == "__main__":
    raise SystemExit(main())
