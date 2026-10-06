# -*- coding: utf-8 -*-
"""Central logging setup for wuthering-waves-scancer.

Replaces ad-hoc ``print()`` calls with the standard :mod:`logging` module so
log output can be filtered, redirected, or silenced by the caller.

Console output is intentionally kept identical to the old ``print()`` style:
messages are written to stdout as plain text (existing ``[Tag] ...``
prefixes are preserved in the message itself).
"""
from __future__ import annotations

import logging
import sys

_configured = False


def _configure() -> None:
    """Install a single stdout handler once per process (idempotent)."""
    global _configured
    if _configured:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(message)s"))
    root = logging.getLogger("wws")
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    # Don't propagate to the real root logger: the app never configured one,
    # and we don't want duplicate lines if an embedder did.
    root.propagate = False
    _configured = True


def get_logger(name: str) -> logging.Logger:
    """Return a child logger of the ``wws`` namespace (configures on first use)."""
    _configure()
    return logging.getLogger("wws.%s" % name)
