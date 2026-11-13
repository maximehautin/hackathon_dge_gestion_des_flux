"""Chargement des bornes de démo depuis `bornes.yaml` (paramètres, pas logique)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

DEFAULT_PATH = Path(__file__).resolve().parent / "bornes.yaml"


@dataclass(frozen=True)
class Borne:
    id: str
    name: str
    id_ens: str
    commune: str
    code_insee: str
    compteur: str  # nom de la colonne éco-compteur de référence (§6)
    lat: float
    lon: float


@dataclass(frozen=True)
class Territoire:
    departement: str
    bornes: dict[str, Borne]


def load(path: Path = DEFAULT_PATH) -> Territoire:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    bornes = {}
    for b in raw["bornes"]:
        borne = Borne(
            id=b["id"],
            name=b["name"],
            id_ens=b["id_ens"],
            commune=b["commune"],
            code_insee=str(b["code_insee"]),
            compteur=b["compteur"],
            lat=float(b["lat"]),
            lon=float(b["lon"]),
        )
        if borne.id in bornes:
            raise ValueError(f"borne en double dans {path} : {borne.id}")
        bornes[borne.id] = borne
    return Territoire(departement=raw["departement"], bornes=bornes)
