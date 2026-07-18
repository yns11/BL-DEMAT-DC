"""Notifications par email (SMTP).

Configuration par variables d'environnement (app.yaml — CDC : rien en dur) :
  BL_SMTP_HOST         serveur SMTP (obligatoire pour activer l'envoi)
  BL_SMTP_PORT         port (défaut 587 ; 465 = SMTPS implicite)
  BL_SMTP_USER         identifiant (optionnel : serveur interne sans auth)
  BL_SMTP_PASSWORD     mot de passe — à injecter via un SECRET, jamais en clair
  BL_SMTP_EXPEDITEUR   adresse expéditrice (défaut : BL_SMTP_USER)
  BL_NOTIF_DESTINATAIRE  destinataire des notifications

L'envoi est volontairement NON bloquant : la mise à jour du BL est déjà
enregistrée quand on notifie ; un échec d'email est loggé et signalé à
l'appelant (False), sans faire échouer l'opération métier.
"""

import logging
import os
import smtplib
from email.message import EmailMessage

logger = logging.getLogger("bl.notifications")

DESTINATAIRE_DEFAUT = "younes.elhachi@gmail.com"


def notifier_passage_ok(
    numero_bl: str,
    fournisseur: str,
    quai: str,
    date_reception,
    utilisateur: str,
) -> bool:
    """Notifie que la réception d'un BL est passée de EDI NOK à OK.
    Retourne True si l'email est parti, False sinon (déjà loggé)."""
    hote = os.environ.get("BL_SMTP_HOST", "")
    if not hote:
        logger.warning("BL_SMTP_HOST non configuré : notification non envoyée (BL %s).", numero_bl)
        return False

    port = int(os.environ.get("BL_SMTP_PORT", "587"))
    utilisateur_smtp = os.environ.get("BL_SMTP_USER", "")
    mot_de_passe = os.environ.get("BL_SMTP_PASSWORD", "")
    expediteur = os.environ.get("BL_SMTP_EXPEDITEUR", utilisateur_smtp) or "bl-dematerialise@notification.local"
    destinataire = os.environ.get("BL_NOTIF_DESTINATAIRE", DESTINATAIRE_DEFAUT)

    message = EmailMessage()
    message["Subject"] = f"[BL dématérialisés] BL {numero_bl} : EDI NOK → OK"
    message["From"] = expediteur
    message["To"] = destinataire
    message.set_content(
        "Bonjour,\n\n"
        f"L'état de réception du BL {numero_bl} vient de passer de EDI NOK à OK.\n\n"
        f"  • Fournisseur      : {fournisseur or '—'}\n"
        f"  • Quai de réception : {quai or '—'}\n"
        f"  • Date de réception : {date_reception or '—'}\n"
        f"  • Modifié par       : {utilisateur or '—'}\n\n"
        "Message automatique de l'application Administration des BL."
    )

    try:
        if port == 465:  # SMTPS (TLS implicite)
            smtp = smtplib.SMTP_SSL(hote, port, timeout=10)
        else:            # SMTP + STARTTLS (587 et assimilés)
            smtp = smtplib.SMTP(hote, port, timeout=10)
            smtp.starttls()
        with smtp:
            if utilisateur_smtp:
                smtp.login(utilisateur_smtp, mot_de_passe)
            smtp.send_message(message)
        logger.info("Notification EDI NOK -> OK envoyée à %s (BL %s).", destinataire, numero_bl)
        return True
    except Exception as e:
        logger.error("Échec d'envoi de la notification (BL %s) : %s", numero_bl, e)
        return False
