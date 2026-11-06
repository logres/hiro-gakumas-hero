"""Opt-in DMM foreground backend, using the same kotonebot stack as KAA.

Capturing activates the target; input moves the real mouse. No background
semantics are promised. Enable via HIRO_DEVICE_BACKEND=hiro.platforms.windows.device.
"""
from .target import activate, ensure_input_access, resolve


def connect(backend: str = "auto"):
    if backend not in ("auto", "windows_native"):
        raise ValueError(f"Unsupported Windows device mode: {backend}")
    from kotonebot.client.device import WindowsDevice
    from kotonebot.client.implements.windows.windows_native import WindowsNativeImpl
    from kotonebot.client.scaler import PortraitGameScaler
    from kotonebot.primitives.geometry import Size

    class WindowScaler(PortraitGameScaler):
        def transform_screenshot(self, image):
            self.physical_resolution = Size(image.shape[1], image.shape[0])
            return super().transform_screenshot(image)

        def logic_to_physical(self, value):
            if tuple(native.screen_size) != tuple(self.physical_resolution):
                raise RuntimeError("Window resized since screenshot; capture and decide again before input")
            return super().logic_to_physical(value)

    class CheckedNative(WindowsNativeImpl):
        def _ensure_active(self):
            activate(self._window())

        def click(self, x, y):
            ensure_input_access(self._window())
            return super().click(x, y)

        def swipe(self, x1, y1, x2, y2, duration=None):
            ensure_input_access(self._window())
            return super().swipe(x1, y1, x2, y2, duration)

    _, query = resolve()
    device = WindowsDevice()
    scaler = WindowScaler()
    scaler.logic_resolution = Size(720, 1280)
    native = CheckedNative(device, query)
    device.setup(screenshot=native, touch=native, scaler=scaler)
    try:
        device.start()
        # kotonebot's lazy initializer overwrites logic_resolution from global
        # config unless physical_resolution is already set. Keep this local.
        scaler.physical_resolution = Size(*native.screen_size)
        device.screenshot()
    except BaseException:
        device.stop()
        raise
    return device


def real_click(lx: int, ly: int) -> None:
    """Explicit foreground fallback; refresh geometry before translating input."""
    device = connect("windows_native")
    try:
        device.click(lx, ly)
    finally:
        device.stop()
