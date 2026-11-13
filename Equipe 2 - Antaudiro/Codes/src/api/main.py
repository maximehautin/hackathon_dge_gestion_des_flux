"""
API FastAPI — Flux Touristiques CG38.

Endpoints :
  GET  /health                    → état de l'API
  GET  /sites                     → liste des sites disponibles
  GET  /predict/{site_id}         → projection J+7 pour un site
  GET  /history/{site_id}         → comptages historiques (CSV) sur une plage de dates
  GET  /metrics/{site_id}         → métriques MLflow + importances des variables
  POST /train/{site_id}           → lance l'entraînement XGBoost en arrière-plan
  GET  /train/{site_id}/status    → état de l'entraînement

Au démarrage : modèle XGBoost + historique CSV + calendrier chargés en cache par site.
Les requêtes /predict n'accèdent ni à MLflow ni aux APIs calendrier.
Seul Open-Meteo (météo J+7) est appelé à chaque prédiction.
"""
import asyncio
import json
import logging
from contextlib import asynccontextmanager
from typing import Literal

import mlflow

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

import pandas as pd

from config import MLFLOW as MLFLOW_CFG, DATA_DIR, FEATURES
from sites import SITES
from predict import charger_meilleur_modele, charger_calendrier_local, run_prediction

log = logging.getLogger(__name__)

# { site_id: (model, capacite, historique, feries, vacances_periodes) }
MODEL_CACHE: dict = {}

# { site_id: "idle" | "training" | "done" | "error" }
TRAINING_STATUS: dict[str, str] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("Chargement des modèles et données statiques...")
    sites_a_entrainer: list[str] = []
    for site_id, cfg in SITES.items():
        if cfg.get("journalier_csv") is None:
            log.info("  %s — pas de données, ignoré", site_id)
            continue
        try:
            model, capacite = charger_meilleur_modele(
                cfg, MLFLOW_CFG["uri"]
            )
            # Vérifie que le modèle a été entraîné avec le jeu de features courant
            if model.n_features_in_ != len(FEATURES):
                raise ValueError(
                    f"Modèle entraîné avec {model.n_features_in_} features, "
                    f"{len(FEATURES)} attendues — réentraînement nécessaire."
                )
            df_j = pd.read_csv(DATA_DIR / cfg["journalier_csv"], sep=";", encoding="utf-8-sig")
            df_j["date"] = pd.to_datetime(df_j["date"])
            df_j = df_j[df_j["jour_complet"] == 1]
            historique = df_j.set_index("date")["passages_jour"].sort_index()
            feries, vacances_periodes = charger_calendrier_local()
            MODEL_CACHE[site_id] = (model, capacite, historique, feries, vacances_periodes)
            log.info("  %s — prêt ✓", site_id)
        except Exception as e:
            log.warning("  %s — modèle absent ou obsolète : %s", site_id, e)
            sites_a_entrainer.append(site_id)

    if sites_a_entrainer:
        log.info(
            "Training automatique lancé pour %d site(s) : %s",
            len(sites_a_entrainer), ", ".join(sites_a_entrainer),
        )
        for site_id in sites_a_entrainer:
            TRAINING_STATUS[site_id] = "training"
            await _train_and_reload(site_id)

    log.info("API prête. %d site(s) en cache.", len(MODEL_CACHE))
    yield
    MODEL_CACHE.clear()


app = FastAPI(
    title="Flux Touristiques — API de prédiction",
    description="Projection de fréquentation J+7 avec indice de risque de sur-fréquentation.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {
        "status": "ok",
        "modeles_en_cache": list(MODEL_CACHE.keys()),
    }


@app.get("/sites")
def list_sites():
    return [
        {
            "id":       site_id,
            "nom":      cfg["nom"],
            "commune":  cfg["commune"],
            "has_data": cfg.get("journalier_csv") is not None,
            "ready":    site_id in MODEL_CACHE,
        }
        for site_id, cfg in SITES.items()
    ]


@app.get("/history/{site_id}")
def history(
    site_id: str,
    from_date: str = Query(..., alias="from", description="Date de début (YYYY-MM-DD)"),
    to_date: str = Query(..., alias="to",   description="Date de fin   (YYYY-MM-DD)"),
):
    if site_id not in SITES:
        raise HTTPException(status_code=404, detail=f"Site '{site_id}' inconnu.")
    cfg = SITES[site_id]
    if cfg.get("journalier_csv") is None:
        raise HTTPException(status_code=404, detail="Pas de données CSV pour ce site.")

    df = pd.read_csv(DATA_DIR / cfg["journalier_csv"], sep=";", encoding="utf-8-sig")
    df["date"] = pd.to_datetime(df["date"])
    df = df[df["jour_complet"] == 1]
    date_str = df["date"].dt.strftime("%Y-%m-%d")
    mask = (date_str >= from_date) & (date_str <= to_date)
    result = df[mask][["date", "passages_jour"]].copy()
    result["date"] = result["date"].dt.strftime("%Y-%m-%d")
    return result.to_dict(orient="records")


@app.post("/train/{site_id}")
async def train_site(site_id: str, background_tasks: BackgroundTasks):
    if site_id not in SITES:
        raise HTTPException(status_code=404, detail=f"Site '{site_id}' inconnu.")
    cfg = SITES[site_id]
    if cfg.get("journalier_csv") is None:
        raise HTTPException(status_code=422, detail="Pas de CSV disponible pour ce site.")
    if TRAINING_STATUS.get(site_id) == "training":
        return {"status": "already_training"}

    TRAINING_STATUS[site_id] = "training"
    background_tasks.add_task(_train_and_reload, site_id)
    return {"status": "started"}


@app.get("/train/{site_id}/status")
def train_status(site_id: str):
    if site_id not in SITES:
        raise HTTPException(status_code=404, detail=f"Site '{site_id}' inconnu.")
    return {
        "status": TRAINING_STATUS.get(site_id, "idle"),
        "ready":  site_id in MODEL_CACHE,
    }


async def _train_and_reload(site_id: str) -> None:
    from train import run_training  # import tardif pour éviter les effets de bord au démarrage
    cfg = SITES[site_id]
    try:
        await asyncio.to_thread(run_training, cfg, MLFLOW_CFG["uri"])
        model, capacite = await asyncio.to_thread(
            charger_meilleur_modele, cfg, MLFLOW_CFG["uri"]
        )
        df_j = pd.read_csv(DATA_DIR / cfg["journalier_csv"], sep=";", encoding="utf-8-sig")
        df_j["date"] = pd.to_datetime(df_j["date"])
        df_j = df_j[df_j["jour_complet"] == 1]
        historique = df_j.set_index("date")["passages_jour"].sort_index()
        feries, vacances_periodes = charger_calendrier_local()
        MODEL_CACHE[site_id] = (model, capacite, historique, feries, vacances_periodes)
        TRAINING_STATUS[site_id] = "done"
        log.info("Entraînement terminé et modèle rechargé : %s", site_id)
    except Exception:
        log.exception("Erreur entraînement %s", site_id)
        TRAINING_STATUS[site_id] = "error"


@app.get("/metrics/{site_id}")
def site_metrics(site_id: str):
    if site_id not in SITES:
        raise HTTPException(status_code=404, detail=f"Site '{site_id}' inconnu.")
    cfg = SITES[site_id]

    try:
        mlflow.set_tracking_uri(MLFLOW_CFG["uri"])
        client = mlflow.tracking.MlflowClient()
        experiment = client.get_experiment_by_name(cfg["mlflow_experiment"])
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"MLflow inaccessible : {e}")

    if experiment is None or experiment.lifecycle_stage == "deleted":
        raise HTTPException(status_code=404, detail="Aucun entraînement trouvé pour ce site.")

    runs = client.search_runs(
        experiment_ids=[experiment.experiment_id],
        order_by=["metrics.mae_holdout ASC"],
    )
    if not runs:
        raise HTTPException(status_code=404, detail="Aucun run MLflow pour ce site.")

    best_run_id = runs[0].info.run_id
    feature_importance = None
    try:
        local_path = mlflow.artifacts.download_artifacts(
            f"runs:/{best_run_id}/feature_importance.json"
        )
        with open(local_path) as f:
            feature_importance = json.load(f)
    except Exception:
        pass

    return {
        "site": {"id": site_id, "nom": cfg["nom"], "commune": cfg["commune"]},
        "runs": [
            {
                "run_id":   r.info.run_id,
                "run_name": r.info.run_name or f"run-{r.info.run_id[:8]}",
                "is_best":  r.info.run_id == best_run_id,
                "metrics": {
                    "mae_holdout":             r.data.metrics.get("mae_holdout"),
                    "rmse_holdout":            r.data.metrics.get("rmse_holdout"),
                    "mae_normalisee_holdout":  r.data.metrics.get("mae_normalisee_holdout"),
                    "precision_alerte_elevee": r.data.metrics.get("precision_alerte_elevee"),
                },
                "params": {
                    "n_estimators":  r.data.params.get("n_estimators"),
                    "max_depth":     r.data.params.get("max_depth"),
                    "learning_rate": r.data.params.get("learning_rate"),
                    "subsample":     r.data.params.get("subsample"),
                    "train_jours":   r.data.params.get("train_jours"),
                    "holdout_jours": r.data.params.get("holdout_jours"),
                },
            }
            for r in runs
        ],
        "feature_importance": feature_importance,
    }


@app.get("/predict/{site_id}")
def predict(site_id: str):
    if site_id not in SITES:
        raise HTTPException(status_code=404, detail=f"Site '{site_id}' inconnu.")

    if site_id not in MODEL_CACHE:
        raise HTTPException(status_code=503, detail=f"Modèle non disponible pour '{site_id}'.")

    model, capacite, historique, feries, vacances_periodes = MODEL_CACHE[site_id]
    try:
        return run_prediction(
            site_id=site_id,
            site_cfg=SITES[site_id],
            model=model,
            capacite=capacite,
            historique=historique,
            feries=feries,
            vacances_periodes=vacances_periodes,
        )
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))
