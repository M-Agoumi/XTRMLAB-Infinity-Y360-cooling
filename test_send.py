"""
test_send.py -- post one frame of deliberately distinctive values.

Every field gets a number you would never see naturally, so you can read
the panel and tell me which readout shows which number. That confirms
the field map in one shot -- and catches any field I mapped wrongly.

    CPU:  temp 55   load 44%   clock 1234 MHz   fan 2345 rpm   power 66 W
    GPU:  temp 77   load 88%   clock 1999 MHz   fan 3456 rpm   power 111 W
    RAM:  33%       total 4096 MB
    DISK: 22%       total 1234 GB
    Clock: 03:07 on 2029-11-22   (deliberately wrong, so it is unmistakable)

It holds for 30 seconds, re-posting once a second, then exits. The panel
may fall back to whatever it showed before once the posts stop.

    python test_send.py
"""
import datetime
import time

from aio_screen import AioScreen, Stats, build_report

DEMO = Stats(
    cpu_temp=55, cpu_load=44, cpu_clock=1234, cpu_fan=2345, cpu_power=66,
    gpu_temp=77, gpu_load=88, gpu_clock=1999, gpu_fan=3456, gpu_power=111,
    mem_load=33, mem_total_mb=4096,
    disk_load=22, disk_total_gb=1234,
    when=datetime.datetime(2029, 11, 22, 3, 7),
)


def main():
    report = build_report(DEMO)
    print("report bytes:")
    print("  " + " ".join(f"{b:02x}" for b in report[:32]))
    print(f"  checksum byte [29] = 0x{report[29]:02x}\n")

    with AioScreen() as screen:
        print(f"panel open at {screen.path!r}")
        print("posting for 30s -- WATCH THE SCREEN and note which value lands where\n")
        for i in range(30):
            screen.send(DEMO)
            print(f"  frame {i + 1}/30", end="\r", flush=True)
            time.sleep(1.0)
    print("\ndone.")


if __name__ == "__main__":
    from panel_lock import PanelBusy

    try:
        main()
    except PanelBusy as busy:
        print(f"\n{busy}\n")
        raise SystemExit(1)
