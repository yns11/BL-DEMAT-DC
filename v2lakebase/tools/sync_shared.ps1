# Synchronise le package partagé shared/bl_core vers les deux applications.
# À exécuter après toute modification de shared/bl_core :
#   powershell -File tools/sync_shared.ps1
# Pourquoi cette copie : chaque Databricks App est déployée de façon autonome
# (source_code_path) et ne peut pas importer de code situé hors de son dossier.
$racine = Split-Path -Parent $PSScriptRoot
$source = Join-Path $racine "shared\bl_core"

foreach ($app in @("app_creation", "app_administration")) {
    $dest = Join-Path $racine "src\$app\bl_core"
    if (Test-Path $dest) { Remove-Item -Recurse -Force $dest }
    Copy-Item -Recurse $source $dest
    Get-ChildItem $dest -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force
    Write-Host "Synchronisé : $dest"
}
