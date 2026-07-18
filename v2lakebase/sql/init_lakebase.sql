-- ============================================================================
-- V2 Lakebase — initialisation du modèle de données "BL dématérialisés"
-- Dialecte : PostgreSQL (base Lakebase). À exécuter en tant que CRÉATEUR du
-- projet Lakebase (il a tous les droits — aucun admin Unity Catalog requis) :
--   * soit via l'éditeur SQL de la page du projet Lakebase (UI Databricks),
--   * soit via la CLI : databricks psql --project <PROJECT_ID>
-- Idempotent : ré-exécutable sans risque (IF NOT EXISTS / ON CONFLICT).
--
-- ORDRE IMPORTANT : déployer d'abord les deux apps avec leur ressource
-- « postgres » (cela crée leurs rôles Postgres), PUIS exécuter ce script en
-- remplaçant <SP_APP_CREATION> et <SP_APP_ADMINISTRATION> par les client ID
-- des service principals (page de l'app -> onglet Authorization).
-- ============================================================================

CREATE SCHEMA IF NOT EXISTS bl_demat;

-- ----------------------------------------------------------------------------
-- Table 1 : suivi_bl — table principale des bordereaux de livraison
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS bl_demat.suivi_bl (
  id_bl           TEXT PRIMARY KEY,          -- UUID généré par l'app
  numero_bl       TEXT NOT NULL,             -- numéro du document (suffixé -1/-2/... si doublon)
  date_reception  DATE,                      -- NULL pour expédition/archivage
  plage_horaire   TEXT,                      -- 00h-06h, 06h-08h ... 20h-00h ; NULL hors réception
  nom_fournisseur TEXT,                      -- fournisseur, OU client pour une expédition
  quai_reception  TEXT,                      -- B15, B06EST, B06NORD, B02NORD, AUTRE ; NULL hors réception
  statut_bl       TEXT,                      -- '1' = OK, '0' = EDI NOK
  comment_bl      TEXT,
  saisie_par      TEXT,
  saisie_le       TIMESTAMPTZ,
  modifie_par     TEXT,
  modifie_le      TIMESTAMPTZ,
  type_operation  TEXT,                      -- RECEPTION, EXPEDITION ou ARCHIVAGE
  est_supprime    BOOLEAN DEFAULT false,     -- suppression logique (soft delete)
  supprime_par    TEXT,
  supprime_le     TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_suivi_bl_numero  ON bl_demat.suivi_bl (numero_bl);
CREATE INDEX IF NOT EXISTS idx_suivi_bl_saisie  ON bl_demat.suivi_bl (saisie_le DESC);
CREATE INDEX IF NOT EXISTS idx_suivi_bl_date    ON bl_demat.suivi_bl (date_reception);

-- ----------------------------------------------------------------------------
-- Table 2 : pieces_jointes_bl — pages scannées, stockées EN BASE (BYTEA).
-- Chaque page fait <= 2 Mo après compression (bl_core/images.py) : volumétrie
-- adaptée à Postgres, et plus aucune dépendance à un volume Unity Catalog.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS bl_demat.pieces_jointes_bl (
  id_photo   TEXT PRIMARY KEY,               -- UUID généré par l'app
  id_bl      TEXT NOT NULL REFERENCES bl_demat.suivi_bl (id_bl),
  contenu    BYTEA NOT NULL,                 -- octets JPEG de la page
  index_page INT                             -- ordre de la page (0..n)
);
CREATE INDEX IF NOT EXISTS idx_pieces_id_bl ON bl_demat.pieces_jointes_bl (id_bl);

-- ----------------------------------------------------------------------------
-- Table 3 : base_desadv — avis d'expédition (DESADV) : numéro de BL annoncé
-- -> fournisseur expéditeur. Alimentée par le flux EDI.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS bl_demat.base_desadv (
  numero_bl       TEXT NOT NULL,
  nom_fournisseur TEXT NOT NULL,
  PRIMARY KEY (numero_bl, nom_fournisseur)
);

-- ----------------------------------------------------------------------------
-- Table 4 : base_frs — référentiel fournisseurs (et clients : même liste)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS bl_demat.base_frs (
  name TEXT PRIMARY KEY
);

-- ----------------------------------------------------------------------------
-- Données d'exemple (à remplacer par les vraies données) — idempotent.
-- ----------------------------------------------------------------------------
INSERT INTO bl_demat.base_frs (name)
VALUES ('FRN1'), ('FRN2'), ('TRANSPORTS DUPONT'), ('LOGISTIQUE MARTIN')
ON CONFLICT (name) DO NOTHING;

INSERT INTO bl_demat.base_desadv (numero_bl, nom_fournisseur)
VALUES ('BL-2026-0001', 'FRN1'), ('BL-2026-0002', 'TRANSPORTS DUPONT')
ON CONFLICT (numero_bl, nom_fournisseur) DO NOTHING;

-- ============================================================================
-- DROITS DES APPLICATIONS — à exécuter APRÈS le déploiement des deux apps
-- (l'attachement de la ressource « postgres » crée leurs rôles Postgres).
-- Remplacer <SP_APP_CREATION> et <SP_APP_ADMINISTRATION> par les client ID
-- des service principals. Vous êtes propriétaire du schéma : aucun droit
-- supplémentaire à demander.
-- ============================================================================
-- App Création : lit les référentiels, insère BL et photos.
-- GRANT USAGE ON SCHEMA bl_demat TO "<SP_APP_CREATION>";
-- GRANT SELECT, INSERT ON bl_demat.suivi_bl, bl_demat.pieces_jointes_bl TO "<SP_APP_CREATION>";
-- GRANT SELECT ON bl_demat.base_frs, bl_demat.base_desadv TO "<SP_APP_CREATION>";

-- App Administration : lit tout, met à jour suivi_bl (correction, soft delete).
-- GRANT USAGE ON SCHEMA bl_demat TO "<SP_APP_ADMINISTRATION>";
-- GRANT SELECT, UPDATE ON bl_demat.suivi_bl TO "<SP_APP_ADMINISTRATION>";
-- GRANT SELECT ON bl_demat.pieces_jointes_bl, bl_demat.base_frs, bl_demat.base_desadv TO "<SP_APP_ADMINISTRATION>";

-- Les tables créées PLUS TARD dans ce schéma hériteront automatiquement :
-- ALTER DEFAULT PRIVILEGES IN SCHEMA bl_demat GRANT SELECT ON TABLES TO "<SP_APP_CREATION>";
-- ALTER DEFAULT PRIVILEGES IN SCHEMA bl_demat GRANT SELECT ON TABLES TO "<SP_APP_ADMINISTRATION>";
