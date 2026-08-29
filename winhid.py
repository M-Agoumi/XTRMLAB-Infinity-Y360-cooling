"""
winhid.py -- minimal HID access on Windows using nothing but Windows itself.

Why this exists: the obvious route, `pip install hidapi`, installs a Cython
binding that does NOT ship the native library -- it hunts for hidapi.dll on
PATH and raises ImportError when it finds none. The vendor app has a
hidapi.dll, but it is 32-bit (the app is x86) and your Python is 64-bit, so
it can never load. Rather than make you chase a matching DLL build, this
talks straight to the Windows HID stack (setupapi.dll + hid.dll) through
ctypes, which is always present and always the right bitness.

Only what this project needs: enumerate, open, write an output report.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes

setupapi = ctypes.WinDLL("setupapi", use_last_error=True)
hid = ctypes.WinDLL("hid", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
DIGCF_PRESENT = 0x02
DIGCF_DEVICEINTERFACE = 0x10
GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
FILE_SHARE_READ = 0x01
FILE_SHARE_WRITE = 0x02
OPEN_EXISTING = 3


class GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]


class SP_DEVICE_INTERFACE_DATA(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("InterfaceClassGuid", GUID),
                ("Flags", wintypes.DWORD), ("Reserved", ctypes.POINTER(ctypes.c_ulong))]


class HIDD_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("Size", wintypes.ULONG), ("VendorID", wintypes.USHORT),
                ("ProductID", wintypes.USHORT), ("VersionNumber", wintypes.USHORT)]


class HIDP_CAPS(ctypes.Structure):
    _fields_ = [
        ("Usage", wintypes.USHORT), ("UsagePage", wintypes.USHORT),
        ("InputReportByteLength", wintypes.USHORT),
        ("OutputReportByteLength", wintypes.USHORT),
        ("FeatureReportByteLength", wintypes.USHORT),
        ("Reserved", wintypes.USHORT * 17),
        ("NumberLinkCollectionNodes", wintypes.USHORT),
        ("NumberInputButtonCaps", wintypes.USHORT),
        ("NumberInputValueCaps", wintypes.USHORT),
        ("NumberInputDataIndices", wintypes.USHORT),
        ("NumberOutputButtonCaps", wintypes.USHORT),
        ("NumberOutputValueCaps", wintypes.USHORT),
        ("NumberOutputDataIndices", wintypes.USHORT),
        ("NumberFeatureButtonCaps", wintypes.USHORT),
        ("NumberFeatureValueCaps", wintypes.USHORT),
        ("NumberFeatureDataIndices", wintypes.USHORT),
    ]


setupapi.SetupDiGetClassDevsW.restype = wintypes.HANDLE
setupapi.SetupDiGetClassDevsW.argtypes = [ctypes.POINTER(GUID), wintypes.LPCWSTR,
                                          wintypes.HWND, wintypes.DWORD]
setupapi.SetupDiEnumDeviceInterfaces.argtypes = [
    wintypes.HANDLE, ctypes.c_void_p, ctypes.POINTER(GUID), wintypes.DWORD,
    ctypes.POINTER(SP_DEVICE_INTERFACE_DATA)]
setupapi.SetupDiEnumDeviceInterfaces.restype = wintypes.BOOL
setupapi.SetupDiGetDeviceInterfaceDetailW.argtypes = [
    wintypes.HANDLE, ctypes.POINTER(SP_DEVICE_INTERFACE_DATA), ctypes.c_void_p,
    wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
setupapi.SetupDiGetDeviceInterfaceDetailW.restype = wintypes.BOOL
setupapi.SetupDiDestroyDeviceInfoList.argtypes = [wintypes.HANDLE]

kernel32.CreateFileW.restype = wintypes.HANDLE
kernel32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                 ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD,
                                 wintypes.HANDLE]
kernel32.WriteFile.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
                               ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
kernel32.WriteFile.restype = wintypes.BOOL
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

hid.HidD_GetHidGuid.argtypes = [ctypes.POINTER(GUID)]
hid.HidD_GetAttributes.argtypes = [wintypes.HANDLE, ctypes.POINTER(HIDD_ATTRIBUTES)]
hid.HidD_GetAttributes.restype = wintypes.BOOLEAN
hid.HidD_GetPreparsedData.argtypes = [wintypes.HANDLE, ctypes.POINTER(ctypes.c_void_p)]
hid.HidD_GetPreparsedData.restype = wintypes.BOOLEAN
hid.HidD_FreePreparsedData.argtypes = [ctypes.c_void_p]
hid.HidP_GetCaps.argtypes = [ctypes.c_void_p, ctypes.POINTER(HIDP_CAPS)]
hid.HidD_GetManufacturerString.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.ULONG]
hid.HidD_GetProductString.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.ULONG]
hid.HidD_SetOutputReport.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.ULONG]
hid.HidD_SetOutputReport.restype = wintypes.BOOLEAN


def _wstr(fn, handle):
    buf = ctypes.create_unicode_buffer(260)
    try:
        if fn(handle, buf, ctypes.sizeof(buf)):
            return buf.value
    except Exception:  # noqa: BLE001
        pass
    return ""


def _open(path, write_only=False):
    access = GENERIC_WRITE if write_only else (GENERIC_READ | GENERIC_WRITE)
    h = kernel32.CreateFileW(path, access, FILE_SHARE_READ | FILE_SHARE_WRITE,
                             None, OPEN_EXISTING, 0, None)
    return None if h == INVALID_HANDLE_VALUE else h


def enumerate_devices():
    """Every present HID interface, as dicts."""
    guid = GUID()
    hid.HidD_GetHidGuid(ctypes.byref(guid))
    hdev = setupapi.SetupDiGetClassDevsW(ctypes.byref(guid), None, None,
                                         DIGCF_PRESENT | DIGCF_DEVICEINTERFACE)
    if hdev == INVALID_HANDLE_VALUE:
        raise OSError("SetupDiGetClassDevs failed")

    out = []
    try:
        i = 0
        while True:
            did = SP_DEVICE_INTERFACE_DATA()
            did.cbSize = ctypes.sizeof(SP_DEVICE_INTERFACE_DATA)
            if not setupapi.SetupDiEnumDeviceInterfaces(hdev, None, ctypes.byref(guid),
                                                        i, ctypes.byref(did)):
                break
            i += 1
            need = wintypes.DWORD(0)
            setupapi.SetupDiGetDeviceInterfaceDetailW(hdev, ctypes.byref(did), None, 0,
                                                      ctypes.byref(need), None)
            if not need.value:
                continue
            buf = ctypes.create_string_buffer(need.value)
            # SP_DEVICE_INTERFACE_DETAIL_DATA_W.cbSize: 8 on 64-bit, 6 on 32-bit
            ctypes.cast(buf, ctypes.POINTER(wintypes.DWORD))[0] = \
                8 if ctypes.sizeof(ctypes.c_void_p) == 8 else 6
            if not setupapi.SetupDiGetDeviceInterfaceDetailW(
                    hdev, ctypes.byref(did), buf, need.value, ctypes.byref(need), None):
                continue
            path = ctypes.wstring_at(ctypes.addressof(buf) + ctypes.sizeof(wintypes.DWORD))

            h = _open(path)
            if h is None:
                # Some devices (keyboards/mice) refuse read+write; still report them.
                out.append({"path": path, "vendor_id": 0, "product_id": 0,
                            "usage_page": 0, "usage": 0, "output_len": 0,
                            "manufacturer": "", "product": "", "opened": False})
                continue
            try:
                attrs = HIDD_ATTRIBUTES()
                attrs.Size = ctypes.sizeof(attrs)
                hid.HidD_GetAttributes(h, ctypes.byref(attrs))
                caps = HIDP_CAPS()
                pp = ctypes.c_void_p()
                if hid.HidD_GetPreparsedData(h, ctypes.byref(pp)):
                    hid.HidP_GetCaps(pp, ctypes.byref(caps))
                    hid.HidD_FreePreparsedData(pp)
                out.append({
                    "path": path,
                    "vendor_id": attrs.VendorID,
                    "product_id": attrs.ProductID,
                    "version": attrs.VersionNumber,
                    "usage_page": caps.UsagePage,
                    "usage": caps.Usage,
                    "output_len": caps.OutputReportByteLength,
                    "input_len": caps.InputReportByteLength,
                    "manufacturer": _wstr(hid.HidD_GetManufacturerString, h),
                    "product": _wstr(hid.HidD_GetProductString, h),
                    "opened": True,
                })
            finally:
                kernel32.CloseHandle(h)
    finally:
        setupapi.SetupDiDestroyDeviceInfoList(hdev)
    return out


class Device:
    """One open HID interface you can post output reports to."""

    def __init__(self, path, output_len=0):
        self.path = path
        self.output_len = output_len
        self._h = _open(path, write_only=True) or _open(path)
        if self._h is None:
            err = ctypes.get_last_error()
            raise OSError(f"could not open HID path (WinError {err}): {path}")
        if not self.output_len:
            caps = HIDP_CAPS()
            pp = ctypes.c_void_p()
            if hid.HidD_GetPreparsedData(self._h, ctypes.byref(pp)):
                hid.HidP_GetCaps(pp, ctypes.byref(caps))
                hid.HidD_FreePreparsedData(pp)
            self.output_len = caps.OutputReportByteLength

    def write(self, data: bytes):
        """
        Post one output report. `data` must start with the report ID.
        Windows demands exactly OutputReportByteLength bytes, so the buffer
        is padded or trimmed to fit.
        """
        n = self.output_len or len(data)
        buf = ctypes.create_string_buffer(bytes(data[:n]).ljust(n, b"\x00"), n)
        written = wintypes.DWORD(0)
        if kernel32.WriteFile(self._h, buf, n, ctypes.byref(written), None):
            return written.value
        werr = ctypes.get_last_error()
        # Fall back to the control-transfer path for devices with no OUT endpoint.
        if hid.HidD_SetOutputReport(self._h, buf, n):
            return n
        raise OSError(f"HID write failed (WriteFile WinError {werr}, "
                      f"HidD_SetOutputReport WinError {ctypes.get_last_error()})")

    def close(self):
        if self._h is not None:
            kernel32.CloseHandle(self._h)
            self._h = None
