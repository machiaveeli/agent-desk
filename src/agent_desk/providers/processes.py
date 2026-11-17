"""Asks the operating system whether a process is still running, without extra dependencies."""

import os
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ProcessState:
    """`start_marker` tells a process apart from a later one that reuses its pid. It is None
    when the OS gives no start time that matches what the provider records."""

    is_running: bool
    start_marker: str | None


NOT_RUNNING = ProcessState(is_running=False, start_marker=None)
RUNNING_START_UNKNOWN = ProcessState(is_running=True, start_marker=None)


STAT_START_TIME_INDEX = 19


def read_start_time(stat: str) -> str | None:
    """Field 22 of Linux's /proc/<pid>/stat, the start time in clock ticks since boot. The
    process name (field 2) may hold spaces and ')', so fields are counted after the last ')'.

    Pure text parsing, defined on every platform so its tests run everywhere."""
    fields_after_name = stat.rsplit(")", 1)[-1].split()
    if len(fields_after_name) <= STAT_START_TIME_INDEX:
        return None
    return fields_after_name[STAT_START_TIME_INDEX]


def inspect_process(pid: int) -> ProcessState:
    # pid 0 and negative pids name process groups or the system itself, never a session.
    if pid <= 0:
        return NOT_RUNNING
    return inspect_running_process(pid)


if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    STILL_ACTIVE = 259
    ERROR_ACCESS_DENIED = 5

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
    kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL

    def inspect_running_process(pid: int) -> ProcessState:
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            # Another user's process refuses access, but it does exist.
            is_denied = ctypes.get_last_error() == ERROR_ACCESS_DENIED
            return RUNNING_START_UNKNOWN if is_denied else NOT_RUNNING
        try:
            exit_code = wintypes.DWORD()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return RUNNING_START_UNKNOWN
            return RUNNING_START_UNKNOWN if exit_code.value == STILL_ACTIVE else NOT_RUNNING
        finally:
            kernel32.CloseHandle(handle)

elif sys.platform == "linux":

    def inspect_running_process(pid: int) -> ProcessState:
        try:
            stat = Path(f"/proc/{pid}/stat").read_text(encoding="ascii", errors="replace")
        except (FileNotFoundError, ProcessLookupError):
            return NOT_RUNNING
        except OSError:
            return RUNNING_START_UNKNOWN
        return ProcessState(is_running=True, start_marker=read_start_time(stat))

else:

    def inspect_running_process(pid: int) -> ProcessState:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return NOT_RUNNING
        except PermissionError:
            return RUNNING_START_UNKNOWN
        return RUNNING_START_UNKNOWN
