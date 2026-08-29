' start_panel.vbs -- launch the AIO screen daemon, silently.
'
' This is what the desktop shortcut points at. It exists because the obvious
' alternatives are both bad:
'
'   * a shortcut straight to the .pyw would run WITHOUT admin rights, and CPU
'     temperature would silently read 0
'   * a shortcut to a .bat that elevates itself pops a UAC prompt every time
'
' Instead it asks Task Scheduler to run the already-registered "AIO_Screen"
' task, which carries its own elevation -- so the daemon starts with admin
' rights and NO UAC prompt. If that task is not installed, it falls back to
' START_NOW.bat, which does prompt.

Option Explicit

Dim sh, fso, here, rc, running, procs, p, svc
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
here = fso.GetParentFolderName(WScript.ScriptFullName)

' --- already running? clicking twice should not start a fight -------------
running = False
On Error Resume Next
Set svc = GetObject("winmgmts:\\.\root\cimv2")
If Err.Number = 0 Then
    Set procs = svc.ExecQuery("SELECT CommandLine FROM Win32_Process WHERE Name = 'pythonw.exe'")
    For Each p In procs
        If Not IsNull(p.CommandLine) Then
            If InStr(LCase(p.CommandLine), "aio_daemon") > 0 Then running = True
        End If
    Next
End If
Err.Clear
On Error GoTo 0

If running Then
    MsgBox "The AIO screen daemon is already running." & vbCrLf & vbCrLf & _
           "Look for its icon in the system tray (it may be hidden under the" & vbCrLf & _
           "^ overflow arrow). Right-click it for status, config, or Quit.", _
           vbInformation, "AIO Screen"
    WScript.Quit 0
End If

' --- preferred path: the scheduled task, which holds the elevation --------
rc = sh.Run("schtasks /Run /TN ""AIO_Screen""", 0, True)

If rc = 0 Then
    WScript.Quit 0
End If

' --- fallback: not installed, so elevate the hard way (UAC prompt) --------
If fso.FileExists(here & "\START_NOW.bat") Then
    sh.Run """" & here & "\START_NOW.bat""", 0, False
Else
    MsgBox "Could not start the daemon." & vbCrLf & vbCrLf & _
           "The scheduled task 'AIO_Screen' is not installed and" & vbCrLf & _
           "START_NOW.bat is missing. Run INSTALL_STARTUP.bat first.", _
           vbExclamation, "AIO Screen"
End If
