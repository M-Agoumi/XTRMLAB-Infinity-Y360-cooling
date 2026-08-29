"""
calibrate_temp.py -- pin down exactly what the 0x80 bit does to the big number.

Self-paced: each step keeps posting its frame to the panel until you press
Enter, so you can look at the glass and the console side by side for as long
as you like. Type the number you see and it gets recorded; press Enter alone
to skip a row.

What the probe run already established:
  * big readout = cpu_temp, small readout beside the fan icon = cpu_fan
    (fan tracked 1000->1011 exactly, so it is a plain RPM integer)
  * every other field in the protocol is ignored by this pump-cap model
  * with the 0x80 bit set: value 30 showed 87, value 41 showed 105 -- that is
    v*1.8+32, i.e. a Fahrenheit conversion (86 and 105.8). It also explains
    the photo: identify.py sent cpu_temp=1, and 1*1.8+32 = 33.8 -> "33".
  * but value 0 with the bit set showed 128, not 32 -- so 0 is special.

Unknown, and the reason for this run: what the panel does with the bit CLEAR.
Every test so far has had it set.

Results are written to calibration_results.txt.

    python calibrate_temp.py
"""
import threading
import time

from aio_screen import AioScreen, Stats

STEPS = [
    (0, True), (1, True), (25, True), (50, True), (100, True), (127, True),
    (0, False), (1, False), (25, False), (50, False), (100, False), (127, False),
]

RESULTS_FILE = "calibration_results.txt"


class Poster(threading.Thread):
    """Keeps the current frame going to the panel while you look at it."""

    daemon = True

    def __init__(self, screen):
        super().__init__()
        self.screen = screen
        self.value = 0
        self.flag = True
        self.stop = threading.Event()

    def set(self, value, flag):
        self.value, self.flag = value, flag

    def run(self):
        while not self.stop.wait(0.4):
            try:
                self.screen.send(Stats(cpu_temp=self.value, cpu_fan=self.value),
                                 fahrenheit=self.flag)
            except Exception:  # noqa: BLE001
                pass


def main():
    rows = []
    with AioScreen() as screen:
        poster = Poster(screen)
        poster.start()
        print(f"\npanel open. {len(STEPS)} steps -- press Enter to advance.\n")
        print("For each step: read the BIG number, type it, press Enter.")
        print("(Enter alone skips. The small number should mirror the sent value.)\n")

        try:
            for n, (value, flag) in enumerate(STEPS, 1):
                byte = (value | 0x80) if flag else value
                poster.set(value, flag)
                time.sleep(0.6)          # let a frame or two land before you look
                print(f"--- step {n}/{len(STEPS)} "
                      f"{'-' * 40}")
                print(f"    sending cpu_temp = {value}"
                      f"{'  with 0x80 set' if flag else '  with 0x80 CLEAR'}"
                      f"   (byte 0x{byte:02X} = {byte})")
                print(f"    predictions:  raw byte {byte}   |   plain value {value}"
                      f"   |   F = v*1.8+32 -> {int(value * 1.8 + 32)}")
                seen = input("    big number on the panel? ").strip()
                rows.append((value, flag, byte, seen))
        except KeyboardInterrupt:
            print("\ninterrupted -- writing what we have.")
        finally:
            poster.stop.set()
            poster.join(timeout=2)

    lines = ["sent  flag   byte   raw?  plain?    F?   OBSERVED",
             "-" * 52]
    for value, flag, byte, seen in rows:
        lines.append(f"{value:>4}  {'0x80' if flag else '  --'}  {byte:>5}  "
                     f"{byte:>5} {value:>7} {int(value * 1.8 + 32):>5}   {seen or '(skipped)'}")
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
