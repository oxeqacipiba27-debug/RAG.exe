# ==============================================================================
# setup_server.ps1: Windows 11 Automated Installer for RTX 4070 PC Server
# ==============================================================================
# Run from PowerShell (as Administrator for Firewall rules):
#   powershell -ExecutionPolicy Bypass -File setup_server.ps1
# ==============================================================================

Write-Host "=================================================================" -ForegroundColor Cyan
Write-Host "    RTX 4070 LLM & Embedding Server: Windows 11 Automated Setup  " -ForegroundColor Cyan
Write-Host "=================================================================" -ForegroundColor Cyan

# 1. Check Python
Write-Host "`n[1/6] Checking Python installation..." -ForegroundColor Yellow
$PythonCmd = ""
$PythonArgs = @()
if (Get-Command python -ErrorAction SilentlyContinue) {
    $PythonCmd = "python"
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
    $PythonCmd = "py"
    $PythonArgs = @("-3")
} else {
    Write-Host "[-] Python not found in PATH! Please install Python 3.10, 3.11, or 3.12 from python.org" -ForegroundColor Red
    Write-Host "    Make sure to check 'Add python.exe to PATH' during installation." -ForegroundColor Red
    Exit 1
}

$PyVersion = & $PythonCmd @PythonArgs --version 2>&1
Write-Host "[+] Found Python: $PyVersion" -ForegroundColor Green

# 2. Check NVIDIA GPU & CUDA Drivers
Write-Host "`n[2/6] Verifying NVIDIA GPU & CUDA Driver (RTX 4070)..." -ForegroundColor Yellow
if (Get-Command nvidia-smi -ErrorAction SilentlyContinue) {
    $GpuOutput = & nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader 2>&1
    Write-Host "[+] Detected GPU: $GpuOutput" -ForegroundColor Green
} else {
    Write-Host "[!] 'nvidia-smi' not found in PATH. Ensure NVIDIA Game Ready or Studio Drivers are installed." -ForegroundColor Yellow
}

# 3. Create Directories & Config
Write-Host "`n[3/6] Setting up project directories and environment config..." -ForegroundColor Yellow
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

New-Item -ItemType Directory -Force -Path "$ScriptDir\models" | Out-Null
New-Item -ItemType Directory -Force -Path "$ScriptDir\logs" | Out-Null
Write-Host "[+] Ensured models\ and logs\ directories exist." -ForegroundColor Green

if (-not (Test-Path "$ScriptDir\.env")) {
    Copy-Item "$ScriptDir\config.example.env" "$ScriptDir\.env"
    Write-Host "[+] Created .env from config.example.env" -ForegroundColor Green
} else {
    Write-Host "[+] Existing .env file found; preserving settings." -ForegroundColor Green
}

# 4. Setup Python Virtual Environment (venv)
Write-Host "`n[4/6] Creating Python virtual environment (venv)..." -ForegroundColor Yellow
if (-not (Test-Path "$ScriptDir\venv")) {
    & $PythonCmd @PythonArgs -m venv "$ScriptDir\venv"
    Write-Host "[+] Virtual environment created at $ScriptDir\venv" -ForegroundColor Green
} else {
    Write-Host "[+] Virtual environment already exists." -ForegroundColor Green
}

$VenvPython = "$ScriptDir\venv\Scripts\python.exe"
$VenvPip = "$ScriptDir\venv\Scripts\pip.exe"

Write-Host "Upgrading pip, setuptools, and wheel..." -ForegroundColor Gray
& $VenvPython -m pip install --upgrade pip setuptools wheel --quiet

# 5. Install Dependencies & llama-cpp-python CUDA Wheels
Write-Host "`n[5/6] Installing core dependencies and CUDA accelerated llama-cpp-python..." -ForegroundColor Yellow
& $VenvPip install -r "$ScriptDir\requirements.txt"

Write-Host "Attempting to install pre-built CUDA 12 wheels for llama-cpp-python..." -ForegroundColor Cyan
$CudaSuccess = $false
$WheelIndices = @(
    "https://abetlen.github.io/llama-cpp-python/whl/cu122",
    "https://abetlen.github.io/llama-cpp-python/whl/cu124",
    "https://abetlen.github.io/llama-cpp-python/whl/cu121"
)

foreach ($wheelUrl in $WheelIndices) {
    Write-Host "Trying wheels from: $wheelUrl ..." -ForegroundColor Gray
    & $VenvPip install llama-cpp-python --extra-index-url $wheelUrl --no-warn-script-location --quiet
    $CheckLlama = & $VenvPython -c "import llama_cpp; print('OK')" 2>&1
    if ($CheckLlama -like "*OK*") {
        $CudaSuccess = $true
        Write-Host "[+] llama-cpp-python installed successfully with GPU support from $wheelUrl!" -ForegroundColor Green
        break
    }
}

if (-not $CudaSuccess) {
    Write-Host "[*] Trying standard PyPI llama-cpp-python package..." -ForegroundColor Gray
    & $VenvPip install llama-cpp-python --quiet
    $CheckLlama = & $VenvPython -c "import llama_cpp; print('OK')" 2>&1
    if ($CheckLlama -like "*OK*") {
        Write-Host "[+] Standard llama-cpp-python package installed." -ForegroundColor Green
    } else {
        Write-Host "[!] Pre-compiled llama-cpp-python binary was not found for this Python version." -ForegroundColor Yellow
        Write-Host "    The server will run in high-fidelity mode until compiled with:" -ForegroundColor Yellow
        Write-Host "    `$env:CMAKE_ARGS='-DGGML_CUDA=on'; pip install llama-cpp-python" -ForegroundColor Gray
    }
}

# 6. Windows Firewall Rule for Port 8000
Write-Host "`n[6/6] Configuring Windows Defender Firewall for TCP Port 8000..." -ForegroundColor Yellow
try {
    $RuleExists = Get-NetFirewallRule -DisplayName "RTX 4070 LLM Server" -ErrorAction SilentlyContinue
    if (-not $RuleExists) {
        New-NetFirewallRule -DisplayName "RTX 4070 LLM Server" `
            -Direction Inbound `
            -LocalPort 8000 `
            -Protocol TCP `
            -Action Allow `
            -Profile Any `
            -Description "Allows incoming remote inference requests from Arch Linux laptop to RTX 4070" | Out-Null
        Write-Host "[+] Firewall rule created: TCP 8000 allowed." -ForegroundColor Green
    } else {
        Write-Host "[+] Firewall rule 'RTX 4070 LLM Server' already active." -ForegroundColor Green
    }
} catch {
    Write-Host "[!] Could not configure firewall automatically (Administrator rights required)." -ForegroundColor Yellow
    Write-Host "    To configure manually, run in Admin PowerShell:" -ForegroundColor Yellow
    Write-Host "    New-NetFirewallRule -DisplayName 'RTX 4070 LLM Server' -Direction Inbound -LocalPort 8000 -Protocol TCP -Action Allow" -ForegroundColor Gray
}

# Final Summary
Write-Host "`n=================================================================" -ForegroundColor Green
Write-Host "    Setup Successfully Completed!                                " -ForegroundColor Green
Write-Host "=================================================================" -ForegroundColor Green
Write-Host "Next steps:" -ForegroundColor Cyan
Write-Host "1. Place GGUF models in: $ScriptDir\models\"
Write-Host "   Or run download_model.ps1 to download Qwen2.5-14B or Llama-3.1-8B."
Write-Host "2. Start the server:"
Write-Host "   Double-click run_server.bat or run: .\run_server.ps1"
Write-Host "3. Remote access from ANY outside network:"
Write-Host "   Run .\setup_tailscale.ps1 for zero-config encrypted mesh VPN, or"
Write-Host "   Run .\setup_cloudflare_tunnel.ps1 for instant public HTTPS endpoint."
Write-Host "=================================================================" -ForegroundColor Green
