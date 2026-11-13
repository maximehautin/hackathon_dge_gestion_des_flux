"""Relais serveur des appels Apidae et Géovélo utilisés par Marguerite."""
from __future__ import annotations

import json
import math
import re
from collections import OrderedDict
from copy import deepcopy
from threading import RLock
from time import monotonic

import requests

from . import config as C

SELECTIONS = frozenset({211891, 211999, 211884, 211908, 211890})
PROJET_ID = 9657
APIDAE_URL = "https://api.apidae-tourisme.com/api/v002/recherche/list-objets-touristiques/"
RESPONSE_FIELDS = [
    "id",
    "nom",
    "type",
    "localisation.adresse.commune",
    "localisation.geolocalisation.geoJson",
    "localisation.geolocalisation.altitude",
    "presentation.descriptifCourt",
    "ouverture.periodeEnClair",
    "illustrations",
]
_CACHE_TTL = 3600
_CACHE_SIZE = 256
_CACHE: OrderedDict[tuple, tuple[float, dict]] = OrderedDict()
_CACHE_LOCK = RLock()
_AV = re.compile(r"parapente|via ferrata|escalade|canyon|ski nautique|wake|luge|accrobranche|chiens polaires|spéléo|rafting|tyrolienne|grotte", re.I)
_SP = re.compile(r"vtt|vélo|cheval|équ|randonn|trek|trail|marche|raquette|course|bivouac|sommet|golf|piscine|baignade", re.I)
_CU = re.compile(r"musée|visite|découverte|forge|patrimoine|histoire|château|atelier|faune|mammif|marmotte|balade|abbaye|église", re.I)
_GAS = re.compile(r"ferme|fromag|chocolat|boulang|pâtiss|patiss|café|bar\b|salon de thé|miel|cave|producteur|brasserie|glac|fournil|tisan|confiserie|gourmand|cellier|douceur|boucherie|noix|liqueur|distiller", re.I)
_NOGAS = re.compile(r"spar|casino|tabac|biocoop|vie claire|eau vive|intercaves|carrefour|intermarché|leclerc|presse|pharmacie", re.I)
_DROP = re.compile(r"^(randonnée.*|marche.*|iaïdo|rando alpine.*)$|leçons|stage d'équitation|cours |fermé", re.I)
_POI_SELECTIONS = [211891, 211999, 211884]


def _point(lat: float, lon: float) -> tuple[float, float]:
    try:
        lat, lon = float(lat), float(lon)
    except (TypeError, ValueError):
        raise ValueError("Coordonnées hors de la zone autorisée.") from None
    if not math.isfinite(lat) or not math.isfinite(lon) or not (44.5 <= lat <= 46.0 and 4.5 <= lon <= 6.6):
        raise ValueError("Coordonnées hors de la zone autorisée.")
    return lat, lon


def _cache_get(key: tuple) -> dict | None:
    with _CACHE_LOCK:
        entry = _CACHE.get(key)
        if entry is None:
            return None
        expires, value = entry
        if expires <= monotonic():
            del _CACHE[key]
            return None
        _CACHE.move_to_end(key)
        return deepcopy(value)


def _cache_put(key: tuple, value: dict) -> None:
    with _CACHE_LOCK:
        _CACHE[key] = (monotonic() + _CACHE_TTL, deepcopy(value))
        _CACHE.move_to_end(key)
        while len(_CACHE) > _CACHE_SIZE:
            _CACHE.popitem(last=False)


def apidae_search(
    selection_ids: list[int],
    lat: float,
    lon: float,
    radius_km: float,
    count: int,
    first: int,
) -> dict:
    if not isinstance(selection_ids, list) or not selection_ids or any(
        type(selection_id) is not int or selection_id not in SELECTIONS
        for selection_id in selection_ids
    ):
        raise ValueError("Sélection Apidae non autorisée.")
    lat, lon = _point(lat, lon)
    try:
        radius_km = float(radius_km)
    except (TypeError, ValueError):
        raise ValueError("Le rayon doit être supérieur à 0 et inférieur ou égal à 20 km.") from None
    if not math.isfinite(radius_km) or not 0 < radius_km <= 20:
        raise ValueError("Le rayon doit être supérieur à 0 et inférieur ou égal à 20 km.")
    if type(count) is not int or not 1 <= count <= 200:
        raise ValueError("count doit être compris entre 1 et 200.")
    if type(first) is not int or not 0 <= first <= 1000:
        raise ValueError("first doit être compris entre 0 et 1000.")

    radius_m = round(radius_km * 1000)
    lat, lon = round(lat, 6), round(lon, 6)
    cache_key = (tuple(sorted(set(selection_ids))), lat, lon, radius_m, count, first)
    key = C.secret("APIDAE_API_KEY")
    if not key:
        raise RuntimeError("Clé Apidae indisponible.")
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    query = {
        "projetId": PROJET_ID,
        "apiKey": key,
        "selectionIds": selection_ids,
        "center": {"type": "Point", "coordinates": [lon, lat]},
        "radius": radius_m,
        "count": count,
        "first": first,
        "locales": ["fr"],
        "responseFields": RESPONSE_FIELDS,
    }
    try:
        response = requests.get(
            APIDAE_URL,
            params={"query": json.dumps(query, ensure_ascii=False, separators=(",", ":"))},
            timeout=30,
        )
    except requests.RequestException:
        raise RuntimeError("L'API Apidae est indisponible.") from None
    if response.status_code != 200:
        raise RuntimeError(f"L'API Apidae a répondu HTTP {response.status_code}.")
    try:
        data = response.json()
    except ValueError:
        raise RuntimeError("Réponse Apidae invalide.") from None
    if not isinstance(data, dict):
        raise RuntimeError("Réponse Apidae invalide.")
    result = {
        "numFound": data.get("numFound", 0),
        "objetsTouristiques": data.get("objetsTouristiques", []),
    }
    if not isinstance(result["objetsTouristiques"], list):
        raise RuntimeError("Réponse Apidae invalide.")
    _cache_put(cache_key, result)
    return deepcopy(result)


def geovelo_route(
    points: list[tuple[float, float]],
    velo: str,
    profil: str = "MEDIAN",
    instructions: bool = False,
) -> list:
    if not isinstance(points, list) or not 2 <= len(points) <= 6:
        raise ValueError("Un itinéraire doit comporter entre 2 et 6 points.")
    if velo not in {"classique", "vae"}:
        raise ValueError("Le vélo doit être classique ou vae.")
    if profil not in {"MEDIAN", "RIDE"}:
        raise ValueError("Le profil doit être MEDIAN ou RIDE.")
    if type(instructions) is not bool:
        raise ValueError("instructions doit être un booléen.")
    normalized = [_point(lat, lon) for lat, lon in points]
    key = C.secret("GEOVELO_API_KEY")
    if not key:
        raise RuntimeError("Clé Géovélo indisponible.")
    electric = velo == "vae"
    body = {
        "waypoints": [
            {"latitude": lat, "longitude": lon} for lat, lon in normalized
        ],
        "bikeDetails": {
            "profile": profil,
            "bikeType": "ELECTRIC" if electric else "TRADITIONAL",
            "averageSpeed": 20 if electric else 15,
        },
        "transportModes": ["BIKE"],
    }
    try:
        response = requests.post(
            C.GEOVELO_URL,
            params={
                "geometry": "true",
                "single_result": "true",
                "elevations": "false",
                "instructions": "true" if instructions else "false",
            },
            headers={"Api-Key": key, "Source": "flux-isere", "Content-Type": "application/json"},
            json=body,
            timeout=60,
        )
    except requests.RequestException:
        raise RuntimeError("L'API Géovélo est indisponible.") from None
    if response.status_code != 200:
        raise RuntimeError(f"L'API Géovélo a répondu HTTP {response.status_code}.")
    try:
        result = response.json()
    except ValueError:
        raise RuntimeError("Réponse Géovélo invalide.") from None
    if not isinstance(result, list):
        raise RuntimeError("Réponse Géovélo invalide.")
    return result


def geovelo_loop(points: list[tuple[float, float]], velo: str) -> list:
    if not isinstance(points, list) or not 3 <= len(points) <= 6:
        raise ValueError("Une boucle doit comporter entre 3 et 6 points.")
    return geovelo_route(points, velo)


def _nested(value, *keys):
    for key in keys:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def to_poi(obj: dict) -> dict | None:
    coordinates = _nested(obj, "localisation", "geolocalisation", "geoJson", "coordinates")
    if not isinstance(coordinates, (list, tuple)) or len(coordinates) < 2:
        return None
    nom = _nested(obj, "nom", "libelleFr") or "Sans nom"
    if not isinstance(nom, str):
        nom = str(nom)
    if _DROP.search(nom):
        return None

    category = obj.get("type")
    if category == "PATRIMOINE_NATUREL":
        cat = "nature"
    elif category == "PATRIMOINE_CULTUREL":
        cat = "culture"
    elif category == "EQUIPEMENT":
        cat = "aventure" if _AV.search(nom) else "culture"
    elif category == "COMMERCE_ET_SERVICE":
        if not _GAS.search(nom) or _NOGAS.search(nom):
            return None
        cat = "gastronomie"
    else:
        cat = "aventure" if _AV.search(nom) else "sportif" if _SP.search(nom) else "culture" if _CU.search(nom) else "sportif"

    illustrations = obj.get("illustrations") or []
    illustration = next(
        (item for item in illustrations if isinstance(item, dict) and item.get("type") == "IMAGE"),
        None,
    )
    files = (illustration or {}).get("traductionFichiers") or []
    image = files[0] if files and isinstance(files[0], dict) else {}
    return {
        "id": obj.get("id"),
        "nom": nom,
        "cat": cat,
        "commune": _nested(obj, "localisation", "adresse", "commune", "nom") or "",
        "lat": coordinates[1],
        "lon": coordinates[0],
        "desc": _nested(obj, "presentation", "descriptifCourt", "libelleFr") or "",
        "ouv": _nested(obj, "ouverture", "periodeEnClair", "libelleFr") or "",
        "img": image.get("urlDiaporama") or image.get("url"),
        "credit": _nested(illustration, "copyright", "libelleFr"),
        "alt": _nested(obj, "localisation", "geolocalisation", "altitude"),
    }


def zone(lat: float, lon: float) -> dict:
    lat, lon = _point(lat, lon)
    first = apidae_search(_POI_SELECTIONS, lat, lon, 17, 200, 0)
    second = apidae_search(_POI_SELECTIONS, lat, lon, 17, 200, 200)
    shops = apidae_search([211908], lat, lon, 17, 200, 0)

    pois = []
    seen = set()
    for obj in first["objetsTouristiques"] + second["objetsTouristiques"]:
        poi = to_poi(obj)
        if poi is None:
            continue
        key = (round(float(poi["lat"]), 4), round(float(poi["lon"]), 4))
        if key not in seen:
            seen.add(key)
            pois.append(poi)
    gas = [poi for obj in shops["objetsTouristiques"] if (poi := to_poi(obj)) is not None]
    return {"pois": pois, "gas": gas}


def zone_v2(lat: float, lon: float) -> dict:
    lat, lon = _point(lat, lon)
    catalogue_path = C.ROOT / "web" / "src" / "catalogue.json"
    catalogue = json.loads(catalogue_path.read_text(encoding="utf-8"))
    pois, gas = [], []
    for row in catalogue.get("pois", []):
        if not isinstance(row, list) or len(row) < 12:
            continue
        try:
            poi_lat, poi_lon = float(row[4]), float(row[5])
        except (TypeError, ValueError):
            continue
        dlat = math.radians(poi_lat - lat)
        dlon = math.radians(poi_lon - lon)
        a = (
            math.sin(dlat / 2) ** 2
            + math.cos(math.radians(lat))
            * math.cos(math.radians(poi_lat))
            * math.sin(dlon / 2) ** 2
        )
        distance = 6371 * 2 * math.asin(math.sqrt(min(1, max(0, a))))
        if distance > 17:
            continue
        image = row[7]
        poi = {
            "id": row[0],
            "nom": row[1],
            "cat": row[2],
            "commune": row[3] or "",
            "lat": poi_lat,
            "lon": poi_lon,
            "alt": row[6],
            "img": (
                "https://static.apidae-tourisme.com/filestore/objets-touristiques/images/"
                f"{image}-diaporama.jpg"
                if image
                else None
            ),
            "credit": row[8] or None,
            "t0": row[9],
            "desc": row[10] or "",
            "ouv": row[11] or "",
        }
        (gas if poi["cat"] == "gastronomie" else pois).append(poi)
    return {"pois": pois, "gas": gas}


def flux_t(row: dict | None) -> float | None:
    saturation = row.get("indice_saturation") if isinstance(row, dict) else None
    try:
        saturation_value = float(saturation) if saturation is not None else math.nan
    except (TypeError, ValueError):
        saturation_value = math.nan
    if saturation is not None and math.isfinite(saturation_value):
        if saturation_value <= 0.3:
            value = 1.5 * saturation_value
        elif saturation_value <= 0.8:
            value = 0.45 + 0.6 * (saturation_value - 0.3)
        else:
            value = min(1, 0.75 + 1.25 * (saturation_value - 0.8))
    else:
        habit = row.get("indice_habitude") if isinstance(row, dict) else None
        try:
            habit_value = float(habit) if habit is not None else math.nan
        except (TypeError, ValueError):
            habit_value = math.nan
        if habit is None or not math.isfinite(habit_value) or habit_value <= 0:
            return None
        value = 0.6 + 0.15 * math.log(habit_value) / math.log(1.5)
    return max(0, min(1, value))
