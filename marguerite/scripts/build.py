"""Construit les artefacts utilisés par Marguerite : prévision ENS, fréquentation des POI, profils horaires.

Usage : FLUX_DATA_DIR=/chemin/vers/diffusion python scripts/build.py
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flux import forecast, frequentation, horaires  # noqa: E402
from flux.data import load_ens_daily  # noqa: E402

t = time.time()
daily, sites = load_ens_daily(force=True)
print(f"[1/4] éco-compteurs ENS : {len(daily)} jours-sites, {len(sites)} sites ({time.time()-t:.0f}s)")
m = forecast.train_and_evaluate()
print(f"[2/4] prévision ENS : {m['n_sites']} sites, MAE {m['mae']:.0f} vs référence {m['mae_baseline']:.0f} (gain {m['gain_pct']:.0f} %) ({time.time()-t:.0f}s)")
fr = frequentation.build()
print(f"[3/4] fréquentation POI : {fr['series_entrainees_par_source']} séries entraînées, {len(fr['routes_zone'])} références routières ({time.time()-t:.0f}s)")
hr = horaires.build()
print(f"[4/4] profils horaires : {hr['series_ens']} séries ENS, {hr['series_routes']} routes ({time.time()-t:.0f}s)")
print("artefacts écrits dans", forecast.C.ARTIFACTS)
