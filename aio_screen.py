"""
aio_screen.py
=============

Driver for the AIO cooler's LCD, as spoken by the vendor "PC Monitor"
app (C:\\Program Files (x86)\\PC Monitor).

This panel is NOTHING like the Hongtai case screen. There is no image
stream and no framebuffer: the panel renders its own fixed layout in
firmware, and the host just posts it a table of numbers ~once a second.
So "drawing" here means choosing what the readouts SAY, not what the
screen looks like.

Transport
---------
USB HID, VID 0x5131 PID 0x2007, one 64-byte OUTPUT report per update.
Write-only -- the vendor app never calls hid_read, only hid_write, so
the panel never talks back. There is no handshake and no ack: you open
the device and start posting reports.

Report layout (the byte before payload[0] is the HID report ID, 0x00)
--------------------------------------------------------------------
    off  size  field                          [*] = used by the pump-cap model
      0    1   0x40    constant header/marker
  [*] 1    1   CPU temperature      (bit 7 = "convert to F", see below)
      2    1   CPU load %
      3    2   CPU clock MHz        big-endian
  [*] 5    2   CPU fan RPM          big-endian
      7    2   CPU power W          big-endian
      9    1   GPU temperature
     10    1   GPU load %
     11    2   GPU core clock MHz   big-endian
     13    2   GPU fan RPM          big-endian
     15    2   GPU power W          big-endian
     17    1   memory load %
     18    2   total RAM in MB      big-endian
     20    1   disk usage %
     21    2   total disk in GB     big-endian
     23    2   year                 big-endian
     25    1   month
     26    1   day
     27    1   hour
     28    1   minute
     29    1   checksum: sum of payload[0..28] & 0xFF
     30+       zero padding out to 64 bytes

All multi-byte values are BIG-endian (high byte first) -- the vendor
writes them as `buf[n] = v >> 8; buf[n+1] = (byte)v`.

The 0x80 temperature bit -- MEASURED, not guessed
-------------------------------------------------
Bit 7 of a temperature byte tells the panel to convert to Fahrenheit
ITSELF. It is the opposite of what the vendor's radio-button code first
suggested. Calibrated against the hardware:

    bit CLEAR   the panel displays the byte exactly as sent
                0->0, 1->1, 25->25, 50->50, 100->100, 127->127
    bit SET     the panel displays v*1.8+32, computed in 8 bits
                0->128 (!), 1->33, 25->77, 50->122, 100->212, 127->4

Two firmware quirks fall out of that table:

  * value 0 with the bit SET displays 128 -- the raw byte, unconverted.
    The conversion appears to be skipped when the low 7 bits are zero.
  * the conversion wraps at 8 bits: 127 -> 127*1.8+32 = 260 -> 260 & 0xFF
    = 4, which is exactly what the panel showed. So with the bit set the
    usable input range stops at 123 (123*1.8+32 = 253).

Hence the default here is bit CLEAR, which makes the big readout an exact
0-127 number you fully control. Pass fahrenheit=True only if you want the
panel to do the conversion for you.

No third-party packages needed: HID access goes through Windows' own
setupapi/hid.dll via ctypes (see winhid.py). The obvious `pip install
hidapi` route does NOT work here -- that wheel ships no native library and
the vendor's hidapi.dll is 32-bit against a 64-bit Python.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import Optional

import winhid
from panel_lock import PanelLock, PanelBusy   # noqa: F401  (re-exported)

VENDOR_ID = 0x5131
PRODUCT_ID = 0x2007
REPORT_LEN = 64
HEADER = 0x40


class AioScreenError(RuntimeError):
    pass


# What this particular panel actually renders. The protocol carries 14
# values because the vendor's larger screens use them; this round pump cap
# reads exactly two, verified field by field against the hardware.
USED_BY_PUMP_CAP = ("cpu_temp", "cpu_fan")


@dataclass
class Stats:
    """
    Everything the protocol carries.

    On the round pump-cap display only cpu_temp (the big number) and cpu_fan
    (the small number by the fan icon) are rendered -- every other field was
    tested and does nothing. They are kept because they are part of the wire
    format and the vendor's bigger panels do use them.

    Nothing forces these to hold what their names say: cpu_temp is simply
    "the big number, 0-127" and cpu_fan is "the small number, 0-65535". Put
    whatever you like in them.
    """
    cpu_temp: int = 0          # degrees, 0-127
    cpu_load: int = 0          # %
    cpu_clock: int = 0         # MHz
    cpu_fan: int = 0           # RPM
    cpu_power: int = 0         # W
    gpu_temp: int = 0
    gpu_load: int = 0
    gpu_clock: int = 0
    gpu_fan: int = 0
    gpu_power: int = 0
    mem_load: int = 0          # %
    mem_total_mb: int = 0      # MB
    disk_load: int = 0         # %
    disk_total_gb: int = 0     # GB
    when: Optional[datetime.datetime] = None   # defaults to now


def _u8(v) -> int:
    return max(0, min(255, int(v)))


def _temp(v) -> int:
    """Temperatures occupy 7 bits -- bit 7 is the unit flag, not data."""
    return max(0, min(127, int(v)))


def _be16(v) -> tuple:
    v = max(0, min(0xFFFF, int(v)))
    return (v >> 8) & 0xFF, v & 0xFF


def build_report(s: Stats, fahrenheit: bool = False) -> bytes:
    """
    Build the 64-byte payload (without the leading HID report ID).

    fahrenheit=False (default): temperatures are shown exactly as given.
    fahrenheit=True: bit 7 is set and the PANEL converts to F itself --
    see the module docstring for the two quirks that come with that.
    """
    b = bytearray(REPORT_LEN)
    t = s.when or datetime.datetime.now()
    flag = 0x80 if fahrenheit else 0x00

    b[0] = HEADER
    b[1] = _temp(s.cpu_temp) | flag
    b[2] = _u8(s.cpu_load)
    b[3], b[4] = _be16(s.cpu_clock)
    b[5], b[6] = _be16(s.cpu_fan)
    b[7], b[8] = _be16(s.cpu_power)
    b[9] = _temp(s.gpu_temp) | flag
    b[10] = _u8(s.gpu_load)
    b[11], b[12] = _be16(s.gpu_clock)
    b[13], b[14] = _be16(s.gpu_fan)
    b[15], b[16] = _be16(s.gpu_power)
    b[17] = _u8(s.mem_load)
    b[18], b[19] = _be16(s.mem_total_mb)
    b[20] = _u8(s.disk_load)
    b[21], b[22] = _be16(s.disk_total_gb)
    b[23], b[24] = _be16(t.year)
    b[25] = _u8(t.month)
    b[26] = _u8(t.day)
    b[27] = _u8(t.hour)
    b[28] = _u8(t.minute)
    b[29] = sum(b[0:29]) & 0xFF
    return bytes(b)


def list_devices():
    """Every HID interface present, so a missing panel is obvious."""
    return winhid.enumerate_devices()


def find_panel():
    """
    Interfaces matching the panel's VID/PID.

    A device often exposes several HID collections and only some accept
    output reports, so anything that can actually take a 64-byte report is
    sorted first.
    """
    hits = [d for d in winhid.enumerate_devices()
            if d["vendor_id"] == VENDOR_ID and d["product_id"] == PRODUCT_ID]
    hits.sort(key=lambda d: (d.get("output_len", 0) < REPORT_LEN + 1,
                             -d.get("output_len", 0)))
    return hits


class AioScreen:
    def __init__(self, path: Optional[bytes] = None, fahrenheit: bool = False,
                 role: str = "", exclusive: bool = True):
        self.path = path
        self.fahrenheit = fahrenheit
        self._dev = None
        self.output_len = 0
        # Exactly one process may drive the panel: it has no arbitration, so
        # two writers silently interleave frames instead of erroring.
        self._lock = PanelLock(role) if exclusive else None

    def open(self):
        if self._lock is not None:
            self._lock.acquire()          # raises PanelBusy, naming the holder
        candidates = find_panel()
        if not candidates:
            if self._lock is not None:
                self._lock.release()
            raise AioScreenError(
                f"no HID device with VID 0x{VENDOR_ID:04X} PID 0x{PRODUCT_ID:04X}. "
                f"Is the AIO's USB header plugged in? Run list_hid.py to see what IS present."
            )
        chosen = candidates[0]
        path = self.path or chosen["path"]
        try:
            self._dev = winhid.Device(path, chosen.get("output_len", 0))
        except OSError as e:
            if self._lock is not None:
                self._lock.release()
            raise AioScreenError(
                f"could not open the panel: {e}. Close the vendor 'PC Monitor' app and retry."
            )
        self.path = path
        self.output_len = self._dev.output_len
        return self

    def send(self, stats, fahrenheit: Optional[bool] = None):
        """
        Post one frame. `stats` is normally a Stats; a raw 64-byte payload is
        also accepted so calibration tools can bypass the encoder.
        """
        if not self._dev:
            raise AioScreenError("not open -- call open() first")
        if isinstance(stats, (bytes, bytearray)):
            payload = bytes(stats)
        else:
            flag = self.fahrenheit if fahrenheit is None else fahrenheit
            payload = build_report(stats, flag)
        # The report ID goes first; this panel uses 0 (no numbered reports).
        try:
            return self._dev.write(b"\x00" + payload)
        except OSError as e:
            raise AioScreenError(str(e))

    def close(self):
        if self._dev:
            try:
                self._dev.close()
            except Exception:  # noqa: BLE001
                pass
            self._dev = None
        if self._lock is not None:
            self._lock.release()

    def __enter__(self):
        return self.open()

    def __exit__(self, *exc):
        self.close()
