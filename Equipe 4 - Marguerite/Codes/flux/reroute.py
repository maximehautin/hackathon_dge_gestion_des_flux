"""M4 Réorientation : vers quel site à expérience proche renvoyer les visiteurs d'un site saturé.

Candidats : lieux conseillés par les offices de tourisme (itinéraire bis), sites ENS
instrumentés (dont on connaît la prévision et le niveau de pression), objets
DataTourisme de nature et de loisirs. Score = recommandation OT + similarité
d'expérience (mots-clés : lac, cascade, sommet, rando, vélo, famille, culture)
+ proximité (10 à 45 km) + calme prévu (M3/M2) + accessibilité douce (M5).
"""
from __future__ import annotations

import json
from datetime import date

import numpy as np
import pandas as pd

from . import config as C
from .data import experience_tags, haversine_km, load_overvisited, load_pois, load_ens_daily
from .pressure import level

W_OT, W_SIM, W_DIST, W_CALM, W_ACCESS = 3.0, 2.0, 1.5, 1.5, 0.5
MAX_KM = 45


def _norm(s: str) -> str:
    import unicodedata
    s = unicodedata.normalize("NFKD", s.lower())
    return "".join(c for c in s if not unicodedata.combining(c)).strip()


def _ot_match(name: str, bis: set[str]) -> float:
    """1 si le nom correspond à un itinéraire bis conseillé (tolérance aux pluriels et variantes d'écriture)."""
    from difflib import SequenceMatcher
    for b in bis:
        if name == b or name in b or b in name or SequenceMatcher(None, name, b).ratio() >= 0.85:
            return 1.0
    return 0.0


def counter_status(ens_sites: pd.DataFrame, site_id: int, day: date) -> str:
    """Statut d'un compteur ENS au jour consulté."""
    hit = ens_sites[ens_sites["site_id"] == int(site_id)]
    if hit.empty:
        return "ok"
    site = hit.iloc[0]
    if pd.Timestamp(day) <= site["last_date"]:
        return "ok"
    if site.get("en_panne", False):
        return "en panne"
    if pd.Timestamp(day) - site["last_date"] > pd.Timedelta(days=C.STALE_DAYS):
        return "données anciennes"
    return "ok"


class Rerouter:
    def __init__(self, forecaster=None, thresholds: dict | None = None, typology: list[dict] | None = None, access: pd.DataFrame | None = None):
        self.ov, self.alt = load_overvisited()
        self.pois = load_pois()
        _, self.ens_sites = load_ens_daily()
        self.forecaster = forecaster
        self.th = {int(k): v for k, v in (thresholds or {}).items()}
        self.typo = {t["site_id"]: t["famille"] for t in (typology or [])}
        self.access = access.set_index("site_key") if access is not None else None
        self.ov["tags"] = [experience_tags(n, t) for n, t in zip(self.ov["name"], self.ov["type"])]
        self.alt["tags"] = [experience_tags(n, t) for n, t in zip(self.alt["name"], self.alt["type"])]
        self.ens_sites["tags"] = [experience_tags(n, "randonnée") for n in self.ens_sites["site_name"]]
        self.ens_sites["site_key"] = "ens_" + self.ens_sites["site_id"].astype(str)

    # ---- catalogue unifié de candidats
    def candidates(self) -> pd.DataFrame:
        a = self.alt.assign(source="office de tourisme", site_id=np.nan)[["site_key", "name", "commune", "lat", "lon", "tags", "source", "site_id"]]
        e = self.ens_sites.assign(source="espace naturel sensible (compteur)", commune="")[["site_key", "site_name", "commune", "lat", "lon", "tags", "source", "site_id"]].rename(columns={"site_name": "name"})
        p = self.pois.assign(source="DataTourisme", site_id=np.nan)[["site_key", "name", "commune", "lat", "lon", "tags", "source", "site_id"]]
        p = p[p["tags"].map(lambda t: t != {"autre"})]
        return pd.concat([a, e, p], ignore_index=True)

    def site_pressure(self, site_id: int, day: date) -> dict:
        """Niveau prévu (M3 + seuils M2) pour un site ENS un jour donné (mémorisé par site et jour)."""
        if self.forecaster is None or int(site_id) not in self.forecaster.cats:
            return {"level": "inconnu"}
        cache = self.__dict__.setdefault("_pressure_cache", {})
        k = (int(site_id), day)
        if k not in cache:
            cache[k] = self._site_pressure(site_id, day)
        return cache[k]

    def counter_status(self, site_id: int, day: date) -> str:
        """« ok », « données anciennes » (prévision sans relevé récent) ou « en panne » (série finie par des zéros)."""
        return counter_status(self.ens_sites, site_id, day)

    def _site_pressure(self, site_id: int, day: date) -> dict:
        statut = self.counter_status(site_id, day)
        if statut == "en panne":
            return {"level": "inconnu", "statut": statut}
        try:
            f = self.forecaster.predict(int(site_id), start=day, days=1).iloc[0]
        except Exception:
            return {"level": "inconnu", "statut": statut}
        th = self.th.get(int(site_id))
        return {"level": level(float(f["pred"]), th), "pred": round(float(f["pred"])), "p80": th and round(th["p80"]), "p95": th and round(th["p95"]), "statut": statut}

    def alternatives(self, site_key: str, day: date | None = None, top: int = 5, profile_tags: set[str] | None = None) -> dict:
        day = day or date.today()
        src = self._find(site_key)
        cands = self.candidates()
        cands = cands[cands["site_key"] != site_key].copy()
        cands["km"] = haversine_km(src["lat"], src["lon"], cands["lat"].to_numpy(), cands["lon"].to_numpy())
        bis = {_norm(x) for x in src.get("itineraire_bis", [])}
        cands["ot"] = cands["name"].map(lambda n: _ot_match(_norm(n), bis))
        # les itinéraires bis des OT sont gardés quelle que soit la distance ; les autres entre 3 et MAX_KM km
        cands = cands[(cands["ot"] > 0) | ((cands["km"] >= 3) & (cands["km"] <= MAX_KM))].copy()
        if cands.empty:
            return {"source": src, "alternatives": []}
        want = set(src["tags"]) | (profile_tags or set())
        cands["sim"] = cands["tags"].map(lambda t: len(t & want) / max(len(t | want), 1))
        cands["dist_score"] = (1 - (cands["km"] - 3) / (MAX_KM - 3)).clip(0, 1)
        # pression prévue : seulement pour les sites instrumentés ; les autres sont neutres
        press = [self.site_pressure(sid, day) if not pd.isna(sid) else {"level": "inconnu"} for sid in cands["site_id"]]
        calm_map = {"calme": 1.0, "normal": 0.6, "inconnu": 0.3, "soutenu": -0.5, "saturé": -2.0}
        # sans relevé récent, une prévision « calme » n'est pas assez sûre pour être un argument
        cands["calm"] = [min(calm_map[p["level"]], calm_map["inconnu"]) if p.get("statut") == "données anciennes" else calm_map[p["level"]] for p in press]
        cands["pression"] = press
        if self.access is not None:
            acc = cands["site_key"].map(lambda k: self.access["acces_doux"].get(k, None))
            cands["access"] = acc.map({"bon": 1.0, "moyen": 0.5, "faible": 0.0}).fillna(0.3)
        else:
            cands["access"] = 0.3
        cands["score"] = (W_OT * cands["ot"] + W_SIM * cands["sim"] + W_DIST * cands["dist_score"] + W_CALM * cands["calm"] + W_ACCESS * cands["access"]).round(2)
        cands = cands[(cands["ot"] > 0) | (cands["sim"] > 0)].sort_values("score", ascending=False).head(top)

        out = []
        for r in cands.itertuples():
            out.append({
                "site_key": r.site_key, "name": r.name, "commune": r.commune, "lat": r.lat, "lon": r.lon,
                "km": round(float(r.km), 1), "source": r.source, "tags": sorted(r.tags), "score": float(r.score),
                "pression": r.pression, "famille": self.typo.get(int(r.site_id)) if not pd.isna(r.site_id) else None,
                "acces_doux": self.access["acces_doux"].get(r.site_key) if self.access is not None else None,
                "raison": self._explain(src, r),
            })
        return {"source": {k: (sorted(v) if isinstance(v, set) else v) for k, v in src.items()}, "date": str(day), "alternatives": out}

    def _find(self, site_key: str) -> dict:
        for df in (self.ov, self.alt, self.ens_sites.rename(columns={"site_name": "name"})):
            hit = df[df["site_key"] == site_key]
            if len(hit):
                d = hit.iloc[0].to_dict()
                d.setdefault("itineraire_bis", [])
                return d
        raise KeyError(site_key)

    @staticmethod
    def _explain(src: dict, r) -> str:
        parts = []
        if r.ot:
            parts.append("itinéraire bis conseillé par l'office de tourisme")
        common = sorted(set(src["tags"]) & r.tags - {"autre"})
        if common:
            parts.append("même type d'expérience (" + ", ".join(common) + ")")
        parts.append(f"à {r.km:.0f} km")
        lvl = r.pression.get("level")
        if lvl in ("soutenu", "saturé"):
            parts.append(f"attention, fréquentation prévue {lvl}")
        elif r.pression.get("statut") == "données anciennes":
            parts.append("pas de relevé récent du compteur, prévision indicative")
        elif lvl in ("calme", "normal"):
            parts.append(f"fréquentation prévue {lvl} ({r.pression.get('pred')} passages, seuil d'alerte {r.pression.get('p95')})")
        return " ; ".join(parts)
