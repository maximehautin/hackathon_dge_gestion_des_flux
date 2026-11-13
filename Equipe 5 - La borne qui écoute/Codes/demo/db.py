"""SQLite (mode WAL) partagée entre le worker et l'app : schéma, connexion, requêtes."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from bornes import Borne

DEFAULT_PATH = Path(os.environ.get("DEMO_DB", Path(__file__).resolve().parent.parent / "data" / "demo.db"))
FUTURE_TOLERANCE_S = 5  # dérive d'horloge tolérée entre l'app et le worker

SCHEMA = """
CREATE TABLE IF NOT EXISTS bornes (
  id   TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  lon  REAL NOT NULL,
  lat  REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS transcription (
  id         INTEGER PRIMARY KEY,
  event_ts   INTEGER NOT NULL,
  borne_id   TEXT NOT NULL REFERENCES bornes(id),
  texte      TEXT NOT NULL CHECK (texte <> ''),
  langue     TEXT,
  is_init    INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_transcription_ts ON transcription(event_ts);

CREATE TABLE IF NOT EXISTS inference_avis (
  transcription_id INTEGER PRIMARY KEY REFERENCES transcription(id) ON DELETE CASCADE,
  status       TEXT NOT NULL CHECK (status IN ('ok','error')),
  satisfaction REAL CHECK (satisfaction BETWEEN 0 AND 100),
  affluence    REAL CHECK (affluence BETWEEN 0 AND 100),
  provenance   TEXT,
  transport    TEXT,
  profil       TEXT,
  jev_raw      TEXT
);

CREATE TABLE IF NOT EXISTS live_state (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  status TEXT,
  committed_text TEXT, partial_text TEXT,
  langue TEXT,                          -- langue verrouillée de l'enregistrement en cours
  message TEXT,                         -- ex. « rien capté », compte à rebours de l'arrêt auto
  updated_at INTEGER
);
INSERT OR IGNORE INTO live_state (id, status, committed_text, partial_text) VALUES (1, 'idle', '', '');

CREATE TABLE IF NOT EXISTS control (
  id INTEGER PRIMARY KEY,
  cmd TEXT CHECK (cmd IN ('start','stop')),
  borne_id TEXT REFERENCES bornes(id),
  event_ts_override INTEGER,
  consumed INTEGER DEFAULT 0
);
"""

INFERENCE_COLUMNS = ("satisfaction", "affluence", "provenance", "transport", "profil")

_READ_VIEW = """
SELECT t.id, t.event_ts, t.borne_id, b.name AS borne_name, t.texte, t.langue, t.is_init,
       i.status, i.satisfaction, i.affluence, i.provenance, i.transport, i.profil, i.jev_raw
FROM transcription t
JOIN bornes b ON b.id = t.borne_id
LEFT JOIN inference_avis i ON i.transcription_id = t.id
"""


def connect(path: Path | str = DEFAULT_PATH) -> sqlite3.Connection:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=10, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 10000")
    conn.executescript(SCHEMA)
    return conn


_local = threading.local()


def thread_conn(path: Path | str = DEFAULT_PATH) -> sqlite3.Connection:
    """Connexion propre au thread appelant, ouverte au premier appel.

    Un objet `sqlite3.Connection` ne doit jamais être utilisé par deux threads à la fois :
    l'app Streamlit exécute les sessions et leurs fragments dans des threads différents.
    """
    conns: dict[str, sqlite3.Connection] = _local.__dict__.setdefault("conns", {})
    key = str(path)
    if key not in conns:
        conns[key] = connect(path)
    return conns[key]


def upsert_bornes(conn: sqlite3.Connection, bornes: Iterable[Borne]) -> None:
    conn.executemany(
        """INSERT INTO bornes (id, name, lon, lat) VALUES (?, ?, ?, ?)
           ON CONFLICT(id) DO UPDATE SET name = excluded.name, lon = excluded.lon, lat = excluded.lat""",
        [(b.id, b.name, b.lon, b.lat) for b in bornes],
    )


# --- transcriptions et inférences ----------------------------------------------


def insert_transcription(  # noqa: PLR0913 - arguments nommés, un par colonne
    conn: sqlite3.Connection,
    *,
    event_ts: int,
    borne_id: str,
    texte: str,
    langue: str | None,
    is_init: bool = False,
    now: float | None = None,
) -> int:
    if event_ts > (now if now is not None else time.time()) + FUTURE_TOLERANCE_S:
        raise ValueError(f"event_ts dans le futur refusé : {event_ts}")
    cur = conn.execute(
        "INSERT INTO transcription (event_ts, borne_id, texte, langue, is_init) VALUES (?, ?, ?, ?, ?)",
        (int(event_ts), borne_id, texte, langue, int(is_init)),
    )
    return int(cur.lastrowid or 0)


def set_inference(conn: sqlite3.Connection, transcription_id: int, status: str, cols: dict[str, Any], raw: Any) -> None:
    """Insère ou remplace (re-classification) la ligne d'inférence d'une transcription."""
    conn.execute(
        f"""INSERT OR REPLACE INTO inference_avis (transcription_id, status, {", ".join(INFERENCE_COLUMNS)}, jev_raw)
            VALUES (?, ?, {", ".join("?" * len(INFERENCE_COLUMNS))}, ?)""",
        (
            transcription_id,
            status,
            *(cols.get(c) for c in INFERENCE_COLUMNS),
            json.dumps(raw, ensure_ascii=False) if raw is not None else None,
        ),
    )


def update_texte(conn: sqlite3.Connection, transcription_id: int, texte: str) -> None:
    """Texte corrigé à la main : l'ancienne inférence est supprimée (la ligne repasse « en cours »)."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute("UPDATE transcription SET texte = ? WHERE id = ?", (texte, transcription_id))
        conn.execute("DELETE FROM inference_avis WHERE transcription_id = ?", (transcription_id,))
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


def delete_transcription(conn: sqlite3.Connection, transcription_id: int) -> None:
    conn.execute("DELETE FROM transcription WHERE id = ?", (transcription_id,))  # l'inférence suit (CASCADE)


def get_avis(conn: sqlite3.Connection, transcription_id: int) -> sqlite3.Row | None:
    row: sqlite3.Row | None = conn.execute(_READ_VIEW + "WHERE t.id = ?", (transcription_id,)).fetchone()
    return row


def latest(conn: sqlite3.Connection, n: int = 10) -> list[sqlite3.Row]:
    return conn.execute(_READ_VIEW + "ORDER BY t.id DESC LIMIT ?", (n,)).fetchall()


def agregats(conn: sqlite3.Connection, debut: int | None, fin: int | None) -> list[sqlite3.Row]:
    """Par borne, sur les avis de `[debut, fin)` (tout le passé si None) : moyennes sur les non-NULL.

    `part_hors` = % de visiteurs hors département parmi ceux dont la provenance est connue.
    """
    window = "" if debut is None or fin is None else "AND t.event_ts >= :debut AND t.event_ts < :fin"
    return conn.execute(
        f"""SELECT b.id AS borne_id, b.name, b.lat, b.lon,
                   COUNT(t.id) AS n_avis,
                   AVG(i.satisfaction) AS satisfaction, COUNT(i.satisfaction) AS n_satisfaction,
                   AVG(i.affluence) AS affluence, COUNT(i.affluence) AS n_affluence,
                   AVG(CASE i.provenance WHEN 'hors_departement' THEN 100.0 WHEN 'departement' THEN 0.0 END)
                     AS part_hors,
                   COUNT(i.provenance) AS n_provenance
            FROM bornes b
            LEFT JOIN transcription t ON t.borne_id = b.id {window}
            LEFT JOIN inference_avis i ON i.transcription_id = t.id AND i.status = 'ok'
            GROUP BY b.id ORDER BY b.rowid""",
        {"debut": debut, "fin": fin},
    ).fetchall()


# --- live_state -----------------------------------------------------------------


def get_live(conn: sqlite3.Connection) -> sqlite3.Row:
    row: sqlite3.Row = conn.execute("SELECT * FROM live_state WHERE id = 1").fetchone()
    return row


def set_live(conn: sqlite3.Connection, **fields: Any) -> None:
    fields["updated_at"] = int(time.time())
    conn.execute(f"UPDATE live_state SET {', '.join(f'{k} = ?' for k in fields)} WHERE id = 1", tuple(fields.values()))


def heartbeat(conn: sqlite3.Connection) -> None:
    conn.execute("UPDATE live_state SET updated_at = ? WHERE id = 1", (int(time.time()),))


# --- control --------------------------------------------------------------------


def push_command(
    conn: sqlite3.Connection, cmd: str, borne_id: str | None = None, event_ts_override: int | None = None
) -> int:
    cur = conn.execute(
        "INSERT INTO control (cmd, borne_id, event_ts_override) VALUES (?, ?, ?)", (cmd, borne_id, event_ts_override)
    )
    return int(cur.lastrowid or 0)


def pop_commands(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Commandes non consommées, dans l'ordre d'`id`, marquées consommées dans la même transaction."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        rows = conn.execute("SELECT * FROM control WHERE consumed = 0 ORDER BY id").fetchall()
        conn.execute("UPDATE control SET consumed = 1 WHERE consumed = 0 AND id <= ?", (rows[-1]["id"] if rows else 0,))
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")
    return rows


def reset_on_startup(conn: sqlite3.Connection) -> int:
    """Invariant 5 : live_state à idle, commandes périmées consommées, orphelines en `error`."""
    set_live(conn, status="idle", committed_text="", partial_text="", langue=None, message="prêt")
    conn.execute("UPDATE control SET consumed = 1 WHERE consumed = 0")
    orphans = [
        r["id"]
        for r in conn.execute(
            "SELECT t.id FROM transcription t LEFT JOIN inference_avis i ON i.transcription_id = t.id "
            "WHERE i.transcription_id IS NULL"
        )
    ]
    for tid in orphans:
        set_inference(conn, tid, "error", {}, {"error": "classification interrompue (worker redémarré)"})
    return len(orphans)
