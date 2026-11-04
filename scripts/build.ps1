# Builds dist\PodPop.exe, a single-file app that needs no Python install.
# Usage:  .\scripts\build.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root
$python = Join-Path $root ".venv\Scripts\python.exe"
# Native tools write progress to stderr; judge them by exit code, not by that.
$ErrorActionPreference = "Continue"

& $python -m pytest -q
if ($LASTEXITCODE -ne 0) { throw "Tests failed" }

# Render the tray artwork to an .ico for the exe.
New-Item -ItemType Directory -Force build | Out-Null
& $python -c "from PySide6.QtWidgets import QApplication; app = QApplication([]); from podpop.ui.tray import render_icon; render_icon().pixmap(256, 256).save('build/podpop.ico')"

& $python -m PyInstaller --noconfirm --clean --windowed --onefile `
    --name PodPop `
    --icon build\podpop.ico `
    --paths src `
    --add-data "src\podpop\assets;podpop\assets" `
    --collect-submodules winrt `
    --collect-submodules bleak `
    --hidden-import comtypes.stream `
    scripts\podpop_entry.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

Write-Host "Built $(Join-Path $root 'dist\PodPop.exe')"
