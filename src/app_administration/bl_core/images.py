"""Traitement d'image : photo brute de terrain -> document "scanné".

Pipeline conforme au cahier des charges (annexe) :
1. Redressement de perspective (détection du contour de la feuille),
   en se rapprochant du ratio A4 quand le quadrilatère détecté en est proche.
2. Limitation de la plus grande dimension à MAX_DIMENSION_PX (3508 par défaut,
   soit un A4 à 300 dpi).
3. Un des 4 modes de rendu : Sans filtre, Couleurs réhaussées, Gris réhaussé,
   Contraste noir & blanc.
4. Boucle de compression JPEG pour garantir une taille de fichier <= 2 Mo.
Le résultat est mis en cache par (contenu d'image, mode) — pas de recalcul à
chaque rerun Streamlit.
"""

import io

import cv2
import numpy as np
import streamlit as st
from PIL import Image, ImageOps

from .config import get_settings

try:
    # Photos "haute efficacité" (HEIC/HEIF), format par défaut des iPhone et de
    # nombreux Android : OpenCV ne sait pas les décoder, Pillow oui via ce plugin.
    from pillow_heif import register_heif_opener

    register_heif_opener()
except ImportError:  # dépendance absente : le repli Pillow reste limité aux formats natifs
    pass

MODES_SCAN = ["Sans filtre", "Couleurs réhaussées", "Gris réhaussé", "Contraste noir & blanc"]

_RATIO_A4 = 297.0 / 210.0  # hauteur / largeur en portrait


def _decoder_image(image_bytes: bytes):
    """Octets -> image BGR. OpenCV d'abord (rapide, couvre JPEG/PNG), repli
    Pillow pour les formats qu'OpenCV ignore (HEIC/HEIF des smartphones), en
    appliquant l'orientation EXIF que ce chemin doit gérer lui-même."""
    img = cv2.imdecode(np.frombuffer(image_bytes, np.uint8), cv2.IMREAD_COLOR)
    if img is not None:
        return img
    try:
        pil = Image.open(io.BytesIO(image_bytes))
        pil = ImageOps.exif_transpose(pil).convert("RGB")
    except Exception as e:
        raise ValueError("Image illisible ou format non supporté.") from e
    return cv2.cvtColor(np.asarray(pil), cv2.COLOR_RGB2BGR)


def _order_points(pts):
    """Range les 4 coins dans l'ordre : haut-gauche, haut-droit, bas-droit, bas-gauche."""
    rect = np.zeros((4, 2), dtype="float32")
    s = pts.sum(axis=1)
    rect[0] = pts[np.argmin(s)]      # haut-gauche  (x+y minimal)
    rect[2] = pts[np.argmax(s)]      # bas-droit    (x+y maximal)
    diff = np.diff(pts, axis=1)
    rect[1] = pts[np.argmin(diff)]   # haut-droit   (x-y minimal)
    rect[3] = pts[np.argmax(diff)]   # bas-gauche   (x-y maximal)
    return rect


def _four_point_transform(image, pts):
    """Aplatit le document (corrige la perspective) à partir de ses 4 coins."""
    rect = _order_points(pts)
    (tl, tr, br, bl) = rect
    max_width = max(int(np.linalg.norm(br - bl)), int(np.linalg.norm(tr - tl)))
    max_height = max(int(np.linalg.norm(tr - br)), int(np.linalg.norm(tl - bl)))

    # Rapprochement du format A4 (CDC) : si le ratio détecté est proche de
    # celui d'un A4 (portrait ou paysage), on force le ratio exact — le léger
    # étirement corrige l'imprécision de la détection de coins.
    ratio = max_height / float(max_width) if max_width else 1.0
    if 0.85 * _RATIO_A4 <= ratio <= 1.15 * _RATIO_A4:
        max_height = int(round(max_width * _RATIO_A4))
    elif 0.85 / _RATIO_A4 <= ratio <= 1.15 / _RATIO_A4:
        max_height = int(round(max_width / _RATIO_A4))

    dst = np.array(
        [[0, 0], [max_width - 1, 0], [max_width - 1, max_height - 1], [0, max_height - 1]],
        dtype="float32",
    )
    M = cv2.getPerspectiveTransform(rect, dst)
    return cv2.warpPerspective(image, M, (max_width, max_height))


def _detecter_et_redresser(img):
    """Détecte le contour de la feuille et corrige la perspective. Repli sur
    l'image entière si aucun quadrilatère n'est trouvé."""
    orig = img.copy()
    # Détection des bords sur une version réduite (plus rapide et plus robuste)
    ratio = img.shape[0] / 500.0
    small = cv2.resize(img, (int(img.shape[1] / ratio), 500))

    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (5, 5), 0)
    edged = cv2.Canny(gray, 75, 200)

    contours, _ = cv2.findContours(edged, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    contours = sorted(contours, key=cv2.contourArea, reverse=True)[:5]

    for c in contours:
        peri = cv2.arcLength(c, True)
        approx = cv2.approxPolyDP(c, 0.02 * peri, True)
        if len(approx) == 4:                 # un quadrilatère = probablement la feuille
            return _four_point_transform(orig, approx.reshape(4, 2) * ratio)
    return orig                              # repli : pas de découpe/redressement


def _limiter_dimension(img, max_px: int):
    """Réduit proportionnellement si la plus grande dimension dépasse max_px (CDC)."""
    h, w = img.shape[:2]
    plus_grand = max(h, w)
    if plus_grand <= max_px:
        return img
    facteur = max_px / float(plus_grand)
    return cv2.resize(img, (int(w * facteur), int(h * facteur)), interpolation=cv2.INTER_AREA)


def _rehausser_niveaux_gris(gray):
    """Rendu 'scan' en niveaux de gris : 1) normalisation de l'éclairage
    (supprime ombres et fond inégal), 2) contraste local (CLAHE),
    3) accentuation douce (unsharp mask)."""
    sigma = max(gray.shape) / 30.0
    fond = cv2.GaussianBlur(gray, (0, 0), sigmaX=sigma)
    normalise = cv2.divide(gray, fond, scale=255)

    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    contraste = clahe.apply(normalise)

    flou = cv2.GaussianBlur(contraste, (0, 0), sigmaX=1.0)
    return cv2.addWeighted(contraste, 1.5, flou, -0.5, 0)  # unsharp mask


def _rehausser_couleur(bgr):
    """Comme le rendu niveaux de gris mais en conservant les couleurs (tampons,
    logos) : rehaussement de la seule luminance en espace LAB."""
    lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    l = clahe.apply(l)
    return cv2.cvtColor(cv2.merge([l, a, b]), cv2.COLOR_LAB2BGR)


def _compresser_jpeg(img, taille_max: int) -> bytes:
    """Encode en JPEG en garantissant taille <= taille_max : baisse de qualité
    progressive, puis réduction de résolution si la qualité minimale ne suffit pas."""
    qualite = 95
    while True:
        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, qualite])
        if not ok:
            raise RuntimeError("Échec de l'encodage JPEG du document scanné.")
        if buf.nbytes <= taille_max:
            return buf.tobytes()
        if qualite > 40:
            qualite -= 7
        else:
            # Qualité plancher atteinte : on réduit la résolution de 15 % et on repart.
            h, w = img.shape[:2]
            img = cv2.resize(img, (int(w * 0.85), int(h * 0.85)), interpolation=cv2.INTER_AREA)
            qualite = 80


@st.cache_data(show_spinner=False, max_entries=30)
def scanner_document(image_bytes: bytes, mode: str = "Gris réhaussé") -> bytes:
    """Photo brute -> document scanné (octets JPEG <= 2 Mo).

    Dans TOUS les modes : redressement de perspective + limite de dimension +
    compression bornée (opérations de base exigées par le CDC). Le mode ne
    change que le rendu visuel.
    """
    img = _decoder_image(image_bytes)

    settings = get_settings()
    redresse = _limiter_dimension(_detecter_et_redresser(img), settings.max_dimension_px)

    if mode == "Sans filtre":
        rendu = redresse
    elif mode == "Couleurs réhaussées":
        rendu = _rehausser_couleur(redresse)
    else:
        gris = _rehausser_niveaux_gris(cv2.cvtColor(redresse, cv2.COLOR_BGR2GRAY))
        if mode == "Contraste noir & blanc":
            # Binarisation Otsu sur image déjà normalisée : propre, sans moucheture.
            _, gris = cv2.threshold(gris, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        rendu = gris

    return _compresser_jpeg(rendu, settings.max_image_bytes)
