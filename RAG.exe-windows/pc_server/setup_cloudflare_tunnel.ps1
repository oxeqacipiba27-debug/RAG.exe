# ==============================================================================
# setup_cloudflare_tunnel.ps1: Cloudflare Tunnel Helper for External Remote Access
# ==============================================================================
# Exposes Port 8000 to the public internet via Cloudflare's secure edge network.
# Requires ZERO port forwarding, ZERO router access, and works behind CGNAT.
# Provides a secure public HTTPS endpoint for your laptop.
# ==============================================================================

Write-Host "=================================================================" -ForegroundColor Cyan
Write-Host "    Cloudflare Tunnel (Public HTTPS Remote Access)               " -ForegroundColor Cyan
Write-Host "=================================================================" -ForegroundColor Cyan

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$CloudflaredExe = "$ScriptDir\cloudflared.exe"

# 1. Download cloudflared.exe if missing
if (-not (Test-Path $CloudflaredExe) -and -not (Get-Command cloudflared -ErrorAction SilentlyContinue)) {
    Write-Host "[*] cloudflared.exe not found. Downloading official binary from Cloudflare..." -ForegroundColor Yellow
    $Url = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe"
    Invoke-WebRequest -Uri $Url -OutFile $CloudflaredExe
    Write-Host "[+] Downloaded cloudflared.exe to $CloudflaredExe" -ForegroundColor Green
}

$ExeToRun = if (Test-Path $CloudflaredExe) { $CloudflaredExe } else { "cloudflared" }

Write-Host "`n[*] Starting quick tunnel to http://localhost:8000 ..." -ForegroundColor Cyan
Write-Host "[*] Cloudflare will assign a temporary or persistent public HTTPS domain." -ForegroundColor Gray
Write-Host "[*] Press Ctrl+C to terminate the tunnel when finished.`n" -ForegroundColor Yellow

& $ExeToRun tunnel --url http://localhost:8000
