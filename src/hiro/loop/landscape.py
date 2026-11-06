"""Window lifecycle facade; PlayCover-specific recovery lives in platforms.macos."""
from hiro.platforms import get_backend


class LandscapeGuard:
    def __init__(self):
        self._guard = get_backend("window").create_guard()

    def tick(self, img, texts: list[str] | None = None) -> bool:
        return self._guard.tick(img, texts)

    def in_live(self, img) -> bool:
        return self._guard.in_live(img)
