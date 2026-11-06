"""Resolve a unique window before allowing native capture or input."""
import os
import time


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
        except win32gui.error as exc:
            raise RuntimeError("Windows refused to activate the selected window") from exc
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
