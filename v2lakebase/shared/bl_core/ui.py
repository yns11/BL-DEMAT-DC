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


def injecter_style() -> None:
    """Habillage visuel commun aux deux applications, à appeler juste après
    st.set_page_config. Complète le thème déclaré dans .streamlit/config.toml
    (couleurs de base) : ici, uniquement du polish — cartes, boutons, titres."""
    st.markdown(
        """
        <style>
        /* Titre principal : graisse forte + soulignement dégradé court */
        [data-testid="stAppViewContainer"] h1 {
            font-weight: 700;
            letter-spacing: -0.02em;
            padding-bottom: 0.35rem;
            background: linear-gradient(90deg, #0F62A6, #4FA3E3)
                        bottom left / 72px 4px no-repeat;
        }
        /* Boutons : coins arrondis, relief léger au survol */
        .stButton > button, [data-testid="stFormSubmitButton"] > button {
            border-radius: 10px;
            font-weight: 600;
            transition: transform 0.08s ease, box-shadow 0.15s ease;
        }
        .stButton > button:hover, [data-testid="stFormSubmitButton"] > button:hover {
            transform: translateY(-1px);
            box-shadow: 0 4px 14px rgba(15, 98, 166, 0.25);
        }
        /* Barre de progression du wizard en dégradé */
        .stProgress > div > div > div {
            background: linear-gradient(90deg, #0F62A6, #4FA3E3);
        }
        /* Conteneurs bordés et expanders en "cartes" */
        [data-testid="stExpander"], div[data-testid="stVerticalBlockBorderWrapper"] {
            border-radius: 12px;
        }
        [data-testid="stExpander"] {
            border: 1px solid #E3E9F2;
            box-shadow: 0 1px 4px rgba(27, 42, 58, 0.06);
        }
        /* Champs de saisie adoucis */
        .stTextInput input, .stTextArea textarea, .stDateInput input,
        [data-baseweb="select"] > div {
            border-radius: 8px;
        }
        /* Tableau du récapitulatif : lignes aérées */
        [data-testid="stMarkdownContainer"] table { width: 100%; }
        [data-testid="stMarkdownContainer"] td { padding: 0.45rem 0.6rem; }
        /* Pied de page Streamlit masqué (application métier) */
        footer { visibility: hidden; }
        </style>
        """,
        unsafe_allow_html=True,
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


def afficher_photo_volume(id_photo: str) -> None:
    """Affiche une page stockée dans Lakebase (téléchargée via le repository,
    en cache). Nom conservé de la V1 pour ne pas toucher aux applications."""
    try:
        st.image(repository.telecharger_photo(id_photo), use_column_width=True)
    except Exception as e:
        st.caption(f"Image inaccessible : {e}")


def afficher_miniatures(pages: list[bytes]) -> None:
    """Miniatures des pages en attente (max 4 par ligne pour rester lisible sur mobile)."""
    for debut in range(0, len(pages), 4):
        cols = st.columns(4)
        for i, img in enumerate(pages[debut : debut + 4]):
            with cols[i]:
                st.image(img, caption=f"Page {debut + i + 1}", use_column_width=True)
