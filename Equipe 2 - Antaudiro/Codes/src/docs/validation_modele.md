## Vue d'ensemble de la stratégie de validation

Valider un modèle de prédiction ne se réduit pas à calculer une erreur sur un jeu de test. Pour qu'un modèle soit utilisable en production — c'est-à-dire pour informer des décisions réelles de gestion de flux —, il faut répondre à plusieurs questions distinctes :

1. Le modèle apprend-il quelque chose de réel, ou mémorise-t-il les données d'entraînement ?
2. Ses prédictions sont-elles meilleures que celles d'une règle simple sans apprentissage ?
3. Ses performances se maintiennent-elles sur des données jamais vues, y compris dans le futur ?
4. Se comporte-t-il de la même façon sur des sites différents, ou dépend-il trop du site d'entraînement ?

La stratégie mise en place repose sur **trois niveaux de test imbriqués** et une **comparaison à une baseline naïve**. Chaque niveau répond à une question différente et produit des métriques interprétables par les gestionnaires de sites.

```
Données 2020-2024-2025-2026
│
├── Niveau 1 : Split Train / Holdout
│   ├── Train     2020–2024  →  entraînement du modèle
│   └── Holdout   2025       →  sélection du meilleur run + première évaluation
│
├── Niveau 2 : Comparaison baseline naïve
│   └── Sur le même holdout 2025 : XGBoost vs "je prédit ce qui s'est passé il y a 7 jours"
│
└── Niveau 3 : Backtest hors-échantillon
    └── Backtest  2026       →  validation finale sur données jamais vues
```

---

## Niveau 1 — Split temporel Train / Holdout

### Principe

Le jeu de données est découpé **chronologiquement** : les années les plus anciennes servent à entraîner le modèle, l'année la plus récente disponible lors de l'entraînement sert à l'évaluer.

| Jeu | Période | Rôle | Taille (Herretang) |
|---|---|---|---|
| Train | **2022–2024** | Apprentissage des paramètres XGBoost | ~1 095 jours |
| Holdout | 2025 | Évaluation et sélection du meilleur run | ~365 jours |

> **2020–2021 exclus du train** : années COVID atypiques (confinements, réouvertures par décret). Ces données sont conservées dans le CSV pour alimenter le lag J-365 des premières lignes de 2022, mais pas utilisées comme cibles d'entraînement.

### Pourquoi une découpe temporelle et non aléatoire ?

Dans une série temporelle, les données récentes dépendent des données passées (via les lags). Un découpage aléatoire laisserait fuiter des informations du futur vers le passé : le modèle verrait pendant l'entraînement des valeurs proches de celles qu'il doit prédire, ce qui gonfle artificiellement ses performances.

La découpe temporelle est l'unique façon correcte de simuler une mise en production réelle : on entraîne sur le passé connu et on évalue sur le futur inconnu.

### Risques de data leakage maîtrisés

- Les features de lag (`passages_j1`, `passages_j7`) utilisent uniquement des valeurs antérieures à la date prédite.
- La capacité de charge (P90) est calculée sur le train uniquement, jamais sur le holdout.
- La température journalière (Open-Meteo archive) est disponible pour toutes les dates sans risque de fuite.

### Résultats — Herretang Tuilerie (run xgb-run-1, meilleur MAE)

| Métrique | Valeur |
|---|---|
| MAE holdout 2025 | **20.31 passages/j** |
| RMSE holdout 2025 | voir MLflow (`rmse_holdout`) |
| MAPE holdout 2025 | voir MLflow (`mape_holdout`) |
| Précision alertes élevées | voir MLflow (`precision_alerte_elevee`) |
| Capacité de référence (P90 train) | 71 passages/jour |

La MAE de **20 passages/jour** signifie qu'en moyenne, le modèle se trompe de 20 unités sur une prédiction journalière. Sur un site dont la médiane dépasse rarement 50 passages/jour hors pic, c'est une erreur relative de l'ordre de 40 %, ce qui est acceptable pour un outil d'aide à la décision stratégique (planification des agents, communication préventive), mais insuffisant pour une gestion opérationnelle heure par heure.

---

## Niveau 2 — Biais de sélection et comparaison baseline naïve

### Le problème du biais de sélection

Lorsqu'on entraîne plusieurs versions d'un modèle (ici 3 runs avec des hyperparamètres différents) et qu'on choisit la meilleure selon la MAE sur le holdout, **la MAE du meilleur modèle est biaisée à la baisse**. Le modèle choisi est celui qui, par chance ou par sur-adaptation, performe le mieux sur cette période précise.

Ce biais est inévitable dès lors qu'on utilise le holdout pour la sélection. Il ne disparaît qu'avec un troisième jeu strictement indépendant — c'est l'objet du niveau 3.

### La baseline naïve : un test indispensable

Avant de conclure qu'un modèle ML apporte de la valeur, il faut le comparer à la stratégie la plus simple possible. Ici, la baseline naturelle est :

> **Prédire pour demain la valeur observée il y a 7 jours** (même jour de la semaine).

Cette règle n'utilise aucun algorithme d'apprentissage, aucun hyperparamètre, aucune météo. Elle exploite uniquement la structure hebdomadaire de la fréquentation. Si XGBoost ne bat pas cette baseline de façon significative, l'investissement en modélisation n'est pas justifié.

| Modèle | MAE | RMSE | Précision alertes |
|---|---|---|---|
| XGBoost (meilleur run) | **60.1** passages/j (backtest avril 2026) | 100.0 | 14 % |
| Baseline naïve (lag J-7) | 61.4 passages/j | 96.9 | 57 % |

Sur 3 semaines en mode multi : XGBoost MAE=30.1 vs baseline MAE=31.5 — même précision alertes (57 %).

La baseline peut être calculée directement sur le holdout sans entraînement :

```bash
# Calcul de la MAE baseline sur le holdout 2025
python3 -c "
import pandas as pd, numpy as np
df = pd.read_csv('src/data/herretang_2020_2025/journalier_herretang_2020_2025.csv', sep=';', encoding='utf-8-sig')
df = df[df['jour_complet'] == 1].copy()
df['date'] = pd.to_datetime(df['date'])
daily = df.set_index('date')['passages_jour'].sort_index()
hold = daily[daily.index.year == 2025]
pred = hold.index.map(lambda d: daily.get(d - pd.Timedelta(days=7), np.nan))
valid = ~pd.isna(pred)
mae = np.mean(np.abs(hold[valid].values - pred[valid]))
print(f'MAE baseline naïve (lag J-7) sur holdout 2025 : {mae:.1f} passages/j')
"
```

### Pourquoi cette comparaison est importante pour le client

Un gestionnaire de site n'a pas besoin d'un modèle ML pour savoir que le samedi de printemps est plus fréquenté que le mardi d'hiver. Ce qu'il attend d'un système intelligent, c'est de détecter les déviations par rapport à ce schéma habituel : un weekend pluvieux, un jour férié chômé, une vague de chaleur exceptionnelle. La valeur de XGBoost réside précisément dans sa capacité à pondérer ces facteurs — capacité que la baseline naïve n'a pas.

---

## Niveau 3 — Backtest hors-échantillon 2026

### Principe et enjeu

Le backtest hors-échantillon est le test le plus rigoureux du pipeline. Il simule une mise en production réelle : le modèle, entraîné et sélectionné sur 2023–2025, est utilisé pour prédire des semaines de 2026 — des données que ni l'entraînement ni la sélection n'ont jamais touchées.

```
Chronologie des données

2023 ─────── 2024 ─────── 2025 ─────── 2026
│── Train ──────│── Holdout ──│── Backtest ──│
     ↓                 ↓              ↓
  Apprentissage   Sélection du   Test final :
                 meilleur run   données inconnues
```

### Données utilisées en 2026

Les archives ENS CG38 Environnement fournissent les comptages réels pour 2026 (jusqu'à mai 2026 pour Herretang). La météo est récupérée via l'API Open-Meteo archive, identique à la source utilisée à l'entraînement. Le calendrier (jours fériés, vacances) est chargé depuis les fichiers JSON bundlés dans `src/data/calendrier/`.

### Résultat A — Semaine du 15 au 21 avril 2026 (mode `single`)

Capacité de référence : 71 passages/j. Seuils : MODÉRÉ ≥ 43 passages/j · ÉLEVÉ ≥ 60 passages/j.

| Jour | Réel | XGBoost | Naïf (J-7) | Err% XGB | Alerte réelle | XGB ? | Naïf ? |
|---|---|---|---|---|---|---|---|
| Mer 15/04 | 288 | 35 | 50 | 88 % | ÉLEVÉ | ✗ | ✗ |
| Jeu 16/04 | 42 | 54 | 40 | 29 % | FAIBLE | ✗ | ✓ |
| Ven 17/04 | 102 | 61 | 32 | 40 % | ÉLEVÉ | ✓ | ✗ |
| Sam 18/04 | 54 | 71 | 5 | 31 % | MODÉRÉ | ✗ | ✗ |
| Dim 19/04 | 28 | 79 | 1 | 182 % | FAIBLE | ✗ | ✓ |
| Lun 20/04 | 16 | 48 | 0 | 200 % | FAIBLE | ✗ | ✓ |
| Mar 21/04 | 28 | 43 | 0 | 54 % | FAIBLE | ✗ | ✓ |

| Métrique | XGBoost | Baseline naïve |
|---|---|---|
| MAE (passages/j) | 60.1 | 61.4 |
| RMSE | 100.0 | 96.9 |
| MAPE | 89.1 % | 77.6 % |
| Précision alertes | **14 %** | **57 %** |

**Lecture :** le 15 avril (288 passages réels, 4× la capacité) écrase toutes les métriques. Ni XGBoost ni la baseline ne l'anticipent — c'est un pic événementiel hors des features disponibles. Sur les 6 autres jours, XGBoost a une MAE similaire à la baseline mais sur-estime les jours creux (lundi-mardi), ce qui lui fait rater les alertes de niveau FAIBLE → la baseline, qui prédit 0 passage (semaine précédente calme), classe correctement ces jours-là.

### Résultat B — Backtest multi-périodes (3 semaines, mode `multi`)

Périodes testées : hiver (2–8 février), printemps précoce (7–13 avril), début-mai (29 avril – 5 mai).

**Période 1 — Hiver : 2 au 8 février 2026**

| Jour | Réel | XGBoost | Naïf (J-7) | Err% XGB | Alerte réelle | XGB ? | Naïf ? |
|---|---|---|---|---|---|---|---|
| Lun 02/02 | 13 | 25 | 9 | 92 % | FAIBLE | ✓ | ✓ |
| Mar 03/02 | 7 | 19 | 7 | 171 % | FAIBLE | ✓ | ✓ |
| Mer 04/02 | 21 | 22 | 1 | 5 % | FAIBLE | ✓ | ✓ |
| Jeu 05/02 | 26 | 27 | 22 | 4 % | FAIBLE | ✓ | ✓ |
| Ven 06/02 | 6 | 32 | 3 | 433 % | FAIBLE | ✓ | ✓ |
| Sam 07/02 | 9 | 33 | 45 | 267 % | FAIBLE | ✓ | ✗ |
| Dim 08/02 | 46 | 41 | 20 | 11 % | MODÉRÉ | ✗ | ✗ |

XGBoost proche de la réalité en semaine (erreurs absolues faibles) mais surestime le samedi, et manque le dimanche MODÉRÉ. La baseline rate le samedi (elle prédit 45 car la semaine précédente avait un samedi chargé) et manque aussi le dimanche.

**Période 2 — Printemps précoce : 7 au 13 avril 2026**

| Jour | Réel | XGBoost | Naïf (J-7) | Err% XGB | Alerte réelle | XGB ? | Naïf ? |
|---|---|---|---|---|---|---|---|
| Mar 07/04 | 57 | 53 | 13 | 7 % | MODÉRÉ | ✓ | ✗ |
| Mer 08/04 | 50 | 53 | 27 | 6 % | MODÉRÉ | ✓ | ✗ |
| Jeu 09/04 | 40 | 67 | 77 | 68 % | FAIBLE | ✗ | ✗ |
| Ven 10/04 | 32 | 68 | 27 | 112 % | FAIBLE | ✗ | ✓ |
| Sam 11/04 | 5 | 63 | 22 | 1 160 % | FAIBLE | ✗ | ✓ |
| Dim 12/04 | 1 | 30 | 66 | 2 900 % | FAIBLE | ✓ | ✗ |
| Lun 13/04 | 0 | 18 | 89 | — | FAIBLE | ✓ | ✗ |

XGBoost est le seul à détecter les deux jours MODÉRÉ (mardi et mercredi). En revanche il surestime massivement les jours du week-end qui étaient, en réalité, quasi vides (pluie ? site fermé ?) — d'où les erreurs relatives explosives. La baseline, qui se base sur la semaine précédente également chargée, rate complètement.

**Période 3 — Début mai : 29 avril au 5 mai 2026**

| Jour | Réel | XGBoost | Naïf (J-7) | Err% XGB | Alerte réelle | XGB ? | Naïf ? |
|---|---|---|---|---|---|---|---|
| Mer 29/04 | 27 | 30 | 30 | 11 % | FAIBLE | ✓ | ✓ |
| Jeu 30/04 | 5 | 72 | 21 | 1 340 % | FAIBLE | ✗ | ✓ |
| Ven 01/05 | 18 | 49 | 35 | 172 % | FAIBLE | ✗ | ✓ |
| Sam 02/05 | 42 | 67 | 52 | 60 % | FAIBLE | ✗ | ✗ |
| Dim 03/05 | 15 | 63 | 36 | 320 % | FAIBLE | ✗ | ✓ |
| **Lun 04/05** | **222** | **24** | **7** | **89 %** | **ÉLEVÉ** | **✗** | **✗** |
| Mar 05/05 | 8 | 3 | 2 | 62 % | FAIBLE | ✓ | ✓ |

Deuxième pic événementiel non anticipé : lundi 4 mai (222 passages, sans doute journée organisée). Ni XGBoost (prédit 24) ni la baseline (prédit 7) ne l'anticipent — même cause que le 15 avril.

**Synthèse multi-périodes**

| Métrique | XGBoost | Baseline naïve |
|---|---|---|
| MAE (passages/j) | **30.1** | 31.5 |
| RMSE | **51.5** | 56.1 |
| MAPE | 432.9 % | 827.6 % |
| Précision alertes | **57 %** | 57 % |
| MAE holdout 2025 (référence) | 20.3 | — |
| Apport XGBoost vs baseline | +4.2 % | — |

XGBoost fait légèrement mieux que la baseline en MAE et RMSE (+4 %) mais à même précision d'alerte. Il détecte mieux les jours MODÉRÉ (printemps) mais sur-estime les jours creux, ce qui annule l'avantage sur les alertes.

### Interprétation pour le client

**Ce que le backtest confirme :**

1. **Le modèle ne sur-apprend pas.** Hors pics événementiels, les erreurs sont stables entre 2025 et 2026.
2. **XGBoost apporte une valeur marginale mais réelle** sur MAE/RMSE par rapport à la règle naïve, avec un avantage net sur la détection des jours MODÉRÉ.
3. **Les pics événementiels sont le vrai angle mort.** Deux jours (15 avril et 4 mai) concentrent l'essentiel de l'erreur totale. Ces jours ont 3× à 4× la fréquentation attendue et aucune feature ne les signale à l'avance.

**Ce qu'il faut améliorer pour la production :**
- Intégrer des données d'événements (Apidae, OpenAgenda) pour signaler les sorties organisées.
- Ajouter des lags complémentaires (J-14, J-21) pour mieux saisir les tendances mensuelles.
- Entraîner sur une fenêtre plus longue (2021–2024) pour couvrir plus de configurations saisonnières.

### Lancer un backtest

```bash
# Période par défaut (15–21 avril 2026, site Herretang)
python3 src/poc_backtest.py

# Mode multi : 3 semaines réparties automatiquement
python3 src/poc_backtest.py --mode multi

# Autre période, autre site
python3 src/poc_backtest.py --date 2026-05-04 --jours 7 --site col-du-coq
```

---

## Métriques de validation

### Métriques quantitatives

| Métrique | Formule | Interprétation | Usage |
|---|---|---|---|
| **MAE** | mean(\|y - ŷ\|) | Erreur moyenne en passages/jour — même unité que la cible | Métrique principale, robuste aux valeurs extrêmes |
| **RMSE** | sqrt(mean((y - ŷ)²)) | Pénalise plus fortement les grosses erreurs | Sensible aux pics exceptionnels |
| **MAE normalisée** | MAE / médiane(holdout) × 100 | Erreur relative robuste — dénominateur = médiane, pas la valeur réelle | Comparaison fiable entre sites à volumes très différents |

> **Pourquoi remplacer le MAPE ?** Le MAPE (`|y - ŷ| / y`) explose mécaniquement quand `y` est proche de 0, ce qui arrive fréquemment sur les petits sites (étang Serre : médiane 6 passages/j, 48% des jours ≤ 5 passages en holdout). Un écart de 3 passages quand la réalité est 2 donne MAPE = 150% — sans que le modèle soit mauvais. La MAE normalisée utilise la **médiane** comme dénominateur, ce qui lui confère la même interprétabilité relative sans ce défaut.

La **MAE** est la métrique principale de sélection (`mae_holdout` dans MLflow) car elle est interprétable directement : "le modèle se trompe de N passages par jour en moyenne."

### Capacité de référence

La capacité journalière sert à calculer le taux de charge et à déclencher les niveaux d'alerte. Elle est estimée automatiquement au **percentile 90** du jeu d'entraînement : c'est le volume d'un "jour chargé mais pas exceptionnel" — un seuil réaliste qui correspond à environ 10 % des journées les plus fréquentées de l'historique.

Pour Herretang : capacité estimée à **71 passages/jour**.

### Métriques orientées métier : précision des alertes

Au-delà de l'erreur numérique, ce qui intéresse le gestionnaire d'un site c'est : **est-ce que le modèle aurait déclenché le bon niveau d'alerte ?**

| Niveau | Condition |
|---|---|
| FAIBLE | taux_charge < 60 % |
| MODÉRÉ | 60 % ≤ taux_charge < 85 % |
| ÉLEVÉ | taux_charge ≥ 85 % |

La métrique `precision_alerte_elevee` (enregistrée dans MLflow pour le holdout 2025) mesure le pourcentage de jours où le modèle classe correctement le niveau "élevé". C'est la traduction opérationnelle directe de la performance du modèle pour les gestionnaires.

---

## Multi-sites : portabilité du pipeline vs portabilité du modèle

### Une distinction essentielle

Il faut distinguer deux notions de portabilité :

**Portabilité du pipeline** : le même code, les mêmes features, le même algorithme peuvent être appliqués à n'importe quel site disposant d'un éco-compteur ENS. Chaque site produit son propre modèle entraîné sur son historique. C'est ce que ce projet implémente.

**Portabilité du modèle** : un modèle entraîné sur le site A serait utilisé directement pour prédire le site B. Cela ne fonctionne pas ici : les niveaux absolus de fréquentation, les patterns saisonniers et les capacités de charge sont trop hétérogènes d'un site à l'autre.

### Pourquoi tester sur plusieurs sites ?

Tester le pipeline sur plusieurs sites ENS remplit deux objectifs :

1. **Valider la généricité des features** : si les mêmes variables (météo, calendrier, lags) permettent de prédire correctement des sites de nature très différente (zone humide, col de montagne, bord de lac), le choix des features est robuste.

2. **Détecter les spécificités non capturées** : un site pour lequel les features échouent systématiquement indique un pattern particulier (afflux touristique estival massif, fréquentation quasi nulle hors saison, dépendance à un événement annuel fixe) qui nécessite un traitement dédié.

### Sites disponibles pour l'extension multi-sites

Les 7 sites suivants sont préconfigurés dans `sites.py` avec leurs CSV journaliers 2020–2025 :

| Identifiant | Nom | Commune |
|---|---|---|
| `herretang` | Herretang — Tuilerie | Saint-Joseph-de-Rivière |
| `veronniere` | Marais de la Véronnière | Morestel |
| `ecouges_pont_chabert` | Écouges — Pont Chabert piéton | Cognin-les-Gorges |
| `etang_serre_observatoire` | Étang de la Serre — observatoire | Sermerieu |
| `etang_lemps_sentier` | Étang de Lemps — sentier | Bouvesse-Quirieu |
| `etang_lemps_observatoire` | Étang de Lemps — observatoire | Bouvesse-Quirieu |
| `lac_save_ouest` | Lac de Save — ouest | Optevoz |

Ces sites couvrent des typologies d'usage variées (zone humide, forêt, plan d'eau), ce qui constitue un bon panel pour valider la robustesse des features.

### Lancer l'entraînement et le backtest sur un autre site

```bash
# Entraîner sur Véronnière
python3 src/api/train.py --site veronniere

# Backtest Véronnière
python3 src/poc_backtest.py --site veronniere --date 2026-04-15

# Comparer les résultats MLflow
# → Chaque site a sa propre expérience "flux-touristique-{site_id}"
```

---

## Limites connues et pistes d'amélioration

### Limites structurelles du modèle actuel

| Limite | Impact observé | Piste d'amélioration |
|---|---|---|
| Événements non capturés | Pics majeurs non prévus (ex. +400 % le 15/04/2026) | Intégrer l'agenda culturel (Apidae, OpenAgenda) |
| Lags imparfaits en projection | Pour J+7, le lag J-1 n'existe pas encore | Remplacer par une prédiction en chaîne ou un intervalle de confiance |
| Capacité non formalisée | P90 est une approximation | Calibrer avec les gestionnaires de chaque site |
| `weekend` redondant | XGBoost lui attribue une importance nulle | Supprimer de la liste de features |

### Limites de la stratégie de validation

| Limite | Explication |
|---|---|
| Holdout utilisé pour la sélection | La MAE de 20.31 est biaisée à la baisse — un 4ème jeu de test strictement indépendant éliminerait ce biais |
| Backtest limité au printemps 2026 | Les archives ENS Herretang s'arrêtent en mai 2026 — on ne peut pas tester l'été ni l'automne 2026 |
| Pas de validation croisée temporelle | Leave-one-year-out donnerait une estimation de variance plus robuste, mais complexifie l'explication au client |
| Test multi-sites non encore exécuté | La portabilité est implémentée (`sites.py`) avec 7 sites, mais les modèles n'ont pas encore été entraînés sur tous |

### Interprétation pour la mise en production

Le modèle est adapté à un usage d'aide à la décision stratégique — anticiper les semaines à risque, planifier les ressources humaines, préparer la communication préventive. Il n'est pas adapté à une gestion opérationnelle heure par heure.

La règle de décision recommandée : **utiliser les prédictions comme signal de tendance**, complémentaires d'un suivi en temps réel des compteurs pour ajuster en cours de journée.
