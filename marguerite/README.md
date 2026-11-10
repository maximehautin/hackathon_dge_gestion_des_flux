# Marguerite : séjours à vélo en étoile en Isère

Projet de l'**Équipe 4** au hackathon DGE « Gestion des flux touristiques » (9 et 10 novembre 2026, territoire test : l'Isère).

Démo en ligne : https://flux-isere.antoine42.com/marguerite/v2

## Le problème

Les planificateurs de voyage à vélo sont pensés pour l'itinérance. Rien n'aide le visiteur qui loge au même endroit et rayonne chaque jour à vélo. Or ce séjour « en étoile » est celui qui répartit le mieux les visiteurs : dans le temps (on choisit le jour le plus calme pour chaque site), dans l'espace (une direction différente chaque jour) et vers les commerces locaux placés sur les boucles.

## Ce que fait Marguerite

1. **Profil** : composition du groupe, dates, distance à vélo par jour, type de vélo.
2. **Envies** : le visiteur trie des activités réelles de toute l'Isère (2 426 fiches Apidae, filtrées selon la saison).
3. **Camp de base** : l'application propose les communes où loger qui donnent accès au plus d'activités aimées par des voies cyclables.
4. **Programme** : une boucle par jour, au départ de l'hébergement.
   - Les boucles privilégient les voies conseillées aux vélos et évitent les routes déconseillées.
   - Elles partent dans des directions variées autour du camp de base.
   - Les sites les plus fréquentés sont placés sur les jours les plus calmes du séjour.
5. **Ajustement en langage libre** : dans une journée, le visiteur écrit ce qu'il veut changer (« remplace la 1re étape par un lieu au bord de l'eau », « ajoute une pause gourmande », « moins de dénivelé »). Le parcours est recalculé, et chaque retour tient compte des précédents.
6. **Professionnels du vélo** : loueurs, réparateurs et hébergements qui prêtent des vélos autour du camp de base.

## Lien avec les problématiques du hackathon

| Problématique | Réponse de Marguerite |
|---|---|
| Réorienter les flux | Lieux équivalents proposés quand un site est chargé ; ajustement libre des étapes |
| Anticiper les pics | Prévision de fréquentation par lieu et par jour, utilisée pour placer les visites |
| Zones sur et sous-fréquentées | Boucles réparties dans toutes les directions, vers des lieux moins connus |
| Mobilités douces | Séjour entièrement à vélo, itinéraires GéoVélo sur voies aménagées |
| Profils des visiteurs | Profil déduit du tri d'activités, sans questionnaire |

## Architecture

```
web/            application (une page HTML générée par web/pipeline/build_app.py)
app/main.py     API FastAPI : sert la page et les endpoints ci-dessous
flux/           modules Python
  marguerite.py        relais Apidae et GéoVélo (les clés restent sur le serveur)
  marguerite_agent.py  ajustement d'une journée : lance Claude Code avec des outils
  marguerite_mcp.py    outils : recherche de lieux, affluence, calcul de boucle, validation
  frequentation.py     prévision de fréquentation d'un lieu
  forecast.py          prévision des éco-compteurs ENS
  horaires.py          profils horaires (compteurs ENS, comptages routiers SMMAG)
  poi.py               index sémantique de 14 000 lieux (Apidae et OpenStreetMap)
scripts/        construction des données : poi.py (index), build.py (modèles)
```

### API utilisées par l'application

| Endpoint | Rôle |
|---|---|
| `POST /api/marguerite/apidae` | Hébergements et lieux Apidae autour d'un point |
| `POST /api/marguerite/geovelo` | Itinéraire vélo (profil touristique, type de voie par tronçon) |
| `GET /api/poi/{poi_id}/frequentation` | Fréquentation prévue d'un lieu, jour par jour |
| `GET /api/poi/frequentation/comparer` | Classe plusieurs lieux pour un jour donné |
| `GET /api/poi/recherche` | Recherche de lieux en texte libre |
| `GET /api/poi/{poi_id}/similaires` | Lieux offrant une expérience comparable |
| `GET /api/poi/{poi_id}/horaires` | Heures de pointe d'un lieu, quand un comptage existe |
| `POST /api/marguerite/agent` puis `GET /api/marguerite/agent/{job}` | Ajustement d'une journée et suivi de sa progression |

La documentation interactive est sur `/docs`.

### Prévision de fréquentation : trois niveaux

- **Calibré lieu** : un éco-compteur ENS à moins de 500 m. Renvoie des passages par jour et un indice de saturation.
- **Calibré zone** : une route d'accès comptée par le SMMAG dessert la commune. Renvoie des véhicules par jour : c'est la fréquentation de la zone, pas celle du lieu.
- **Relatif** : tous les autres lieux. Renvoie seulement « plus » ou « moins » de monde qu'un jour habituel.

## Données

- Apidae (lieux, hébergements, commerces), DATAtourisme et OpenStreetMap (loueurs et réparateurs de vélos).
- GéoVélo (itinéraires).
- Éco-compteurs des espaces naturels sensibles de l'Isère, comptages routiers SMMAG, ventes de forfaits, compteurs vélo.
- Météo Open-Meteo, calendrier scolaire.

Les données du hackathon ne sont pas dans ce dépôt. Elles se téléchargent depuis le SSP Cloud (`projet-hackathon-gestion-flux-isere/diffusion/`).

## Lancer le projet

```bash
pip install -r requirements.txt
export FLUX_DATA_DIR=/chemin/vers/diffusion     # données du SSP Cloud
export APIDAE_API_KEY=... GEOVELO_API_KEY=...   # clés du hackathon (onglet Codes de l'inventaire)
python scripts/poi.py collect && python scripts/poi.py index   # index des lieux
python scripts/build.py                          # modèles de fréquentation
python web/pipeline/build_app.py                 # page de l'application
uvicorn app.main:app --port 8000                 # puis ouvrir http://localhost:8000
```

Ou avec Docker : `docker compose up --build`.

Deux clés facultatives : `OPENROUTER_API_KEY` affine le classement de la recherche de lieux, et `CLAUDE_CODE_OAUTH_TOKEN` active l'ajustement en langage libre. Sans elles, le reste fonctionne. Aucune clé n'est écrite dans le code ni dans la page servie.

## Limites

- La prévision donne un ordre de grandeur : sur des lieux jamais vus, elle trouve la bonne tendance environ une fois sur deux, contre une fois sur trois pour une méthode naïve.
- Le ski et les lieux couverts sont peu fiables, faute de comptages.
- Les seuils de saturation sont provisoires et ne sont pas des capacités écologiques validées.
- Les horaires d'ouverture des lieux ne sont pas vérifiés automatiquement.
- La dépense locale affichée repose sur une hypothèse de 68 € par personne et par jour.
