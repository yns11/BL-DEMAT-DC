"""Configuration externalisée : tout vient de l'environnement (app.yaml),
rien n'est codé en dur dans l'UI ni le repository."""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    catalog: str
    schema: str
    volume_path: str
    warehouse_id: str
    max_image_bytes: int
    max_dimension_px: int
    page_size_defaut: int

    @property
    def table_suivi(self) -> str:
        return f"{self.catalog}.{self.schema}.suivi_bl"

    @property
    def table_pieces(self) -> str:
        return f"{self.catalog}.{self.schema}.pieces_jointes_bl"

    @property
    def table_desadv(self) -> str:
        return f"{self.catalog}.{self.schema}.base_desadv"

    @property
    def table_fournisseurs(self) -> str:
        return f"{self.catalog}.{self.schema}.base_frs"


def get_settings() -> Settings:
    catalog = os.environ.get("BL_CATALOG", "poc_bl")
    schema = os.environ.get("BL_SCHEMA", "projet_livraison")
    return Settings(
        catalog=catalog,
        schema=schema,
        # Injecté par la ressource d'app "volume" (valueFrom) ; repli sur le chemin standard.
        volume_path=os.environ.get("BL_VOLUME_PATH", f"/Volumes/{catalog}/{schema}/images_bl"),
        # Injecté par la ressource d'app "sql-warehouse" (valueFrom).
        warehouse_id=os.environ.get("DATABRICKS_WAREHOUSE_ID", ""),
        max_image_bytes=int(os.environ.get("BL_MAX_IMAGE_BYTES", str(2 * 1024 * 1024))),
        max_dimension_px=int(os.environ.get("BL_MAX_DIMENSION_PX", "3508")),
        page_size_defaut=int(os.environ.get("BL_PAGE_SIZE", "25")),
    )
