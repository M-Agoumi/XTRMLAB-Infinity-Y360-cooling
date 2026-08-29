"""
fan_tune.py -- measure the fan slot's digit offset. Two readings, not twenty.

The panel does not display the fan number verbatim. It renders it as TWO
independent decimal fields -- everything above the last two digits, and the
last two digits -- and the second field comes out offset:

    sent 8008  ->  80|08  ->  80|28  ->  shown 8028
    sent 7988  ->  79|88  ->  79|08  ->  shown 7908
    sent 7996  ->  79|96  ->  79|16  ->  shown 7916   (96+20 = 116, no carry)

The offset is 20 on the unit this was written for. One reading is enough to
measure it, because the offset is the whole story: read what 8008 displays as,
subtract, done.

(The first version of this script searched +/-1 around a scaled guess. That
could never work: when the last-two field is wrong, every neighbour is wrong
by the same amount, and the value that lands is 100 away, not 1. Sorry for
the twenty trips to the case.)

    python fan_tune.py            # measure, verify, save
    python fan_tune.py 1234       # verify against a different number
"""
import json
import os
import sys
import threading
import time

from aio_screen import AioScreen, Stats, corrected_fan

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "config.json")


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


def ask(poster, value, note=""):
    poster.value = value
    time.sleep(0.9)
    print(f"\n  sending {value}{('   ' + note) if note else ''}")
    while True:
        raw = input("  small number on the panel? ").strip()
        if raw.isdigit():
            return int(raw)
        print("  (digits only, please)")


def main():
    target = int(sys.argv[1]) if len(sys.argv) > 1 else 8008
    print(f"\nMeasuring the fan slot's digit offset, using {target}.")
    print("Two readings. The big readout stays at 42 so the small one is unambiguous.")

    # correction OFF while measuring, or we would measure our own compensation
    with AioScreen(fan_low2_offset=None) as screen:
        poster = Poster(screen)
        poster.start()
        try:
            seen = ask(poster, target, "(raw, uncorrected)")

            if seen == target:
                print("\n  Displays verbatim -- no correction needed.")
                save(None)
                return

            if seen // 100 != target // 100:
                print(f"\n  Unexpected: the upper digits changed too "
                      f"({target // 100} -> {seen // 100}).")
                print("  That is not the offset pattern this fixes. Run "
                      "RUN_FAN_CALIBRATE.bat and send me fan_calibration.txt.")
                return

            offset = (seen % 100 - target % 100) % 100
            print(f"\n  {target} displayed as {seen}")
            print(f"  upper digits unchanged ({target // 100}), "
                  f"last two {target % 100:02d} -> {seen % 100:02d}")
            print(f"  => offset is +{offset} (mod 100)")

            fixed = corrected_fan(target, offset)
            got = ask(poster, fixed, f"(corrected, should display {target})")
            if got == target:
                print(f"\n  Confirmed: asking for {target} now displays {target}.")
                save(offset)
            else:
                print(f"\n  Verification failed: sending {fixed} displayed {got}, "
                      f"expected {target}.")
                print("  Run RUN_FAN_CALIBRATE.bat and send me fan_calibration.txt.")
        finally:
            poster.stop.set()
            poster.join(timeout=2)


def save(offset):
    try:
        cfg = {}
        if os.path.exists(CONFIG_PATH):
            with open(CONFIG_PATH, encoding="utf-8") as fh:
                cfg = json.load(fh)
        cfg["fan_low2_offset"] = offset
        with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
            json.dump(cfg, fh, indent=2)
        print(f"  saved fan_low2_offset = {offset} to config.json")
        print("\n  Restart the daemon (tray -> Quit, then the desktop shortcut).")
    except Exception as e:  # noqa: BLE001
        print(f"  could not write config.json: {e}")


if __name__ == "__main__":
    from panel_lock import PanelBusy

    try:
        main()
    except PanelBusy as busy:
        print(f"\n{busy}\n")
        raise SystemExit(1)
