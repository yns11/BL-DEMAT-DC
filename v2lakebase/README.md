# BL dématérialisés — V2 Lakebase

Deuxième version de la solution : **toutes les données (métadonnées ET photos)
sont stockées dans une base Lakebase** (Postgres managé Databricks). Aucune
dépendance à Unity Catalog : ni warehouse SQL, ni tables Delta, ni volume —
donc aucun `GRANT USE CATALOG` à demander à un admin. Le créateur du projet
Lakebase a tous les droits nécessaires.

Fonctionnellement identique à la V1 (wizard 3 étapes, DESADV, quai, plages
horaires, types réception/expédition/archivage, notification email, filtres
admin par défaut, capture photo mobile corrigée).

## Ce qui change par rapport à la V1

| | V1 (Unity Catalog) | V2 (Lakebase) |
|---|---|---|
| Métadonnées | tables Delta via SQL warehouse | tables Postgres (schéma `bl_demat`) |
| Photos | volume UC (API Files) | colonne `BYTEA` (≤ 2 Mo/page) |
| Ressources d'app | `sql-warehouse` + `volume` | une seule : `postgres` |
| Droits | GRANTs UC par un admin | GRANTs Postgres par VOUS (créateur du projet) |
| Connexion | databricks-sql-connector | psycopg + jeton OAuth (renouvelé avant 1 h) |

Seuls `bl_core/config.py`, `bl_core/repository.py` (et un libellé dans
`ui.py`/`app.py`) diffèrent — l'interface du repository est identique, les
applications Streamlit sont inchangées.

## Déploiement pas à pas

### 1. La base Lakebase (déjà créée)

Repérez dans la page de votre projet Lakebase : le **projet**, la **branche**
(`production` par défaut) et la **base** (`databricks_postgres` par défaut).

### 2. Créer les deux apps et attacher la ressource Postgres

Pour chaque app (`bl-creation`, `bl-administration`) :

1. **Compute → Apps → Create app** (app personnalisée, sans template).
2. Page de l'app → **Edit** → **Resources** → **+ Add resource** →
   type **Database (Lakebase / Postgres)** : sélectionnez votre projet,
   la branche et la base, permission **Can connect and create**,
   clé de ressource : `postgres`.
3. Sauvegardez. L'attachement crée le **rôle Postgres** du service principal
   de l'app et injectera au démarrage : `PGHOST`, `PGPORT`, `PGDATABASE`,
   `PGUSER`, `PGSSLMODE`, `LAKEBASE_ENDPOINT` (utilisées par le code).

### 3. Déployer le code

Comme en V1 : dossier Git dans le workspace (ou upload), puis **Deploy** sur
chaque app en pointant `src/app_creation` / `src/app_administration` de CE
dossier (`v2_lakebase`). Les `requirements.txt` installent `psycopg` et le
SDK ; **aucune variable de connexion à saisir**.

### 4. Créer les tables et donner les droits (vous suffisez !)

1. Récupérez le **client ID** du service principal de chaque app
   (page de l'app → onglet **Authorization**).
2. Ouvrez `sql/init_lakebase.sql`, remplacez `<SP_APP_CREATION>` et
   `<SP_APP_ADMINISTRATION>` par ces client IDs et décommentez les GRANT.
3. Exécutez le script en tant que créateur du projet :
   - via l'éditeur SQL de la page du projet Lakebase, ou
   - via la CLI : `databricks psql --project <PROJECT_ID>` puis `\i sql/init_lakebase.sql`
     (ou copier/coller le contenu).

Le script est idempotent (ré-exécutable). Il crée le schéma `bl_demat`,
les 4 tables (dont les photos en `BYTEA`), les index, des données d'exemple
(`base_frs`, `base_desadv`) et les droits des deux apps.

### 5. Tester

Redémarrez/rafraîchissez les apps, puis créez un BL de bout en bout depuis un
smartphone (le numéro `BL-2026-0001` doit auto-remplir le fournisseur `FRN1`
via les DESADV d'exemple). Vérifiez la fiche et les photos dans l'app
Administration. Remplacez ensuite les données d'exemple par vos référentiels
réels, et configurez le SMTP dans `src/app_administration/app.yaml` pour
activer la notification EDI NOK → OK.

## Notes d'exploitation

- **Jeton OAuth** : validité 1 h ; le code renouvelle la connexion au bout de
  45 min et rejoue automatiquement une requête sur coupure (réveil après
  scale-to-zero compris).
- **Scale-to-zero** : la base s'endort après inactivité ; la première requête
  au réveil peut prendre ~1 s — géré par le rejeu automatique.
- **Volumétrie photos** : ≤ 2 Mo/page en JPEG compressé ; adapté à Postgres
  pour ce cas d'usage. Si la volumétrie explose un jour (millions de pages),
  revenir au volume UC de la V1 ou activer un archivage.
- **Synchronisation du code partagé** : `shared/bl_core` est la source de
  vérité ; après modification, exécuter `tools/sync_shared.ps1` (copie vers
  les deux apps).
