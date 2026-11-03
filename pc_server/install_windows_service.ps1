# ==============================================================================
# install_windows_service.ps1: Configure Windows Auto-Start Task / Service
# ==============================================================================
# Registers a high-priority Windows Scheduled Task that automatically boots
# the RTX 4070 LLM Server on system startup (or user login) in the background.
# ==============================================================================
param (
    [ValidateSet("install", "uninstall", "status", "start", "stop")]
    [string]$Action = "install"
)

$TaskName = "RTX4070_LLM_Server"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvPython = "$ScriptDir\venv\Scripts\python.exe"
$ServerScript = "$ScriptDir\server.py"

if ($Action -eq "install") {
    Write-Host "[*] Registering Scheduled Task '$TaskName' for auto-start..." -ForegroundColor Yellow

    if (-not (Test-Path $VenvPython)) {
        Write-Host "[-] Virtual environment not found at $VenvPython!" -ForegroundColor Red
        Write-Host "    Please run setup_server.ps1 first." -ForegroundColor Yellow
        Exit 1
    }

    # Action: run python server.py in working dir
    $TaskAction = New-ScheduledTaskAction -Execute $VenvPython -Argument "`"$ServerScript`"" -WorkingDirectory $ScriptDir

    # Trigger: At startup or logon
    $TriggerBoot = New-ScheduledTaskTrigger -AtStartup
    $TriggerLogon = New-ScheduledTaskTrigger -AtLogOn

    # Settings: do not stop on battery, restart on failure, run indefinitely
    $Settings = New-ScheduledTaskSettingsSet `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -StartWhenAvailable `
        -RestartCount 3 `
        -RestartInterval (New-TimeSpan -Minutes 1) `
        -ExecutionTimeLimit ([TimeSpan]::Zero)

    # Principal: current user with highest privileges
    $User = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
    $Principal = New-ScheduledTaskPrincipal -UserId $User -LogonType Interactive -RunLevel Highest

    # Unregister if previously existed
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue

    # Register task
    Register-ScheduledTask -TaskName $TaskName `
        -Action $TaskAction `
        -Trigger @($TriggerBoot, $TriggerLogon) `
        -Settings $Settings `
        -Principal $Principal | Out-Null

    Write-Host "[+] Scheduled task '$TaskName' registered successfully!" -ForegroundColor Green
    Write-Host "    The server will now automatically start on Windows boot/logon." -ForegroundColor Green
    Write-Host "    To start it right now, run: .\install_windows_service.ps1 -Action start" -ForegroundColor Cyan

} elseif ($Action -eq "uninstall") {
    Write-Host "[*] Removing Scheduled Task '$TaskName'..." -ForegroundColor Yellow
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "[+] Task '$TaskName' unregistered." -ForegroundColor Green

} elseif ($Action -eq "start") {
    Start-ScheduledTask -TaskName $TaskName
    Write-Host "[+] Started task '$TaskName' in background." -ForegroundColor Green

} elseif ($Action -eq "stop") {
    Stop-ScheduledTask -TaskName $TaskName
    Write-Host "[+] Stopped task '$TaskName'." -ForegroundColor Green

} elseif ($Action -eq "status") {
    Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
}
