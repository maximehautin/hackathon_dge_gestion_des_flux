# Architecture — Dashboard Flux Touristiques

## Vue d'ensemble

L'application est composée de deux services Docker orchestrés par `docker-compose` :

```
┌─────────────────────────────────────────────────────┐
│  docker-compose                                     │
│                                                     │
│  ┌─────────────────┐       ┌───────────────────┐   │
│  │   frontend      │       │      api          │   │
│  │   Nuxt 3 (SSR)  │──────▶│   FastAPI + ML    │   │
│  │   :3000         │ HTTP  │   :8000           │   │
│  └─────────────────┘       └────────┬──────────┘   │
│                                     │               │
│                             ┌───────▼──────┐        │
│                             │  mlflow_data │        │
│                             │  (volume)    │        │
│                             └──────────────┘        │
└─────────────────────────────────────────────────────┘
```

## Service `api` — Python / FastAPI

**Rôle :** pipeline ML complet + exposition REST.

| Fichier       | Rôle                                                        |
|---------------|-------------------------------------------------------------|
| `main.py`     | Entrypoint FastAPI, routes HTTP                             |
| `predict.py`  | Prédiction J+7, retourne un dict JSON                       |
| `train.py`    | Entraînement XGBoost, logging MLflow (CLI uniquement)       |
| `sites.py`    | Catalogue multi-sites (coords, seuils, chemins CSV)         |
| `config.py`   | MLflow URI, liste de features, hyperparamètres              |
| `utils.py`    | Fetch température historique (Open-Meteo Archive)           |

### Endpoints

| Méthode | Route                   | Description                                |
|---------|-------------------------|--------------------------------------------|
| `GET`   | `/health`               | Health check                               |
| `GET`   | `/sites`                | Liste des sites avec flag `has_data`       |
| `GET`   | `/predict/{site_id}`    | Projection J+7 pour un site (JSON)         |

### Format de réponse `/predict/{site_id}`

```json
{
  "site": { "id": "herretang", "nom": "Herretang — Tuilerie", "commune": "Saint-Joseph-de-Rivière" },
  "capacite": 320,
  "seuils_abs": { "modere": 192, "eleve": 272 },
  "predictions": [
    {
      "date": "2026-11-11",
      "passages_prevus": 145,
      "risque": "FAIBLE",
      "charge": 0.453,
      "temperature_moy": 8.2,
      "precipitations_mm": 0.0,
      "pluie_heures": 0.0,
      "neige": false,
      "weekend": false,
      "jour_ferie": true,
      "vacances": false
    }
  ]
}
```

### Sources de données externes (appelées à la prédiction)

- **Open-Meteo Forecast** — prévisions météo J+7 (gratuit, sans clé)

Jours fériés et vacances scolaires sont chargés depuis des fichiers JSON bundlés dans `src/data/calendrier/` — aucun appel API à la prédiction.

## Service `frontend` — Nuxt 3 (SSR)

**Rôle :** BFF (Backend For Frontend) + UI Vue.

Les server endpoints Nuxt (`server/api/`) proxyfient vers `http://api:8000` via le réseau interne Docker. Le frontend Vue consomme uniquement l'API Nuxt — jamais Python directement.

```
Navigateur
    │  GET /api/predict/herretang
    ▼
Nuxt server endpoint          → $fetch("http://api:8000/predict/herretang")
    │  JSON
    ▼
Composant Vue (dashboard)
```

Variable d'environnement côté Nuxt : `NUXT_API_BASE_URL=http://api:8000`.

## MLflow

Le modèle est entraîné hors ligne avec `python train.py --site herretang` puis stocké dans le volume `mlflow_data` (SQLite + artefacts). La prédiction charge le run avec la meilleure MAE sur le holdout 2025.

## Démarrage

```bash
# 1. Copier et renseigner les variables d'environnement
cp .env.example .env

# 2. Entraîner le modèle (une fois, hors Docker)
cd src/api && python train.py --site herretang

# 3. Lancer l'ensemble
docker compose up --build
```

## Structure du repo

```
/
├── src/
│   ├── api/                # Service Python
│   │   ├── Dockerfile
│   │   ├── requirements.txt
│   │   ├── main.py         # FastAPI
│   │   ├── predict.py
│   │   ├── train.py
│   │   ├── sites.py
│   │   ├── config.py
│   │   └── utils.py
│   ├── frontend/           # Service Nuxt 3
│   │   ├── Dockerfile
│   │   └── ...             # à init avec : npx nuxi init src/frontend
│   ├── data/               # Données de fréquentation + calendrier bundlé (montés en lecture seule)
│   │   ├── calendrier/
│   │   │   ├── jours_feries_metropole.json
│   │   │   └── vacances_grenoble.json
│   │   ├── herretang_2020_2025/
│   │   ├── veronniere_2020_2025/
│   │   ├── ecouges_pont_chabert_2020_2025/
│   │   ├── etang_serre_observatoire_2020_2025/
│   │   ├── etang_lemps_sentier_2020_2025/
│   │   ├── etang_lemps_observatoire_2020_2025/
│   │   └── lac_save_ouest_2020_2025/
│   └── docs/               # Documentation
│   └── docker-compose.yml
├── .env.example
```
