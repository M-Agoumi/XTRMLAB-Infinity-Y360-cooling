"""
probe_display.py -- find out which fields this round pump-cap display uses.

The panel is a small circular readout: one big number with a degree mark,
one small number beside a fan icon. It cannot show fourteen values, so most
of what the protocol carries is simply ignored by this model. The question
is which two fields it does read -- and whether the big number comes from us
at all, or from the pump's own coolant sensor.

Static values cannot answer that: a number that happens to look right might
be ours or might be the panel's. So every phase here COUNTS UP once a second.
A readout that ticks along with the console is ours; one that sits still is
the panel's own sensor.

PHASE 0 is the key one: a valid, correctly-checksummed packet with every
field set to ZERO. If the big number still shows ~33 during phase 0, it is
self-measured and no host field will ever change it.

    python probe_display.py           # all phases, ~12s each
    python probe_display.py 3         # just phase 3
"""
import sys
import time

from aio_screen import AioScreen, Stats

PHASES = [
    ("baseline: EVERYTHING zero", None, 0),
    ("cpu_temp", "cpu_temp", 30),
    ("gpu_temp", "gpu_temp", 50),
    ("cpu_fan", "cpu_fan", 1000),
    ("gpu_fan", "gpu_fan", 2000),
    ("cpu_load", "cpu_load", 10),
    ("gpu_load", "gpu_load", 60),
    ("cpu_power", "cpu_power", 100),
    ("mem_load", "mem_load", 80),
]

HOLD = 12


def run_phase(screen, n, label, field, start):
    print(f"\n=== PHASE {n}: {label} ===")
    if field is None:
        print("    sending a valid packet with every value at 0.")
        print("    Anything still lit on the panel is NOT coming from us.")
    else:
        print(f"    {field} counts {start} -> {start + HOLD - 1}, everything else 0.")
        print("    Watch for a readout ticking up once a second.")
    for i in range(HOLD):
        s = Stats()
        if field:
            setattr(s, field, start + i)
        screen.send(s)
        shown = (start + i) if field else 0
        print(f"    t+{i:2d}s  sending {field or 'all fields'} = {shown}   ",
              end="\r", flush=True)
        time.sleep(1.0)
    print()


def main():
    only = int(sys.argv[1]) if len(sys.argv) > 1 else None
    with AioScreen() as screen:
        print(f"panel open, output report length = {screen.output_len}")
        print("WATCH THE PANEL. Note the phase number where a readout starts counting.")
        for n, (label, field, start) in enumerate(PHASES):
            if only is not None and n != only:
                continue
            run_phase(screen, n, label, field, start)
    print("\ndone. Which phase(s) made a number move, and which readout moved?")


if __name__ == "__main__":
    main()
