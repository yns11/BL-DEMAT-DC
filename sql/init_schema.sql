-- ============================================================================
-- Initialisation du modèle de données "BL dématérialisés"
-- À exécuter UNE FOIS dans l'éditeur SQL Databricks (ou via la CLI), avec un
-- utilisateur ayant les droits de création sur le metastore.
-- Idempotent : ré-exécutable sans risque (IF NOT EXISTS partout).
-- ============================================================================

CREATE CATALOG IF NOT EXISTS poc_bl;
CREATE SCHEMA IF NOT EXISTS poc_bl.projet_livraison
  COMMENT 'Solution BL dématérialisés (POC)';

-- ----------------------------------------------------------------------------
-- Table 1 : suivi_bl — table principale des bordereaux de livraison
-- Champs conformes au cahier des charges + colonnes de suppression logique
-- (le CDC exige un soft delete : il faut donc des colonnes pour le porter).
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS poc_bl.projet_livraison.suivi_bl (
  id_bl          STRING    NOT NULL COMMENT 'Clé primaire (UUID généré par l''app)',
  numero_bl      STRING    NOT NULL COMMENT 'Numéro écrit sur le document (unique, suffixé -1/-2/... si doublon)',
  date_reception DATE               COMMENT 'Date de livraison effective',
  num_article    STRING             COMMENT 'P-00xxxxxx, lié à base_article.item',
  nom_fournisseur STRING            COMMENT 'Fournisseur, lié à base_frs.name',
  statut_bl      STRING             COMMENT '1 = OK, 0 = EDI NOK',
  comment_bl     STRING             COMMENT 'Commentaire libre',
  saisie_par     STRING             COMMENT 'Utilisateur créateur (SSO)',
  saisie_le      TIMESTAMP          COMMENT 'Horodatage de création (système)',
  modifie_par    STRING             COMMENT 'Dernier utilisateur modificateur',
  modifie_le     TIMESTAMP          COMMENT 'Horodatage de dernière modification',
  operation_type BOOLEAN            COMMENT 'false = nouvelle réception, true = archivage',
  est_supprime   BOOLEAN            COMMENT 'Suppression logique (soft delete)',
  supprime_par   STRING             COMMENT 'Utilisateur ayant supprimé',
  supprime_le    TIMESTAMP          COMMENT 'Horodatage de suppression',
  CONSTRAINT pk_suivi_bl PRIMARY KEY (id_bl)
)
COMMENT 'BL dématérialisés — métadonnées';

-- ----------------------------------------------------------------------------
-- Table 2 : pieces_jointes_bl — photos liées aux BL
-- + index_page pour garantir l'ordre des pages à l'affichage (le nom de
-- fichier seul rendrait le tri fragile).
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS poc_bl.projet_livraison.pieces_jointes_bl (
  id_photo        STRING NOT NULL COMMENT 'Clé primaire de l''image (UUID)',
  id_bl           STRING NOT NULL COMMENT 'Clé étrangère vers suivi_bl.id_bl',
  chemin_stockage STRING          COMMENT 'Chemin absolu du fichier dans le Volume',
  index_page      INT             COMMENT 'Ordre de la page dans le document (0..n)',
  CONSTRAINT pk_pieces_jointes_bl PRIMARY KEY (id_photo),
  CONSTRAINT fk_pieces_bl FOREIGN KEY (id_bl) REFERENCES poc_bl.projet_livraison.suivi_bl (id_bl)
)
COMMENT 'Pages scannées des BL';

-- ----------------------------------------------------------------------------
-- Table 3 : base_article — référentiel articles -> fournisseurs connus
-- Une ligne par couple (article, fournisseur) : un article peut avoir
-- plusieurs fournisseurs connus.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS poc_bl.projet_livraison.base_article (
  item            STRING NOT NULL COMMENT 'Numéro article P-00xxxxxx',
  nom_fournisseur STRING NOT NULL COMMENT 'Fournisseur connu pour cet article'
)
COMMENT 'Référentiel articles / fournisseurs connus';

-- ----------------------------------------------------------------------------
-- Table 4 : base_frs — référentiel fournisseurs
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS poc_bl.projet_livraison.base_frs (
  name STRING NOT NULL COMMENT 'Nom du fournisseur'
)
COMMENT 'Référentiel fournisseurs';

-- ----------------------------------------------------------------------------
-- Volume de stockage des images
-- ----------------------------------------------------------------------------
CREATE VOLUME IF NOT EXISTS poc_bl.projet_livraison.images_bl
  COMMENT 'Photos des BL — nomenclature {id_bl}_{index_page}_{id_photo}.jpg';

-- ----------------------------------------------------------------------------
-- Données d'exemple pour les référentiels (à remplacer par les vraies données)
-- MERGE pour rester idempotent en cas de ré-exécution.
-- ----------------------------------------------------------------------------
MERGE INTO poc_bl.projet_livraison.base_frs AS cible
USING (
  SELECT * FROM (VALUES ('FRN1'), ('FRN2'), ('TRANSPORTS DUPONT'), ('LOGISTIQUE MARTIN')) AS v(name)
) AS src
ON cible.name = src.name
WHEN NOT MATCHED THEN INSERT (name) VALUES (src.name);

MERGE INTO poc_bl.projet_livraison.base_article AS cible
USING (
  SELECT * FROM (VALUES
    ('P-00123456', 'FRN1'),
    ('P-00123456', 'FRN2'),
    ('P-00654321', 'TRANSPORTS DUPONT'),
    ('P-00111222', 'LOGISTIQUE MARTIN')
  ) AS v(item, nom_fournisseur)
) AS src
ON cible.item = src.item AND cible.nom_fournisseur = src.nom_fournisseur
WHEN NOT MATCHED THEN INSERT (item, nom_fournisseur) VALUES (src.item, src.nom_fournisseur);

-- ============================================================================
-- DROITS DES APPLICATIONS (à exécuter APRÈS le premier déploiement des apps)
-- Le warehouse et le volume sont accordés automatiquement via les ressources
-- d'app du bundle. Les TABLES doivent être accordées manuellement au service
-- principal de chaque app (client_id visible via `databricks apps get <nom>`
-- ou dans l'UI de l'app, onglet Authorization).
-- Remplacer <SP_APP_CREATION> et <SP_APP_ADMINISTRATION> ci-dessous.
-- ============================================================================
-- GRANT USE CATALOG ON CATALOG poc_bl TO `<SP_APP_CREATION>`;
-- GRANT USE SCHEMA  ON SCHEMA  poc_bl.projet_livraison TO `<SP_APP_CREATION>`;
-- GRANT SELECT, MODIFY ON TABLE poc_bl.projet_livraison.suivi_bl          TO `<SP_APP_CREATION>`;
-- GRANT SELECT, MODIFY ON TABLE poc_bl.projet_livraison.pieces_jointes_bl TO `<SP_APP_CREATION>`;
-- GRANT SELECT ON TABLE poc_bl.projet_livraison.base_article TO `<SP_APP_CREATION>`;
-- GRANT SELECT ON TABLE poc_bl.projet_livraison.base_frs     TO `<SP_APP_CREATION>`;

-- GRANT USE CATALOG ON CATALOG poc_bl TO `<SP_APP_ADMINISTRATION>`;
-- GRANT USE SCHEMA  ON SCHEMA  poc_bl.projet_livraison TO `<SP_APP_ADMINISTRATION>`;
-- GRANT SELECT, MODIFY ON TABLE poc_bl.projet_livraison.suivi_bl          TO `<SP_APP_ADMINISTRATION>`;
-- GRANT SELECT, MODIFY ON TABLE poc_bl.projet_livraison.pieces_jointes_bl TO `<SP_APP_ADMINISTRATION>`;
-- GRANT SELECT ON TABLE poc_bl.projet_livraison.base_article TO `<SP_APP_ADMINISTRATION>`;
-- GRANT SELECT ON TABLE poc_bl.projet_livraison.base_frs     TO `<SP_APP_ADMINISTRATION>`;
