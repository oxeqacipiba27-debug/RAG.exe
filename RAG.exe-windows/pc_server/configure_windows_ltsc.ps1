<#
.SYNOPSIS
    Firewall, Autostart & Wake-on-LAN Configuration for Windows 11 LTSC + RTX 4070
.DESCRIPTION
    1. Opens TCP port 8000 in Windows Defender Firewall for LAN and Tailscale
    2. Registers Windows Scheduled Task 'LLM_Engine_4070' running at system boot (-AtStartup)
    3. Enables Wake-on-LAN (Magic Packet) on physical Ethernet adapter
    4. Disables Fast Startup (HiberbootEnabled = 0) so Wake-on-LAN works reliably
    5. Discovers and prints formatted config ready for Arch Linux ~/.config/llm-remote/config.env
#>

[CmdletBinding()]
param(
    [string]$TargetDir = "C:\llm_engine",
    [int]$Port = 8000
)

$ErrorActionPreference = "Continue"

# Console encoding setup (UTF-8 & CP65001)
chcp 65001 > $null
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::InputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

Write-Host "==========================================================================" -ForegroundColor Cyan
Write-Host "  EXSCIO: Windows 11 LTSC Systems & Network Tuning (Port $Port / WoL / Boot)" -ForegroundColor Cyan
Write-Host "==========================================================================" -ForegroundColor Cyan
Write-Host ""

# -----------------------------------------------------------------------------
# 0. Administrator Privileges Check
# -----------------------------------------------------------------------------
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Warning "[!] Скрипт требует прав Администратора для полной настройки Firewall, автозапуска и сетевой карты."
    $scriptPath = if ($PSCommandPath) { $PSCommandPath } else { $MyInvocation.MyCommand.Path }
    if ($scriptPath) {
        try {
            Write-Host "[*] Попытка автоматического перезапуска с повышением привилегий (UAC)..." -ForegroundColor Yellow
            Start-Process powershell.exe -Verb RunAs -ArgumentList ("-ExecutionPolicy Bypass -File `"$scriptPath`"") -ErrorAction Stop
            exit 0
        } catch {
            Write-Warning "Не удалось вызвать диалог UAC в неинтерактивной консоли."
            Write-Host "Для применения системных правил (Firewall/Task/WoL) запустите PowerShell от имени Администратора:" -ForegroundColor Yellow
            Write-Host "  powershell -ExecutionPolicy Bypass -File `"$scriptPath`"" -ForegroundColor Cyan
            Write-Host ""
        }
    } else {
        Write-Error "Пожалуйста, запустите PowerShell от имени Администратора (Run as Administrator)."
        exit 1
    }
}

# -----------------------------------------------------------------------------
# 1. Windows Defender Firewall Inbound Rule
# -----------------------------------------------------------------------------
Write-Host "[1/4] Настройка Windows Defender Firewall для порта $Port (TCP)..." -ForegroundColor Yellow

$RuleName = "LLM_Engine_$Port"

try {
    # Check if rule exists
    $existingRule = Get-NetFirewallRule -DisplayName $RuleName -ErrorAction SilentlyContinue
    if ($existingRule) {
        Remove-NetFirewallRule -DisplayName $RuleName -ErrorAction SilentlyContinue | Out-Null
        Write-Host "  [i] Удалено старое правило брандмауэра '$RuleName'." -ForegroundColor DarkGray
    }

    # Open TCP port 8000 for Private, Domain, and Public profiles (scoped to LAN & Tailscale)
    New-NetFirewallRule -DisplayName $RuleName `
                        -Direction Inbound `
                        -Action Allow `
                        -Protocol TCP `
                        -LocalPort $Port `
                        -Profile Any `
                        -Description "Inbound access for EXSCIO Standalone LLM Engine from Arch Linux Laptop" `
                        -ErrorAction Stop | Out-Null

    Write-Host "  [OK] Правило брандмауэра '$RuleName' успешно создано (TCP Port $Port разрешен)." -ForegroundColor Green
} catch {
    Write-Warning "  [!] Ошибка настройки брандмауэра: $_"
}

# -----------------------------------------------------------------------------
# 2. Windows Scheduled Task for System Boot Autostart (-AtStartup)
# -----------------------------------------------------------------------------
Write-Host "`n[2/4] Регистрация Windows Scheduled Task 'LLM_Engine_4070' (-AtStartup)..." -ForegroundColor Yellow

$TaskName = "LLM_Engine_4070"
$PythonwExe = Join-Path $TargetDir ".venv\Scripts\pythonw.exe"
$ServiceScript = Join-Path $TargetDir "service.py"

if (-not (Test-Path $PythonwExe)) {
    # Fallback to python.exe
    $PythonwExe = Join-Path $TargetDir ".venv\Scripts\python.exe"
}

if (-not (Test-Path $ServiceScript)) {
    Write-Warning "  [!] $ServiceScript не найден в $TargetDir. Убедитесь, что setup_pc_server.ps1 выполнен."
}

try {
    $Action = New-ScheduledTaskAction -Execute $PythonwExe -Argument "`"$ServiceScript`"" -WorkingDirectory $TargetDir
    $Trigger = New-ScheduledTaskTrigger -AtStartup
    $Principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
    $Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Days 0) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)

    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Principal $Principal -Settings $Settings -Description "EXSCIO Standalone RTX 4070 LLM & Embedding Server" -ErrorAction Stop | Out-Null

    Write-Host "  [OK] Задача '$TaskName' зарегистрирована (запуск от SYSTEM при старте ПК до входа пользователя)." -ForegroundColor Green
} catch {
    Write-Warning "  [!] Ошибка регистрации Scheduled Task: $_"
}

# -----------------------------------------------------------------------------
# 3. Wake-on-LAN (WoL) & Fast Startup Disabling
# -----------------------------------------------------------------------------
Write-Host "`n[3/4] Оптимизация сетевого адаптера для Wake-on-LAN (Magic Packet)..." -ForegroundColor Yellow

# 3a. Disable Fast Startup (HiberbootEnabled = 0)
try {
    $pwrReg = "HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager\Power"
    Set-ItemProperty -Path $pwrReg -Name "HiberbootEnabled" -Value 0 -Type DWord -Force -ErrorAction Stop
    Write-Host "  [OK] Быстрый запуск (Fast Startup) отключен (HiberbootEnabled = 0). ACPI S5 чистый shutdown активен." -ForegroundColor Green
} catch {
    Write-Warning "  [!] Не удалось обновить реестр для Fast Startup: $_"
}

# 3b. Locate physical Ethernet adapter
$ethAdapter = Get-NetAdapter | Where-Object { 
    (($_.PhysicalMediaType -match "802.3|Ethernet") -or ($_.InterfaceDescription -match "Ethernet|PCIe|Realtek|Intel|Killer|Broadcom")) -and
    ($_.InterfaceDescription -notmatch "Virtual|VPN|Tailscale|Hyper-V|VMware|Loopback|WSL")
} | Where-Object { $_.Status -eq "Up" } | Select-Object -First 1

if (-not $ethAdapter) {
    # Fallback to any physical adapter that is Up
    $ethAdapter = Get-NetAdapter | Where-Object { 
        $_.Virtual -eq $false -and 
        $_.Status -eq "Up" -and 
        $_.InterfaceDescription -notmatch "Virtual|VPN|Tailscale|Hyper-V|VMware|Loopback|WSL" 
    } | Select-Object -First 1
}

$macAddr = "00:00:00:00:00:00"
$lanIp = "127.0.0.1"

if ($ethAdapter) {
    Write-Host "  [*] Обнаружен физический сетевой адаптер: $($ethAdapter.Name) ($($ethAdapter.InterfaceDescription))" -ForegroundColor Cyan
    $macRaw = $ethAdapter.MacAddress
    if ($macRaw) {
        $macAddr = ($macRaw -replace "-", ":").ToUpper()
        Write-Host "  [OK] MAC-адрес для Magic Packet: $macAddr" -ForegroundColor Green
    }

    # Enable WakeOnMagicPacket in advanced adapter properties
    try {
        Set-NetAdapterAdvancedProperty -Name $ethAdapter.Name -DisplayName "*Wake on Magic Packet*" -DisplayValue "Enabled" -ErrorAction SilentlyContinue | Out-Null
        Set-NetAdapterAdvancedProperty -Name $ethAdapter.Name -DisplayName "Wake on Magic Packet" -DisplayValue "Enabled" -ErrorAction SilentlyContinue | Out-Null
        Write-Host "  [OK] Свойства драйвера WakeOnMagicPacket переведены в режим Enabled." -ForegroundColor Green
    } catch {
        Write-Debug "Set-NetAdapterAdvancedProperty: $_"
    }

    # Enable wake via powercfg
    try {
        $desc = $ethAdapter.InterfaceDescription
        powercfg /deviceenablewake "$desc" 2>$null
        Write-Host "  [OK] powercfg /deviceenablewake активирован для '$desc'." -ForegroundColor Green
    } catch {
        Write-Debug "powercfg error: $_"
    }

    # Get LAN IPv4
    $ipObj = Get-NetIPAddress -InterfaceIndex $ethAdapter.InterfaceIndex -AddressFamily IPv4 -ErrorAction SilentlyContinue | Where-Object { $_.IPAddress -notmatch "^127\.|^169\.254\." } | Select-Object -First 1
    if ($ipObj) {
        $lanIp = $ipObj.IPAddress
    }
} else {
    Write-Warning "  [!] Физический Ethernet адаптер не обнаружен. Настройка WoL пропущена."
}

# Fallback LAN IP discovery if needed (filters out virtual VPN/WSL tunnel adapters)
if ($lanIp -eq "127.0.0.1") {
    $fallbackIp = (Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue | Where-Object { 
        $_.IPAddress -match "^(192\.168\.|10\.|172\.(1[6-9]|2[0-9]|3[0-1])\.)" -and
        $_.InterfaceAlias -notmatch "tun|tap|vpn|vEthernet|Loopback"
    } | Select-Object -First 1)
    if (-not $fallbackIp) {
        $fallbackIp = (Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue | Where-Object { 
            $_.IPAddress -match "^(192\.168\.|10\.|172\.(1[6-9]|2[0-9]|3[0-1])\.)"
        } | Select-Object -First 1)
    }
    if ($fallbackIp) {
        $lanIp = $fallbackIp.IPAddress
    }
}

# 3c. Tailscale IP discovery
$tailscaleIp = $null
if (Get-Command tailscale -ErrorAction SilentlyContinue) {
    try {
        $out = & tailscale ip -4
        if ($LASTEXITCODE -eq 0 -and $out) {
            $tailscaleIp = $out.Trim()
        }
    } catch {}
}
if (-not $tailscaleIp) {
    $tsAdapter = Get-NetAdapter | Where-Object { $_.InterfaceDescription -match "Tailscale" -or $_.Name -match "Tailscale" } | Select-Object -First 1
    if ($tsAdapter) {
        $tsIpObj = Get-NetIPAddress -InterfaceIndex $tsAdapter.InterfaceIndex -AddressFamily IPv4 -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($tsIpObj) {
            $tailscaleIp = $tsIpObj.IPAddress
        }
    }
}

# -----------------------------------------------------------------------------
# 4. Display Formatted Arch Linux Configuration
# -----------------------------------------------------------------------------
Write-Host "`n[4/4] Сбор сетевых координат для Arch Linux ноутбука..." -ForegroundColor Yellow
Write-Host ""
Write-Host "==========================================================================" -ForegroundColor Green
Write-Host "  СКОПИРУЙТЕ ДАННЫЙ БЛОК В ФАЙЛ НА ВАШЕМ ARCH LINUX НОУТБУКЕ:" -ForegroundColor Cyan
Write-Host "  ~/.config/llm-remote/config.env" -ForegroundColor Yellow
Write-Host "==========================================================================" -ForegroundColor Green

$preferredIp = if ($tailscaleIp) { $tailscaleIp } else { $lanIp }
$tsDisplayIp = if ($tailscaleIp) { $tailscaleIp } else { "NONE" }

$configContent = @"
# ==============================================================================
# EXSCIO RTX 4070 Remote LLM & Embeddings Engine Configuration
# Target PC: Windows 11 LTSC | NVIDIA GeForce RTX 4070 (12GB VRAM)
# ==============================================================================
LLM_SERVER_IP="$preferredIp"
LLM_SERVER_PORT="$Port"
LLM_SERVER_MAC="$macAddr"
REAL_SERVER_IP="$lanIp"
TAILSCALE_SERVER_IP="$tsDisplayIp"
LLM_DEFAULT_CTX="16384"
LAUNCHER_CMD="rofi -dmenu -i -p 'RTX 4070'"
"@

Write-Host $configContent -ForegroundColor White
Write-Host "==========================================================================" -ForegroundColor Green
Write-Host ""
Write-Host "[OK] Конфигурация Windows 11 LTSC полностью завершена!" -ForegroundColor Green
Write-Host "     Сервер готов к холодным стартам по Wake-on-LAN и удаленному инференсу." -ForegroundColor Green
