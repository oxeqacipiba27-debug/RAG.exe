# ==============================================================================
# setup_firewall.ps1: Windows Defender Firewall Configuration for Port 8000
# ==============================================================================
# Run as Administrator in PowerShell
# ==============================================================================
param (
    [ValidateSet("allow", "remove", "check")]
    [string]$Action = "allow"
)

$RuleName = "RTX 4070 LLM Server"
$Port = 8000

if ($Action -eq "allow") {
    Write-Host "[*] Configuring Windows Defender Firewall for TCP Port $Port..." -ForegroundColor Yellow

    # Remove previous rule if exists
    Remove-NetFirewallRule -DisplayName $RuleName -ErrorAction SilentlyContinue

    # Add Inbound Rule
    New-NetFirewallRule -DisplayName $RuleName `
        -Direction Inbound `
        -LocalPort $Port `
        -Protocol TCP `
        -Action Allow `
        -Profile Any `
        -Description "Permits external inference calls from remote Arch Linux client to RTX 4070 PC Server" | Out-Null

    Write-Host "[+] Successfully created firewall rule '$RuleName' allowing inbound TCP port $Port across all profiles." -ForegroundColor Green

} elseif ($Action -eq "remove") {
    Remove-NetFirewallRule -DisplayName $RuleName -ErrorAction SilentlyContinue
    Write-Host "[+] Removed firewall rule '$RuleName'." -ForegroundColor Green

} elseif ($Action -eq "check") {
    $Rule = Get-NetFirewallRule -DisplayName $RuleName -ErrorAction SilentlyContinue
    if ($Rule) {
        Write-Host "[+] Rule '$RuleName' is ACTIVE (Enabled: $($Rule.Enabled), Action: $($Rule.Action))." -ForegroundColor Green
    } else {
        Write-Host "[-] Rule '$RuleName' does NOT exist." -ForegroundColor Red
    }
}
