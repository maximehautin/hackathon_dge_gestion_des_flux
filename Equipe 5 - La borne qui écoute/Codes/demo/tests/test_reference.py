import datetime as dt

import pandas as pd
import pytest
import reference


@pytest.fixture
def root(tmp_path):
    rows = [
        {"Année": 2010, "Mois": dt.datetime(2010, 11, 30), "Site A parking (à diviser par 2)": 1200, "site b ": 300},
        {"Année": "Somme 2010", "Mois": None, "Site A parking (à diviser par 2)": 99999, "site b ": 99999},
        {"Année": 2011, "Mois": "Novembre 2011", "Site A parking (à diviser par 2)": 2400, "site b ": None},
        {"Année": 2011, "Mois": "Décembre 2011", "Site A parking (à diviser par 2)": 10, "site b ": 10},
    ]
    xlsx = tmp_path / reference.WORKBOOK
    xlsx.parent.mkdir(parents=True)
    pd.DataFrame(rows).to_excel(xlsx, index=False)
    return tmp_path


def test_moyenne_du_mois_ramenee_a_la_demi_journee(root):
    f = reference.frequentations({"a": "Site A parking", "b": "SITE B"}, 11, root=root)
    a, b = f["a"], f["b"]
    assert a is not None and b is not None
    # « à diviser par 2 » : (600 + 1200) / 2 = 900 par mois, ÷ 30 jours ÷ 2
    assert a.valeur == pytest.approx(900 / 30 / 2)
    assert (a.periode, a.n_annees, a.compteur) == ("2010-2011", 2, "Site A parking")
    assert b.valeur == pytest.approx(300 / 30 / 2)
    assert b.periode == "2010-2010"


def test_mois_sans_donnees(root):
    assert reference.frequentations({"b": "site b"}, 6, root=root) == {"b": None}


def test_compteur_inconnu(root):
    with pytest.raises(KeyError, match="introuvable"):
        reference.frequentations({"x": "inconnu"}, 11, root=root)


def test_resolution_du_dossier(tmp_path):
    with pytest.raises(FileNotFoundError, match="aucun dossier"):
        reference.resolve_root((tmp_path / "a", tmp_path / "b"))
    (tmp_path / "b").mkdir()
    assert reference.resolve_root((tmp_path / "a", tmp_path / "b")) == tmp_path / "b"
