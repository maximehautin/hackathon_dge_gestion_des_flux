"""
Paramètres centralisés — MLflow, features, hyperparamètres.
Le catalogue des sites est dans sites.py.
"""
import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
except ImportError:
    pass

ROOT           = Path(__file__).resolve().parent
# En Docker, DATA_DIR est injecté via l'env var pour pointer vers le volume monté (/app/data).
# En local, il remonte à src/data/ par rapport à src/api/.
DATA_DIR       = Path(os.getenv("DATA_DIR", str(ROOT.parent / "data")))
CALENDRIER_DIR = DATA_DIR / "calendrier"

MLFLOW = {
    "uri":         os.getenv("MLFLOW_TRACKING_URI", f"sqlite:///{ROOT / 'mlflow' / 'mlflow.db'}"),
    "metric_best": "mae_holdout",
}

# Transformation log1p de la cible à l'entraînement (expm1 à la prédiction).
# Réduit l'influence des pics extrêmes sur la loss XGBoost et améliore la MAE
# sur les queues hautes (journées de sur-fréquentation).
LOG_TRANSFORM = True

FEATURES = [
    "mois", "jour_semaine", "weekend", "jour_ferie", "vacances_scolaires_zone_a",
    "temperature_moy", "precipitations_mm", "pluie_heures", "neige_oui_non_jour",
    "passages_j1", "passages_j7", "passages_j365",
    "nb_evenements_references_j",
]

HYPERPARAMETRES = [
    {"n_estimators": 100, "max_depth": 3, "learning_rate": 0.10, "subsample": 1.0},
    {"n_estimators": 300, "max_depth": 5, "learning_rate": 0.05, "subsample": 0.8},
    {"n_estimators": 500, "max_depth": 6, "learning_rate": 0.02, "subsample": 0.8},
]
