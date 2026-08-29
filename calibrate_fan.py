"""
calibrate_fan.py -- what does the panel actually do with the fan number?

Sending 8008 displays 8028. That is a 20 count difference, and it is not a
constant offset: the earlier ramp test sent 1000-1011 and the panel tracked it
to within 1. So the fan field is not the plain pass-through it looked like,
and one data point is not enough to say what it is.

Candidate explanations this walk can tell apart:

  * a scale factor        8008 * 1.0025 = 8028   (and 1000 -> 1002)
  * quantisation          the firmware snapping to a step of 4, 12, 20 ...
  * a tacho round-trip    rpm -> pulse period -> rpm, which loses precision
                          in a way that grows with the value
  * something above a threshold only, with small values passing through

Self-paced: each step holds until you press Enter, and what you type is
recorded. Results go to fan_calibration.txt.

    python calibrate_fan.py
"""
import threading
import time

from aio_screen import AioScreen, Stats

VALUES = [100, 420, 1000, 2000, 4000, 6000, 8000, 8008, 8888,
          10000, 12345, 20000, 30000, 60000, 65535]

RESULTS_FILE = "fan_calibration.txt"


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
                # big readout parked at 42 so it is obvious which is which
                self.screen.send(Stats(cpu_temp=42, cpu_fan=self.value))
            except Exception:  # noqa: BLE001
                pass


def main():
    rows = []
    with AioScreen() as screen:
        poster = Poster(screen)
        poster.start()
        print(f"\npanel open. {len(VALUES)} steps -- press Enter to advance.")
        print("Read the SMALL number (beside the fan icon), type it, press Enter.")
        print("Enter alone skips. The big number stays at 42 throughout.\n")
        try:
            for n, value in enumerate(VALUES, 1):
                poster.value = value
                time.sleep(0.6)
                hi, lo = (value >> 8) & 0xFF, value & 0xFF
                print(f"--- step {n}/{len(VALUES)} " + "-" * 40)
                print(f"    sending fan = {value}   (bytes {hi:02X} {lo:02X})")
                seen = input("    small number on the panel? ").strip()
                rows.append((value, seen))
        except KeyboardInterrupt:
            print("\ninterrupted -- writing what we have.")
        finally:
            poster.stop.set()
            poster.join(timeout=2)

    lines = ["sent   observed   difference   ratio", "-" * 42]
    for value, seen in rows:
        if seen.isdigit():
            got = int(seen)
            lines.append(f"{value:>6} {got:>10} {got - value:>+12} {got / value:>9.5f}")
        else:
            lines.append(f"{value:>6} {(seen or '(skipped)'):>10}")
    text = "\n".join(lines)
    print("\n" + text)
    with open(RESULTS_FILE, "w", encoding="utf-8") as fh:
        fh.write(text + "\n")
    print(f"\nsaved to {RESULTS_FILE}")


if __name__ == "__main__":
    from panel_lock import PanelBusy

    try:
        main()
    except PanelBusy as busy:
        print(f"\n{busy}\n")
        raise SystemExit(1)
