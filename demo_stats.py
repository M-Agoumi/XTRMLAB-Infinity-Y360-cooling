"""
demo_stats.py -- drive the AIO pump-cap display with whatever you want.

    python demo_stats.py                       # GPU temp + GPU fan RPM
    python demo_stats.py --big cpu_load        # CPU load % in the big readout
    python demo_stats.py --big gpu_temp --small gpu_power
    python demo_stats.py --lhm http://localhost:8085/data.json --big cpu_temp
    python demo_stats.py --list                # what you can put where

This panel has exactly two readouts -- the big number (0-127) and the small
one beside the fan icon (0-65535) -- so the interesting question is not how
to draw on it but WHAT TO PUT IN THEM. Neither slot cares what its protocol
field is called: the big number is just a byte the firmware prints.

About CPU temperature: Windows does not expose it to an ordinary process,
which is exactly why the vendor app ships a kernel driver (PC_Monitor.sys).
So the default here is GPU temp, which nvidia-smi gives up freely. If you
run LibreHardwareMonitor with its web server on, --lhm reads real CPU temp
from it -- same number, no kernel driver.

Requires: pip install psutil   (HID access needs no package -- see winhid.py)
"""
import argparse
import json
import re
import shutil
import subprocess
import sys
import time
import urllib.request

import psutil

from aio_screen import AioScreen, Stats

NVIDIA_QUERY = ("temperature.gpu,utilization.gpu,clocks.current.graphics,"
                "fan.speed,power.draw")

# name -> (how to get it, one-line description, sensible for the big slot?)
METRICS = {
    "gpu_temp":   "GPU temperature, C (nvidia-smi)",
    "gpu_load":   "GPU utilisation, %",
    "gpu_clock":  "GPU core clock, MHz",
    "gpu_fan":    "GPU fan, RPM (estimated from nvidia-smi's %)",
    "gpu_power":  "GPU power draw, W",
    "cpu_load":   "CPU utilisation, %",
    "cpu_clock":  "CPU clock, MHz",
    "cpu_temp":   "CPU temperature, C -- needs --admin-sensors or --lhm",
    "cpu_fan":    "CPU/case fan, RPM -- needs --admin-sensors or --lhm",
    "cpu_power":  "CPU package power, W -- needs --lhm",
    "mem_load":   "memory in use, %",
    "mem_total":  "total RAM, MB",
    "disk_load":  "system drive in use, %",
    "disk_total": "system drive size, GB",
    "clock_hhmm": "wall clock as HHMM (small slot only)",
    "zero":       "nothing -- leave the readout at 0",
}


def gpu_stats():
    exe = shutil.which("nvidia-smi")
    if not exe:
        return {}
    try:
        out = subprocess.run(
            [exe, f"--query-gpu={NVIDIA_QUERY}", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5,
        ).stdout.strip().splitlines()[0]
    except Exception:  # noqa: BLE001
        return {}
    vals = []
    for part in out.split(","):
        try:
            vals.append(int(float(part.strip())))
        except ValueError:
            vals.append(0)          # "[N/A]" on some cards
    vals += [0] * (5 - len(vals))
    return {"gpu_temp": vals[0], "gpu_load": vals[1], "gpu_clock": vals[2],
            # nvidia-smi reports fan as a PERCENT; scaled to a plausible RPM
            "gpu_fan": vals[3] * 22, "gpu_power": vals[4]}


def lhm_stats(url):
    try:
        with urllib.request.urlopen(url, timeout=2) as r:
            data = json.load(r)
    except Exception:  # noqa: BLE001
        return {}
    found = {}

    def walk(node):
        text, value = node.get("Text", ""), node.get("Value", "")
        if "cpu_temp" not in found and re.search(r"CPU Package|Core \(Tctl", text, re.I) \
                and "°C" in value:
            found["cpu_temp"] = int(float(value.split()[0].replace(",", ".")))
        if "cpu_power" not in found and re.search(r"CPU Package|Package Power", text, re.I) \
                and " W" in value:
            found["cpu_power"] = int(float(value.split()[0].replace(",", ".")))
        for child in node.get("Children", []):
            walk(child)

    walk(data)
    return found


def collect(lhm_url=None, lhm_lib=None, fan_prefer=None, temp_prefer=None):
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage("C:\\" if sys.platform == "win32" else "/")
    freq = psutil.cpu_freq()
    now = time.localtime()
    v = {
        "cpu_load": int(psutil.cpu_percent()),
        "cpu_clock": int(freq.current) if freq else 0,
        "cpu_temp": 0, "cpu_fan": 0, "cpu_power": 0,
        "mem_load": int(mem.percent),
        "mem_total": int(mem.total / (1024 * 1024)),
        "disk_load": int(disk.percent),
        "disk_total": int(disk.total / (1024 ** 3)),
        "clock_hhmm": now.tm_hour * 100 + now.tm_min,
        "zero": 0,
    }
    v.update(gpu_stats())
    if lhm_url:
        v.update(lhm_stats(lhm_url))
    if lhm_lib is not None:
        temp = lhm_lib.cpu_temp(temp_prefer)
        fan = lhm_lib.fan_rpm(fan_prefer)
        if temp is not None:
            v["cpu_temp"] = int(round(temp))
        if fan is not None:
            v["cpu_fan"] = int(round(fan))
    return v


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--big", default="gpu_temp", choices=sorted(METRICS),
                    help="what the big number shows (clamped to 0-127)")
    ap.add_argument("--small", default="gpu_fan", choices=sorted(METRICS),
                    help="what the small number beside the fan icon shows")
    ap.add_argument("--lhm", metavar="URL",
                    help="LibreHardwareMonitor data.json URL, for real CPU temp/power")
    ap.add_argument("--admin-sensors", action="store_true",
                    help="read CPU temp and fan RPM directly via LibreHardwareMonitorLib "
                         "(needs administrator + pip install pythonnet)")
    ap.add_argument("--dll", default=None, help="path to LibreHardwareMonitorLib.dll")
    ap.add_argument("--fan", default=None, metavar="NAME|#N",
                    help="which fan sensor to use: a name, part of one, or #index "
                         "(run RUN_SENSORS.bat to see the list)")
    ap.add_argument("--temp", default=None, metavar="NAME|#N",
                    help="which temperature sensor to use (default: CPU package)")
    ap.add_argument("--list-sensors", action="store_true",
                    help="with --admin-sensors: dump every sensor and exit")
    ap.add_argument("--fahrenheit", action="store_true",
                    help="let the panel convert the big number to F (max input 123)")
    ap.add_argument("--hz", type=float, default=1.0)
    ap.add_argument("--list", action="store_true", help="list metrics and exit")
    args = ap.parse_args()

    if args.list:
        print("what you can put in either readout:\n")
        for name, desc in METRICS.items():
            print(f"  {name:<12} {desc}")
        return

    lhm_lib = None
    if args.admin_sensors or args.list_sensors:
        from sensors import LhmSensors, SensorError, is_admin, DEFAULT_DLL
        if not is_admin():
            print("!! not running as administrator -- CPU temp and fan RPM will read 0.")
            print("   use RUN_CPU_DEMO.bat, which elevates for you.\n")
        try:
            lhm_lib = LhmSensors(args.dll or DEFAULT_DLL)
        except SensorError as e:
            print(f"sensor init failed: {e}")
            return
        if args.list_sensors:
            for hw, kind, name, value in lhm_lib.list_sensors():
                print(f"  {hw:<28} {kind:<12} {name:<28} {value:>10.1f}")
            lhm_lib.close()
            return

    psutil.cpu_percent()                       # prime the counter
    period = 1.0 / args.hz if args.hz > 0 else 1.0

    with AioScreen(fahrenheit=args.fahrenheit) as screen:
        print(f"panel open (output report {screen.output_len} bytes)")
        print(f"  big   = {args.big:<12} {METRICS[args.big]}")
        print(f"  small = {args.small:<12} {METRICS[args.small]}")
        if lhm_lib is not None:
            # Say out loud which sensors are in use. Boards expose several
            # plausible-looking candidates and picking the wrong one is silent.
            t, f = lhm_lib.pick_temp(args.temp), lhm_lib.pick_fan(args.fan)
            print(f"  temp sensor  = {t[1]!r} ({t[0]})" if t else "  temp sensor  = none found")
            print(f"  fan sensor   = {f[1]!r} ({f[0]})" if f else "  fan sensor   = none found")
            others = [r for r in lhm_lib.fans() if not f or r[1] != f[1]]
            if others:
                print("  other fans   = " + ", ".join(f"{n} {v:.0f}rpm" for _, n, v in others))
            print("  (wrong one? pass --fan / --temp with a name or #index)")
        if args.big == "cpu_temp" and not (args.lhm or lhm_lib):
            print("\n  NOTE: CPU temp needs --admin-sensors or --lhm; otherwise it reads 0.")
        print("\nCtrl+C to stop.\n")
        try:
            while True:
                v = collect(args.lhm, lhm_lib, args.fan, args.temp)
                big, small = v.get(args.big, 0), v.get(args.small, 0)
                if args.fahrenheit and big > 123:
                    big = 123          # the panel's 8-bit F conversion wraps past this
                screen.send(Stats(cpu_temp=big, cpu_fan=small))
                print(f"  big {big:>5}   small {small:>6}      ", end="\r", flush=True)
                time.sleep(period)
        except KeyboardInterrupt:
            print("\nstopped. The panel holds the last frame for a while, then fades.")
        finally:
            if lhm_lib is not None:
                lhm_lib.close()


if __name__ == "__main__":
    from panel_lock import PanelBusy

    try:
        main()
    except PanelBusy as busy:
        print(f"\n{busy}\n")
        raise SystemExit(1)
