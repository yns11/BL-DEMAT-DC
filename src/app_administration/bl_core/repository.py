"""Couche d'accès aux données (repository) — isolée de l'UI Streamlit.

- Connexion Databricks SQL Warehouse via databricks-sql-connector et
  l'authentification OAuth du service principal de l'app (Config()).
- Toutes les requêtes sont paramétrées (aucune concaténation de valeurs) :
  protection systématique contre l'injection SQL.
- Streamlit n'est utilisé ici que pour la mise en cache des ressources.
"""

import logging
import uuid
import datetime
from typing import Optional

import pandas as pd
import streamlit as st
from databricks import sql
from databricks.sdk import WorkspaceClient
from databricks.sdk.core import Config

from .config import Settings, get_settings

logger = logging.getLogger("bl.repository")

STATUT_OK = "1"
STATUT_EDI_NOK = "0"


# ---------------------------------------------------------------------------
# Connexions (mises en cache : une par processus d'app, pas une par requête)
# ---------------------------------------------------------------------------
@st.cache_resource(show_spinner=False)
def _get_connection():
    cfg = Config()
    settings = get_settings()
    if not settings.warehouse_id:
        raise RuntimeError(
            "DATABRICKS_WAREHOUSE_ID absent : vérifiez la ressource d'app 'sql-warehouse' "
            "et le valueFrom correspondant dans app.yaml."
        )
    return sql.connect(
        server_hostname=cfg.host,
        http_path=f"/sql/1.0/warehouses/{settings.warehouse_id}",
        credentials_provider=lambda: cfg.authenticate,
    )


@st.cache_resource(show_spinner=False)
def get_workspace_client() -> WorkspaceClient:
    """Client SDK pour l'API Files (le conteneur d'app n'a pas /Volumes monté en local)."""
    return WorkspaceClient()


def _run(query: str, params: Optional[dict] = None, fetch: bool = False):
    """Exécute une requête paramétrée. Reconstruit la connexion si elle a expiré."""
    for tentative in (1, 2):
        conn = _get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(query, params)
                if fetch:
                    cols = [d[0] for d in cursor.description]
                    return pd.DataFrame(cursor.fetchall(), columns=cols)
                return None
        except Exception as e:
            message = str(e).lower()
            if tentative == 1 and ("closed" in message or "session" in message or "expired" in message):
                logger.warning("Connexion SQL expirée, reconnexion : %s", e)
                _get_connection.clear()
                continue
            logger.error("Erreur SQL : %s | requête : %s", e, query.strip().split("\n")[0])
            raise


# ---------------------------------------------------------------------------
# Référentiels (cache court : les référentiels bougent peu)
# ---------------------------------------------------------------------------
@st.cache_data(ttl=300, show_spinner=False)
def lister_fournisseurs() -> list[str]:
    s = get_settings()
    df = _run(f"SELECT DISTINCT name FROM {s.table_fournisseurs} ORDER BY name", fetch=True)
    return df["name"].tolist() if df is not None else []


@st.cache_data(ttl=300, show_spinner=False)
def fournisseurs_pour_article(num_article: str) -> list[str]:
    s = get_settings()
    df = _run(
        f"SELECT DISTINCT nom_fournisseur FROM {s.table_articles} "
        "WHERE item = %(item)s ORDER BY nom_fournisseur",
        params={"item": num_article},
        fetch=True,
    )
    return df["nom_fournisseur"].tolist() if df is not None else []


# ---------------------------------------------------------------------------
# Création d'un BL
# ---------------------------------------------------------------------------
def numero_bl_unique(numero_souhaite: str) -> str:
    """Unicité du numéro de BL : si le numéro existe déjà (y compris supprimé),
    suffixe incrémental -1, -2, ... sans message utilisateur (exigence CDC)."""
    s = get_settings()
    df = _run(
        f"SELECT numero_bl FROM {s.table_suivi} "
        "WHERE numero_bl = %(base)s OR numero_bl LIKE %(motif)s",
        params={"base": numero_souhaite, "motif": f"{numero_souhaite}-%"},
        fetch=True,
    )
    existants = set(df["numero_bl"].tolist()) if df is not None else set()
    if numero_souhaite not in existants:
        return numero_souhaite
    n = 1
    while f"{numero_souhaite}-{n}" in existants:
        n += 1
    return f"{numero_souhaite}-{n}"


def bl_existe(id_bl: str) -> bool:
    s = get_settings()
    df = _run(
        f"SELECT 1 FROM {s.table_suivi} WHERE id_bl = %(id)s LIMIT 1",
        params={"id": id_bl},
        fetch=True,
    )
    return df is not None and not df.empty


def inserer_bl(
    id_bl: str,
    numero_bl: str,
    date_reception: datetime.date,
    num_article: str,
    nom_fournisseur: str,
    statut_bl: str,
    comment_bl: str,
    operation_archivage: bool,
    utilisateur: str,
) -> None:
    s = get_settings()
    _run(
        f"""
        INSERT INTO {s.table_suivi}
          (id_bl, numero_bl, date_reception, num_article, nom_fournisseur,
           statut_bl, comment_bl, saisie_par, saisie_le, operation_type, est_supprime)
        VALUES
          (%(id)s, %(num)s, %(dr)s, %(art)s, %(frs)s,
           %(st)s, %(com)s, %(par)s, current_timestamp(), %(op)s, false)
        """,
        params={
            "id": id_bl,
            "num": numero_bl,
            "dr": date_reception,
            "art": num_article,
            "frs": nom_fournisseur,
            "st": statut_bl,
            "com": comment_bl,
            "par": utilisateur,
            "op": operation_archivage,
        },
    )


def enregistrer_page(id_bl: str, index_page: int, image_bytes: bytes) -> None:
    """Pousse une page sur le Volume (API Files) puis référence son chemin en table.
    Nomenclature CDC : {id_bl}_{index_page}_{id_photo}.jpg"""
    import io

    s = get_settings()
    id_photo = str(uuid.uuid4())
    chemin = f"{s.volume_path}/{id_bl}_{index_page}_{id_photo}.jpg"
    get_workspace_client().files.upload(chemin, io.BytesIO(image_bytes), overwrite=True)
    _run(
        f"INSERT INTO {s.table_pieces} (id_photo, id_bl, chemin_stockage, index_page) "
        "VALUES (%(idp)s, %(idb)s, %(chemin)s, %(idx)s)",
        params={"idp": id_photo, "idb": id_bl, "chemin": chemin, "idx": index_page},
    )


def pages_enregistrees(id_bl: str) -> set[int]:
    """Index des pages déjà en base pour ce BL — permet une reprise idempotente
    si l'enregistrement a échoué au milieu des uploads."""
    s = get_settings()
    df = _run(
        f"SELECT index_page FROM {s.table_pieces} WHERE id_bl = %(id)s",
        params={"id": id_bl},
        fetch=True,
    )
    return set(df["index_page"].tolist()) if df is not None else set()


# ---------------------------------------------------------------------------
# Recherche / lecture (app Administration)
# ---------------------------------------------------------------------------
def rechercher_bl(
    fournisseur: str = "",
    numero: str = "",
    article: str = "",
    date_min: Optional[datetime.date] = None,
    date_max: Optional[datetime.date] = None,
    statut: Optional[str] = None,
    inclure_supprimes: bool = False,
    page: int = 1,
    page_size: int = 25,
) -> tuple[pd.DataFrame, int]:
    """Recherche multicritère insensible à la casse, paginée. Retourne (page, total)."""
    s = get_settings()
    conditions = ["1=1"]
    params: dict = {}

    if not inclure_supprimes:
        conditions.append("(est_supprime IS NULL OR est_supprime = false)")
    if fournisseur:
        conditions.append("lower(nom_fournisseur) LIKE %(frs)s")
        params["frs"] = f"%{fournisseur.lower()}%"
    if numero:
        conditions.append("lower(numero_bl) LIKE %(num)s")
        params["num"] = f"%{numero.lower()}%"
    if article:
        conditions.append("lower(num_article) LIKE %(art)s")
        params["art"] = f"%{article.lower()}%"
    if date_min:
        conditions.append("date_reception >= %(dmin)s")
        params["dmin"] = date_min
    if date_max:
        conditions.append("date_reception <= %(dmax)s")
        params["dmax"] = date_max
    if statut in (STATUT_OK, STATUT_EDI_NOK):
        conditions.append("statut_bl = %(st)s")
        params["st"] = statut

    where = " AND ".join(conditions)

    df_total = _run(
        f"SELECT COUNT(*) AS n FROM {s.table_suivi} WHERE {where}", params=params, fetch=True
    )
    total = int(df_total["n"].iloc[0]) if df_total is not None else 0

    params_page = dict(params)
    params_page["lim"] = page_size
    params_page["off"] = max(page - 1, 0) * page_size
    df = _run(
        f"""
        SELECT id_bl, numero_bl, date_reception, num_article, nom_fournisseur,
               statut_bl, comment_bl, saisie_par, saisie_le, modifie_par, modifie_le,
               operation_type, est_supprime
        FROM {s.table_suivi}
        WHERE {where}
        ORDER BY saisie_le DESC
        LIMIT %(lim)s OFFSET %(off)s
        """,
        params=params_page,
        fetch=True,
    )
    return (df if df is not None else pd.DataFrame()), total


def photos_pour_bls(ids_bl: list[str]) -> dict[str, list[str]]:
    """Chemins des photos pour tous les BL affichés, EN UNE SEULE requête
    (évite le N+1), triés par index_page."""
    if not ids_bl:
        return {}
    s = get_settings()
    params = {f"id_{i}": v for i, v in enumerate(ids_bl)}
    placeholders = ", ".join(f"%({k})s" for k in params)
    df = _run(
        f"SELECT id_bl, chemin_stockage, index_page FROM {s.table_pieces} "
        f"WHERE id_bl IN ({placeholders}) ORDER BY index_page",
        params=params,
        fetch=True,
    )
    if df is None or df.empty:
        return {}
    return df.groupby("id_bl")["chemin_stockage"].apply(list).to_dict()


@st.cache_data(ttl=3600, show_spinner=False, max_entries=200)
def telecharger_photo(chemin: str) -> bytes:
    """Octets d'une photo du Volume, en cache (une photo ne change jamais)."""
    return get_workspace_client().files.download(chemin).contents.read()


# ---------------------------------------------------------------------------
# Mise à jour / suppression logique (app Administration)
# ---------------------------------------------------------------------------
CHAMPS_MODIFIABLES = {"numero_bl", "date_reception", "num_article", "nom_fournisseur", "statut_bl", "comment_bl"}


def mettre_a_jour_bl(id_bl: str, champs: dict, utilisateur: str) -> None:
    """UPDATE des seuls champs autorisés (liste blanche), avec traçabilité."""
    a_modifier = {k: v for k, v in champs.items() if k in CHAMPS_MODIFIABLES}
    if not a_modifier:
        return
    s = get_settings()
    set_clause = ", ".join(f"{k} = %({k})s" for k in a_modifier)
    params = dict(a_modifier)
    params["id"] = id_bl
    params["par"] = utilisateur
    _run(
        f"UPDATE {s.table_suivi} SET {set_clause}, "
        "modifie_par = %(par)s, modifie_le = current_timestamp() "
        "WHERE id_bl = %(id)s",
        params=params,
    )


def supprimer_bl(id_bl: str, utilisateur: str) -> None:
    """Suppression LOGIQUE (CDC) : le BL et ses images restent en base/volume."""
    s = get_settings()
    _run(
        f"UPDATE {s.table_suivi} SET est_supprime = true, "
        "supprime_par = %(par)s, supprime_le = current_timestamp() "
        "WHERE id_bl = %(id)s",
        params={"id": id_bl, "par": utilisateur},
    )


def restaurer_bl(id_bl: str, utilisateur: str) -> None:
    s = get_settings()
    _run(
        f"UPDATE {s.table_suivi} SET est_supprime = false, "
        "modifie_par = %(par)s, modifie_le = current_timestamp() "
        "WHERE id_bl = %(id)s",
        params={"id": id_bl, "par": utilisateur},
    )
