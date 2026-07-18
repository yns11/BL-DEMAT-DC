"""Configuration externalisée : tout vient de l'environnement (app.yaml),
rien n'est codé en dur dans l'UI ni le repository.

V2 Lakebase : plus de catalogue/warehouse/volume Unity Catalog. La connexion
Postgres est décrite par les variables PGHOST/PGPORT/PGDATABASE/PGUSER et
LAKEBASE_ENDPOINT, injectées automatiquement par la ressource d'app
« postgres » (base Lakebase) — voir bl_core/repository.py."""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    pg_schema: str
    max_image_bytes: int
    max_dimension_px: int
    page_size_defaut: int


def get_settings() -> Settings:
    return Settings(
        pg_schema=os.environ.get("BL_PG_SCHEMA", "bl_demat"),
        max_image_bytes=int(os.environ.get("BL_MAX_IMAGE_BYTES", str(2 * 1024 * 1024))),
        max_dimension_px=int(os.environ.get("BL_MAX_DIMENSION_PX", "3508")),
        page_size_defaut=int(os.environ.get("BL_PAGE_SIZE", "25")),
    )
