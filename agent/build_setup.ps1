param(
    [switch]$AgentOnly,
    [switch]$InstallerOnly
)

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

function Build-SyncLayerAgent {
    Write-Host "== SyncLayer: build SyncLayerAgent.exe =="

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

    Write-Host "OK: dist\SyncLayerAgent.exe"
}

function Build-SyncLayerSetup {
    Write-Host "== SyncLayer: build SyncLayerSetup.exe =="

    if (!(Test-Path "dist/SyncLayerAgent.exe")) {
        throw "SyncLayerAgent.exe not found — run agent build first"
    }

    $iscc = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
    if (!(Test-Path $iscc)) {
        throw "Inno Setup compiler not found at: $iscc"
    }

    & $iscc "installer\SyncLayerSetup.iss"

    if (!(Test-Path "dist\SyncLayerSetup.exe")) {
        throw "SyncLayerSetup.exe was not built"
    }

    Write-Host "OK: dist\SyncLayerSetup.exe"
}

if ($AgentOnly -and $InstallerOnly) {
    throw "Use only one of -AgentOnly or -InstallerOnly, or omit both for full build"
}

if ($AgentOnly) {
    Build-SyncLayerAgent
    exit 0
}

if ($InstallerOnly) {
    Build-SyncLayerSetup
    exit 0
}

Build-SyncLayerAgent
Build-SyncLayerSetup
Write-Host "Done: dist\SyncLayerSetup.exe"
