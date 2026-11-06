"""DMM window bounds and conservative, frame-only LIVE recognition.

DMM has no demonstrated need for PlayCover's fullscreen repair. tick therefore
performs no desktop action; in_live recognizes KAA's actual skip-performance UI.
Hidden controls, LIVE start screens and landscape dialogs are not classified.
"""
from functools import lru_cache


@lru_cache(maxsize=1)
def _live_matcher():
    from hiro.platforms import PlatformUnavailableError
    try:
        from kaa.tasks import R
        from kaa.game_ui import WhiteFilter
        from kotonebot.backend.image import find
        template = R.Produce.ButtonSkipLive.template
        # Force resource loading now, so missing generated sprites are errors.
        template.pixels
    except (ImportError, AttributeError, FileNotFoundError) as exc:
        raise PlatformUnavailableError('Windows LIVE recognition requires KAA and generated R.py/sprites; run setup-windows.ps1.') from exc
    return find, template, WhiteFilter()


class WindowGuard:
    def tick(self, img, texts=None) -> bool:
        """No proven DMM recovery action; never toggle fullscreen speculatively."""
        return False

    def in_live(self, img) -> bool:
        find, template, white_filter = _live_matcher()
        if img is None or img.size == 0:
            return False
        h, w = img.shape[:2]
        # Shape is only a prerequisite, never positive evidence of LIVE.
        if w <= h or abs(w / h - 16 / 9) > 0.03:
            return False
        import cv2
        if (w, h) != (1280, 720):
            img = cv2.resize(img, (1280, 720), interpolation=cv2.INTER_CUBIC)
        return find(img, template, preprocessors=[white_filter], threshold=0.8, debug_output=False) is not None


def create_guard():
    return WindowGuard()


def window_bounds() -> tuple[float, float, float, float]:
    from .target import resolve
    window, _ = resolve()
    bounds = window.get_bounds()
    if bounds is None:
        raise RuntimeError('Selected Windows window has no readable bounds')
    return bounds.x1, bounds.y1, bounds.w, bounds.h
