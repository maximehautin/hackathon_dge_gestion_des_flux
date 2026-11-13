import bornes
import pytest


def test_bornes_yaml():
    t = bornes.load()
    assert t.departement == "Isère"
    assert list(t.bornes) == ["bois_batie", "col_coq", "ecouges", "peuil", "montfort"]
    assert t.bornes["peuil"].code_insee == "38111"
    assert t.bornes["montfort"].compteur == "Montfort voitures"


def test_doublon(tmp_path):
    p = tmp_path / "b.yaml"
    b = "{id: a, name: A, id_ens: X, commune: C, code_insee: '1', compteur: c, lat: 1, lon: 2}"
    p.write_text(f"departement: D\nbornes: [{b}, {b}]\n", encoding="utf-8")
    with pytest.raises(ValueError, match="double"):
        bornes.load(p)
