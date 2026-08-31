$ErrorActionPreference = "Stop"

Set-Location -Path $PSScriptRoot

Write-Host "== SyncLayer: build standalone binaries =="

python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install pyinstaller

if (Test-Path "dist") {
    Remove-Item -Recurse -Force "dist"
}
if (Test-Path "build") {
    Remove-Item -Recurse -Force "build"
}

python -m PyInstaller `
  --noconfirm `
  --clean `
  --noconsole `
  --onefile `
  --name SyncLayerAgent `
  --icon icon.png `
  --add-data "icon.png;." `
  app_main.py `
  --distpath dist

python -m PyInstaller `
  --noconfirm `
  --clean `
  --onefile `
  --name SyncLayerService `
  tracker_service.py `
  --distpath dist

if (!(Test-Path "dist/SyncLayerAgent.exe")) {
    throw "SyncLayerAgent.exe was not built"
}
if (!(Test-Path "dist/SyncLayerService.exe")) {
    throw "SyncLayerService.exe was not built"
}

Write-Host "== SyncLayer: build installer =="
$iscc = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
if (!(Test-Path $iscc)) {
    throw "Inno Setup compiler not found at: $iscc"
}

& $iscc "installer\SyncLayerSetup.iss"

if (!(Test-Path "dist\SyncLayerSetup.exe")) {
    throw "SyncLayerSetup.exe was not built"
}

Write-Host "Done: dist\SyncLayerSetup.exe"
