import mapping

PRESENT = {"type": "noul", "noul": 0.9}
ANSWERS = {
    "satisfaction_present": PRESENT,
    "satisfaction": {"type": "score", "score": 3.0, "confidence": 0.9},
    "affluence_present": PRESENT,
    "affluence": {"type": "score", "score": 1.0, "confidence": 0.8},
    "provenance": {"type": "choice", "choice": "hors_departement", "confidence": 0.95},
    "transport": {"type": "choice", "choice": "voiture", "confidence": 0.3},
    "profil": {"type": "refusal"},
}


def test_questions():
    qs = mapping.questions("Isère")
    assert set(qs) == {*mapping.COLUMNS, "satisfaction_present", "affluence_present"}
    for col in mapping.SCORE_COLUMNS:
        assert qs[col + mapping.PRESENT_SUFFIX]["type"] == "noul"
    for col, opts in mapping.CHOICE_OPTIONS.items():
        assert tuple(qs[col]["criteria"]) == (*opts, mapping.MISSING)
    assert "Isère" in qs["provenance"]["instructions"]


def test_parse():
    out = mapping.parse(ANSWERS, "Isère", seuil=0.6)
    assert out == {
        "satisfaction": 75.0,  # index 3 sur 5 niveaux
        "affluence": 25.0,
        "provenance": "hors_departement",
        "transport": None,  # confiance trop faible : no guess
        "profil": None,  # refus
    }


def test_score_absent_du_texte_selon_noul():
    answers = {**ANSWERS, "affluence_present": {"type": "noul", "noul": 0.2}}
    out = mapping.parse(answers, "Isère", seuil=0.6)
    assert out["affluence"] is None
    assert out["satisfaction"] == 75.0


def test_score_sans_reponse_noul_est_null():
    answers = {k: v for k, v in ANSWERS.items() if k != "satisfaction_present"}
    assert mapping.parse(answers, "Isère")["satisfaction"] is None
    answers["satisfaction_present"] = {"type": "refusal"}
    assert mapping.parse(answers, "Isère")["satisfaction"] is None


def test_categorie_missing_est_null():
    out = mapping.parse({"transport": {"type": "choice", "choice": "missing", "confidence": 0.99}}, "Isère")
    assert out["transport"] is None


def test_seuil_sur_les_scores_aussi():
    answers = {"satisfaction_present": PRESENT, "satisfaction": {"type": "score", "score": 4, "confidence": 0.5}}
    assert mapping.parse(answers, "Isère", seuil=0.6)["satisfaction"] is None


def test_sans_confiance_la_valeur_est_gardee():
    out = mapping.parse({"profil": {"type": "choice", "choice": "famille"}}, "Isère", seuil=0.6)
    assert out["profil"] == "famille"


def test_valeurs_hors_options_ou_absentes():
    out = mapping.parse({"transport": {"type": "choice", "choice": "avion", "confidence": 1}}, "Isère")
    assert out == dict.fromkeys(mapping.COLUMNS)


def test_score_borne():
    out = mapping.parse(
        {"affluence_present": PRESENT, "affluence": {"type": "score", "score": 7, "confidence": 1}}, "Isère"
    )
    assert out["affluence"] == 100.0
