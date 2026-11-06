"""Explicit foreground-click fallback routed through the selected platform provider."""
from hiro.platforms import get_backend


def click(lx: int, ly: int) -> None:
    return get_backend("device").real_click(lx, ly)


def window_bounds() -> tuple[float, float, float, float]:
    return get_backend("window").window_bounds()


def to_screen(lx: float, ly: float, bounds: tuple[float, float, float, float]) -> tuple[float, float]:
    """Legacy PlayCover conversion (28px title bar); not a Windows coordinate contract."""
    x, y, w, _ = bounds
    scale = w / 720
    return x + lx * scale, y + 28 + ly * scale
