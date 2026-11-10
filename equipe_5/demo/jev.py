"""Client HTTP de l'API Decisions d'OpenRouter (Jev, TypeSafe). Effets de bord isolés ici.

Un seul appel `POST /api/alpha/decisions` par avis, toutes les questions groupées dans
`questions` (format de la doc OpenRouter, à confirmer au jour 1 par un appel réel).
"""

from __future__ import annotations

import os
from typing import Any

import httpx

ENDPOINT = os.environ.get("JEV_ENDPOINT", "https://openrouter.ai/api/alpha/decisions")
MODEL = os.environ.get("JEV_MODEL", "typesafe/jev-1.14")  # épinglé, pas d'alias `latest`
TIMEOUT_S = float(os.environ.get("JEV_TIMEOUT_S", "20"))
HTTP_OK = 200


class JevError(RuntimeError):
    pass


def build_request(transcript: str, questions: dict[str, Any], borne: str, langue: str | None) -> dict[str, Any]:
    return {
        "model": MODEL,
        "state": {
            "contexte": "Recueil du ressenti d'un randonneur, qui parle librement à une borne au départ "
            "d'une randonnée dans un espace naturel sensible. Le texte est une transcription automatique de "
            "sa parole : elle peut être de mauvaise qualité, avec des mots mal reconnus ou des termes "
            "hallucinés sans rapport avec le reste. Ne retiens que ce que le visiteur exprime clairement.",
            "borne": borne,
            "langue": langue or "inconnue",
            "transcription": transcript,
        },
        "questions": questions,
    }


def decide(body: dict[str, Any], client: httpx.Client | None = None) -> dict[str, Any]:
    """Envoie la requête ; renvoie la réponse JSON brute. Lève `JevError` en cas d'échec."""
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        raise JevError("OPENROUTER_API_KEY non définie")
    own = client is None
    client = client or httpx.Client(timeout=TIMEOUT_S)
    try:
        r = client.post(ENDPOINT, json=body, headers={"Authorization": f"Bearer {key}"})
    except httpx.HTTPError as e:
        raise JevError(f"réseau : {e}") from e
    finally:
        if own:
            client.close()
    if r.status_code != HTTP_OK:
        raise JevError(f"HTTP {r.status_code} : {r.text[:300]}")
    try:
        raw = r.json()
    except ValueError as e:
        raise JevError(f"réponse non JSON : {r.text[:300]}") from e
    if not isinstance(raw, dict) or not isinstance(raw.get("answers"), dict):
        raise JevError(f"réponse inattendue : {r.text[:300]}")
    return raw
