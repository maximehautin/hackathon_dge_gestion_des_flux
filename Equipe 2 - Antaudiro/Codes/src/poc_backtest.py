"""
POC — Backtest : prédictions vs données réelles
Test du modèle sur des périodes hors entraînement (2023-2024) et hors sélection (holdout 2025).

Usage :
    python3 poc_backtest.py [--site SITE] [--date YYYY-MM-DD] [--jours N] [--mode single|multi]

    --site  : identifiant du site (défaut : herretang, voir sites.py)
    --date  : premier jour du backtest en mode 'single' (défaut : 2026-04-15)
    --jours : nombre de jours en mode 'single' (défaut : 7)
    --mode  : 'single' (une période) ou 'multi' (3 semaines réparties sur l'année)

Données réelles : archives ENS CG38 Environnement (un canal IN par site, voir sites.py)
Comparaison systématique avec une baseline naïve (prédire = même jour la semaine passée).
"""
import argparse
import sys
import time
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "api"))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import mlflow
import mlflow.xgboost
import numpy as np
import pandas as pd
import requests

from config import MLFLOW as MLFLOW_CFG, FEATURES, CALENDRIER_DIR
from sites import SITES, DEFAULT_SITE

ENS_DIR = Path("/home/wazolab/Downloads/Fréquentation/DONNEES brutes ecocompteurs ENS")

# ─────────────────────────────────────────────
# 0. ARGUMENTS
# ─────────────────────────────────────────────
parser = argparse.ArgumentParser(description="Backtest du modèle de prédiction de fréquentation")
parser.add_argument("--site",  default=DEFAULT_SITE, choices=SITES.keys(),
                    help=f"Site à tester (défaut : {DEFAULT_SITE})")
parser.add_argument("--date",  default="2026-04-15",
                    help="Premier jour du backtest en mode single (YYYY-MM-DD)")
parser.add_argument("--jours", type=int, default=7,
                    help="Nombre de jours à tester en mode single (défaut : 7)")
parser.add_argument("--mode",  default="single", choices=["single", "multi"],
                    help="'single' : une période | 'multi' : 3 semaines réparties")
cli = parser.parse_args()

SITE = SITES[cli.site]
print(f"[Backtest] Site    : {SITE['nom']} ({cli.site})")
print(f"[Backtest] Mode    : {cli.mode}")

# ─────────────────────────────────────────────
# 1. CHARGEMENT DU MEILLEUR MODÈLE MLFLOW
# ─────────────────────────────────────────────
mlflow.set_tracking_uri(MLFLOW_CFG["uri"])
client     = mlflow.tracking.MlflowClient()
experiment = client.get_experiment_by_name(SITE["mlflow_experiment"])
if experiment is None:
    raise RuntimeError(
        f"Expérience '{SITE['mlflow_experiment']}' introuvable — "
        "lancez d'abord train.py."
    )

runs = client.search_runs(
    experiment_ids=[experiment.experiment_id],
    order_by=["start_time DESC"],
    max_results=3,
)
if not runs:
    raise RuntimeError("Aucun run trouvé — lancez d'abord train.py.")

best_run  = min(runs, key=lambda r: r.data.metrics.get(MLFLOW_CFG["metric_best"], float("inf")))
mae_ref   = best_run.data.metrics.get(MLFLOW_CFG["metric_best"], "?")
capacite  = int(best_run.data.params.get("capacite_journaliere") or SITE["capacite_journaliere"] or 300)
print(f"[MLflow]  Modèle   : {best_run.info.run_name}  (MAE holdout 2025 = {mae_ref} passages/j)")
print(f"[MLflow]  Capacité : {capacite} passages/jour")

# Chargement du modèle : SSP Cloud en priorité, mlartifacts locaux en fallback
model = None
run_uri = f"runs:/{best_run.info.run_id}/model"
try:
    model = mlflow.xgboost.load_model(run_uri)
    print(f"[MLflow]  Chargé depuis serveur MLflow (run URI)")
except Exception:
    # Fallback : recherche dans les artefacts locaux (utile sans accès réseau)
    mlartifacts_dir = Path(__file__).parent / "mlartifacts"
    model_local_path = None
    for mlmodel_file in mlartifacts_dir.rglob("MLmodel"):
        if best_run.info.run_id in mlmodel_file.read_text():
            model_local_path = str(mlmodel_file.parent)
            break
    if model_local_path is None:
        raise RuntimeError(
            f"Modèle introuvable pour le run {best_run.info.run_id} — "
            "ni via le serveur MLflow ni en local (src/mlartifacts/)."
        )
    model = mlflow.xgboost.load_model(model_local_path)
    print(f"[MLflow]  Chargé depuis artefacts locaux : {model_local_path}")

# ─────────────────────────────────────────────
# 2. DONNÉES ENS — totaux journaliers (toutes années utiles)
# ─────────────────────────────────────────────
def lire_comptages_ens(zip_path: Path, channel_id: str) -> pd.Series:
    """Totaux journaliers depuis un zip ENS pour un canal donné."""
    with zipfile.ZipFile(zip_path) as z:
        with z.open("measures.csv") as f:
            df = pd.read_csv(
                f,
                usecols=["channel_id", "start_datetime", "count"],
                dtype={"channel_id": str, "count": float},
            )
    df = df[df["channel_id"] == channel_id].copy()
    df["date"] = pd.to_datetime(df["start_datetime"].str[:10])
    return df.groupby("date")["count"].sum().rename("passages_jour")


def charger_historique(channel_id: str, annees: range) -> pd.Series:
    """Charge et concatène les comptages ENS pour plusieurs années."""
    series = []
    for annee in annees:
        zip_path = ENS_DIR / f"export-transport-data-gouv-fr_CG38Environnement_{annee}.zip"
        if not zip_path.exists():
            print(f"[ENS] Archive {annee} introuvable — ignorée")
            continue
        print(f"[ENS] Lecture {annee} (canal {channel_id})...")
        series.append(lire_comptages_ens(zip_path, channel_id))
    if not series:
        raise RuntimeError("Aucune archive ENS disponible.")
    histo = pd.concat(series).sort_index()
    return histo[~histo.index.duplicated(keep="last")]

# ─────────────────────────────────────────────
# 3. PÉRIODES DE BACKTEST
# ─────────────────────────────────────────────
if cli.mode == "single":
    start = pd.Timestamp(cli.date)
    periodes = [(start, start + pd.Timedelta(days=cli.jours - 1))]
else:
    # Mode multi : 3 semaines sur des saisons différentes en 2026
    # (hiver, printemps, et début-été si données disponibles)
    periodes = [
        (pd.Timestamp("2026-02-02"), pd.Timestamp("2026-02-08")),   # Hiver
        (pd.Timestamp("2026-04-07"), pd.Timestamp("2026-04-13")),   # Printemps
        (pd.Timestamp("2026-04-29"), pd.Timestamp("2026-05-05")),   # Début mai
    ]
    print(f"[Backtest] Périodes : {', '.join(str(s.date())+' → '+str(e.date()) for s,e in periodes)}")

# Années à précharger (lags remontent jusqu'à 7 jours avant la première période)
lag_start  = min(s for s, _ in periodes) - pd.Timedelta(days=7)
data_end   = max(e for _, e in periodes)
annees     = range(lag_start.year, data_end.year + 1)

historique = charger_historique(SITE["channel_in"], annees)
fallback_lag = float(historique.median())
print(f"[ENS] {len(historique)} jours disponibles "
      f"({historique.index.min().date()} → {historique.index.max().date()})")

def lag(date, n):
    cible = pd.Timestamp(date).normalize() - pd.Timedelta(days=n)
    return float(historique[cible]) if cible in historique.index else fallback_lag

# ─────────────────────────────────────────────
# 4. MÉTÉO — une seule requête pour toute la plage de dates
# ─────────────────────────────────────────────
meteo_start = min(s for s, _ in periodes)
meteo_end   = max(e for _, e in periodes)
print(f"[Météo] Archive {meteo_start.date()} → {meteo_end.date()}...")
url = (
    f"https://archive-api.open-meteo.com/v1/archive"
    f"?latitude={SITE['latitude']}&longitude={SITE['longitude']}"
    f"&daily=temperature_2m_mean,precipitation_sum,precipitation_hours,snowfall_sum"
    f"&start_date={meteo_start.date()}&end_date={meteo_end.date()}"
    f"&timezone=Europe%2FParis"
)
for tentative in range(4):
    resp = requests.get(url, timeout=30)
    if resp.status_code != 429:
        break
    attente = 60 * (tentative + 1)
    print(f"[Météo] Rate limit (429) — pause {attente}s avant tentative {tentative+2}/4...")
    time.sleep(attente)
resp.raise_for_status()
w = resp.json()["daily"]
meteo_global = pd.DataFrame({
    "date":               pd.to_datetime(w["time"]),
    "temperature_moy":    w["temperature_2m_mean"],
    "precipitations_mm":  w["precipitation_sum"],
    "pluie_heures":       w["precipitation_hours"],
    "neige_oui_non_jour": [int(s > 0) if s else 0 for s in w["snowfall_sum"]],
}).set_index("date")

# ─────────────────────────────────────────────
# 5. CALENDRIER — fichiers bundlés (zone A / Grenoble)
# ─────────────────────────────────────────────
import json as _json
print("[Calendrier] Chargement depuis fichiers bundlés...")
with open(CALENDRIER_DIR / "jours_feries_metropole.json", encoding="utf-8") as _f:
    feries = set(_json.load(_f).keys())
with open(CALENDRIER_DIR / "vacances_grenoble.json", encoding="utf-8") as _f:
    _vac_data = _json.load(_f)
vacances_periodes = [
    (pd.to_datetime(r["start_date"]).date(), pd.to_datetime(r["end_date"]).date())
    for r in _vac_data["results"]
]

def est_vacances(date):
    d = date.date()
    return int(any(s <= d < e for s, e in vacances_periodes))

# ─────────────────────────────────────────────
# 6. FONCTION DE BACKTEST SUR UNE PÉRIODE
# ─────────────────────────────────────────────
def backtest_periode(start_date: pd.Timestamp, end_date: pd.Timestamp) -> pd.DataFrame:
    """Construit le DataFrame de backtest pour une période donnée (météo déjà chargée)."""
    dates = pd.date_range(start=start_date, end=end_date, freq="D")
    df = meteo_global.reindex(dates).reset_index().rename(columns={"index": "date"})

    df["weekend"]                   = (df["date"].dt.day_of_week >= 5).astype(int)
    df["jour_ferie"]                = df["date"].dt.strftime("%Y-%m-%d").isin(feries).astype(int)
    df["vacances_scolaires_zone_a"] = df["date"].apply(est_vacances)
    df["mois"]                      = df["date"].dt.month
    df["jour_semaine"]               = df["date"].dt.day_of_week
    df["passages_j1"]               = df["date"].apply(lambda d: lag(d, 1))
    df["passages_j7"]               = df["date"].apply(lambda d: lag(d, 7))

    # Données réelles
    df["passages_reels"] = df["date"].apply(
        lambda d: float(historique[d.normalize()])
        if d.normalize() in historique.index else np.nan
    )

    # Baseline naïve : prédire le même jour la semaine passée (lag J-7)
    df["baseline_naive"] = df["passages_j7"].round().astype(int)

    # Prédictions XGBoost
    manquantes = df[FEATURES].isnull().sum()
    if manquantes.any():
        df[FEATURES] = df[FEATURES].fillna(df[FEATURES].mean())
    X = df[FEATURES].values
    df["passages_prevus"] = np.clip(model.predict(X), 0, None).round().astype(int)

    return df

# ─────────────────────────────────────────────
# 6. EXÉCUTION DES BACKTESTS
# ─────────────────────────────────────────────
seuils = SITE["seuils_risque"]

def niveau_alerte(passages):
    r = passages / capacite
    if r >= seuils["eleve"]:  return "ÉLEVÉ"
    if r >= seuils["modere"]: return "MODÉRÉ"
    return "FAIBLE"

resultats_par_periode = []
for start_date, end_date in periodes:
    print(f"\n[Backtest] Période {start_date.date()} → {end_date.date()}...")
    df = backtest_periode(start_date, end_date)
    resultats_par_periode.append(df)

df_all = pd.concat(resultats_par_periode, ignore_index=True)
df_valid = df_all.dropna(subset=["passages_reels"]).copy()

if len(df_valid) == 0:
    raise RuntimeError("Aucune donnée réelle disponible pour les périodes testées.")

y_real   = df_valid["passages_reels"].values
y_xgb    = df_valid["passages_prevus"].values
y_naive  = df_valid["baseline_naive"].values

# ─────────────────────────────────────────────
# 7. MÉTRIQUES GLOBALES
# ─────────────────────────────────────────────
def metrics(y_true, y_pred):
    mae  = float(np.mean(np.abs(y_true - y_pred)))
    rmse = float(np.sqrt(np.mean((y_true - y_pred) ** 2)))
    mape = float(np.mean(np.abs((y_true - y_pred) / np.clip(y_true, 1, None))) * 100)
    return mae, rmse, mape

mae_xgb,  rmse_xgb,  mape_xgb  = metrics(y_real, y_xgb)
mae_naive, rmse_naive, mape_naive = metrics(y_real, y_naive)

# Précision alertes
df_valid["alerte_reelle"]   = df_valid["passages_reels"].apply(niveau_alerte)
df_valid["alerte_prevue"]   = df_valid["passages_prevus"].apply(niveau_alerte)
df_valid["alerte_naive"]    = df_valid["baseline_naive"].apply(niveau_alerte)
prec_xgb   = (df_valid["alerte_reelle"] == df_valid["alerte_prevue"]).mean()
prec_naive = (df_valid["alerte_reelle"] == df_valid["alerte_naive"]).mean()

# ─────────────────────────────────────────────
# 8. RÉSUMÉ CONSOLE
# ─────────────────────────────────────────────
print(f"\n{'═'*70}")
print(f" Backtest — {SITE['nom']}")
print(f" Modèle : {best_run.info.run_name}  |  MAE holdout 2025 : {mae_ref} passages/j")
print(f"{'═'*70}")

for df_p in resultats_par_periode:
    start = df_p["date"].min()
    end   = df_p["date"].max()
    df_pv = df_p.dropna(subset=["passages_reels"])
    if df_pv.empty:
        print(f"\n  — {start.date()} → {end.date()} : aucune donnée réelle")
        continue
    print(f"\n  Période {start.date()} → {end.date()}")
    print(f"  {'Jour':<13} {'Réel':>7} {'XGBoost':>8} {'Naïf':>7} {'Err%XGB':>9} {'Alerte réelle':<15} {'XGB?':<8} {'Naïf?'}")
    print(f"  {'─'*80}")
    for _, row in df_pv.iterrows():
        reel  = int(row["passages_reels"])
        prevu = int(row["passages_prevus"])
        naive = int(row["baseline_naive"])
        errp  = abs(prevu - reel) / max(reel, 1) * 100
        a_r   = niveau_alerte(reel)
        ok_x  = "✓" if niveau_alerte(prevu) == a_r else "✗"
        ok_n  = "✓" if niveau_alerte(naive) == a_r else "✗"
        print(
            f"  {row['date'].strftime('%a %d/%m'):<13}"
            f"{reel:>7}"
            f"{prevu:>8}"
            f"{naive:>7}"
            f"{errp:>8.0f}%"
            f"  {a_r:<15}"
            f"{ok_x:<8}"
            f"{ok_n}"
        )

print(f"\n{'─'*70}")
print(f"  {'Métrique':<30} {'XGBoost':>12} {'Baseline naïve':>14}")
print(f"  {'─'*58}")
print(f"  {'MAE (passages/j)':<30} {mae_xgb:>12.1f} {mae_naive:>14.1f}")
print(f"  {'RMSE (passages/j)':<30} {rmse_xgb:>12.1f} {rmse_naive:>14.1f}")
print(f"  {'MAPE (%)':<30} {mape_xgb:>12.1f} {mape_naive:>14.1f}")
print(f"  {'Précision alertes (%)':<30} {prec_xgb*100:>12.0f} {prec_naive*100:>14.0f}")
print(f"  {'─'*58}")
print(f"  {'MAE holdout 2025 (référence)':<30} {float(mae_ref):>12.1f}")
apport = (1 - mae_xgb / mae_naive) * 100 if mae_naive > 0 else 0
signe  = "↓ meilleur" if apport > 0 else "↑ moins bon"
print(f"\n  Apport XGBoost vs baseline : {apport:+.1f}% ({signe})")
print(f"{'═'*70}\n")

# ─────────────────────────────────────────────
# 9. GRAPHIQUE — Réel vs XGBoost vs Baseline
# ─────────────────────────────────────────────
n = len(df_valid)
x = np.arange(n)

fig, (ax1, ax2) = plt.subplots(
    2, 1, figsize=(max(14, n * 1.2), 8),
    gridspec_kw={"height_ratios": [3, 1]},
)
titre_periode = (
    f"{periodes[0][0].date()} → {periodes[-1][1].date()}"
    if cli.mode == "multi"
    else f"{periodes[0][0].date()} → {periodes[0][1].date()}"
)
fig.suptitle(
    f"Backtest — {SITE['nom']}\n{titre_periode}",
    fontsize=12, fontweight="bold",
)

bar_w = 0.28
ax1.bar(x - bar_w, df_valid["passages_reels"],  bar_w, label="Réel",           color="steelblue",  alpha=0.85)
ax1.bar(x,          df_valid["passages_prevus"], bar_w, label="XGBoost",        color="darkorange", alpha=0.85)
ax1.bar(x + bar_w,  df_valid["baseline_naive"],  bar_w, label="Baseline (J-7)", color="mediumseagreen", alpha=0.75)

ax1.axhline(
    capacite * seuils["eleve"],  color="crimson", linestyle=":", linewidth=1.2,
    label=f"Seuil élevé ≥ {int(seuils['eleve']*100)}%", alpha=0.75,
)
ax1.axhline(
    capacite * seuils["modere"], color="gold",    linestyle=":", linewidth=1.2,
    label=f"Seuil modéré ≥ {int(seuils['modere']*100)}%", alpha=0.75,
)

xlabels = [pd.Timestamp(d).strftime("%a\n%d/%m") for d in df_valid["date"].values]
ax1.set_xticks(x)
ax1.set_xticklabels(xlabels, fontsize=8)
ax1.set_ylabel("Passages / jour")
ax1.legend(fontsize=8, loc="upper left", ncol=2)
ax1.grid(axis="y", alpha=0.3)

# Boîte métriques
ax1.text(
    0.99, 0.97,
    f"XGBoost   MAE={mae_xgb:.1f} · MAPE={mape_xgb:.0f}% · alertes={prec_xgb*100:.0f}%\n"
    f"Baseline  MAE={mae_naive:.1f} · MAPE={mape_naive:.0f}% · alertes={prec_naive*100:.0f}%",
    transform=ax1.transAxes, ha="right", va="top", fontsize=8,
    bbox=dict(boxstyle="round,pad=0.4", facecolor="white", alpha=0.88),
)

# Erreurs XGBoost
errors = df_valid["passages_prevus"] - df_valid["passages_reels"]
bar_colors = ["crimson" if e > 0 else "steelblue" for e in errors]
ax2.bar(x, errors, color=bar_colors, alpha=0.75, label="Erreur XGBoost (prévu − réel)")
ax2.axhline(0, color="black", linewidth=0.8)
ax2.set_xticks(x)
ax2.set_xticklabels(xlabels, fontsize=8)
ax2.set_ylabel("Erreur XGBoost\n(prévu − réel)")
ax2.grid(axis="y", alpha=0.3)

plt.tight_layout()
suffix = f"_{cli.site}_{cli.mode}"
output = Path(__file__).parent / "outputs" / f"backtest_result{suffix}.png"
output.parent.mkdir(exist_ok=True)
plt.savefig(output, dpi=150)
print(f"[OK] Graphique sauvegardé → {output}")
