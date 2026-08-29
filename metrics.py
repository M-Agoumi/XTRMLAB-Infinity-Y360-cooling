"""
metrics.py -- what can go in each of the panel's two readouts.

The panel draws two numbers and does not care what they mean, so anything the
machine can measure is fair game. This maps friendly names to sensors, and is
shared by the daemon and demo_stats so both offer the same list.

Each entry is (sensor kind, name pattern, hardware pattern, unit, description,
relax, typical_max) where `relax` says whether it is safe to ignore the
hardware pattern when nothing matches, and `typical_max` is the largest value
this metric realistically reaches.

typical_max exists because the two readouts have hard limits and offering a
metric that cannot fit is offering a broken choice:

    big readout    0-127        7-bit field; anything larger clamps to 127
    small readout  0-65535      but values above ~1020 have their last two
                                digits corrupted by the firmware

So `suits()` filters what may be offered for each slot. It is NOT safe for GPU metrics: with relaxation on, a
missing GPU fan sensor happily resolves to the motherboard's Fan #1 and the
readout silently shows the wrong hardware.
Patterns are case-insensitive regular expressions matched against what
LibreHardwareMonitor reports. The first match wins, so put the specific name
first: "CPU Package" before a general "cpu".
"""

from __future__ import annotations

import re
import time

# name -> (kind, name regex, hardware regex, unit, description, relax, typical_max)
METRICS = {
    "cpu_temp":    ("Temperature", r"cpu package|core \(tctl|core average",
                    r"cpu|intel|amd|ryzen", "C", "CPU temperature", True, 110),
    "cpu_fan":     ("Fan", r".", r".", "rpm", "CPU / case fan speed", True, 3000),
    "cpu_load":    ("Load", r"cpu total", r"cpu|intel|amd|ryzen", "%",
                    "CPU utilisation", True, 100),
    "cpu_clock":   ("Clock", r"cpu core #?1\b", r"cpu|intel|amd|ryzen", "MHz",
                    "CPU core clock", True, 6500),
    "cpu_power":   ("Power", r"cpu package", r"cpu|intel|amd|ryzen", "W",
                    "CPU package power", True, 400),
    "gpu_temp":    ("Temperature", r"gpu core", r"nvidia|amd|radeon|geforce|gpu",
                    "C", "GPU temperature", False, 110),
    "gpu_hotspot": ("Temperature", r"hot ?spot", r"nvidia|amd|radeon|geforce|gpu",
                    "C", "GPU hot spot", False, 125),
    "gpu_load":    ("Load", r"gpu core", r"nvidia|amd|radeon|geforce|gpu", "%",
                    "GPU utilisation", False, 100),
    "gpu_clock":   ("Clock", r"gpu core", r"nvidia|amd|radeon|geforce|gpu", "MHz",
                    "GPU core clock", False, 3500),
    "gpu_fan":     ("Fan", r".", r"nvidia|amd|radeon|geforce", "rpm",
                    "GPU fan", False, 4000),
    "gpu_power":   ("Power", r"gpu package|gpu power", r"nvidia|amd|radeon|geforce|gpu",
                    "W", "GPU power draw", False, 700),
    "mem_load":    ("Load", r"^memory$", r"memory", "%", "Memory in use", True, 100),
    "mem_used_gb": ("Data", r"memory used", r"memory", "GB", "Memory used", True, 256),
    "vram_load":   ("Load", r"gpu memory", r"nvidia|amd|radeon|geforce", "%",
                    "VRAM in use", False, 100),
}

# these do not come from the sensor library
SPECIAL = {
    "clock_hhmm": ("time as HHMM", 2359),
    "clock_hh":   ("hour", 23),
    "clock_mm":   ("minute", 59),
    "zero":       ("always 0 (blank-ish)", 0),
}

BIG_MAX = 127        # 7-bit field; bit 7 is the unit flag, not data
SMALL_EXACT_MAX = 1020   # above this the firmware corrupts the last two digits


def typical_max(name):
    if name in METRICS:
        return METRICS[name][6]
    if name in SPECIAL:
        return SPECIAL[name][1]
    return 0


def describe(name):
    if name in METRICS:
        unit, desc = METRICS[name][3], METRICS[name][4]
        return f"{desc} ({unit})"
    if name in SPECIAL:
        return SPECIAL[name][0]
    return name


def suits(slot, name):
    """Can this metric actually be displayed in this readout?"""
    if slot == "big":
        return typical_max(name) <= BIG_MAX
    return True


def exact_in(slot, name):
    """Will it display exactly, or hit the firmware's digit corruption?"""
    if slot == "big":
        return suits("big", name)
    return typical_max(name) <= SMALL_EXACT_MAX


def names(slot=None):
    """Every metric, or only those that fit the given readout."""
    all_names = list(METRICS) + list(SPECIAL)
    if slot is None:
        return all_names
    return [n for n in all_names if suits(slot, n)]


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
    kind, name_pat, hw_pat, _unit, _desc, relax, _max = spec

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
