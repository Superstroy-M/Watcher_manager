$ErrorActionPreference = "Stop"

Set-Location -Path $PSScriptRoot

Write-Host "== SyncLayer: verify config.py =="
python verify_build_url.py config

Write-Host "== SyncLayer: build SyncLayerAgent.exe =="

python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install pyinstaller

if (Test-Path "dist") {
    Remove-Item -Recurse -Force "dist"
}
if (Test-Path "build") {
    Remove-Item -Recurse -Force "build"
}

$iconArgs = @()
if (Test-Path "icon.png") {
    $iconArgs = @("--icon", "icon.png", "--add-data", "icon.png;.")
}

python -m PyInstaller `
  --noconfirm `
  --clean `
  --noconsole `
  --onefile `
  --name SyncLayerAgent `
  --hidden-import pywintypes `
  --hidden-import win32api `
  --hidden-import win32con `
  --hidden-import win32gui `
  --hidden-import win32process `
  --hidden-import win32timezone `
  --collect-submodules pynput `
  @iconArgs `
  app_main.py `
  --distpath dist

if (!(Test-Path "dist/SyncLayerAgent.exe")) {
    throw "SyncLayerAgent.exe was not built"
}

Write-Host "== SyncLayer: verify SyncLayerAgent.exe URL =="
python verify_build_url.py agent-exe --path dist/SyncLayerAgent.exe

Write-Host "== SyncLayer: build installer =="
$iscc = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
if (!(Test-Path $iscc)) {
    throw "Inno Setup compiler not found at: $iscc"
}

& $iscc "installer\SyncLayerSetup.iss"

if (!(Test-Path "dist\SyncLayerSetup.exe")) {
    throw "SyncLayerSetup.exe was not built"
}

Write-Host "== SyncLayer: verify installer artifact =="
python verify_build_url.py installer --path dist/SyncLayerSetup.exe

Write-Host "Done: dist\SyncLayerSetup.exe"
