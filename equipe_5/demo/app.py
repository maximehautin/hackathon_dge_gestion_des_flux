"""Démo live, écran projeté : colonne « Backend » (STT + base) | colonne « Frontend » (mockup téléphone).

Lancement : `streamlit run demo/app.py` (le worker doit tourner : `python demo/worker.py`).
Préparation (date simulée, avis d'initialisation) : `DEMO_PREP=1 streamlit run demo/app.py`.
"""

from __future__ import annotations

import html
import json
import logging
import os
import sqlite3
import time
from datetime import datetime, timedelta
from typing import Any

import bornes
import db
import folium
import pandas as pd
import periods
import reference
import streamlit as st
import worker
from streamlit_folium import st_folium

st.set_page_config(page_title="La borne qui écoute", page_icon="⛰️", layout="wide")

PREP = os.environ.get("DEMO_PREP") == "1"
log = logging.getLogger("app")
HEARTBEAT_LOST_S = 5  # invariant 6
NULL = "—"
N_LATEST = 10

BLUE, RED, NEUTRAL, MUTED = "#2a78d6", "#e34948", "#f0efec", "#a3a29c"
NO_DATA = "#b5b4ae"  # borne sans avis : remplissage neutre
# Échelles 0..100 (arrêts répartis uniformément)
SCALES = {
    "satisfaction": ("#d73027", "#fc8d59", "#fee08b", "#91cf60", "#1a9850"),  # rouge → vert
    "affluence": (BLUE, NEUTRAL, RED),  # calme → saturé
    "provenance": ("#fde725", "#5ec962", "#21918c", "#3b528b", "#440154"),  # jaune → violet (viridis)
}
IGN_PLAN = (
    "https://data.geopf.fr/wmts?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0"
    "&LAYER=GEOGRAPHICALGRIDSYSTEMS.PLANIGNV2&STYLE=normal&TILEMATRIXSET=PM&FORMAT=image/png"
    "&TILEMATRIX={z}&TILEROW={y}&TILECOL={x}"
)

st.markdown(
    """
<style>
.block-container { padding-top: 3.5rem; max-width: 100%; }
.st-key-phone {  /* format smartphone : 390 x 844 px d'écran */
  width: 412px; height: 866px; flex: none; margin: 0 auto; padding: 34px 12px 16px 12px; overflow: hidden;
  border: 11px solid #1b1b1d; border-radius: 48px; background: #fcfcfb;
  box-shadow: 0 18px 40px rgba(0,0,0,.25); position: relative; gap: .5rem;
}
.st-key-nav button { min-height: 0; padding: 0 .45rem; line-height: 1.4; }
.spin { display:inline-block; width:12px; height:12px; margin-right:6px; vertical-align: middle;
  border: 2px solid #d6d5d0; border-top-color: #2a78d6; border-radius: 50%; animation: spin .8s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
.st-key-phone::before {
  content: ""; position: absolute; top: 8px; left: 50%; transform: translateX(-50%);
  width: 110px; height: 22px; background: #1b1b1d; border-radius: 12px;
}
.phone-head { display:flex; justify-content:space-between; align-items:center; margin-top: 6px;
  font-weight: 700; font-size: 1.05rem; color: #0b0b0b; }
.phone-sub { color: #52514e; font-size: .8rem; }
[data-testid="stColumn"]:has(.st-key-phone) { border-left: 1px solid #d6d5d0; padding-left: 2rem; }
.badge { display:inline-block; padding: 1px 8px; border-radius: 999px; font-size: .75rem; font-weight: 600; }
.badge-live { background:#e34948; color:#fff; }
.badge-hist { background:#e8e7e3; color:#52514e; }
.live-box { border: 1px solid #e3e2de; border-radius: 10px; padding: 12px 14px; min-height: 96px;
  background: #fff; font-size: 1.05rem; line-height: 1.5; color: #0b0b0b; }
.live-box .partial { color: #8a8984; font-style: italic; }
.status { font-size: .9rem; color: #52514e; margin-bottom: 6px; }
.dot { display:inline-block; width:10px; height:10px; border-radius:50%; margin-right:6px; vertical-align: middle; }
.legend-bar { height: 10px; border-radius: 5px; margin: 2px 0; }
.legend-row { display:flex; justify-content:space-between; color:#52514e; font-size:.72rem; }
</style>
""",
    unsafe_allow_html=True,
)

TERR = bornes.load()


@st.cache_resource
def init_db() -> None:
    """Une fois par processus : schéma et bornes (la carte s'affiche même sans worker)."""
    db.upsert_bornes(db.thread_conn(db.DEFAULT_PATH), TERR.bornes.values())


def conn() -> sqlite3.Connection:
    """Jamais de connexion partagée entre threads (sessions et fragments Streamlit) : une par thread."""
    return db.thread_conn(db.DEFAULT_PATH)


@st.cache_data(show_spinner=False)
def frequentations(mois: int) -> dict[str, reference.Frequentation | None]:
    try:
        compteurs = {b.id: b.compteur for b in TERR.bornes.values()}
        return reference.frequentations(compteurs, mois)
    except (FileNotFoundError, KeyError, ValueError):
        log.exception("fréquentation de référence indisponible (tooltip : « indisponible »)")
        return dict.fromkeys(TERR.bornes)


init_db()
ss = st.session_state
ss.setdefault("win", None)  # None = demi-journée en cours (live) ; sinon clé de demi-journée
ss.setdefault("expect", None)  # (statut attendu, instant) juste après un clic
ss.setdefault("detail_id", None)  # ligne sélectionnée dans le tableau (clic)
ss.setdefault("table_ver", 0)  # change la clé du tableau : efface une sélection devenue obsolète
ss.setdefault("to_classify", None)  # transcription saisie à la main, à classifier (avec spinner)
ss.setdefault("flash", None)


def fmt_ts(ts: int) -> str:
    return datetime.fromtimestamp(ts, periods.TZ).strftime("%d/%m %H:%M")


# --- colonne Backend --------------------------------------------------------------

STATUS_UI = {
    "idle": ("#1baf7a", "Prêt"),
    "recording": (RED, "Enregistrement"),
    "transcribing": ("#eda100", "Transcription finale"),
    "classifying": (BLUE, "Classification Jev"),
    "offline": (MUTED, "Worker arrêté"),
}
BUSY = ("transcribing", "classifying")


def worker_status() -> tuple[str, Any]:
    live = db.get_live(conn())
    if live["updated_at"] is None or time.time() - live["updated_at"] > HEARTBEAT_LOST_S:
        return "offline", live
    return live["status"] or "idle", live


def simulated_ts() -> int | None:
    """Mode préparation : horodatage choisi (date simulée), sinon None (horloge du worker)."""
    if not PREP:
        return None
    local = datetime.combine(ss.sim_date, ss.sim_time, periods.TZ)
    return int(local.timestamp())


def _send(cmd: str) -> None:
    if cmd == "start":
        db.push_command(conn(), "start", borne_id=ss.borne, event_ts_override=simulated_ts())
        ss.expect = ("recording", time.monotonic())
    else:
        db.push_command(conn(), "stop")
        ss.expect = ("transcribing", time.monotonic())


@st.fragment(run_every=1.0)
def live_panel() -> None:
    status, live = worker_status()
    exp = ss.expect
    if exp and time.monotonic() - exp[1] < 3 and status not in (exp[0], "offline"):  # noqa: PLR2004
        status = exp[0]  # le worker n'a pas encore pris la commande en compte
    elif exp:
        ss.expect = None
    future = PREP and (simulated_ts() or 0) > time.time()
    c1, c2 = st.columns([2, 1], vertical_alignment="bottom")
    c1.selectbox(
        "Borne",
        list(TERR.bornes),
        format_func=lambda k: f"{TERR.bornes[k].name} · {TERR.bornes[k].commune} ({TERR.bornes[k].id_ens})",
        key="borne",
        disabled=status == "recording",
    )
    if status == "recording":
        c2.button("■  Stop", type="primary", width="stretch", key="btn_stop", on_click=_send, args=("stop",))
    else:
        c2.button(
            "●  Enregistrer",
            type="primary",
            width="stretch",
            key="btn_start",
            disabled=status != "idle" or future,
            on_click=_send,
            args=("start",),
        )
    if status == "offline":
        st.error("Worker arrêté (pas de heartbeat depuis plus de 5 s) : lancer `python demo/worker.py`.", icon="⚠️")
    if future:
        st.warning("Date simulée dans le futur : refusée.")
    color, label = STATUS_UI.get(status, (MUTED, status))
    spin = '<span class="spin"></span>' if status in BUSY else ""
    lang = f" · langue : <b>{html.escape(live['langue'])}</b>" if live["langue"] else ""
    msg = f" — {html.escape(live['message'])}" if live["message"] and status != "offline" else ""
    st.markdown(
        f'<div class="status"><span class="dot" style="background:{color}"></span>{spin}<b>{label}</b>{lang}{msg}'
        "</div>",
        unsafe_allow_html=True,
    )
    committed = html.escape(live["committed_text"] or "")
    partial = html.escape(live["partial_text"] or "")
    body = committed + (f' <span class="partial">{partial}</span>' if partial else "")
    body = body or '<span class="partial">La transcription apparaît ici pendant l\'enregistrement…</span>'
    st.markdown(f'<div class="live-box">{body}</div>', unsafe_allow_html=True)


def _fmt_score(v: float | None) -> str:
    return NULL if v is None else f"{v:.0f}"


def _status(r: Any) -> str:
    return {"ok": "✅ ok", "error": "⚠️ erreur", None: "⏳ en cours"}[r["status"]]


def _reclassify(tid: int) -> None:
    worker.classify_transcription(conn(), tid, TERR)


def _delete(tid: int) -> None:
    db.delete_transcription(conn(), tid)
    ss.detail_id = None


def _close_detail() -> None:
    ss.detail_id = None
    ss.table_ver += 1  # nouvelle clé : efface aussi la sélection affichée dans le tableau


def _on_select(ids: list[int]) -> None:
    sel = ss[f"table_{ss.table_ver}"].selection
    rows = sel.rows or [row for row, _ in sel.cells]  # clic sur la case de ligne ou sur n'importe quelle cellule
    ss.detail_id = ids[rows[0]] if rows else None


def _save_text(tid: int | None) -> None:
    """Texte saisi à la main : met à jour la transcription (ou en crée une), puis la classification suit."""
    key = f"edit_{tid}" if tid is not None else "new_text"
    texte = ss[key].strip()
    if not texte:
        ss.flash = "Texte vide : rien n'est enregistré."
        return
    try:
        if tid is None:  # saisie sans audio : nouvel avis sur la borne sélectionnée
            tid = db.insert_transcription(
                conn(),
                event_ts=simulated_ts() or int(time.time()),
                borne_id=ss.borne,
                texte=texte,
                langue=None,
                is_init=PREP,
            )
            ss.new_text = ""
        else:
            db.update_texte(conn(), tid, texte)
    except ValueError as e:
        ss.flash = str(e)
        return
    ss.detail_id = tid
    ss.to_classify = tid


def detail_panel(rows: list[Any]) -> None:
    """Détail de la ligne cliquée, avec texte modifiable ; sans sélection, saisie d'un avis sans audio."""
    if ss.flash:
        st.warning(ss.flash)
        ss.flash = None
    if ss.to_classify is not None:
        with st.spinner(f"Classification Jev de #{ss.to_classify}…"):
            worker.classify_transcription(conn(), ss.to_classify, TERR)
        ss.to_classify = None
    r = next((r for r in rows if r["id"] == ss.detail_id), None)
    if r is None:
        st.caption("Cliquer sur une ligne du tableau pour la détailler. Ou saisir un avis à la main (sans audio) :")
        st.text_area("Saisie manuelle", key="new_text", height=90, label_visibility="collapsed")
        st.button("✍️ Ajouter l'avis et classifier", key="add", on_click=_save_text, args=(None,))
        return
    tid = r["id"]
    st.caption(f"#{tid} · {r['borne_name']} · langue {r['langue'] or NULL}" + (" · init" if r["is_init"] else ""))
    st.text_area("Transcription", value=r["texte"], key=f"edit_{tid}", height=90, label_visibility="collapsed")
    c1, c2, c3 = st.columns([2, 1, 1])
    c1.button("💾 Mettre à jour et re-classifier", key="save", on_click=_save_text, args=(tid,), width="stretch")
    c2.button("🗑 Supprimer", key="del", on_click=_delete, args=(tid,), width="stretch")
    c3.button("✖ Fermer", key="close", on_click=_close_detail, width="stretch")
    if r["jev_raw"]:
        st.json(json.loads(r["jev_raw"]), expanded=False)


@st.fragment(run_every=1.0)
def latest_panel() -> None:
    rows = db.latest(conn(), N_LATEST)
    if not rows:
        st.info("Aucun avis en base pour l'instant.")
        detail_panel(rows)
        return
    ids = [r["id"] for r in rows]
    if ss.get("table_ids") != ids:  # nouvelles lignes : les index de sélection ne sont plus valables
        ss.table_ids = ids
        ss.table_ver += 1
    df = pd.DataFrame(
        [
            {
                "#": r["id"],
                "heure": fmt_ts(r["event_ts"]),
                "borne": r["borne_name"],
                "texte": r["texte"] if len(r["texte"]) <= 70 else r["texte"][:69] + "…",  # noqa: PLR2004
                "satisf.": _fmt_score(r["satisfaction"]),
                "affl.": _fmt_score(r["affluence"]),
                "provenance": r["provenance"] or NULL,
                "transport": r["transport"] or NULL,
                "profil": r["profil"] or NULL,
                "statut": _status(r),
            }
            for r in rows
        ]
    )
    st.dataframe(
        df,
        hide_index=True,
        width="stretch",
        key=f"table_{ss.table_ver}",
        on_select=lambda: _on_select(ids),
        selection_mode=["single-row", "single-cell"],
        column_config={
            "#": st.column_config.NumberColumn(width=40),
            "heure": st.column_config.TextColumn(width=90),
            "texte": st.column_config.TextColumn(width="medium"),
            "statut": st.column_config.TextColumn(width=95),
        },
    )
    for r in [r for r in rows if r["status"] == "error"][:3]:
        err = json.loads(r["jev_raw"]).get("error", "") if r["jev_raw"] else ""
        c1, c2 = st.columns([3, 1])
        c1.caption(f"⚠️ #{r['id']} : {html.escape(str(err)[:140])}")
        c2.button(f"Re-classifier #{r['id']}", key=f"recl_{r['id']}", on_click=_reclassify, args=(r["id"],))
    detail_panel(rows)


# --- colonne Frontend (mockup téléphone) ------------------------------------------

CRITERES = {"satisfaction": "Satisfaction", "affluence": "Affluence\nressentie", "provenance": "Provenance"}
CRIT_LABEL = {
    "satisfaction": "Satisfaction globale",
    "affluence": "Affluence ressentie",
    "provenance": "Proportion de touristes",
}


def _hex(c: str) -> tuple[int, int, int]:
    return int(c[1:3], 16), int(c[3:5], 16), int(c[5:7], 16)


def _mix(a: str, b: str, t: float) -> str:
    ra, rb = _hex(a), _hex(b)
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(ra, rb, strict=True))


def color_for(crit: str, v: float) -> str:
    """0..100 → couleur, interpolée entre les arrêts de l'échelle du critère."""
    stops = SCALES[crit]
    x = min(max(v, 0.0), 100.0) / 100 * (len(stops) - 1)
    i = min(int(x), len(stops) - 2)
    return _mix(stops[i], stops[i + 1], x - i)


def legend_html(crit: str) -> str:
    stops = ", ".join(color_for(crit, v) for v in (0, 25, 50, 75, 100))
    ends = {
        "satisfaction": ("mécontent", "satisfait"),
        "affluence": ("personne", "trop de monde"),
        "provenance": ("excursionnistes / habitants", "touristes"),
    }[crit]
    return (
        f'<div class="legend-bar" style="background:linear-gradient(90deg,{stops})"></div>'
        f'<div class="legend-row"><span>{ends[0]}</span><span>{ends[1]}</span></div>'
    )


def _radius(freq: reference.Frequentation | None, vmax: float) -> float:
    """Rayon proportionnel à la fréquentation (linéaire : l'écart entre bornes est accentué)."""
    if freq is None or vmax <= 0:
        return 8.0
    return 5 + 25 * freq.valeur / vmax


def _tooltip(agg: Any, crit: str, val: float | None, freq: reference.Frequentation | None) -> str:
    unit = " %" if crit == "provenance" else " / 100"
    crit_txt = f"{CRIT_LABEL[crit]} : {val:.0f}{unit}" if val is not None else f"{CRIT_LABEL[crit]} : {NULL}"
    freq_txt = (
        f"Fréquentation ≈ {freq.valeur:.0f} passages / demi-journée (simulé : moyenne du mois, "
        f"compteur « {freq.compteur} », {freq.periode})"
        if freq
        else "Fréquentation : indisponible"
    )
    return f"<b>{html.escape(agg['name'])}</b><br>{agg['n_avis']} avis<br>{crit_txt}<br>{html.escape(freq_txt)}"


CRIT_COLUMN = {"satisfaction": "satisfaction", "affluence": "affluence", "provenance": "part_hors"}


def base_map() -> folium.Map:
    """Fond de carte fixe (Plan IGN en niveaux de gris, cadré sur les bornes) : jamais rechargé."""
    m = folium.Map(tiles=None)
    folium.TileLayer(IGN_PLAN, attr="© IGN Plan", name="Plan IGN", max_zoom=19).add_to(m)
    m.get_root().header.add_child(  # type: ignore[attr-defined]
        folium.Element(
            "<style>.leaflet-tile-pane { filter: grayscale(1) brightness(1.05) contrast(.9); }"
            ".leaflet-control-attribution { font-size: 8px !important; }</style>"
        )
    )
    lats = [b.lat for b in TERR.bornes.values()]
    lons = [b.lon for b in TERR.bornes.values()]
    m.fit_bounds([(min(lats), min(lons)), (max(lats), max(lons))], padding=(40, 40))
    return m


def bornes_layer(aggs: list[Any], crit: str, freqs: dict[str, reference.Frequentation | None]) -> folium.FeatureGroup:
    """Couche des bornes : seule partie mise à jour quand le critère ou la fenêtre change."""
    fg = folium.FeatureGroup(name="bornes")
    vmax = max((f.valeur for f in freqs.values() if f), default=0.0)
    for a in aggs:
        val = a[CRIT_COLUMN[crit]]
        freq = freqs.get(a["borne_id"])
        tip = _tooltip(a, crit, val, freq)
        folium.CircleMarker(
            location=(a["lat"], a["lon"]),
            radius=_radius(freq, vmax),
            tooltip=folium.Tooltip(tip, style="white-space: normal; width: 230px; font-size: 12px;"),
            popup=folium.Popup(tip, max_width=260),
            color="#ffffff",
            weight=2,
            fill_color=color_for(crit, val) if val is not None else NO_DATA,
            fill_opacity=0.95,
        ).add_to(fg)
    return fg


def _nav(step: int) -> None:
    cur = periods.demi_journee(int(time.time()))
    nxt = periods.decaler(ss.win or cur, step)
    ss.win = None if periods.intervalle(nxt) >= periods.intervalle(cur) else nxt


def window_controls() -> str:
    """Date affichée, avec ◀ / ▶ à sa droite ; retourne la demi-journée. Plus de ▶ possible = live."""
    cur = periods.demi_journee(int(time.time()))
    if ss.win and periods.intervalle(ss.win) >= periods.intervalle(cur):
        ss.win = None
    dj = ss.win or cur
    with st.container(key="nav", horizontal=True, vertical_alignment="center", gap="small"):
        badge = (
            '<span class="badge badge-live">● LIVE</span>'
            if ss.win is None
            else '<span class="badge badge-hist">Historique</span>'
        )
        st.markdown(f'{badge} <span class="phone-sub">{periods.libelle(dj)}</span>', unsafe_allow_html=True)
        st.button("◀", key="prev", type="tertiary", on_click=_nav, args=(-1,))
        st.button("▶", key="next", type="tertiary", disabled=ss.win is None, on_click=_nav, args=(1,))
    return dj


@st.fragment(run_every=1.0)
def phone() -> None:
    now = datetime.now(periods.TZ)
    st.markdown(
        f'<div class="phone-head"><span>⛰️ La borne qui écoute</span><span class="phone-sub">{now:%H:%M}</span></div>',
        unsafe_allow_html=True,
    )
    dj = window_controls()
    crit = st.segmented_control(
        "Critère",
        list(CRITERES),
        format_func=lambda k: CRITERES[k],
        key="crit",
        required=True,
        default="satisfaction",
        width="stretch",
        label_visibility="collapsed",
    )
    aggs = db.agregats(conn(), *periods.intervalle(dj))
    freqs = frequentations(periods.mois(dj))
    st_folium(
        base_map(),
        feature_group_to_add=bornes_layer(aggs, crit, freqs),
        height=620,
        use_container_width=True,
        returned_objects=[],
        key="map",
    )
    st.markdown(legend_html(crit), unsafe_allow_html=True)


# --- mise en page -----------------------------------------------------------------

col_b, col_f = st.columns([1.45, 1], gap="large")
with col_b:
    if PREP:
        now = datetime.now(periods.TZ)
        c1, c2 = st.columns(2)
        c1.date_input("Date simulée", key="sim_date", value=now.date(), max_value=now.date())
        c2.time_input(
            "Heure", key="sim_time", value=now.time().replace(second=0, microsecond=0), step=timedelta(minutes=15)
        )
        st.caption("🧪 Mode préparation : les avis enregistrés sont marqués « initialisation » (`is_init=1`).")
    live_panel()
    st.markdown(f"#### Dernières lignes ({N_LATEST})")
    latest_panel()

with col_f, st.container(key="phone"):
    phone()
