"""Lazy platform capabilities, independent of game strategy and optional OS libraries.

Providers can be modules or zero-argument factories (module:factory). Registration
accepts a provider instance and takes precedence over environment configuration.
"""
from __future__ import annotations

import importlib
import os
import sys
from functools import lru_cache
from typing import Any, Literal, Protocol

Kind = Literal["device", "ocr", "window"]
ENV = {"device": "HIRO_DEVICE_BACKEND", "ocr": "HIRO_OCR_BACKEND", "window": "HIRO_WINDOW_BACKEND"}
_registered: dict[str, Any] = {}


class PlatformUnavailableError(RuntimeError):
    """A requested platform capability has no installed implementation."""


class DeviceBackend(Protocol):
    def connect(self, backend: str = "auto") -> Any:
        """Return a started kotonebot-compatible device; screenshots/clicks use 720x1280 logical pixels.

        The provider owns physical/client coordinate conversion and initialization
        of the KAA scaler. The caller owns the returned device's lifetime (stop).
        """
        ...

    def real_click(self, lx: int, ly: int) -> None:
        """Explicit foreground mouse fallback, using the same logical coordinates."""
        ...


class OCRBackend(Protocol):
    def ocr(self, img: Any, *, scale: float = 3.0, languages=("ja-JP", "en-US")) -> list[tuple[str, float]]: ...

    def ocr_boxes(self, img: Any, *, scale: float = 3.0, languages=("ja-JP", "en-US")) -> list[tuple[str, float, tuple[int, int, int, int]]]:
        """BGR image → text/confidence (0..1)/box in original image top-left pixels.

        scale is an internal recognition aid, never a multiplier on returned boxes.
        Empty means no text; unavailable engines must raise, not fabricate a result.
        """
        ...


class WindowGuard(Protocol):
    def tick(self, img: Any, texts: list[str] | None = None) -> bool:
        """True only when window recovery acted, so dispatch should skip this frame."""
        ...

    def in_live(self, img: Any) -> bool:
        """Whether this frame belongs to LIVE; client-specific, not simply window aspect ratio."""
        ...


class WindowBackend(Protocol):
    def create_guard(self) -> WindowGuard:
        """Create independent per-controller recovery state."""
        ...

    def window_bounds(self) -> tuple[float, float, float, float]:
        """Screen-space outer window x/y/width/height; input conversion is provider-owned."""
        ...


def register(kind: Kind, provider: Any) -> None:
    """Install an implementation before connecting devices/creating window guards."""
    if kind not in ENV:
        raise ValueError(f"Unknown platform capability: {kind}")
    _registered[kind] = provider


def reset() -> None:
    """Clear provider selection for tests/reconfiguration; does not stop live devices."""
    _registered.clear()
    _load.cache_clear()


@lru_cache(maxsize=None)
def _load(spec: str):
    module, sep, factory = spec.partition(":")
    loaded = importlib.import_module(module)
    return getattr(loaded, factory)() if sep else loaded


def get_backend(kind: Kind):
    if kind not in ENV:
        raise ValueError(f"Unknown platform capability: {kind}")
    if kind in _registered:
        return _registered[kind]
    spec = os.environ.get(ENV[kind])
    if not spec:
        if sys.platform != "darwin":
            raise PlatformUnavailableError(
                f"No default {kind} backend for {sys.platform}. Windows/DMM providers require explicit opt-in; "
                f"set {ENV[kind]}=package.module[:factory] or register an implementation."
            )
        spec = f"hiro.platforms.macos.{kind}"
    return _load(spec)
