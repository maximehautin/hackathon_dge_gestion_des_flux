#!/usr/bin/env python3
"""
Projection de fréquentation à J+7 avec indice de risque.

Charge le meilleur modèle depuis MLflow, récupère les prévisions météo
et le calendrier bundlé, puis prédit les 7 prochains jours.

Usage CLI :
    python predict.py --site herretang
    python predict.py --site herretang --mlflow-uri https://mon-serveur-mlflow
"""
import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import numpy as np
import pandas as pd
import requests
import mlflow
import mlflow.xgboost

from config import MLFLOW as MLFLOW_CFG, FEATURES, DATA_DIR, CALENDRIER_DIR, LOG_TRANSFORM
from sites import SITES, DEFAULT_SITE

log = logging.getLogger(__name__)

COULEURS = {
    "FAIBLE":  ("🟢", "steelblue",  "Faible"),
    "MODÉRÉ":  ("🟠", "darkorange", "Modéré"),
    "ÉLEVÉ":   ("🔴", "crimson",    "Élevé"),
}


def charger_meilleur_modele(site_cfg: dict, mlflow_uri: str):
    mlflow.set_tracking_uri(mlflow_uri)
    client     = mlflow.tracking.MlflowClient()
    experiment = client.get_experiment_by_name(site_cfg["mlflow_experiment"])
    if experiment is None or experiment.lifecycle_stage == "deleted":
        raise RuntimeError(
            f"Expérience '{site_cfg['mlflow_experiment']}' introuvable. "
            "Lancez d'abord train.py."
        )
    # Récupérer les 3 runs les plus récents (= dernière session d'entraînement)
    # pour éviter de sélectionner un ancien modèle entraîné avec un jeu de features différent.
    recent_runs = client.search_runs(
        experiment_ids=[experiment.experiment_id],
        order_by=["start_time DESC"],
        max_results=3,
    )
    if not recent_runs:
        raise RuntimeError("Aucun run trouvé. Lancez d'abord train.py.")

    metric = MLFLOW_CFG["metric_best"]
    best_run = min(
        (r for r in recent_runs if metric in r.data.metrics),
        key=lambda r: r.data.metrics[metric],
        default=recent_runs[0],
    )
    mae      = best_run.data.metrics.get(MLFLOW_CFG["metric_best"], "?")
    capacite = int(
        best_run.data.params.get("capacite_journaliere")
        or site_cfg.get("capacite_journaliere")
        or 300
    )
    log.info("Meilleur modèle : %s  (MAE = %s passages/j)", best_run.info.run_name, mae)
    log.info("Capacité du site : %d passages/jour", capacite)

    model = mlflow.xgboost.load_model(f"runs:/{best_run.info.run_id}/model")
    return model, capacite


def charger_calendrier_local() -> tuple[set, list]:
    """Charge jours fériés et vacances scolaires depuis les JSON bundlés (zone A / Grenoble)."""
    with open(CALENDRIER_DIR / "jours_feries_metropole.json", encoding="utf-8") as f:
        feries = set(json.load(f).keys())

    with open(CALENDRIER_DIR / "vacances_grenoble.json", encoding="utf-8") as f:
        data = json.load(f)
    vacances_periodes = [
        (pd.to_datetime(r["start_date"]).date(), pd.to_datetime(r["end_date"]).date())
        for r in data["results"]
    ]
    return feries, vacances_periodes


def construire_lags(historique: pd.Series):
    today     = pd.Timestamp.today().normalize().tz_localize(None)
    last_date = historique.index.max()
    data_age  = (today - last_date).days

    if data_age > 30:
        fallback = historique.median()
        log.warning(
            "Données historiques antérieures de %d j → fallback médiane (%.0f passages/j)",
            data_age, fallback,
        )
    else:
        fallback = historique.mean()

    def lag(date: pd.Timestamp, n: int) -> float:
        cible = date - pd.Timedelta(days=n)
        return float(historique.get(cible, fallback))

    return lag


def fetch_meteo_prevision(site_cfg: dict) -> pd.DataFrame:
    url = (
        f"https://api.open-meteo.com/v1/forecast"
        f"?latitude={site_cfg['latitude']}&longitude={site_cfg['longitude']}"
        f"&daily=temperature_2m_mean,precipitation_sum,precipitation_hours,snowfall_sum"
        f"&forecast_days=7&timezone=Europe%2FParis"
    )
    log.info("Prévisions 7 jours pour %s...", site_cfg["nom"])
    resp = requests.get(url, timeout=5)
    resp.raise_for_status()
    w = resp.json()["daily"]
    return pd.DataFrame({
        "date":               pd.to_datetime(w["time"]),
        "temperature_moy":    w["temperature_2m_mean"],
        "precipitations_mm":  w["precipitation_sum"],
        "pluie_heures":       w["precipitation_hours"],
        "neige_oui_non_jour": [int(s > 0) if s else 0 for s in w["snowfall_sum"]],
    })


def niveau_risque(passages: int, capacite: int, seuils: dict) -> tuple[str, float]:
    ratio = passages / capacite
    if ratio >= seuils["eleve"]:
        return "ÉLEVÉ",  ratio
    if ratio >= seuils["modere"]:
        return "MODÉRÉ", ratio
    return "FAIBLE", ratio


def run_prediction(
    site_id: str,
    site_cfg: dict,
    mlflow_uri: str = None,
    max_results: int = None,
    *,
    model=None,
    capacite: int = None,
    historique: pd.Series = None,
    feries: set = None,
    vacances_periodes: list = None,
) -> dict:
    """
    Orchestre la prédiction J+7 et retourne un dict JSON-sérialisable.
    - API  : passe model/capacite/historique/feries/vacances (boot cache) → zéro I/O statique.
    - CLI  : laisse tout à None → charge depuis MLflow + disque + calendrier bundlé.
    """
    if model is None:
        model, capacite = charger_meilleur_modele(site_cfg, mlflow_uri, max_results)

    if historique is None:
        daily = pd.read_csv(
            DATA_DIR / site_cfg["journalier_csv"], sep=";", encoding="utf-8-sig"
        )
        daily["date"] = pd.to_datetime(daily["date"])
        daily = daily[daily["jour_complet"] == 1]
        historique = daily.set_index("date")["passages_jour"].sort_index()

    lag = construire_lags(historique)

    df = fetch_meteo_prevision(site_cfg)

    if feries is None or vacances_periodes is None:
        feries, vacances_periodes = charger_calendrier_local()

    def est_vacances(date: pd.Timestamp) -> int:
        d = date.date()
        return int(any(s <= d < e for s, e in vacances_periodes))

    df["weekend"]                   = (df["date"].dt.dayofweek >= 5).astype(int)
    df["jour_ferie"]                = df["date"].dt.strftime("%Y-%m-%d").isin(feries).astype(int)
    df["vacances_scolaires_zone_a"] = df["date"].apply(est_vacances)
    df["mois"]                      = df["date"].dt.month
    df["jour_semaine"]              = df["date"].dt.dayofweek
    df["passages_j1"]               = df["date"].apply(lambda d: lag(d, 1))
    df["passages_j7"]               = df["date"].apply(lambda d: lag(d, 7))
    df["passages_j365"]             = df["date"].apply(lambda d: lag(d, 365))
    df["nb_evenements_references_j"] = 0

    X = df[FEATURES].values
    preds_raw = model.predict(X)
    preds = np.clip(np.expm1(preds_raw) if LOG_TRANSFORM else preds_raw, 0, None)
    df["passages_prevus"] = preds.round().astype(int)

    seuils = site_cfg["seuils_risque"]
    df[["risque", "charge"]] = df["passages_prevus"].apply(
        lambda p: pd.Series(niveau_risque(p, capacite, seuils))
    )

    _hist_df = historique.reset_index()
    _hist_df.columns = ["date", "passages_jour"]
    _ref_by_dow = _hist_df.groupby(_hist_df["date"].dt.dayofweek)["passages_jour"].median()

    return {
        "site": {
            "id":      site_id,
            "nom":     site_cfg["nom"],
            "commune": site_cfg["commune"],
        },
        "capacite": capacite,
        "seuils_abs": {
            "modere": int(capacite * seuils["modere"]),
            "eleve":  int(capacite * seuils["eleve"]),
        },
        "predictions": [
            {
                "date":               row["date"].strftime("%Y-%m-%d"),
                "passages_prevus":    int(row["passages_prevus"]),
                "pic_horaire_estime": int(round(row["passages_prevus"] * 0.22)),
                "passages_reference": int(round(_ref_by_dow.get(row["date"].dayofweek, 0))),
                "risque":             row["risque"],
                "charge":             round(float(row["charge"]), 3),
                "temperature_moy":    round(float(row["temperature_moy"]), 1),
                "precipitations_mm":  round(float(row["precipitations_mm"]), 1),
                "pluie_heures":       round(float(row["pluie_heures"]), 1),
                "neige":              bool(row["neige_oui_non_jour"]),
                "weekend":            bool(row["weekend"]),
                "jour_ferie":         bool(row["jour_ferie"]),
                "vacances":           bool(row["vacances_scolaires_zone_a"]),
            }
            for _, row in df.iterrows()
        ],
    }


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Projette la fréquentation à J+7 (sortie JSON sur stdout).",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--site",        default=DEFAULT_SITE, choices=list(SITES.keys()))
    p.add_argument("--mlflow-uri",  default=None)
    p.add_argument("--max-results", type=int, default=None)
    p.add_argument("--verbose", "-v", action="store_true")
    return p.parse_args()


def main() -> None:
    import json as _json
    args = parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    mlflow_uri  = args.mlflow_uri or MLFLOW_CFG["uri"]
    max_results = args.max_results or MLFLOW_CFG["max_results"]
    result = run_prediction(args.site, SITES[args.site], mlflow_uri, max_results)
    print(_json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
