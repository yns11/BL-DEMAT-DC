"""Application « Création de BL dématérialisés ».

Public : opérateurs logistiques en mobilité (réceptionnistes), sur smartphone
ou tablette. Formulaire de type wizard en 3 étapes :
  1. Informations du BL (numéro, fournisseur via DESADV, quai, état)
  2. Numérisation des pages
  3. Récapitulatif et enregistrement
"""

import uuid
import datetime

import streamlit as st

from bl_core import images, repository, ui
from bl_core.identity import get_current_user

# set_page_config doit être la 1re commande Streamlit.
st.set_page_config(page_title="Création BL", page_icon="📥", layout="centered")

ui.configurer_logs()
ui.injecter_style()

NB_ETAPES = 3
NOMS_ETAPES = {1: "Informations du BL", 2: "Numérisation des pages", 3: "Récapitulatif"}

# --- État du wizard ---
st.session_state.setdefault("etape", 1)
st.session_state.setdefault("donnees", {})          # saisies utilisateur de l'étape 1
st.session_state.setdefault("pages", [])            # octets JPEG des pages traitées
st.session_state.setdefault("photo_en_cours", None)  # octets bruts de la photo capturée (étape 2)
st.session_state.setdefault("uploader_key", 0)      # rotation du widget de capture
st.session_state.setdefault("enregistrement_lance", False)
st.session_state.setdefault("bl_insere", False)


def aller_a(etape) -> None:
    st.session_state.etape = etape
    st.rerun()


def reinitialiser_wizard() -> None:
    for cle in ("etape", "donnees", "pages", "photo_en_cours", "uploader_key",
                "enregistrement_lance", "bl_insere", "id_bl", "numero_final"):
        st.session_state.pop(cle, None)


st.title("📥 Création de BL")
ui.show_flash()

etape = st.session_state.etape
if etape in NOMS_ETAPES:
    st.progress(etape / NB_ETAPES, text=f"Étape {etape}/{NB_ETAPES} — {NOMS_ETAPES[etape]}")

donnees = st.session_state.donnees

# =====================================================================
# ÉTAPE 1 — Informations du BL
# =====================================================================
if etape == 1:
    libelles_op = list(repository.LIBELLES_OPERATION.values())
    type_actuel = donnees.get("type_operation", repository.TYPE_RECEPTION)
    choix_op = st.radio(
        "Nature de l'opération *", libelles_op,
        index=libelles_op.index(repository.LIBELLES_OPERATION[type_actuel]),
        horizontal=True,
    )
    type_op = next(t for t, l in repository.LIBELLES_OPERATION.items() if l == choix_op)
    reception = type_op == repository.TYPE_RECEPTION
    tiers = repository.libelle_tiers(type_op)  # « Client » pour une expédition

    numero = st.text_input("Numéro du BL *", value=donnees.get("numero", ""), max_chars=60)

    # Date et plage horaire : uniquement pour une nouvelle réception —
    # expédition et archivage ne demandent que le numéro de BL et le tiers.
    if reception:
        date_reception = st.date_input("Date de réception *",
                                       value=donnees.get("date_reception", datetime.date.today()))
        plage_defaut = (donnees["plage"] if donnees.get("plage") in repository.PLAGES_HORAIRES
                        else repository.plage_horaire_courante())
        plage = st.selectbox(
            "Plage horaire de réception *", options=repository.PLAGES_HORAIRES,
            index=repository.PLAGES_HORAIRES.index(plage_defaut),
        )
    else:
        date_reception = None
        plage = None
        st.caption(f"{choix_op} : seuls le numéro de BL et le {tiers.lower()} sont demandés.")

    # --- Fournisseur / client : automatique via l'avis d'expédition (DESADV)
    # quand le numéro de BL y figure — quel que soit le type d'opération ;
    # sélection manuelle (filtre + liste) sinon. ---
    frs_desadv = None
    if numero.strip():
        try:
            frs_desadv = repository.fournisseur_pour_bl(numero.strip())
        except Exception as e:
            st.warning(f"Consultation des avis d'expédition impossible : {e} — "
                       f"sélectionnez le {tiers.lower()} manuellement.")

    if frs_desadv:
        st.text_input(
            f"{tiers} (avis d'expédition) ✓", value=frs_desadv, disabled=True,
            help="Renseigné automatiquement : ce numéro de BL figure dans un avis "
                 "d'expédition (DESADV).",
        )
        fournisseur = frs_desadv
    else:
        if numero.strip():
            st.caption("Ce BL est absent des avis d'expédition (DESADV) : "
                       f"sélectionnez le {tiers.lower()} manuellement.")
        try:
            tous_fournisseurs = repository.lister_fournisseurs()
        except Exception as e:
            tous_fournisseurs = []
            st.error(f"Impossible de charger la liste : {e}")

        # Sur smartphone, la liste déroulante n'ouvre pas le clavier (Streamlit
        # désactive la saisie tactile dans st.selectbox) : le filtrage se fait
        # donc dans un champ texte dédié, qui restreint les options de la liste.
        filtre_frs = st.text_input(
            "Filtrer la liste", value="",
            placeholder="Tapez quelques lettres pour filtrer la liste…",
        )
        if filtre_frs.strip():
            fournisseurs_affiches = [f for f in tous_fournisseurs
                                     if filtre_frs.strip().lower() in f.lower()]
            if not fournisseurs_affiches:
                st.caption("Aucun résultat ne correspond à ce filtre.")
        else:
            fournisseurs_affiches = tous_fournisseurs

        index_frs = None
        if donnees.get("fournisseur") in fournisseurs_affiches:
            index_frs = fournisseurs_affiches.index(donnees["fournisseur"])
        elif len(fournisseurs_affiches) == 1:
            index_frs = 0                    # un seul résultat filtré : présélection
        fournisseur = st.selectbox(
            f"{tiers} *", options=fournisseurs_affiches,
            index=index_frs, placeholder="Choisir…",
        )

    # Quai, état et commentaire : uniquement pour une nouvelle réception.
    # Expédition/archivage : état imposé à OK, autres champs vides (NULL).
    if reception:
        index_quai = (repository.QUAIS_RECEPTION.index(donnees["quai"])
                      if donnees.get("quai") in repository.QUAIS_RECEPTION else None)
        quai = st.selectbox(
            "Quai de réception *", options=repository.QUAIS_RECEPTION,
            index=index_quai, placeholder="Choisir le quai…",
        )
        choix = st.radio(
            "État de réception *", ["OK", "EDI NOK"],
            index=1 if donnees.get("statut") == repository.STATUT_EDI_NOK else 0, horizontal=True,
        )
        statut = repository.STATUT_OK if choix == "OK" else repository.STATUT_EDI_NOK
        commentaire = st.text_area("Commentaire (facultatif)",
                                   value=donnees.get("commentaire", ""), max_chars=1000)
    else:
        quai = None
        statut = repository.STATUT_OK
        commentaire = ""

    if st.button("Suivant ➡️", type="primary", use_container_width=True):
        if not numero.strip():
            st.error("Le numéro de BL est obligatoire.")
        elif not fournisseur:
            st.error(f"Le {tiers.lower()} est obligatoire.")
        elif reception and not quai:
            st.error("Le quai de réception est obligatoire.")
        else:
            donnees.update({
                "numero": numero.strip(), "date_reception": date_reception,
                "plage": plage, "type_operation": type_op, "fournisseur": fournisseur,
                "fournisseur_desadv": bool(frs_desadv), "quai": quai,
                "statut": statut, "commentaire": commentaire.strip(),
            })
            aller_a(2)

# =====================================================================
# ÉTAPE 2 — Numérisation des pages en flux continu (multipage)
# =====================================================================
elif etape == 2:
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
        aller_a(1)
    if col_suiv.button("Suivant ➡️", type="primary", use_container_width=True):
        if not st.session_state.pages:
            st.error("Ajoutez au moins une page avant de continuer.")
        else:
            aller_a(3)

# =====================================================================
# ÉTAPE 3 — Récapitulatif et enregistrement
# =====================================================================
elif etape == 3:
    st.subheader("Récapitulatif")
    type_op = donnees.get("type_operation", repository.TYPE_RECEPTION)
    reception = type_op == repository.TYPE_RECEPTION
    origine_frs = " (avis d'expédition)" if donnees.get("fournisseur_desadv") else ""

    # Lignes du récapitulatif : expédition et archivage n'affichent que le
    # numéro de BL et le tiers (les autres champs ne sont pas saisis).
    lignes = [
        ("Opération", repository.LIBELLES_OPERATION.get(type_op, type_op)),
        ("Numéro de BL", donnees.get("numero", "")),
    ]
    if reception:
        lignes += [
            ("Date de réception", donnees.get("date_reception", "")),
            ("Plage horaire", donnees.get("plage") or "—"),
        ]
    lignes.append((repository.libelle_tiers(type_op),
                   f'{donnees.get("fournisseur", "")}{origine_frs}'))
    if reception:
        lignes += [
            ("Quai de réception", donnees.get("quai", "")),
            ("État de réception", ui.libelle_statut(donnees.get("statut", repository.STATUT_OK))),
            ("Commentaire", donnees.get("commentaire") or "—"),
        ]
    lignes.append(("Pages", len(st.session_state.pages)))

    st.markdown("| | |\n|---|---|\n"
                + "\n".join(f"| **{label}** | {valeur} |" for label, valeur in lignes))

    if st.session_state.enregistrement_lance:
        # L'enregistrement s'exécute sur CE rerun : le clic a seulement posé un
        # drapeau, ce qui neutralise les double-clics (idempotence CDC).
        with st.spinner("Enregistrement dans Lakebase…"):
            try:
                id_bl = st.session_state.setdefault("id_bl", str(uuid.uuid4()))
                utilisateur = get_current_user()

                if not st.session_state.bl_insere:
                    numero_final = repository.numero_bl_unique(donnees["numero"])
                    repository.inserer_bl(
                        id_bl=id_bl,
                        numero_bl=numero_final,
                        nom_fournisseur=donnees["fournisseur"],
                        statut_bl=donnees["statut"],
                        type_operation=donnees.get("type_operation", repository.TYPE_RECEPTION),
                        utilisateur=utilisateur,
                        date_reception=donnees.get("date_reception"),
                        quai_reception=donnees.get("quai"),
                        comment_bl=donnees["commentaire"],
                        plage_horaire=donnees.get("plage"),
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
        aller_a(2)
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
