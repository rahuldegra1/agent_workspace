$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $projectRoot

$pythonExe = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $pythonExe)) {
    throw "Virtual environment not found at $pythonExe. Create it with: py -m venv .venv"
}

Write-Host "Installing PyInstaller into the project environment..."
& $pythonExe -m pip install --upgrade pip
& $pythonExe -m pip install pyinstaller

$exeName = "PC Assistant"
$distPath = Join-Path $projectRoot "dist"
$buildPath = Join-Path $projectRoot "build"
$iconPath = Join-Path $projectRoot "assets\pc_assistant.ico"

Write-Host "Building Windows EXE..."
# Added --collect-all customtkinter to ensure the UI themes are packaged
& $pythonExe -m PyInstaller --noconfirm --clean --distpath $distPath --workpath $buildPath --specpath $projectRoot --name $exeName --onefile --windowed --collect-submodules pynput --collect-submodules uiautomation --collect-all customtkinter --icon $iconPath $projectRoot\desktop_app.py

$installDir = Join-Path $env:LOCALAPPDATA "Programs\PC Assistant"
New-Item -ItemType Directory -Force -Path $installDir | Out-Null

$targetExe = Join-Path $installDir "$exeName.exe"
Copy-Item (Join-Path $distPath "$exeName.exe") -Destination $targetExe -Force

Write-Host "Populating desktop shortcut..."
& (Join-Path $projectRoot "create_desktop_shortcut.ps1") -TargetExe $targetExe -ShortcutName "PC Assistant"

Write-Host "Installation complete." 
Write-Host "Installed EXE: $targetExe"
Write-Host "Desktop shortcut created successfully."