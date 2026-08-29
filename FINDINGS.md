# AIO pump-cap display — Findings

> Interoperability notes. Everything here is a *description* of a wire format,
> derived from the vendor application's own bytecode in order to make hardware
> already owned work with software of the owner's choosing. No vendor code is
> reproduced or redistributed.

**Status: solved and verified on hardware (29 Aug 2026).** Both readouts are
under host control, and the temperature encoding is calibrated rather than
guessed.

## The device

| | |
|---|---|
| Vendor app | `C:\Program Files (x86)\PC Monitor\PC_Monitor.exe` (Qt5, mixed-mode C++/CLI) |
| Transport | **USB HID**, VID `0x5131` PID `0x2007` |
| Direction | write-only — the app never calls `hid_read` |
| Report | one 64-byte OUTPUT report, report ID `0x00` |
| Display | round pump cap: one big number (0–127) + one small number by a fan icon |

Nothing here resembles the Hongtai case screen. There is no image stream and
no framebuffer: the panel renders its own layout in firmware and the host
just posts a table of numbers about once a second.

## How it was found

`PC_Monitor.exe` is a mixed-mode assembly — the app's own logic compiles to
.NET IL, not x86, so parsing its CLR metadata gave something close to source.

`MainHidInterFace.getuUsbHidDeviceList` calls `hid_enumerate(0,0)` and walks
the result comparing `+4` against `20785` and `+6` against `8199`. Those are
`vendor_id`/`product_id` in hidapi's `hid_device_info`, hence **5131:2007**.

`DMainWidget.onGetPcInfoOk` builds the packet byte by byte, and each value
was traced back to its source (`Monitor::get_SetOrGet_Cpu_Clock`,
`GlobalMemoryStatusEx.dwMemoryLoad`, `ullTotalPhys * 2^-20` for RAM-in-MB,
`size >> 30` for disk-in-GB).

## Wire format

```
off  size  field                                   [*] = rendered by this panel
[*] 0    1   0x40  constant header
[*] 1    1   CPU temperature   (bit 7 = "convert to F" — see below)
    2    1   CPU load %
    3    2   CPU clock MHz          big-endian
[*] 5    2   CPU fan RPM            big-endian
    7    2   CPU power W            big-endian
    9    1   GPU temperature
   10    1   GPU load %
   11    2   GPU core clock MHz     big-endian
   13    2   GPU fan RPM            big-endian
   15    2   GPU power W            big-endian
   17    1   memory load %
   18    2   total RAM MB           big-endian
   20    1   disk usage %
   21    2   total disk GB          big-endian
   23    2   year (BE), 25 month, 26 day, 27 hour, 28 minute
   29    1   checksum = sum(payload[0..28]) & 0xFF
   30+       zero padding to 64 bytes
```

All multi-byte values are **big-endian** (`buf[n] = v >> 8; buf[n+1] = v`).

## What this panel actually uses

Each field was driven with a counting ramp while the rest stayed at zero.
Only two moved anything:

- **big number ← `cpu_temp`** (offset 1)
- **small number ← `cpu_fan`** (offset 5). NOT a plain pass-through — see
  below.

GPU, loads, power, memory, disk and the clock all did nothing. The other
twelve fields exist because the vendor's larger panels use them.

An earlier hypothesis — that the big number was the pump's own coolant
sensor — is **wrong**. Every number on the glass comes from the host.

## The fan slot renders two independent decimal fields

Sending 8008 displays **8028**. That looks like a ~0.25% scale, and with only
that one point plus an early ramp reading, a scale is what it looked like. It
is not. Seventeen measured pairs show what is really happening:

| sent | shown | upper | last two |
|---:|---:|---|---|
| 8008 | 8028 | 80 → 80 | 08 → 28 |
| 7988 | 7908 | 79 → 79 | 88 → 08 |
| 7990 | 7910 | 79 → 79 | 90 → 10 |
| 7996 | 7916 | 79 → 79 | 96 → 16 |

The firmware draws the number as **two independent fields** — everything above
the last two digits, and the last two digits — and the second field is offset
by **+20 (mod 100)**. There is no carry: 7996 shows 7916, because 96+20 = 116
displays as 16 while the 79 stays 79.

So to display `d`, send the same upper digits with the last two rolled back:

```
sent = (d - d % 100) + ((d % 100 - 20) % 100)
   8008  ->  send 8088
    420  ->  send  400
   1439  ->  send 1419
```

**This model is incomplete and the correction ships DISABLED.** It fits every
value measured between 7981 and 8008, and fails both known values under 1000:

| sent | shown | +20 model predicts | |
|---:|---:|---:|---|
| 4 | 4 | 24 | ✗ (photographed) |
| 420 | 420 | 440 | ✗ |
| 1000 | 1001 | 1020 | ✗ |
| 7988 | 7908 | 7908 | ✓ |
| 8008 | 8028 | 8028 | ✓ |

So the offset depends on magnitude, or on how many digits the panel is
drawing — seventeen samples from one narrow band could never distinguish
those. `fan_map.py` walks values across the whole range to settle it.

`aio_screen.corrected_fan()` implements the offset, driven by
`fan_low2_offset` in `config.json` (`null` = send verbatim, the default until
the mapping is known).

Two lessons recorded because both cost real time:

1. The original ramp test (1000→1011 displaying 1000→1011) was read as proof
   of a verbatim pass-through. It was not: in that range the last-two field
   happened to be offset by an amount too small to notice against digits read
   off a photo. A weak measurement was promoted to a documented fact.
2. Sampling one narrow band and generalising to the whole range. Seventeen
   readings between 7981 and 8008 produced a confident model that two much
   older data points — a photograph, and a value that had been quietly
   working — already contradicted. Range matters more than sample count.
3. Hunting for the right input by stepping ±1 around a scaled guess is
   hopeless against this mapping. When the last-two field is wrong, *every*
   neighbouring value is wrong by the same amount; the value that lands is
   100 away, not 1. Twenty manual steps produced twenty identical failures,
   which is itself the clue — a constant error across a swept range means the
   model is wrong, not the guess.

## The 0x80 temperature bit (calibrated)

Bit 7 tells the panel to convert to Fahrenheit **itself**. This is the
opposite of what the vendor's radio-button code suggested at first read, and
it was only settled by measurement:

| sent | bit clear | bit set |
|---:|---:|---:|
| 0 | 0 | **128** |
| 1 | 1 | 33 |
| 25 | 25 | 77 |
| 50 | 50 | 122 |
| 100 | 100 | 212 |
| 127 | 127 | **4** |

- **bit clear → the byte is displayed verbatim.** This makes the big readout
  an exact 0–127 number under full host control. It is the driver default.
- **bit set → the panel computes `v*1.8+32`**, in 8-bit arithmetic.

Two firmware quirks fall out of the extremes:

1. **`0` with the bit set shows `128`** — the raw byte, unconverted. The
   conversion appears to be skipped when the low 7 bits are zero.
2. **the conversion wraps at 8 bits**: `127*1.8+32 = 260`, and `260 & 0xFF =
   4`, which is exactly what the panel showed. With the bit set the usable
   input range therefore stops at **123** (`123*1.8+32 = 253`).

This also explains the very first photo taken during this work: `identify.py`
had sent `cpu_temp=1`, and `1*1.8+32 = 33.8` → the panel read **33**, which
looked exactly like a plausible coolant temperature and nearly sent the
investigation down the wrong path.

## Why `pip install hidapi` cannot work here

The wheel is only a Cython *binding* — it ships no native library and hunts
for `hidapi.dll` on PATH, raising `ImportError` when it finds none. The
vendor's own `hidapi.dll` cannot fill the gap either: `PC_Monitor.exe` is
x86, so its DLL is 32-bit, and a 64-bit Python can never load it.

`winhid.py` therefore talks straight to the Windows HID stack through
ctypes: `setupapi.dll` to enumerate interfaces, `hid.dll` for attributes and
capabilities, `CreateFile`/`WriteFile` to post reports. No dependency, always
the right bitness. Two details that matter:

- a device exposes several HID collections and only some accept output
  reports, so `find_panel()` sorts interfaces that can take a 64-byte report
  first rather than grabbing the first VID/PID match
- Windows requires a write of **exactly** `OutputReportByteLength` bytes, so
  the buffer is padded to whatever the device declares, with a
  `HidD_SetOutputReport` fallback for devices with no interrupt OUT endpoint

## Behaviour notes

- The panel has no idle screen of its own: it shows the last frame a host
  posted, then fades out after an inactivity timeout of some seconds. That
  is why the vendor app must keep running in the background.
- There is no handshake, no ack and nothing to wedge. Open the device and
  start posting.

## Files

| File | Purpose |
|---|---|
| `aio_screen.py` | the driver — `Stats`, `build_report`, `AioScreen` |
| `winhid.py` | dependency-free Windows HID access via ctypes |
| `demo_stats.py` | live demo; `--big`/`--small` choose what each readout shows |
| `list_hid.py` | every HID interface present, panel flagged |
| `identify.py` | sets each field to its own index so the panel maps itself |
| `probe_display.py` | counting ramps, one field at a time — found the two live fields |
| `calibrate_temp.py` | self-paced walk that produced the table above |
| `RUN_*.bat` | double-clickable wrappers for each of the above |

## Open questions

- The fan readout takes a 16-bit value; only 0–8888 was exercised. What it
  does with five-digit numbers is untested.
- Whether any field drives the pump's *behaviour* (fan curve, pump speed)
  rather than just the display was not investigated — everything here is
  display-only, and nothing was sent that could change cooling.
