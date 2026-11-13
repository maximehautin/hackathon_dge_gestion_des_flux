"""Chargement des données du bucket SSP Cloud et des sources externes ouvertes.

Toutes les fonctions lisent dans ``config.DATA_DIR`` (copie locale du dossier
``diffusion/`` du bucket, voir ``scripts/download_data.py``) et mettent en cache
les résultats lourds dans ``config.ARTIFACTS``.
"""
from __future__ import annotations

import io
import json
import math
import re
import sys
import time
import zipfile
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import requests

from . import config as C

# --------------------------------------------------------------------------- utils

def _clean(s: object) -> str:
    s = str(s)
    if "Ã" in s or "Â" in s:  # noms DataTourisme doublement encodés (« Chà¢teau »)
        try:
            s = s.encode("latin-1").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
    s = s.replace("à¢", "â")  # même défaut, « â » devenu « à¢ » (« Chà¢tonnay »)
    return re.sub(r"\s+", " ", s).strip()


def _num(s: object) -> float | None:
    """Convertit « 45,1234 » ou « \t5.52 » en float."""
    try:
        return float(_clean(s).replace(",", "."))
    except ValueError:
        return None


def haversine_km(lat1, lon1, lat2, lon2):
    import numpy as np

    lat1, lon1, lat2, lon2 = map(np.radians, (lat1, lon1, lat2, lon2))
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 6371.0 * 2 * np.arcsin(np.sqrt(a))


# --------------------------------------------------------------------------- éco-compteurs ENS

def _iter_ens_pedestrian_frames():
    for zp in sorted((C.DATA_DIR / C.D_ENS).glob("*.zip")):
        with zipfile.ZipFile(zp) as archive:
            sites = pd.read_csv(archive.open("sites.csv"), sep=None, engine="python")
            channels = pd.read_csv(archive.open("channels.csv"), sep=None, engine="python")
            measures = pd.read_csv(archive.open("measures.csv"), sep=None, engine="python")
        channels = channels[channels["mobility_type"].str.upper() == "PEDESTRIAN"][["channel_id", "site_id"]]
        measures = measures.merge(channels, on="channel_id")
        if measures.empty:
            continue
        local_time = pd.to_datetime(measures["start_datetime"], utc=True).dt.tz_convert(C.TZ)
        measures["date"] = local_time.dt.date
        measures["hour"] = local_time.dt.hour
        yield sites[["site_id", "site_name", "xlong", "ylat"]], measures[["site_id", "date", "hour", "count"]]


def load_ens_hourly() -> pd.DataFrame:
    """Comptages piétonniers ENS par site, jour et heure locale issus des archives ZIP."""
    frames = []
    for _, measures in _iter_ens_pedestrian_frames():
        frames.append(
            measures.groupby(["site_id", "date", "hour"], as_index=False)["count"].sum()
        )
    if not frames:
        return pd.DataFrame(columns=["site_id", "date", "hour", "count"])
    hourly = pd.concat(frames, ignore_index=True)
    return hourly.groupby(["site_id", "date", "hour"], as_index=False)["count"].sum()


def load_ens_daily(force: bool = False) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Séries journalières piétonnes par site ENS (2009-2026) et référentiel des sites.

    Retourne (daily, sites) :
      daily : site_id, date, count, hours (nb d'heures mesurées dans la journée)
      sites : site_id, site_name, lat, lon, first_date, last_date, n_days, mean_daily, en_panne, donnees_anciennes,
              jours_panne (jours à zéro retirés), pannes (périodes « début/fin » ISO)
    """
    p_daily = C.ARTIFACTS / "ens_daily.parquet"
    p_sites = C.ARTIFACTS / "ens_sites.parquet"
    if p_daily.exists() and p_sites.exists() and not force:
        cached_sites = pd.read_parquet(p_sites)
        if {"en_panne", "jours_panne", "pannes"}.issubset(cached_sites.columns):
            return pd.read_parquet(p_daily), cached_sites

    frames, sites_frames = [], []
    for sites, measures in _iter_ens_pedestrian_frames():
        d = measures.groupby(["site_id", "date"]).agg(
            count=("count", "sum"), hours=("hour", "nunique")
        ).reset_index()
        frames.append(d)
        sites_frames.append(sites)

    daily = pd.concat(frames, ignore_index=True)
    daily["date"] = pd.to_datetime(daily["date"])
    daily = daily.groupby(["site_id", "date"], as_index=False).agg(count=("count", "sum"), hours=("hours", "max"))
    # une journée n'est gardée que si au moins 20 heures ont été mesurées
    daily = daily[daily["hours"] >= 20].copy()
    sites = pd.concat(sites_frames).drop_duplicates("site_id", keep="last")
    # les fichiers Eco-Compteur 2021-2026, plus récents et plus complets, priment sur les archives
    eco = _load_eco_daily(set(sites["site_id"]))
    if not eco.empty:
        daily = pd.concat([eco, daily], ignore_index=True).drop_duplicates(["site_id", "date"], keep="first")
    # valeurs aberrantes (compteur en défaut) : au-delà de 20 fois le quantile 95 du site
    q95 = daily.groupby("site_id")["count"].transform(lambda s: s.quantile(0.95))
    daily = daily[(daily["count"] <= 20 * q95.clip(lower=10))].copy()
    raw_last = daily.groupby("site_id")["date"].max().rename("raw_last")
    runs = dead_runs(daily)
    daily = drop_dead_runs(daily)

    sites = sites.rename(columns={"xlong": "lon", "ylat": "lat"})
    sites["site_name"] = sites["site_name"].map(_clean)
    agg = daily.groupby("site_id").agg(first_date=("date", "min"), last_date=("date", "max"), n_days=("date", "count"), mean_daily=("count", "mean"))
    sites = sites.merge(agg, on="site_id", how="inner").reset_index(drop=True)
    sites["en_panne"] = sites["site_id"].map(raw_last) > sites["last_date"]
    sites["donnees_anciennes"] = sites["last_date"] < daily["date"].max() - pd.Timedelta(days=C.STALE_DAYS)
    sites["jours_panne"] = sites["site_id"].map(runs.groupby("site_id")["jours"].sum()).fillna(0).astype(int)
    periods = runs.sort_values("debut").groupby("site_id").apply(
        lambda g: [f"{a.date()}/{b.date()}" for a, b in zip(g["debut"], g["fin"])], include_groups=False
    )
    sites["pannes"] = [periods.get(sid, []) for sid in sites["site_id"]]

    daily.to_parquet(p_daily, index=False)
    sites.to_parquet(p_sites, index=False)
    return daily, sites


def _load_eco_daily(site_ids: set) -> pd.DataFrame:
    """Passages piétons journaliers des fichiers Eco-Compteur 2021-2026, sens 1 et 2 additionnés."""
    frames = []
    for f in (C.F_ECO_HIST, C.F_ECO_DAILY):
        path = C.DATA_DIR / f
        if not path.exists():
            print(f"[avertissement] fichier Eco-Compteur absent : {path}", file=sys.stderr)
            continue
        d = pd.read_csv(path, usecols=["site_id", "date", "user_type", "counts"])
        d = d[(d["user_type"] == "pedestrian") & d["site_id"].isin(site_ids)]
        frames.append(d.groupby(["site_id", "date"], as_index=False)["counts"].sum().rename(columns={"counts": "count"}))
    if not frames:
        return pd.DataFrame(columns=["site_id", "date", "count", "hours"])
    eco = pd.concat(frames, ignore_index=True)
    eco["date"] = pd.to_datetime(eco["date"])
    eco["hours"] = 24
    return eco.drop_duplicates(["site_id", "date"], keep="last")


def _dead_mask(d: pd.DataFrame, min_days: int) -> tuple[pd.Series, pd.Series]:
    zero = d["count"] == 0
    new_run = ~zero | (d["site_id"] != d["site_id"].shift()) | (d["date"].diff() != pd.Timedelta(days=1)) | ~zero.shift(fill_value=False)
    run_id = new_run.cumsum()
    run_len = zero.groupby(run_id).transform("sum")
    return zero & (run_len >= min_days), run_id


def drop_dead_runs(daily: pd.DataFrame, min_days: int = C.DEAD_RUN_DAYS) -> pd.DataFrame:
    """Retire les suites d'au moins ``min_days`` jours consécutifs à zéro : compteur en panne, pas site vide."""
    d = daily.sort_values(["site_id", "date"]).reset_index(drop=True)
    dead, _ = _dead_mask(d, min_days)
    return d[~dead].copy()


def dead_runs(daily: pd.DataFrame, min_days: int = C.DEAD_RUN_DAYS) -> pd.DataFrame:
    """Périodes de panne retirées par ``drop_dead_runs`` : site_id, debut, fin, jours."""
    d = daily.sort_values(["site_id", "date"]).reset_index(drop=True)
    dead, run_id = _dead_mask(d, min_days)
    return (
        d[dead].groupby(run_id[dead])
        .agg(site_id=("site_id", "first"), debut=("date", "min"), fin=("date", "max"), jours=("date", "size"))
        .reset_index(drop=True)
    )


# --------------------------------------------------------------------------- sites surfréquentés (offices de tourisme)

def load_overvisited() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Les 53 sites surfréquentés et les 22 lieux conseillés en report (fichier des OT)."""
    xl = pd.read_excel(C.DATA_DIR / C.F_SITES_SURFREQ, sheet_name=None)
    s = xl["Sites fréquentés"].copy()
    s.columns = [_clean(c) for c in s.columns]
    s = s.rename(columns={"Type d'objet touristique": "type", "Identifiant Apidae": "apidae_id", "Nom": "name",
                          "Nom_commune": "commune", "Lattitude": "lat", "Longitude": "lon", "Itinéraire Bis": "itineraire_bis"})
    s["name"] = s["name"].map(_clean)
    s["commune"] = s["commune"].map(_clean)
    s["lat"] = s["lat"].map(_num)
    s["lon"] = s["lon"].map(_num)
    s["itineraire_bis"] = s["itineraire_bis"].map(lambda v: [] if _clean(v) in ("/", "", "nan") else [_clean(x) for x in str(v).split("\n") if _clean(x)])
    s["site_key"] = "ot_" + s.index.astype(str)

    a = xl["Lieux conseignés"].copy()
    a.columns = [_clean(c) for c in a.columns]
    a = a.rename(columns={"Type d'objet touristique": "type", "Identifiant Apidae": "apidae_id", "Nom": "name", "Commune": "commune",
                          "Lattitude": "lat", "Longitude": "lon", "Itinéraire bis de..": "alternative_de"})
    a["name"] = a["name"].map(_clean)
    a["commune"] = a["commune"].map(_clean)
    a["lat"] = a["lat"].map(_num)
    a["lon"] = a["lon"].map(_num)
    a["alternative_de"] = a["alternative_de"].map(lambda v: [_clean(x) for x in str(v).split("\n") if _clean(x) and _clean(x) != "nan"])
    a = a[a["lat"].notna() & a["lon"].notna()].reset_index(drop=True)
    a["site_key"] = "alt_" + a.index.astype(str)
    return s, a[["site_key", "type", "apidae_id", "name", "commune", "lat", "lon", "alternative_de"]]


# --------------------------------------------------------------------------- DataTourisme, hébergements, gares

OUTDOOR_KEYWORDS = {
    "lac": ["lac", "étang", "plage", "base nautique", "baignade"],
    "cascade": ["cascade", "gorges", "pont", "rivière", "canyon"],
    "sommet": ["col ", "col du", "pic", "sommet", "belvédère", "vertige", "crête", "plateau", "pas de"],
    "rando": ["randonnée", "rando", "sentier", "tour ", "trail", "boucle", "refuge", "forêt", "marais", "tourbière"],
    "velo": ["vélo", "vtt", "cyclable", "via "],
    "famille": ["famille", "aire de détente", "camping", "parc", "jardin", "ferme"],
    "culture": ["musée", "château", "église", "abbaye", "grotte", "monument", "scierie", "canal"],
}


def experience_tags(name: str, extra: str = "") -> set[str]:
    txt = " " + re.sub(r"[^\w ]", " ", f"{name} {extra}".lower()) + " "
    tags = {tag for tag, kws in OUTDOOR_KEYWORDS.items() if any(re.search(r"\b" + re.escape(k.strip()) + r"\b", txt) for k in kws)}
    return tags or {"autre"}


def load_pois() -> pd.DataFrame:
    """Objets DataTourisme géolocalisés en Isère (6 075), filtrés sur les lieux de loisir et de nature."""
    d = pd.read_excel(C.DATA_DIR / C.F_DATATOURISME, sheet_name="Données brutes")
    d = d.rename(columns={"Nom": "name", "Type": "type", "Sous-type": "subtype", "Sous-type_1": "subtype2", "NOM_COMM": "commune", "Latitude": "lat", "Longitude": "lon"})
    d = d[d["lat"].notna() & d["lon"].notna()]
    keep = d["subtype"].fillna("").str.contains("Site sportif|Site naturel|Site culturel|Itinéraire", regex=True)
    d = d[keep].reset_index(drop=True)
    d["name"] = d["name"].map(_clean)
    d["commune"] = d["commune"].map(_clean)
    d["site_key"] = "dt_" + d.index.astype(str)
    d["tags"] = [experience_tags(n, f"{a} {b}") for n, a, b in zip(d["name"], d["subtype"].fillna(""), d["subtype2"].fillna(""))]
    return d[["site_key", "name", "type", "subtype", "subtype2", "commune", "lat", "lon", "tags"]]


def load_hebergements() -> pd.DataFrame:
    h = pd.read_excel(C.DATA_DIR / C.F_HEBERGEMENTS, sheet_name="Répartition places d'héberg")
    h = h.rename(columns={"NOM_COMM": "commune", "Nombre total d'établissements": "n_etablissements", "Nombre total lits": "lits"})
    return h[["commune", "n_etablissements", "lits"]].dropna(subset=["commune"])


def load_offre_communes() -> pd.DataFrame:
    o = pd.read_excel(C.DATA_DIR / C.F_DATATOURISME, sheet_name="Sous-type simplifié par comm")
    o = o.rename(columns={"NOM_COMM": "commune"})
    o["commune"] = o["commune"].map(_clean)
    return o


def load_gares() -> pd.DataFrame:
    g = pd.read_excel(C.DATA_DIR / C.F_GARES, header=1)
    g = g.rename(columns={"NOM_COMM": "commune"})
    cols = [c for c in g.columns if str(c).startswith("Gare")]
    g["gares"] = g[cols].fillna(0).sum(axis=1)
    return g[["commune", "gares"]]


def load_communes() -> pd.DataFrame:
    return pd.read_excel(C.DATA_DIR / C.F_COMMUNES).rename(columns={"NOM_COMM": "commune", "CP": "cp"})


# --------------------------------------------------------------------------- forfaits de ski

def load_forfaits() -> pd.DataFrame:
    """Ventes en ligne de forfaits (7 Laux, Collet), 2 saisons. Une ligne = un forfait.

    Seules des colonnes agrégeables sont conservées (pas de date de naissance, pas de référence client).
    """
    p = C.ARTIFACTS / "forfaits.parquet"
    if p.exists():
        return pd.read_parquet(p)
    cols = ["type_produit", "type_vente", "date_debut", "categorie_age", "produit", "categorie_produit", "validite", "facturation_codepostal", "facturation_pays", "prix"]
    xs = pd.read_excel(C.DATA_DIR / C.F_FORFAITS, sheet_name=None, usecols=cols)
    out = []
    for sheet, df in xs.items():
        df = df[df["type_produit"] == "Forfait"].copy()
        df["station"] = "Les 7 Laux" if "7 LAUX" in sheet.upper() else "Le Collet"
        df["saison"] = re.search(r"(\d\d) ?(\d\d)$", sheet).group(0).replace(" ", "-") if re.search(r"(\d\d) ?(\d\d)$", sheet) else sheet
        out.append(df)
    f = pd.concat(out, ignore_index=True)
    f["date_debut"] = pd.to_datetime(f["date_debut"], errors="coerce")
    f["facturation_codepostal"] = f["facturation_codepostal"].astype(str)
    f["categorie_age"] = f["categorie_age"].astype(str).str.lower().str.replace("etudiant", "étudiant")
    f["dept"] = f["facturation_codepostal"].astype(str).str.extract(r"^\s*(\d{2})")[0]
    f.loc[f["facturation_pays"].fillna("FR") != "FR", "dept"] = "étranger"
    f.to_parquet(p, index=False)
    return f


# --------------------------------------------------------------------------- calendrier scolaire, météo

def school_holidays(zone: str = C.ZONE_SCOLAIRE) -> list[tuple[date, date]]:
    """Périodes de vacances scolaires (open data Éducation nationale), en cache."""
    p = C.ARTIFACTS / f"vacances_{zone.replace(' ', '_')}.json"
    if p.exists():
        rows = json.loads(p.read_text())
    else:
        rows, offset = [], 0
        try:
            while True:
                r = requests.get(C.EDUCATION_CALENDAR, params={"where": f'zones="{zone}"', "limit": 100, "offset": offset}, timeout=30)
                r.raise_for_status()
                res = r.json()["results"]
                rows += [{"start": x["start_date"][:10], "end": x["end_date"][:10]} for x in res]
                if len(res) < 100:
                    break
                offset += 100
            p.write_text(json.dumps(rows))
        except Exception:
            return []
    return sorted({(date.fromisoformat(r["start"]), date.fromisoformat(r["end"])) for r in rows})


WEATHER_VARS = "precipitation_sum,temperature_2m_max,temperature_2m_min,snowfall_sum,sunshine_duration"


def _weather_frame(js: dict) -> pd.DataFrame:
    d = pd.DataFrame(js["daily"])
    d = d.rename(columns={"time": "date", "precipitation_sum": "rr", "temperature_2m_max": "tx", "temperature_2m_min": "tn", "snowfall_sum": "snow", "sunshine_duration": "sun"})
    d["date"] = pd.to_datetime(d["date"])
    d["sun"] = d["sun"] / 3600.0
    return d


def _get_with_retry(url: str, params: dict, timeout: int) -> requests.Response:
    for attempt in range(1, 6):
        response = requests.get(url, params=params, timeout=timeout)
        if response.status_code != 429 and not 500 <= response.status_code < 600:
            response.raise_for_status()
            return response
        if attempt == 5:
            response.raise_for_status()
            return response
        retry_after = response.headers.get("Retry-After")
        try:
            delay = float(retry_after) if retry_after is not None else 30 * attempt
        except (TypeError, ValueError):
            delay = 30 * attempt
        time.sleep(delay)
    raise RuntimeError("Open-Meteo retry loop exited unexpectedly")


def weather_history(lat: float, lon: float, start: date, end: date, key: str) -> pd.DataFrame:
    """Météo journalière observée (réanalyse Open-Meteo, mondiale, sans clé), en cache par site."""
    wdir = C.ARTIFACTS / "weather"
    wdir.mkdir(exist_ok=True)
    p = wdir / f"{key}.parquet"
    cached = None
    fetch_start = start
    if p.exists():
        cached = pd.read_parquet(p)
        cached["date"] = pd.to_datetime(cached["date"])
        if not cached.empty and cached["date"].min().date() <= start:
            cached_end = cached["date"].max().date()
            if cached_end >= end - timedelta(days=7):
                return cached
            fetch_start = cached_end + timedelta(days=1)
        else:
            cached = None
    params = {"latitude": lat, "longitude": lon, "start_date": fetch_start.isoformat(), "end_date": end.isoformat(), "daily": WEATHER_VARS, "timezone": C.TZ}
    r = _get_with_retry(C.OPEN_METEO_ARCHIVE, params=params, timeout=60)
    d = _weather_frame(r.json())
    if cached is not None:
        d = pd.concat([cached, d], ignore_index=True).drop_duplicates("date", keep="last").sort_values("date").reset_index(drop=True)
    d.to_parquet(p, index=False)
    return d


def elevation(points: list[tuple[float, float]]) -> list[float | None]:
    """Altitudes Open-Meteo mises en cache par coordonnées arrondies à quatre décimales."""
    path = C.ARTIFACTS / "elevation.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        cache = json.loads(path.read_text())
        if not isinstance(cache, dict):
            cache = {}
    except (OSError, json.JSONDecodeError):
        cache = {}

    keys: list[str | None] = []
    coordinates: dict[str, tuple[float, float]] = {}
    for lat, lon in points:
        try:
            latitude, longitude = float(lat), float(lon)
            if not math.isfinite(latitude) or not math.isfinite(longitude):
                keys.append(None)
                continue
        except (TypeError, ValueError):
            keys.append(None)
            continue
        key = f"{latitude:.4f},{longitude:.4f}"
        keys.append(key)
        coordinates.setdefault(key, (latitude, longitude))

    missing = [key for key in coordinates if key not in cache]
    changed = False
    for offset in range(0, len(missing), 100):
        batch = missing[offset:offset + 100]
        params = {
            "latitude": ",".join(f"{coordinates[key][0]:.6f}" for key in batch),
            "longitude": ",".join(f"{coordinates[key][1]:.6f}" for key in batch),
        }
        try:
            response = _get_with_retry(C.OPEN_METEO_ELEVATION, params=params, timeout=30)
            values = response.json()["elevation"]
            if len(values) != len(batch):
                continue
        except Exception:
            continue
        for key, value in zip(batch, values):
            try:
                number = float(value) if value is not None else None
            except (TypeError, ValueError):
                number = None
            if number is not None and not math.isfinite(number):
                number = None
            cache[key] = number
            changed = True
    if changed:
        path.write_text(json.dumps(cache, ensure_ascii=False, indent=2))
    return [cache.get(key) if key is not None else None for key in keys]


_FORECAST_CACHE: dict[tuple, tuple[float, pd.DataFrame]] = {}


def weather_forecast(lat: float, lon: float, days: int = 7) -> pd.DataFrame:
    """Prévision météo Open-Meteo, mise en cache 1 h par maille de 0,1 degré (une dizaine de km)."""
    import time

    key = (round(lat, 1), round(lon, 1), min(days, 16))
    hit = _FORECAST_CACHE.get(key)
    if hit and time.time() - hit[0] < 3600:
        return hit[1].copy()
    d = _fetch_forecast(lat, lon, days)
    _FORECAST_CACHE[key] = (time.time(), d)
    return d.copy()


def _fetch_forecast(lat: float, lon: float, days: int) -> pd.DataFrame:
    r = requests.get(C.OPEN_METEO_FORECAST, params={"latitude": lat, "longitude": lon, "daily": WEATHER_VARS, "timezone": C.TZ, "past_days": 7, "forecast_days": min(days + 1, 16)}, timeout=30)
    r.raise_for_status()
    return _weather_frame(r.json())
