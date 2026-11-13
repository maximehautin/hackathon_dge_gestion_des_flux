"""
Catalogue des sites supportés par le pipeline ML.

Chaque entrée référence un site ENS (CG38 Environnement) avec les paramètres
nécessaires au pipeline : coordonnées GPS, capacité, seuils d'alerte, et
chemin vers le CSV journalier pré-agrégé (2020–2025).

Usage :
    from sites import SITES, DEFAULT_SITE
    site_cfg = SITES["herretang"]
"""

SITES = {
    "herretang": {
        "nom":                  "Herretang — Tuilerie",
        "commune":              "Saint-Joseph-de-Rivière",
        "latitude":             45.38224,
        "longitude":            5.68871,
        "capacite_journaliere": None,
        "seuils_risque":        {"modere": 0.60, "eleve": 0.85},
        "zone_vacances":        "Grenoble",
        "mlflow_experiment":    "flux-touristique-herretang",
        "journalier_csv":       "herretang_2020_2025/journalier_herretang_2020_2025.csv",
        "channel_in":           "353347292",
    },
    "veronniere": {
        "nom":                  "Marais de la Véronnière",
        "commune":              "Morestel",
        "latitude":             45.47377,
        "longitude":            5.5626,
        "capacite_journaliere": None,
        "seuils_risque":        {"modere": 0.60, "eleve": 0.85},
        "zone_vacances":        "Grenoble",
        "mlflow_experiment":    "flux-touristique-veronniere",
        "journalier_csv":       "veronniere_2020_2025/journalier_veronniere_2020_2025.csv",
    },
    "ecouges_pont_chabert": {
        "nom":                  "Écouges — Pont Chabert piéton",
        "commune":              "Cognin-les-Gorges",
        "latitude":             45.17871,
        "longitude":            5.49912,
        "capacite_journaliere": None,
        "seuils_risque":        {"modere": 0.60, "eleve": 0.85},
        "zone_vacances":        "Grenoble",
        "mlflow_experiment":    "flux-touristique-ecouges-pont-chabert",
        "journalier_csv":       "ecouges_pont_chabert_2020_2025/journalier_ecouges_pont_chabert_2020_2025.csv",
    },
    "etang_serre_observatoire": {
        "nom":                  "Étang de la Serre — observatoire",
        "commune":              "Sermerieu",
        "latitude":             45.72695,
        "longitude":            5.4248,
        "capacite_journaliere": None,
        "seuils_risque":        {"modere": 0.60, "eleve": 0.85},
        "zone_vacances":        "Grenoble",
        "mlflow_experiment":    "flux-touristique-etang-serre-observatoire",
        "journalier_csv":       "etang_serre_observatoire_2020_2025/journalier_etang_serre_observatoire_2020_2025.csv",
    },
    "etang_lemps_sentier": {
        "nom":                  "Étang de Lemps — sentier",
        "commune":              "Bouvesse-Quirieu",
        "latitude":             45.75944,
        "longitude":            5.3587,
        "capacite_journaliere": None,
        "seuils_risque":        {"modere": 0.60, "eleve": 0.85},
        "zone_vacances":        "Grenoble",
        "mlflow_experiment":    "flux-touristique-etang-lemps-sentier",
        "journalier_csv":       "etang_lemps_sentier_2020_2025/journalier_etang_lemps_sentier_2020_2025.csv",
    },
    "etang_lemps_observatoire": {
        "nom":                  "Étang de Lemps — observatoire",
        "commune":              "Bouvesse-Quirieu",
        "latitude":             45.754936,
        "longitude":            5.360318,
        "capacite_journaliere": None,
        "seuils_risque":        {"modere": 0.60, "eleve": 0.85},
        "zone_vacances":        "Grenoble",
        "mlflow_experiment":    "flux-touristique-etang-lemps-observatoire",
        "journalier_csv":       "etang_lemps_observatoire_2020_2025/journalier_etang_lemps_observatoire_2020_2025.csv",
    },
    "lac_save_ouest": {
        "nom":                  "Lac de Save — ouest",
        "commune":              "Optevoz",
        "latitude":             45.69929,
        "longitude":            5.4564,
        "capacite_journaliere": None,
        "seuils_risque":        {"modere": 0.60, "eleve": 0.85},
        "zone_vacances":        "Grenoble",
        "mlflow_experiment":    "flux-touristique-lac-save-ouest",
        "journalier_csv":       "lac_save_ouest_2020_2025/journalier_lac_save_ouest_2020_2025.csv",
    },
}

DEFAULT_SITE = "herretang"
