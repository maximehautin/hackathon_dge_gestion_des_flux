import sqlite3
import threading
import time

import bornes
import db
import pytest


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "t.db")
    db.upsert_bornes(c, bornes.load().bornes.values())
    return c


def _avis(conn, borne="peuil", ts=None, texte="bien"):
    return db.insert_transcription(conn, event_ts=ts or int(time.time()), borne_id=borne, texte=texte, langue="fr")


def test_futur_refuse(conn):
    with pytest.raises(ValueError, match="futur"):
        _avis(conn, ts=int(time.time()) + 3600)


def test_texte_vide_refuse(conn):
    with pytest.raises(sqlite3.IntegrityError):
        _avis(conn, texte="")


def test_borne_inconnue_refusee(conn):
    with pytest.raises(sqlite3.IntegrityError):
        _avis(conn, borne="nulle_part")


def test_inference_remplacee_et_supprimee_en_cascade(conn):
    tid = _avis(conn)
    assert db.get_avis(conn, tid)["status"] is None  # en cours de classification
    db.set_inference(conn, tid, "error", {}, {"error": "réseau"})
    db.set_inference(conn, tid, "ok", {"satisfaction": 80.0, "transport": None}, {"answers": {}})
    row = db.get_avis(conn, tid)
    assert (row["status"], row["satisfaction"], row["transport"]) == ("ok", 80.0, None)
    db.delete_transcription(conn, tid)
    assert conn.execute("SELECT COUNT(*) FROM inference_avis").fetchone()[0] == 0


def test_agregats(conn):
    now = int(time.time())
    a = _avis(conn, ts=now - 10)
    b = _avis(conn, ts=now - 5)
    c = _avis(conn, ts=now - 1)
    old = _avis(conn, ts=now - 86400 * 3)
    db.set_inference(conn, a, "ok", {"satisfaction": 80, "provenance": "hors_departement"}, None)
    db.set_inference(conn, b, "ok", {"satisfaction": 40, "provenance": "departement", "affluence": 90}, None)
    db.set_inference(conn, c, "error", {}, None)
    db.set_inference(conn, old, "ok", {"satisfaction": 0}, None)
    rows = {r["borne_id"]: r for r in db.agregats(conn, now - 3600, now + 1)}
    p = rows["peuil"]
    assert (p["n_avis"], p["satisfaction"], p["affluence"], p["part_hors"]) == (3, 60.0, 90.0, 50.0)
    assert rows["montfort"]["n_avis"] == 0 and rows["montfort"]["satisfaction"] is None
    assert len(rows) == 5
    assert {r["borne_id"]: r for r in db.agregats(conn, None, None)}["peuil"]["n_avis"] == 4


def test_commandes_dans_l_ordre_et_consommees(conn):
    db.push_command(conn, "start", borne_id="peuil")
    db.push_command(conn, "stop")
    assert [r["cmd"] for r in db.pop_commands(conn)] == ["start", "stop"]
    assert db.pop_commands(conn) == []


def test_reset_au_demarrage(conn):
    orphan = _avis(conn)
    done = _avis(conn)
    db.set_inference(conn, done, "ok", {}, None)
    db.push_command(conn, "start", borne_id="peuil")
    db.set_live(conn, status="recording", committed_text="x")
    assert db.reset_on_startup(conn) == 1
    assert db.get_avis(conn, orphan)["status"] == "error"
    assert db.get_avis(conn, done)["status"] == "ok"
    assert db.pop_commands(conn) == []
    assert db.get_live(conn)["status"] == "idle"


def test_une_connexion_par_thread(tmp_path):
    path = tmp_path / "t.db"
    assert db.thread_conn(path) is db.thread_conn(path)
    other = []
    t = threading.Thread(target=lambda: other.append(db.thread_conn(path)))
    t.start()
    t.join()
    assert other[0] is not db.thread_conn(path)


def test_lectures_concurrentes_sans_erreur(tmp_path):
    """Régression PR #18 : sessions et fragments Streamlit lisent la base depuis plusieurs threads."""
    path = tmp_path / "t.db"
    c = db.thread_conn(path)
    db.upsert_bornes(c, bornes.load().bornes.values())
    for i in range(5):
        _avis(c, texte=f"avis {i}")
    errors = []

    def lire():
        try:
            for _ in range(200):
                conn = db.thread_conn(path)
                assert db.get_live(conn) is not None
                assert len(db.agregats(conn, None, None)) == 5
                assert all(r["texte"] for r in db.latest(conn, 10))
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=lire) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []


def test_texte_corrige_a_la_main(conn):
    tid = _avis(conn, texte="pas content")
    db.set_inference(conn, tid, "ok", {"satisfaction": 10.0}, None)
    db.update_texte(conn, tid, "très content")
    row = db.get_avis(conn, tid)
    assert row["texte"] == "très content"
    assert row["status"] is None  # à re-classifier
    with pytest.raises(sqlite3.IntegrityError):
        db.update_texte(conn, tid, "")
    assert db.get_avis(conn, tid)["texte"] == "très content"  # rollback
