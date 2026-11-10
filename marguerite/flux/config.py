"""Chemins, paramètres et clés d'API.

Les clés ne sont jamais écrites dans le code. OPENROUTER_API_KEY et les autres
clés viennent de l'environnement ; les clés Apidae, Géovélo, Loopi et
DataTourisme peuvent aussi venir de l'onglet « Codes » de l'inventaire.
"""
from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("FLUX_DATA_DIR", ROOT / "data"))
ARTIFACTS = Path(os.environ.get("FLUX_ARTIFACTS", ROOT / "artifacts"))
ARTIFACTS.mkdir(parents=True, exist_ok=True)

DEPARTEMENT = os.environ.get("FLUX_DEPARTEMENT", "38")
ZONE_SCOLAIRE = os.environ.get("FLUX_ZONE_SCOLAIRE", "Zone A")  # Grenoble = zone A
TZ = "Europe/Paris"

S3_BASE = "https://minio.lab.sspcloud.fr/projet-hackathon-gestion-flux-isere/"
S3_PREFIX = "diffusion/"

# Fichiers du bucket utilisés (chemins relatifs à DATA_DIR)
F_INVENTAIRE = "Données à disposition - par onglet.xlsx"
F_SITES_SURFREQ = "Sites et équipements/Sites sur-fréquentés.xlsx"
F_DATATOURISME = "Sites et équipements/Données France DataTourisme.xlsx"
F_HEBERGEMENTS = "Hébergements/Hébergements par commune.xlsx"
F_COMMUNES = "Communes/Communes d'Isere.xlsx"
F_DISTANCES = "Communes/Distances villes/Distances_routieres_Isere.xlsx"
F_GARES = "Transports/Equipements gares, taxis et aéroport par commune.xlsx"
F_FORFAITS = "Fréquentation/Ventes en lignes forfaits stations 7 laux et Collet 2024-2026.xlsx"
D_ENS = "Fréquentation/DONNEES brutes ecocompteurs ENS"
F_ECO_HIST = "Fréquentation/eco-compteur-Isère/comptages/historique_2021_2024.csv"
F_ECO_DAILY = "Fréquentation/eco-compteur-Isère/comptages/comptages_journalier_2025_2026.csv"

# Compteur en panne : une suite d'au moins DEAD_RUN_DAYS jours à zéro est retirée des séries ;
# si elle termine la série, le site est « en panne ». L'ancienneté des données est évaluée
# par rapport au jour consulté.
DEAD_RUN_DAYS = 14
STALE_DAYS = 28

# Points d'accès utilisés comme origines pour le calcul d'accessibilité
ORIGINES = {
    "Grenoble (gare)": (45.1915, 5.7144),
    "Lyon (Part-Dieu)": (45.7606, 4.8596),
    "Chambéry (gare)": (45.5713, 5.9199),
}

GEOVELO_URL = "https://backend.geovelo.fr/api/v2/computedroutes"
OPEN_METEO_FORECAST = "https://api.open-meteo.com/v1/forecast"
OPEN_METEO_ELEVATION = "https://api.open-meteo.com/v1/elevation"
OPEN_METEO_ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"
EDUCATION_CALENDAR = (
    "https://data.education.gouv.fr/api/explore/v2.1/catalog/datasets/"
    "fr-en-calendrier-scolaire/records"
)


@lru_cache(maxsize=1)
def _codes_from_excel() -> dict[str, str]:
    """Lit l'onglet Codes de l'inventaire si le fichier est présent (jamais loggé)."""
    path = DATA_DIR / F_INVENTAIRE
    if not path.exists():
        return {}
    try:
        import pandas as pd

        x = pd.read_excel(path, sheet_name="Codes", header=None)
    except Exception:
        return {}
    out: dict[str, str] = {}
    for _, row in x.iterrows():
        label = str(row.iloc[1]).lower() if len(row) > 1 else ""
        blob = " ".join(str(v) for v in row.tolist() if isinstance(v, str))
        key = re.search(r"Cl[ée] API\s*:\s*(\S+)", blob)
        if "géovélo" in label or "geovelo" in label:
            if key:
                out["GEOVELO_API_KEY"] = key.group(1)
        elif "apidae" in blob.lower():
            if key:
                out["APIDAE_API_KEY"] = key.group(1)
        elif "datatourisme" in label and key:
            out["DATATOURISME_API_KEY"] = key.group(1)
        elif "loopi" in label:
            u = re.search(r"Utilisateur\s*:\s*(\S+)", blob)
            p = re.search(r"Mot de passe\s*:\s*(\S+)", blob)
            if u:
                out["LOOPI_USER"] = u.group(1)
            if p:
                out["LOOPI_PASSWORD"] = p.group(1)
    return out


def secret(name: str) -> str | None:
    return os.environ.get(name) or _codes_from_excel().get(name)
