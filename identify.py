"""
identify.py -- work out which readout on the panel is which field.

The panel renders its own fixed layout in firmware, so we cannot know from
the protocol alone where each number lands on the glass. Two ways to find
out, and the first one usually settles it in a single frame.

MODE 1 (default) -- "ordinal frame".
Every field is set to its own index: CPU temp = 1, CPU load = 2, CPU clock
= 3, and so on up to 14. The panel then literally displays a map of itself.
Read it off and you know the whole layout at once:

     1 cpu_temp        6 gpu_temp        11 mem_load
     2 cpu_load        7 gpu_load        12 mem_total_mb
     3 cpu_clock       8 gpu_clock       13 disk_load
     4 cpu_fan         9 gpu_fan         14 disk_total_gb
     5 cpu_power      10 gpu_power
     clock is pinned to 11:11 on 2011-11-11 so it is unmistakable

Some readouts may not show a bare small number (a percent ring will show
1%, a clock field may show "3 MHz"), but the digit is what matters.

MODE 2 -- `python identify.py sweep`
One field at a time: every field zero except one, held for 6 seconds while
the console names it. Slower, but unambiguous when two readouts sit close
together or a field is drawn as a gauge rather than a number.

    python identify.py          # ordinal frame, held for 60s
    python identify.py sweep    # one field at a time
"""
import datetime
import sys
import time

from aio_screen import AioScreen, Stats

FIELDS = [
    "cpu_temp", "cpu_load", "cpu_clock", "cpu_fan", "cpu_power",
    "gpu_temp", "gpu_load", "gpu_clock", "gpu_fan", "gpu_power",
    "mem_load", "mem_total_mb", "disk_load", "disk_total_gb",
]

MARKER_TIME = datetime.datetime(2011, 11, 11, 11, 11)


def ordinal_frame():
    s = Stats(when=MARKER_TIME)
    for n, name in enumerate(FIELDS, start=1):
        setattr(s, name, n)
    return s


def run_ordinal(screen, seconds=60):
    s = ordinal_frame()
    print("Every field is set to its own number. Read the panel:\n")
    for n, name in enumerate(FIELDS, start=1):
        print(f"    {n:>2}  = {name}")
    print("    clock = 11:11 on 2011-11-11\n")
    print(f"holding for {seconds}s -- tell me which number appears in which spot")
    print("(a photo of the panel is the easiest way to send me this)\n")
    end = time.time() + seconds
    while time.time() < end:
        screen.send(s)
        print(f"  {int(end - time.time()):>3d}s left ", end="\r", flush=True)
        time.sleep(1.0)
    print()


def run_sweep(screen, hold=6.0):
    print("One field at a time; everything else is zero.\n")
    for name in FIELDS:
        # percentages and temps cap at ~100; clocks/fans/sizes get a wide value
        value = 88 if name.endswith(("load", "temp")) else 8888
        s = Stats(when=MARKER_TIME)
        setattr(s, name, value)
        print(f"  NOW SHOWING: {name} = {value}   (watch which readout changes)")
        end = time.time() + hold
        while time.time() < end:
            screen.send(s)
            time.sleep(0.5)
    print("\nsweep done.")


def main():
    mode = (sys.argv[1] if len(sys.argv) > 1 else "ordinal").lower()
    with AioScreen() as screen:
        print(f"panel open, output report length = {screen.output_len}\n")
        if mode.startswith("s"):
            run_sweep(screen)
        else:
            run_ordinal(screen)
    print("stopped posting -- the panel will go black again until something feeds it.")


if __name__ == "__main__":
    main()
