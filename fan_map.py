"""
fan_map.py -- map what the fan slot really does, across the whole range.

I got this wrong twice by generalising from a narrow band:

  * first "verbatim", from a ramp of 1000-1011 whose error was too small to see
  * then "+20 on the last two digits", from seventeen readings all between
    7981 and 8008

The second model fits every 4-digit value measured and fails both values under
1000: identify.py sent 4 and the panel showed 4; the fun frame sent 420 and
showed 420. So the offset is not universal -- it depends on the magnitude, or
on how many digits the panel is drawing, and one band of samples cannot tell.

This walks values chosen to straddle every plausible boundary: single digits,
tens, hundreds, either side of 1000, and up through the thousands. Ten
readings, self-paced, and then the pattern will be visible rather than
guessed at.

    python fan_map.py
"""
import os
import threading
import time

from aio_screen import AioScreen, Stats

VALUES = [4, 42, 99, 100, 420, 999, 1000, 1020, 4000, 8008]
RESULTS_FILE = "fan_map.txt"


class Poster(threading.Thread):
    daemon = True

    def __init__(self, screen):
        super().__init__()
        self.screen = screen
        self.value = 0
        self.stop = threading.Event()

    def run(self):
        while not self.stop.wait(0.4):
            try:
                self.screen.send(Stats(cpu_temp=42, cpu_fan=self.value))
            except Exception:  # noqa: BLE001
                pass


def main():
    rows = []
    # correction OFF -- we are measuring the raw firmware behaviour
    with AioScreen(fan_low2_offset=None) as screen:
        poster = Poster(screen)
        poster.start()
        print(f"\n{len(VALUES)} readings. Big readout stays at 42; read the SMALL one.")
        print("Type what you see and press Enter. Enter alone skips.\n")
        try:
            for n, value in enumerate(VALUES, 1):
                poster.value = value
                time.sleep(0.8)
                print(f"--- {n}/{len(VALUES)}  sending {value}")
                seen = input("    small number shown? ").strip()
                rows.append((value, seen))
        except KeyboardInterrupt:
            print("\ninterrupted -- writing what we have.")
        finally:
            poster.stop.set()
            poster.join(timeout=2)

    lines = ["sent   shown    difference", "-" * 32]
    for value, seen in rows:
        if seen.isdigit():
            lines.append(f"{value:>5} {int(seen):>7} {int(seen) - value:>+13}")
        else:
            lines.append(f"{value:>5} {(seen or '(skipped)'):>7}")
    text = "\n".join(lines)
    print("\n" + text)
    with open(RESULTS_FILE, "w", encoding="utf-8") as fh:
        fh.write(text + "\n")
    print(f"\nsaved to {RESULTS_FILE} -- send me that and I will work out the rule.")


if __name__ == "__main__":
    from panel_lock import PanelBusy

    try:
        main()
    except PanelBusy as busy:
        print(f"\n{busy}\n")
        raise SystemExit(1)
