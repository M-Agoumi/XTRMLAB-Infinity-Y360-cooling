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
import sys

# Searched in order. `lib/` is where INSTALL.bat puts a downloaded copy; the
# PC Monitor path is where the vendor app already has one on machines that
# shipped with it.
def _search_roots():
    roots = [os.path.dirname(os.path.abspath(__file__))]
    if getattr(sys, "frozen", False):
        roots.insert(0, getattr(sys, "_MEIPASS", ""))          # bundled copy
        roots.insert(1, os.path.dirname(os.path.abspath(sys.executable)))
    return [r for r in roots if r]


DLL_CANDIDATES = tuple(
    [os.path.join(root, "lib", "LibreHardwareMonitorLib.dll") for root in _search_roots()]
    + [os.path.join(root, "LibreHardwareMonitorLib.dll") for root in _search_roots()]
) + (
    r"C:\Program Files (x86)\PC Monitor\LibreHardwareMonitorLib.dll",
    r"C:\Program Files\LibreHardwareMonitor\LibreHardwareMonitorLib.dll",
    r"C:\Program Files (x86)\LibreHardwareMonitor\LibreHardwareMonitorLib.dll",
)


# LibreHardwareMonitor up to 0.9.4 reaches the hardware through WinRing0,
# which it unpacks next to the running exe as <exe>.sys (pythonw.sys here).
# Microsoft Defender quarantines that file as VulnerableDriver:WinNT/Winring0
# the moment it appears, and the library then quietly returns no CPU or
# motherboard readings -- only the GPU, which goes through the vendor driver.
# 0.9.5 replaced WinRing0 with PawnIO, a signed driver Defender leaves alone.
PAWNIO_SINCE = (0, 9, 5)


def dll_version(path: str) -> tuple | None:
    """File version of a DLL as (major, minor, build, revision), or None."""
    try:
        ver = ctypes.windll.version
        size = ver.GetFileVersionInfoSizeW(path, None)
        if not size:
            return None
        buf = ctypes.create_string_buffer(size)
        if not ver.GetFileVersionInfoW(path, 0, size, buf):
            return None
        ptr, n = ctypes.c_void_p(), ctypes.c_uint()
        if not ver.VerQueryValueW(buf, "\\", ctypes.byref(ptr), ctypes.byref(n)):
            return None
        # VS_FIXEDFILEINFO: signature, struc version, then FileVersionMS/LS
        ms, ls = ctypes.cast(ptr, ctypes.POINTER(ctypes.c_uint32))[2:4]
        return (ms >> 16, ms & 0xFFFF, ls >> 16, ls & 0xFFFF)
    except Exception:  # noqa: BLE001
        return None


def uses_winring0(path: str) -> bool:
    """True for a library old enough to need the driver Defender blocks."""
    v = dll_version(path)
    return v is not None and v[:3] < PAWNIO_SINCE


def find_dll(explicit: str | None = None) -> str | None:
    """
    The LibreHardwareMonitorLib.dll to load, or None.

    An explicit path always wins. Otherwise the first candidate that uses
    PawnIO, falling back to the first that exists at all: the vendor app's
    copy is 0.9.4, and picking it over a newer one means no CPU readings.
    """
    if explicit and os.path.exists(explicit):
        return explicit
    present = [p for p in DLL_CANDIDATES if os.path.exists(p)]
    for path in present:
        if not uses_winring0(path):
            return path
    return present[0] if present else None


def pawnio_installed() -> bool:
    """Is the PawnIO driver service registered? 0.9.5+ needs it."""
    try:
        import winreg
        winreg.CloseKey(winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Services\PawnIO"))
        return True
    except OSError:
        return False


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

        # 0.9.5+ depends on several assemblies shipped beside it; .NET only
        # finds them if their folder is on the probing path, which pythonnet
        # builds from sys.path.
        dll_dir = os.path.dirname(os.path.abspath(dll_path))
        if dll_dir not in sys.path:
            sys.path.append(dll_dir)
        try:
            clr.AddReference(dll_path)
        except Exception as e:  # noqa: BLE001
            # Files unpacked from a zip that Windows saw arrive from the
            # internet carry a Zone.Identifier stream, and .NET Framework
            # refuses to load them ("network location ... loadFromRemoteSources").
            blocked = sorted(n for n in os.listdir(dll_dir)
                             if n.lower().endswith(".dll")
                             and os.path.exists(os.path.join(dll_dir, n + ":Zone.Identifier")))
            if blocked:
                raise SensorError(
                    f"Windows has marked {len(blocked)} DLL(s) in {dll_dir} as downloaded "
                    "from the internet, so .NET will not load them. Unblock them with:\n"
                    f'    Unblock-File "{dll_dir}\\*.dll"') from e
            raise
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
    def cpu_blind(self) -> bool:
        """
        True when the CPU is listed but none of its temperatures read.

        That is the driver failing to start, not a missing sensor: the
        library still enumerates every CPU core, it just gets no values.
        """
        self._refresh()
        seen = False
        for hw, sen in self._walk():
            if str(hw.HardwareType) == "Cpu" and str(sen.SensorType) == "Temperature":
                seen = True
                if sen.Value is not None:
                    return False
        return seen

    def blind_reason(self) -> str:
        """Best guess at why cpu_blind() is true, in one line."""
        if not self._admin:
            return "not running as administrator, so the sensor driver cannot start"
        if uses_winring0(self.dll_path):
            v = ".".join(map(str, (dll_version(self.dll_path) or ())[:3]))
            return (f"LibreHardwareMonitorLib {v} uses the WinRing0 driver, which "
                    "Microsoft Defender quarantines; install LibreHardwareMonitor "
                    "0.9.5 or newer (it uses PawnIO) into lib\\")
        if not pawnio_installed():
            return "the PawnIO driver is not installed (https://pawnio.eu)"
        return "the sensor driver did not start; check Defender's protection history"

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
