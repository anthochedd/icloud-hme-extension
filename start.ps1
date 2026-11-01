# Discover Windows host interfaces before starting the Docker container.
$ErrorActionPreference = 'Stop'
$previousAddresses = $env:IHME_HOST_ADDRESSES
Push-Location $PSScriptRoot
try {
    $addresses = @(Get-NetIPAddress -AddressFamily IPv4 -AddressState Preferred |
        Where-Object { $_.IPAddress -ne '127.0.0.1' -and $_.IPAddress -notlike '169.254.*' } |
        ForEach-Object { @{ name = $_.InterfaceAlias; address = $_.IPAddress } })
    $env:IHME_HOST_ADDRESSES = ConvertTo-Json -InputObject $addresses -Compress
    & docker compose up -d --build
    if ($LASTEXITCODE -ne 0) { throw 'Docker startup failed. Make sure Docker Desktop is running.' }
    Write-Host 'Open http://localhost:8001 to configure iCloud HME.'
} finally {
    $env:IHME_HOST_ADDRESSES = $previousAddresses
    Pop-Location
}
