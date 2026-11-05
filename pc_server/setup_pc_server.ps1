<#
.SYNOPSIS
    Automated Bootstrap & Model Migrator for Windows 11 LTSC + NVIDIA RTX 4070
    Builds the 100% standalone inference engine in C:\llm_engine
.DESCRIPTION
    1. Creates directory structure: C:\llm_engine\bin, models, logs
    2. Downloads official llama.cpp CUDA binaries & CUDA runtime DLLs
    3. Performs zero-copy migration (hardlinks/symlinks) of existing LM Studio and Ollama GGUF models
    4. Downloads nomic-embed-text-v1.5.Q8_0.gguf for permanent embeddings if absent
    5. Configures standalone Python .venv with FastAPI, Uvicorn, HTTPX, Pydantic, PSUtil
#>

[CmdletBinding()]
param(
    [string]$TargetDir = "C:\llm_engine",
    [switch]$ForceRedownload = $false,
    [switch]$SkipEmbedDownload = $false
)

$ErrorActionPreference = "Stop"

# Console encoding setup (UTF-8 & CP65001)
chcp 65001 > $null
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::InputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

Write-Host "==========================================================================" -ForegroundColor Cyan
Write-Host "  EXSCIO: Standalone LLM + Embeddings Engine Bootstrap (Windows 11 / RTX 4070)" -ForegroundColor Cyan
Write-Host "==========================================================================" -ForegroundColor Cyan
Write-Host ""

# -----------------------------------------------------------------------------
# 1. Directory Structure Creation
# -----------------------------------------------------------------------------
Write-Host "[1/5] Создание файловой структуры в '$TargetDir'..." -ForegroundColor Yellow

$BinDir = Join-Path $TargetDir "bin"
$ModelsDir = Join-Path $TargetDir "models"
$LogsDir = Join-Path $TargetDir "logs"
$VenvDir = Join-Path $TargetDir ".venv"

foreach ($dir in @($BinDir, $ModelsDir, $LogsDir)) {
    if (-not (Test-Path $dir)) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
        Write-Host "  [+] Создан каталог: $dir" -ForegroundColor Green
    } else {
        Write-Host "  [i] Каталог уже существует: $dir" -ForegroundColor DarkGray
    }
}

# -----------------------------------------------------------------------------
# 2. llama.cpp Official CUDA Binaries Download
# -----------------------------------------------------------------------------
Write-Host "`n[2/5] Проверка и загрузка официальных CUDA-бинарников llama.cpp..." -ForegroundColor Yellow

$LlamaServerExe = Join-Path $BinDir "llama-server.exe"

if ((Test-Path $LlamaServerExe) -and (-not $ForceRedownload)) {
    Write-Host "  [OK] llama-server.exe уже установлен в $BinDir" -ForegroundColor Green
} else {
    Write-Host "  [i] Запрос последних релизов через GitHub API..." -ForegroundColor Cyan
    
    $ApiUrl = "https://api.github.com/repos/ggml-org/llama.cpp/releases/latest"
    $Headers = @{ "User-Agent" = "PowerShell-EXSCIO-Bootstrap" }
    
    $Release = $null
    try {
        $Release = Invoke-RestMethod -Uri $ApiUrl -Headers $Headers -TimeoutSec 15
    } catch {
        Write-Warning "  [!] Ошибка запроса latest релиза: $_. Попытка запроса списка релизов..."
    }

    # Fallback to general releases if latest lacks assets
    if (-not $Release -or -not $Release.assets -or ($Release.assets.Count -le 1)) {
        $ReleasesListUrl = "https://api.github.com/repos/ggml-org/llama.cpp/releases?per_page=5"
        $Releases = Invoke-RestMethod -Uri $ReleasesListUrl -Headers $Headers -TimeoutSec 15
        foreach ($r in $Releases) {
            $hasCuda = $r.assets | Where-Object { $_.name -match "bin-win-cuda" }
            if ($hasCuda) {
                $Release = $r
                break
            }
        }
    }

    if (-not $Release) {
        throw "Не удалось получить метаданные релизов llama.cpp с GitHub."
    }

    Write-Host "  [i] Выбран релиз: $($Release.tag_name)" -ForegroundColor Cyan

    # Search for Windows CUDA x64 binaries zip (prefer CUDA 12.x for RTX 4070)
    $binAsset = $Release.assets | Where-Object { 
        $_.name -match "llama-.*-bin-win-cuda-(12\.[0-9]+|cu12)-x64\.zip" 
    } | Select-Object -First 1

    if (-not $binAsset) {
        # General cuda-x64 fallback
        $binAsset = $Release.assets | Where-Object { 
            $_.name -match "llama-.*-bin-win-cuda-.*-x64\.zip" 
        } | Select-Object -First 1
    }

    # Search for matching cudart zip
    $cudartAsset = $Release.assets | Where-Object { 
        $_.name -match "cudart-llama-bin-win-cuda-(12\.[0-9]+|cu12)-x64\.zip" 
    } | Select-Object -First 1

    if (-not $cudartAsset) {
        $cudartAsset = $Release.assets | Where-Object { 
            $_.name -match "cudart-llama-bin-win-cuda-.*-x64\.zip" 
        } | Select-Object -First 1
    }

    if (-not $binAsset) {
        throw "Не найден бинарный архив CUDA x64 в релизе $($Release.tag_name)."
    }

    $TempDownloadDir = Join-Path $env:TEMP "llama_cpp_download_$(Get-Random)"
    New-Item -ItemType Directory -Path $TempDownloadDir -Force | Out-Null

    try {
        # 2a. Download binary zip
        $binZipPath = Join-Path $TempDownloadDir $binAsset.name
        Write-Host "  [>] Загрузка $($binAsset.name) ($([math]::Round($binAsset.size / 1MB, 1)) МБ)..." -ForegroundColor Cyan
        Invoke-WebRequest -Uri $binAsset.browser_download_url -OutFile $binZipPath
        
        Write-Host "  [+] Распаковка бинарников в $BinDir..." -ForegroundColor Cyan
        Expand-Archive -Path $binZipPath -DestinationPath $BinDir -Force

        # 2b. Download cudart zip if available
        if ($cudartAsset) {
            $cudartZipPath = Join-Path $TempDownloadDir $cudartAsset.name
            Write-Host "  [>] Загрузка библиотек CUDA Runtime $($cudartAsset.name) ($([math]::Round($cudartAsset.size / 1MB, 1)) МБ)..." -ForegroundColor Cyan
            Invoke-WebRequest -Uri $cudartAsset.browser_download_url -OutFile $cudartZipPath
            
            Write-Host "  [+] Распаковка CUDA DLL в $BinDir..." -ForegroundColor Cyan
            Expand-Archive -Path $cudartZipPath -DestinationPath $BinDir -Force
        }
    } finally {
        Remove-Item -Path $TempDownloadDir -Recurse -Force -ErrorAction SilentlyContinue
    }

    if (-not (Test-Path $LlamaServerExe)) {
        throw "Критическая ошибка: llama-server.exe не обнаружен после распаковки в $BinDir"
    }
    Write-Host "  [OK] llama.cpp CUDA успешно установлен: $LlamaServerExe" -ForegroundColor Green
}

# -----------------------------------------------------------------------------
# 3. Zero-Copy GGUF Model Finder & Importer (Hardlinks / Symlinks)
# -----------------------------------------------------------------------------
Write-Host "`n[3/5] Zero-Copy сканирование и миграция моделей (LM Studio & Ollama)..." -ForegroundColor Yellow

$migratedCount = 0

function Create-ModelLink {
    param(
        [string]$SourcePath,
        [string]$TargetName
    )

    $cleanName = $TargetName -replace '[\\/:*?"<>| ]', '_'
    if (-not $cleanName.EndsWith(".gguf", [System.StringComparison]::OrdinalIgnoreCase)) {
        $cleanName += ".gguf"
    }

    $destPath = Join-Path $ModelsDir $cleanName
    if (Test-Path $destPath) {
        Write-Host "  [i] Модель уже подключена: $cleanName" -ForegroundColor DarkGray
        return
    }

    # Attempt hardlink first (requires 0 disk space and zero admin elevation on same volume)
    $linked = $false
    try {
        New-Item -ItemType HardLink -Path $destPath -Target $SourcePath -Force -ErrorAction Stop | Out-Null
        $linked = $true
        Write-Host "  [OK] Создан HardLink (0 байт на диске): $cleanName -> $SourcePath" -ForegroundColor Green
    } catch {
        # Fallback to SymbolicLink (if cross-volume)
        try {
            New-Item -ItemType SymbolicLink -Path $destPath -Target $SourcePath -Force -ErrorAction Stop | Out-Null
            $linked = $true
            Write-Host "  [OK] Создан SymLink: $cleanName -> $SourcePath" -ForegroundColor Green
        } catch {
            Write-Warning "  [!] Не удалось создать ссылку для $($cleanName): $_"
        }
    }

    if ($linked) {
        $script:migratedCount++
    }
}

# 3a. Scan LM Studio directory (checks both ~/.cache/lm-studio/models and ~/.lmstudio/models)
$LmStudioPaths = @(
    (Join-Path $env:USERPROFILE ".cache\lm-studio\models"),
    (Join-Path $env:USERPROFILE ".lmstudio\models")
)
$lmFound = $false
foreach ($lmPath in $LmStudioPaths) {
    if (Test-Path $lmPath) {
        $lmFound = $true
        Write-Host "  [*] Поиск моделей в LM Studio: $lmPath" -ForegroundColor Cyan
        $lmFiles = Get-ChildItem -Path $lmPath -Filter "*.gguf" -Recurse -File -ErrorAction SilentlyContinue
        foreach ($f in $lmFiles) {
            Create-ModelLink -SourcePath $f.FullName -TargetName $f.Name
        }
    }
}
if (-not $lmFound) {
    Write-Host "  [i] Каталог LM Studio не найден." -ForegroundColor DarkGray
}

# 3b. Scan Ollama manifests and blobs (respects OLLAMA_MODELS env var)
$ollamaRoot = if ($env:OLLAMA_MODELS) { $env:OLLAMA_MODELS } else { Join-Path $env:USERPROFILE ".ollama\models" }
$OllamaManifests = Join-Path $ollamaRoot "manifests"
$OllamaBlobs = Join-Path $ollamaRoot "blobs"

if ((Test-Path $OllamaManifests) -and (Test-Path $OllamaBlobs)) {
    Write-Host "  [*] Поиск моделей в Ollama ($ollamaRoot)..." -ForegroundColor Cyan
    $manifestFiles = Get-ChildItem -Path $OllamaManifests -Recurse -File -ErrorAction SilentlyContinue
    
    $processedBlobs = @{}

    foreach ($mf in $manifestFiles) {
        try {
            $manifestJson = Get-Content -Path $mf.FullName -Raw | ConvertFrom-Json
            if ($manifestJson -and $manifestJson.layers) {
                # Find layer with GGUF model mediaType
                $modelLayer = $manifestJson.layers | Where-Object { 
                    $_.mediaType -eq "application/vnd.ollama.image.model" 
                } | Select-Object -First 1

                if ($modelLayer -and $modelLayer.digest) {
                    $blobHash = $modelLayer.digest -replace '^sha256:', 'sha256-'
                    $blobPath = Join-Path $OllamaBlobs $blobHash
                    
                    if (Test-Path $blobPath) {
                        # Construct human-friendly model name from manifest relative path
                        $rel = $mf.FullName.Substring($OllamaManifests.Length).TrimStart('\', '/')
                        # e.g. registry.ollama.ai\library\qwen2.5\14b -> qwen2.5-14b
                        $parts = $rel.Split([char[]]@('\', '/'))
                        $meaningfulParts = @()
                        foreach ($p in $parts) {
                            if ($p -notin @("registry.ollama.ai", "library", "manifests", "latest")) {
                                $meaningfulParts += $p
                            }
                        }
                        if ($meaningfulParts.Count -eq 0) {
                            $meaningfulParts += $mf.Directory.Name
                        }
                        $modelName = ($meaningfulParts -join "-") + ".gguf"
                        
                        Create-ModelLink -SourcePath $blobPath -TargetName $modelName
                        $processedBlobs[$blobHash] = $true
                    }
                }
            }
        } catch {
            Write-Debug "Ошибка чтения манифеста $($mf.FullName): $_"
        }
    }

    # 3c. Scan any remaining large blobs that are GGUF files by header magic ('GGUF' = 0x47, 0x47, 0x55, 0x46)
    $blobFiles = Get-ChildItem -Path $OllamaBlobs -File -ErrorAction SilentlyContinue | Where-Object { $_.Length -gt 50MB }
    foreach ($bf in $blobFiles) {
        if (-not $processedBlobs.ContainsKey($bf.Name)) {
            $stream = $null
            try {
                $stream = [System.IO.File]::OpenRead($bf.FullName)
                $buffer = New-Object byte[] 4
                $read = $stream.Read($buffer, 0, 4)
                if ($read -eq 4 -and $buffer[0] -eq 0x47 -and $buffer[1] -eq 0x47 -and $buffer[2] -eq 0x55 -and $buffer[3] -eq 0x46) {
                    $shortHash = $bf.Name.Substring(0, [math]::Min(19, $bf.Name.Length))
                    $autoName = "ollama_$shortHash.gguf"
                    Create-ModelLink -SourcePath $bf.FullName -TargetName $autoName
                }
            } catch {
                # Ignore read locked blobs
            } finally {
                if ($stream) { $stream.Dispose() }
            }
        }
    }
} else {
    Write-Host "  [i] Каталоги Ollama не найдены." -ForegroundColor DarkGray
}

Write-Host "  [OK] Завершена миграция моделей (подключено новых: $migratedCount)." -ForegroundColor Green

# -----------------------------------------------------------------------------
# 4. HuggingFace Nomic Embeddings Model Download
# -----------------------------------------------------------------------------
Write-Host "`n[4/5] Проверка перманентной модели эмбеддингов Nomic v1.5..." -ForegroundColor Yellow

$NomicEmbedFile = Join-Path $ModelsDir "nomic-embed-text-v1.5.Q8_0.gguf"

# Check if nomic-embed model was already migrated from Ollama/LM Studio
$existingNomic = Get-ChildItem -Path $ModelsDir -Filter "*nomic-embed*.gguf" -File -ErrorAction SilentlyContinue | Select-Object -First 1

if (Test-Path $NomicEmbedFile) {
    Write-Host "  [OK] Модель эмбеддингов уже присутствует: $NomicEmbedFile" -ForegroundColor Green
} elseif ($existingNomic) {
    Create-ModelLink -SourcePath $existingNomic.FullName -TargetName "nomic-embed-text-v1.5.Q8_0.gguf"
    Write-Host "  [OK] Модель эмбеддингов подключена из существующих весов: $($existingNomic.Name)" -ForegroundColor Green
} elseif ($SkipEmbedDownload) {
    Write-Host "  [i] Загрузка модели эмбеддингов пропущена по флагу -SkipEmbedDownload." -ForegroundColor Yellow
} else {
    $NomicUrl = "https://huggingface.co/nomic-ai/nomic-embed-text-v1.5-GGUF/resolve/main/nomic-embed-text-v1.5.Q8_0.gguf"
    Write-Host "  [>] Загрузка nomic-embed-text-v1.5.Q8_0.gguf (~274 МБ) с HuggingFace..." -ForegroundColor Cyan
    
    $tmpEmbed = $NomicEmbedFile + ".tmp"
    try {
        Invoke-WebRequest -Uri $NomicUrl -OutFile $tmpEmbed
        Move-Item -Path $tmpEmbed -Destination $NomicEmbedFile -Force
        Write-Host "  [OK] Модель nomic-embed-text-v1.5 успешно сохранена в $NomicEmbedFile" -ForegroundColor Green
    } catch {
        Remove-Item -Path $tmpEmbed -Force -ErrorAction SilentlyContinue
        Write-Warning "  [!] Не удалось загрузить nomic-embed напрямую: $_"
        Write-Host "      Вы можете поместить nomic-embed-text-v1.5.Q8_0.gguf вручную в $ModelsDir" -ForegroundColor Yellow
    }
}

# -----------------------------------------------------------------------------
# 5. Standalone Python Virtual Environment Setup (.venv)
# -----------------------------------------------------------------------------
Write-Host "`n[5/5] Настройка изолированного Python окружения в '$VenvDir'..." -ForegroundColor Yellow

$PythonCmd = $null
if (Test-Path "$VenvDir\Scripts\python.exe") {
    $PythonCmd = "$VenvDir\Scripts\python.exe"
    Write-Host "  [i] Окружение .venv уже создано." -ForegroundColor DarkGray
} else {
    # Find system python or repo venv
    $sysPy = $null
    $candRepoPy1 = Join-Path $PSScriptRoot "venv\Scripts\python.exe"
    $candRepoPy2 = Join-Path $PSScriptRoot "..\venv\Scripts\python.exe"
    if (Test-Path $candRepoPy1) {
        $sysPy = (Resolve-Path $candRepoPy1).Path
    } elseif (Test-Path $candRepoPy2) {
        $sysPy = (Resolve-Path $candRepoPy2).Path
    }

    if (-not $sysPy) {
        $sysPy = (Get-Command python -ErrorAction SilentlyContinue).Source
    }
    if (-not $sysPy) {
        $sysPy = (Get-Command py -ErrorAction SilentlyContinue).Source
    }

    if (-not $sysPy) {
        throw "Python 3.10+ не найден в системе. Установите Python и добавьте его в PATH."
    }

    Write-Host "  [+] Создание .venv с использованием $sysPy..." -ForegroundColor Cyan
    & $sysPy -m venv $VenvDir
    $PythonCmd = "$VenvDir\Scripts\python.exe"
}

Write-Host "  [+] Установка production-зависимостей (fastapi, uvicorn, httpx, pydantic, psutil)..." -ForegroundColor Cyan
& $PythonCmd -m pip install --quiet --upgrade pip
& $PythonCmd -m pip install --quiet fastapi uvicorn httpx pydantic psutil

# Ensure service.py is present in C:\llm_engine
$ServicePyDest = Join-Path $TargetDir "service.py"
$ServiceCandidates = @(
    (Join-Path $PSScriptRoot "service.py"),
    (Join-Path $PSScriptRoot "pc_server\service.py"),
    (Join-Path $PSScriptRoot "RAG.exe-windows\pc_server\service.py"),
    (Join-Path $PSScriptRoot "..\pc_server\service.py"),
    "C:\llm_engine\service.py"
)

$foundService = $null
foreach ($cand in $ServiceCandidates) {
    if (Test-Path $cand) {
        $foundService = $cand
        break
    }
}

if ($foundService -and ($foundService -ne $ServicePyDest)) {
    Copy-Item -Path $foundService -Destination $ServicePyDest -Force
    Write-Host "  [+] Скопирован service.py в $ServicePyDest (из $foundService)" -ForegroundColor Green
} elseif (Test-Path $ServicePyDest) {
    Write-Host "  [i] service.py уже присутствует в $ServicePyDest" -ForegroundColor DarkGray
} else {
    Write-Warning "  [!] service.py не найден ни в одном из исходных каталогов!"
}

Write-Host ""
Write-Host "==========================================================================" -ForegroundColor Green
Write-Host "  [OK] ПОДГОТОВКА СЕРВЕРА LLM ЗАВЕРШЕНА УСПЕШНО!" -ForegroundColor Green
Write-Host "==========================================================================" -ForegroundColor Green
Write-Host "  - Корневой каталог: $TargetDir" -ForegroundColor White
Write-Host "  - llama-server:     $LlamaServerExe" -ForegroundColor White
Write-Host "  - Каталог моделей:  $ModelsDir" -ForegroundColor White
Write-Host "  - Интерпретатор:    $VenvDir\Scripts\python.exe" -ForegroundColor White
Write-Host ""
Write-Host "Для ручного запуска сервера выполните:" -ForegroundColor Yellow
Write-Host "  $VenvDir\Scripts\python.exe $TargetDir\service.py" -ForegroundColor Cyan
Write-Host ""
Write-Host "Для настройки автозапуска при загрузке Windows и Wake-on-LAN выполните:" -ForegroundColor Yellow
Write-Host "  powershell -ExecutionPolicy Bypass -File .\configure_windows_ltsc.ps1" -ForegroundColor Cyan
Write-Host "==========================================================================" -ForegroundColor Green
