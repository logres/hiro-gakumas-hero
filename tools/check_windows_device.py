"""Explicit desktop smoke test: creates and clicks only its own test window.

Run manually on Windows. This moves the real cursor and briefly activates a
360x640 test window; it never searches for or interacts with the game.
"""
import json
import os
import threading
import time


def main():
    import ctypes
    from ctypes import wintypes
    import win32api
    import win32con
    import win32gui

    ctypes.windll.user32.SetProcessDPIAware()
    ready = threading.Event()
    clicked = threading.Event()
    state = {}

    def window_thread():
        def proc(hwnd, message, wparam, lparam):
            if message == win32con.WM_PAINT:
                dc, paint = win32gui.BeginPaint(hwnd)
                brush = win32gui.CreateSolidBrush(win32api.RGB(220, 40, 20))
                try:
                    win32gui.FillRect(dc, win32gui.GetClientRect(hwnd), brush)
                finally:
                    win32gui.DeleteObject(brush)
                    win32gui.EndPaint(hwnd, paint)
                return 0
            if message == win32con.WM_LBUTTONUP:
                state["click"] = [lparam & 65535, (lparam >> 16) & 65535]
                clicked.set()
                return 0
            if message == win32con.WM_DESTROY:
                win32gui.PostQuitMessage(0)
                return 0
            return win32gui.DefWindowProc(hwnd, message, wparam, lparam)

        try:
            cls = win32gui.WNDCLASS()
            cls.hInstance = win32api.GetModuleHandle(None)
            cls.lpszClassName = f"HiroDeviceFixture{os.getpid()}"
            cls.lpfnWndProc = proc
            atom = win32gui.RegisterClass(cls)
            style = win32con.WS_OVERLAPPEDWINDOW
            bounds = wintypes.RECT(0, 0, 360, 640)
            if not ctypes.windll.user32.AdjustWindowRect(ctypes.byref(bounds), style, False):
                raise ctypes.WinError()
            hwnd = win32gui.CreateWindowEx(win32con.WS_EX_TOPMOST, atom, "Hiro controlled device test", style,
                                         40, 40, bounds.right-bounds.left, bounds.bottom-bounds.top,
                                         0, 0, cls.hInstance, None)
            state["hwnd"] = hwnd
            win32gui.ShowWindow(hwnd, win32con.SW_SHOW)
            win32gui.UpdateWindow(hwnd)
            ready.set()
            win32gui.PumpMessages()
            win32gui.UnregisterClass(atom, cls.hInstance)
        except BaseException as exc:
            state["error"] = repr(exc)
            ready.set()

    thread = threading.Thread(target=window_thread, daemon=True)
    thread.start()
    device = None
    previous = os.environ.get("HIRO_WINDOW_HWND")
    try:
        if not ready.wait(10) or "error" in state:
            raise RuntimeError(f"Fixture creation failed: {state}")
        os.environ["HIRO_WINDOW_HWND"] = str(state["hwnd"])
        from hiro.platforms.windows.device import connect
        device = connect()
        for _ in range(20):
            frame = device.screenshot()
            if all(abs(a-b) <= 2 for a, b in zip(frame[500, 300].tolist(), [20, 40, 220])):
                break
            time.sleep(0.1)
        assert frame.shape == (1280, 720, 3), frame.shape
        color = frame[500, 300].tolist()
        assert all(abs(a-b) <= 2 for a, b in zip(color, [20, 40, 220])), color
        device.click(360, 640)
        received = clicked.wait(5)
        assert received, {"error": "Target window did not receive mouse-up",
                          "cursor": win32gui.GetCursorPos(),
                          "expected_screen": win32gui.ClientToScreen(state["hwnd"], (180, 320)),
                          "foreground": win32gui.GetForegroundWindow(), "target": state["hwnd"]}
        assert all(abs(a-b) <= 2 for a, b in zip(state["click"], [180, 320])), state
        print(json.dumps({"shape": list(frame.shape), "bgr": color,
                          "logical_click": [360, 640], "client_click": state["click"],
                          "result": "passed"}))
    finally:
        if device is not None:
            device.stop()
        if previous is None:
            os.environ.pop("HIRO_WINDOW_HWND", None)
        else:
            os.environ["HIRO_WINDOW_HWND"] = previous
        if "hwnd" in state and win32gui.IsWindow(state["hwnd"]):
            win32gui.PostMessage(state["hwnd"], win32con.WM_CLOSE, 0, 0)
        thread.join(5)


if __name__ == "__main__":
    main()
