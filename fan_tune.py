"""
fan_tune.py -- make the fan slot display the number you actually asked for.

Sending 8008 puts 8028 on the glass. The panel scales what it is given, so to
DISPLAY a number we have to send a different one. This finds the correction by
measurement rather than by trusting a theory, then writes it to config.json as
"fan_scale", after which every script here compensates automatically.

It works by search, not algebra, so it does not matter whether the firmware is
scaling, rounding, or doing something stranger:

  1. send the target, ask what appeared
  2. from that ratio, compute a better guess and try it
  3. if still off, walk outward one step at a time until it lands exactly

Self-paced: read the SMALL number each time, type it, press Enter.

    python fan_tune.py            # tune for 8008
    python fan_tune.py 1234
"""
import json
import os
import sys
import threading
import time

from aio_screen import AioScreen, Stats

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


def ask(poster, send_value, note=""):
    poster.value = send_value
    time.sleep(0.8)
    print(f"\n  sending {send_value}{('   ' + note) if note else ''}")
    while True:
        raw = input("  small number on the panel? ").strip()
        if raw.isdigit():
            return int(raw)
        if raw == "":
            print("  (please type the number you see)")
        else:
            print("  (digits only)")


def main():
    target = int(sys.argv[1]) if len(sys.argv) > 1 else 8008
    print(f"\nTuning the fan slot so it displays {target}.")
    print("The big readout sits at 42 throughout, so the small one is unambiguous.")

    # fan_scale must be OFF while measuring, or we would be tuning a correction
    # on top of a correction.
    with AioScreen(fan_scale=None) as screen:
        poster = Poster(screen)
        poster.start()
        try:
            seen = ask(poster, target, "(the raw target)")
            if seen == target:
                print(f"\n  It already displays {target} exactly -- no correction needed.")
                save_scale(1.0)
                return

            scale = seen / target
            print(f"\n  {target} displayed as {seen}  ->  ratio {scale:.6f}")

            guess = max(0, min(0xFFFF, round(target / scale)))
            seen2 = ask(poster, guess, f"(computed from that ratio)")
            if seen2 == target:
                finish(target, guess)
                return

            # Walk outward from the guess: +1, -1, +2, -2 ... The firmware's
            # rounding makes several inputs map to the same output, so a step
            # or two either way normally lands it.
            print(f"\n  {guess} displayed as {seen2}, not {target}. Walking outward.")
            for step in range(1, 9):
                for candidate in (guess + step, guess - step):
                    if not 0 <= candidate <= 0xFFFF:
                        continue
                    got = ask(poster, candidate, f"(step {step})")
                    if got == target:
                        finish(target, candidate)
                        return
            print("\n  Could not land on it exactly. Send me fan_calibration.txt "
                  "(RUN_FAN_CALIBRATE.bat) and I will work out the rule.")
        finally:
            poster.stop.set()
            poster.join(timeout=2)


def finish(target, send_value):
    scale = target / send_value
    print(f"\n  Sending {send_value} displays {target}.")
    print(f"  fan_scale = {scale:.8f}")
    save_scale(scale)


def save_scale(scale):
    try:
        cfg = {}
        if os.path.exists(CONFIG_PATH):
            with open(CONFIG_PATH, encoding="utf-8") as fh:
                cfg = json.load(fh)
        cfg["fan_scale"] = round(scale, 8)
        with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
            json.dump(cfg, fh, indent=2)
        print(f"  saved to {CONFIG_PATH}")
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
