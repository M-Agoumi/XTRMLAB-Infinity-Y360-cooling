# Creates a desktop shortcut that starts the AIO screen daemon.
# No admin needed to make the shortcut, and none to USE it either: it goes
# through the scheduled task, which carries the elevation itself.

$here    = Split-Path -Parent $MyInvocation.MyCommand.Path
$desktop = [Environment]::GetFolderPath('Desktop')   # follows OneDrive redirection
$link    = Join-Path $desktop 'AIO Screen.lnk'

$vbs = Join-Path $here 'start_panel.vbs'
if (-not (Test-Path $vbs)) { Write-Host "missing: $vbs"; exit 1 }

$icon = Join-Path $here 'icon.ico'
if (-not (Test-Path $icon)) { $icon = "$env:WINDIR\System32\shell32.dll,13" }

$sh = New-Object -ComObject WScript.Shell
$s  = $sh.CreateShortcut($link)
$s.TargetPath       = Join-Path $env:WINDIR 'System32\wscript.exe'
$s.Arguments        = '"' + $vbs + '"'
$s.WorkingDirectory = $here
$s.IconLocation     = $icon
$s.Description      = 'Start the AIO pump-cap display daemon'
$s.WindowStyle      = 7          # minimised; wscript shows nothing anyway
$s.Save()

Write-Host ""
Write-Host "Created:  $link"
Write-Host ""
Write-Host "Double-click it any time you have quit the daemon from the tray."
Write-Host "It starts the scheduled task, so it runs elevated with no UAC prompt."
Write-Host "If the daemon is already running it just tells you so."
Write-Host ""

$task = schtasks /Query /TN "AIO_Screen" 2>$null
if (-not $?) {
  Write-Host "NOTE: the 'AIO_Screen' scheduled task is not installed yet."
  Write-Host "      Run INSTALL_STARTUP.bat first, otherwise the shortcut has to"
  Write-Host "      fall back to a UAC prompt each time."
  Write-Host ""
}
