# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for "AIO Screen.exe" -- one file, no Python needed.

Build with BUILD_EXE.bat (which installs PyInstaller and calls this).

Notes on the awkward parts:

  * uac_admin=True bakes an elevation manifest into the exe. Reading CPU
    temperature needs a kernel driver, so without it the app runs and silently
    reports 0. Better to prompt than to lie.
  * console=False: it is a tray app. That means nothing can be printed, which
    is why the exe supports --doctor (writes a report and opens it in Notepad)
    and why everything else goes to aio_daemon.log.
  * pythonnet needs clr_loader and its runtime config collected explicitly;
    PyInstaller does not always follow the .NET side on its own.
  * LibreHardwareMonitorLib.dll is bundled if present. It is MPL-2.0, which
    permits redistributing the unmodified binary as long as the licence
    travels with it -- lib/THIRD-PARTY.txt does that, and is bundled too.
"""

import os
from PyInstaller.utils.hooks import collect_all, collect_submodules

block_cipher = None
here = os.path.abspath(os.getcwd())

datas = [
    ("icon.ico", "."),
    ("config.example.json", "."),
    ("README.md", "."),
    ("LICENSE", "."),
]

# bundle the sensor library if it has been fetched, plus its licence notice
for name in ("LibreHardwareMonitorLib.dll", "HidSharp.dll", "THIRD-PARTY.txt"):
    path = os.path.join(here, "lib", name)
    if os.path.exists(path):
        datas.append((path, "lib"))

hiddenimports = [
    "pystray._win32",
    "PIL.Image",
    "clr_loader",
    "clr_loader.netfx",
    "pythonnet",
    "metrics",
    "sensors",
    "winhid",
    "panel_lock",
    "aio_screen",
    "doctor",
]
hiddenimports += collect_submodules("clr_loader")

for pkg in ("pythonnet", "clr_loader"):
    try:
        pkg_datas, pkg_binaries, pkg_hidden = collect_all(pkg)
        datas += pkg_datas
        hiddenimports += pkg_hidden
    except Exception:
        pass

a = Analysis(
    ["aio_daemon.pyw"],
    pathex=[here],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "numpy", "pytest"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="AIO Screen",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    icon="icon.ico",
    uac_admin=True,
    version_file=None,
)
