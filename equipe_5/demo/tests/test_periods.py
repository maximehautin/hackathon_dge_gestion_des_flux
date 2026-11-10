from datetime import datetime

import periods
import pytest


def ts(s: str) -> int:
    return int(datetime.fromisoformat(s).replace(tzinfo=periods.TZ).timestamp())


@pytest.mark.parametrize("hm", ["00:00", "05:59", "12:59"])
def test_matin(hm):
    assert periods.demi_journee(ts(f"2026-11-09T{hm}")) == "2026-11-09_matin"


@pytest.mark.parametrize("hm", ["13:00", "19:59", "20:00", "23:59"])
def test_apres_midi(hm):
    assert periods.demi_journee(ts(f"2026-11-09T{hm}")) == "2026-11-09_apres_midi"


def test_utc_converti_en_heure_de_paris():
    # 12:30 UTC = 13:30 à Paris en novembre (UTC+1)
    assert periods.demi_journee(int(datetime.fromisoformat("2026-11-09T12:30+00:00").timestamp())) == (
        "2026-11-09_apres_midi"
    )


@pytest.mark.parametrize("dj", ["2026-11-09_matin", "2026-11-09_apres_midi", "2026-10-25_matin", "2026-03-29_matin"])
def test_intervalle_inverse(dj):
    debut, fin = periods.intervalle(dj)
    assert periods.demi_journee(debut) == dj
    assert periods.demi_journee(fin - 1) == dj
    assert periods.demi_journee(fin) == periods.decaler(dj, 1)


def test_passage_heure_hiver():
    # nuit du 24 au 25 octobre 2026 : 25 h ; la matinée du 25 dure 14 h
    debut, fin = periods.intervalle("2026-10-25_matin")
    assert fin - debut == 14 * 3600
    debut, fin = periods.intervalle("2026-03-29_matin")  # heure d'été : 12 h
    assert fin - debut == 12 * 3600


def test_decaler_et_libelle():
    assert periods.decaler("2026-11-09_matin", -1) == "2026-11-08_apres_midi"
    assert periods.decaler("2026-11-09_apres_midi", 1) == "2026-11-10_matin"
    assert periods.mois("2026-11-09_matin") == 11
    assert periods.libelle("2026-11-09_apres_midi") == "lun. 09/11 · après-midi"


def test_cle_invalide():
    with pytest.raises(ValueError, match="invalide"):
        periods.intervalle("2026-11-09_soir")
