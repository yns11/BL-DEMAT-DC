"""Identité de l'utilisateur connecté (SSO Databricks Apps).

Databricks Apps authentifie chaque visiteur en amont (OAuth SSO) et transmet
son identité dans les en-têtes HTTP de la requête. Streamlit les expose via
st.context.headers. Aucune gestion de mot de passe côté app.
"""

import streamlit as st


def get_current_user() -> str:
    """Nom de l'utilisateur SSO, pour la traçabilité (saisie_par / modifie_par)."""
    try:
        headers = st.context.headers
        user = headers.get("X-Forwarded-Preferred-Username") or headers.get("X-Forwarded-Email")
        if user:
            return user
    except Exception:
        pass
    # Exécution locale (développement) : pas d'en-têtes de proxy Databricks.
    return "developpement-local"
