"""Exécution de l'agent Claude Code de Marguerite."""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from . import config as C
from . import marguerite as M

PROMPT_PATH = Path(__file__).with_name("marguerite_agent_prompt.md")
LOGGER = logging.getLogger(__name__)
_TOOL_NAMES = {
    "contexte",
    "chercher_lieux",
    "lieux_similaires",
    "details_lieu",
    "affluence",
    "conseil_horaire",
    "commerces_proches",
    "calculer_boucle",
    "definir_journee",
}


def _message(payload: dict) -> str:
    lines = [
        "Contexte de la journée (JSON) :",
        json.dumps(payload["jour"], ensure_ascii=False, separators=(",", ":")),
        "Historique :",
    ]
    for index, version in enumerate(payload.get("historique", []), start=1):
        feedback = version.get("feedback") or "Parcours initial"
        steps = " → ".join(step.get("nom", "") for step in version.get("etapes", [])) or "aucune"
        lines.append(
            f"Version {index} — retour : {feedback} → étapes : {steps} "
            f"({version.get('km')} km, {version.get('dplus')} m) — {version.get('resume', '')}"
        )
    lines.append(f"Nouveau retour du visiteur : {payload['feedback']}")
    return "\n".join(lines)


def _tools_used(stdout: str) -> list[str]:
    try:
        output = json.loads(stdout)
    except (TypeError, ValueError):
        return []
    found = []

    def visit(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key in {"name", "tool_name"} and isinstance(item, str):
                    if item.startswith("mcp__marguerite__"):
                        item = item.removeprefix("mcp__marguerite__")
                    if item in _TOOL_NAMES and item not in found:
                        found.append(item)
                if isinstance(item, (dict, list)):
                    visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    visit(output)
    return found


def _notify_progress(on_progress, text: str) -> None:
    if on_progress is None:
        return
    try:
        on_progress(text)
    except Exception:
        pass


def _read_progress(path: Path, offset: int, on_progress) -> int:
    try:
        with path.open("r", encoding="utf-8") as stream:
            stream.seek(offset)
            while True:
                line = stream.readline()
                if not line or not line.endswith("\n"):
                    break
                offset = stream.tell()
                try:
                    item = json.loads(line)
                except (TypeError, ValueError):
                    continue
                text = item.get("texte") if isinstance(item, dict) else None
                if isinstance(text, str) and text.strip():
                    _notify_progress(on_progress, text)
    except OSError:
        pass
    return offset


def run_agent(payload: dict, on_progress=None) -> dict:
    started = time.monotonic()
    _notify_progress(on_progress, "Lecture de votre demande…")
    token = C.secret("CLAUDE_CODE_OAUTH_TOKEN")
    if not token:
        LOGGER.error("Jeton Claude Code absent; ajustement indisponible.")
        raise RuntimeError("Ajustement indisponible pour le moment.")

    prompt = PROMPT_PATH.read_text(encoding="utf-8")
    area = (
        M.zone_v2(payload["zone"]["lat"], payload["zone"]["lon"])
        if payload.get("variante", "v1") == "v2"
        else M.zone(payload["zone"]["lat"], payload["zone"]["lon"])
    )
    with tempfile.TemporaryDirectory(prefix="marguerite-agent-") as temporary:
        session_dir = Path(temporary)
        (session_dir / "contexte.json").write_text(
            json.dumps({"payload": payload, "zone": area}, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        mcp_environment = {
            "PYTHONPATH": os.pathsep.join(
                value for value in (str(C.ROOT), os.environ.get("PYTHONPATH", "")) if value
            ),
            "FLUX_INTERNAL_URL": os.environ.get("FLUX_INTERNAL_URL", "http://127.0.0.1:8000"),
            "FLUX_DATA_DIR": str(C.DATA_DIR),
            "FLUX_ARTIFACTS": str(C.ARTIFACTS),
        }
        mcp_config = {
            "mcpServers": {
                "marguerite": {
                    "command": sys.executable,
                    "args": ["-m", "flux.marguerite_mcp", "--session", str(session_dir)],
                    "env": mcp_environment,
                }
            }
        }
        mcp_path = session_dir / "mcp.json"
        mcp_path.write_text(json.dumps(mcp_config, ensure_ascii=False), encoding="utf-8")
        command = [
            "claude",
            "-p",
            _message(payload),
            "--append-system-prompt",
            prompt,
            "--output-format",
            "json",
            "--model",
            "sonnet",
            "--no-session-persistence",
            "--mcp-config",
            str(mcp_path),
            "--strict-mcp-config",
            "--allowedTools",
            "mcp__marguerite__*",
            "--disallowedTools",
            "Bash Edit Write MultiEdit Read Glob Grep WebFetch WebSearch Task NotebookEdit TodoWrite",
        ]
        environment = os.environ.copy()
        environment["CLAUDE_CODE_OAUTH_TOKEN"] = token
        stdout_path = session_dir / "claude.stdout"
        stderr_path = session_dir / "claude.stderr"
        progress_path = session_dir / "progression.jsonl"
        with (
            stdout_path.open("w+", encoding="utf-8") as stdout_file,
            stderr_path.open("w+", encoding="utf-8") as stderr_file,
        ):
            try:
                process = subprocess.Popen(
                    command,
                    cwd=session_dir,
                    env=environment,
                    stdout=stdout_file,
                    stderr=stderr_file,
                    text=True,
                )
            except FileNotFoundError:
                raise RuntimeError("Ajustement indisponible pour le moment.") from None

            offset = 0
            deadline = time.monotonic() + 150
            while process.poll() is None:
                offset = _read_progress(progress_path, offset, on_progress)
                if time.monotonic() >= deadline:
                    process.kill()
                    process.wait()
                    _read_progress(progress_path, offset, on_progress)
                    raise TimeoutError("L'ajustement a pris trop de temps. Réessayez.")
                time.sleep(0.5)
            process.wait()
            _read_progress(progress_path, offset, on_progress)
            stdout_file.seek(0)
            stdout = stdout_file.read()

        result_path = session_dir / "resultat.json"
        if not result_path.is_file():
            raise RuntimeError("Aucun nouveau parcours n'a pu être proposé. Reformulez votre retour.")
        try:
            proposal = json.loads(result_path.read_text(encoding="utf-8"))
            loop = {
                "stops": proposal["stops"],
                "km": proposal["km"],
                "dplus": proposal["dplus"],
                "green": proposal["green"],
                "voies": proposal["voies"],
                "geom": proposal["geom"],
            }
            resume = proposal["resume"]
            if not isinstance(loop["stops"], list) or not isinstance(loop["geom"], list):
                raise ValueError
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            raise RuntimeError("Le parcours proposé est invalide. Réessayez.") from None
        _notify_progress(on_progress, "Parcours prêt.")
        return {
            "loop": loop,
            "resume": resume,
            "outils": _tools_used(stdout),
            "duree_s": round(time.monotonic() - started, 2),
        }
