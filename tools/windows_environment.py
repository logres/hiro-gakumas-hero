"""Read-only desktop/package diagnostics; does not activate windows or send input."""
import ctypes
from ctypes import wintypes as w
import json
import os


def snapshot():
    user = ctypes.WinDLL("user32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    user.GetThreadDesktop.argtypes = [w.DWORD]
    user.GetThreadDesktop.restype = w.HANDLE
    user.OpenInputDesktop.argtypes = [w.DWORD, w.BOOL, w.DWORD]
    user.OpenInputDesktop.restype = w.HANDLE
    user.CloseDesktop.argtypes = [w.HANDLE]
    user.GetUserObjectInformationW.argtypes = [w.HANDLE, ctypes.c_int, w.LPVOID, w.DWORD, ctypes.POINTER(w.DWORD)]
    user.GetForegroundWindow.restype = w.HWND
    user.GetWindowThreadProcessId.argtypes = [w.HWND, ctypes.POINTER(w.DWORD)]
    kernel.ProcessIdToSessionId.argtypes = [w.DWORD, ctypes.POINTER(w.DWORD)]
    kernel.GetCurrentPackageFullName.argtypes = [ctypes.POINTER(w.UINT), w.LPWSTR]

    def desktop_name(handle):
        if not handle:
            return {"error": ctypes.get_last_error()}
        buffer = ctypes.create_unicode_buffer(256)
        needed = w.DWORD()
        if not user.GetUserObjectInformationW(handle, 2, buffer, ctypes.sizeof(buffer), ctypes.byref(needed)):
            return {"error": ctypes.get_last_error()}
        return buffer.value

    thread_desktop = desktop_name(user.GetThreadDesktop(kernel.GetCurrentThreadId()))
    handle = user.OpenInputDesktop(0, False, 1)  # DESKTOP_READOBJECTS
    input_desktop = desktop_name(handle)
    if handle:
        user.CloseDesktop(handle)
    session = w.DWORD()
    kernel.ProcessIdToSessionId(os.getpid(), ctypes.byref(session))
    foreground_pid = w.DWORD()
    foreground_tid = user.GetWindowThreadProcessId(user.GetForegroundWindow(), ctypes.byref(foreground_pid))
    size = w.UINT()
    status = kernel.GetCurrentPackageFullName(ctypes.byref(size), None)
    package = None
    if status == 122:
        buffer = ctypes.create_unicode_buffer(size.value)
        status = kernel.GetCurrentPackageFullName(ctypes.byref(size), buffer)
        if status == 0:
            package = buffer.value
    return {"pid": os.getpid(), "session": session.value,
            "thread_desktop": thread_desktop, "input_desktop": input_desktop,
            "foreground_pid": foreground_pid.value, "foreground_thread": foreground_tid,
            "package": package, "package_query_status": status}


if __name__ == "__main__":
    print(json.dumps(snapshot(), ensure_ascii=False, indent=2))
