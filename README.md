# aio_screen

Drive the little round LCD on an AIO cooler's pump cap from Python, instead of
leaving the vendor's "PC Monitor" app running.

Works with the USB HID panel that identifies as **`5131:2007`** — the display
bundled with coolers whose software is *PC Monitor* (`C:\Program Files (x86)\PC
Monitor`, a Qt5 app by Witmod). These panels are sold under several brands.

No third-party packages are needed to talk to the panel: HID access goes
through Windows' own `setupapi`/`hid.dll` via `ctypes`.

## What the hardware can and cannot do

Set expectations before you invest time here. This is **not** a screen you can
draw on. The panel renders its own fixed layout in firmware; the host just
posts a table of numbers over USB HID about once a second. On the round pump
cap that means exactly **two readouts**:

- a **big number**, 0–127, with a degree mark
- a **small number** beside a fan icon, 0–65535

Neither slot cares what its protocol field is called — the big one is just a
byte the firmware prints. So the freedom you get is *choosing what those two
numbers say*, not designing a layout. There is no framebuffer, no image
stream, no fonts, no colours.

The protocol carries fourteen values (CPU/GPU temp, load, clock, fan, power,
memory, disk, date, time) because the vendor's larger panels use them. On this
one, twelve of them do nothing. See [FINDINGS.md](FINDINGS.md).

## Install

```
INSTALL.bat
```

That installs the Python packages, downloads `LibreHardwareMonitorLib.dll`
from the LibreHardwareMonitor project's own releases (it is MPL-2.0 and not
bundled here — if the vendor app is installed, its existing copy is used
instead), and finishes by running the environment check.

By hand, if you prefer: `pip install -r requirements.txt`. Driving the panel
needs no packages at all; they are for the demo, the sensor reading and the
tray icon.

**`RUN_DOCTOR.bat` tells you exactly what is missing** — Python version and
bitness, each package and what it is for, whether the DLL was found and where
it looked, whether the panel is present and accepts a 64-byte report, whether
something else is already driving it, and whether the autostart task exists.
Every failure prints the command that fixes it.

Close the vendor "PC Monitor" app first — the `RUN_*.bat` wrappers do it for
you. Two writers do not error out, they interleave frames.

## Quick start

```
RUN_TEST.bat        list HID devices, then post a test frame
RUN_DEMO.bat        live stats: GPU temp big, GPU fan RPM small
python demo_stats.py --list                 what can go in each slot
python demo_stats.py --big cpu_load         CPU load % in the big readout
```

```python
from aio_screen import AioScreen, Stats

with AioScreen() as screen:
    screen.send(Stats(cpu_temp=42, cpu_fan=1200))
```

`cpu_temp` is the big number (clamped to 0–127), `cpu_fan` the small one.

`AioScreen(fahrenheit=True)` sets bit 7, which makes the **panel** convert with
`v*1.8+32`. Two measured firmware quirks come with it: `0` displays as `128`,
and the arithmetic wraps at 8 bits so inputs above `123` are nonsense (`127`
shows as `4`). The default — bit clear — displays your number exactly.

## Run it in the background

```
INSTALL_STARTUP.bat      start at logon, elevated, plus a desktop shortcut
UNINSTALL_STARTUP.bat    remove it
CREATE_SHORTCUT.bat      just the desktop shortcut
START_NOW.bat            run once without installing
```

`aio_daemon.pyw` posts CPU temperature and fan RPM at 1 Hz with no console
window and sits in the system tray — hover for live values, right-click for
config, log, or quit. Settings live in `config.json` (copied from
`config.example.json` on first run); problems go to `aio_daemon.log`.

### Fun mode

Toggle it from the tray icon. The panel alternates second by second, with the
**temperature left real throughout** — only the fan slot goes silly:

```
1s  47 C / 1439 rpm       3s  47 C / 1439 rpm
2s  47 C / 8008 rpm       4s  47 C /  420 rpm     ... and loops
```

Each entry in `fun_frames` is a `[big, small]` pair and **`null` keeps the
real reading** for that slot. The defaults only touch the fan because the big
readout is drawn with a degree mark: a joke number there reads as a plausible
temperature rather than as a joke, and you cannot tell at a glance whether the
panel is being honest. Keeping it real means the one number worth acting on is
never faked, while 8008 rpm is unmistakable nonsense.

Put a number in the first slot — `[69, 8008]` — if you do want to fake the
temperature too. It is a 7-bit field, so anything above 127 displays as 127.

**Why a scheduled task rather than a Startup shortcut:** reading CPU
temperature needs administrator rights, and a shortcut would fire a UAC prompt
on every boot. A Task Scheduler entry with *run with highest privileges* holds
the elevation itself, so it starts silently — and the desktop shortcut goes
through that same task, so restarting after a Quit needs no prompt either.

## Reading CPU temperature and fan RPM

Windows exposes neither to an ordinary process: both live behind the SuperIO
chip and MSR registers, which need a kernel driver. That is why the vendor app
ships one (`PC_Monitor.sys`).

This project does not install any driver. It loads
**[LibreHardwareMonitor](https://github.com/LibreHardwareMonitor/LibreHardwareMonitor)**'s
library through pythonnet and lets it do the work — the same library the
vendor app already bundles, so on a machine with PC Monitor installed the DLL
is present at
`C:\Program Files (x86)\PC Monitor\LibreHardwareMonitorLib.dll`. Point
`--dll`/`config.json` elsewhere if you have your own copy. This still requires
running elevated, because the library's driver does.

Prefer not to run elevated? Run the LibreHardwareMonitor GUI with its web
server enabled and use `--lhm http://localhost:8085/data.json` instead.

### The fan slot does not display what you send

Sending `8008` puts **`8028`** on the glass. The firmware draws the value as
two independent decimal fields — everything above the last two digits, and the
last two digits — and the second one is offset by +20 (mod 100), with no carry
into the hundreds. So `7996` shows as `7916`.

But that offset does **not** apply below 1000: `4` displays as `4` and `420`
as `420`. So the correction (`fan_low2_offset` in `config.json`) ships
**disabled** — enabling it fixes 8008 and breaks 420.

`RUN_FAN_MAP.bat` walks ten values across the whole range to establish where
the behaviour changes.

`RUN_FAN_CALIBRATE.bat` is the fuller version — 15 values from 100 to 65535 —
if you want the actual shape of the mapping rather than one corrected point.

### Sensor names are board-specific — check yours

**`RUN_SENSORS.bat`** lists every sensor with an index and value. Match them
against your motherboard's own utility, then set `temp` and `fan` in
`config.json`. Both accept a name, part of a name, or `#index`.

This matters more than it sounds. On the machine this was developed on
(Gigabyte Z790 D AX, ITE IT8689E, i7-14700KF):

| LHM sensor | rpm | actually is |
|---|---|---|
| `Fan #1` | 1439 | CPU header ✅ |
| `Fan #2`, `#3` | 0 | empty headers |
| `Fan #4` | 1397 | a case fan |
| `Fan #5` | 2556 | CPU_OPT — **the pump** |

Naive heuristics pick wrong: "fastest fan" gets the pump, "slowest spinning"
gets a case fan. Name the one you want. If a named sensor goes missing from a
refresh the daemon **holds the previous value** rather than silently
substituting a different sensor — that used to flash a stray high number onto
the panel for one frame.

On temperature, `CPU Package` is the on-die DTS: correct, and genuinely spiky
(it swung 44→68 °C between samples here). It will **not** agree with your
board vendor's utility, which shows the motherboard's socket probe — a
different physical sensor, slower and cooler. Neither is wrong. For a calmer
readout use `"temp": "Core Average"`, and `"smooth"` takes a median over the
last N samples.

## Only one writer at a time

The panel has no arbitration: any process that opens it can post, and the last
frame wins. Two writers interleave rather than erroring, which looks like the
display updating twice a second with one wrong reading.

Every script here takes an exclusive lock inside `AioScreen.open()`. A second
one refuses and names the holder:

```
The panel is already being driven by aio_daemon.pyw (pid 4242, running 1h01m).
    That is the background daemon. Quit it from the tray icon,
    or run UNINSTALL_STARTUP.bat, then try again.
    To run anyway (they WILL fight): set AIO_FORCE=1
```

A lock left by a crash is detected and taken over. `RUN_WHO.bat` lists every
process that could be posting.

## If your panel is a different model

The wire format is the vendor's, so other panels in the family should accept
the same packets — but which fields they render, and where, will differ. The
tools that worked it out are included:

- `list_hid.py` — every HID interface, with report lengths
- `identify.py` — sets each field to its own index, so the panel maps itself
- `probe_display.py` — counting ramps, one field at a time: a readout that
  ticks along is yours, one that sits still is not
- `calibrate_temp.py` — self-paced walk that produced the temperature table
- `sensors.py` — run directly (elevated) to list every hardware sensor

## Files

| File | Purpose |
|---|---|
| `aio_screen.py` | the driver — `Stats`, `build_report`, `AioScreen` |
| `winhid.py` | dependency-free Windows HID access via ctypes |
| `panel_lock.py` | single-writer enforcement |
| `sensors.py` | CPU temp and fan RPM via LibreHardwareMonitor |
| `aio_daemon.pyw` | background tray app |
| `demo_stats.py` | live demo; `--big`/`--small` choose each readout |
| `start_panel.vbs` | what the desktop shortcut runs |
| `doctor.py` | environment check: what is missing and how to fix it |
| `install.ps1` | packages + downloads the sensor DLL |

## How this was worked out

`PC_Monitor.exe` is a mixed-mode C++/CLI assembly, so its logic compiles to
.NET IL rather than x86 — parsing its CLR metadata gave something close to
source. The device IDs came out of its own enumeration loop, the packet layout
out of the method that builds it, and every field was then confirmed against
the hardware. Full write-up, including the calibration table, the two firmware
quirks and the dead ends, in [FINDINGS.md](FINDINGS.md).

This is a clean-room-ish interoperability reimplementation: no vendor code is
included or redistributed here, only a description of the wire format.

## Notes and limits

- **Windows only.** The HID layer is Win32-specific. The protocol is not, so a
  Linux port would mainly mean swapping `winhid.py` for `hidraw`.
- **Display only.** Nothing here sends anything that could change pump or fan
  behaviour — the cooler's own controller is untouched. Whether any field in
  the protocol affects cooling was never investigated, deliberately.
- **Not affiliated** with the vendor, Witmod, or any cooler brand.

## Licence

MIT — see [LICENSE](LICENSE).

LibreHardwareMonitor is MPL-2.0 and is *not* bundled here; it is loaded at
runtime from wherever you point it.
