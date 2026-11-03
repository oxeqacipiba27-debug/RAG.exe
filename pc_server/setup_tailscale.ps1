# ==============================================================================
# setup_tailscale.ps1: Tailscale Remote Mesh VPN Helper for Windows 11
# ==============================================================================
# Tailscale creates a secure, encrypted peer-to-peer WireGuard mesh network
# allowing your Arch Linux laptop to connect to this Windows 11 PC from ANYWHERE
# in the world (hotel Wi-Fi, mobile 5G hotspot, coffee shops, another country)
# without port forwarding, static IPs, or router changes.
# ==============================================================================

Write-Host "=================================================================" -ForegroundColor Cyan
Write-Host "    Tailscale Multi-Network Remote Connectivity Setup            " -ForegroundColor Cyan
Write-Host "=================================================================" -ForegroundColor Cyan

# 1. Check if Tailscale is installed
$TailscaleCmd = Get-Command tailscale.exe -ErrorAction SilentlyContinue
$TailscaleExe = if ($TailscaleCmd) { $TailscaleCmd.Source } else { $null }
if (-not $TailscaleExe) {
    $CommonPaths = @(
        "$env:ProgramFiles\Tailscale\tailscale.exe",
        "$env:ProgramFiles(x86)\Tailscale\tailscale.exe",
        "$env:LOCALAPPDATA\Tailscale\tailscale.exe"
    )
    foreach ($p in $CommonPaths) {
        if (Test-Path $p) {
            $TailscaleExe = $p
            break
        }
    }
}

if (-not $TailscaleExe) {
    Write-Host "[!] Tailscale is not currently installed on this Windows 11 PC." -ForegroundColor Yellow
    Write-Host "    Installing Tailscale via winget..." -ForegroundColor Cyan

    if (Get-Command winget -ErrorAction SilentlyContinue) {
        winget install Tailscale.Tailscale --silent --accept-package-agreements --accept-source-agreements
        Write-Host "[+] Installation command dispatched. Please sign in when Tailscale opens in system tray." -ForegroundColor Green
    } else {
        Write-Host "    Download and install Tailscale for Windows from:" -ForegroundColor Yellow
        Write-Host "    https://tailscale.com/download/windows" -ForegroundColor White
    }
    Exit 0
}

Write-Host "[+] Found Tailscale at: $TailscaleExe" -ForegroundColor Green

# 2. Check Tailscale Connection & Retrieve IP
$Status = & $TailscaleExe status 2>&1
$TailscaleIP = (& $TailscaleExe ip -4 2>&1).Trim()

if ($LASTEXITCODE -ne 0 -or -not $TailscaleIP -or $TailscaleIP -notlike "100.*") {
    Write-Host "[!] Tailscale is installed but not logged in or running." -ForegroundColor Yellow
    Write-Host "    Running 'tailscale up' to authenticate..." -ForegroundColor Cyan
    & $TailscaleExe up
    $TailscaleIP = (& $TailscaleExe ip -4 2>&1).Trim()
}

Write-Host "`n=================================================================" -ForegroundColor Green
Write-Host "    Tailscale Connection Status: ACTIVE                         " -ForegroundColor Green
Write-Host "=================================================================" -ForegroundColor Green
Write-Host "This Windows 11 PC's Tailscale Remote IP: $TailscaleIP" -ForegroundColor Magenta
Write-Host "Server Endpoint for Remote Client      : http://${TailscaleIP}:8000" -ForegroundColor Cyan

Write-Host "`n-----------------------------------------------------------------" -ForegroundColor Yellow
Write-Host " Laptop Client Configuration (Arch Linux):                      " -ForegroundColor Yellow
Write-Host "-----------------------------------------------------------------" -ForegroundColor Yellow
Write-Host "On your Arch Linux laptop, update ~/.config/llm-remote/config.env:" -ForegroundColor White
Write-Host ""
Write-Host "  LLM_SERVER_IP=`"$TailscaleIP`"" -ForegroundColor Green
Write-Host "  LLM_SERVER_PORT=`"8000`"" -ForegroundColor Green
Write-Host ""
Write-Host "Or on the laptop, run:" -ForegroundColor White
Write-Host "  sed -i 's/^LLM_SERVER_IP=.*/LLM_SERVER_IP=\`"$TailscaleIP\`"/' ~/.config/llm-remote/config.env" -ForegroundColor Gray
Write-Host "-----------------------------------------------------------------" -ForegroundColor Yellow
Write-Host "Done! Your Arch Linux laptop can now reach your RTX 4070 from ANY network worldwide." -ForegroundColor Green
