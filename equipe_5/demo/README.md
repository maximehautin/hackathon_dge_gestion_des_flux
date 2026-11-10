# Démo live : borne de captation du ressenti des visiteurs

Implémentation de la spec [`context/demo_live_avis.md`](../context/demo_live_avis.md).

Un visiteur parle à une borne posée près du parking d'un Espace Naturel Sensible (ENS)
équipé d'un éco-compteur. Sa parole est transcrite localement (faster-whisper, CPU), puis
classifiée par Jev (OpenRouter) en critères : satisfaction, affluence ressentie, provenance,
transport et profil. Le résultat est croisé avec la fréquentation mesurée par l'éco-compteur.

L'écran projeté a deux colonnes, séparées par un trait vertical :

- à gauche, la partie technique : enregistrement, transcription live, dernières lignes de la base ;
- à droite, l'app « La borne qui écoute » dans un mockup de téléphone, avec la carte des 5
  bornes sur le plan IGN (en niveaux de gris). Changer de critère ne recharge ni le fond de
  carte ni la taille des cercles : seules leur couleur et leur tooltip changent.
  - La taille d'un cercle représente la fréquentation (éco-compteur, simulée).
  - Sa couleur représente le critère choisi : satisfaction (rouge → vert), affluence
    (bleu → rouge) ou part hors département (jaune → violet).
  - Une borne sans avis est en gris neutre.

**Données manquantes (Jev).** Une colonne est NULL quand l'information n'est pas dans la
transcription :

- pour un score, une question `noul` associée (`satisfaction_present`, `affluence_present`)
  dit si l'information est présente ;
- pour un choix, Jev peut répondre la catégorie `missing`.

Le seuil de confiance `SEUIL_CONFIANCE` s'applique en plus.

## Installation (laptop de démo)

```bash
uv sync                                   # Python >= 3.12
sudo apt-get install -y libportaudio2     # Linux uniquement : PortAudio pour le micro
export OPENROUTER_API_KEY=sk-or-...       # clé OpenRouter (classeur Excel du SSP Cloud)
```

La clé doit être définie dans les **deux** terminaux : le worker classifie les nouveaux avis,
et l'app appelle Jev elle-même pour **Re-classifier**, une correction ou une saisie manuelle.

Les données de référence sont lues dans `data/ssp/` ou `../onyxia-data/`, le premier
dossier présent étant retenu (fichier `Fréquentation/données_eco_compteurs_ENS.xlsx`).

**Avant le jour J, avec du réseau** : lancer une fois le worker ou le bench pour télécharger
le modèle dans `models/` (~480 Mo pour `small`). Ensuite le chargement se fait hors
ligne. Seule la classification Jev a besoin du réseau.

## Lancement (2 terminaux, depuis la racine du dépôt)

```bash
uv run python worker.py        # micro + VAD + STT + Jev (--model base si trop lent)
uv run streamlit run app.py    # écran du show (http://localhost:8501)
```

1. Choisir la **borne**, puis **● Enregistrer**. 1 enregistrement = 1 avis.
2. **■ Stop**, ou arrêt automatique après **15 s sans parole** (durée maximale : 120 s).
3. La transcription apparaît en base (`⏳ en cours`), puis elle est classifiée (`✅ ok`).
   En cas d'échec Jev (`⚠️ erreur`), cliquer sur **Re-classifier #id**.
4. Cliquer sur une ligne du tableau pour la détailler. Son texte est modifiable :
   **💾 Mettre à jour et re-classifier** enregistre la correction en base et relance Jev.
5. Sans ligne sélectionnée (**✖ Fermer**), un avis peut être saisi à la main, sans audio :
   **✍️ Ajouter l'avis et classifier** le crée sur la borne choisie.

Dans l'app, ◀ / ▶ à droite de la date naviguent entre les demi-journées ; le badge **LIVE**
indique la demi-journée en cours.

Un enregistrement sans parole ne crée **aucune ligne** et ne déclenche pas d'appel à Jev
(« rien capté »). Si le worker ne donne plus signe de vie depuis 5 s, un bandeau
« Worker arrêté » s'affiche.

## Préparation de la base (avant le show)

```bash
DEMO_PREP=1 uv run streamlit run app.py
```

Ce mode ajoute les champs **date simulée** et **heure** : les avis enregistrés sont horodatés
à cette date et marqués `is_init=1`. Il sert à peupler des demi-journées passées avec de
vrais avis de l'équipe. Les dates futures sont refusées. Ce mode n'existe pas sans la
variable d'environnement, donc il ne peut pas être déclenché par erreur pendant le show.

La base est `data/demo.db`, à la racine du dépôt (gitignorée). **En fin de hackathon :**
`rm data/demo.db`.

## Options utiles

| Besoin | Commande |
|---|---|
| Choisir le micro | `python worker.py --list-devices`, puis `--device <index>` |
| Mesurer la latence STT | `python bench.py voix.wav` (reporter dans [`BENCH.md`](BENCH.md)) |
| Couper les partiels live (stretch 1) | `python worker.py --no-partiels` |
| Répéter sans micro | `python worker.py --simulate a.wav b.wav` (un fichier par enregistrement) |
| Autre base | `DEMO_DB=/chemin/demo.db` (pour les deux processus) |
| Seuil de confiance Jev (NULL en dessous) | `SEUIL_CONFIANCE=0.4` (à fixer au jour 1) |
| Modèle Jev | `JEV_MODEL=typesafe/jev-1.14` (défaut), `JEV_TIMEOUT_S=20` |
| Langues candidates / défaut | `DEMO_LANGS=fr,en,de,it,nl,es`, `DEMO_DEFAULT_LANG=fr` |

Les bornes sont des paramètres, définis dans [`bornes.yaml`](bornes.yaml). Pour un autre
département, il suffit d'un autre fichier de ce format et d'un autre jeu de compteurs.

## Modules

| Fichier | Rôle |
|---|---|
| `worker.py` | micro, VAD, STT, arrêt automatique, appel Jev |
| `app.py` | Streamlit (2 colonnes) |
| `db.py` | schéma SQLite (WAL), requêtes, agrégats par borne |
| `jev.py` | client HTTP de l'API Decisions (seul module à effets de bord réseau) |
| `mapping.py` | pur : questions Jev, réponse vers colonnes, seuil de confiance |
| `bornes.yaml`, `bornes.py` | les 5 bornes ENS et leur chargement |
| `periods.py` | demi-journées (Europe/Paris), calculées côté app |
| `reference.py` | fréquentation éco-compteurs : moyenne du mois, ramenée à la demi-journée |

## Tests

```bash
uv run pytest -q
```

Les tests ne font aucun appel réseau et ne lisent pas les données privées. Ils couvrent :

- les demi-journées (cas figés, heure d'été et heure d'hiver) ;
- le mapping Jev (seuil, refus, score vers 0..100) et le client HTTP (mocké) ;
- `reference.py` sur un classeur factice ;
- la base (futur refusé, cascade, agrégats, commandes) ;
- les invariants du worker (§2) avec un faux micro, une fausse VAD, un faux STT et un faux Jev.

## Checklist jour 1 (§10)

- [ ] `bench.py` sur le laptop de démo avec une vraie voix : `small` et `base`, chiffres dans `BENCH.md`.
- [ ] Premier appel Jev réel : vérifier `jev_raw` (détail d'une ligne), le modèle servi
  (`jev-1.14` n'apparaît pas encore dans la doc OpenRouter, qui ne cite que `jev-1.13`) et la
  présence de `confidence` par question.
- [ ] Fixer `SEUIL_CONFIANCE` sur une dizaine d'avis réels. Vérifier qu'un avis sans mention
  de transport donne bien `transport` NULL (`missing`), et un avis qui ne parle pas d'affluence
  `affluence` NULL (`affluence_present`).
- [ ] Micro : `--list-devices`, puis test en salle (bruit, arrêt automatique intempestif).
- [ ] Coordonnées des bornes recalées sur le parking (OpenStreetMap), électricité, commune.
- [ ] Modèle déjà téléchargé ; test Wi-Fi coupé (le STT marche, Jev passe en erreur).
- [ ] Partage de connexion 4G prêt.
