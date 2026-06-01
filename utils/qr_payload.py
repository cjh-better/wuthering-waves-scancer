# -*- coding: utf-8 -*-
"""Helpers for validating and de-duplicating Wuthering Waves QR payloads."""

from __future__ import annotations

from typing import Optional


KURO_MARKERS = ("G152#KURO", "KURO")
TICKET_LENGTH = 24


def normalise_qr_text(value: object) -> str:
    """Return decoded QR text, or an empty string if it is unusable."""
    if value is None:
        return ""
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8")
        except UnicodeDecodeError:
            return value.decode("utf-8", errors="ignore")
    return str(value)


def is_kuro_qr(value: object) -> bool:
    """True when the decoded QR payload looks like a Kuro login QR."""
    text = normalise_qr_text(value)
    upper_text = text.upper()
    return any(marker in upper_text for marker in KURO_MARKERS)


def extract_kuro_ticket(value: object) -> Optional[str]:
    """Return the stable de-duplication key for a Kuro QR payload.

    Kuro login URLs keep the short-lived ticket in the final 24 characters.
    Short test/development payloads still use the whole payload so existing
    simulator and regression cases remain observable.
    """
    text = normalise_qr_text(value).strip()
    if not text or not is_kuro_qr(text):
        return None
    if len(text) >= TICKET_LENGTH:
        return text[-TICKET_LENGTH:]
    return text
