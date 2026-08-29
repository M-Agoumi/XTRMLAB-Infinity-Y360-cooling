# aio_screen — custom driver for the AIO pump-cap display

**Working and verified on hardware.** Both readouts on the cooler's round
display are under your control, driven from Python with no third-party
packages.

This replaces the vendor "PC Monitor" app (`C:\Program Files (x86)\PC
Monitor`). The protocol was read out of that app's own bytecode — it is a
mixed-mode C++/CLI assembly, so its logic decompiles to .NET IL rather than
x86. See FINDINGS.md for the full derivation.

## What this hardware is

A round pump-cap display with exactly **two readouts**:

- a **big number**, 0–127, with a degree mark
- a **small number** beside a fan icon, 0–65535

There is no framebuffer and no image stream. The panel renders its own fixed
layout in firmware; the host posts a table of numbers over USB HID about once
a second. So "custom content" here means **choosing what those two numbers
say** — not designing a layout. Neither slot cares what its protocol field is
named: the big one is just a byte the firmware prints.

- Transport: USB HID, VID `0x5131` PID `0x2007`, one 64-byte output report
- Write-only: the panel never replies, there is no handshake, nothing to wedge
- The panel holds the last posted frame, then fades after a few seconds of
  silence — it has no idle screen of its own

## Setup

```
pip install psutil     # only for demo_stats.py; HID access needs nothing
```

Close the vendor "PC Monitor" app first — the `RUN_*.bat` wrappers do it for
you.

## Try it

```
RUN_TEST.bat          lists HID devices, then posts a test frame
RUN_DEMO.bat          live stats: GPU temp big, GPU fan RPM small
python demo_stats.py --list                    what you can put in each slot
python demo_stats.py --big cpu_load            CPU load % in the big readout
python demo_stats.py --big gpu_temp --small clock_hhmm
```

## Library quick reference

```python
from aio_screen import AioScreen, Stats

with AioScreen() as screen:                 # finds and opens the panel
    screen.send(Stats(cpu_temp=42, cpu_fan=1200))
```

`cpu_temp` is the big number (clamped to 0–127), `cpu_fan` the small one.
Every other field of `Stats` is part of the wire format but does nothing on
this panel — they are read by the vendor's larger screens.

`AioScreen(fahrenheit=True)` sets bit 7, which makes the **panel** convert
the big number with `v*1.8+32`. Two measured quirks come with it: `0`
displays as `128`, and the arithmetic wraps at 8 bits so inputs above `123`
are nonsense (`127` displays as `4`). The default, bit clear, displays your
number exactly and is almost always what you want.

## A note on CPU temperature

Windows does not expose CPU temperature to an ordinary process — that is
precisely why the vendor app ships a kernel driver (`PC_Monitor.sys`). So the
demo defaults to **GPU** temperature, which `nvidia-smi` gives up freely.

For real CPU temp without loading a kernel driver, run LibreHardwareMonitor
with its web server enabled and point the demo at it:

```
python demo_stats.py --lhm http://localhost:8085/data.json --big cpu_temp
```

## Diagnostics

Kept because they are what cracked this, and they re-derive it quickly if a
future firmware or a different panel behaves differently:

- `list_hid.py` — every HID interface, panel flagged, with report lengths
- `identify.py` — sets each field to its own index, so the panel maps itself
- `probe_display.py` — counting ramps one field at a time; a readout that
  ticks along is yours, one that sits still is not
- `calibrate_temp.py` — self-paced walk that produced the temperature table

## Status

Verified end to end. Field mapping and the temperature encoding were measured
against the hardware, not inferred. FINDINGS.md records the protocol, the
calibration table, the two firmware quirks, and the dead ends — including one
hypothesis (that the big number was the pump's own coolant sensor) that the
data disproved.
