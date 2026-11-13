#!/usr/bin/env python3
"""Collecte les POI et construit leur index de recherche sémantique."""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from flux import config as C  # noqa: E402
from flux.poi import APIDAE_SELECTIONS, build_index  # noqa: E402

APIDAE_URL = "https://api.apidae-tourisme.com/api/v002/recherche/list-objets-touristiques/"
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
OVERPASS_QUERY = (
    '[out:json][timeout:180];area["ref:INSEE"="38"]["admin_level"="6"]->.a;'
    '(nwr["tourism"~"^(attraction|viewpoint|museum|artwork|picnic_site|camp_site|alpine_hut|wilderness_hut|zoo|theme_park|gallery)$"]["name"](area.a);'
    'nwr["natural"~"^(peak|waterfall|cave_entrance|glacier)$"]["name"](area.a);'
    'nwr["historic"]["name"](area.a);'
    'nwr["leisure"~"^(nature_reserve|water_park|swimming_area)$"]["name"](area.a););out center tags;'
)
OVERPASS_HEADERS = {
    "User-Agent": "flux-isere-hackathon/1.0 (contact antoineblr16@gmail.com)",
    "Content-Type": "text/plain; charset=utf-8",
}
POI_DATA_DIR = ROOT / "data" / "poi"


def _raw_objects(payload: dict) -> list[dict]:
    objects = payload.get("objetsTouristiques", [])
    return objects if isinstance(objects, list) else []


def _has_apidae_coordinates(obj: dict) -> bool:
    coordinates = (
        obj.get("localisation", {})
        .get("geolocalisation", {})
        .get("geoJson", {})
        .get("coordinates")
    )
    return (
        isinstance(coordinates, (list, tuple))
        and len(coordinates) >= 2
        and _valid_coordinates(coordinates[0], coordinates[1])
    )


def _valid_coordinates(lon: object, lat: object) -> bool:
    try:
        lon_value, lat_value = float(lon), float(lat)
    except (TypeError, ValueError):
        return False
    return -180 <= lon_value <= 180 and -90 <= lat_value <= 90


def _has_osm_coordinates(element: dict) -> bool:
    if "lat" in element and "lon" in element:
        return _valid_coordinates(element["lon"], element["lat"])
    center = element.get("center")
    return isinstance(center, dict) and _valid_coordinates(center.get("lon"), center.get("lat"))


def _apidae_request(session: requests.Session, selection_id: int, key: str, offset: int) -> dict:
    query = {
        "projetId": 9657,
        "apiKey": key,
        "selectionIds": [selection_id],
        "count": 200,
        "first": offset,
        "responseFields": ["@all"],
        "locales": ["fr"],
    }
    try:
        response = session.get(APIDAE_URL, params={"query": json.dumps(query)}, timeout=90)
    except requests.RequestException as error:
        raise RuntimeError(f"Apidae selection {selection_id}: réseau indisponible ({type(error).__name__})") from None
    if response.status_code != 200:
        raise RuntimeError(f"Apidae selection {selection_id}: HTTP {response.status_code}")
    try:
        payload = response.json()
    except ValueError:
        raise RuntimeError(f"Apidae selection {selection_id}: réponse JSON invalide") from None
    if not isinstance(payload, dict):
        raise RuntimeError(f"Apidae selection {selection_id}: format de réponse invalide")
    return payload


def _collect_apidae(session: requests.Session, key: str) -> None:
    target_dir = POI_DATA_DIR / "apidae"
    target_dir.mkdir(parents=True, exist_ok=True)
    for selection_id, category in APIDAE_SELECTIONS.items():
        pages = []
        offset = 0
        total = None
        while total is None or offset < total:
            payload = _apidae_request(session, selection_id, key, offset)
            pages.append(payload)
            objects = _raw_objects(payload)
            total = int(payload.get("numFound", offset + len(objects)))
            if not objects:
                break
            offset += len(objects)

        raw_count = sum(len(_raw_objects(page)) for page in pages)
        skipped_coordinates = sum(
            1
            for page in pages
            for obj in _raw_objects(page)
            if not _has_apidae_coordinates(obj)
        )
        payload = {
            "selection_id": selection_id,
            "category": category,
            "num_found": total,
            "responses": pages,
        }
        destination = target_dir / f"{selection_id}.json"
        partial = destination.with_suffix(".json.part")
        partial.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        partial.replace(destination)
        print(
            f"Apidae {selection_id} ({category}): "
            f"{raw_count} objets, {skipped_coordinates} sans coordonnées"
        )


def _collect_osm(session: requests.Session) -> None:
    destination = POI_DATA_DIR / "osm.json"
    POI_DATA_DIR.mkdir(parents=True, exist_ok=True)
    delays = (30, 60, 120, 240)
    for attempt in range(len(delays) + 1):
        try:
            response = session.post(
                OVERPASS_URL,
                data=OVERPASS_QUERY,
                headers=OVERPASS_HEADERS,
                timeout=240,
            )
        except requests.RequestException as error:
            if attempt >= len(delays):
                raise RuntimeError(f"Overpass indisponible ({type(error).__name__})") from None
            delay = delays[attempt]
            print(f"Overpass réseau indisponible, nouvel essai dans {delay}s ({attempt + 1}/{len(delays)})")
            time.sleep(delay)
            continue

        if response.status_code in (429, 502, 503, 504):
            if attempt >= len(delays):
                raise RuntimeError(f"Overpass HTTP {response.status_code} après plusieurs essais")
            delay = delays[attempt]
            print(f"Overpass HTTP {response.status_code}, nouvel essai dans {delay}s ({attempt + 1}/{len(delays)})")
            time.sleep(delay)
            continue
        if response.status_code != 200:
            raise RuntimeError(f"Overpass HTTP {response.status_code}")
        try:
            payload = response.json()
        except ValueError:
            raise RuntimeError("Overpass a retourné une réponse JSON invalide") from None
        if not isinstance(payload, dict):
            raise RuntimeError("Format de réponse Overpass invalide")

        elements = payload.get("elements", [])
        skipped = sum(1 for element in elements if not _has_osm_coordinates(element))
        partial = destination.with_suffix(".json.part")
        partial.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        partial.replace(destination)
        print(f"OSM: {len(elements)} éléments bruts, {skipped} sans coordonnées")
        return


def collect() -> None:
    key = C.secret("APIDAE_API_KEY")
    if not key:
        raise RuntimeError(
            "APIDAE_API_KEY absent : définir la variable d'environnement ou vérifier "
            "l'onglet Codes de FLUX_DATA_DIR."
        )
    with requests.Session() as session:
        _collect_apidae(session, key)
        _collect_osm(session)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("collect", "index"))
    args = parser.parse_args()
    try:
        if args.action == "collect":
            collect()
        else:
            build_index()
    except Exception as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
