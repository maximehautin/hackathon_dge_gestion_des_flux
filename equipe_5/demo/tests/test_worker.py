"""Invariants du couplage UI ↔ worker (§2), avec faux micro, fausse VAD, faux STT et faux Jev."""

import time

import bornes
import db
import jev
import numpy as np
import pytest
import worker
from worker import SR


def speech(s):
    return np.full(int(s * SR), 0.3, np.float32)


def silence(s):
    return np.zeros(int(s * SR), np.float32)


def energy_vad(audio):
    """VAD factice : segments où le signal est non nul, pauses < MIN_SILENCE_MS fusionnées."""
    on = np.abs(audio) > 1e-3
    segs, start = [], None
    for i in range(0, len(audio), 160):
        v = bool(on[i : i + 160].any())
        if v and start is None:
            start = i
        if not v and start is not None:
            segs.append({"start": start, "end": i})
            start = None
    if start is not None:
        segs.append({"start": start, "end": len(audio)})
    merged = []
    for s in segs:
        if merged and s["start"] - merged[-1]["end"] < worker.MIN_SILENCE_MS / 1000 * SR:
            merged[-1]["end"] = s["end"]
        else:
            merged.append(s)
    return merged


class FakeSource:
    def __init__(self):
        self.pending = []
        self.started = 0

    def feed(self, *chunks):
        self.pending.extend(chunks)

    def start(self):
        self.started += 1

    def read(self):
        out = np.concatenate(self.pending) if self.pending else np.zeros(0, np.float32)
        self.pending = []
        return out

    def stop(self):
        pass


class FakeSTT:
    def __init__(self, text="phrase"):
        self.calls = []
        self.text = text

    def detect(self, audio):
        return "fr"

    def transcribe(self, audio, language, prompt):
        self.calls.append(round(len(audio) / SR, 1))
        return f"{self.text}{len(self.calls)}" if self.text else ""


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(worker, "TICK_S", 0.0)
    monkeypatch.setattr(worker, "speech_segments", energy_vad)
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    jev_calls = []

    def fake_decide(body, client=None):
        jev_calls.append(body)
        return {
            "answers": {
                "satisfaction_present": {"type": "noul", "noul": 0.95},
                "satisfaction": {"type": "score", "score": 4, "confidence": 0.9},
            }
        }

    monkeypatch.setattr(jev, "decide", fake_decide)
    statuses = []
    real_set_live = db.set_live

    def spy(conn, **fields):
        if "status" in fields and (not statuses or statuses[-1] != fields["status"]):
            statuses.append(fields["status"])
        real_set_live(conn, **fields)

    monkeypatch.setattr(db, "set_live", spy)
    conn = db.connect(tmp_path / "w.db")
    src, stt = FakeSource(), FakeSTT()
    w = worker.Worker(conn, src, stt, bornes.load())
    w.startup()
    return w, conn, src, stt, jev_calls, statuses


def rows(conn):
    return conn.execute("SELECT * FROM transcription").fetchall()


def test_enregistrement_complet(env):
    w, conn, src, _, jev_calls, statuses = env
    db.push_command(conn, "start", borne_id="peuil")
    w.step()
    src.feed(speech(4), silence(1.5), speech(3), silence(1))
    w.step()  # langue verrouillée
    w.step()  # partiels : chunks validés jusqu'à la dernière pause
    assert db.get_live(conn)["committed_text"].startswith("phrase")
    db.push_command(conn, "stop")
    w.step()
    (t,) = rows(conn)
    assert t["borne_id"] == "peuil" and t["langue"] == "fr" and t["is_init"] == 0
    avis = db.get_avis(conn, t["id"])
    assert avis["status"] == "ok" and avis["satisfaction"] == 100.0 and avis["transport"] is None
    assert len(jev_calls) == 1 and jev_calls[0]["state"]["borne"] == "Peuil"
    assert statuses == ["idle", "recording", "transcribing", "classifying", "idle"]  # invariant 4
    assert w.rec is None


def test_start_pendant_enregistrement_et_stop_hors_enregistrement_ignores(env):
    w, conn, src, *_ = env
    db.push_command(conn, "stop")
    db.push_command(conn, "start", borne_id="peuil")
    db.push_command(conn, "start", borne_id="montfort")
    w.step()
    assert src.started == 1 and w.rec.borne_id == "peuil"
    assert db.pop_commands(conn) == []  # toutes consommées


def test_arret_auto_apres_15s_de_silence(env):
    w, conn, src, _, jev_calls, _ = env
    db.push_command(conn, "start", borne_id="col_coq")
    w.step()
    src.feed(speech(2))
    w.step()
    for _ in range(13):
        src.feed(silence(1))
        w.step()
    assert w.rec is not None  # 13 s de silence : toujours en cours
    assert "arrêt automatique dans" in db.get_live(conn)["message"]
    src.feed(silence(2))
    w.step()
    assert w.rec is None
    assert len(rows(conn)) == 1 and len(jev_calls) == 1
    assert "arrêt automatique" in db.get_live(conn)["message"]


def test_arret_auto_sans_parole_rien_insere(env):
    w, conn, src, stt, jev_calls, statuses = env
    db.push_command(conn, "start", borne_id="ecouges")
    w.step()
    src.feed(silence(16))
    w.step()
    assert w.rec is None
    assert rows(conn) == [] and jev_calls == [] and stt.calls == []  # invariant 3
    assert db.get_live(conn)["message"].startswith("rien capté")
    assert statuses == ["idle", "recording", "transcribing", "idle"]


def test_transcript_vide_rien_insere(env):
    w, conn, src, stt, jev_calls, _ = env
    stt.text = ""  # parole détectée mais rien de transcrit
    db.push_command(conn, "start", borne_id="ecouges")
    w.step()
    src.feed(speech(2))
    db.push_command(conn, "stop")
    w.step()
    assert rows(conn) == [] and jev_calls == []


def test_duree_maximale(env):
    w, conn, src, *_ = env
    db.push_command(conn, "start", borne_id="peuil")
    w.step()
    src.feed(speech(worker.MAX_DUREE_S + 1))
    w.step()
    assert w.rec is None and len(rows(conn)) == 1


def test_echec_jev_puis_reclassification(env, monkeypatch):
    w, conn, src, *_ = env

    def failing(body, client=None):
        raise jev.JevError("réseau : hors ligne")

    monkeypatch.setattr(jev, "decide", failing)
    db.push_command(conn, "start", borne_id="peuil")
    w.step()
    src.feed(speech(2))
    db.push_command(conn, "stop")
    w.step()
    (t,) = rows(conn)
    assert db.get_avis(conn, t["id"])["status"] == "error"
    assert db.get_live(conn)["status"] == "idle"
    monkeypatch.setattr(jev, "decide", lambda body, client=None: {"answers": {}})
    assert worker.classify_transcription(conn, t["id"], w.territoire) == "ok"  # bouton « Re-classifier »
    assert db.get_avis(conn, t["id"])["status"] == "ok"


def test_date_simulee(env):
    w, conn, src, *_ = env
    hier = int(time.time()) - 86400
    db.push_command(conn, "start", borne_id="peuil", event_ts_override=hier)
    w.step()
    src.feed(speech(2))
    db.push_command(conn, "stop")
    w.step()
    (t,) = rows(conn)
    assert t["event_ts"] == hier and t["is_init"] == 1


def test_date_future_refusee(env):
    w, conn, src, _, jev_calls, _ = env
    db.push_command(conn, "start", borne_id="peuil", event_ts_override=int(time.time()) + 86400)
    w.step()
    src.feed(speech(2))
    db.push_command(conn, "stop")
    w.step()
    assert rows(conn) == [] and jev_calls == []
    assert "futur" in db.get_live(conn)["message"]


def test_sans_partiels_une_seule_transcription_au_stop(env):
    w, conn, src, stt, *_ = env
    w.partiels = False
    db.push_command(conn, "start", borne_id="peuil")
    w.step()
    src.feed(speech(4), silence(1.5), speech(3))
    w.step()
    assert stt.calls == []
    db.push_command(conn, "stop")
    w.step()
    assert stt.calls == [8.5]


def test_orphelines_au_demarrage(env):
    w, conn, *_ = env
    tid = db.insert_transcription(conn, event_ts=int(time.time()), borne_id="peuil", texte="x", langue="fr")
    w.startup()
    assert db.get_avis(conn, tid)["status"] == "error"
