"""
Fonctions partagées entre l'entraînement (train.py) et la projection (predict.py).
"""
import logging

import pandas as pd
import requests

log = logging.getLogger(__name__)


def fetch_temperature_historique(start_date: str, end_date: str, site_cfg: dict) -> pd.DataFrame:
    url = (
        f"https://archive-api.open-meteo.com/v1/archive"
        f"?latitude={site_cfg['latitude']}&longitude={site_cfg['longitude']}"
        f"&daily=temperature_2m_mean"
        f"&start_date={start_date}&end_date={end_date}"
        f"&timezone=Europe%2FParis"
    )
    log.info("Récupération température historique %s → %s", start_date, end_date)
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    return pd.DataFrame({
        "date":            pd.to_datetime(resp.json()["daily"]["time"]),
        "temperature_moy": resp.json()["daily"]["temperature_2m_mean"],
    })
