"""Start-with-Windows via a per-user Task Scheduler logon task.

Explorer's Run key is skipped now and then (it was on a real logon, with the
entry present and approved), so the logon task is the primary mechanism. The
Run key is only a fallback for when the task can't be created, and an old Run
entry is migrated to the task on the next start.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import tempfile
import winreg
from pathlib import Path
from xml.sax.saxutils import escape

from . import APP_NAME

log = logging.getLogger(__name__)

_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_TASK_NAME = APP_NAME
# Give Bluetooth and the tray a moment after logon.
_LOGON_DELAY = "PT10S"


def launch_command() -> str:
    program, args = _program()
    return f'"{program}" {args}'.rstrip()


def is_enabled() -> bool:
    return _task_exists() or _run_value() is not None


def set_enabled(enabled: bool) -> None:
    if not enabled:
        _delete_task()
        _set_run_value(None)
        return
    try:
        _create_task()
    except OSError:
        log.exception("Could not create the logon task; using the Run key instead")
        _set_run_value(launch_command())
        return
    _set_run_value(None)  # the task replaces it; two entries would launch twice


def refresh() -> None:
    """Re-register an enabled entry so it points at this exe and uses the task."""
    if not is_enabled():
        return
    try:
        set_enabled(True)
    except OSError:
        log.exception("Could not refresh the startup entry")


# ------------------------------------------------------------------ helpers


def _program() -> tuple[str, str]:
    if getattr(sys, "frozen", False):  # PyInstaller build
        return sys.executable, ""
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    interpreter = pythonw if pythonw.exists() else Path(sys.executable)
    return str(interpreter), "-m podpop"


def _task_xml() -> str:
    program, args = _program()
    user = escape(f"{os.environ.get('USERDOMAIN', '')}\\{os.environ.get('USERNAME', '')}".lstrip("\\"))
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>Starts {APP_NAME} when you sign in.</Description></RegistrationInfo>
  <Triggers>
    <LogonTrigger><Enabled>true</Enabled><UserId>{user}</UserId><Delay>{_LOGON_DELAY}</Delay></LogonTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author"><UserId>{user}</UserId><LogonType>InteractiveToken</LogonType><RunLevel>LeastPrivilege</RunLevel></Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Priority>7</Priority>
    <RestartOnFailure><Interval>PT1M</Interval><Count>3</Count></RestartOnFailure>
  </Settings>
  <Actions Context="Author">
    <Exec><Command>{escape(program)}</Command><Arguments>{escape(args)}</Arguments></Exec>
  </Actions>
</Task>
"""


def _schtasks(*args: str) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            ["schtasks", *args],
            capture_output=True,
            text=True,
            timeout=15,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise OSError(f"schtasks failed: {exc}") from exc


def _create_task() -> None:
    fd, path = tempfile.mkstemp(suffix=".xml")
    try:
        with os.fdopen(fd, "w", encoding="utf-16") as f:
            f.write(_task_xml())
        result = _schtasks("/create", "/tn", _TASK_NAME, "/xml", path, "/f")
    finally:
        os.unlink(path)
    if result.returncode != 0:
        raise OSError(f"schtasks /create: {(result.stderr or result.stdout).strip()}")


def _task_exists() -> bool:
    try:
        return _schtasks("/query", "/tn", _TASK_NAME).returncode == 0
    except OSError:
        return False


def _delete_task() -> None:
    if _task_exists():
        result = _schtasks("/delete", "/tn", _TASK_NAME, "/f")
        if result.returncode != 0:
            raise OSError(f"schtasks /delete: {(result.stderr or result.stdout).strip()}")


def _run_value() -> str | None:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
            return winreg.QueryValueEx(key, APP_NAME)[0]
    except FileNotFoundError:
        return None


def _set_run_value(command: str | None) -> None:
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if command is not None:
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, command)
        else:
            try:
                winreg.DeleteValue(key, APP_NAME)
            except FileNotFoundError:
                pass
