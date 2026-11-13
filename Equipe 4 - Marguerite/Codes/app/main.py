"""API Flux Isère (FastAPI) : expose les modules et sert l'interface cartographique.

Lancer : uvicorn app.main:app --reload   (après python scripts/build.py)
"""
from __future__ import annotations

import asyncio
import json
import time
from collections import deque
from datetime import date, timedelta
from pathlib import Path
from threading import Lock, Semaphore
from typing import Literal
from uuid import uuid4

import pandas as pd
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator

from flux import config as C
from flux import marguerite as M
from flux import marguerite_agent as MA
from flux.data import load_ens_daily
from flux.forecast import METRICS_PATH, MODEL_PATH, Forecaster
from flux.frequentation import META_PATH, MODEL_PATH as FORME_MODEL_PATH, FrequentationModel, compare_predictions
from flux.horaires import HORAIRES_PATH, conseil as conseil_horaire, type_jour
from flux.poi import PoiIndex, poi_response

ROUTE_TAGS: dict[str, list[str]] = {}


def route_tags(path: str) -> list[str]:
    return []


app = FastAPI(
    title="Flux Isère",
    description="Une application, cinq problématiques de gestion des flux touristiques",
    version="0.1",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)
MARGUERITE_V2_APP = Path(__file__).resolve().parents[1] / "web" / "app" / "index.html"


class MargueriteApidaeRequest(BaseModel):
    selectionIds: list[int]
    lat: float
    lon: float
    radiusKm: float
    count: int = 200
    first: int = 0


class MargueritePoint(BaseModel):
    lat: float
    lon: float


class MargueriteGeoVeloRequest(BaseModel):
    points: list[MargueritePoint]
    velo: str
    profil: Literal["MEDIAN", "RIDE"] | None = None
    instructions: bool = False


class MargueriteAgentCoordinates(BaseModel):
    lat: float = Field(ge=44.5, le=46.0)
    lon: float = Field(ge=4.5, le=6.6)


class MargueriteAgentStop(BaseModel):
    id: int
    nom: str
    cat: str | None = None


class MargueriteAgentBudget(BaseModel):
    km: float = Field(gt=0)
    d: float = Field(gt=0)


class MargueriteAgentAccommodation(MargueriteAgentCoordinates):
    nom: str


class MargueriteAgentDay(BaseModel):
    date: date
    hebergement: MargueriteAgentAccommodation
    profil: str
    velo: Literal["classique", "vae"]
    budget: MargueriteAgentBudget
    prefs: dict[str, float]
    rmax: float = Field(gt=0, le=17)
    alt_origine: float | None = None
    etapes: list[MargueriteAgentStop]
    autres_jours: list[list[int]]


class MargueriteAgentVersion(BaseModel):
    feedback: str | None
    etapes: list[MargueriteAgentStop]
    km: float
    dplus: float
    resume: str


class MargueriteAgentRequest(BaseModel):
    zone: MargueriteAgentCoordinates
    jour: MargueriteAgentDay
    historique: list[MargueriteAgentVersion] = Field(max_length=20)
    feedback: str = Field(min_length=1, max_length=1000)
    variante: Literal["v1", "v2"] = "v1"
    profil_geovelo: Literal["MEDIAN", "RIDE"] = "MEDIAN"

    @field_validator("feedback")
    @classmethod
    def non_empty_feedback(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Le retour ne peut pas être vide.")
        return value


_AGENT_SEMAPHORE = Semaphore(2)
_AGENT_RATE_LIMIT = 10
_AGENT_RATE_WINDOW_S = 600
_AGENT_RATE_LOCK = Lock()
_AGENT_CALLS: dict[str, deque[float]] = {}
_AGENT_JOBS_LOCK = Lock()
_AGENT_JOBS: dict[str, dict] = {}
_AGENT_TASKS: set[asyncio.Task] = set()
_AGENT_JOB_TTL_S = 15 * 60
_AGENT_JOB_LIMIT = 100


class State:
    def __init__(self):
        self.forecaster = Forecaster() if MODEL_PATH.exists() else None
        poi_artifacts = (
            C.ARTIFACTS / "poi.parquet",
            C.ARTIFACTS / "poi_embeddings.npy",
            C.ARTIFACTS / "poi_meta.json",
        )
        self.poi_index = PoiIndex() if all(path.exists() for path in poi_artifacts) else None
        self.daily, self.ens_sites = load_ens_daily()
        self.frequentation = (
            FrequentationModel(self.forecaster, self.ens_sites)
            if FORME_MODEL_PATH.exists() and META_PATH.exists()
            else None
        )
        self.horaires = json.loads(HORAIRES_PATH.read_text()) if HORAIRES_PATH.exists() else None


S = State()


def _jsonable(d: dict) -> dict:
    out = {}
    for k, v in d.items():
        if isinstance(v, set):
            v = sorted(v)
        elif isinstance(v, float) and pd.isna(v):
            v = None
        elif hasattr(v, "item"):
            v = v.item()
        out[k] = v
    return out


def _require_poi_index() -> PoiIndex:
    if S.poi_index is None:
        raise HTTPException(503, "Index POI indisponible : lancer `python scripts/poi.py collect` puis `python scripts/poi.py index`.")
    return S.poi_index


@app.get("/")
def marguerite_v2_page():
    if not MARGUERITE_V2_APP.is_file():
        raise HTTPException(
            503,
            "Le parcours v2 de Marguerite n'est pas construit : "
            "python web/pipeline/build_app.py",
        )
    return FileResponse(MARGUERITE_V2_APP, media_type="text/html")


@app.get("/api/poi/recherche", tags=route_tags("/api/poi/recherche"))
def poi_recherche(
    q: str,
    k: int = 10,
    lat: float | None = Query(None, ge=-90, le=90),
    lon: float | None = Query(None, ge=-180, le=180),
    rayon_km: float | None = Query(None, gt=0),
    categories: str | None = None,
    affiner: bool = True,
):
    index = _require_poi_index()
    selected_categories = [item.strip() for item in categories.split(",") if item.strip()] if categories else None
    try:
        results, affinage = index.search(
            q,
            k=min(max(k, 1), 50),
            lat=lat,
            lon=lon,
            rayon_km=rayon_km,
            categories=selected_categories,
            affiner=affiner,
        )
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    items = [poi_response(item) for item in results]
    return {
        "query": q,
        "items": items,
        "count": len(items),
        "affinage": affinage,
    }


@app.get("/api/poi/frequentation/comparer", tags=route_tags("/api/poi/frequentation/comparer"))
def poi_frequentation_comparer(ids: str, day: date | None = None):
    poi_ids = [poi_id.strip() for poi_id in ids.split(",") if poi_id.strip()]
    if not 2 <= len(poi_ids) <= 10:
        raise HTTPException(422, "Il faut fournir entre 2 et 10 identifiants de POI.")
    day = day or date.today() + timedelta(days=1)
    index = _require_poi_index()
    unknown = [poi_id for poi_id in poi_ids if index.get(poi_id) is None]
    if unknown:
        raise HTTPException(404, f"POI inconnus : {', '.join(unknown)}")
    if S.frequentation is None:
        raise HTTPException(503, "Modèle de fréquentation indisponible.")
    predictions = []
    for poi_id in poi_ids:
        item = index.get(poi_id)
        prediction = S.frequentation.predict_poi(item, day, 1)
        predictions.append({"poi": poi_response(item), **prediction})
    return {"day": day.isoformat(), **compare_predictions(predictions)}


@app.get("/api/poi/{poi_id}/frequentation", tags=route_tags("/api/poi/{poi_id}/frequentation"))
def poi_frequentation(
    poi_id: str,
    start: date | None = None,
    days: int = Query(7, ge=1, le=14),
):
    index = _require_poi_index()
    item = index.get(poi_id)
    if item is None:
        raise HTTPException(404, f"POI {poi_id} inconnu")
    if S.frequentation is None:
        raise HTTPException(503, "Modèle de fréquentation indisponible.")
    start = start or date.today() + timedelta(days=1)
    prediction = S.frequentation.predict_poi(item, start, days)
    return {"poi": poi_response(item), **prediction}


@app.get("/api/poi/{poi_id}/horaires", tags=route_tags("/api/poi/{poi_id}/horaires"))
def poi_horaires(poi_id: str, day: date | None = None):
    index = _require_poi_index()
    item = index.get(poi_id)
    if item is None:
        raise HTTPException(404, f"POI {poi_id} inconnu")
    if S.horaires is None:
        raise HTTPException(503, "Profils horaires indisponibles.")
    day = day or date.today() + timedelta(days=1)
    day_type = type_jour(day)
    source = S.frequentation.source(item, day) if S.frequentation else None
    calibrage = "relatif"
    profile = None
    warnings = []
    if source:
        if source["type"] == "ens":
            calibrage = "calibré lieu"
            warnings.append("Profil moyen du compteur ENS sur les 3 dernières années, pas une prévision du jour.")
            series = S.horaires.get("ens", {}).get(str(source["site_id"]), {})
        else:
            calibrage = "calibré zone"
            warnings.append("Heures de passage des véhicules sur la route d'accès (sens montée), pas sur le lieu.")
            series = S.horaires.get("routes", {}).get(source["station"], {})
        profile = series.get(day_type)
        source = {**source, "n_jours": int(profile["n_jours"]) if profile else 0}
    if profile is None:
        warnings.append("Aucun comptage horaire pour ce lieu.")
        parts = None
        advice = None
    else:
        parts = [round(float(value), 3) for value in profile["parts"]]
        advice = conseil_horaire(profile["parts"])
    return {
        "poi": poi_response(item),
        "day": day.isoformat(),
        "type_jour": day_type,
        "calibrage": calibrage,
        "source": source,
        "parts": parts,
        "conseil": advice,
        "avertissements": warnings,
    }


@app.get("/api/poi/{poi_id}/similaires", tags=route_tags("/api/poi/{poi_id}/similaires"))
def poi_similaires(
    poi_id: str,
    k: int = 10,
    rayon_km: float | None = Query(None, gt=0),
    categories: str | None = None,
    affiner: bool = True,
):
    index = _require_poi_index()
    source = index.get(poi_id)
    if source is None:
        raise HTTPException(404, f"POI {poi_id} inconnu")
    selected_categories = [item.strip() for item in categories.split(",") if item.strip()] if categories else None
    results, affinage = index.similar(
        poi_id,
        k=min(max(k, 1), 50),
        rayon_km=rayon_km,
        categories=selected_categories,
        affiner=affiner,
    )
    items = [poi_response(item) for item in results]
    return {
        "poi": poi_response(source),
        "items": items,
        "count": len(items),
        "affinage": affinage,
    }


@app.get("/api/poi/{poi_id}", tags=route_tags("/api/poi/{poi_id}"))
def poi_detail(poi_id: str):
    index = _require_poi_index()
    item = index.get(poi_id)
    if item is None:
        raise HTTPException(404, f"POI {poi_id} inconnu")
    return poi_response(item)


@app.get("/api/status")
def status():
    m = json.loads(METRICS_PATH.read_text()) if METRICS_PATH.exists() else {}
    return {
        "departement": C.DEPARTEMENT,
        "prevision_ens": bool(S.forecaster),
        "frequentation_poi": bool(S.frequentation),
        "index_poi": bool(S.poi_index),
        "horaires": bool(S.horaires),
        "geovelo": bool(C.secret("GEOVELO_API_KEY")),
        "apidae": bool(C.secret("APIDAE_API_KEY")),
        "ajustement": bool(C.secret("CLAUDE_CODE_OAUTH_TOKEN")),
        "metrics": {k: v for k, v in m.items() if k not in ("per_site", "site_categories")},
    }


@app.post("/api/marguerite/apidae")
def marguerite_apidae(body: MargueriteApidaeRequest):
    try:
        return M.apidae_search(
            body.selectionIds,
            body.lat,
            body.lon,
            body.radiusKm,
            body.count,
            body.first,
        )
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    except RuntimeError as error:
        raise HTTPException(502, str(error)) from error


@app.post("/api/marguerite/geovelo")
def marguerite_geovelo(body: MargueriteGeoVeloRequest):
    try:
        points = [(point.lat, point.lon) for point in body.points]
        if body.profil is not None:
            return M.geovelo_route(points, body.velo, body.profil, body.instructions)
        if body.instructions:
            if len(points) < 3:
                return M.geovelo_loop(points, body.velo)
            return M.geovelo_route(points, body.velo, instructions=True)
        return M.geovelo_loop(points, body.velo)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    except RuntimeError as error:
        raise HTTPException(502, str(error)) from error


def _agent_rate_limited(client_ip: str) -> bool:
    now = time.monotonic()
    with _AGENT_RATE_LOCK:
        for ip, calls in list(_AGENT_CALLS.items()):
            while calls and now - calls[0] >= _AGENT_RATE_WINDOW_S:
                calls.popleft()
            if not calls:
                del _AGENT_CALLS[ip]
        calls = _AGENT_CALLS.setdefault(client_ip, deque())
        if len(calls) >= _AGENT_RATE_LIMIT:
            return True
        calls.append(now)
    return False


def _purge_agent_jobs(now: float) -> None:
    for job_id, job in list(_AGENT_JOBS.items()):
        finished_at = job["finished_at"]
        if finished_at is not None and now - finished_at >= _AGENT_JOB_TTL_S:
            del _AGENT_JOBS[job_id]


def _append_agent_progress(job_id: str, text: str) -> None:
    with _AGENT_JOBS_LOCK:
        job = _AGENT_JOBS.get(job_id)
        if job is not None and job["etat"] == "en_cours":
            job["progression"].append({
                "t": round(max(0, time.monotonic() - job["started_at"]), 2),
                "texte": text,
            })


def _expire_agent_job(job_id: str, finished_at: float) -> None:
    with _AGENT_JOBS_LOCK:
        job = _AGENT_JOBS.get(job_id)
        if job is not None and job["finished_at"] == finished_at:
            del _AGENT_JOBS[job_id]


def _finish_agent_job(job_id: str, etat: str, resultat=None, erreur=None) -> None:
    finished_at = time.monotonic()
    with _AGENT_JOBS_LOCK:
        job = _AGENT_JOBS.get(job_id)
        if job is None:
            return
        job.update(
            etat=etat,
            resultat=resultat,
            erreur=erreur,
            finished_at=finished_at,
        )
    try:
        asyncio.get_running_loop().call_later(
            _AGENT_JOB_TTL_S,
            _expire_agent_job,
            job_id,
            finished_at,
        )
    except RuntimeError:
        pass


async def _run_agent_job(job_id: str, payload: dict) -> None:
    try:
        resultat = await asyncio.to_thread(
            MA.run_agent,
            payload,
            lambda text: _append_agent_progress(job_id, text),
        )
    except ValueError as error:
        _finish_agent_job(job_id, "erreur", erreur={"code": 422, "detail": str(error)})
    except TimeoutError as error:
        _finish_agent_job(job_id, "erreur", erreur={"code": 504, "detail": str(error)})
    except RuntimeError as error:
        _finish_agent_job(job_id, "erreur", erreur={"code": 502, "detail": str(error)})
    except asyncio.CancelledError:
        _finish_agent_job(
            job_id,
            "erreur",
            erreur={"code": 504, "detail": "L'ajustement a été interrompu."},
        )
        raise
    except Exception:
        _finish_agent_job(
            job_id,
            "erreur",
            erreur={"code": 502, "detail": "Erreur inattendue pendant l'ajustement."},
        )
    else:
        _finish_agent_job(job_id, "termine", resultat=resultat)
    finally:
        _AGENT_SEMAPHORE.release()


@app.post("/api/marguerite/agent", status_code=202)
async def marguerite_agent(body: MargueriteAgentRequest, request: Request):
    forwarded_ip = request.headers.get("CF-Connecting-IP", "").split(",", 1)[0].strip()
    client_ip = forwarded_ip or (request.client.host if request.client else "inconnu")
    if _agent_rate_limited(client_ip):
        raise HTTPException(429, "Limite de 10 appels par IP sur 10 minutes dépassée.")
    if not _AGENT_SEMAPHORE.acquire(blocking=False):
        raise HTTPException(
            429,
            "Ajustement déjà en cours pour d'autres visiteurs, réessayez dans un instant.",
        )
    job_id = uuid4().hex
    now = time.monotonic()
    with _AGENT_JOBS_LOCK:
        _purge_agent_jobs(now)
        if len(_AGENT_JOBS) >= _AGENT_JOB_LIMIT:
            _AGENT_SEMAPHORE.release()
            raise HTTPException(429, "Trop de demandes en cours, réessayez dans un instant.")
        _AGENT_JOBS[job_id] = {
            "etat": "en_cours",
            "started_at": now,
            "finished_at": None,
            "progression": [],
            "resultat": None,
            "erreur": None,
        }
    try:
        task = asyncio.create_task(_run_agent_job(job_id, body.model_dump(mode="json")))
    except Exception:
        with _AGENT_JOBS_LOCK:
            _AGENT_JOBS.pop(job_id, None)
        _AGENT_SEMAPHORE.release()
        raise
    _AGENT_TASKS.add(task)
    task.add_done_callback(_AGENT_TASKS.discard)
    return {"job": job_id}


@app.get("/api/marguerite/agent/{job}")
def marguerite_agent_status(job: str):
    with _AGENT_JOBS_LOCK:
        _purge_agent_jobs(time.monotonic())
        record = _AGENT_JOBS.get(job)
        if record is None:
            raise HTTPException(404, "Tâche inconnue.")
        return {
            "etat": record["etat"],
            "progression": [dict(item) for item in record["progression"]],
            "resultat": record["resultat"],
            "erreur": record["erreur"],
        }


