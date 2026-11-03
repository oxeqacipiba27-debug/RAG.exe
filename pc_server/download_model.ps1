# ==============================================================================
# download_model.ps1: Download Recommended GGUF Models for RTX 4070 (12GB VRAM)
# ==============================================================================
param (
    [ValidateSet("qwen14b", "llama8b-q8", "llama8b-q4", "nomic-embed", "all")]
    [string]$Model = "qwen14b"
)

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ModelsDir = "$ScriptDir\models"
New-Item -ItemType Directory -Force -Path $ModelsDir | Out-Null

$ModelCatalog = @{
    "qwen14b" = @{
        "Name" = "Qwen2.5-14B-Instruct-Q4_K_M.gguf";
        "Url"  = "https://huggingface.co/Qwen/Qwen2.5-14B-Instruct-GGUF/resolve/main/qwen2.5-14b-instruct-q4_k_m.gguf";
        "Desc" = "14B parameter model, Q4_K_M quantization (~8.9GB). Recommended for RTX 4070 12GB VRAM."
    };
    "llama8b-q8" = @{
        "Name" = "Llama-3.1-8B-Instruct-Q8_0.gguf";
        "Url"  = "https://huggingface.co/bartowski/Meta-Llama-3.1-8B-Instruct-GGUF/resolve/main/Meta-Llama-3.1-8B-Instruct-Q8_0.gguf";
        "Desc" = "8B parameter model, high precision Q8_0 quantization (~8.5GB)."
    };
    "llama8b-q4" = @{
        "Name" = "Llama-3.1-8B-Instruct-Q4_K_M.gguf";
        "Url"  = "https://huggingface.co/bartowski/Meta-Llama-3.1-8B-Instruct-GGUF/resolve/main/Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf";
        "Desc" = "8B parameter model, fast Q4_K_M quantization (~4.9GB). Leaves 7GB VRAM for large contexts."
    };
    "nomic-embed" = @{
        "Name" = "nomic-embed-text-v1.5.Q8_0.gguf";
        "Url"  = "https://huggingface.co/nomic-ai/nomic-embed-text-v1.5-GGUF/resolve/main/nomic-embed-text-v1.5.Q8_0.gguf";
        "Desc" = "Dedicated 768-dimensional embedding model (~270MB)."
    }
}

function Download-TargetModel($Key) {
    $info = $ModelCatalog[$Key]
    $dest = "$ModelsDir\$($info.Name)"
    Write-Host "`n[*] Target: $($info.Name)" -ForegroundColor Cyan
    Write-Host "    Description: $($info.Desc)" -ForegroundColor Gray
    Write-Host "    URL: $($info.Url)" -ForegroundColor Gray

    if (Test-Path $dest) {
        Write-Host "    [!] File already exists at: $dest" -ForegroundColor Yellow
        $overwrite = Read-Host "    Overwrite? (y/N)"
        if ($overwrite -ne "y" -and $overwrite -ne "Y") {
            Write-Host "    Skipping download." -ForegroundColor Gray
            return
        }
    }

    Write-Host "    Downloading into models\ ... (this may take several minutes)" -ForegroundColor Yellow
    if (Get-Command curl.exe -ErrorAction SilentlyContinue) {
        & curl.exe -L -o $dest $info.Url --progress-bar
    } else {
        $PrevProgress = $ProgressPreference
        $ProgressPreference = 'SilentlyContinue'
        Invoke-WebRequest -Uri $info.Url -OutFile $dest
        $ProgressPreference = $PrevProgress
    }

    if (Test-Path $dest) {
        $sizeGB = [math]::Round((Get-Item $dest).Length / 1GB, 2)
        Write-Host "    [+] Successfully downloaded $($info.Name) ($sizeGB GB)" -ForegroundColor Green
    } else {
        Write-Host "    [-] Download failed!" -ForegroundColor Red
    }
}

Write-Host "=================================================================" -ForegroundColor Cyan
Write-Host "         GGUF Model Downloader for RTX 4070                      " -ForegroundColor Cyan
Write-Host "=================================================================" -ForegroundColor Cyan

if ($Model -eq "all") {
    foreach ($k in $ModelCatalog.Keys) {
        Download-TargetModel $k
    }
} else {
    Download-TargetModel $Model
}

Write-Host "`nDone! Downloaded models are now available for hot-swapping." -ForegroundColor Green
