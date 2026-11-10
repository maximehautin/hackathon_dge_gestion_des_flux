"""Profils horaires moyens des compteurs ENS et des routes SMMAG."""
from __future__ import annotations

import json
import sys
from datetime import datetime

import numpy as np
import pandas as pd

from . import config as C
from .data import load_ens_hourly
from .features import FR_HOLIDAYS
from .frequentation import SMMAG

HORAIRES_PATH = C.ARTIFACTS / "horaires.json"
HOURS = list(range(24))
HOUR_COLUMNS = [f"h{hour + 1}" for hour in HOURS]


def type_jour(value: object) -> str:
    day = pd.Timestamp(value).date()
    return "weekend" if day.weekday() >= 5 or day in FR_HOLIDAYS else "semaine"


def _profiles(daily_parts: pd.DataFrame) -> dict:
    profiles = {}
    if daily_parts.empty:
        return profiles
    day_types = pd.Series([type_jour(value) for value in daily_parts.index], index=daily_parts.index)
    for day_type in ("semaine", "weekend"):
        selected = daily_parts.loc[day_types == day_type]
        if len(selected) < 30:
            continue
        parts = selected.mean(axis=0).reindex(HOURS).fillna(0)
        total = float(parts.sum())
        if total <= 0:
            continue
        profiles[day_type] = {
            "parts": (parts / total).astype(float).tolist(),
            "n_jours": int(len(selected)),
        }
    return profiles


def _ens_profiles(hourly: pd.DataFrame) -> dict:
    result = {}
    if hourly.empty:
        return result
    for site_id, rows in hourly.groupby("site_id"):
        years = sorted({pd.Timestamp(value).year for value in rows["date"]})[-3:]
        rows = rows[rows["date"].map(lambda value: pd.Timestamp(value).year in years)]
        daily = rows.pivot_table(index="date", columns="hour", values="count", aggfunc="sum")
        daily = daily.reindex(columns=HOURS)
        complete = daily.notna().sum(axis=1) == 24
        daily = daily.loc[complete].fillna(0)
        totals = daily.sum(axis=1)
        daily = daily.loc[totals > 0].div(totals[totals > 0], axis=0)
        profiles = _profiles(daily)
        if profiles:
            result[str(int(site_id))] = profiles
    return result


def _route_parts(rows: pd.DataFrame) -> pd.DataFrame:
    counts = rows[HOUR_COLUMNS].apply(pd.to_numeric, errors="coerce").fillna(0)
    counts.columns = HOURS
    totals = pd.to_numeric(rows["total_jour"], errors="coerce")
    valid = totals.gt(0) & counts.sum(axis=1).gt(0)
    counts = counts.loc[valid]
    totals = totals.loc[valid]
    counts.index = pd.to_datetime(rows.loc[valid, "date"]).dt.date
    totals.index = counts.index
    return counts.div(totals, axis=0).groupby(level=0).mean()


def _route_profiles(path) -> dict:
    if not path.exists():
        print(f"[avertissement] fichier de comptages routiers absent : {path}", file=sys.stderr)
        return {}
    frame = pd.read_excel(path)
    frame = frame[
        frame["station"].isin(SMMAG)
        & frame["Valide"].eq(True)
        & pd.to_numeric(frame["total_jour"], errors="coerce").gt(0)
    ].copy()
    result = {}
    for station in SMMAG:
        station_rows = frame[frame["station"] == station]
        if station_rows.empty:
            continue
        directions = {}
        for direction, rows in station_rows.groupby("sens"):
            parts = _route_parts(rows)
            if parts.empty:
                continue
            mean_profile = parts.mean(axis=0).reindex(HOURS).fillna(0)
            weight = float(mean_profile.sum())
            if weight <= 0:
                continue
            mean_hour = float(np.dot(mean_profile.to_numpy(), HOURS) / weight)
            directions[str(direction)] = (mean_hour, parts)
        if not directions:
            continue
        direction, (_, parts) = min(directions.items(), key=lambda item: item[1][0])
        profiles = _profiles(parts)
        if profiles:
            result[station] = {"sens": direction, **profiles}
    return result


def build() -> dict:
    """Construit et écrit les profils horaires ENS et SMMAG."""
    hourly = load_ens_hourly()
    if hourly.empty:
        raise RuntimeError(f"Aucune mesure horaire ENS trouvée dans {C.DATA_DIR / C.D_ENS}.")
    ens = _ens_profiles(hourly)
    routes = _route_profiles(C.DATA_DIR / "Fréquentation/Comptages routiers SMMAG.xlsx")
    result = {
        "ens": ens,
        "routes": routes,
        "construit_le": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    HORAIRES_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"series_ens": len(ens), "series_routes": len(routes)}


def conseil(parts: list[float]) -> dict:
    """Résume l'heure de pointe, l'arrivée conseillée et les plages calmes."""
    if len(parts) != 24:
        raise ValueError("Un profil horaire doit contenir 24 valeurs.")
    values = [float(value) for value in parts]
    peak = max(range(24), key=values.__getitem__)
    maximum = values[peak]
    arrive_before = next(
        (hour for hour in range(6, peak + 1) if values[hour] >= 0.7 * maximum),
        None,
    )
    if arrive_before is not None and arrive_before <= 6:
        arrive_before = None

    quiet = []
    start = None
    for hour in range(8, 20):
        if values[hour] <= 0.5 * maximum:
            if start is None:
                start = hour
        elif start is not None:
            quiet.append({"debut": start, "fin": hour})
            start = None
    if start is not None:
        quiet.append({"debut": start, "fin": 20})

    text = f"Affluence maximale vers {peak} h."
    if arrive_before is not None:
        text += f" Arrivez avant {arrive_before} h."
    return {
        "pointe": peak,
        "arriver_avant": arrive_before,
        "creneaux_calmes": quiet,
        "texte": text,
    }
