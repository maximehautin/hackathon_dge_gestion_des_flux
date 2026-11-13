"""Outils MCP de l'agent de planification Marguerite."""
from __future__ import annotations

import argparse
import json
import math
import os
import re
from datetime import date
from pathlib import Path

import requests
from mcp.server.fastmcp import FastMCP

from . import marguerite as M

mcp = FastMCP("marguerite")
_SESSION_DIR: Path | None = None
_CONTEXT: dict = {}


def configure_session(session_dir: str | Path) -> None:
    global _SESSION_DIR, _CONTEXT
    _SESSION_DIR = Path(session_dir).resolve()
    _CONTEXT = json.loads((_SESSION_DIR / "contexte.json").read_text(encoding="utf-8"))
    if not isinstance(_CONTEXT.get("payload"), dict) or not isinstance(_CONTEXT.get("zone"), dict):
        raise ValueError("Contexte de session invalide.")


def _payload() -> dict:
    if not _CONTEXT:
        raise RuntimeError("Contexte de session indisponible.")
    return _CONTEXT["payload"]


def _jour() -> dict:
    return _payload()["jour"]


def _zone() -> dict:
    return _CONTEXT["zone"]


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _progress(text: str) -> None:
    if _SESSION_DIR is None:
        return
    try:
        with (_SESSION_DIR / "progression.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(_json({"texte": text}) + "\n")
            stream.flush()
    except Exception:
        pass


def _poi_name(value) -> str | None:
    poi_id = _poi_id(value)
    poi = _poi_map().get(str(poi_id)) if poi_id is not None else None
    return poi.get("nom") if poi else None


def _join_names(names: list[str]) -> str:
    if len(names) < 2:
        return names[0] if names else "aucun lieu"
    return f"{', '.join(names[:-1])} et {names[-1]}"


def _format_date(value: str) -> str:
    weekdays = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")
    months = (
        "janvier", "février", "mars", "avril", "mai", "juin",
        "juillet", "août", "septembre", "octobre", "novembre", "décembre",
    )
    try:
        parsed = date.fromisoformat(value)
    except (TypeError, ValueError):
        return str(value)
    return f"{weekdays[parsed.weekday()]} {parsed.day} {months[parsed.month - 1]}"


def _format_number(value) -> str:
    formatted = f"{float(value):,.10f}".rstrip("0").rstrip(".")
    return formatted.replace(",", "\u202f").replace(".", ",")


def _base_url() -> str:
    return os.environ.get("FLUX_INTERNAL_URL", "http://127.0.0.1:8000").rstrip("/")


def _http_json(path: str, params: dict) -> dict:
    try:
        response = requests.get(f"{_base_url()}{path}", params=params, timeout=45)
    except requests.RequestException:
        raise RuntimeError("L'API Flux Isère est indisponible.") from None
    if response.status_code != 200:
        raise RuntimeError(f"L'API Flux Isère a répondu HTTP {response.status_code}.")
    try:
        result = response.json()
    except ValueError:
        raise RuntimeError("Réponse Flux Isère invalide.") from None
    if not isinstance(result, dict):
        raise RuntimeError("Réponse Flux Isère invalide.")
    return result


def _poi_id(value) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    match = re.fullmatch(r"(?:apidae-)?(\d+)", str(value or ""))
    return int(match.group(1)) if match else None


def _zone_items() -> list[dict]:
    return _zone().get("pois", []) + _zone().get("gas", [])


def _poi_map() -> dict[str, dict]:
    return {str(item["id"]): item for item in _zone_items() if item.get("id") is not None}


def _distance_km(first: dict, second: dict) -> float:
    lat1, lon1 = math.radians(float(first["lat"])), math.radians(float(first["lon"]))
    lat2, lon2 = math.radians(float(second["lat"])), math.radians(float(second["lon"]))
    dlat, dlon = lat2 - lat1, lon2 - lon1
    value = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(value))


def _decode_polyline(encoded: str, precision: int = 6) -> list[list[float]]:
    coords, index, lat, lon = [], 0, 0, 0
    factor = 10 ** precision
    while index < len(encoded):
        for which in (0, 1):
            shift = result = 0
            while True:
                byte = ord(encoded[index]) - 63
                index += 1
                result |= (byte & 0x1F) << shift
                shift += 5
                if byte < 0x20:
                    break
            delta = ~(result >> 1) if result & 1 else result >> 1
            if which == 0:
                lat += delta
            else:
                lon += delta
        coords.append([lat / factor, lon / factor])
    return coords


def _attach_result(item: dict) -> dict | None:
    poi_id = str(item.get("poi_id") or "")
    match = re.fullmatch(r"apidae-(\d+)", poi_id)
    poi_by_id = _poi_map()
    if match:
        return poi_by_id.get(match.group(1))
    if poi_id.startswith("osm-") and item.get("lat") is not None and item.get("lon") is not None:
        point = {"lat": item["lat"], "lon": item["lon"]}
        nearest = None
        nearest_distance = 0.3
        for poi in _zone().get("pois", []):
            distance = _distance_km(point, poi)
            if distance <= nearest_distance:
                nearest, nearest_distance = poi, distance
        return nearest
    return None


def _other_day_ids() -> set[str]:
    return {
        str(_poi_id(poi_id))
        for day in _jour().get("autres_jours", [])
        for poi_id in day
        if _poi_id(poi_id) is not None
    }


def _filtered_results(items: list[dict], limit: int) -> list[dict]:
    jour = _jour()
    origin = jour["hebergement"]
    radius = float(jour["rmax"])
    budget_d = float(jour["budget"]["d"])
    origin_alt = jour.get("alt_origine")
    other_ids = _other_day_ids()
    result = []
    seen = set()
    for item in items:
        poi = _attach_result(item)
        if poi is None or poi.get("cat") == "gastronomie":
            continue
        poi_id = str(poi.get("id"))
        if poi_id in seen or poi_id in other_ids:
            continue
        distance = _distance_km(origin, poi)
        if distance > radius:
            continue
        altitude = poi.get("alt")
        if origin_alt is not None and altitude is not None and float(altitude) - float(origin_alt) > budget_d * 0.85:
            continue
        seen.add(poi_id)
        result.append({
            "id": poi["id"],
            "nom": poi["nom"],
            "cat": poi["cat"],
            "commune": poi["commune"],
            "distance_km": round(distance, 1),
            "desc_court": str(poi.get("desc") or "")[:240],
        })
        if len(result) >= limit:
            break
    return result


@mcp.tool()
def contexte() -> str:
    """Renvoie la journée, l'historique des parcours et le retour en cours."""
    _progress("Lecture de votre journée actuelle…")
    payload = _payload()
    return _json({
        "jour": payload["jour"],
        "historique": payload["historique"],
        "feedback": payload["feedback"],
    })


@mcp.tool()
def chercher_lieux(texte: str, k: int = 15) -> str:
    """Recherche des lieux Apidae pertinents, rattachés à la zone et filtrés selon le budget."""
    _progress(f"Recherche de lieux : « {texte} »…")
    limit = min(max(int(k), 1), 50)
    jour = _jour()
    response = _http_json("/api/poi/recherche", {
        "q": texte,
        "lat": jour["hebergement"]["lat"],
        "lon": jour["hebergement"]["lon"],
        "rayon_km": jour["rmax"],
        "k": 50,
        "affiner": "true",
    })
    results = _filtered_results(response.get("items", []), limit)
    if not results:
        message = "Aucun lieu possible autour de l'hébergement."
    elif len(results) == 1:
        message = "1 lieu possible autour de l'hébergement."
    else:
        message = f"{len(results)} lieux possibles autour de l'hébergement."
    _progress(message)
    return _json(results)


@mcp.tool()
def lieux_similaires(id: int, k: int = 10) -> str:
    """Trouve des lieux proches et similaires à une étape de la zone."""
    poi_id = _poi_id(id)
    name = _poi_name(poi_id) if poi_id is not None else None
    _progress(f"Recherche d'alternatives : {name or 'ce lieu'}…")
    if poi_id is None or str(poi_id) not in _poi_map():
        return _json({"erreur": "Lieu absent de la zone."})
    limit = min(max(int(k), 1), 50)
    response = _http_json(f"/api/poi/apidae-{poi_id}/similaires", {
        "k": 15,
        "rayon_km": 8,
        "affiner": "false",
    })
    results = _filtered_results(response.get("items", []), limit)
    if not results:
        message = "Aucune alternative trouvée."
    elif len(results) == 1:
        message = "1 alternative trouvée."
    else:
        message = f"{len(results)} alternatives trouvées."
    _progress(message)
    return _json(results)


@mcp.tool()
def details_lieu(id: int) -> str:
    """Renvoie la fiche d'un lieu Apidae de la zone."""
    poi_id = _poi_id(id)
    poi = _poi_map().get(str(poi_id)) if poi_id is not None else None
    _progress(f"Lecture de la fiche : {poi['nom'] if poi else 'ce lieu'}…")
    return _json(poi if poi is not None else {"erreur": "Lieu absent de la zone."})


@mcp.tool()
def affluence(ids: list[int], date: str) -> str:
    """Renvoie le niveau, le calibrage et l'indice d'affluence pour une date."""
    normalized = [_poi_id(value) for value in ids]
    names = [_poi_name(value) or "ce lieu" for value in normalized]
    _progress(f"Vérification de l'affluence du {_format_date(date)} : {_join_names(names)}…")
    if not normalized or any(value is None for value in normalized):
        return _json({"erreur": "Identifiants de lieux invalides."})
    poi_ids = [f"apidae-{value}" for value in normalized]
    if len(poi_ids) == 1:
        response = _http_json(f"/api/poi/{poi_ids[0]}/frequentation", {"start": date, "days": 1})
        row = response.get("jours", [{}])[0] if response.get("jours") else {}
        result = [{
            "id": normalized[0],
            "niveau": row.get("niveau", "inconnu"),
            "calibrage": response.get("calibrage", "relatif"),
            "t": M.flux_t(row),
        }]
        _progress(f"{names[0]} : {result[0]['niveau']}")
        return _json(result)
    if not 2 <= len(poi_ids) <= 10:
        return _json({"erreur": "Fournissez entre 2 et 10 lieux."})
    response = _http_json("/api/poi/frequentation/comparer", {
        "ids": ",".join(poi_ids),
        "day": date,
    })
    values = {
        item["poi_id"]: item
        for group in (response.get("calibres", []), response.get("relatifs", []))
        for item in group
    }
    result = []
    for poi_id, number in zip(poi_ids, normalized):
        item = values.get(poi_id, {})
        result.append({
            "id": number,
            "niveau": item.get("niveau", "inconnu"),
            "calibrage": item.get("calibrage", "relatif"),
            "t": M.flux_t(item),
        })
    for name, item in zip(names, result):
        _progress(f"{name} : {item['niveau']}")
    return _json(result)


@mcp.tool()
def conseil_horaire(id: int, date: str) -> str:
    """Renvoie le profil horaire et le conseil d'arrivée pour une date."""
    poi_id = _poi_id(id)
    name = _poi_name(poi_id) if poi_id is not None else None
    _progress(f"Consultation des heures d'affluence : {name or 'ce lieu'}…")
    if poi_id is None or str(poi_id) not in _poi_map():
        return _json({"erreur": "Lieu absent de la zone."})
    return _json(_http_json(f"/api/poi/apidae-{poi_id}/horaires", {"day": date}))


@mcp.tool()
def commerces_proches(id_ou_lat_lon: str, rayon_km: float = 3) -> str:
    """Liste les commerces de la zone à proximité d'un lieu ou de coordonnées."""
    poi_id = _poi_id(id_ou_lat_lon)
    name = _poi_name(poi_id) if poi_id is not None else None
    _progress(f"Recherche de commerces locaux à proximité : {name or 'ce point'}…")
    try:
        radius = float(rayon_km)
    except (TypeError, ValueError):
        return _json({"erreur": "Rayon invalide."})
    if not math.isfinite(radius) or radius < 0:
        return _json({"erreur": "Rayon invalide."})
    if poi_id is not None:
        origin = _poi_map().get(str(poi_id))
    else:
        try:
            lat, lon = (float(value.strip()) for value in id_ou_lat_lon.split(",", 1))
            origin = {"lat": lat, "lon": lon}
        except (AttributeError, TypeError, ValueError):
            return _json({"erreur": "Indiquez un identifiant Apidae ou des coordonnées lat,lon."})
    if origin is None:
        return _json({"erreur": "Lieu absent de la zone."})
    result = []
    for shop in _zone().get("gas", []):
        distance = _distance_km(origin, shop)
        if distance <= radius:
            result.append((distance, {
                "id": shop["id"],
                "nom": shop["nom"],
                "cat": shop["cat"],
                "commune": shop["commune"],
                "distance_km": round(distance, 1),
            }))
    result.sort(key=lambda item: item[0])
    return _json([item for _, item in result])


def _calculate_loop(ids: list[int]) -> dict:
    if not isinstance(ids, list) or not 1 <= len(ids) <= 4:
        raise ValueError("Une boucle doit comporter une à trois visites et au plus un commerce.")
    normalized = [_poi_id(value) for value in ids]
    if any(value is None for value in normalized) or len(set(normalized)) != len(normalized):
        raise ValueError("Identifiants de lieux invalides ou répétés.")
    poi_map = _poi_map()
    stops = [poi_map.get(str(value)) for value in normalized]
    if any(stop is None for stop in stops):
        raise ValueError("Un lieu n'appartient pas à la zone.")
    visits = [stop for stop in stops if stop["cat"] != "gastronomie"]
    shops = [stop for stop in stops if stop["cat"] == "gastronomie"]
    if not 1 <= len(visits) <= 3 or len(shops) > 1:
        raise ValueError("Une boucle doit comporter une à trois visites et au plus un commerce.")

    jour = _jour()
    origin = jour["hebergement"]
    response = M.geovelo_route(
        [(origin["lat"], origin["lon"]), *[(stop["lat"], stop["lon"]) for stop in stops], (origin["lat"], origin["lon"])],
        jour["velo"],
        profil=_payload().get("profil_geovelo", "MEDIAN"),
        instructions=False,
    )
    try:
        section = response[0]["sections"][0]
        details = section.get("details") or {}
        distances = details.get("distances") or {}
        total = float(distances.get("total") or 0)
        km = math.floor(total / 100 + 0.5) / 10
        dplus = float(details.get("verticalGain") or 0)
        greenway = float(distances.get("greenway") or 0)
        cycleway = float(distances.get("cycleway") or 0)
        dedicated = greenway + cycleway + sum(
            float(distances.get(key) or 0)
            for key in ("lane", "sharebusway", "opposite")
        )
        discouraged = float(distances.get("discouragedRoads") or 0)
        pedestrian = sum(
            float(distances.get(key) or 0)
            for key in ("footway", "pedestrian", "steps")
        )
        remaining = max(0, total - dedicated - discouraged - pedestrian)
        calm = min(
            sum(float(distances.get(key) or 0) for key in ("zone30", "livingstreet", "residential")),
            remaining,
        )
        ordinary = max(0, remaining - calm)
        denominator = max(1, dedicated + discouraged + pedestrian + calm + ordinary)
        green = (greenway + cycleway) / max(1, total)
        voies = {
            "dedie": max(0, min(1, dedicated / denominator)),
            "deconseillee": max(0, min(1, discouraged / denominator)),
        }
        geometry = _decode_polyline(section["geometry"]) if section.get("geometry") else []
    except (IndexError, KeyError, TypeError, ValueError):
        raise RuntimeError("Réponse Géovélo invalide.") from None
    budget = jour["budget"]
    over_km = max(0, round(km - float(budget["km"]), 1))
    over_dplus = max(0, dplus - float(budget["d"]))
    return {
        "stops": normalized,
        "km": km,
        "dplus": dplus,
        "green": green,
        "voies": voies,
        "respecte_budget": over_km == 0 and over_dplus == 0,
        "depassement_km": over_km,
        "depassement_dplus": over_dplus,
        "geom": geometry,
    }


@mcp.tool()
def calculer_boucle(ids: list[int]) -> str:
    """Calcule la boucle GéoVélo et vérifie les budgets de distance et de dénivelé."""
    names = [_poi_name(value) or "un lieu" for value in ids] if isinstance(ids, list) else []
    origin_name = _jour().get("hebergement", {}).get("nom") or "l'hébergement"
    _progress(f"Calcul de la boucle à vélo avec GéoVélo : {' → '.join([origin_name, *names, origin_name])}…")
    try:
        result = _calculate_loop(ids)
    except ValueError as error:
        return _json({"erreur": str(error)})
    budget_text = "dans le budget" if result["respecte_budget"] else "hors budget"
    _progress(
        f"{_format_number(result['km'])} km, {_format_number(result['dplus'])} m de dénivelé : "
        f"{budget_text} ; "
        f"{_format_number(round(result['voies']['dedie'] * 100))} % sur voies dédiées, "
        f"{_format_number(round(result['voies']['deconseillee'] * 100))} % sur routes déconseillées."
    )
    return _json({key: value for key, value in result.items() if key != "geom"})


@mcp.tool()
def definir_journee(ids: list[int], resume: str) -> str:
    """Valide et enregistre le parcours proposé pour cette journée."""
    _progress("Validation du nouveau parcours…")
    if _SESSION_DIR is None:
        _progress("Parcours refusé : Session indisponible. Correction en cours…")
        return _json({"erreur": "Session indisponible."})
    try:
        result = _calculate_loop(ids)
    except (RuntimeError, ValueError) as error:
        reason = str(error).rstrip().rstrip(".")
        _progress(f"Parcours refusé : {reason}. Correction en cours…")
        return _json({"erreur": str(error)})
    if not result["respecte_budget"]:
        _progress("Parcours refusé : Le parcours dépasse le budget. Correction en cours…")
        return _json({
            "erreur": "Le parcours dépasse le budget.",
            "depassement_km": result["depassement_km"],
            "depassement_dplus": result["depassement_dplus"],
        })
    proposal = {
        "stops": result["stops"],
        "resume": resume,
        "km": result["km"],
        "dplus": result["dplus"],
        "green": result["green"],
        "voies": result["voies"],
        "geom": result["geom"],
    }
    target = _SESSION_DIR / "resultat.json"
    temporary = target.with_suffix(".tmp")
    temporary.write_text(_json(proposal), encoding="utf-8")
    temporary.replace(target)
    _progress("Parcours validé.")
    return _json({
        "ok": True,
        "km": result["km"],
        "dplus": result["dplus"],
        "voies": result["voies"],
    })


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--session", required=True)
    args = parser.parse_args()
    configure_session(args.session)
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
