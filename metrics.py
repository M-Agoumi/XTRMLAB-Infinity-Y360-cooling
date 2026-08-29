"""
metrics.py -- what can go in each of the panel's two readouts.

The panel draws two numbers and does not care what they mean, so anything the
machine can measure is fair game. This maps friendly names to sensors, and is
shared by the daemon and demo_stats so both offer the same list.

Each entry is (sensor kind, name pattern, hardware pattern, unit, description,
relax) where `relax` says whether it is safe to ignore the hardware pattern
when nothing matches. It is NOT safe for GPU metrics: with relaxation on, a
missing GPU fan sensor happily resolves to the motherboard's Fan #1 and the
readout silently shows the wrong hardware.
Patterns are case-insensitive regular expressions matched against what
LibreHardwareMonitor reports. The first match wins, so put the specific name
first: "CPU Package" before a general "cpu".
"""

from __future__ import annotations

import re
import time

# name -> (kind, name regex, hardware regex, unit, description)
METRICS = {
    "cpu_temp":   ("Temperature", r"cpu package|core \(tctl|core average", r"cpu|intel|amd|ryzen",
                   "C", "CPU temperature", True),
    "cpu_fan":    ("Fan", r".", r".", "rpm", "CPU / case fan speed", True),
    "cpu_load":   ("Load", r"cpu total", r"cpu|intel|amd|ryzen", "%", "CPU utilisation", True),
    "cpu_clock":  ("Clock", r"cpu core #?1\b", r"cpu|intel|amd|ryzen",
                   "MHz", "CPU core clock", True),
    "cpu_power":  ("Power", r"cpu package", r"cpu|intel|amd|ryzen", "W",
                   "CPU package power", True),
    "gpu_temp":   ("Temperature", r"gpu core", r"nvidia|amd|radeon|geforce|gpu",
                   "C", "GPU temperature", False),
    "gpu_hotspot": ("Temperature", r"hot ?spot", r"nvidia|amd|radeon|geforce|gpu",
                    "C", "GPU hot spot", False),
    "gpu_load":   ("Load", r"gpu core", r"nvidia|amd|radeon|geforce|gpu", "%",
                   "GPU utilisation", False),
    "gpu_clock":  ("Clock", r"gpu core", r"nvidia|amd|radeon|geforce|gpu", "MHz",
                   "GPU core clock", False),
    "gpu_fan":    ("Fan", r".", r"nvidia|amd|radeon|geforce", "rpm", "GPU fan", False),
    "gpu_power":  ("Power", r"gpu package|gpu power", r"nvidia|amd|radeon|geforce|gpu",
                   "W", "GPU power draw", False),
    "mem_load":   ("Load", r"^memory$", r"memory", "%", "Memory in use", True),
    "mem_used_gb": ("Data", r"memory used", r"memory", "GB", "Memory used", True),
    "vram_load":  ("Load", r"gpu memory", r"nvidia|amd|radeon|geforce", "%",
                   "VRAM in use", False),
}

# these do not come from the sensor library
SPECIAL = {
    "clock_hhmm": ("", "time as HHMM"),
    "clock_hh":   ("", "hour"),
    "clock_mm":   ("", "minute"),
    "zero":       ("", "always 0 (blank-ish)"),
}


def names():
    return list(METRICS) + list(SPECIAL)


def describe(name):
    if name in METRICS:
        unit, desc = METRICS[name][3], METRICS[name][4]
        return f"{desc} ({unit})"
    if name in SPECIAL:
        return SPECIAL[name][1]
    return name


def read(rows, name, temp_prefer=None, fan_prefer=None):
    """
    Resolve one metric from a sensor snapshot.

    rows: [(hardware, kind, name, value)] as sensors.LhmSensors.rows() gives.
    temp_prefer / fan_prefer: the explicit sensor choices from config.json,
    which win over the pattern for cpu_temp / cpu_fan -- those two are the ones
    boards disagree about most, and the user has already pinned them.
    """
    now = time.localtime()
    if name == "clock_hhmm":
        return now.tm_hour * 100 + now.tm_min
    if name == "clock_hh":
        return now.tm_hour
    if name == "clock_mm":
        return now.tm_min
    if name == "zero":
        return 0

    override = {"cpu_temp": temp_prefer, "cpu_fan": fan_prefer}.get(name)
    spec = METRICS.get(name)
    if not spec:
        return None
    kind, name_pat, hw_pat, _unit, _desc, relax = spec

    candidates = [r for r in rows if r[1] == kind]
    if override:
        want = str(override).strip().lower()
        idx = want.lstrip("#")
        pool = [r for r in candidates]
        if idx.isdigit() and int(idx) < len(pool):
            return pool[int(idx)][3]
        for r in pool:                                  # exact, then prefix, then substring
            if r[2].lower() == want:
                return r[3]
        for r in pool:
            if r[2].lower().startswith(want):
                return r[3]
        for r in pool:
            if want in r[2].lower():
                return r[3]

    name_re, hw_re = re.compile(name_pat, re.I), re.compile(hw_pat, re.I)
    for hw, _kind, sensor, value in candidates:
        if name_re.search(sensor) and hw_re.search(hw):
            return value
    if relax:                                           # only where it is safe
        for hw, _kind, sensor, value in candidates:
            if name_re.search(sensor):
                return value
    if name in ("cpu_fan",):                            # fall back to any turning fan
        spinning = [r for r in candidates if r[3] > 0]
        if spinning:
            return spinning[0][3]
    return None
