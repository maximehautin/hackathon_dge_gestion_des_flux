#!/usr/bin/env python3
"""
Entraînement XGBoost + logging MLflow.

Lance 3 runs avec des hyperparamètres différents (définis dans config.py)
et enregistre les métriques, paramètres et modèles dans MLflow.

Usage :
    python train.py --site herretang
    python train.py --site herretang --mlflow-uri https://mon-serveur-mlflow
    python train.py --help
"""
import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import numpy as np
import pandas as pd
import mlflow
import mlflow.xgboost
import xgboost as xgb
from sklearn.metrics import mean_absolute_error, root_mean_squared_error

from config import MLFLOW as MLFLOW_CFG, FEATURES, HYPERPARAMETRES, DATA_DIR, LOG_TRANSFORM
from sites import SITES, DEFAULT_SITE
from utils import fetch_temperature_historique

log = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Entraîne les modèles XGBoost et les enregistre dans MLflow.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--site",        default=DEFAULT_SITE, choices=list(SITES.keys()))
    p.add_argument("--mlflow-uri",  default=None,
                   help="URI du serveur MLflow (priorité sur MLFLOW_TRACKING_URI)")
    p.add_argument("--verbose", "-v", action="store_true")
    return p.parse_args()


def run_training(site_cfg: dict, mlflow_uri: str) -> None:
    if site_cfg.get("journalier_csv") is None:
        raise ValueError(f"Pas de données disponibles pour le site '{site_cfg['nom']}'.")

    # Charger le CSV journalier pré-agrégé, garder uniquement les jours complets
    daily = pd.read_csv(DATA_DIR / site_cfg["journalier_csv"], sep=";", encoding="utf-8-sig")
    daily["date"] = pd.to_datetime(daily["date"])
    daily = daily[daily["jour_complet"] == 1].copy()

    # Température historique depuis Open-Meteo Archive (absente des CSV journaliers)
    data_start = daily["date"].min().strftime("%Y-%m-%d")
    data_end   = daily["date"].max().strftime("%Y-%m-%d")
    temp_df    = fetch_temperature_historique(data_start, data_end, site_cfg)
    daily      = daily.merge(temp_df, on="date", how="left")

    daily = daily.sort_values("date").reset_index(drop=True)
    daily["passages_j1"] = daily["passages_jour"].shift(1)
    daily["passages_j7"] = daily["passages_jour"].shift(7)

    # J-365 via merge par date (robuste aux jours manquants)
    lag365 = daily[["date", "passages_jour"]].copy()
    lag365["date"] = lag365["date"] + pd.Timedelta(days=365)
    lag365 = lag365.rename(columns={"passages_jour": "passages_j365"})
    daily = daily.merge(lag365, on="date", how="left")

    daily = daily.dropna(subset=["passages_j1", "passages_j7", "passages_j365", "temperature_moy"])
    if "nb_evenements_references_j" not in daily.columns:
        daily["nb_evenements_references_j"] = 0

    # 2020-2021 exclus : données COVID atypiques (confinements, réouvertures)
    train   = daily[(daily["date"].dt.year >= 2022) & (daily["date"].dt.year < 2025)].copy()
    holdout = daily[daily["date"].dt.year == 2025].copy()
    log.info("Split : %d jours train (2022–2024) | %d jours holdout (2025)", len(train), len(holdout))

    X_train   = train[FEATURES].values
    y_train   = train["passages_jour"].values
    X_holdout = holdout[FEATURES].values
    y_holdout = holdout["passages_jour"].values

    capacite = site_cfg["capacite_journaliere"]
    if capacite is None:
        capacite = int(np.percentile(y_train, 90))
        log.info("Capacité estimée automatiquement : %d passages/jour (P90 train)", capacite)
    else:
        log.info("Capacité définie dans config : %d passages/jour", capacite)

    mlflow.set_tracking_uri(mlflow_uri)
    client = mlflow.tracking.MlflowClient()
    experiment = client.get_experiment_by_name(site_cfg["mlflow_experiment"])
    if experiment is None:
        experiment_id = client.create_experiment(site_cfg["mlflow_experiment"])
    elif experiment.lifecycle_stage == "deleted":
        client.restore_experiment(experiment.experiment_id)
        experiment_id = experiment.experiment_id
    else:
        experiment_id = experiment.experiment_id
    log.info("MLflow connecté à : %s  (experiment_id=%s)", mlflow_uri, experiment_id)

    seuils = site_cfg["seuils_risque"]

    for i, params in enumerate(HYPERPARAMETRES, 1):
        log.info("[Run %d/%d] %s", i, len(HYPERPARAMETRES), params)
        with mlflow.start_run(run_name=f"xgb-run-{i}", experiment_id=experiment_id):
            mlflow.log_params(params)
            mlflow.log_param("features",             FEATURES)
            mlflow.log_param("site",                 site_cfg["nom"])
            mlflow.log_param("train_jours",          len(train))
            mlflow.log_param("holdout_jours",        len(holdout))
            mlflow.log_param("capacite_journaliere", capacite)
            mlflow.log_param("seuil_modere",         seuils["modere"])
            mlflow.log_param("seuil_eleve",          seuils["eleve"])

            model = xgb.XGBRegressor(**params, random_state=42)
            y_train_fit = np.log1p(y_train) if LOG_TRANSFORM else y_train
            model.fit(X_train, y_train_fit)

            preds_raw = model.predict(X_holdout)
            preds = np.clip(np.expm1(preds_raw) if LOG_TRANSFORM else preds_raw, 0, None)
            mae   = mean_absolute_error(y_holdout, preds)
            rmse  = root_mean_squared_error(y_holdout, preds)
            mediane_holdout = float(np.median(y_holdout))
            mae_norm = round(mae / mediane_holdout * 100, 2) if mediane_holdout > 0 else 0.0

            mlflow.log_metric("mae_holdout",           round(mae,      2))
            mlflow.log_metric("rmse_holdout",          round(rmse,     2))
            mlflow.log_metric("mae_normalisee_holdout", mae_norm)

            vraie_charge = y_holdout / capacite
            pred_charge  = preds     / capacite
            bonne_alerte = float(np.mean(
                (vraie_charge >= seuils["eleve"]) == (pred_charge >= seuils["eleve"])
            ))
            mlflow.log_metric("precision_alerte_elevee", round(bonne_alerte, 4))

            fi = dict(zip(FEATURES, model.feature_importances_.round(4)))
            mlflow.log_dict(fi, "feature_importance.json")
            mlflow.xgboost.log_model(model, name="model")

            log.info(
                "  MAE=%.1f passages/j | RMSE=%.1f | MAE/médiane=%.0f%% | Alertes élevées correctes=%.0f%%",
                mae, rmse, mae_norm, bonne_alerte * 100,
            )

    log.info("Terminé — ouvre MLflow UI > Experiments > %s", site_cfg["mlflow_experiment"])


def main() -> None:
    args = parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    site_cfg   = SITES[args.site]
    mlflow_uri = args.mlflow_uri or MLFLOW_CFG["uri"]
    run_training(site_cfg=site_cfg, mlflow_uri=mlflow_uri)


if __name__ == "__main__":
    main()
