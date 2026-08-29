# restore_pc_monitor.ps1 -- undo disable_pc_monitor.ps1.
$ErrorActionPreference = 'Continue'
$here     = Split-Path -Parent $MyInvocation.MyCommand.Path
$backup   = Join-Path $here 'pcmonitor_autostart_backup'
$manifest = Join-Path $backup 'manifest.json'

if (-not (Test-Path $manifest)) {
    Write-Host "Nothing to restore: no manifest at $manifest" -ForegroundColor Yellow
    exit 0
}
$items = Get-Content $manifest -Raw | ConvertFrom-Json
foreach ($i in @($items)) {
    switch ($i.kind) {
        'registry' {
            if (Test-Path $i.backup) {
                & reg.exe import $i.backup 2>&1 | Out-Null
                Write-Host "  restored registry value $($i.name)" -ForegroundColor Green
            }
        }
        'startup' {
            $dst = Join-Path $i.path $i.name
            if (Test-Path $i.backup) {
                Move-Item -Path $i.backup -Destination $dst -Force
                Write-Host "  restored startup item $($i.name)" -ForegroundColor Green
            }
        }
        'task' {
            & schtasks /Change /TN "$($i.name)" /ENABLE 2>&1 | Out-Null
            Write-Host "  re-enabled task $($i.name)" -ForegroundColor Green
        }
        'service' {
            $mode = if ($i.previous -eq 'Auto') { 'auto' } else { 'demand' }
            & sc.exe config "$($i.name)" start= $mode | Out-Null
            Write-Host "  service $($i.name) set back to $mode" -ForegroundColor Green
        }
    }
}
Write-Host ""
Write-Host "Restored. The vendor app will start at logon again -- expect it to"
Write-Host "fight our daemon for the panel unless you stop ours."
