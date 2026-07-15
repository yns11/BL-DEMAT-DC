"""Aides d'interface communes aux deux applications."""

import logging
import sys

import streamlit as st

from . import repository


def configurer_logs() -> None:
    """Logs structurés vers stdout : repris par `databricks apps logs` et par la
    télémétrie OTEL de Databricks Apps si elle est activée sur l'app."""
    if not logging.getLogger().handlers:
        logging.basicConfig(
            stream=sys.stdout,
            level=logging.INFO,
            format='{"ts":"%(asctime)s","niveau":"%(levelname)s","logger":"%(name)s","message":"%(message)s"}',
        )


# --- Messages "flash" : survivent à un st.rerun (sinon le message disparaît
# avant que l'utilisateur ait pu le lire). ---
def set_flash(kind: str, message: str) -> None:
    st.session_state["flash"] = (kind, message)


def show_flash() -> None:
    flash = st.session_state.pop("flash", None)
    if flash:
        kind, message = flash
        getattr(st, kind)(message)


def libelle_statut(statut_bl: str) -> str:
    return "✅ OK" if statut_bl == repository.STATUT_OK else "🟥 EDI NOK"


def afficher_photo_volume(chemin: str) -> None:
    """Affiche une image stockée sur le Volume UC (téléchargée via l'API Files,
    en cache). use_column_width : compatible avec le Streamlit du runtime."""
    try:
        st.image(repository.telecharger_photo(chemin), use_column_width=True)
    except Exception as e:
        st.caption(f"Image inaccessible sur le volume : {e}")


def afficher_miniatures(pages: list[bytes]) -> None:
    """Miniatures des pages en attente (max 4 par ligne pour rester lisible sur mobile)."""
    for debut in range(0, len(pages), 4):
        cols = st.columns(4)
        for i, img in enumerate(pages[debut : debut + 4]):
            with cols[i]:
                st.image(img, caption=f"Page {debut + i + 1}", use_column_width=True)
