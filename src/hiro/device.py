"""Platform-neutral device factory. The backend returns a started KAA-compatible device."""
from hiro.platforms import get_backend


def connect(backend: str = "auto"):
    """Use the selected platform provider; backend selects its capture/input mode.

    macOS retains auto / maatools / quartz and logical resolution 720x1280.
    Select a different provider with HIRO_DEVICE_BACKEND or platforms.register().
    """
    return get_backend("device").connect(backend=backend)
