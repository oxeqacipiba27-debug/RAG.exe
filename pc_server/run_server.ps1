# ==============================================================================
# run_server.ps1: PowerShell Launcher for Windows 11 RTX 4070 Server
# ==============================================================================
param (
    [switch]$Background
)

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

$VenvPython = "$ScriptDir\venv\Scripts\python.exe"
if (-not (Test-Path $VenvPython)) {
    Write-Host "[-] Virtual environment not found at $VenvPython!" -ForegroundColor Red
    Write-Host "    Please run setup_server.ps1 first." -ForegroundColor Yellow
    Exit 1
}

Write-Host "=================================================================" -ForegroundColor Cyan
Write-Host "     RTX 4070 Inference Host (Windows 11 LTSC)                   " -ForegroundColor Cyan
Write-Host "=================================================================" -ForegroundColor Cyan

# Display GPU Status
if (Get-Command nvidia-smi -ErrorAction SilentlyContinue) {
    $Gpu = & nvidia-smi --query-gpu=name,temperature.gpu,memory.used,memory.total --format=csv,noheader 2>&1
    Write-Host "[GPU Status] $Gpu" -ForegroundColor Green
}

# Display Local Network Interfaces & Tailscale IP
Write-Host "`n[Network Endpoints]" -ForegroundColor Yellow
$LocalIPs = Get-NetIPAddress -AddressFamily IPv4 -InterfaceAlias * -ErrorAction SilentlyContinue |
    Where-Object { $_.IPAddress -ne "127.0.0.1" -and $_.IPAddress -notlike "169.254*" } |
    Select-Object -ExpandProperty IPAddress

foreach ($ip in $LocalIPs) {
    if ($ip -like "100.*") {
        Write-Host "  ✔ Tailscale Remote IP : http://${ip}:8000 (Accessible from anywhere)" -ForegroundColor Magenta
    } else {
        Write-Host "  ✔ Local LAN IP        : http://${ip}:8000" -ForegroundColor Gray
    }
}
Write-Host "  ✔ Localhost           : http://127.0.0.1:8000" -ForegroundColor Gray

Write-Host "`nStarting server process..." -ForegroundColor Cyan

if ($Background) {
    Start-Process -FilePath $VenvPython -ArgumentList "$ScriptDir\server.py" -WindowStyle Hidden
    Write-Host "[+] Server started in background." -ForegroundColor Green
} else {
    & $VenvPython "$ScriptDir\server.py"
}
