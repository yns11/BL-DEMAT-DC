"""Couche d'accès aux données (repository) — V2 Lakebase Postgres.

Les métadonnées ET les photos sont stockées dans une base Lakebase (Postgres
managé Databricks) : aucune dépendance à Unity Catalog (ni warehouse SQL, ni
tables Delta, ni volume). Les photos sont des colonnes BYTEA (<= 2 Mo par page
après compression, voir bl_core/images.py).

- Authentification : jeton OAuth du service principal de l'app, généré via le
  SDK (validité 1 h) et renouvelé automatiquement avant expiration.
- Ressource d'app « postgres » requise : elle injecte PGHOST, PGPORT,
  PGDATABASE, PGUSER, PGSSLMODE et LAKEBASE_ENDPOINT au démarrage.
- Toutes les requêtes sont paramétrées (aucune concaténation de valeurs) :
  protection systématique contre l'injection SQL.
- L'interface publique (noms et signatures) est identique à la V1 : les
  applications Streamlit sont inchangées.
"""

import datetime
import logging
import os
import time
import uuid
from typing import Optional
from zoneinfo import ZoneInfo

import pandas as pd
import psycopg
import streamlit as st

from .config import get_settings

logger = logging.getLogger("bl.repository")

STATUT_OK = "1"
STATUT_EDI_NOK = "0"

# Types d'opération. Le tiers saisi (colonne nom_fournisseur) est un
# fournisseur pour une réception/un archivage, un CLIENT pour une expédition —
# même colonne en base, seul le libellé à l'écran change.
TYPE_RECEPTION = "RECEPTION"
TYPE_EXPEDITION = "EXPEDITION"
TYPE_ARCHIVAGE = "ARCHIVAGE"
LIBELLES_OPERATION = {
    TYPE_RECEPTION: "Nouvelle réception",
    TYPE_EXPEDITION: "Expédition",
    TYPE_ARCHIVAGE: "Archivage d'un ancien BL",
}


def libelle_tiers(type_operation: str) -> str:
    """« Client » pour une expédition, « Fournisseur » sinon."""
    return "Client" if type_operation == TYPE_EXPEDITION else "Fournisseur"


# Quais de réception du site (valeur obligatoire à la création d'un BL).
QUAIS_RECEPTION = ["B15", "B06EST", "B06NORD", "B02NORD", "AUTRE"]

# Plages horaires de réception : 2 h entre 06h et 20h, plus les plages de
# nuit 00h-06h et 20h-00h. Obligatoire pour une nouvelle réception.
PLAGES_HORAIRES = ["00h-06h"] + [f"{h:02d}h-{h + 2:02d}h" for h in range(6, 20, 2)] + ["20h-00h"]


def maintenant_local() -> datetime.datetime:
    """Heure locale du site (le conteneur d'app tourne en UTC : sans fuseau,
    le préremplissage de la plage horaire serait décalé)."""
    try:
        fuseau = ZoneInfo(os.environ.get("BL_FUSEAU", "Europe/Paris"))
    except Exception:
        fuseau = None
    return datetime.datetime.now(fuseau)


def plage_horaire_courante() -> str:
    """Plage horaire contenant l'heure locale courante (préremplissage)."""
    h = maintenant_local().hour
    if h < 6:
        return PLAGES_HORAIRES[0]
    if h >= 20:
        return PLAGES_HORAIRES[-1]
    debut = 6 + ((h - 6) // 2) * 2
    return f"{debut:02d}h-{debut + 2:02d}h"


# ---------------------------------------------------------------------------
# Connexion Lakebase (une par processus d'app, renouvelée avant l'expiration
# du jeton OAuth — validité 1 h)
# ---------------------------------------------------------------------------
_DUREE_MAX_CONNEXION_S = 45 * 60


@st.cache_resource(show_spinner=False)
def _etat_connexion() -> dict:
    """Conteneur mutable partagé par les reruns : connexion + horodatage."""
    return {"conn": None, "creee_a": 0.0}


def _jeton_acces() -> str:
    """Mot de passe Postgres = jeton OAuth Databricks du service principal.

    Voie principale : le jeton OAuth de l'app (DATABRICKS_CLIENT_ID/SECRET,
    injectés par la plateforme) — Lakebase l'accepte directement comme mot de
    passe, sans configuration supplémentaire. Si le workspace injecte aussi
    LAKEBASE_ENDPOINT, on utilise de préférence le jeton dédié généré pour cet
    endpoint (portée plus étroite)."""
    # Import local : le SDK n'est nécessaire que pour générer le jeton.
    from databricks.sdk import WorkspaceClient

    w = WorkspaceClient()
    endpoint = os.environ.get("LAKEBASE_ENDPOINT", "")
    if endpoint:
        try:
            return w.postgres.generate_database_credential(endpoint=endpoint).token
        except Exception as e:
            logger.warning("generate_database_credential en échec (%s) : repli sur le jeton OAuth.", e)
    return w.config.oauth_token().access_token


def _nouvelle_connexion():
    if not os.environ.get("PGHOST"):
        raise RuntimeError(
            "PGHOST absent : vérifiez que la ressource d'app « postgres » "
            "(base Lakebase) est bien attachée à l'application, puis redéployez-la."
        )
    return psycopg.connect(
        host=os.environ["PGHOST"],
        port=int(os.environ.get("PGPORT", "5432")),
        dbname=os.environ["PGDATABASE"],
        user=os.environ["PGUSER"],
        password=_jeton_acces(),
        sslmode="require",
    )


def _fermer_connexion() -> None:
    etat = _etat_connexion()
    if etat["conn"] is not None:
        try:
            etat["conn"].close()
        except Exception:
            pass
    etat["conn"] = None


def _get_connection():
    etat = _etat_connexion()
    conn = etat["conn"]
    if conn is None or conn.closed or time.monotonic() - etat["creee_a"] > _DUREE_MAX_CONNEXION_S:
        _fermer_connexion()
        etat["conn"] = _nouvelle_connexion()
        etat["creee_a"] = time.monotonic()
    return etat["conn"]


def _run(query: str, params: Optional[dict] = None, fetch: bool = False):
    """Exécute une requête paramétrée. Reconnecte et rejoue une fois en cas de
    coupure (réveil après scale-to-zero, jeton expiré, connexion fermée)."""
    for tentative in (1, 2):
        try:
            conn = _get_connection()
            with conn.cursor() as cursor:
                cursor.execute(query, params)
                resultat = None
                if fetch:
                    cols = [d[0] for d in cursor.description]
                    resultat = pd.DataFrame(cursor.fetchall(), columns=cols)
            conn.commit()
            return resultat
        except Exception as e:
            _fermer_connexion()  # la prochaine tentative repartira d'une connexion neuve
            if tentative == 1:
                logger.warning("Connexion Lakebase perdue, nouvelle tentative : %s", e)
                continue
            logger.error("Erreur SQL Lakebase : %s | requête : %s", e, query.strip().split("\n")[0])
            raise


# ---------------------------------------------------------------------------
# Référentiels (cache court : les référentiels bougent peu)
# ---------------------------------------------------------------------------
@st.cache_data(ttl=300, show_spinner=False)
def lister_fournisseurs() -> list[str]:
    s = get_settings()
    df = _run(f"SELECT DISTINCT name FROM {s.pg_schema}.base_frs ORDER BY name", fetch=True)
    return df["name"].tolist() if df is not None else []


@st.cache_data(ttl=300, show_spinner=False)
def fournisseur_pour_bl(numero_bl: str) -> Optional[str]:
    """Fournisseur annoncé par l'avis d'expédition (DESADV) pour ce numéro de
    BL — None si le BL n'y figure pas (l'utilisateur choisira manuellement)."""
    s = get_settings()
    df = _run(
        f"SELECT nom_fournisseur FROM {s.pg_schema}.base_desadv "
        "WHERE upper(numero_bl) = upper(%(num)s) LIMIT 1",
        params={"num": numero_bl},
        fetch=True,
    )
    if df is None or df.empty:
        return None
    return df["nom_fournisseur"].iloc[0]


# ---------------------------------------------------------------------------
# Création d'un BL
# ---------------------------------------------------------------------------
def numero_bl_unique(numero_souhaite: str) -> str:
    """Unicité du numéro de BL : si le numéro existe déjà (y compris supprimé),
    suffixe incrémental -1, -2, ... sans message utilisateur (exigence CDC)."""
    s = get_settings()
    df = _run(
        f"SELECT numero_bl FROM {s.pg_schema}.suivi_bl "
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
        f"SELECT 1 FROM {s.pg_schema}.suivi_bl WHERE id_bl = %(id)s LIMIT 1",
        params={"id": id_bl},
        fetch=True,
    )
    return df is not None and not df.empty


def inserer_bl(
    id_bl: str,
    numero_bl: str,
    nom_fournisseur: str,
    statut_bl: str,
    type_operation: str,
    utilisateur: str,
    date_reception: Optional[datetime.date] = None,
    quai_reception: Optional[str] = None,
    comment_bl: str = "",
    plage_horaire: Optional[str] = None,
) -> None:
    """Date, plage, quai et commentaire ne concernent qu'une nouvelle
    réception : NULL pour une expédition ou un archivage."""
    s = get_settings()
    _run(
        f"""
        INSERT INTO {s.pg_schema}.suivi_bl
          (id_bl, numero_bl, date_reception, plage_horaire, nom_fournisseur, quai_reception,
           statut_bl, comment_bl, saisie_par, saisie_le, type_operation, est_supprime)
        VALUES
          (%(id)s, %(num)s, %(dr)s, %(plage)s, %(frs)s, %(quai)s,
           %(st)s, %(com)s, %(par)s, now(), %(op)s, false)
        """,
        params={
            "id": id_bl,
            "num": numero_bl,
            "dr": date_reception,
            "plage": plage_horaire,
            "frs": nom_fournisseur,
            "quai": quai_reception,
            "st": statut_bl,
            "com": comment_bl,
            "par": utilisateur,
            "op": type_operation,
        },
    )


def enregistrer_page(id_bl: str, index_page: int, image_bytes: bytes) -> None:
    """Insère une page scannée directement en base (colonne BYTEA) — plus de
    volume Unity Catalog en V2."""
    s = get_settings()
    id_photo = str(uuid.uuid4())
    _run(
        f"INSERT INTO {s.pg_schema}.pieces_jointes_bl (id_photo, id_bl, contenu, index_page) "
        "VALUES (%(idp)s, %(idb)s, %(contenu)s, %(idx)s)",
        params={"idp": id_photo, "idb": id_bl, "contenu": image_bytes, "idx": index_page},
    )


def pages_enregistrees(id_bl: str) -> set[int]:
    """Index des pages déjà en base pour ce BL — permet une reprise idempotente
    si l'enregistrement a échoué au milieu des insertions."""
    s = get_settings()
    df = _run(
        f"SELECT index_page FROM {s.pg_schema}.pieces_jointes_bl WHERE id_bl = %(id)s",
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
    quai: str = "",
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
    if quai:
        conditions.append("quai_reception = %(quai)s")
        params["quai"] = quai
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
        f"SELECT COUNT(*) AS n FROM {s.pg_schema}.suivi_bl WHERE {where}", params=params, fetch=True
    )
    total = int(df_total["n"].iloc[0]) if df_total is not None else 0

    params_page = dict(params)
    params_page["lim"] = page_size
    params_page["off"] = max(page - 1, 0) * page_size
    df = _run(
        f"""
        SELECT id_bl, numero_bl, date_reception, plage_horaire, nom_fournisseur, quai_reception,
               statut_bl, comment_bl, saisie_par, saisie_le, modifie_par, modifie_le,
               type_operation, est_supprime
        FROM {s.pg_schema}.suivi_bl
        WHERE {where}
        ORDER BY saisie_le DESC
        LIMIT %(lim)s OFFSET %(off)s
        """,
        params=params_page,
        fetch=True,
    )
    return (df if df is not None else pd.DataFrame()), total


def photos_pour_bls(ids_bl: list[str]) -> dict[str, list[str]]:
    """Identifiants des photos pour tous les BL affichés, EN UNE SEULE requête
    (évite le N+1), triés par index_page. Le contenu binaire n'est téléchargé
    qu'à l'affichage (telecharger_photo, en cache)."""
    if not ids_bl:
        return {}
    s = get_settings()
    params = {f"id_{i}": v for i, v in enumerate(ids_bl)}
    placeholders = ", ".join(f"%({k})s" for k in params)
    df = _run(
        f"SELECT id_bl, id_photo, index_page FROM {s.pg_schema}.pieces_jointes_bl "
        f"WHERE id_bl IN ({placeholders}) ORDER BY index_page",
        params=params,
        fetch=True,
    )
    if df is None or df.empty:
        return {}
    return df.groupby("id_bl")["id_photo"].apply(list).to_dict()


@st.cache_data(ttl=3600, show_spinner=False, max_entries=200)
def telecharger_photo(id_photo: str) -> bytes:
    """Octets d'une photo stockée en base, en cache (une photo ne change jamais)."""
    s = get_settings()
    df = _run(
        f"SELECT contenu FROM {s.pg_schema}.pieces_jointes_bl WHERE id_photo = %(id)s",
        params={"id": id_photo},
        fetch=True,
    )
    if df is None or df.empty:
        raise ValueError(f"Photo introuvable : {id_photo}")
    return bytes(df["contenu"].iloc[0])


# ---------------------------------------------------------------------------
# Mise à jour / suppression logique (app Administration)
# ---------------------------------------------------------------------------
CHAMPS_MODIFIABLES = {"numero_bl", "date_reception", "plage_horaire", "nom_fournisseur",
                      "quai_reception", "statut_bl", "comment_bl"}


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
        f"UPDATE {s.pg_schema}.suivi_bl SET {set_clause}, "
        "modifie_par = %(par)s, modifie_le = now() "
        "WHERE id_bl = %(id)s",
        params=params,
    )


def supprimer_bl(id_bl: str, utilisateur: str) -> None:
    """Suppression LOGIQUE (CDC) : le BL et ses images restent en base."""
    s = get_settings()
    _run(
        f"UPDATE {s.pg_schema}.suivi_bl SET est_supprime = true, "
        "supprime_par = %(par)s, supprime_le = now() "
        "WHERE id_bl = %(id)s",
        params={"id": id_bl, "par": utilisateur},
    )


def restaurer_bl(id_bl: str, utilisateur: str) -> None:
    s = get_settings()
    _run(
        f"UPDATE {s.pg_schema}.suivi_bl SET est_supprime = false, "
        "modifie_par = %(par)s, modifie_le = now() "
        "WHERE id_bl = %(id)s",
        params={"id": id_bl, "par": utilisateur},
    )
