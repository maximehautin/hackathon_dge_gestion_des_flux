"""M2 Indice de pression : seuils par site (compteurs) et indice multifactoriel par commune.

Site : les seuils sont les quantiles de la distribution journalière des trois
dernières années du compteur : < p50 calme, < p80 normal, < p95 soutenu, >= p95 saturé.
Commune : chaque facteur devient un rang 0-100 parmi les communes. Le score de
fréquentation est la moyenne des rangs disponibles des passages ENS et des sites
signalés par les OT, chaque rang étant calculé uniquement parmi les communes
concernées. Pression = rang de (fréquentation - 0,5 x capacité d'accueil), potentiel
= rang de (offre + 0,5 x capacité - fréquentation). Capacité : lits, gares. Sans
compteur ni site signalé, la commune est « données insuffisantes ».
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from . import config as C
from .data import load_ens_daily, load_gares, load_hebergements, load_offre_communes, load_overvisited, haversine_km
from .levels import level as _shared_level

LEVELS = ["calme", "normal", "soutenu", "saturé"]
COLORS = {"calme": "#2e7d32", "normal": "#7cb342", "soutenu": "#f9a825", "saturé": "#c62828", "inconnu": "#9e9e9e"}
THRESH_PATH = C.ARTIFACTS / "site_thresholds.json"
COMMUNES_PATH = C.ARTIFACTS / "communes_index.parquet"
COUNTER_MAX_KM = 10


def site_thresholds(years: int = 3) -> dict[int, dict]:
    daily, sites = load_ens_daily()
    recent = daily[daily["date"] >= daily["date"].max() - pd.Timedelta(days=365 * years)]
    out = {}
    for sid, g in recent.groupby("site_id"):
        if len(g) < 120:
            continue
        q = g["count"].quantile([0.5, 0.8, 0.95]).tolist()
        out[int(sid)] = {"p50": q[0], "p80": q[1], "p95": q[2], "max": float(g["count"].max()), "n_days": int(len(g))}
    THRESH_PATH.write_text(json.dumps(out))
    return out


def level(value: float | None, th: dict | None) -> str:
    return _shared_level(value, th)


def _score(s: pd.Series) -> pd.Series:
    """Rang-percentile 0-100 (robuste aux valeurs extrêmes)."""
    return (s.rank(pct=True) * 100).round(1)


def communes_index() -> pd.DataFrame:
    offre = load_offre_communes()
    heb = load_hebergements()
    gares = load_gares()
    ov, _ = load_overvisited()
    daily, sites = load_ens_daily()

    # fréquentation moyenne annuelle des compteurs rattachés à la commune la plus proche d'un site surfréquenté / d'une commune via le centroïde des POI
    recent = daily[daily["date"] >= daily["date"].max() - pd.Timedelta(days=365)]
    site_year = recent.groupby("site_id")["count"].sum().rename("passages_an").reset_index().merge(sites, on="site_id")

    communes = offre[["commune"]].drop_duplicates()
    df = communes.merge(offre, on="commune", how="left").merge(heb, on="commune", how="left").merge(gares, on="commune", how="left")
    df = df.fillna({"lits": 0, "n_etablissements": 0, "gares": 0})
    df["sites_surfrequentes"] = df["commune"].map(ov["commune"].value_counts()).fillna(0)

    # chaque compteur est rattaché à une seule commune : celle dont le centroïde des POI DataTourisme est le plus proche
    from .data import load_pois
    pois = load_pois()
    cent = pois.groupby("commune")[["lat", "lon"]].mean().reset_index()
    df = df.merge(cent, on="commune", how="left")
    located = df.dropna(subset=["lat"]).reset_index(drop=True)
    owner = {}
    for s in site_year.itertuples():
        d = haversine_km(s.lat, s.lon, located["lat"].to_numpy(), located["lon"].to_numpy())
        i = int(np.argmin(d))
        if d[i] < COUNTER_MAX_KM:
            owner[s.site_id] = located.at[i, "commune"]
    by_commune = site_year.assign(commune=site_year["site_id"].map(owner)).groupby("commune")["passages_an"]
    df["passages_compteurs_an"] = df["commune"].map(by_commune.sum()).fillna(0.0)
    df["n_compteurs"] = df["commune"].map(by_commune.size()).fillna(0).astype(int)

    offer_cols = ["Sites culturels", "Sites sportifs, récréatifs et de loisirs", "Prestataires d'activités", "Evènements culturels, sportifs et de loisirs"]
    df["offre"] = df[offer_cols].fillna(0).sum(axis=1)
    df["offre_score"] = _score(df["offre"])
    # sans compteur ni site signalé, la fréquentation est inconnue : pas de score plutôt qu'un rang moyen
    counted = df["n_compteurs"] > 0
    signaled = df["sites_surfrequentes"] > 0
    known = counted | signaled
    passages_score = _score(df.loc[counted, "passages_compteurs_an"]).reindex(df.index)
    sites_score = _score(df.loc[signaled, "sites_surfrequentes"]).reindex(df.index)
    freq = pd.concat([passages_score, sites_score], axis=1).mean(axis=1)
    df["frequentation_score"] = freq.round(1)
    cap = _score(df["lits"]) * 0.7 + _score(df["gares"]) * 0.3
    df["capacite_score"] = cap.round(1)
    k = df[known]
    df["pression"] = _score((k["frequentation_score"] - 0.5 * k["capacite_score"]).clip(lower=0)).reindex(df.index)
    df["potentiel"] = _score((k["offre_score"] + 0.5 * k["capacite_score"]) - k["frequentation_score"]).reindex(df.index)

    def cls(r):
        if pd.isna(r.frequentation_score):
            return "données insuffisantes"
        if r.frequentation_score >= 80 and r.pression >= 75:
            return "sous pression"
        if r.potentiel >= 75 and r.frequentation_score < 60:
            return "potentiel sous-exploité"
        return "équilibré"

    df["classe"] = [cls(r) for r in df.itertuples()]
    keep = ["commune", "lat", "lon", "offre", "lits", "gares", "sites_surfrequentes", "passages_compteurs_an", "n_compteurs",
            "offre_score", "frequentation_score", "capacite_score", "pression", "potentiel", "classe"]
    df = df[keep]
    df.to_parquet(COMMUNES_PATH, index=False)
    return df
