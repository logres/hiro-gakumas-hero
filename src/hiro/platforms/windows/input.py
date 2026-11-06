"""Explicit atomic foreground click injection; does not activate a window."""
from functools import lru_cache
import ctypes

# Fixed-width Windows ABI types, even when unit tests run on another OS.
DWORD = ctypes.c_uint32
LONG = ctypes.c_int32
WORD = ctypes.c_uint16
ULONG_PTR = ctypes.c_size_t


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [('dx', LONG), ('dy', LONG), ('mouseData', DWORD),
                ('dwFlags', DWORD), ('time', DWORD), ('dwExtraInfo', ULONG_PTR)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [('wVk', WORD), ('wScan', WORD), ('dwFlags', DWORD),
                ('time', DWORD), ('dwExtraInfo', ULONG_PTR)]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [('uMsg', DWORD), ('wParamL', WORD), ('wParamH', WORD)]


class INPUTUNION(ctypes.Union):
    _fields_ = [('mi', MOUSEINPUT), ('ki', KEYBDINPUT), ('hi', HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ('data',)
    _fields_ = [('type', DWORD), ('data', INPUTUNION)]


MOVE_ABSOLUTE_VIRTUAL = 0x0001 | 0x8000 | 0x4000
LEFTDOWN = 0x0002
LEFTUP = 0x0004


def _normalize(x: int, y: int, bounds: tuple[int, int, int, int]) -> tuple[int, int]:
    left, top, width, height = bounds
    if width < 2 or height < 2:
        raise ValueError(f'Invalid virtual desktop dimensions: {bounds}')
    if not isinstance(x, int) or not isinstance(y, int):
        raise ValueError('Click coordinates must be integer screen pixels')
    if not (left <= x < left + width and top <= y < top + height):
        raise ValueError(f'Click ({x}, {y}) is outside virtual desktop {bounds}')
    # Both endpoints map exactly to the documented normalized [0, 65535] range.
    return round((x - left) * 65535 / (width - 1)), round((y - top) * 65535 / (height - 1))


def _packet(flags: int, x: int = 0, y: int = 0) -> INPUT:
    event = INPUT()
    event.type = 0  # INPUT_MOUSE
    event.mi = MOUSEINPUT(x, y, 0, flags, 0, 0)
    return event


def _click_packets(x: int, y: int, bounds: tuple[int, int, int, int]):
    nx, ny = _normalize(x, y, bounds)
    return (INPUT * 3)(_packet(MOVE_ABSOLUTE_VIRTUAL, nx, ny), _packet(LEFTDOWN), _packet(LEFTUP))


@lru_cache(maxsize=1)
def _api():
    import sys
    if sys.platform != 'win32':
        from hiro.platforms import PlatformUnavailableError
        raise PlatformUnavailableError('SendInput clicks require Windows')
    api = ctypes.WinDLL('user32', use_last_error=True)
    api.GetSystemMetrics.argtypes = [ctypes.c_int]
    api.GetSystemMetrics.restype = ctypes.c_int
    api.SendInput.argtypes = [ctypes.c_uint, ctypes.POINTER(INPUT), ctypes.c_int]
    api.SendInput.restype = ctypes.c_uint
    return api


def click_screen(x: int, y: int) -> None:
    """Insert one MOVE/DOWN/UP batch; caller owns foreground and target checks.

    Successful insertion does not prove the target consumed the click. No hold
    duration is inserted. This API never retries a click after partial failure.
    """
    api = _api()
    bounds = tuple(api.GetSystemMetrics(index) for index in (76, 77, 78, 79))
    packets = _click_packets(x, y, bounds)
    accepted = api.SendInput(3, packets, ctypes.sizeof(INPUT))
    if accepted != 3:
        cleanup = ''
        if accepted == 2:
            release = (INPUT * 1)(_packet(LEFTUP))
            released = api.SendInput(1, release, ctypes.sizeof(INPUT))
            cleanup = f'; release cleanup accepted {released}/1'
        raise RuntimeError(f'SendInput accepted {accepted}/3 events{cleanup}; click not retried')
