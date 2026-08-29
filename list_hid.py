"""
list_hid.py -- show every HID interface on this PC, flag the AIO panel.

Run this first. If the panel's VID/PID is not in the list, nothing else in
this folder can work and the problem is USB/plumbing, not protocol.
"""
from aio_screen import VENDOR_ID, PRODUCT_ID, REPORT_LEN, list_devices

rows = list_devices()
print(f"{len(rows)} HID interfaces present\n")
hits = 0
for d in sorted(rows, key=lambda x: (x["vendor_id"], x["product_id"], x["path"])):
    match = d["vendor_id"] == VENDOR_ID and d["product_id"] == PRODUCT_ID
    if match:
        hits += 1
    mark = "   <<<<<< AIO PANEL" if match else ""
    print(f"  {d['vendor_id']:04X}:{d['product_id']:04X}  "
          f"page=0x{d['usage_page']:04X} usage=0x{d['usage']:04X}  "
          f"out={d['output_len']:>3d} in={d.get('input_len', 0):>3d}  "
          f"{d['manufacturer']!r} {d['product']!r}{mark}")
    if match:
        print(f"          path={d['path']}")

print()
if hits:
    print(f"Found the panel on {hits} interface(s).")
    good = [d for d in rows
            if d["vendor_id"] == VENDOR_ID and d["product_id"] == PRODUCT_ID
            and d["output_len"] >= REPORT_LEN + 1]
    if good:
        print(f"{len(good)} of them accept a {REPORT_LEN}-byte output report. Good to go.")
    else:
        print("WARNING: none reported an output report long enough for a "
              f"{REPORT_LEN}-byte payload -- tell me the out= values above.")
else:
    print(f"NOT FOUND: expected {VENDOR_ID:04X}:{PRODUCT_ID:04X}, read straight out of "
          "PC_Monitor.exe's own enumeration loop.")
    print("If PC Monitor drives your screen fine but this says not found, tell me --")
    print("it would mean the app talks to a different device than I traced.")
