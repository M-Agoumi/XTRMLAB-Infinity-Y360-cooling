# disable_pc_monitor.ps1 -- stop the vendor "PC Monitor" app starting at logon.
#
# It is not enough to close it: while it runs it posts its own frames to the
# panel, and the panel has no arbitration -- last frame wins -- so the two
# programs interleave and the display flickers between two sets of numbers.
#
# Everything here is REVERSIBLE and nothing is deleted outright:
#   * registry Run values are exported to a .reg file, then removed
#   * Startup-folder shortcuts are MOVED into the backup folder
#   * scheduled tasks are disabled, not deleted
#   * services are set to Manual, not deleted
# restore_pc_monitor.ps1 puts it all back.

param([switch]$List)

$ErrorActionPreference = 'Continue'
$here    = Split-Path -Parent $MyInvocation.MyCommand.Path
$backup  = Join-Path $here 'pcmonitor_autostart_backup'
$manifest = Join-Path $backup 'manifest.json'

$PATTERN = 'PC[_ ]?Monitor|allComputerInfoGetPro|Witmod'

function Head($t) { Write-Host ""; Write-Host $t -ForegroundColor Cyan }
function Item($t) { Write-Host "    $t" }
function Good($t) { Write-Host "  [done] $t" -ForegroundColor Green }
function Note($t) { Write-Host "  [note] $t" -ForegroundColor Yellow }

$found = @()

# --- registry Run keys ------------------------------------------------------
$runKeys = @(
    'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run',
    'HKCU:\Software\Microsoft\Windows\CurrentVersion\RunOnce',
    'HKLM:\Software\Microsoft\Windows\CurrentVersion\Run',
    'HKLM:\Software\Microsoft\Windows\CurrentVersion\RunOnce',
    'HKLM:\Software\Wow6432Node\Microsoft\Windows\CurrentVersion\Run'
)
foreach ($key in $runKeys) {
    if (-not (Test-Path $key)) { continue }
    $props = Get-ItemProperty -Path $key -ErrorAction SilentlyContinue
    foreach ($p in $props.PSObject.Properties) {
        if ($p.Name -like 'PS*') { continue }
        if ("$($p.Name) $($p.Value)" -match $PATTERN) {
            $found += [pscustomobject]@{
                Kind = 'registry'; Where = $key; Name = $p.Name; Value = "$($p.Value)"
            }
        }
    }
}

# --- startup folders --------------------------------------------------------
$startupDirs = @([Environment]::GetFolderPath('Startup'),
                 [Environment]::GetFolderPath('CommonStartup')) | Where-Object { $_ }
foreach ($dir in $startupDirs) {
    Get-ChildItem -Path $dir -ErrorAction SilentlyContinue | ForEach-Object {
        $target = ''
        if ($_.Extension -eq '.lnk') {
            try {
                $sh = New-Object -ComObject WScript.Shell
                $target = $sh.CreateShortcut($_.FullName).TargetPath
            } catch {}
        }
        if ("$($_.Name) $target" -match $PATTERN) {
            $found += [pscustomobject]@{
                Kind = 'startup'; Where = $dir; Name = $_.Name; Value = $target
            }
        }
    }
}

# --- scheduled tasks --------------------------------------------------------
try {
    Get-ScheduledTask -ErrorAction SilentlyContinue | ForEach-Object {
        $task = $_
        $actions = ($task.Actions | ForEach-Object { "$($_.Execute) $($_.Arguments)" }) -join ' '
        if ("$($task.TaskName) $actions" -match $PATTERN) {
            $found += [pscustomobject]@{
                Kind = 'task'; Where = $task.TaskPath; Name = $task.TaskName
                Value = "$actions  [state: $($task.State)]"
            }
        }
    }
} catch { Note "could not enumerate scheduled tasks: $($_.Exception.Message)" }

# --- services ---------------------------------------------------------------
try {
    Get-CimInstance Win32_Service -ErrorAction SilentlyContinue | ForEach-Object {
        if ("$($_.Name) $($_.DisplayName) $($_.PathName)" -match $PATTERN) {
            $found += [pscustomobject]@{
                Kind = 'service'; Where = $_.StartMode; Name = $_.Name; Value = $_.PathName
            }
        }
    }
} catch {}

# --- report -----------------------------------------------------------------
Head "Autostart entries for the vendor PC Monitor app"
if (-not $found) {
    Write-Host "  none found -- it does not start itself, or was already disabled." -ForegroundColor Green
    Write-Host ""
    exit 0
}
foreach ($f in $found) {
    Item "$($f.Kind.PadRight(8)) $($f.Name)"
    Item "         in    $($f.Where)"
    Item "         value $($f.Value)"
}

if ($List) { Write-Host ""; exit 0 }

Write-Host ""
$answer = Read-Host "Disable these? Everything is backed up and reversible [y/N]"
if ($answer -notmatch '^[Yy]') { Write-Host "Nothing changed."; exit 0 }

New-Item -ItemType Directory -Path $backup -Force | Out-Null
$record = @()

foreach ($f in $found) {
    switch ($f.Kind) {
        'registry' {
            $safe = ($f.Where -replace '[:\\]', '_') + "_$($f.Name).reg"
            $regFile = Join-Path $backup $safe
            $hive = $f.Where -replace '^HKCU:', 'HKEY_CURRENT_USER' -replace '^HKLM:', 'HKEY_LOCAL_MACHINE'
            # a hand-written .reg so a single value can be restored, not a whole key
            $escaped = $f.Value -replace '\\', '\\\\' -replace '"', '\"'
            @("Windows Registry Editor Version 5.00", "", "[$hive]",
              "`"$($f.Name)`"=`"$escaped`"") | Set-Content -Path $regFile -Encoding Unicode
            Remove-ItemProperty -Path $f.Where -Name $f.Name -ErrorAction SilentlyContinue
            Good "registry value '$($f.Name)' removed (backup: $safe)"
            $record += @{ kind='registry'; path=$f.Where; name=$f.Name; backup=$regFile }
        }
        'startup' {
            $src = Join-Path $f.Where $f.Name
            $dst = Join-Path $backup $f.Name
            Move-Item -Path $src -Destination $dst -Force -ErrorAction SilentlyContinue
            Good "startup item '$($f.Name)' moved into the backup folder"
            $record += @{ kind='startup'; path=$f.Where; name=$f.Name; backup=$dst }
        }
        'task' {
            & schtasks /Change /TN "$($f.Where)$($f.Name)".TrimStart('\') /DISABLE 2>&1 | Out-Null
            if ($LASTEXITCODE -ne 0) { & schtasks /Change /TN "$($f.Name)" /DISABLE 2>&1 | Out-Null }
            Good "scheduled task '$($f.Name)' disabled"
            $record += @{ kind='task'; name=$f.Name; path=$f.Where }
        }
        'service' {
            & sc.exe config "$($f.Name)" start= demand | Out-Null
            Good "service '$($f.Name)' set to Manual (was $($f.Where))"
            $record += @{ kind='service'; name=$f.Name; previous=$f.Where }
        }
    }
}

$record | ConvertTo-Json -Depth 5 | Set-Content -Path $manifest -Encoding UTF8

Head "Stopping it if it is running now"
foreach ($proc in @('PC_Monitor', 'allComputerInfoGetPro')) {
    $running = Get-Process -Name $proc -ErrorAction SilentlyContinue
    if ($running) {
        $running | Stop-Process -Force -ErrorAction SilentlyContinue
        Good "stopped $proc"
    }
}

Write-Host ""
Write-Host "Done. The vendor app will no longer start at logon." -ForegroundColor Green
Write-Host "Backups and a manifest are in:"
Write-Host "   $backup"
Write-Host "Undo with restore_pc_monitor.ps1 (or RESTORE_PC_MONITOR.bat)."
Note "If you ever run the vendor app by hand it may re-add its autostart entry."
Write-Host ""
