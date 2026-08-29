"""
panel_lock.py -- exactly one process may drive the panel at a time.

The panel has no arbitration of its own: any process that opens the HID
device can post a frame, and the last frame posted wins. Two writers do not
error out, they interleave -- which is why a leftover demo window plus the
daemon looked like "it updates twice a second and one frame is wrong".

So the exclusion has to live on our side, and it has to cover EVERY script
here rather than just the daemon. This module is acquired inside
AioScreen.open(), so anything that opens the panel participates for free.

How it decides:

  * a named mutex makes the check atomic against two processes starting at
    the same instant
  * a lock file records WHO holds it (pid, script, start time, elevated),
    so the second process can print something useful instead of "busy"
  * liveness is verified with OpenProcess, so a lock left behind by a crash
    is detected and taken over rather than blocking forever

The mutex alone is not enough: the daemon runs elevated, and a normal-rights
process cannot open an elevated process's Global object -- it gets
ACCESS_DENIED, which is itself proof that someone holds it. Both signals are
used.
"""

from __future__ import annotations

import ctypes
import json
import os
import sys
import time
from ctypes import wintypes

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

ERROR_ALREADY_EXISTS = 183
ERROR_ACCESS_DENIED = 5
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

MUTEX_NAME = "aio_screen_panel"
LOCK_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "panel.lock")

kernel32.CreateMutexW.restype = wintypes.HANDLE
kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]


class PanelBusy(RuntimeError):
    """Raised when another process already holds the panel."""

    def __init__(self, holder: dict | None):
        self.holder = holder or {}
        super().__init__(self.describe())

    def describe(self) -> str:
        h = self.holder
        if not h:
            return ("Another process is already driving the panel.\n"
                    "    Run RUN_WHO.bat to see which one.")
        age = ""
        if h.get("started"):
            secs = int(time.time() - h["started"])
            age = f", running {secs // 3600}h{(secs // 60) % 60:02d}m" if secs > 3600 \
                else f", running {secs // 60}m{secs % 60:02d}s"
        who = h.get("script") or "unknown script"
        line = (f"The panel is already being driven by {who} "
                f"(pid {h.get('pid')}{age}).\n")
        if "aio_daemon" in str(who):
            line += ("    That is the background daemon. Quit it from the tray icon,\n"
                     "    or run UNINSTALL_STARTUP.bat, then try again.")
        else:
            line += ("    Close that window first -- two writers interleave frames\n"
                     "    and you get alternating readings.")
        line += "\n    To run anyway (they WILL fight): set AIO_FORCE=1"
        return line


def _pid_alive(pid: int) -> bool:
    if not pid:
        return False
    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
    if h:
        kernel32.CloseHandle(h)
        return True
    # ACCESS_DENIED means it exists but is more privileged than us.
    return ctypes.get_last_error() == ERROR_ACCESS_DENIED


def _read_lock() -> dict | None:
    try:
        with open(LOCK_PATH, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:  # noqa: BLE001
        return None


def _write_lock(role: str):
    try:
        with open(LOCK_PATH, "w", encoding="utf-8") as fh:
            json.dump({
                "pid": os.getpid(),
                "script": role or os.path.basename(sys.argv[0] or "python"),
                "started": time.time(),
                "elevated": bool(ctypes.windll.shell32.IsUserAnAdmin()),
            }, fh)
    except Exception:  # noqa: BLE001
        pass


class PanelLock:
    """Hold this for as long as you are posting frames."""

    def __init__(self, role: str = ""):
        self.role = role or os.path.basename(sys.argv[0] or "python")
        self._handle = None
        self._held = False

    def acquire(self, force: bool = False):
        if force or os.environ.get("AIO_FORCE") == "1":
            self._held = False
            return self

        holder = _read_lock()
        if holder and holder.get("pid") != os.getpid() and _pid_alive(holder.get("pid", 0)):
            raise PanelBusy(holder)

        for prefix in ("Global\\", "Local\\"):
            handle = kernel32.CreateMutexW(None, False, prefix + MUTEX_NAME)
            err = ctypes.get_last_error()
            if handle and err == ERROR_ALREADY_EXISTS:
                kernel32.CloseHandle(handle)
                raise PanelBusy(_read_lock())
            if not handle and err == ERROR_ACCESS_DENIED:
                # Exists and is owned by a more privileged process: the daemon.
                raise PanelBusy(_read_lock())
            if handle:
                self._handle = handle
                self._held = True
                _write_lock(self.role)
                return self
        # Could not create any mutex; the lock file check above already ran, so
        # allow the run rather than blocking on an unexplained API failure.
        _write_lock(self.role)
        return self

    def release(self):
        if self._handle:
            kernel32.CloseHandle(self._handle)
            self._handle = None
        if self._held:
            try:
                holder = _read_lock()
                if holder and holder.get("pid") == os.getpid():
                    os.remove(LOCK_PATH)
            except Exception:  # noqa: BLE001
                pass
            self._held = False

    def __enter__(self):
        return self.acquire()

    def __exit__(self, *exc):
        self.release()
