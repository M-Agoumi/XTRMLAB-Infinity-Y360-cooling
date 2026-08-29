"""
sensors.py -- real CPU temperature and fan RPM, via LibreHardwareMonitor.

Windows gives an ordinary process no way to read CPU temperature or a
motherboard fan tacho: both live behind the SuperIO chip / MSR registers,
which need a kernel driver. That is exactly why the vendor app ships
PC_Monitor.sys. LibreHardwareMonitor solves the same problem with its own
signed ring0 driver, and its library is already sitting on this machine at

    C:\\Program Files (x86)\\PC Monitor\\LibreHardwareMonitorLib.dll

(open source, MPL-2.0 -- the vendor bundles it for the same reason).

So: load that assembly through pythonnet and read the sensors directly.

    REQUIRES ADMINISTRATOR. Without it the library loads fine but silently
    reports no temperatures, because its driver cannot start.

    pip install pythonnet

If you would rather not run elevated, run the LibreHardwareMonitor GUI (it
elevates itself), enable its web server, and use demo_stats.py --lhm
http://localhost:8085/data.json instead -- same numbers, no admin here.
"""

from __future__ import annotations

import ctypes
import os

# Searched in order. `lib/` is where INSTALL.bat puts a downloaded copy; the
# PC Monitor path is where the vendor app already has one on machines that
# shipped with it.
DLL_CANDIDATES = (
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib",
                 "LibreHardwareMonitorLib.dll"),
    r"C:\Program Files (x86)\PC Monitor\LibreHardwareMonitorLib.dll",
    r"C:\Program Files\LibreHardwareMonitor\LibreHardwareMonitorLib.dll",
    r"C:\Program Files (x86)\LibreHardwareMonitor\LibreHardwareMonitorLib.dll",
)


def find_dll(explicit: str | None = None) -> str | None:
    """First LibreHardwareMonitorLib.dll that actually exists, or None."""
    for path in ([explicit] if explicit else []) + list(DLL_CANDIDATES):
        if path and os.path.exists(path):
            return path
    return None


DEFAULT_DLL = DLL_CANDIDATES[1]


class SensorError(RuntimeError):
    pass


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:  # noqa: BLE001
        return False


class LhmSensors:
    """Thin wrapper over LibreHardwareMonitor's Computer object."""

    def __init__(self, dll_path: str | None = None):
        dll_path = find_dll(dll_path)
        if not dll_path:
            raise SensorError(
                "LibreHardwareMonitorLib.dll was not found. Looked in:\n"
                + "\n".join(f"    {c}" for c in DLL_CANDIDATES)
                + "\n\nRun INSTALL.bat to download it, or pass --dll with a path.")
        self.dll_path = dll_path
        try:
            # pythonnet 3 defaults to .NET Core; this DLL is net472, so ask
            # for the .NET Framework runtime explicitly before clr is imported.
            try:
                from pythonnet import load as _load
                _load("netfx")
            except Exception:  # noqa: BLE001
                pass                     # pythonnet 2.x, or already loaded
            import clr
        except ImportError as e:
            raise SensorError(f"pythonnet is not installed ({e}). pip install pythonnet") from e

        clr.AddReference(dll_path)
        from LibreHardwareMonitor.Hardware import Computer  # noqa: PLC0415

        self._computer = Computer()
        self._computer.IsCpuEnabled = True
        self._computer.IsMotherboardEnabled = True      # SuperIO: fan RPMs
        self._computer.IsGpuEnabled = True
        self._computer.IsMemoryEnabled = True
        self._computer.IsStorageEnabled = False
        self._computer.Open()
        self._admin = is_admin()

    # -- internals ----------------------------------------------------
    def _refresh(self):
        for hw in self._computer.Hardware:
            hw.Update()
            for sub in hw.SubHardware:       # SuperIO hangs off the motherboard
                sub.Update()

    def _walk(self):
        for hw in self._computer.Hardware:
            for s in hw.Sensors:
                yield hw, s
            for sub in hw.SubHardware:
                for s in sub.Sensors:
                    yield sub, s

    # -- public -------------------------------------------------------
    def snapshot(self) -> dict:
        """{(hardware, sensor_type, name): value} for everything readable."""
        self._refresh()
        out = {}
        for hw, s in self._walk():
            if s.Value is not None:
                out[(str(hw.Name), str(s.SensorType), str(s.Name))] = float(s.Value)
        return out

    def list_sensors(self):
        rows = []
        for (hw, kind, name), value in sorted(self.snapshot().items()):
            rows.append((hw, kind, name, value))
        return rows

    def fans(self, refresh=True):
        """[(hardware, name, rpm)] for every fan tacho, in discovery order."""
        if refresh:
            self._refresh()
        out = []
        for hw, sen in self._walk():
            if str(sen.SensorType) == "Fan" and sen.Value is not None:
                out.append((str(hw.Name), str(sen.Name), float(sen.Value)))
        return out

    def rows(self, refresh=True):
        """[(hardware, kind, name, value)] for everything readable, one refresh."""
        if refresh:
            self._refresh()
        out = []
        for hw, sen in self._walk():
            if sen.Value is not None:
                out.append((str(hw.Name), str(sen.SensorType), str(sen.Name),
                            float(sen.Value)))
        return out

    def temps(self, refresh=True):
        """[(hardware, name, celsius)] for every temperature sensor."""
        if refresh:
            self._refresh()
        out = []
        for hw, sen in self._walk():
            if str(sen.SensorType) == "Temperature" and sen.Value is not None:
                out.append((str(hw.Name), str(sen.Name), float(sen.Value)))
        return out

    @staticmethod
    def _pick(rows, prefer):
        """
        Choose one (hardware, name, value) row.

        `prefer` may be an exact-ish sensor name, a substring, or "#3"/"3" to
        take the third row as listed. Matching goes strictest-first so that
        asking for "CPU Fan" cannot silently land on "CPU OPT Fan" -- which is
        exactly the trap on an AIO build, where CPU_OPT usually drives the
        pump and spins far faster than the radiator fans.
        """
        if not rows:
            return None
        if prefer:
            want = str(prefer).strip().lower()
            idx = want.lstrip("#")
            if idx.isdigit():
                i = int(idx)
                if 0 <= i < len(rows):
                    return rows[i]
            for row in rows:                              # exact
                if row[1].lower() == want:
                    return row
            for row in rows:                              # prefix
                if row[1].lower().startswith(want):
                    return row
            for row in rows:                              # substring
                if want in row[1].lower():
                    return row
            for row in rows:                              # hardware name
                if want in row[0].lower():
                    return row
        return None

    def pick_temp(self, prefer=None, strict=False):
        rows = self.temps()
        hit = self._pick(rows, prefer)
        if hit:
            return hit
        if prefer and strict:
            # A named sensor that is momentarily missing must NOT silently
            # become a different sensor -- that is how a stray high reading
            # flashes onto the panel for one frame.
            return None
        # No preference: CPU package first, else the hottest CPU core.
        for row in rows:
            n = row[1].lower()
            if "package" in n or "tctl" in n:
                return row
        cores = [r for r in rows if r[1].lower().startswith("core")
                 or "cores" in r[1].lower()]
        if cores:
            return max(cores, key=lambda r: r[2])
        return rows[0] if rows else None

    def pick_fan(self, prefer=None, strict=False):
        rows = self.fans()
        hit = self._pick(rows, prefer)
        if hit:
            return hit
        if prefer and strict:
            return None
        # No preference: the FIRST fan that is actually turning. SuperIO chips
        # enumerate in header order and #1 is the CPU header on every board
        # seen so far, so this beats both "fastest" (which picks the pump on
        # CPU_OPT) and "slowest" (which picks whichever case fan idles lowest).
        spinning = [r for r in rows if r[2] > 0]
        if spinning:
            return spinning[0]
        return rows[0] if rows else None

    def cpu_temp(self, prefer=None, strict=False):
        hit = self.pick_temp(prefer, strict)
        return hit[2] if hit else None

    def fan_rpm(self, prefer=None, strict=False):
        hit = self.pick_fan(prefer, strict)
        return hit[2] if hit else None

    def read_pair(self, temp_prefer=None, fan_prefer=None, strict=True):
        """
        Both values from ONE hardware refresh.

        Calling cpu_temp() and fan_rpm() separately refreshes every sensor
        twice per cycle, which on this box costs hundreds of milliseconds and
        makes the update cadence lumpy.
        """
        self._refresh()
        temps, fans = [], []
        for hw, sen in self._walk():
            if sen.Value is None:
                continue
            kind = str(sen.SensorType)
            if kind == "Temperature":
                temps.append((str(hw.Name), str(sen.Name), float(sen.Value)))
            elif kind == "Fan":
                fans.append((str(hw.Name), str(sen.Name), float(sen.Value)))

        t = self._pick(temps, temp_prefer)
        if t is None and not (temp_prefer and strict):
            for row in temps:
                if "package" in row[1].lower() or "tctl" in row[1].lower():
                    t = row
                    break
        f = self._pick(fans, fan_prefer)
        if f is None and not (fan_prefer and strict):
            spinning = [r for r in fans if r[2] > 0]
            f = spinning[0] if spinning else (fans[0] if fans else None)
        return t, f

    def close(self):
        try:
            self._computer.Close()
        except Exception:  # noqa: BLE001
            pass


def main():
    import argparse
    ap = argparse.ArgumentParser(description="list every sensor LibreHardwareMonitor can see")
    ap.add_argument("--dll", default=None, help="path to LibreHardwareMonitorLib.dll")
    args = ap.parse_args()

    if not is_admin():
        print("!! NOT running as administrator -- temperatures and fan RPMs will be missing.\n")
    lhm = LhmSensors(args.dll)
    try:
        rows = lhm.list_sensors()
        print(f"{len(rows)} readable sensors\n")
        for hw, kind, name, value in rows:
            flag = ""
            if kind == "Fan":
                flag = "   <-- fan"
            elif kind == "Temperature" and ("package" in name.lower() or "tctl" in name.lower()):
                flag = "   <-- CPU package temp"
            print(f"  {hw:<28} {kind:<12} {name:<28} {value:>10.1f}{flag}")
        print("\n--- fans, as the demo lists them (index | name | rpm) ---")
        for i, (hw, name, value) in enumerate(lhm.fans()):
            print(f"  [{i}]  {name:<24} {value:>8.0f} rpm    ({hw})")
        print("\n--- temperatures ---")
        for i, (hw, name, value) in enumerate(lhm.temps()):
            print(f"  [{i}]  {name:<24} {value:>8.1f} C      ({hw})")
        t, f = lhm.pick_temp(), lhm.pick_fan()
        print(f"\ndefault temp choice : {t[1]!r} = {t[2]:.1f} C" if t else "\nno temperature found")
        print(f"default fan choice  : {f[1]!r} = {f[2]:.0f} rpm" if f else "no fan found")
        print("\nCompare these against your motherboard tool, then pass the one you want:")
        print('   python demo_stats.py --admin-sensors --big cpu_temp --small cpu_fan \\')
        print('          --temp "CPU Package" --fan "#0"')
    finally:
        lhm.close()


if __name__ == "__main__":
    main()
