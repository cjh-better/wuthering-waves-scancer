# -*- coding: utf-8 -*-
"""
Screenshot backend abstraction.

DXGI (GPU), BitBlt (win32) and PIL are different implementations of one
contract – :class:`ScreenshotBackend`.  Callers iterate an ordered
backend chain instead of hard-coding ``if dxgi: … elif bitblt: …``
ladders.  Backends that cannot initialise (non-Windows, missing libs)
are simply absent from the chain, so importing this module never breaks
on Linux.
"""
from typing import List, Optional, Protocol, runtime_checkable

from PIL import Image, ImageGrab

from utils.log import get_logger


logger = get_logger("Screenshot")


@runtime_checkable
class ScreenshotBackend(Protocol):
    """Screenshot backend contract.

    Implementations handle DPI scaling internally and return a
    ``PIL.Image`` in logical (unscaled) coordinates, or ``None`` when
    the capture failed.  Must never raise for degenerate regions –
    return ``None`` instead.
    """

    name: str

    def grab_region(
        self, x: int, y: int, width: int, height: int
    ) -> Optional[Image.Image]:
        ...


class PILBackend:
    """PIL.ImageGrab backend – always available, slowest."""

    name = "PIL"

    def __init__(self, scale_factor: float = 1.0):
        self.scale_factor = scale_factor

    def grab_region(
        self, x: int, y: int, width: int, height: int
    ) -> Optional[Image.Image]:
        if width <= 0 or height <= 0:
            return None
        x_scaled = int(x * self.scale_factor)
        y_scaled = int(y * self.scale_factor)
        w_scaled = int(width * self.scale_factor)
        h_scaled = int(height * self.scale_factor)
        try:
            return ImageGrab.grab(
                bbox=(x_scaled, y_scaled, x_scaled + w_scaled, y_scaled + h_scaled)
            )
        except Exception as e:
            logger.warning("[Screenshot] PIL grab failed: %s", e)
            return None


def available_backends(scale_factor: float = 1.0) -> List[ScreenshotBackend]:
    """Return the ordered screenshot backend chain.

    Order is DXGI → BitBlt → PIL, mirroring the historical priority.
    BitBlt is only initialised when DXGI is unavailable (same as the
    previous behaviour); PIL is always present as the last resort.
    """
    chain: List[ScreenshotBackend] = []

    try:
        from utils.dxgi_screenshot import get_dxgi_screenshot

        dxgi = get_dxgi_screenshot()
    except Exception as e:
        logger.warning("[Screenshot] DXGI backend unavailable: %s", e)
        dxgi = None
    if dxgi is not None:
        chain.append(dxgi)
    else:
        try:
            from utils.fast_screenshot import get_fast_screenshot

            bitblt = get_fast_screenshot()
        except Exception as e:
            logger.warning("[Screenshot] BitBlt backend unavailable: %s", e)
            bitblt = None
        if bitblt is not None:
            chain.append(bitblt)

    chain.append(PILBackend(scale_factor))
    return chain


def grab_region_first_success(
    backends: List[ScreenshotBackend], x: int, y: int, width: int, height: int
) -> "tuple[Optional[Image.Image], str]":
    """Try each backend in order; return ``(image, backend_name)``.

    Returns ``(None, "unknown")`` when every backend failed.
    """
    for backend in backends:
        try:
            img = backend.grab_region(x, y, width, height)
        except Exception:
            continue
        if img is not None:
            return img, backend.name
    return None, "unknown"
