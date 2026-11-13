"""Niveaux génériques calculés à partir de seuils fournis."""
from __future__ import annotations

import math


def level(value: float | None, thresholds: dict | None) -> str:
    if value is None or thresholds is None or math.isnan(float(value)):
        return "inconnu"
    if value < thresholds["p50"]:
        return "calme"
    if value < thresholds["p80"]:
        return "normal"
    if value < thresholds["p95"]:
        return "soutenu"
    return "saturé"
