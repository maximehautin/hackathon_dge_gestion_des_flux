"""Fréquentation de référence (§6) : éco-compteurs de parking des ENS.

Les séries sont mensuelles (2004-2016) : aucune ne couvre la date de la démo. La valeur
affichée est donc la **moyenne du même mois calendaire** sur les années disponibles,
ramenée à une demi-journée (÷ jours du mois ÷ 2). Elle est toujours présentée comme
« simulée », avec le compteur et la période source.
"""

from __future__ import annotations

import calendar
import datetime as dt
import re
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parent.parent
CANDIDATES = (REPO / "data" / "ssp", REPO.parent / "onyxia-data")
WORKBOOK = Path("Fréquentation") / "données_eco_compteurs_ENS.xlsx"
_DIVISER = re.compile(r"\(\s*à diviser par 2\s*\)", re.IGNORECASE)
_MOIS_FR = (
    "janvier",
    "février",
    "mars",
    "avril",
    "mai",
    "juin",
    "juillet",
    "août",
    "septembre",
    "octobre",
    "novembre",
    "décembre",
)
_ANNEE_REF = 2001  # année non bissextile : février compte 28 jours


@dataclass(frozen=True)
class Frequentation:
    valeur: float  # passages estimés par demi-journée
    compteur: str
    periode: str  # ex. "2009-2016"
    n_annees: int


def resolve_root(candidates: tuple[Path, ...] = CANDIDATES) -> Path:
    for c in candidates:
        if c.is_dir():
            return c
    raise FileNotFoundError("aucun dossier de données : " + " ou ".join(str(c) for c in candidates))


def _norm(name: str) -> str:
    return " ".join(_DIVISER.sub("", str(name)).split()).casefold()


def _month(v: object) -> int:
    if isinstance(v, dt.date):
        return v.month
    return _MOIS_FR.index(str(v).split()[0].casefold()) + 1


def load_series(xlsx: Path, compteurs: list[str]) -> dict[str, pd.DataFrame]:
    """Séries mensuelles (annee, mois, valeur) des compteurs demandés, « à diviser par 2 » appliqué."""
    df = pd.read_excel(xlsx)
    df = df[pd.to_numeric(df["Année"], errors="coerce").notna()]  # retire les lignes « Somme » / « Moyenne »
    by_norm = {_norm(c): c for c in df.columns}
    out = {}
    for compteur in compteurs:
        col = by_norm.get(_norm(compteur))
        if col is None:
            raise KeyError(f"compteur introuvable dans {xlsx.name} : {compteur!r}")
        valeur = pd.to_numeric(df[col], errors="coerce")
        if _DIVISER.search(str(col)):
            valeur = valeur / 2
        s = pd.DataFrame({"annee": df["Année"].astype(int), "mois": df["Mois"].map(_month), "valeur": valeur})
        out[compteur] = s.dropna(subset=["valeur"]).reset_index(drop=True)
    return out


def demi_journee_moyenne(serie: pd.DataFrame, compteur: str, mois: int) -> Frequentation | None:
    """Moyenne du mois calendaire sur les années disponibles, ramenée à une demi-journée."""
    m = serie[serie["mois"] == mois]
    if m.empty:
        return None
    jours = calendar.monthrange(_ANNEE_REF, mois)[1]
    return Frequentation(
        valeur=float(m["valeur"].mean()) / jours / 2,
        compteur=compteur,
        periode=f"{m['annee'].min()}-{m['annee'].max()}",
        n_annees=int(m["annee"].nunique()),
    )


def frequentations(compteurs: dict[str, str], mois: int, root: Path | None = None) -> dict[str, Frequentation | None]:
    """{borne_id: Frequentation} pour un mois calendaire ; `compteurs` = {borne_id: nom du compteur}."""
    xlsx = (root or resolve_root()) / WORKBOOK
    series = load_series(xlsx, list(compteurs.values()))
    return {bid: demi_journee_moyenne(series[c], c, mois) for bid, c in compteurs.items()}
