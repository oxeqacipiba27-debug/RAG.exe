# ==============================================================================
# create_desktop_shortcut.ps1 — Интеграция ярлыка EXSCIO в рабочий стол и меню "Пуск" Windows
# Аналог linux-интеграции (exscio.desktop / Rofi drun / icons hicolor)
# ==============================================================================

[CmdletBinding()]
param(
    [switch]$InstallStartMenu = $true,
    [switch]$InstallDesktop = $true
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$IconPath = Join-Path $ScriptDir "rag_icon.ico"
$VbsPath = Join-Path $ScriptDir "EXSCIO.vbs"
$BatPath = Join-Path $ScriptDir "start.bat"

if (-not (Test-Path $IconPath)) {
    Write-Warning "[!] Файл иконки $IconPath не найден. Будет использована системная иконка."
}

$WshShell = New-Object -ComObject WScript.Shell

function Create-Shortcut {
    param(
        [string]$DestinationPath,
        [string]$Target,
        [string]$Arguments,
        [string]$WorkingDirectory,
        [string]$Icon,
        [string]$Description
    )

    $Shortcut = $WshShell.CreateShortcut($DestinationPath)
    $Shortcut.TargetPath = $Target
    if ($Arguments) { $Shortcut.Arguments = $Arguments }
    $Shortcut.WorkingDirectory = $WorkingDirectory
    if ($Icon -and (Test-Path $Icon)) {
        $Shortcut.IconLocation = "$Icon, 0"
    }
    $Shortcut.Description = $Description
    $Shortcut.Save()
    Write-Host "[OK] Ярлык успешно создан: $DestinationPath" -ForegroundColor Green
}

$TargetExecutable = "wscript.exe"
$TargetArgs = "`"$VbsPath`""
if (-not (Test-Path $VbsPath)) {
    $TargetExecutable = "$env:ComSpec"
    $TargetArgs = "/c `"$BatPath`""
}

$AppDescription = "Интеллектуальный RAG-ассистент EXSCIO (Автономная система поиска и ответов)"

# 1. Ярлык на Рабочий стол
if ($InstallDesktop) {
    $DesktopPath = [Environment]::GetFolderPath([Environment+SpecialFolder]::Desktop)
    $DesktopShortcut = Join-Path $DesktopPath "EXSCIO Studio.lnk"
    Create-Shortcut -DestinationPath $DesktopShortcut `
                    -Target $TargetExecutable `
                    -Arguments $TargetArgs `
                    -WorkingDirectory $ScriptDir `
                    -Icon $IconPath `
                    -Description $AppDescription
}

# 2. Ярлык в меню "Пуск" (Programs)
if ($InstallStartMenu) {
    $ProgramsPath = [Environment]::GetFolderPath([Environment+SpecialFolder]::Programs)
    $StartMenuShortcut = Join-Path $ProgramsPath "EXSCIO Studio.lnk"
    Create-Shortcut -DestinationPath $StartMenuShortcut `
                    -Target $TargetExecutable `
                    -Arguments $TargetArgs `
                    -WorkingDirectory $ScriptDir `
                    -Icon $IconPath `
                    -Description $AppDescription
}

Write-Host "`n[OK] Интеграция лаунчера EXSCIO для Windows успешно завершена." -ForegroundColor Cyan
