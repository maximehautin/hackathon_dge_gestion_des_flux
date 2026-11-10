"""Worker : micro → VAD → faster-whisper → SQLite → Jev.

Piloté par la table `control` (commandes écrites par l'app Streamlit), lue toutes les ~100 ms.
Lancement : `python demo/worker.py` (voir `demo/README.md` pour les options).
"""

from __future__ import annotations

import argparse
import logging
import os
import queue
import re
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import bornes
import db
import jev
import mapping
import numpy as np

SR = 16_000
POLL_S = 0.1  # lecture de la table `control`
TICK_S = 2.0  # VAD + retranscription du chunk en cours (texte partiel)
HEARTBEAT_S = 1.0  # invariant 6 : rafraîchi au moins toutes les 2 s
SILENCE_STOP_S = 15.0  # invariant 2 : arrêt auto sans parole détectée
SILENCE_WARN_S = 5.0  # au-delà, compte à rebours affiché dans l'UI
MAX_DUREE_S = 120.0
MIN_SILENCE_MS = 700  # pause qui clôt un chunk
MAX_UNCOMMITTED_S = 20.0  # au-delà, on valide de force pour borner le coût des partiels
LANG_LOCK_MIN_S = 3.0  # langue verrouillée dès 3 s d'audio avec de la parole
WHISPER_WINDOW_S = 30
TOKENS_PER_S = 8  # parole ≈ 3-5 tokens/s : marge x2 (anti-boucle d'hallucination)
# Détection auto restreinte aux langues plausibles ; une langue autre que la langue par défaut
# n'est retenue que si Whisper en est assez sûr (sinon un français mal détecté est « traduit »).
CANDIDATE_LANGS = tuple(os.environ.get("DEMO_LANGS", "fr,en,de,it,nl,es").split(","))
DEFAULT_LANG = os.environ.get("DEMO_DEFAULT_LANG", "fr")
LANG_MIN_PROB = float(os.environ.get("DEMO_LANG_MIN_PROB", "0.5"))

# Hallucinations classiques de Whisper sur du silence ou du bruit.
_HALLUCINATIONS = re.compile(
    r"sous-titr|amara\.org|merci d'avoir regard|armée|abonnez-vous|thanks for watching|untertitel", re.IGNORECASE
)

log = logging.getLogger("worker")


# --- sources audio ----------------------------------------------------------------


class AudioSource(Protocol):
    def start(self) -> None: ...
    def read(self) -> np.ndarray: ...
    def stop(self) -> None: ...


class MicSource:
    """Micro du laptop via sounddevice (PortAudio). L'audio reste en mémoire."""

    def __init__(self, device: str | int | None = None) -> None:
        import sounddevice as sd

        self._sd = sd
        self.device = device
        self._q: queue.Queue[np.ndarray] = queue.Queue()
        self._stream: Any = None

    def start(self) -> None:
        def cb(indata: np.ndarray, frames: int, t: Any, status: Any) -> None:  # thread PortAudio
            if status:
                log.warning("audio : %s", status)
            self._q.put(indata[:, 0].copy())

        self._q = queue.Queue()
        self._stream = self._sd.InputStream(
            samplerate=SR, channels=1, dtype="float32", device=self.device, callback=cb, blocksize=1600
        )
        self._stream.start()

    def read(self) -> np.ndarray:
        parts = []
        while True:
            try:
                parts.append(self._q.get_nowait())
            except queue.Empty:
                break
        return np.concatenate(parts) if parts else np.zeros(0, np.float32)

    def stop(self) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None


class FileSource:
    """Rejoue des fichiers audio, un par enregistrement (répétition sans micro).

    En temps réel, le fichier est suivi de silence : l'arrêt automatique se déclenche.
    """

    def __init__(self, paths: list[str], *, realtime: bool = True) -> None:
        from faster_whisper import decode_audio

        self._clips = [decode_audio(p, sampling_rate=SR) for p in paths]
        self._i = 0
        self.realtime = realtime
        self._clip = np.zeros(0, np.float32)
        self._pos = 0
        self._t0 = 0.0

    def start(self) -> None:
        self._clip = self._clips[self._i % len(self._clips)]
        self._i += 1
        self._pos = 0
        self._t0 = time.monotonic()

    def read(self) -> np.ndarray:
        if not self.realtime:
            out, self._pos = self._clip[self._pos :], len(self._clip)
            return out
        end = int((time.monotonic() - self._t0) * SR)
        out = self._clip[self._pos : end]
        if end > len(self._clip):  # après la fin du fichier : silence
            out = np.concatenate([out, np.zeros(end - max(self._pos, len(self._clip)), np.float32)])
        self._pos = max(self._pos, end)
        return out

    def stop(self) -> None:
        pass


# --- transcription ------------------------------------------------------------------


class STT(Protocol):
    def detect(self, audio: np.ndarray) -> str: ...
    def transcribe(self, audio: np.ndarray, language: str, prompt: str | None) -> str: ...


class Transcriber:
    """faster-whisper sur CPU (int8)."""

    def __init__(self, model_size: str, cpu_threads: int, download_root: Path) -> None:
        from faster_whisper import WhisperModel

        t0 = time.monotonic()
        kw: dict[str, Any] = {
            "device": "cpu",
            "compute_type": "int8",
            "cpu_threads": cpu_threads,
            "download_root": str(download_root),
        }
        try:  # hors ligne d'abord : la salle peut ne pas avoir de réseau
            self.model = WhisperModel(model_size, local_files_only=True, **kw)
        except Exception:
            log.info("modèle %s absent localement : téléchargement dans %s", model_size, download_root)
            self.model = WhisperModel(model_size, **kw)
        log.info("modèle %s chargé en %.1f s", model_size, time.monotonic() - t0)

    def detect(self, audio: np.ndarray) -> str:
        _, _, probs = self.model.detect_language(audio[: WHISPER_WINDOW_S * SR])
        lang = choose_language(probs, CANDIDATE_LANGS, DEFAULT_LANG, LANG_MIN_PROB)
        log.info("langue : %s (top : %s)", lang, ", ".join(f"{la}={p:.2f}" for la, p in probs[:3]))
        return lang

    def transcribe(self, audio: np.ndarray, language: str, prompt: str | None) -> str:
        t0 = time.monotonic()
        dur = len(audio) / SR
        segments, _ = self.model.transcribe(
            audio,
            language=language,
            beam_size=1,
            vad_filter=False,
            condition_on_previous_text=False,
            initial_prompt=prompt or None,
            hotwords="rando randonnée",
            # latence bornée en live : pas de ré-essais à température croissante, plafond de tokens
            temperature=0.0,
            max_new_tokens=min(440, int(min(dur, WHISPER_WINDOW_S) * TOKENS_PER_S) + 16),
        )
        texts = [s.text.strip() for s in segments if not _HALLUCINATIONS.search(s.text)]
        log.info("stt : %.1f s d'audio en %.2f s (%s)", dur, time.monotonic() - t0, language)
        return " ".join(t for t in texts if t)


def choose_language(probs: list[tuple[str, float]], candidates: tuple[str, ...], default: str, min_prob: float) -> str:
    """Meilleure langue parmi les candidates ; la langue par défaut sauf si une autre est assez probable."""
    cands = [(la, p) for la, p in probs if la in candidates]
    if not cands:
        return default
    best, p = max(cands, key=lambda lp: lp[1])
    return best if best == default or p >= min_prob else default


def speech_segments(audio: np.ndarray) -> list[dict[str, int]]:
    """VAD silero (embarquée dans faster-whisper) : segments de parole en échantillons."""
    from faster_whisper.vad import VadOptions, get_speech_timestamps

    if len(audio) < SR // 4:
        return []
    segs: list[dict[str, int]] = get_speech_timestamps(
        audio, VadOptions(min_silence_duration_ms=MIN_SILENCE_MS, speech_pad_ms=200)
    )
    return segs


# --- classification -----------------------------------------------------------------


def classify_transcription(conn: sqlite3.Connection, transcription_id: int, territoire: bornes.Territoire) -> str:
    """Appelle Jev sur une transcription et insère (ou remplace) sa ligne `inference_avis`."""
    row = db.get_avis(conn, transcription_id)
    if row is None:
        raise KeyError(transcription_id)
    body = jev.build_request(row["texte"], mapping.questions(territoire.departement), row["borne_name"], row["langue"])
    try:
        raw = jev.decide(body)
    except jev.JevError as e:
        log.error("transcription #%d : échec Jev : %s", transcription_id, e)
        db.set_inference(conn, transcription_id, "error", {}, {"error": str(e)})
        return "error"
    cols = mapping.parse(raw["answers"], territoire.departement)
    db.set_inference(conn, transcription_id, "ok", cols, raw)
    log.info("transcription #%d classifiée : %s", transcription_id, cols)
    return "ok"


# --- enregistrement en cours --------------------------------------------------------


@dataclass
class Recording:
    borne_id: str
    event_ts: int
    is_init: bool
    audio: list[np.ndarray] = field(default_factory=list)
    n_samples: int = 0
    committed_pos: int = 0
    committed: list[str] = field(default_factory=list)
    language: str | None = None  # verrouillée une fois par enregistrement
    last_speech: int = 0  # fin de la dernière parole détectée (échantillons)
    last_tick: float = 0.0
    partial_key: tuple[int, int] | None = None
    _flat: np.ndarray | None = None

    def append(self, chunk: np.ndarray) -> None:
        if len(chunk):
            self.audio.append(chunk)
            self.n_samples += len(chunk)
            self._flat = None

    def flat(self) -> np.ndarray:
        if self._flat is None:
            self._flat = np.concatenate(self.audio) if self.audio else np.zeros(0, np.float32)
            self.audio = [self._flat]
        return self._flat

    @property
    def committed_text(self) -> str:
        return " ".join(t for t in self.committed if t)

    @property
    def silence_s(self) -> float:
        return (self.n_samples - self.last_speech) / SR


class Worker:
    def __init__(
        self,
        conn: sqlite3.Connection,
        source: AudioSource,
        stt: STT,
        territoire: bornes.Territoire,
        *,
        partiels: bool = True,
    ) -> None:
        self.conn = conn
        self.source = source
        self.stt = stt
        self.territoire = territoire
        self.partiels = partiels
        self.rec: Recording | None = None

    # -- boucle principale
    def startup(self) -> None:
        db.upsert_bornes(self.conn, self.territoire.bornes.values())
        n = db.reset_on_startup(self.conn)
        if n:
            log.warning("%d transcription(s) orpheline(s) marquée(s) en erreur (re-classifiables)", n)

    def step(self) -> None:
        for cmd in db.pop_commands(self.conn):
            self._handle(cmd)
        rec = self.rec
        if rec is None:
            return
        rec.append(self.source.read())
        now = time.monotonic()
        if now - rec.last_tick >= TICK_S:
            rec.last_tick = now
            self._tick(rec)

    def _handle(self, cmd: sqlite3.Row) -> None:
        if cmd["cmd"] == "stop":
            if self.rec is not None:
                self._finish("stop")
            return
        if self.rec is not None:  # invariant 1 : start pendant un enregistrement → ignoré
            log.warning("start ignoré : enregistrement déjà en cours")
            return
        if cmd["borne_id"] not in self.territoire.bornes:
            db.set_live(self.conn, message=f"borne inconnue : {cmd['borne_id']}")
            return
        try:
            self.source.start()
        except Exception as e:
            log.exception("ouverture audio impossible")
            db.set_live(self.conn, status="idle", message=f"micro indisponible : {e}")
            return
        override = cmd["event_ts_override"]
        self.rec = Recording(
            borne_id=cmd["borne_id"],
            event_ts=int(override) if override is not None else int(time.time()),
            is_init=override is not None,  # avis d'initialisation = enregistrés en mode préparation
            last_tick=time.monotonic(),
        )
        db.set_live(
            self.conn, status="recording", committed_text="", partial_text="", langue=None, message="enregistrement…"
        )
        log.info("start (%s)", cmd["borne_id"])

    # -- toutes les TICK_S : VAD (arrêt auto), langue, partiels
    def _tick(self, rec: Recording) -> None:
        self._update_speech(rec)
        if rec.silence_s >= SILENCE_STOP_S or rec.n_samples / SR >= MAX_DUREE_S:
            self._finish("auto")
            return
        if rec.silence_s >= SILENCE_WARN_S:
            db.set_live(self.conn, message=f"silence : arrêt automatique dans {SILENCE_STOP_S - rec.silence_s:.0f} s")
        else:
            db.set_live(self.conn, message="enregistrement…")
        if not self.partiels:
            return
        if rec.language is None:
            if rec.last_speech > 0 and rec.n_samples >= LANG_LOCK_MIN_S * SR:
                rec.language = self.stt.detect(rec.flat())
                db.set_live(self.conn, langue=rec.language)
            return
        self._partial(rec)

    def _update_speech(self, rec: Recording) -> None:
        start = max(0, rec.last_speech - SR)  # 1 s de recouvrement
        segs = speech_segments(rec.flat()[start:])
        if segs:
            rec.last_speech = max(rec.last_speech, start + segs[-1]["end"])

    def _partial(self, rec: Recording) -> None:
        """Valide les chunks clos par une pause, retranscrit le chunk en cours (une passe Whisper au plus)."""
        buf = rec.flat()[rec.committed_pos :]
        if len(buf) < SR // 2:
            return
        segs = speech_segments(buf)
        if not segs:
            return
        cut = None
        if len(buf) - segs[-1]["end"] >= MIN_SILENCE_MS / 1000 * SR:
            cut = segs[-1]["end"]
        elif len(segs) >= 2:  # noqa: PLR2004
            cut = segs[-2]["end"]
        elif len(buf) > MAX_UNCOMMITTED_S * SR:
            cut = len(buf)
        if cut is not None:
            rec.committed.append(self._transcribe(rec, buf[:cut]))
            rec.committed_pos += cut
            partial = ""  # le reste sera retranscrit au tick suivant
        else:
            key = (rec.committed_pos, rec.n_samples)
            if key == rec.partial_key:
                return
            rec.partial_key = key
            partial = self._transcribe(rec, buf)
        db.set_live(self.conn, committed_text=rec.committed_text, partial_text=partial)

    def _transcribe(self, rec: Recording, audio: np.ndarray) -> str:
        prompt = rec.committed_text[-200:] if rec.committed else None
        return self.stt.transcribe(audio, rec.language or DEFAULT_LANG, prompt)

    # -- fin d'enregistrement (stop ou arrêt auto)
    def _finish(self, reason: str) -> None:
        rec = self.rec
        assert rec is not None
        self.source.stop()
        rec.append(self.source.read())
        db.set_live(self.conn, status="transcribing", partial_text="", message="transcription finale…")
        rest = rec.flat()[rec.committed_pos :]
        if speech_segments(rest):
            if rec.language is None:  # enregistrement court : détection sur tout l'audio
                rec.language = self.stt.detect(rec.flat())
            rec.committed.append(self._transcribe(rec, rest))
        transcript = rec.committed_text.strip()
        duree = rec.n_samples / SR
        self.rec = None  # audio libéré, jamais écrit sur disque
        auto = " (arrêt automatique)" if reason == "auto" else ""
        if not transcript:  # invariant 3 : ni Jev, ni insertion
            db.set_live(self.conn, status="idle", committed_text="", langue=None, message="rien capté" + auto)
            log.info("%s : rien capté (%.1f s)", reason, duree)
            return
        try:
            tid = db.insert_transcription(
                self.conn,
                event_ts=rec.event_ts,
                borne_id=rec.borne_id,
                texte=transcript,
                langue=rec.language,
                is_init=rec.is_init,
            )
        except ValueError as e:
            db.set_live(self.conn, status="idle", message=f"avis refusé : {e}")
            return
        log.info("transcription #%d enregistrée (%.1f s, %s)%s", tid, duree, rec.language, auto)
        db.set_live(
            self.conn, status="classifying", committed_text=transcript, langue=rec.language, message=f"#{tid} → Jev…"
        )
        status = classify_transcription(self.conn, tid, self.territoire)
        msg = f"#{tid} classifié" if status == "ok" else f"#{tid} : échec Jev (re-classifiable)"
        db.set_live(self.conn, status="idle", message=msg + auto)


def _heartbeat_loop(db_path: Path, stop: threading.Event) -> None:
    """Thread dédié : le heartbeat continue pendant une transcription ou un appel Jev bloquants."""
    conn = db.connect(db_path)
    while not stop.wait(HEARTBEAT_S):
        db.heartbeat(conn)
    conn.close()


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db", type=Path, default=db.DEFAULT_PATH)
    p.add_argument("--bornes", type=Path, default=bornes.DEFAULT_PATH)
    p.add_argument("--model", default="small", help="taille faster-whisper (small par défaut, base en repli)")
    p.add_argument("--threads", type=int, default=0, help="threads CPU (0 = auto)")
    p.add_argument("--models-dir", type=Path, default=Path(__file__).resolve().parent / "models")
    p.add_argument("--device", default=None, help="périphérique d'entrée (index ou nom, cf. --list-devices)")
    p.add_argument("--list-devices", action="store_true")
    p.add_argument("--no-partiels", action="store_true", help="coupe le stretch 1 : transcription unique au stop")
    p.add_argument("--simulate", nargs="+", metavar="AUDIO", help="rejoue ces fichiers au lieu du micro")
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")

    if args.list_devices:
        import sounddevice as sd

        print(sd.query_devices())
        return
    source: AudioSource
    if args.simulate:
        source = FileSource(args.simulate)
    else:
        import sounddevice as sd

        device = int(args.device) if args.device and args.device.isdigit() else args.device
        log.info("périphériques :\n%s", sd.query_devices())
        log.info("micro : %s", sd.query_devices(device if device is not None else sd.default.device[0])["name"])
        source = MicSource(device)
    if not os.environ.get("OPENROUTER_API_KEY"):
        log.warning("OPENROUTER_API_KEY absente : les avis seront en 'error' (re-classifiables)")
    conn = db.connect(args.db)
    stt = Transcriber(args.model, args.threads, args.models_dir)
    worker = Worker(conn, source, stt, bornes.load(args.bornes), partiels=not args.no_partiels)
    worker.startup()
    stop = threading.Event()  # heartbeat seulement une fois prêt : avant, l'UI affiche « worker arrêté »
    threading.Thread(target=_heartbeat_loop, args=(args.db, stop), daemon=True).start()
    log.info("worker prêt (base : %s)", args.db)
    try:
        while True:
            worker.step()
            time.sleep(POLL_S)
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        source.stop()


if __name__ == "__main__":
    main()
