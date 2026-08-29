"""
who_is_writing.py -- is something ELSE posting to the panel?

The panel has no arbitration: any process that opens it can post a frame, and
the last frame posted wins. Two writers at 1 Hz, unsynchronised, look exactly
like "it updates twice in a second and one of them is wrong" -- because it is
literally two different programs each drawing their own numbers.

Usual suspects:
  * a leftover demo_stats.py console window from testing
  * the vendor "PC Monitor" app having restarted
  * two copies of the daemon (the mutex should prevent this, but check)

    python who_is_writing.py
"""
import subprocess

PS = (
    "Get-CimInstance Win32_Process | "
    "Where-Object { $_.Name -match 'python|pythonw|PC_Monitor|allComputerInfo' } | "
    "Select-Object ProcessId,Name,CommandLine | Format-List"
)


def main():
    print("processes that could be writing to the panel:\n")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", PS],
                             capture_output=True, text=True, timeout=30).stdout
    except Exception as e:  # noqa: BLE001
        print(f"could not query processes: {e}")
        return

    blocks = [b.strip() for b in out.split("\n\n") if b.strip()]
    if not blocks:
        print("  none found -- nothing else is posting, so a double update is")
        print("  coming from inside the daemon rather than a second writer.")
        return

    daemons = 0
    for b in blocks:
        print("  " + b.replace("\n", "\n  "))
        print()
        if "aio_daemon" in b:
            daemons += 1
        if "demo_stats" in b:
            print("  ^^ THIS IS A SECOND WRITER. Close that window.\n")
        if "PC_Monitor" in b:
            print("  ^^ the vendor app is running and posting its own frames.\n")

    if daemons > 1:
        print(f"!! {daemons} copies of aio_daemon are running. Kill them all and")
        print("   restart with: UNINSTALL_STARTUP.bat then INSTALL_STARTUP.bat")


if __name__ == "__main__":
    main()
