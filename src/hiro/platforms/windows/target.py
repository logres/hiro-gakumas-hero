"""Resolve a unique window before allowing native capture or input."""
import os
import time


def integrity_level(pid: int) -> int:
    """Read a process token's integrity RID without requesting write access."""
    import win32api
    import win32security
    process = win32api.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFORMATION
    try:
        token = win32security.OpenProcessToken(process, 8)  # TOKEN_QUERY
        try:
            info = win32security.GetTokenInformation(token, win32security.TokenIntegrityLevel)
            sid = info[0] if isinstance(info, tuple) else info
            return sid.GetSubAuthority(sid.GetSubAuthorityCount() - 1)
        finally:
            token.Close()
    finally:
        process.Close()


def ensure_input_access(window) -> None:
    own = integrity_level(os.getpid())
    target = integrity_level(window.info.process_id)
    if own < target:
        raise PermissionError(
            f"Game integrity level {target} is higher than Hiro {own}; Windows may block input. "
            "Run the game and Hiro at the same permission level. No input was sent."
        )


def activate(window):
    """Check the foreground handle, not pywin32's None success return value."""
    import win32con
    import win32gui

    hwnd = int(window.info.id)
    if win32gui.IsIconic(hwnd):
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
    if win32gui.GetForegroundWindow() != hwnd:
        try:
            win32gui.SetForegroundWindow(hwnd)
        except win32gui.error:
            # The foreground input queue may belong to another application.
            # Share it only for activation, then always detach. This neither
            # elevates the process nor allows cross-desktop input.
            import win32api
            import win32process
            current = win32api.GetCurrentThreadId()
            foreground = win32gui.GetForegroundWindow()
            thread, _ = win32process.GetWindowThreadProcessId(foreground)
            attached = False
            try:
                if thread and thread != current:
                    win32process.AttachThreadInput(current, thread, True)
                    attached = True
                win32gui.SetForegroundWindow(hwnd)
            except win32gui.error as exc:
                raise RuntimeError("Windows refused to activate the selected window") from exc
            finally:
                if attached:
                    win32process.AttachThreadInput(current, thread, False)
    deadline = time.monotonic() + 0.5
    while win32gui.GetForegroundWindow() != hwnd:
        if time.monotonic() >= deadline:
            raise RuntimeError("Windows refused to activate the selected window; input/capture stopped")
        time.sleep(0.02)


def resolve():
    from kotonebot.interop.window import WindowManager, WindowQuery
    from kotonebot.interop.window.model import WindowsNativeQuery

    handle = os.environ.get("HIRO_WINDOW_HWND")
    query = WindowQuery(
        platform="windows",
        title=None if handle else os.environ.get("HIRO_WINDOW_TITLE", "gakumas"),
        native=WindowsNativeQuery(hwnd=int(handle, 0)) if handle else None,
    )
    matches = WindowManager.default().find_all(query)
    if len(matches) != 1:
        raise RuntimeError(
            f"Expected one visible game window, found {len(matches)}. "
            "Set HIRO_WINDOW_TITLE (exact title) or HIRO_WINDOW_HWND."
        )
    window = matches[0]
    # Pin the selected process as well as HWND; never silently choose another window.
    pinned = WindowQuery(platform="windows", process_id=window.info.process_id,
                         native=WindowsNativeQuery(hwnd=int(window.info.id)))
    return window, pinned
