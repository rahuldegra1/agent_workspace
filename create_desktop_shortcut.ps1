param(
    [string]$TargetExe = (Join-Path $env:LOCALAPPDATA "Programs\PC Assistant\PC Assistant.exe"),
    [string]$ShortcutName = "PC Assistant"
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $TargetExe)) {
    throw "Target executable not found: $TargetExe"
}

$WshShell = New-Object -ComObject WScript.Shell
$desktop = [Environment]::GetFolderPath("Desktop")
$startMenuPrograms = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"

foreach ($path in @($desktop, $startMenuPrograms)) {
    if (-not (Test-Path $path)) {
        New-Item -ItemType Directory -Path $path -Force | Out-Null
    }

    $shortcutPath = Join-Path $path "$ShortcutName.lnk"
    $shortcut = $WshShell.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = $TargetExe
    $shortcut.WorkingDirectory = Split-Path $TargetExe
    $shortcut.IconLocation = "$TargetExe,0"
    $shortcut.Description = "PC Assistant with AI model switching"
    $shortcut.Save()

    Write-Host "Created shortcut: $shortcutPath"
}
