"""Application « Création de BL dématérialisés ».

Public : opérateurs logistiques en mobilité (réceptionnistes), sur smartphone
ou tablette. Formulaire de type wizard en 4 étapes (cahier des charges) :
  1. Informations de base  2. Informations de réception
  3. Capture d'images      4. Récapitulatif et enregistrement
"""

import re
import uuid
import datetime

import streamlit as st

from bl_core import images, repository, ui
from bl_core.identity import get_current_user

# set_page_config doit être la 1re commande Streamlit.
st.set_page_config(page_title="Création BL", page_icon="📥", layout="centered")

ui.configurer_logs()

NB_ETAPES = 4
NOMS_ETAPES = {1: "Informations de base", 2: "Informations de réception", 3: "Capture des pages", 4: "Récapitulatif"}

# --- État du wizard ---
st.session_state.setdefault("etape", 1)
st.session_state.setdefault("donnees", {})          # saisies utilisateur des étapes 1-2
st.session_state.setdefault("pages", [])            # octets JPEG des pages traitées
st.session_state.setdefault("photo_en_cours", None)  # octets bruts de la photo capturée (étape 3)
st.session_state.setdefault("frs_connus", None)     # résultat du bouton "Vérifier"
st.session_state.setdefault("uploader_key", 0)      # rotation du widget de capture
st.session_state.setdefault("enregistrement_lance", False)
st.session_state.setdefault("bl_insere", False)


def aller_a(etape) -> None:
    st.session_state.etape = etape
    st.rerun()


def reinitialiser_wizard() -> None:
    for cle in ("etape", "donnees", "pages", "photo_en_cours", "frs_connus", "uploader_key",
                "enregistrement_lance", "bl_insere", "id_bl", "numero_final"):
        st.session_state.pop(cle, None)


st.title("📥 Création de BL")
ui.show_flash()

etape = st.session_state.etape
if etape in NOMS_ETAPES:
    st.progress(etape / NB_ETAPES, text=f"Étape {etape}/{NB_ETAPES} — {NOMS_ETAPES[etape]}")

donnees = st.session_state.donnees

# =====================================================================
# ÉTAPE 1 — Informations de base
# =====================================================================
if etape == 1:
    operation = st.radio(
        "Nature de l'opération *",
        ["Nouvelle réception", "Archivage d'un ancien BL"],
        index=1 if donnees.get("archivage") else 0,
        horizontal=True,
    )
    numero = st.text_input("Numéro du BL *", value=donnees.get("numero", ""), max_chars=60)
    date_reception = st.date_input("Date de réception *", value=donnees.get("date_reception", datetime.date.today()))

    if st.button("Suivant ➡️", type="primary", use_container_width=True):
        if not numero.strip():
            st.error("Le numéro de BL est obligatoire.")
        else:
            archivage = operation.startswith("Archivage")
            donnees.update({"numero": numero.strip(), "date_reception": date_reception, "archivage": archivage})
            if archivage:
                donnees["statut"] = repository.STATUT_OK  # imposé par le CDC
            aller_a(2)

# =====================================================================
# ÉTAPE 2 — Informations de réception
# =====================================================================
elif etape == 2:
    st.caption("Numéro d'article réceptionné * (préfixe P-00 déjà rempli)")
    col_prefixe, col_chiffres, col_verif = st.columns([2, 4, 3])
    with col_prefixe:
        st.text_input("Préfixe", value="P-00", disabled=True, label_visibility="collapsed")
    with col_chiffres:
        chiffres = st.text_input(
            "6 chiffres", value=donnees.get("art6", ""), max_chars=6,
            placeholder="6 chiffres", label_visibility="collapsed",
        )
    with col_verif:
        verifier = st.button("🔎 Vérifier", use_container_width=True)

    if verifier:
        if re.fullmatch(r"\d{6}", chiffres or ""):
            try:
                st.session_state.frs_connus = repository.fournisseurs_pour_article(f"P-00{chiffres}")
            except Exception as e:
                st.error(f"Vérification impossible : {e}")
        else:
            st.error("Saisissez exactement 6 chiffres après P-00.")

    # Champ d'information grisé : fournisseurs connus pour l'article vérifié.
    frs_connus = st.session_state.frs_connus
    if frs_connus is None:
        info_article = ""
    elif frs_connus:
        info_article = ", ".join(frs_connus)
    else:
        info_article = "article inconnu"
    st.text_input("Fournisseurs connus pour cet article", value=info_article, disabled=True)

    try:
        tous_fournisseurs = repository.lister_fournisseurs()
    except Exception as e:
        tous_fournisseurs = []
        st.error(f"Impossible de charger les fournisseurs : {e}")

    # Sur smartphone, la liste déroulante n'ouvre pas le clavier (Streamlit
    # désactive la saisie tactile dans st.selectbox) : le filtrage se fait donc
    # dans un champ texte dédié, qui restreint les options de la liste.
    filtre_frs = st.text_input(
        "Filtrer les fournisseurs", value="",
        placeholder="Tapez quelques lettres pour filtrer la liste…",
    )
    if filtre_frs.strip():
        fournisseurs_affiches = [f for f in tous_fournisseurs
                                 if filtre_frs.strip().lower() in f.lower()]
        if not fournisseurs_affiches:
            st.caption("Aucun fournisseur ne correspond à ce filtre.")
    else:
        fournisseurs_affiches = tous_fournisseurs

    index_frs = None
    if donnees.get("fournisseur") in fournisseurs_affiches:
        index_frs = fournisseurs_affiches.index(donnees["fournisseur"])
    elif frs_connus and frs_connus[0] in fournisseurs_affiches:
        index_frs = fournisseurs_affiches.index(frs_connus[0])
    elif len(fournisseurs_affiches) == 1:
        index_frs = 0                        # un seul résultat filtré : présélection
    fournisseur = st.selectbox(
        "Fournisseur *", options=fournisseurs_affiches,
        index=index_frs, placeholder="Choisir un fournisseur…",
    )

    if donnees.get("archivage"):
        st.radio("État de réception *", ["OK"], index=0, disabled=True, horizontal=True,
                 help="Archivage : l'état est imposé à OK.")
        statut = repository.STATUT_OK
    else:
        choix = st.radio(
            "État de réception *", ["OK", "EDI NOK"],
            index=1 if donnees.get("statut") == repository.STATUT_EDI_NOK else 0, horizontal=True,
        )
        statut = repository.STATUT_OK if choix == "OK" else repository.STATUT_EDI_NOK

    commentaire = st.text_area("Commentaire (facultatif)", value=donnees.get("commentaire", ""), max_chars=1000)

    col_prec, col_suiv = st.columns(2)
    if col_prec.button("⬅️ Précédent", use_container_width=True):
        donnees.update({"art6": chiffres, "commentaire": commentaire})
        aller_a(1)
    if col_suiv.button("Suivant ➡️", type="primary", use_container_width=True):
        if not re.fullmatch(r"\d{6}", chiffres or ""):
            st.error("Le numéro d'article doit comporter exactement 6 chiffres après P-00.")
        elif not fournisseur:
            st.error("Le fournisseur est obligatoire.")
        else:
            donnees.update({
                "art6": chiffres, "num_article": f"P-00{chiffres}",
                "fournisseur": fournisseur, "statut": statut, "commentaire": commentaire.strip(),
            })
            aller_a(3)

# =====================================================================
# ÉTAPE 3 — Capture d'images en flux continu (multipage)
# =====================================================================
elif etape == 3:
    st.caption(
        "Prenez chaque page en photo. Sur smartphone, le bouton ci-dessous "
        "propose directement l'appareil photo natif (qualité HD)."
    )
    # st.file_uploader ouvre l'appareil photo natif sur mobile (CDC) : pleine
    # résolution du capteur, contrairement à st.camera_input (webcam basse déf.).
    # HEIC/HEIF : format par défaut des iPhone et de nombreux Android récents.
    photo = st.file_uploader(
        "Photographier / choisir une page", type=["jpg", "jpeg", "png", "heic", "heif"],
        key=f"upl_{st.session_state.uploader_key}",
    )

    # Sur mobile, l'onglet passe en arrière-plan pendant la prise de photo et la
    # WebSocket se reconnecte au retour ; sur ces reruns le widget peut rendre
    # None alors que la photo avait bien été transmise. On copie donc les octets
    # en session_state dès leur arrivée : la suite de l'étape n'en dépend plus.
    if photo is not None:
        octets = photo.getvalue()
        if octets:
            st.session_state.photo_en_cours = octets
        elif st.session_state.photo_en_cours is None:
            st.warning("La photo n'a pas été transmise (connexion interrompue ?). "
                       "Reprenez la photo.")
    photo_brute = st.session_state.photo_en_cours

    def abandonner_photo() -> None:
        st.session_state.photo_en_cours = None
        st.session_state.uploader_key += 1  # réarme le widget de capture

    if photo_brute is not None:
        mode = st.radio("Rendu du scan", images.MODES_SCAN, index=2, horizontal=True,
                        help="La limite de taille et la compression s'appliquent "
                             "dans tous les modes.")
        cadrage_auto = st.toggle(
            "Cadrage automatique (détection du contour et redressement)", value=True,
            help="Désactivez si le cadrage automatique donne un résultat inattendu : "
                 "la photo est alors conservée telle quelle (le rendu, la taille et "
                 "la compression restent appliqués).",
        )
        try:
            with st.spinner("Traitement de la page…"):
                page_traitee, redressee = images.scanner_document(photo_brute, mode, cadrage_auto)
            st.image(page_traitee, caption=f"Aperçu — {mode}", use_column_width=True)
            if cadrage_auto and not redressee:
                st.caption("ℹ️ Contour du document non détecté : la photo entière "
                           "est conservée, sans redressement.")
            with st.expander("Voir la photo originale"):
                try:
                    st.image(photo_brute, use_column_width=True)
                except Exception:
                    st.caption("Aperçu original indisponible pour ce format.")

            col_ajout, col_reprise = st.columns(2)
            if col_ajout.button("➕ Empiler cette page", type="primary", use_container_width=True):
                st.session_state.pages.append(page_traitee)
                abandonner_photo()  # pas de double ajout au rerun suivant
                ui.set_flash("toast", f"Page {len(st.session_state.pages)} ajoutée")
                st.rerun()
            if col_reprise.button("🔄 Reprendre la photo", use_container_width=True):
                abandonner_photo()
                st.rerun()
        except Exception as e:
            st.error(f"Traitement impossible : {e}")
            if st.button("🔄 Reprendre la photo", use_container_width=True):
                abandonner_photo()
                st.rerun()

    if st.session_state.pages:
        st.write(f"📂 **{len(st.session_state.pages)} page(s) en attente :**")
        ui.afficher_miniatures(st.session_state.pages)
        if st.button("🗑️ Vider la liste d'attente", use_container_width=True):
            st.session_state.pages = []
            st.rerun()

    col_prec, col_suiv = st.columns(2)
    if col_prec.button("⬅️ Précédent", use_container_width=True):
        aller_a(2)
    if col_suiv.button("Suivant ➡️", type="primary", use_container_width=True):
        if not st.session_state.pages:
            st.error("Ajoutez au moins une page avant de continuer.")
        else:
            aller_a(4)

# =====================================================================
# ÉTAPE 4 — Récapitulatif et enregistrement
# =====================================================================
elif etape == 4:
    st.subheader("Récapitulatif")
    st.markdown(
        f"""
| | |
|---|---|
| **Opération** | {"Archivage" if donnees.get("archivage") else "Nouvelle réception"} |
| **Numéro de BL** | {donnees.get("numero", "")} |
| **Date de réception** | {donnees.get("date_reception", "")} |
| **Article** | {donnees.get("num_article", "")} |
| **Fournisseur** | {donnees.get("fournisseur", "")} |
| **État de réception** | {ui.libelle_statut(donnees.get("statut", repository.STATUT_OK))} |
| **Commentaire** | {donnees.get("commentaire") or "—"} |
| **Pages** | {len(st.session_state.pages)} |
"""
    )

    if st.session_state.enregistrement_lance:
        # L'enregistrement s'exécute sur CE rerun : le clic a seulement posé un
        # drapeau, ce qui neutralise les double-clics (idempotence CDC).
        with st.spinner("Enregistrement dans le Lakehouse…"):
            try:
                id_bl = st.session_state.setdefault("id_bl", str(uuid.uuid4()))
                utilisateur = get_current_user()

                if not st.session_state.bl_insere:
                    numero_final = repository.numero_bl_unique(donnees["numero"])
                    repository.inserer_bl(
                        id_bl=id_bl,
                        numero_bl=numero_final,
                        date_reception=donnees["date_reception"],
                        num_article=donnees["num_article"],
                        nom_fournisseur=donnees["fournisseur"],
                        statut_bl=donnees["statut"],
                        comment_bl=donnees["commentaire"],
                        operation_archivage=bool(donnees.get("archivage")),
                        utilisateur=utilisateur,
                    )
                    st.session_state.numero_final = numero_final
                    st.session_state.bl_insere = True

                # Reprise idempotente : en cas de nouvel essai après une erreur,
                # seules les pages manquantes sont uploadées (pas de doublons).
                deja = repository.pages_enregistrees(id_bl)
                for idx, page in enumerate(st.session_state.pages):
                    if idx not in deja:
                        repository.enregistrer_page(id_bl, idx, page)

                st.session_state.enregistrement_lance = False
                aller_a("succes")
            except Exception as e:
                st.session_state.enregistrement_lance = False
                st.error(f"Échec de l'enregistrement : {e}")
                st.info("Vos saisies sont conservées : corrigez si besoin via « Précédent », puis revalidez.")

    col_prec, col_val = st.columns(2)
    if col_prec.button("⬅️ Précédent", use_container_width=True, disabled=st.session_state.enregistrement_lance):
        aller_a(3)
    if col_val.button("💾 Valider", type="primary", use_container_width=True,
                      disabled=st.session_state.enregistrement_lance):
        st.session_state.enregistrement_lance = True
        st.rerun()

# =====================================================================
# ÉCRAN DE SUCCÈS
# =====================================================================
elif etape == "succes":
    st.success(f"BL n° {st.session_state.get('numero_final', '')} enregistré avec succès ✅")
    if st.button("🆕 Créer un nouveau BL", type="primary", use_container_width=True):
        reinitialiser_wizard()
        st.rerun()
