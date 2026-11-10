"""Pur : questions Jev ↔ colonnes de `inference_avis`, réponse Jev → valeurs, seuil de confiance.

Règle « missing data » (§4 et revue de #18), sur toutes les colonnes → NULL si :

- score : la question `noul` associée (`<colonne>_present`) dit que l'information n'est
  pas dans la transcription (probabilité < 0,5), ou est refusée ;
- choix : Jev répond la catégorie `missing` ;
- toutes : refus, valeur absente ou confiance < `SEUIL_CONFIANCE`. Si Jev ne renvoie pas de
  confiance pour une question, la valeur est gardée telle quelle (go/no-go §10).
"""

from __future__ import annotations

import os
from typing import Any

SEUIL_CONFIANCE = float(os.environ.get("SEUIL_CONFIANCE", "0.4"))  # à fixer au jour 1 sur des avis réels

SCORE_COLUMNS = ("satisfaction", "affluence")
CHOICE_OPTIONS: dict[str, tuple[str, ...]] = {
    "provenance": ("departement", "hors_departement"),
    "transport": ("voiture", "transport_en_commun", "velo"),
    "profil": ("groupe_amis", "famille", "seul", "couple"),
}
COLUMNS = (*SCORE_COLUMNS, *CHOICE_OPTIONS)
MISSING = "aucune_information"
PRESENT_SUFFIX = "_present"  # question noul : l'information du score est-elle dans la transcription ?
NOUL_SEUIL = 0.5

_MISSING_TXT = (
    "La transcription ne contient aucune information pertinente sur le sujet, ou pas assez clairement pour trancher."
)

_EXPLICITE = f" Uniquement si le visiteur le dit explicitement ; sinon, réponds « {MISSING} »."


def _present(sujet: str) -> dict[str, Any]:
    return {
        "type": "noul",
        "instructions": f"La transcription contient-elle une indication sur {sujet} ?",
        "criteria": {
            "true": f"Le visiteur s'exprime, même brièvement, sur {sujet}.",
            "false": f"Rien dans la transcription ne renseigne sur {sujet}.",
        },
    }


def questions(departement: str) -> dict[str, dict[str, Any]]:
    """Les questions, envoyées en un seul appel : une par colonne, plus une `noul` de présence par score."""
    return {
        "satisfaction" + PRESENT_SUFFIX: _present("sa satisfaction ou son appréciation de la sortie"),
        "affluence" + PRESENT_SUFFIX: _present("le nombre de personnes croisées ou l'affluence sur le site"),
        "satisfaction": {
            "type": "score",
            "instructions": "Quelle satisfaction globale le visiteur exprime-t-il dans la conversation ?",
            "criteria": [
                "0 - Très insatisfait",
                "25 - Plutôt insatisfait",
                "50 - Mitigé ou neutre",
                "75 - Plutôt satisfait",
                "100 - Très satisfait",
            ],
        },
        "affluence": {
            "type": "score",
            "instructions": "Quelle affluence le visiteur a-t-il ressentie sur le site (monde, parking, sentier) ?",
            "criteria": [
                "0 - Personne, site désert",
                "25 - Peu de monde, calme",
                "50 - Fréquentation normale",
                "75 - Beaucoup de monde",
                "100 - Beaucoup trop de monde, saturation",
            ],
        },
        "provenance": {
            "type": "choice",
            "instructions": (
                f"Le visiteur habite-t-il vraisemblablement dans le coin / le département"
                f"({departement}) ou bien en dehors (il vient de loin, en dehors de France, ou un autre département) ?"
                " Pour t'aider tu peux réfléchir en deux temps : 1/ est-ce qu'il y a une information"
                " sur un lieu géographique qui se rapporte à la résidence de l'interlocuteur ou des personnes dénigrées"
                " puis 2/ est-ce que ce lieu est dans la zone géographique autour du département"
                f" 3/ si la personne critique les gens pas du coin tu peux inférer qu'il est du coin." + _EXPLICITE
            ),
            "criteria": {
                "departement": f"Habite DANS le coin / le département ({departement}).",
                "hors_departement": (
                    f"Habite à l'étranger, ou alors en France mais HORS du coin / du département ({departement})."
                ),
                MISSING: _MISSING_TXT,
            },
        },
        "transport": {
            "type": "choice",
            "instructions": "Quel moyen de transport le visiteur a-t-il utilisé pour venir ?" + _EXPLICITE,
            "criteria": {
                "voiture": (
                    "Voiture, moto ou covoiturage.Exemple : « le parking est plein », « compliqué de se garer »."
                ),
                "transport_commun": (
                    "Bus, car, train ou navette. Exemple : « les horaires des bus ne sont pas pratiques »."
                ),
                "velo": (
                    "Vélo ou mobilité douce. Exemple : « pas pratique pour les vélos » ou « j'ai crevé sur la route »."
                ),
                MISSING: _MISSING_TXT,
            },
        },
        "profil": {
            "type": "choice",
            "instructions": "Avec qui le visiteur est-il venu ?" + _EXPLICITE,
            "criteria": {
                "groupe_amis": "Entre amis, en groupe.",
                "famille": "En famille, avec des enfants ou des proches.",
                "seul": "Seul.",
                "couple": "En couple, à deux.",
                MISSING: _MISSING_TXT,
            },
        },
    }


def _present_dans_texte(answer: dict[str, Any]) -> bool:
    return answer.get("type") == "noul" and isinstance(answer.get("noul"), int | float) and answer["noul"] >= NOUL_SEUIL


def _confiant(answer: dict[str, Any], seuil: float) -> bool:
    conf = answer.get("confidence")
    return conf is None or float(conf) >= seuil


def _score(answer: dict[str, Any], n_levels: int) -> float | None:
    """`score` est un index pondéré à partir de 0 sur `n_levels` niveaux → 0..100."""
    s = answer.get("score")
    if not isinstance(s, int | float):
        return None
    return min(100.0, max(0.0, float(s) / (n_levels - 1) * 100.0))


def parse(answers: dict[str, Any], departement: str, seuil: float = SEUIL_CONFIANCE) -> dict[str, Any]:
    """Réponse Jev (`answers`) → {colonne: valeur ou None}."""
    qs = questions(departement)
    out: dict[str, Any] = dict.fromkeys(COLUMNS)
    for col in SCORE_COLUMNS:
        a = answers.get(col) or {}
        present = _present_dans_texte(answers.get(col + PRESENT_SUFFIX) or {})
        if present and a.get("type") == "score" and _confiant(a, seuil):
            out[col] = _score(a, len(qs[col]["criteria"]))
    for col, options in CHOICE_OPTIONS.items():
        a = answers.get(col) or {}
        if a.get("type") == "choice" and a.get("choice") in options and _confiant(a, seuil):
            out[col] = a["choice"]
    return out
