"""Application « Administration de BL dématérialisés ».

Public : approvisionneurs. Recherche multicritère paginée, consultation des
pages scannées, correction des données (UPDATE), suppression logique et
restauration — avec traçabilité complète (qui / quand).
"""

import datetime

import streamlit as st

from bl_core import notifications, repository, ui
from bl_core.identity import get_current_user

st.set_page_config(page_title="Administration BL", page_icon="🗂️", layout="wide")

ui.configurer_logs()
ui.injecter_style()

st.title("🗂️ Administration des BL")
ui.show_flash()

# =====================================================================
# FILTRES (recherche multicritère, insensible à la casse)
# =====================================================================
with st.container(border=True):
    col1, col2, col3 = st.columns(3)
    with col1:
        f_fournisseur = st.text_input("Fournisseur contient").strip()
        f_numero = st.text_input("Numéro de BL contient").strip()
    with col2:
        f_quai = st.selectbox("Quai de réception", ["Tous"] + repository.QUAIS_RECEPTION)
        # Par défaut : les EDI NOK (ce sont eux qui demandent une action).
        f_statut = st.selectbox("État de réception", ["Tous", "OK", "EDI NOK"], index=2)
    with col3:
        # Par défaut : les BL de la veille et d'aujourd'hui (toute plage horaire).
        aujourdhui = repository.maintenant_local().date()
        f_date_min = st.date_input("Reçu à partir du", value=aujourdhui - datetime.timedelta(days=1))
        f_date_max = st.date_input("Reçu jusqu'au", value=aujourdhui)
    col4, col5 = st.columns(3)[:2]
    with col4:
        f_inclure_supprimes = st.checkbox("Inclure les BL supprimés")
    with col5:
        page_size = st.selectbox("Résultats par page", [10, 25, 50, 100], index=1)

statut_filtre = {"OK": repository.STATUT_OK, "EDI NOK": repository.STATUT_EDI_NOK}.get(f_statut)

# La pagination est réinitialisée quand les filtres changent (sinon on peut se
# retrouver sur une page vide au-delà du nouveau total).
signature_filtres = (f_fournisseur, f_numero, f_quai, str(f_date_min), str(f_date_max),
                     f_statut, f_inclure_supprimes, page_size)
if st.session_state.get("signature_filtres") != signature_filtres:
    st.session_state.signature_filtres = signature_filtres
    st.session_state.page = 1
st.session_state.setdefault("page", 1)

# =====================================================================
# RECHERCHE + PAGINATION
# =====================================================================
try:
    df_bl, total = repository.rechercher_bl(
        fournisseur=f_fournisseur, numero=f_numero,
        quai="" if f_quai == "Tous" else f_quai,
        date_min=f_date_min, date_max=f_date_max, statut=statut_filtre,
        inclure_supprimes=f_inclure_supprimes,
        page=st.session_state.page, page_size=page_size,
    )
    photos_par_bl = repository.photos_pour_bls(df_bl["id_bl"].tolist() if not df_bl.empty else [])
except Exception as e:
    st.error(f"Erreur de lecture de la base : {e}")
    st.stop()

nb_pages = max((total + page_size - 1) // page_size, 1)
col_info, col_prec, col_page, col_suiv = st.columns([4, 1, 2, 1])
col_info.write(f"**{total}** BL trouvé(s)")
if col_prec.button("⬅️", disabled=st.session_state.page <= 1, use_container_width=True):
    st.session_state.page -= 1
    st.rerun()
col_page.markdown(f"<div style='text-align:center'>page {st.session_state.page} / {nb_pages}</div>",
                  unsafe_allow_html=True)
if col_suiv.button("➡️", disabled=st.session_state.page >= nb_pages, use_container_width=True):
    st.session_state.page += 1
    st.rerun()

if df_bl.empty:
    st.info("Aucun BL ne correspond à votre recherche.")
    st.stop()

# =====================================================================
# RÉSULTATS
# =====================================================================
try:
    tous_fournisseurs = repository.lister_fournisseurs()
except Exception:
    tous_fournisseurs = []

utilisateur = get_current_user()

for _, bl in df_bl.iterrows():
    id_bl = bl["id_bl"]
    chemins = photos_par_bl.get(id_bl, [])
    type_op_bl = bl.get("type_operation") or repository.TYPE_RECEPTION
    reception_bl = type_op_bl == repository.TYPE_RECEPTION
    tiers_bl = repository.libelle_tiers(type_op_bl)

    marqueur = " · 🗑️ SUPPRIMÉ" if bl.get("est_supprime") else ""
    marqueur_op = "" if reception_bl else f" · {repository.LIBELLES_OPERATION.get(type_op_bl, type_op_bl)}"
    quai_titre = f" — quai {bl['quai_reception']}" if bl.get("quai_reception") else ""
    titre = (f"📄 BL n° {bl['numero_bl']} — {bl['nom_fournisseur']}{quai_titre} — "
             f"{ui.libelle_statut(bl['statut_bl'])} ({len(chemins)} page(s)){marqueur_op}{marqueur}")

    with st.expander(titre):
        col_donnees, col_images = st.columns([1, 1])

        # ----- Fiche de correction (formulaire : un seul rerun à la soumission) -----
        with col_donnees:
            with st.form(key=f"form_{id_bl}"):
                nouveau_numero = st.text_input("Numéro de BL", value=bl["numero_bl"], max_chars=60)
                index_frs = (tous_fournisseurs.index(bl["nom_fournisseur"])
                             if bl["nom_fournisseur"] in tous_fournisseurs else None)
                nouveau_frs = st.selectbox(tiers_bl, options=tous_fournisseurs, index=index_frs,
                                           placeholder="Choisir…")

                # Date, plage, quai, état et commentaire : pertinents pour une
                # nouvelle réception uniquement (non saisis en expédition/archivage).
                if reception_bl:
                    nouvelle_date = st.date_input("Date de réception", value=bl["date_reception"])
                    index_plage = (repository.PLAGES_HORAIRES.index(bl["plage_horaire"])
                                   if bl.get("plage_horaire") in repository.PLAGES_HORAIRES else None)
                    nouvelle_plage = st.selectbox("Plage horaire de réception",
                                                  options=repository.PLAGES_HORAIRES, index=index_plage,
                                                  placeholder="Non renseignée (BL antérieur)")
                    index_quai = (repository.QUAIS_RECEPTION.index(bl["quai_reception"])
                                  if bl.get("quai_reception") in repository.QUAIS_RECEPTION else None)
                    nouveau_quai = st.selectbox("Quai de réception", options=repository.QUAIS_RECEPTION,
                                                index=index_quai, placeholder="Non renseigné (BL antérieur)")
                    nouveau_statut = st.radio(
                        "État de réception", ["OK", "EDI NOK"], horizontal=True,
                        index=0 if bl["statut_bl"] == repository.STATUT_OK else 1,
                    )
                    nouveau_commentaire = st.text_area("Commentaire", value=bl["comment_bl"] or "", max_chars=1000)
                else:
                    nouvelle_date = nouvelle_plage = nouveau_quai = None
                    nouveau_statut = None
                    nouveau_commentaire = None

                if st.form_submit_button("💾 Enregistrer les modifications", type="primary",
                                         use_container_width=True):
                    try:
                        champs = {
                            "numero_bl": nouveau_numero.strip(),
                            "nom_fournisseur": nouveau_frs,
                        }
                        if reception_bl:
                            champs["date_reception"] = nouvelle_date
                            champs["statut_bl"] = (repository.STATUT_OK if nouveau_statut == "OK"
                                                   else repository.STATUT_EDI_NOK)
                            champs["comment_bl"] = nouveau_commentaire.strip()
                            if nouveau_quai:  # BL antérieurs : quai absent tant que non choisi
                                champs["quai_reception"] = nouveau_quai
                            if nouvelle_plage:
                                champs["plage_horaire"] = nouvelle_plage
                        # Transition EDI NOK -> OK : à notifier par email (après
                        # l'UPDATE, pour ne jamais bloquer la mise à jour).
                        passe_a_ok = (reception_bl
                                      and bl["statut_bl"] == repository.STATUT_EDI_NOK
                                      and champs["statut_bl"] == repository.STATUT_OK)
                        repository.mettre_a_jour_bl(id_bl, champs, utilisateur)
                        if passe_a_ok:
                            envoye = notifications.notifier_passage_ok(
                                numero_bl=nouveau_numero.strip(),
                                fournisseur=nouveau_frs,
                                quai=champs.get("quai_reception", ""),
                                date_reception=nouvelle_date,
                                utilisateur=utilisateur,
                            )
                            if envoye:
                                ui.set_flash("success",
                                             f"BL {nouveau_numero} mis à jour — passage à OK notifié par email.")
                            else:
                                ui.set_flash("warning",
                                             f"BL {nouveau_numero} mis à jour, mais la notification email "
                                             "n'a pas pu être envoyée (voir les logs de l'app).")
                        else:
                            ui.set_flash("success", f"BL {nouveau_numero} mis à jour.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Échec de la mise à jour : {e}")

            # ----- Traçabilité -----
            st.caption(
                f"Créé par **{bl['saisie_par'] or '?'}** le {bl['saisie_le'] or '?'} · "
                f"Opération : {repository.LIBELLES_OPERATION.get(type_op_bl, type_op_bl)}"
                + (f" · Modifié par **{bl['modifie_par']}** le {bl['modifie_le']}" if bl["modifie_par"] else "")
            )

            # ----- Suppression logique / restauration (confirmation en 2 temps) -----
            if bl.get("est_supprime"):
                if st.button("♻️ Restaurer ce BL", key=f"rest_{id_bl}", use_container_width=True):
                    try:
                        repository.restaurer_bl(id_bl, utilisateur)
                        ui.set_flash("success", f"BL {bl['numero_bl']} restauré.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Échec de la restauration : {e}")
            elif st.session_state.get(f"confirme_suppr_{id_bl}"):
                st.warning("Confirmer la suppression ? (suppression logique : le BL reste restaurable)")
                col_oui, col_non = st.columns(2)
                if col_oui.button("✅ Oui, supprimer", key=f"oui_{id_bl}", use_container_width=True):
                    try:
                        repository.supprimer_bl(id_bl, utilisateur)
                        st.session_state.pop(f"confirme_suppr_{id_bl}", None)
                        ui.set_flash("success", f"BL {bl['numero_bl']} supprimé (logiquement).")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Échec de la suppression : {e}")
                if col_non.button("Annuler", key=f"non_{id_bl}", use_container_width=True):
                    st.session_state.pop(f"confirme_suppr_{id_bl}", None)
                    st.rerun()
            else:
                if st.button("🗑️ Supprimer ce BL", key=f"suppr_{id_bl}", use_container_width=True):
                    st.session_state[f"confirme_suppr_{id_bl}"] = True
                    st.rerun()

        # ----- Visionneuse d'images (onglets Page 1, Page 2, …) -----
        with col_images:
            if not chemins:
                st.warning("Aucune page rattachée.")
            elif len(chemins) == 1:
                ui.afficher_photo_volume(chemins[0])
            else:
                onglets = st.tabs([f"Page {i + 1}" for i in range(len(chemins))])
                for onglet, chemin in zip(onglets, chemins):
                    with onglet:
                        ui.afficher_photo_volume(chemin)
