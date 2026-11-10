"""Prévision de fréquentation d'un POI par forme de série temporelle."""
from __future__ import annotations

import copy
import json
import re
import sys
import time
import unicodedata
from datetime import date, timedelta
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

from . import config as C
from .data import (
    elevation,
    haversine_km,
    load_ens_daily,
    weather_forecast,
    weather_history,
)
from .features import calendar_features
from .reroute import counter_status

MODEL_PATH = C.ARTIFACTS / "forme_lgbm.txt"
META_PATH = C.ARTIFACTS / "frequentation_meta.json"
SOURCE_CATEGORIES = ["ens_pieton", "route", "ski_forfaits", "ski_rando", "velo"]
CAL = ["dow", "month", "doy", "weekend", "ferie", "vacances", "pont", "off"]
WX = ["rr", "tx", "tn", "snow", "sun"]
SITE = ["lat", "lon", "alt", "d_grenoble", "d_lyon", "src"]
FEATURES = CAL + WX + SITE
P = {
    "objective": "regression_l1",
    "learning_rate": 0.05,
    "num_leaves": 31,
    "min_data_in_leaf": 50,
    "feature_fraction": 0.8,
    "bagging_fraction": 0.8,
    "bagging_freq": 1,
    "verbose": -1,
    "seed": 42,
}
SEUILS = {
    "provisoires": True,
    "calibre": {
        "trop_de_monde": 0.8,
        "peu_de_monde": 0.3,
        "sinon": "fréquentation normale",
    },
    "relatif": {
        "plus_que_d_habitude": 1.5,
        "moins_de_d_habitude": 1 / 1.5,
        "sinon": "comme d'habitude",
    },
}
VALIDATION = {
    "protocole": "63 séries (42 ENS, 16 routes SMMAG, 2 forfaits ski, Pipay, 2 vélo) ; chaque lieu et ses voisins à moins de 5 km retirés de l'entraînement",
    "spearman_median": 0.59,
    "acc3_median": 0.54,
    "facteur_erreur_typique": 1.91,
    "reference_calendrier_moyen": {"spearman_median": 0.43, "acc3_median": 0.40},
    "spearman_par_source": {
        "ens_pieton": 0.58,
        "route": 0.58,
        "ski_forfaits": 0.39,
        "ski_rando": 0.29,
        "velo": 0.63,
    },
}

SMMAG = {
    "D211_SARENNES": (45.07, 6.05),
    "D213_DEUX_ALPES": (45.02, 6.10),
    "D1091_B_OISANS_NORD": (45.07, 6.02),
    "Livet_Gavet": (45.11, 5.93),
    "D526_EAU_D_OLLE": (45.20, 6.05),
    "D111_SEIGLIERES": (45.14, 5.86),
    "D111_BELMONT": (45.13, 5.84),
    "D524_URIAGE": (45.14, 5.83),
    "D106_CROIX_PERRIN": (45.13, 5.58),
    "D106_ST_NIZIER": (45.17, 5.63),
    "Lans en Vercors RDT": (45.13, 5.59),
    "Rencurel": (45.10, 5.46),
    "D520_PLACETTE": (45.31, 5.71),
    "Clelles": (44.83, 5.62),
    "Monestier": (44.92, 5.64),
    "Croix Haute": (44.68, 5.70),
}
ROUTE_ZONES = {
    "D211_SARENNES": ("Huez", "Alpe d'Huez", "La Garde-en-Oisans", "Villard-Reculas"),
    "D213_DEUX_ALPES": ("Les Deux Alpes", "les 2 alpes"),
    "D111_BELMONT": ("Chamrousse",),
    "D106_ST_NIZIER": (
        "Saint-Nizier-du-Moucherotte",
        "Lans-en-Vercors",
        "Villard-de-Lans",
        "Corrençon-en-Vercors",
    ),
    "D106_CROIX_PERRIN": ("Autrans", "Autrans-Méaudre en Vercors"),
    "Rencurel": ("Rencurel",),
    "D526_EAU_D_OLLE": ("Vaujany", "Oz-en-Oisans", "Allemond"),
}
GRENOBLE = (45.188, 5.724)
LYON = (45.764, 4.836)
_VUE_CACHE_SECONDS = 3600


def _warning(path: Path, label: str = "fichier de fréquentation") -> None:
    print(f"[avertissement] {label} absent : {path}", file=sys.stderr)


def _add_series(
    series: list[pd.DataFrame],
    metadata: list[dict],
    sid: str,
    source: str,
    lat: float,
    lon: float,
    frame: pd.DataFrame,
    name: str,
    **extra: object,
) -> None:
    values = frame[["date", "count"]].dropna().copy()
    if values.empty:
        return
    values["date"] = pd.to_datetime(values["date"]).dt.normalize()
    values = values.groupby("date", as_index=False)["count"].sum()
    values["sid"] = sid
    values["source"] = source
    series.append(values)
    metadata.append({
        "sid": sid,
        "source": source,
        "lat": float(lat),
        "lon": float(lon),
        "name": str(name),
        **extra,
    })


def _load_series() -> tuple[pd.DataFrame, pd.DataFrame]:
    series: list[pd.DataFrame] = []
    metadata: list[dict] = []
    today = date.today()

    ens, sites = load_ens_daily()
    ens = ens[ens["date"].dt.year >= 2015]
    for site in sites.itertuples():
        daily = ens[ens["site_id"] == site.site_id]
        if len(daily) >= 365:
            _add_series(
                series,
                metadata,
                f"ens_{site.site_id}",
                "ens_pieton",
                site.lat,
                site.lon,
                daily,
                site.site_name,
                site_id=int(site.site_id),
            )

    smmag_path = C.DATA_DIR / "Fréquentation/Comptages routiers SMMAG.xlsx"
    if smmag_path.exists():
        smmag = pd.read_excel(smmag_path)
        smmag = smmag[smmag["station"].isin(SMMAG)]
        nsens = smmag.groupby("station")["sens"].nunique()
        valid = smmag[(smmag["Valide"] == True) & (smmag["total_jour"] > 0)]
        routes = (
            valid.groupby(["station", "date"])
            .agg(count=("total_jour", "sum"), n=("sens", "nunique"))
            .reset_index()
        )
        routes = routes[routes["n"] == routes["station"].map(nsens)]
        for station, (lat, lon) in SMMAG.items():
            daily = routes[routes["station"] == station]
            if len(daily) >= 200:
                _add_series(
                    series,
                    metadata,
                    f"route_{station}",
                    "route",
                    lat,
                    lon,
                    daily,
                    station,
                    station=station,
                )
    else:
        _warning(smmag_path)

    forfaits_path = C.DATA_DIR / C.F_FORFAITS
    if forfaits_path.exists():
        sheets = pd.read_excel(forfaits_path, sheet_name=None)
        for key, (lat, lon) in {
            "7 LAUX": (45.26, 6.03),
            "COLLET": (45.39, 6.13),
        }.items():
            matched = [frame for sheet, frame in sheets.items() if key in sheet]
            if not matched:
                _warning(forfaits_path, f"feuilles de forfaits {key}")
                continue
            frame = pd.concat(matched)
            frame = (
                frame[frame["type_produit"] == "Forfait"]
                .groupby("date_debut")
                .size()
                .rename("count")
                .reset_index()
                .rename(columns={"date_debut": "date"})
            )
            _add_series(
                series,
                metadata,
                f"ski_{key}",
                "ski_forfaits",
                lat,
                lon,
                frame,
                f"Forfaits {key}",
            )
    else:
        _warning(forfaits_path)

    pipay_path = C.DATA_DIR / "Fréquentation/Frequentation Pipay Ski de Rando.xlsx"
    if pipay_path.exists():
        pipay = pd.read_excel(pipay_path, sheet_name=0, header=None).iloc[3:, :2]
        pipay.columns = ["date", "count"]
        pipay = pipay[pd.to_datetime(pipay["date"], errors="coerce").notna()]
        pipay["count"] = pd.to_numeric(pipay["count"])
        _add_series(
            series,
            metadata,
            "rando_pipay",
            "ski_rando",
            45.28,
            6.04,
            pipay,
            "Pipay ski de rando",
        )
    else:
        _warning(pipay_path)

    velo_dir = C.DATA_DIR / "Fréquentation/Comptages Velo Isere/Ecocompteurs"
    for key, (lat, lon) in {
        "ViaRhona_Chavanoz": (45.773, 5.175),
        "BelleVia_Pontcharra": (45.436, 6.017),
    }.items():
        files = sorted(velo_dir.glob(f"Comptages_{key}_*.xlsx"))
        if not files:
            _warning(velo_dir / f"Comptages_{key}_*.xlsx", "fichiers de comptage vélo")
            continue
        frames = []
        for path in files:
            frame = pd.read_excel(path, header=None).iloc[3:, :2]
            frame.columns = ["date", "count"]
            frame = frame[pd.to_datetime(frame["date"], errors="coerce").notna()]
            frame["count"] = pd.to_numeric(frame["count"])
            frames.append(frame)
        daily = pd.concat(frames)
        daily["date"] = pd.to_datetime(daily["date"]).dt.normalize()
        daily = daily.groupby("date", as_index=False)["count"].sum()
        daily = daily[daily["count"] > 0]
        _add_series(series, metadata, f"velo_{key}", "velo", lat, lon, daily, key)

    if not series:
        raise ValueError("Aucune série de fréquentation disponible.")
    data = pd.concat(series, ignore_index=True)
    data = data[data["date"].dt.date <= today]
    metadata_frame = pd.DataFrame(metadata)
    metadata_frame = metadata_frame[metadata_frame["sid"].isin(data["sid"].unique())].reset_index(drop=True)
    return data, metadata_frame


def _finite(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if np.isfinite(number) else None


def _reference_stats(frame: pd.DataFrame, source: str) -> dict:
    values = frame.copy()
    values["year"] = values["date"].dt.year
    if source == "route":
        values = values[values["year"] == 2025]
    years_for_median = sorted(values["year"].unique())[-3:]
    median = _finite(values.loc[values["year"].isin(years_for_median), "count"].median()) if years_for_median else None

    annual_high = {}
    for year, group in values.groupby("year"):
        if len(group) >= 120:
            annual_high[int(year)] = float(group.nlargest(10, "count")["count"].mean())
    high_years = sorted(annual_high)[-3:]
    reference = _finite(np.mean([annual_high[year] for year in high_years])) if high_years else None
    return {
        "mediane": median,
        "reference_haute": reference,
        "annees": high_years,
        "annees_mediane": [int(year) for year in years_for_median],
    }


def _source_counts(data: pd.DataFrame) -> dict[str, int]:
    counts = {source: 0 for source in SOURCE_CATEGORIES}
    for source, count in data[["sid", "source"]].drop_duplicates()["source"].value_counts().items():
        counts[str(source)] = int(count)
    return counts


def _metadata(
    data: pd.DataFrame,
    sites: pd.DataFrame,
    reference_data: pd.DataFrame,
    reference_sites: pd.DataFrame,
) -> dict:
    ens = {}
    for row in reference_sites[reference_sites["source"] == "ens_pieton"].itertuples():
        stats = _reference_stats(reference_data[reference_data["sid"] == row.sid], row.source)
        site_id = int(row.site_id)
        ens[str(site_id)] = {
            "nom": row.name,
            "lat": float(row.lat),
            "lon": float(row.lon),
            **stats,
        }
    routes = {}
    if "station" in reference_sites:
        for station, communes in ROUTE_ZONES.items():
            selected = reference_sites[(reference_sites["source"] == "route") & (reference_sites["station"] == station)]
            if selected.empty:
                continue
            row = selected.iloc[0]
            stats = _reference_stats(reference_data[reference_data["sid"] == row["sid"]], "route")
            routes[station] = {
                "station": station,
                "lat": float(row["lat"]),
                "lon": float(row["lon"]),
                "communes": list(communes),
                **stats,
            }
    return {
        "series_par_source": _source_counts(reference_data),
        "series_entrainees_par_source": _source_counts(data),
        "compteurs_ens": ens,
        "routes_zone": routes,
    }


def build() -> dict:
    """Construit le modèle M2 sur toutes les séries disponibles, sans validation croisée."""
    reference_data, reference_sites = _load_series()
    data, sites = reference_data.copy(), reference_sites.copy()
    medians = data.groupby("sid")["count"].median()
    usable = medians[medians > 0].index
    data = data[data["sid"].isin(usable)].copy()
    sites = sites[sites["sid"].isin(usable)].copy()
    if data.empty:
        raise ValueError("Aucune série de médiane positive disponible.")

    data["y"] = np.log1p(data["count"]) - np.log1p(data["sid"].map(medians))
    data["weight"] = 1.0 / data.groupby("sid")["y"].transform("size")

    sites["alt"] = pd.to_numeric(elevation(list(zip(sites["lat"], sites["lon"]))), errors="coerce")
    sites["d_grenoble"] = haversine_km(sites["lat"].to_numpy(), sites["lon"].to_numpy(), *GRENOBLE)
    sites["d_lyon"] = haversine_km(sites["lat"].to_numpy(), sites["lon"].to_numpy(), *LYON)

    weather = []
    for site in sites.itertuples():
        daily = data[data["sid"] == site.sid]
        is_ens = site.source == "ens_pieton"
        key = f"site_{int(site.site_id)}" if is_ens else re.sub(r"\W", "_", f"exp_{site.sid}")
        try:
            frame = weather_history(
                site.lat,
                site.lon,
                daily["date"].min().date(),
                daily["date"].max().date(),
                key=key,
            )
        except Exception as error:
            print(f"[avertissement] météo absente pour {site.sid} : {error}", file=sys.stderr)
            frame = pd.DataFrame(columns=["date", *WX])
        frame = frame[["date", *[column for column in WX if column in frame]]].copy()
        for column in WX:
            if column not in frame:
                frame[column] = np.nan
        frame["sid"] = site.sid
        weather.append(frame)
    wx = pd.concat(weather, ignore_index=True)

    data = data.merge(sites, on=["sid", "source"], how="left")
    data = data.merge(wx, on=["sid", "date"], how="left")
    calendar = calendar_features(data["date"]).drop(columns=["year"])
    data = pd.concat([data.reset_index(drop=True), calendar.reset_index(drop=True)], axis=1)
    data["src"] = pd.Categorical(data["source"], categories=SOURCE_CATEGORIES)
    for column in FEATURES:
        if column not in data:
            data[column] = np.nan

    model = lgb.train(
        P,
        lgb.Dataset(
            data[FEATURES],
            label=data["y"],
            weight=data["weight"],
            categorical_feature=["src"],
        ),
        num_boost_round=400,
    )
    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    model.save_model(str(MODEL_PATH))
    meta = _metadata(data, sites, reference_data, reference_sites)
    META_PATH.write_text(json.dumps(meta, ensure_ascii=False, indent=2, allow_nan=False))
    return meta


def _normalize_name(value: object) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or "").casefold())
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", normalized).strip()


def _number(value: object) -> float | None:
    if value is None or pd.isna(value):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if np.isfinite(number) else None


def _rounded(value: object, digits: int = 2) -> float | None:
    number = _number(value)
    return round(number, digits) if number is not None else None


def _weather_value(value: object) -> float | None:
    return _rounded(value, 1)


class FrequentationModel:
    def __init__(self, forecaster=None, ens_sites: pd.DataFrame | None = None):
        self.model = lgb.Booster(model_file=str(MODEL_PATH))
        self.meta = json.loads(META_PATH.read_text())
        self.forecaster = forecaster
        self.ens_sites = ens_sites if ens_sites is not None else pd.DataFrame()
        self._cache: dict[tuple[str, date, int], tuple[float, dict]] = {}

    def _ens_candidate(self, poi: dict, day: date) -> tuple[dict | None, str | None]:
        if self.forecaster is None or self.ens_sites.empty:
            return None, None
        lat, lon = _number(poi.get("lat")), _number(poi.get("lon"))
        if lat is None or lon is None:
            return None, None
        candidates = []
        cats = {int(site_id) for site_id in self.forecaster.cats}
        references = self.meta.get("compteurs_ens", {})
        for site in self.ens_sites.itertuples():
            site_id = int(site.site_id)
            reference = references.get(str(site_id))
            if site_id not in cats or not reference or reference.get("reference_haute") is None:
                continue
            if not reference.get("mediane"):
                continue
            distance = float(haversine_km(lat, lon, site.lat, site.lon))
            if distance <= 0.5:
                candidates.append((distance, site, reference))
        if not candidates:
            return None, None
        distance, site, reference = min(candidates, key=lambda item: item[0])
        status = counter_status(self.ens_sites, int(site.site_id), day)
        if status == "en panne":
            warning = f"Le compteur ENS {site.site_name} est en panne ; le calibrage par lieu n'est pas utilisé."
            return None, warning
        return {
            "site": site,
            "reference": reference,
            "distance_km": distance,
            "statut": status,
        }, None

    def _route_candidate(self, poi: dict) -> dict | None:
        lat, lon = _number(poi.get("lat")), _number(poi.get("lon"))
        if lat is None or lon is None:
            return None
        commune = _normalize_name(poi.get("commune"))
        routes = self.meta.get("routes_zone", {})
        candidates = []
        for station, communes in ROUTE_ZONES.items():
            if commune not in {_normalize_name(name) for name in communes}:
                continue
            route = routes.get(station)
            if not route or route.get("reference_haute") is None or not route.get("mediane"):
                continue
            distance = float(haversine_km(lat, lon, route["lat"], route["lon"]))
            if distance <= 25:
                candidates.append((distance, route))
        if not candidates:
            return None
        distance, route = min(candidates, key=lambda item: item[0])
        return {**route, "distance_km": distance}

    def source(self, poi: dict, day: date) -> dict | None:
        ens, _ = self._ens_candidate(poi, day)
        if ens:
            site = ens["site"]
            return {
                "type": "ens",
                "site_id": int(site.site_id),
                "nom": str(site.site_name),
                "distance_km": round(float(ens["distance_km"]), 2),
            }
        route = self._route_candidate(poi)
        if route:
            return {
                "type": "route",
                "station": route["station"],
                "distance_km": round(float(route["distance_km"]), 2),
            }
        return None

    def _weather(self, poi_id: str, lat: float | None, lon: float | None, start: date, days: int) -> tuple[pd.DataFrame, list[str]]:
        dates = pd.date_range(start, periods=days, freq="D")
        weather = pd.DataFrame({"date": dates, **{column: np.nan for column in WX}})
        warnings = []
        if lat is None or lon is None:
            warnings.append("Coordonnées absentes : météo indisponible.")
            return weather, warnings
        try:
            if dates[-1].date() < date.today() - timedelta(days=5):
                key = re.sub(r"\W", "_", f"poi_{poi_id}_{start.isoformat()}")
                fetched = weather_history(lat, lon, dates[0].date(), dates[-1].date(), key=key)
            else:
                last_available = date.today() + timedelta(days=15)
                forecast_dates = dates[dates.date <= last_available]
                if len(forecast_dates):
                    forecast_days = max(1, (forecast_dates[-1].date() - date.today()).days + 1)
                    fetched = weather_forecast(lat, lon, days=forecast_days)
                else:
                    fetched = pd.DataFrame(columns=["date", *WX])
                    warnings.append("Météo indisponible au-delà de 16 jours de prévision.")
                if dates[-1].date() > last_available:
                    warnings.append("Météo indisponible au-delà de 16 jours de prévision.")
        except Exception as error:
            warnings.append(f"Météo indisponible : {error}")
            return weather, warnings
        fetched = fetched.copy()
        fetched["date"] = pd.to_datetime(fetched["date"])
        available = [column for column in WX if column in fetched]
        merged = (
            weather.drop(columns=WX)
            .merge(fetched[["date", *available]], on="date", how="left")
            .reindex(columns=["date", *WX])
        )
        missing = merged[WX].isna().all(axis=1).sum()
        if missing:
            warnings.append(f"Météo indisponible pour {int(missing)} jour(s) de la période.")
        return merged, warnings

    def _form_predictions(
        self,
        poi: dict,
        source: str,
        lat: float,
        lon: float,
        start: date,
        days: int,
    ) -> tuple[pd.DataFrame, list[str]]:
        lat_value, lon_value = _number(lat), _number(lon)
        weather, warnings = self._weather(str(poi.get("poi_id", "")), lat_value, lon_value, start, days)
        dates = weather["date"]
        frame = calendar_features(dates).drop(columns=["year"])
        frame = pd.concat([frame.reset_index(drop=True), weather[WX].reset_index(drop=True)], axis=1)
        frame["date"] = dates.to_numpy()
        altitude = _number(elevation([(lat_value, lon_value)])[0])
        features = {
            "lat": lat_value,
            "lon": lon_value,
            "alt": altitude,
            "d_grenoble": haversine_km(lat_value, lon_value, *GRENOBLE) if lat_value is not None and lon_value is not None else None,
            "d_lyon": haversine_km(lat_value, lon_value, *LYON) if lat_value is not None and lon_value is not None else None,
        }
        for column, value in features.items():
            number = _number(value)
            frame[column] = np.full(len(frame), np.nan if number is None else number, dtype=float)
        frame["src"] = pd.Categorical([source] * len(frame), categories=SOURCE_CATEGORIES)
        ratios = np.exp(np.clip(self.model.predict(frame[FEATURES]), -20, 20))
        frame["ratio"] = ratios
        return frame, warnings

    def _cached(self, key: tuple[str, date, int]) -> dict | None:
        hit = self._cache.get(key)
        if hit and time.monotonic() - hit[0] < _VUE_CACHE_SECONDS:
            return copy.deepcopy(hit[1])
        if hit:
            self._cache.pop(key, None)
        return None

    def predict_poi(self, poi: dict, start: date, days: int = 7) -> dict:
        poi_id = str(poi.get("poi_id", ""))
        key = (poi_id, start, days)
        cached = self._cached(key)
        if cached is not None:
            return cached
        result = self._predict_poi(poi, start, days)
        self._cache[key] = (time.monotonic(), copy.deepcopy(result))
        return result

    def _predict_poi(self, poi: dict, start: date, days: int) -> dict:
        lat, lon = _number(poi.get("lat")), _number(poi.get("lon"))
        categories = set(poi.get("categories") or [])
        tags = poi.get("tags") or []
        tags_text = " ".join(map(str, tags)) if isinstance(tags, (list, tuple, set)) else str(tags)
        warnings: list[str] = []

        ens, ens_warning = self._ens_candidate(poi, start)
        if ens_warning:
            warnings.append(ens_warning)
        if ens:
            site = ens["site"]
            reference = ens["reference"]
            try:
                forecast = self.forecaster.predict(int(site.site_id), start=start, days=days)
            except Exception as error:
                warnings.append(f"Prévision du compteur ENS indisponible : {error}")
            else:
                if forecast[["rr", "tx", "tn", "snow"]].isna().all(axis=1).any():
                    warnings.append("Météo indisponible pour au moins un jour de la prévision du compteur ENS.")
                if any(row.date.date() > date.today() + timedelta(days=15) for row in forecast.itertuples()):
                    warnings.append("Météo indisponible au-delà de 16 jours de prévision.")
                statuses = [
                    counter_status(self.ens_sites, int(site.site_id), row.date.date())
                    for row in forecast.itertuples()
                ]
                confidence = "moyenne" if "données anciennes" in statuses else "bonne"
                if confidence == "moyenne":
                    warnings.append("Les données du compteur ENS sont anciennes pour au moins un jour de la période.")
                unit = "passages/jour"
                high = _number(reference.get("reference_haute"))
                median = _number(reference.get("mediane"))
                jours = []
                for row in forecast.itertuples():
                    value = _number(row.pred)
                    saturation = value / high if value is not None and high else None
                    habit = value / median if value is not None and median else None
                    jours.append({
                        "date": str(row.date.date()),
                        "valeur_prevue": round(value) if value is not None else None,
                        "indice_saturation": _rounded(saturation),
                        "indice_habitude": _rounded(habit),
                        "niveau": self._level(saturation, calibrated=True),
                        "meteo": {
                            "rr": _weather_value(row.rr),
                            "tx": _weather_value(row.tx),
                            "tn": _weather_value(row.tn),
                            "snow": _weather_value(row.snow),
                        },
                    })
                return {
                    "calibrage": "calibré lieu",
                    "source": {
                        "type": "compteur ENS",
                        "site_id": int(site.site_id),
                        "nom": str(site.site_name),
                        "distance_km": round(float(ens["distance_km"]), 2),
                    },
                    "reference": self._reference(reference, unit, "Moyenne des 10 comptages journaliers les plus élevés par année, puis moyenne des trois dernières années disponibles."),
                    "habitude": {"valeur": round(median) if median is not None else None, "unite": unit},
                    "confiance": confidence,
                    "seuils": SEUILS,
                    "fiabilite": VALIDATION,
                    "avertissements": list(dict.fromkeys(warnings)),
                    "jours": jours,
                }

        route = self._route_candidate(poi)
        if route:
            source = "route"
            frame, weather_warnings = self._form_predictions(
                poi, source, route["lat"], route["lon"], start, days
            )
            warnings.extend(weather_warnings)
            median = _number(route.get("mediane"))
            high = _number(route.get("reference_haute"))
            unit = "véhicules/jour"
            warnings.append("fréquentation de la zone (véhicules sur la route d'accès), pas du lieu ; référence sur la seule année 2025")
            jours = self._form_days(frame, median, high, calibrated=True)
            return {
                "calibrage": "calibré zone",
                "source": {
                    "type": "route SMMAG",
                    "station": route["station"],
                    "communes": route["communes"],
                    "distance_km": round(float(route["distance_km"]), 2),
                },
                "reference": self._reference(route, unit, "Moyenne des 10 comptages journaliers les plus élevés en 2025."),
                "habitude": {"valeur": round(median) if median is not None else None, "unite": unit},
                "confiance": "moyenne",
                "seuils": SEUILS,
                "fiabilite": VALIDATION,
                "avertissements": list(dict.fromkeys(warnings)),
                "jours": jours,
            }

        if "ski-vtt" in categories:
            source = "ski_forfaits"
        elif re.search(r"v[ée]lo|voie verte|viarhona|bellevia|cyclo", f"{poi.get('nom', '')} {tags_text}", flags=re.I):
            source = "velo"
        else:
            source = "ens_pieton"
        frame, weather_warnings = self._form_predictions(
            poi,
            source,
            lat if lat is not None else np.nan,
            lon if lon is not None else np.nan,
            start,
            days,
        )
        warnings.extend(weather_warnings)
        warnings.append("indice relatif à l'habitude du lieu, sans valeur absolue ; on suppose le lieu ni sur- ni sous-fréquenté en temps normal")
        if source == "ski_forfaits":
            warnings.append("le ski se transfère mal : 3 séries d'entraînement au même endroit")
        if categories.intersection({"culture", "equipement"}):
            warnings.append("lieu possiblement couvert : l'effet de la météo peut être inversé, non modélisé")
        if categories.intersection({"hebergement", "commerce", "service", "prestataire"}):
            warnings.append("ce type de lieu n'est pas une destination de visite : indice peu significatif")
        confidence = (
            "moyenne"
            if source in {"ens_pieton", "velo"} and categories.intersection({"nature", "randonnee", "activite"})
            else "faible"
        )
        jours = self._form_days(frame, None, None, calibrated=False)
        return {
            "calibrage": "relatif",
            "source": {"type": "modèle de forme", "profil": source},
            "reference": None,
            "habitude": None,
            "confiance": confidence,
            "seuils": SEUILS,
            "fiabilite": VALIDATION,
            "avertissements": list(dict.fromkeys(warnings)),
            "jours": jours,
        }

    @staticmethod
    def _reference(reference: dict, unit: str, method: str) -> dict:
        return {
            "valeur": round(float(reference["reference_haute"])),
            "unite": unit,
            "methode": method,
            "annees": reference["annees"],
        }

    @staticmethod
    def _level(index: float | None, calibrated: bool) -> str:
        if index is None or not np.isfinite(index):
            return "inconnu"
        if calibrated:
            if index >= SEUILS["calibre"]["trop_de_monde"]:
                return "trop de monde"
            if index < SEUILS["calibre"]["peu_de_monde"]:
                return "peu de monde"
            return SEUILS["calibre"]["sinon"]
        if index > SEUILS["relatif"]["plus_que_d_habitude"]:
            return "plus que d'habitude"
        if index < SEUILS["relatif"]["moins_de_d_habitude"]:
            return "moins que d'habitude"
        return SEUILS["relatif"]["sinon"]

    def _form_days(self, frame: pd.DataFrame, median: float | None, high: float | None, calibrated: bool) -> list[dict]:
        days = []
        for row in frame.itertuples():
            ratio = _number(row.ratio)
            value = median * ratio if median is not None and ratio is not None else None
            saturation = value / high if value is not None and high else None
            habit = value / median if value is not None and median else ratio
            days.append({
                "date": str(row.date.date()),
                "valeur_prevue": round(value) if calibrated and value is not None else None,
                "indice_saturation": _rounded(saturation) if calibrated else None,
                "indice_habitude": _rounded(habit),
                "niveau": self._level(saturation if calibrated else habit, calibrated),
                "meteo": {
                    "rr": _weather_value(row.rr),
                    "tx": _weather_value(row.tx),
                    "tn": _weather_value(row.tn),
                    "snow": _weather_value(row.snow),
                },
            })
        return days


def compare_predictions(predictions: list[dict]) -> dict:
    """Sépare les indices calibrés et relatifs avant de recommander le lieu le moins fréquenté."""
    calibres = []
    relatifs = []
    for prediction in predictions:
        first = prediction["jours"][0] if prediction.get("jours") else {}
        item = {
            "poi_id": prediction["poi"]["poi_id"],
            "nom": prediction["poi"]["nom"],
            "calibrage": prediction["calibrage"],
            "confiance": prediction["confiance"],
            "niveau": first.get("niveau", "inconnu"),
        }
        if prediction["calibrage"] == "relatif":
            item["indice_habitude"] = first.get("indice_habitude")
            relatifs.append(item)
        else:
            item["indice_saturation"] = first.get("indice_saturation")
            calibres.append(item)
    calibres.sort(key=lambda item: (item["indice_saturation"] is None, item["indice_saturation"] or 0))
    relatifs.sort(key=lambda item: (item["indice_habitude"] is None, item["indice_habitude"] or 0))
    group = calibres or relatifs
    group_name = "calibres" if calibres else "relatifs"
    recommendation = None
    significant = False
    if group:
        first = group[0]
        significant = len(group) == 1
        if len(group) > 1:
            second_value = group[1].get("indice_saturation" if calibres else "indice_habitude")
            first_value = first.get("indice_saturation" if calibres else "indice_habitude")
            if second_value is not None and first_value is not None:
                if calibres:
                    significant = second_value - first_value >= 0.1
                elif first_value > 0:
                    significant = second_value / first_value >= VALIDATION["facteur_erreur_typique"]
                else:
                    significant = second_value > first_value
        recommendation = {
            "poi_id": first["poi_id"],
            "nom": first["nom"],
            "groupe": group_name,
            "ecart_significatif": bool(significant),
        }
    if recommendation is None:
        explanation = "Aucun indice de fréquentation n'a pu être calculé."
    else:
        error = VALIDATION["facteur_erreur_typique"]
        if len(group) == 1:
            gap = f"Un seul lieu est disponible dans le groupe retenu ; l'erreur typique reste d'un facteur {error}."
        elif calibres:
            first_value = group[0].get("indice_saturation")
            second_value = group[1].get("indice_saturation")
            delta = second_value - first_value if first_value is not None and second_value is not None else None
            if delta is None:
                gap = f"L'écart ne peut pas être calculé ; l'erreur typique est d'un facteur {error}."
            else:
                factor = (
                    float("inf") if first_value == 0 and second_value > 0
                    else second_value / first_value if first_value
                    else None
                )
                relation = (
                    "au moins égal" if factor is not None and factor >= error
                    else "inférieur" if factor is not None
                    else "impossible à comparer"
                )
                seuil = (
                    "atteint le seuil provisoire de 0,1"
                    if significant
                    else "est inférieur au seuil provisoire de 0,1"
                )
                gap = (
                    f"L'écart d'indice {seuil} ; "
                    f"le rapport entre indices est {relation} au facteur d'erreur typique {error}."
                )
        else:
            first_value = group[0].get("indice_habitude")
            second_value = group[1].get("indice_habitude")
            if first_value is None or second_value is None:
                ratio = None
            elif first_value == 0:
                ratio = float("inf") if second_value > 0 else None
            else:
                ratio = second_value / first_value
            if ratio is None:
                gap = f"Le rapport d'indices ne peut pas être calculé ; l'erreur typique est d'un facteur {error}."
            elif significant:
                gap = f"Le rapport d'indices atteint le facteur d'erreur typique {error}."
            else:
                gap = f"Le rapport d'indices est inférieur au facteur d'erreur typique {error}."
        explanation = f"Les lieux calibrés et relatifs ne se comparent pas directement. {gap}"
    return {
        "calibres": calibres,
        "relatifs": relatifs,
        "recommandation": recommendation,
        "explication": explanation,
    }
