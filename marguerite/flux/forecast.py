"""M3 Prévision : un seul modèle LightGBM multi-sites, horizon J+1 à J+7.

Cible : log1p(passages journaliers). Variables : site, calendrier (jour de semaine,
mois, fériés, vacances zone A, ponts), météo du jour (réanalyse pour l'historique,
prévision Open-Meteo pour l'avenir) et retards >= 7 jours. Évaluation sur la
dernière année contre une référence naïve (moyenne des 4 derniers mêmes jours).
"""
from __future__ import annotations

import json
import sys
from datetime import date, timedelta

import lightgbm as lgb
import numpy as np
import pandas as pd

from . import config as C
from .data import load_ens_daily, weather_forecast, weather_history
from .features import add_lags, calendar_features, seasonal_baseline

MODEL_PATH = C.ARTIFACTS / "forecast_lgbm.txt"
METRICS_PATH = C.ARTIFACTS / "forecast_metrics.json"
WEATHER_COLS = ["rr", "tx", "tn", "snow", "sun"]
MIN_DAYS = 365  # un site doit avoir au moins un an de données pour être modélisé


def _weather_all(sites: pd.DataFrame, start: date, end: date) -> pd.DataFrame:
    frames = []
    errors = []
    for r in sites.itertuples():
        try:
            w = weather_history(r.lat, r.lon, start, end, key=f"site_{r.site_id}")
        except Exception as exc:
            errors.append(exc)
            continue
        w["site_id"] = r.site_id
        frames.append(w)
    if errors:
        print(f"[avertissement] météo indisponible pour {len(errors)}/{len(sites)} sites : {errors[0]}", file=sys.stderr)
    return pd.concat(frames, ignore_index=True)


def build_training_frame(start_year: int = 2015) -> tuple[pd.DataFrame, pd.DataFrame]:
    daily, sites = load_ens_daily()
    daily = daily[daily["date"].dt.year >= start_year]
    ok = sites[sites["n_days"] >= MIN_DAYS]["site_id"]
    daily = daily[daily["site_id"].isin(ok)]
    full = add_lags(daily)
    full = full[full["count"].notna()]
    cal = calendar_features(full["date"])
    full = pd.concat([full.reset_index(drop=True), cal], axis=1)
    sites_ok = sites[sites["site_id"].isin(ok)]
    w = _weather_all(sites_ok, full["date"].min().date(), min(full["date"].max().date(), date.today() - timedelta(days=3)))
    full = full.merge(w, on=["site_id", "date"], how="left")
    full["baseline"] = seasonal_baseline(full)
    return full, sites_ok


FEATURES = ["site_id", "dow", "month", "doy", "weekend", "ferie", "vacances", "pont", "off",
            "lag_7", "lag_14", "lag_21", "lag_28", "lag_364", "roll_28", "roll_dow_4"] + WEATHER_COLS


def _fit(train: pd.DataFrame) -> lgb.Booster:
    X = train[FEATURES].copy()
    X["site_id"] = X["site_id"].astype("category")
    y = np.log1p(train["count"])
    params = dict(objective="regression_l1", learning_rate=0.05, num_leaves=63, min_data_in_leaf=40,
                  feature_fraction=0.8, bagging_fraction=0.8, bagging_freq=1, lambda_l2=1.0, verbose=-1, seed=42)
    return lgb.train(params, lgb.Dataset(X, y, categorical_feature=["site_id"]), num_boost_round=600)


def _predict(model: lgb.Booster, X: pd.DataFrame, cats) -> np.ndarray:
    X = X[FEATURES].copy()
    X["site_id"] = pd.Categorical(X["site_id"], categories=cats)
    return np.expm1(model.predict(X)).clip(min=0)


def train_and_evaluate() -> dict:
    full, sites = build_training_frame()
    cutoff = full["date"].max() - pd.Timedelta(days=365)
    train, test = full[full["date"] <= cutoff], full[(full["date"] > cutoff) & full["baseline"].notna()]
    cats = sorted(full["site_id"].unique())
    model = _fit(train)
    pred = _predict(model, test, cats)
    err = np.abs(pred - test["count"])
    err_b = np.abs(test["baseline"] - test["count"])
    per_site = (
        test.assign(err=err.values, err_b=err_b.values)
        .groupby("site_id").agg(mae=("err", "mean"), mae_baseline=("err_b", "mean"), mean=("count", "mean"), n=("count", "size"))
        .merge(sites[["site_id", "site_name"]], on="site_id")
    )
    per_site["gain_pct"] = (1 - per_site["mae"] / per_site["mae_baseline"]) * 100
    metrics = {
        "test_period": [str(cutoff.date()), str(full["date"].max().date())],
        "n_sites": int(len(cats)),
        "n_train": int(len(train)),
        "n_test": int(len(test)),
        "mae": float(err.mean()),
        "mae_baseline": float(err_b.mean()),
        "gain_pct": float((1 - err.mean() / err_b.mean()) * 100),
        "wape_pct": float(err.sum() / test["count"].sum() * 100),
        "wape_baseline_pct": float(err_b.sum() / test["count"].sum() * 100),
        "per_site": per_site.round(1).sort_values("mean", ascending=False).to_dict(orient="records"),
    }
    # réapprentissage sur tout l'historique pour la mise en production
    model = _fit(full)
    model.save_model(str(MODEL_PATH))
    metrics["site_categories"] = [int(c) for c in cats]
    imp = dict(zip(FEATURES, model.feature_importance("gain")))
    tot = sum(imp.values()) or 1
    metrics["feature_importance"] = {k: round(v / tot * 100, 1) for k, v in sorted(imp.items(), key=lambda kv: -kv[1])}
    METRICS_PATH.write_text(json.dumps(metrics, ensure_ascii=False, indent=1, default=str))
    return metrics


class Forecaster:
    """Prévision à J+1..J+7 pour un site, à partir du modèle sérialisé et de l'historique récent."""

    def __init__(self):
        self.model = lgb.Booster(model_file=str(MODEL_PATH))
        self.metrics = json.loads(METRICS_PATH.read_text())
        self.cats = self.metrics["site_categories"]
        self.daily, self.sites = load_ens_daily()

    def available(self) -> bool:
        return MODEL_PATH.exists()

    def predict(self, site_id: int, start: date | None = None, days: int = 7) -> pd.DataFrame:
        if site_id not in self.cats:
            raise KeyError(f"site {site_id} non modélisé")
        site = self.sites[self.sites["site_id"] == site_id].iloc[0]
        hist = self.daily[self.daily["site_id"] == site_id][["site_id", "date", "count"]]
        start = start or date.today() + timedelta(days=1)
        horizon = pd.date_range(start, periods=days, freq="D")
        future = pd.DataFrame({"site_id": site_id, "date": horizon, "count": np.nan})
        # si l'historique s'arrête avant la date demandée, les retards sont pris sur la dernière année connue
        gap = (horizon[0] - hist["date"].max()).days
        shift_years = 0 if gap <= 7 else int(np.ceil((gap - 7) / 364))
        if shift_years:
            hist = hist.assign(date=hist["date"] + pd.Timedelta(days=364 * shift_years))
        # l'horizon demandé est toujours prédit, même si des relevés existent déjà (rejeu sur le passé)
        hist = hist[hist["date"] < horizon[0]]
        frame = add_lags(pd.concat([hist, future], ignore_index=True))
        frame = frame[frame["date"].isin(horizon)].reset_index(drop=True)
        frame = pd.concat([frame, calendar_features(frame["date"])], axis=1)
        try:
            if horizon[-1].date() < date.today() - timedelta(days=5):
                w = weather_history(site.lat, site.lon, horizon[0].date(), horizon[-1].date(), key=f"range_{site_id}_{horizon[0].date()}")
                weather_source = "open-meteo archive"
            else:
                w = weather_forecast(site.lat, site.lon, days=max(1, (horizon[-1].date() - date.today()).days + 1))
                weather_source = "open-meteo forecast"
            frame = frame.merge(w, on="date", how="left")
        except Exception:
            weather_source = "indisponible"
        for c in WEATHER_COLS:
            if c not in frame:
                frame[c] = np.nan
        frame["pred"] = _predict(self.model, frame, self.cats)
        frame["baseline"] = seasonal_baseline(frame)
        frame["weather_source"] = weather_source
        return frame[["date", "pred", "baseline", "dow", "weekend", "ferie", "vacances", "rr", "tx", "tn", "snow"]]
