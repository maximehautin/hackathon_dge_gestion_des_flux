"""Variables explicatives communes aux modèles : calendrier, météo, retards."""
from __future__ import annotations

from datetime import date

import holidays
import numpy as np
import pandas as pd

from . import config as C
from .data import school_holidays

FR_HOLIDAYS = holidays.France(years=range(2008, 2030))
LAGS = (7, 14, 21, 28, 364)


def calendar_features(dates: pd.Series) -> pd.DataFrame:
    d = pd.to_datetime(dates)
    vac = school_holidays()
    as_date = d.dt.date
    in_vac = np.zeros(len(d), dtype=bool)
    for s, e in vac:
        in_vac |= ((as_date >= s) & (as_date <= e)).to_numpy()
    f = pd.DataFrame({
        "dow": d.dt.dayofweek.to_numpy(),
        "month": d.dt.month.to_numpy(),
        "doy": d.dt.dayofyear.to_numpy(),
        "year": d.dt.year.to_numpy(),
        "weekend": (d.dt.dayofweek >= 5).astype(int).to_numpy(),
        "ferie": np.array([x in FR_HOLIDAYS for x in as_date], dtype=int),
        "vacances": in_vac.astype(int),
    })
    f["pont"] = ((f["dow"] == 4) & np.roll(f["ferie"].to_numpy(), 1).astype(bool)).astype(int)
    f["off"] = ((f["weekend"] + f["ferie"] + f["vacances"]) > 0).astype(int)
    return f


def add_lags(df: pd.DataFrame, target: str = "count") -> pd.DataFrame:
    """Retards >= 7 jours uniquement, pour qu'une prévision à J+7 n'utilise que du passé connu."""
    df = df.sort_values(["site_id", "date"]).copy()
    full = (
        df.set_index("date").groupby("site_id")[target]
        .apply(lambda s: s.asfreq("D"))
        .reset_index()
    )
    g = full.groupby("site_id")[target]
    for lag in LAGS:
        full[f"lag_{lag}"] = g.shift(lag)
    full["roll_28"] = g.transform(lambda s: s.shift(7).rolling(28, min_periods=7).mean())
    full["roll_dow_4"] = g.transform(lambda s: s.shift(7).rolling(22, min_periods=1).apply(lambda w: np.nanmean(w[::7][-4:]) if len(w) else np.nan, raw=True))
    return full


def seasonal_baseline(full: pd.DataFrame) -> pd.Series:
    """Référence naïve : moyenne des 4 derniers mêmes jours de semaine connus (lags 7, 14, 21, 28)."""
    return full[[f"lag_{l}" for l in (7, 14, 21, 28)]].mean(axis=1)
