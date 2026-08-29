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
    "cpu_temp":   "CPU temperature, C -- needs --lhm",
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


def collect(lhm_url=None):
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage("C:\\" if sys.platform == "win32" else "/")
    freq = psutil.cpu_freq()
    now = time.localtime()
    v = {
        "cpu_load": int(psutil.cpu_percent()),
        "cpu_clock": int(freq.current) if freq else 0,
        "cpu_temp": 0, "cpu_power": 0,
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
    return v


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--big", default="gpu_temp", choices=sorted(METRICS),
                    help="what the big number shows (clamped to 0-127)")
    ap.add_argument("--small", default="gpu_fan", choices=sorted(METRICS),
                    help="what the small number beside the fan icon shows")
    ap.add_argument("--lhm", metavar="URL",
                    help="LibreHardwareMonitor data.json URL, for real CPU temp/power")
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

    psutil.cpu_percent()                       # prime the counter
    period = 1.0 / args.hz if args.hz > 0 else 1.0

    with AioScreen(fahrenheit=args.fahrenheit) as screen:
        print(f"panel open (output report {screen.output_len} bytes)")
        print(f"  big   = {args.big:<12} {METRICS[args.big]}")
        print(f"  small = {args.small:<12} {METRICS[args.small]}")
        if args.big == "cpu_temp" and not args.lhm:
            print("\n  NOTE: CPU temp needs --lhm; without it this will read 0.")
        print("\nCtrl+C to stop.\n")
        try:
            while True:
                v = collect(args.lhm)
                big, small = v.get(args.big, 0), v.get(args.small, 0)
                if args.fahrenheit and big > 123:
                    big = 123          # the panel's 8-bit F conversion wraps past this
                screen.send(Stats(cpu_temp=big, cpu_fan=small))
                print(f"  big {big:>5}   small {small:>6}      ", end="\r", flush=True)
                time.sleep(period)
        except KeyboardInterrupt:
            print("\nstopped. The panel holds the last frame for a while, then fades.")


if __name__ == "__main__":
    main()
