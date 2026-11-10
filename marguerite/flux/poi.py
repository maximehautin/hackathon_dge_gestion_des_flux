"""Corpus Apidae / OpenStreetMap et recherche sémantique de POI."""
from __future__ import annotations

import json
import logging
import math
import re
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any

import numpy as np
import pandas as pd
import requests

from flux import config as C

MODEL_NAME = "intfloat/multilingual-e5-large-instruct"
QUERY_INSTRUCTION = "Étant donné une recherche de visiteur, trouver les lieux touristiques qui y correspondent"
EMBEDDING_DIMENSIONS = 1024
JEV_MODEL = "typesafe/jev-1.14"
JEV_URL = "https://openrouter.ai/api/alpha/decisions"
RERANK_POOL = 50
POI_DATA_DIR = C.ROOT / "data" / "poi"
POI_PATH = C.ARTIFACTS / "poi.parquet"
EMBEDDINGS_PATH = C.ARTIFACTS / "poi_embeddings.npy"
META_PATH = C.ARTIFACTS / "poi_meta.json"
EARTH_RADIUS_KM = 6371.0088
MAX_K = 50
_LOGGER = logging.getLogger(__name__)
_JEV_CACHE: dict[tuple[str, str, tuple[str, ...]], list[float]] = {}
_JEV_CACHE_LOCK = Lock()

APIDAE_SELECTIONS = {
    211884: "activite",
    211888: "ski-vtt",
    211890: "hebergement",
    211891: "nature",
    211905: "prestataire",
    211906: "service",
    211908: "commerce",
    211911: "randonnee",
    211914: "equipement",
    211999: "culture",
}

CATEGORY_LABELS = {
    "activite": "Activité",
    "ski-vtt": "Ski et VTT",
    "hebergement": "Hébergement",
    "nature": "Nature",
    "prestataire": "Prestataire touristique",
    "service": "Service touristique",
    "commerce": "Commerce",
    "randonnee": "Randonnée",
    "equipement": "Équipement",
    "culture": "Culture",
}

POI_COLUMNS = [
    "poi_id",
    "source",
    "nom",
    "categories",
    "tags",
    "commune",
    "lat",
    "lon",
    "description",
    "apidae_type",
    "osm_type",
    "osm_tags",
    "url",
]

OSM_LABELS = {
    ("tourism", "viewpoint"): "Point de vue",
    ("natural", "peak"): "Sommet",
    ("natural", "waterfall"): "Cascade",
    ("natural", "cave_entrance"): "Grotte",
    ("natural", "glacier"): "Glacier",
    ("tourism", "museum"): "Musée",
    ("tourism", "gallery"): "Galerie d'art",
    ("tourism", "artwork"): "Œuvre d'art",
    ("tourism", "alpine_hut"): "Refuge",
    ("tourism", "wilderness_hut"): "Cabane",
    ("tourism", "camp_site"): "Camping",
    ("tourism", "picnic_site"): "Aire de pique-nique",
    ("tourism", "zoo"): "Parc animalier",
    ("tourism", "theme_park"): "Parc de loisirs",
    ("tourism", "attraction"): "Attraction",
    ("leisure", "nature_reserve"): "Réserve naturelle",
    ("leisure", "water_park"): "Parc aquatique",
    ("leisure", "swimming_area"): "Baignade",
    ("historic", "castle"): "Château",
    ("historic", "ruins"): "Ruines",
    ("historic", "church"): "Église",
    ("historic", "chapel"): "Chapelle",
    ("historic", "monument"): "Monument / Mémorial",
    ("historic", "memorial"): "Monument / Mémorial",
    ("historic", "archaeological_site"): "Site archéologique",
}
OSM_CATEGORIES = {
    ("tourism", "attraction"): "activite",
    ("tourism", "viewpoint"): "nature",
    ("tourism", "museum"): "culture",
    ("tourism", "gallery"): "culture",
    ("tourism", "artwork"): "culture",
    ("tourism", "picnic_site"): "activite",
    ("tourism", "camp_site"): "hebergement",
    ("tourism", "alpine_hut"): "hebergement",
    ("tourism", "wilderness_hut"): "hebergement",
    ("tourism", "zoo"): "activite",
    ("tourism", "theme_park"): "activite",
    ("natural", "peak"): "nature",
    ("natural", "waterfall"): "nature",
    ("natural", "cave_entrance"): "nature",
    ("natural", "glacier"): "nature",
    ("historic", "*"): "culture",
    ("leisure", "nature_reserve"): "nature",
    ("leisure", "water_park"): "activite",
    ("leisure", "swimming_area"): "activite",
}


def _nested(value: Any, *keys: str) -> Any:
    for key in keys:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def _text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        for key in ("libelleFr", "nom", "libelle"):
            item = value.get(key)
            if isinstance(item, str) and item.strip():
                return item.strip()
    return ""


def _coordinates(lon: Any, lat: Any) -> tuple[float, float] | None:
    try:
        longitude, latitude = float(lon), float(lat)
    except (TypeError, ValueError):
        return None
    if (
        not math.isfinite(longitude)
        or not math.isfinite(latitude)
        or not -180 <= longitude <= 180
        or not -90 <= latitude <= 90
    ):
        return None
    return latitude, longitude


def _apidae_coordinates(obj: dict) -> tuple[float, float] | None:
    coordinates = _nested(
        obj,
        "localisation",
        "geolocalisation",
        "geoJson",
        "coordinates",
    )
    if not isinstance(coordinates, (list, tuple)) or len(coordinates) < 2:
        return None
    return _coordinates(coordinates[0], coordinates[1])


def _osm_coordinates(element: dict) -> tuple[float, float] | None:
    if "lat" in element and "lon" in element:
        return _coordinates(element.get("lon"), element.get("lat"))
    center = element.get("center")
    if isinstance(center, dict):
        return _coordinates(center.get("lon"), center.get("lat"))
    return None


def normalize_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(value).casefold())
    without_marks = "".join(char for char in normalized if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", "", without_marks)


def _normalize_similarity_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(value).casefold())
    without_marks = "".join(char for char in normalized if not unicodedata.combining(char))
    articles = {"au", "aux", "de", "des", "du", "la", "le", "les", "l"}
    tokens = re.findall(r"[a-z0-9]+", without_marks)
    return "".join(token for token in tokens if token not in articles)


def _collect_libelles(value: Any, output: list[str]) -> None:
    if isinstance(value, dict):
        for key, nested_value in value.items():
            if key == "libelleFr" and isinstance(nested_value, str):
                candidate = nested_value.strip()
                if candidate:
                    output.append(candidate)
            else:
                _collect_libelles(nested_value, output)
    elif isinstance(value, list):
        for item in value:
            _collect_libelles(item, output)


def _unique_texts(values: list[str], limit: int = 15) -> list[str]:
    result = []
    seen = set()
    for value in values:
        cleaned = " ".join(str(value).split())
        normalized = normalize_name(cleaned)
        if cleaned and normalized and normalized not in seen:
            seen.add(normalized)
            result.append(cleaned)
            if len(result) >= limit:
                break
    return result


def _apidae_tags(obj: dict) -> list[str]:
    values: list[str] = []
    for key, value in obj.items():
        if key.startswith("informations") and key != "informations":
            _collect_libelles(value, values)
    typologies = _nested(obj, "presentation", "typologiesPromoSitra")
    _collect_libelles(typologies, values)
    return _unique_texts(values)


def _apidae_description(obj: dict) -> str:
    presentation = obj.get("presentation") or {}
    short = _text(_nested(presentation, "descriptifCourt", "libelleFr"))
    detailed = _text(_nested(presentation, "descriptifDetaille", "libelleFr"))
    parts = []
    for part in (short, detailed):
        if part and normalize_name(part) not in {normalize_name(value) for value in parts}:
            parts.append(part)
    return " ".join(parts)


def _find_url(value: Any) -> str | None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key.casefold() in {"url", "urlweb", "urlexterne", "siteweb", "lienweb"}:
                if isinstance(item, str) and item.strip().startswith(("http://", "https://")):
                    return item.strip()
        for item in value.values():
            result = _find_url(item)
            if result:
                return result
    elif isinstance(value, list):
        for item in value:
            result = _find_url(item)
            if result:
                return result
    return None


def _apidae_record(obj: dict, category: str) -> dict | None:
    coordinates = _apidae_coordinates(obj)
    if coordinates is None:
        return None
    latitude, longitude = coordinates
    identifier = obj.get("id")
    if identifier is None:
        return None
    name = _text(obj.get("nom"))
    if not name:
        return None
    commune = _text(_nested(obj, "localisation", "adresse", "commune", "nom"))
    apidae_type = _text(obj.get("type")) or None
    return {
        "poi_id": f"apidae-{identifier}",
        "source": "apidae",
        "nom": name,
        "categories": [category],
        "tags": _apidae_tags(obj),
        "commune": commune,
        "lat": latitude,
        "lon": longitude,
        "description": _apidae_description(obj),
        "apidae_type": apidae_type,
        "osm_type": None,
        "osm_tags": None,
        "url": _find_url(obj),
    }


def _osm_category(tags: dict) -> list[str]:
    categories = set()
    for key, value in tags.items():
        category = OSM_CATEGORIES.get((key, value))
        if category is None and key == "historic":
            category = OSM_CATEGORIES.get(("historic", "*"))
        if category:
            categories.add(category)
    order = {category: index for index, category in enumerate(CATEGORY_LABELS)}
    return sorted(categories, key=lambda item: order.get(item, len(order)))


def _osm_tags(tags: dict) -> list[str]:
    values = []
    for key in ("tourism", "natural", "leisure", "historic"):
        value = tags.get(key)
        if value:
            label = OSM_LABELS.get((key, value))
            if label:
                values.append(label)
            elif key == "historic":
                values.append("Patrimoine historique")
    elevation = tags.get("ele")
    if elevation:
        values.append(f"Altitude {elevation} m")
    description = tags.get("description:fr") or tags.get("description")
    if description:
        values.append(description)
    return _unique_texts(values, limit=15)


def _osm_record(element: dict) -> dict | None:
    coordinates = _osm_coordinates(element)
    if coordinates is None:
        return None
    tags = element.get("tags")
    if not isinstance(tags, dict):
        return None
    name = tags.get("name:fr") or tags.get("name")
    if not isinstance(name, str) or not name.strip():
        return None
    element_type = str(element.get("type", ""))
    identifier = element.get("id")
    if element_type not in ("node", "way", "relation") or identifier is None:
        return None
    latitude, longitude = coordinates
    description = tags.get("description:fr") or tags.get("description") or ""
    osm_type = next(
        (
            f"{key}={tags[key]}"
            for key in ("tourism", "natural", "historic", "leisure")
            if tags.get(key)
        ),
        None,
    )
    return {
        "poi_id": f"osm-{element_type}-{identifier}",
        "source": "osm",
        "nom": name.strip(),
        "categories": _osm_category(tags),
        "tags": _osm_tags(tags),
        "commune": (
            tags.get("addr:city")
            or tags.get("addr:town")
            or tags.get("addr:village")
            or tags.get("is_in:municipality")
            or ""
        ),
        "lat": latitude,
        "lon": longitude,
        "description": description.strip() if isinstance(description, str) else "",
        "apidae_type": None,
        "osm_type": osm_type,
        "osm_tags": json.dumps(tags, ensure_ascii=False, sort_keys=True),
        "url": tags.get("website") or tags.get("contact:website"),
    }


def _merge_apidae_record(existing: dict, incoming: dict) -> None:
    category_order = {category: index for index, category in enumerate(CATEGORY_LABELS)}
    categories = set(existing["categories"]) | set(incoming["categories"])
    existing["categories"] = sorted(
        categories,
        key=lambda item: category_order.get(item, len(category_order)),
    )
    existing["tags"] = _unique_texts(existing["tags"] + incoming["tags"])
    for field in ("commune", "description", "url", "apidae_type"):
        if not existing.get(field) and incoming.get(field):
            existing[field] = incoming[field]


def _haversine_km(lat: float, lon: float, latitudes: np.ndarray, longitudes: np.ndarray) -> np.ndarray:
    lat1 = math.radians(lat)
    lat2 = np.radians(latitudes.astype(np.float64))
    delta_lat = lat2 - lat1
    delta_lon = np.radians(longitudes.astype(np.float64) - lon)
    hav = np.sin(delta_lat / 2) ** 2 + math.cos(lat1) * np.cos(lat2) * np.sin(delta_lon / 2) ** 2
    return 2 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(np.clip(hav, 0, 1)))


def _deduplicate_osm(apidae: list[dict], osm: list[dict]) -> tuple[list[dict], int]:
    if not apidae or not osm:
        return osm, 0
    apidae_lat = np.asarray([item["lat"] for item in apidae], dtype=np.float64)
    apidae_lon = np.asarray([item["lon"] for item in apidae], dtype=np.float64)
    apidae_names = [normalize_name(item["nom"]) for item in apidae]
    kept = []
    removed = 0
    for item in osm:
        name = normalize_name(item["nom"])
        lat, lon = item["lat"], item["lon"]
        lat_delta = 0.2 / 111.2
        lon_delta = lat_delta / max(math.cos(math.radians(lat)), 0.1)
        candidates = np.flatnonzero(
            (np.abs(apidae_lat - lat) <= lat_delta)
            & (np.abs(apidae_lon - lon) <= lon_delta)
        )
        matched = False
        if name:
            for position in candidates:
                other_name = apidae_names[position]
                if not other_name or not (name == other_name or name in other_name or other_name in name):
                    continue
                distance = _haversine_km(
                    lat,
                    lon,
                    np.asarray([apidae_lat[position]]),
                    np.asarray([apidae_lon[position]]),
                )[0]
                if distance < 0.2:
                    matched = True
                    break
        if matched:
            removed += 1
        else:
            kept.append(item)
    return kept, removed


def _read_apidae(path: Path) -> tuple[list[dict], dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    category = str(payload.get("category") or APIDAE_SELECTIONS.get(int(path.stem), "service"))
    selection_id = int(payload.get("selection_id", path.stem))
    pages = payload.get("responses", [])
    if not isinstance(pages, list):
        pages = []
    raw_count = 0
    coordinate_less = 0
    records: dict[str, dict] = {}
    for page in pages:
        if not isinstance(page, dict):
            continue
        objects = page.get("objetsTouristiques", [])
        if not isinstance(objects, list):
            continue
        raw_count += len(objects)
        for obj in objects:
            if not isinstance(obj, dict):
                continue
            if _apidae_coordinates(obj) is None:
                coordinate_less += 1
                continue
            record = _apidae_record(obj, category)
            if record is None:
                continue
            identifier = record["poi_id"]
            if identifier in records:
                _merge_apidae_record(records[identifier], record)
            else:
                records[identifier] = record
    stats = {
        "category": category,
        "raw": raw_count,
        "coordinate_less": coordinate_less,
        "indexed_unique": len(records),
        "selection_name": payload.get("selection_name"),
        "selection_id": selection_id,
    }
    return list(records.values()), stats


def _read_osm(path: Path) -> tuple[list[dict], dict[str, int]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    elements = payload.get("elements", []) if isinstance(payload, dict) else []
    records = []
    coordinate_less = 0
    for element in elements:
        if not isinstance(element, dict):
            continue
        if _osm_coordinates(element) is None:
            coordinate_less += 1
            continue
        record = _osm_record(element)
        if record is None:
            continue
        records.append(record)
    return records, {"raw": len(elements), "coordinate_less": coordinate_less}


def build_corpus() -> pd.DataFrame:
    """Construit le corpus unifié, sans charger le modèle d'embeddings."""
    apidae_dir = POI_DATA_DIR / "apidae"
    if not apidae_dir.is_dir() or not (POI_DATA_DIR / "osm.json").is_file():
        raise FileNotFoundError("Sources POI absentes : lancer `python scripts/poi.py collect`.")

    apidae_records: dict[str, dict] = {}
    selection_stats = {}
    total_apidae_raw = 0
    total_apidae_coordinate_less = 0
    for selection_id in APIDAE_SELECTIONS:
        path = apidae_dir / f"{selection_id}.json"
        if not path.is_file():
            raise FileNotFoundError(f"Collecte Apidae absente pour la sélection {selection_id}.")
        records, stats = _read_apidae(path)
        selection_stats[str(selection_id)] = stats
        total_apidae_raw += stats["raw"]
        total_apidae_coordinate_less += stats["coordinate_less"]
        for record in records:
            if record["poi_id"] in apidae_records:
                _merge_apidae_record(apidae_records[record["poi_id"]], record)
            else:
                apidae_records[record["poi_id"]] = record

    osm_records, osm_stats = _read_osm(POI_DATA_DIR / "osm.json")
    osm_records, deduplicated_osm = _deduplicate_osm(list(apidae_records.values()), osm_records)
    rows = list(apidae_records.values()) + osm_records
    frame = pd.DataFrame(rows, columns=POI_COLUMNS)
    frame.attrs["stats"] = {
        "selections": selection_stats,
        "apidae_raw": total_apidae_raw,
        "apidae_coordinate_less": total_apidae_coordinate_less,
        "apidae_indexed_unique": len(apidae_records),
        "osm_raw": osm_stats["raw"],
        "osm_coordinate_less": osm_stats["coordinate_less"],
        "osm_deduplicated": deduplicated_osm,
        "osm_indexed": len(osm_records),
        "sources": frame["source"].value_counts().to_dict() if not frame.empty else {},
    }
    return frame


def embedding_text(record: dict | pd.Series) -> str:
    values = record.to_dict() if isinstance(record, pd.Series) else record
    categories = [
        CATEGORY_LABELS.get(category, category)
        for category in (values.get("categories") or [])
    ]
    tags = values.get("tags") or []
    parts = (
        str(values.get("nom") or ""),
        ", ".join(categories),
        ", ".join(str(tag) for tag in tags),
        str(values.get("commune") or ""),
        str(values.get("description") or ""),
    )
    return ". ".join(part for part in parts if part)[:1500]


def build_index() -> dict:
    start = time.monotonic()
    frame = build_corpus()
    stats = frame.attrs["stats"]
    if frame.empty:
        raise RuntimeError("Le corpus POI est vide après filtrage des coordonnées.")

    import torch
    from sentence_transformers import SentenceTransformer

    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = SentenceTransformer(MODEL_NAME, device=device)
    model.max_seq_length = 512
    texts = [embedding_text(record) for record in frame.to_dict(orient="records")]
    embeddings = model.encode(
        texts,
        batch_size=64,
        show_progress_bar=True,
        convert_to_numpy=True,
        normalize_embeddings=True,
    )
    embeddings = np.asarray(embeddings, dtype=np.float16)

    C.ARTIFACTS.mkdir(parents=True, exist_ok=True)
    temporary_poi = POI_PATH.with_suffix(".parquet.part")
    temporary_embeddings = EMBEDDINGS_PATH.with_suffix(".npy.part")
    temporary_meta = META_PATH.with_suffix(".json.part")
    frame.to_parquet(temporary_poi, index=False)
    with temporary_embeddings.open("wb") as stream:
        np.save(stream, embeddings, allow_pickle=False)
    meta = {
        "model": MODEL_NAME,
        "n": int(len(frame)),
        "sources": {
            str(source): int(count)
            for source, count in frame["source"].value_counts().items()
        },
        "built_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "dimensions": int(embeddings.shape[1]),
        "dtype": str(embeddings.dtype),
        "selection_counts": stats["selections"],
        "coordinate_less": {
            "apidae": stats["apidae_coordinate_less"],
            "osm": stats["osm_coordinate_less"],
        },
        "deduplicated_osm": stats["osm_deduplicated"],
    }
    temporary_meta.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary_poi.replace(POI_PATH)
    temporary_embeddings.replace(EMBEDDINGS_PATH)
    temporary_meta.replace(META_PATH)

    sizes = {
        path.name: path.stat().st_size
        for path in (POI_PATH, EMBEDDINGS_PATH, META_PATH)
    }
    elapsed = time.monotonic() - start
    for selection_id, selection in stats["selections"].items():
        name = selection.get("selection_name") or selection["category"]
        print(
            f"Apidae {selection_id} ({name}): {selection['raw']} bruts, "
            f"{selection['coordinate_less']} sans coordonnées, "
            f"{selection['indexed_unique']} uniques géolocalisés"
        )
    print(
        f"Sources indexées: Apidae {stats['apidae_indexed_unique']}, "
        f"OSM {stats['osm_indexed']} (bruts {stats['osm_raw']}, "
        f"sans coordonnées {stats['osm_coordinate_less']}, "
        f"dédoublonnés avec Apidae {stats['osm_deduplicated']}); "
        f"total {len(frame)}"
    )
    print(f"Index construit en {elapsed:.1f}s.")
    print("Taille des artefacts: " + ", ".join(f"{name}={size} octets" for name, size in sizes.items()))
    return meta


def poi_response(item: dict, score: float | None = None, distance_km: float | None = None) -> dict:
    if score is None:
        score = item.get("score")
    if distance_km is None:
        distance_km = item.get("distance_km")
    categories = _list_values(item.get("categories"))
    tags = _list_values(item.get("tags"))
    return {
        "poi_id": str(item.get("poi_id", "")),
        "nom": str(item.get("nom", "")),
        "categories": list(categories),
        "tags": list(tags)[:6],
        "commune": str(item.get("commune") or ""),
        "lat": float(item["lat"]) if item.get("lat") is not None else None,
        "lon": float(item["lon"]) if item.get("lon") is not None else None,
        "source": str(item.get("source", "")),
        "score": round(float(score), 3) if score is not None else None,
        "jev_score": (
            round(float(item["jev_score"]), 2)
            if item.get("jev_score") is not None
            else None
        ),
        "distance_km": round(float(distance_km), 1) if distance_km is not None else None,
        "description": str(item.get("description") or "")[:280],
    }


def _normalize_categories(categories: list[str] | tuple[str, ...] | set[str] | None) -> set[str] | None:
    if not categories:
        return None
    normalized = {str(category).strip().casefold() for category in categories if str(category).strip()}
    return normalized or None


def _list_values(value: Any) -> list:
    if value is None:
        return []
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


def jev_card(record: dict) -> dict:
    categories = [
        CATEGORY_LABELS.get(str(category), str(category))
        for category in _list_values(record.get("categories"))
    ]
    return {
        "nom": str(record.get("nom") or ""),
        "categories": categories,
        "tags": [str(tag) for tag in _list_values(record.get("tags"))[:8]],
        "commune": str(record.get("commune") or ""),
        "description": str(record.get("description") or "")[:300],
    }


def jev_scores(reference: dict | str, candidates: list[dict]) -> list[float] | None:
    if not candidates:
        return []
    candidate_ids = tuple(str(candidate.get("poi_id", "")) for candidate in candidates)
    if isinstance(reference, dict):
        mode = "poi"
        reference_key = str(reference.get("poi_id") or reference.get("nom") or "")
        state = {"lieu_de_reference": jev_card(reference)}
        criteria = [
            "Aucun rapport avec le lieu de référence",
            "Faible ressemblance",
            "Même grande famille de lieu, mais une expérience différente",
            "Expérience proche",
            "Expérience quasi équivalente : une alternative crédible pour un visiteur",
        ]
    else:
        mode = "query"
        reference_key = str(reference)
        state = {"recherche_du_visiteur": reference_key}
        criteria = [
            "Ne correspond pas à la recherche",
            "Correspond faiblement",
            "Correspond en partie",
            "Correspond bien",
            "Correspond parfaitement à la recherche",
        ]

    cache_key = (mode, reference_key, candidate_ids)
    with _JEV_CACHE_LOCK:
        cached = _JEV_CACHE.get(cache_key)
        if cached is not None:
            return list(cached)

    try:
        api_key = C.secret("OPENROUTER_API_KEY")
        if not api_key:
            _LOGGER.warning("Affinage JEV indisponible : clé OPENROUTER_API_KEY absente.")
            return None
        state["candidats"] = {
            f"c{index}": jev_card(candidate)
            for index, candidate in enumerate(candidates)
        }
        questions = {}
        for index in range(len(candidates)):
            if mode == "poi":
                instructions = (
                    f"Pour un visiteur qui voulait aller au lieu de référence, le candidat c{index} "
                    "offre-t-il une expérience comparable (même type de lieu, même activité, "
                    "même intérêt) ?"
                )
            else:
                instructions = (
                    f"Le candidat c{index} correspond-il à ce que cherche le visiteur ?"
                )
            questions[f"c{index}"] = {
                "type": "score",
                "instructions": instructions,
                "criteria": criteria,
            }
        response = requests.post(
            JEV_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            json={"model": JEV_MODEL, "state": state, "questions": questions},
            timeout=20,
        )
        if response.status_code != 200:
            _LOGGER.warning(
                "Affinage JEV indisponible : réponse HTTP %s.", response.status_code
            )
            return None
        answers = response.json().get("answers")
        if not isinstance(answers, dict):
            raise ValueError("Réponses JEV absentes.")
        scores = []
        for index in range(len(candidates)):
            answer = answers.get(f"c{index}")
            score = answer.get("score") if isinstance(answer, dict) else None
            if isinstance(score, bool) or not isinstance(score, (int, float)):
                raise ValueError("Score JEV absent.")
            score = float(score)
            if not math.isfinite(score) or not 0 <= score <= 4:
                raise ValueError("Score JEV invalide.")
            scores.append(score)
    except Exception as error:
        _LOGGER.warning("Affinage JEV indisponible : %s.", type(error).__name__)
        return None

    with _JEV_CACHE_LOCK:
        _JEV_CACHE[cache_key] = scores
        if len(_JEV_CACHE) > 512:
            _JEV_CACHE.pop(next(iter(_JEV_CACHE)))
    return list(scores)


def _clamp_k(value: int) -> int:
    return max(1, min(int(value), MAX_K))


def _validate_location(lat: float | None, lon: float | None, rayon_km: float | None) -> None:
    if rayon_km is not None and (lat is None or lon is None):
        raise ValueError("rayon_km nécessite lat et lon.")
    if (lat is None) != (lon is None):
        raise ValueError("lat et lon doivent être fournis ensemble.")
    if lat is not None and lon is not None and _coordinates(lon, lat) is None:
        raise ValueError("Coordonnées invalides.")
    if rayon_km is not None and (not math.isfinite(float(rayon_km)) or rayon_km <= 0):
        raise ValueError("rayon_km doit être positif.")


def _rank_candidates(
    reference: dict | str,
    selected: np.ndarray,
    scores: np.ndarray,
    distances: np.ndarray | None,
    records: list[dict],
    k: int,
    affiner: bool,
) -> tuple[list[dict], dict[str, Any]]:
    result_limit = _clamp_k(k)
    cosine_order = selected[np.argsort(scores[selected])[::-1]]
    if affiner:
        pool = cosine_order[: max(RERANK_POOL, result_limit)]
        rerank_scores = jev_scores(reference, [records[int(position)] for position in pool])
        if rerank_scores is None:
            order = [(int(position), None) for position in cosine_order[:result_limit]]
            status = "indisponible"
        else:
            order = sorted(
                (
                    (int(position), float(rerank_scores[index]))
                    for index, position in enumerate(pool)
                ),
                key=lambda item: (item[1], float(scores[item[0]])),
                reverse=True,
            )[:result_limit]
            status = "ok"
        candidate_count = len(pool)
    else:
        order = [(int(position), None) for position in cosine_order[:result_limit]]
        candidate_count = 0
        status = "desactive"

    results = []
    for position, jev_score in order:
        results.append(
            {
                **records[position],
                "score": float(scores[position]),
                "jev_score": jev_score,
                "distance_km": (
                    float(distances[position]) if distances is not None else None
                ),
            }
        )
    return results, {
        "modele": JEV_MODEL,
        "candidats": candidate_count,
        "statut": status,
    }


class PoiIndex:
    """Index de POI ; le modèle d'embeddings n'est chargé qu'au premier search."""

    def __init__(
        self,
        poi_path: Path = POI_PATH,
        embeddings_path: Path = EMBEDDINGS_PATH,
        meta_path: Path = META_PATH,
    ):
        self.frame = pd.read_parquet(poi_path)
        self.embeddings = np.load(embeddings_path, mmap_mode="r", allow_pickle=False)
        self.meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if self.meta.get("model") != MODEL_NAME:
            raise ValueError(
                f"Index POI incompatible : modèle attendu {MODEL_NAME}, "
                f"trouvé {self.meta.get('model')!r}."
            )
        if len(self.frame) != self.embeddings.shape[0]:
            raise ValueError("Le corpus et les embeddings POI n'ont pas la même taille.")
        if self.embeddings.ndim != 2:
            raise ValueError("La matrice d'embeddings POI doit être en deux dimensions.")
        if (
            self.meta.get("dimensions") != EMBEDDING_DIMENSIONS
            or self.embeddings.shape[1] != EMBEDDING_DIMENSIONS
        ):
            raise ValueError(
                f"Index POI incompatible : dimension attendue {EMBEDDING_DIMENSIONS}, "
                f"meta={self.meta.get('dimensions')!r}, matrice={self.embeddings.shape[1]}."
            )
        self.records = self.frame.to_dict(orient="records")
        for record in self.records:
            record["categories"] = _list_values(record.get("categories"))
            record["tags"] = _list_values(record.get("tags"))
        self.positions = {
            str(record["poi_id"]): position
            for position, record in enumerate(self.records)
        }
        self.normalized_names = [normalize_name(record["nom"]) for record in self.records]
        self.similarity_names = [_normalize_similarity_name(record["nom"]) for record in self.records]
        self.latitudes = self.frame["lat"].to_numpy(dtype=np.float64)
        self.longitudes = self.frame["lon"].to_numpy(dtype=np.float64)
        matrix = np.asarray(self.embeddings, dtype=np.float32)
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        self.normalized_embeddings = matrix / np.maximum(norms, 1e-12)
        self._model = None

    def get(self, poi_id: str) -> dict | None:
        position = self.positions.get(str(poi_id))
        return self.records[position] if position is not None else None

    def suggest(self, q: str, limit: int = 20) -> list[dict]:
        query = normalize_name(q)
        if not query:
            return []
        matches = [
            position
            for position, name in enumerate(self.normalized_names)
            if query in name
        ]
        matches.sort(
            key=lambda position: (
                0 if self.normalized_names[position].startswith(query) else 1,
                len(self.normalized_names[position]),
                self.normalized_names[position],
            )
        )
        return [self.records[position] for position in matches[:_clamp_k(limit)]]

    def similar(
        self,
        poi_id: str,
        k: int = 10,
        rayon_km: float | None = None,
        categories: list[str] | tuple[str, ...] | set[str] | None = None,
        affiner: bool = True,
    ) -> tuple[list[dict], dict[str, Any]]:
        source_position = self.positions.get(str(poi_id))
        if source_position is None:
            raise KeyError(poi_id)
        source = self.records[source_position]
        _validate_location(source["lat"], source["lon"], rayon_km)
        wanted = _normalize_categories(categories)
        distances = _haversine_km(
            float(source["lat"]),
            float(source["lon"]),
            self.latitudes,
            self.longitudes,
        )
        scores = self.normalized_embeddings @ self.normalized_embeddings[source_position]
        candidates = np.arange(len(self.records))
        keep = candidates != source_position
        if rayon_km is not None:
            keep &= distances <= rayon_km
        source_name = self.similarity_names[source_position]
        if source_name:
            same_name_nearby = (
                (distances < 20)
                & np.asarray([name == source_name for name in self.similarity_names])
            )
            keep &= ~same_name_nearby
        if wanted:
            category_mask = np.asarray([
                bool(wanted.intersection(record.get("categories") or []))
                for record in self.records
            ])
            keep &= category_mask
        selected = candidates[keep]
        return _rank_candidates(
            source, selected, scores, distances, self.records, k, affiner
        )

    def _query_embedding(self, q: str) -> np.ndarray:
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(MODEL_NAME, device="cpu")
            self._model.max_seq_length = 512
        embedding = self._model.encode(
            [f"Instruct: {QUERY_INSTRUCTION}\nQuery: {q.strip()}"],
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return np.asarray(embedding[0], dtype=np.float32)

    def search(
        self,
        q: str,
        k: int = 10,
        lat: float | None = None,
        lon: float | None = None,
        rayon_km: float | None = None,
        categories: list[str] | tuple[str, ...] | set[str] | None = None,
        affiner: bool = True,
    ) -> tuple[list[dict], dict[str, Any]]:
        query = str(q).strip()
        if not query:
            raise ValueError("q ne peut pas être vide.")
        _validate_location(lat, lon, rayon_km)
        wanted = _normalize_categories(categories)
        scores = self.normalized_embeddings @ self._query_embedding(query)
        candidates = np.arange(len(self.records))
        keep = np.ones(len(self.records), dtype=bool)
        distances = None
        if lat is not None and lon is not None:
            distances = _haversine_km(float(lat), float(lon), self.latitudes, self.longitudes)
            if rayon_km is not None:
                keep &= distances <= rayon_km
        if wanted:
            category_mask = np.asarray([
                bool(wanted.intersection(record.get("categories") or []))
                for record in self.records
            ])
            keep &= category_mask
        selected = candidates[keep]
        return _rank_candidates(
            query, selected, scores, distances, self.records, k, affiner
        )
