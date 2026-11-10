"""Demi-journées, calculées côté app à partir de `event_ts` (UTC) converti en Europe/Paris.

`heure < 13 → matin`, sinon après-midi (0h-6h rattaché au matin, 20h-24h à l'après-midi).
Clé : `'2026-11-09_matin'` ou `'2026-11-09_apres_midi'`.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Paris")
MATIN = "matin"
APRES_MIDI = "apres_midi"
HEURE_BASCULE = 13
_SLOTS = (MATIN, APRES_MIDI)
_LABELS = {MATIN: "matin", APRES_MIDI: "après-midi"}
_JOURS = ("lun.", "mar.", "mer.", "jeu.", "ven.", "sam.", "dim.")


def demi_journee(ts: int) -> str:
    """Demi-journée d'un timestamp Unix (fonction totale)."""
    local = datetime.fromtimestamp(ts, TZ)
    slot = MATIN if local.hour < HEURE_BASCULE else APRES_MIDI
    return f"{local.date().isoformat()}_{slot}"


def _parse(dj: str) -> tuple[date, str]:
    day_s, _, slot = dj.partition("_")
    if slot not in _SLOTS:
        raise ValueError(f"demi-journée invalide : {dj!r}")
    return date.fromisoformat(day_s), slot


def _local_ts(d: date, t: time) -> int:
    return int(datetime.combine(d, t, TZ).timestamp())


def intervalle(dj: str) -> tuple[int, int]:
    """Intervalle `[debut, fin)` de `event_ts` couvert par la demi-journée."""
    d, slot = _parse(dj)
    midi = _local_ts(d, time(HEURE_BASCULE))
    if slot == MATIN:
        return _local_ts(d, time(0)), midi
    return midi, _local_ts(d + timedelta(days=1), time(0))


def decaler(dj: str, n: int) -> str:
    """Demi-journée située `n` crans plus loin (négatif = passé)."""
    d, slot = _parse(dj)
    idx = d.toordinal() * 2 + _SLOTS.index(slot) + n
    return f"{date.fromordinal(idx // 2).isoformat()}_{_SLOTS[idx % 2]}"


def mois(dj: str) -> int:
    return _parse(dj)[0].month


def libelle(dj: str) -> str:
    d, slot = _parse(dj)
    return f"{_JOURS[d.weekday()]} {d.strftime('%d/%m')} · {_LABELS[slot]}"
