# install.ps1 -- one-shot setup: Python packages + LibreHardwareMonitorLib.dll
#
# The DLL is NOT bundled with this project. It belongs to LibreHardwareMonitor
# (MPL-2.0) and is downloaded from that project's own GitHub releases, so you
# get it from the source rather than from a copy someone repackaged.
#
# On a machine that shipped with the vendor "PC Monitor" app the DLL is already
# present, and this script uses that copy instead of downloading anything.

param([switch]$DllOnly)

$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$lib  = Join-Path $here 'lib'

function Say($msg)  { Write-Host $msg }
function Good($msg) { Write-Host "  OK    $msg" -ForegroundColor Green }
function Bad($msg)  { Write-Host "  FAIL  $msg" -ForegroundColor Red }
function Warn($msg) { Write-Host "  WARN  $msg" -ForegroundColor Yellow }

Say ""
Say "======================================================================"
Say " aio_screen setup"
Say "======================================================================"
Say ""

if ($DllOnly) {
    # BUILD_EXE.bat calls us just to fetch the DLL for bundling.
    $lib = Join-Path $here 'lib'
    $existing = @(
        (Join-Path $lib 'LibreHardwareMonitorLib.dll'),
        'C:\Program Files (x86)\PC Monitor\LibreHardwareMonitorLib.dll'
    ) | Where-Object { Test-Path $_ } | Select-Object -First 1
    if ($existing -and $existing -notlike "$lib*") {
        New-Item -ItemType Directory -Path $lib -Force | Out-Null
        Copy-Item $existing (Join-Path $lib 'LibreHardwareMonitorLib.dll') -Force
        $sharp = Join-Path (Split-Path $existing) 'HidSharp.dll'
        if (Test-Path $sharp) { Copy-Item $sharp (Join-Path $lib 'HidSharp.dll') -Force }
        Good "copied the sensor library into lib\ for bundling"
        exit 0
    }
}

# --- 1. python --------------------------------------------------------------
if (-not $DllOnly) {
Say "[1/4] Python"
try {
    $pyv = & python -c "import sys;print('%d.%d %s-bit' % (sys.version_info[0], sys.version_info[1], 64 if sys.maxsize > 2**32 else 32))"
    Good "python $pyv"
} catch {
    Bad "python is not on PATH. Install it from python.org and tick 'Add to PATH'."
    exit 1
}

# --- 2. packages ------------------------------------------------------------
Say ""
Say "[2/4] Python packages"
$req = Join-Path $here 'requirements.txt'
if (Test-Path $req) {
    & python -m pip install --disable-pip-version-check -r $req
} else {
    & python -m pip install --disable-pip-version-check psutil pythonnet pystray pillow
}
if ($LASTEXITCODE -ne 0) { Bad "pip failed -- see the output above."; exit 1 }
Good "packages installed"

}

# --- 3. LibreHardwareMonitorLib.dll ----------------------------------------
Say ""
Say "[3/4] LibreHardwareMonitorLib.dll (for CPU temperature and fan RPM)"

$targets = @(
    (Join-Path $lib 'LibreHardwareMonitorLib.dll'),
    'C:\Program Files (x86)\PC Monitor\LibreHardwareMonitorLib.dll',
    'C:\Program Files\LibreHardwareMonitor\LibreHardwareMonitorLib.dll'
)
$found = $targets | Where-Object { Test-Path $_ } | Select-Object -First 1

if ($found) {
    Good "already present: $found"
} else {
    Say "  not found locally -- fetching from the LibreHardwareMonitor releases"
    try {
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        $api = 'https://api.github.com/repos/LibreHardwareMonitor/LibreHardwareMonitor/releases/latest'
        $rel = Invoke-RestMethod -Uri $api -Headers @{ 'User-Agent' = 'aio_screen-setup' }
        Say "  latest release: $($rel.tag_name)"

        # prefer the .NET Framework 4.7.2 build -- that is what the DLL targets
        $asset = $rel.assets | Where-Object { $_.name -match '\.zip$' -and $_.name -match 'net472' } | Select-Object -First 1
        if (-not $asset) {
            $asset = $rel.assets | Where-Object { $_.name -match '\.zip$' } | Select-Object -First 1
        }
        if (-not $asset) { throw "no .zip asset in the latest release" }

        $tmp = Join-Path $env:TEMP ("lhm_" + [Guid]::NewGuid().ToString('N'))
        New-Item -ItemType Directory -Path $tmp -Force | Out-Null
        $zip = Join-Path $tmp $asset.name
        Say "  downloading $($asset.name) ..."
        Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $zip -UseBasicParsing
        Expand-Archive -Path $zip -DestinationPath $tmp -Force

        New-Item -ItemType Directory -Path $lib -Force | Out-Null
        # LibreHardwareMonitorLib needs HidSharp alongside it for some controllers
        foreach ($name in @('LibreHardwareMonitorLib.dll', 'HidSharp.dll')) {
            $src = Get-ChildItem -Path $tmp -Recurse -Filter $name -ErrorAction SilentlyContinue | Select-Object -First 1
            if ($src) {
                Copy-Item $src.FullName (Join-Path $lib $name) -Force
                Good "$name -> lib\"
            } elseif ($name -eq 'LibreHardwareMonitorLib.dll') {
                throw "$name was not inside $($asset.name)"
            }
        }
        Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue

        $notice = Join-Path $lib 'THIRD-PARTY.txt'
        @(
            "LibreHardwareMonitorLib.dll and HidSharp.dll in this folder are NOT part",
            "of aio_screen. They were downloaded from:",
            "",
            "  https://github.com/LibreHardwareMonitor/LibreHardwareMonitor",
            "",
            "release: $($rel.tag_name)",
            "licence: MPL-2.0 (LibreHardwareMonitor), MIT (HidSharp)",
            "",
            "They are loaded at runtime to read CPU temperature and fan speeds,",
            "which Windows does not expose to an unprivileged process."
        ) | Set-Content -Path $notice -Encoding UTF8
    } catch {
        Bad "could not fetch the DLL: $($_.Exception.Message)"
        Say ""
        Say "  Do it by hand instead:"
        Say "    1. download the latest release zip from"
        Say "       https://github.com/LibreHardwareMonitor/LibreHardwareMonitor/releases"
        Say "    2. copy LibreHardwareMonitorLib.dll (and HidSharp.dll) into:"
        Say "       $lib"
        Say ""
        Say "  Everything except CPU temperature and fan RPM works without it."
    }
}

if ($DllOnly) { exit 0 }

# --- 4. verify --------------------------------------------------------------
Say ""
Say "[4/4] Checking the result"
Say ""
& python (Join-Path $here 'doctor.py')
$rc = $LASTEXITCODE

Say ""
if ($rc -eq 0) {
    Say "Setup complete. Next:"
    Say "   RUN_TEST.bat          confirm the panel responds"
    Say "   INSTALL_STARTUP.bat   run it at logon, elevated, + desktop shortcut"
} else {
    Warn "Setup finished with $rc unresolved item(s) -- see the list above."
}
Say ""
