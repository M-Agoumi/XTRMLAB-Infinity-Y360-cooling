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
'
' Detecting whether it is ALREADY running is the fiddly part. The first
' version asked WMI for pythonw.exe command lines and looked for "aio_daemon";
' that silently failed, because the daemon runs elevated and a non-elevated
' WMI query gets NULL for an elevated process's CommandLine. The check always
' said "not running", schtasks then returned success without starting a second
' instance (the task's policy is IgnoreNew), and so a double-click did nothing
' at all and said nothing.
'
' Now: read our own panel.lock for the pid, and ask WMI only whether that pid
' exists -- basic process identity is visible across the UAC boundary even
' when the command line is not.

Option Explicit

Dim sh, fso, here, rc, lockPid, out

Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
here = fso.GetParentFolderName(WScript.ScriptFullName)

lockPid = LockOwnerPid()
If lockPid > 0 Then
    If PidAlive(lockPid) Then
        MsgBox "The AIO screen daemon is already running (pid " & lockPid & ")." & vbCrLf & vbCrLf & _
               "Look for its icon in the system tray -- it is probably hidden" & vbCrLf & _
               "under the ^ overflow arrow. Right-click it for status, config" & vbCrLf & _
               "or Quit.", vbInformation, "AIO Screen"
        WScript.Quit 0
    End If
End If

' --- preferred path: the scheduled task, which holds the elevation --------
rc = sh.Run("schtasks /Run /TN ""AIO_Screen""", 0, True)

If rc = 0 Then
    ' Confirm it actually came up, rather than trusting the exit code: with
    ' IgnoreNew, schtasks reports success even when it started nothing.
    If WaitForDaemon(8) Then
        WScript.Quit 0
    End If
    MsgBox "Task Scheduler accepted the request, but the daemon did not" & vbCrLf & _
           "start within 8 seconds." & vbCrLf & vbCrLf & _
           "Check aio_daemon.log in:" & vbCrLf & here, _
           vbExclamation, "AIO Screen"
    WScript.Quit 1
End If

' --- fallback: task not installed, so elevate the hard way (UAC prompt) ---
If fso.FileExists(here & "\AIO Screen.exe") Then
    sh.Run """" & here & "\AIO Screen.exe""", 0, False
    If Not WaitForDaemon(20) Then
        MsgBox "Could not start the daemon." & vbCrLf & vbCrLf & _
               "The scheduled task 'AIO_Screen' is not installed, and starting" & vbCrLf & _
               "AIO Screen.exe did not come up (a UAC prompt may have been declined).", _
               vbExclamation, "AIO Screen"
    End If
ElseIf fso.FileExists(here & "\START_NOW.bat") Then
    sh.Run """" & here & "\START_NOW.bat""", 0, False
    If Not WaitForDaemon(20) Then
        MsgBox "Could not start the daemon." & vbCrLf & vbCrLf & _
               "The scheduled task 'AIO_Screen' is not installed, and the" & vbCrLf & _
               "fallback did not come up (a UAC prompt may have been declined)." & vbCrLf & vbCrLf & _
               "Run INSTALL_STARTUP.bat to set it up properly.", _
               vbExclamation, "AIO Screen"
    End If
Else
    MsgBox "Could not start the daemon." & vbCrLf & vbCrLf & _
           "The scheduled task 'AIO_Screen' is not installed and" & vbCrLf & _
           "START_NOW.bat is missing. Run INSTALL_STARTUP.bat first.", _
           vbExclamation, "AIO Screen"
End If


' ------------------------------------------------------------------------
Function LockOwnerPid()
    ' Prefer daemon.pid, which exists for the daemon's whole lifetime.
    ' panel.lock is a fallback: it is released whenever the panel handle is
    ' dropped, so the daemon can be alive with no lock file.
    LockOwnerPid = PidFromFile(here & "\daemon.pid")
    If LockOwnerPid = 0 Then LockOwnerPid = PidFromFile(here & "\panel.lock")
End Function


Function PidFromFile(path)
    ' Parsing a pid out of a small json file needs no privilege at all,
    ' unlike reading an elevated process's command line.
    Dim f, text, i, j, digits, ch
    PidFromFile = 0
    If Not fso.FileExists(path) Then Exit Function
    On Error Resume Next
    Set f = fso.OpenTextFile(path, 1)
    text = f.ReadAll
    f.Close
    If Err.Number <> 0 Then Exit Function
    On Error GoTo 0

    i = InStr(text, """pid""")
    If i = 0 Then Exit Function
    i = InStr(i, text, ":")
    If i = 0 Then Exit Function
    digits = ""
    For j = i + 1 To Len(text)
        ch = Mid(text, j, 1)
        If ch >= "0" And ch <= "9" Then
            digits = digits & ch
        ElseIf digits <> "" Then
            Exit For
        End If
    Next
    If digits <> "" Then PidFromFile = CLng(digits)
End Function


Function PidAlive(pid)
    ' Only asks whether the pid exists. Works across the UAC boundary, where
    ' asking for its CommandLine would come back NULL.
    Dim svc, items
    PidAlive = False
    On Error Resume Next
    Set svc = GetObject("winmgmts:\\.\root\cimv2")
    If Err.Number <> 0 Then
        Err.Clear
        PidAlive = True        ' cannot tell -- assume yes rather than duplicate
        Exit Function
    End If
    Set items = svc.ExecQuery("SELECT ProcessId FROM Win32_Process WHERE ProcessId = " & pid)
    If Err.Number = 0 Then
        If items.Count > 0 Then PidAlive = True
    End If
    Err.Clear
    On Error GoTo 0
End Function


Function WaitForDaemon(seconds)
    Dim waited, pid
    WaitForDaemon = False
    waited = 0
    Do While waited < seconds
        WScript.Sleep 500
        waited = waited + 0.5
        pid = LockOwnerPid()
        If pid > 0 Then
            If PidAlive(pid) Then
                WaitForDaemon = True
                Exit Function
            End If
        End If
    Loop
End Function
