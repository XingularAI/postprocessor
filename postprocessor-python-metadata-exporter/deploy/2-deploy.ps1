<#
    2-deploy.ps1  —  RUN ON THE TARGET LAPTOP (Nx Witness), as Administrator.

    Installs the prebuilt post-processor without rebuilding:
      1. Ensures the VC++ x64 runtime is present (installs it via winget if missing).
      2. Uses the Nx Witness postprocessors folder (override with -NxPostprocessorsDir).
      3. Stops the mediaserver, copies exe+dll -> postprocessors, ini -> etc.
      4. Merges/creates external_postprocessors.json (entry name "Metadata Exporter").
      5. Restarts the mediaserver.

    Usage (from the deploy folder):
      powershell -ExecutionPolicy Bypass -File .\2-deploy.ps1
      powershell -ExecutionPolicy Bypass -File .\2-deploy.ps1 -BackendUrl "http://192.168.1.50:8000/ingest"
#>

param(
    [string]$BackendUrl = "http://127.0.0.1:8000/ingest",
    [string]$SocketPath = "C:\Windows\Temp\metadata-exporter.sock",
    [string]$NxPostprocessorsDir = ""   # override auto-discovery if needed (e.g. Nx Meta)
)

$ErrorActionPreference = "Stop"
$payload = Join-Path $PSScriptRoot "payload"

# --- must be Administrator (systemprofile paths are protected) ---
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
           ).IsInRole([Security.Principal.WindowsBuiltinRole]::Administrator)
if (-not $isAdmin) { Write-Error "Please run this script as Administrator."; exit 1 }

# --- payload check ---
$exeSrc = Join-Path $payload "postprocessor-python-metadata-exporter.exe"
$dllSrc = Join-Path $payload "nxai-c-utilities-shared.dll"
$iniSrc = Join-Path $payload "plugin.metadata-exporter.ini"
foreach ($f in @($exeSrc, $dllSrc)) {
    if (-not (Test-Path $f)) { Write-Error "Missing payload file: $f. Run 1-package.ps1 on the source laptop first."; exit 1 }
}

# --- 1. VC++ x64 runtime ---
$need = @("VCRUNTIME140.dll", "VCRUNTIME140_1.dll", "MSVCP140.dll")
$missing = @($need | Where-Object { -not (Test-Path (Join-Path $env:SystemRoot "System32\$_")) })
if ($missing.Count -gt 0) {
    Write-Host "VC++ runtime missing: $($missing -join ', '). Installing..." -ForegroundColor Yellow
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        winget install --id Microsoft.VCRedist.2015+.x64 -e --accept-source-agreements --accept-package-agreements
    } else {
        Write-Warning "winget not found. Install 'Microsoft Visual C++ 2015-2022 Redistributable (x64)' manually, then re-run."
    }
} else {
    Write-Host "VC++ runtime present." -ForegroundColor Green
}

# --- 2. locate the NX Witness postprocessors / etc folders ---
if ($NxPostprocessorsDir) {
    $ppDir = $NxPostprocessorsDir
} else {
    # Nx Witness product folder (NOT Nx Meta / "MetaVMS")
    $ppDir = "C:\Windows\System32\config\systemprofile\AppData\Local\Network Optix\Network Optix Media Server\nx_ai_manager\nxai_manager\postprocessors"
}
$nxaiParent = Split-Path $ppDir -Parent      # ...\nx_ai_manager\nxai_manager
if (-not (Test-Path $nxaiParent)) {
    Write-Error "Nx Witness AI Manager folder not found:`n  $nxaiParent`nIs Nx Witness + AI Manager installed? For Nx Meta or a custom layout, pass -NxPostprocessorsDir <path>."
    exit 1
}
New-Item -ItemType Directory -Force $ppDir | Out-Null
$etcDir  = Join-Path $nxaiParent "etc"
$exeDest = Join-Path $ppDir "postprocessor-python-metadata-exporter.exe"
$jsonPath = Join-Path $ppDir "external_postprocessors.json"
Write-Host "Target (Nx Witness) postprocessors: $ppDir" -ForegroundColor Cyan

# --- find the Nx Witness mediaserver service ("Network Optix Media Server"); exclude Nx Meta ("...MetaVMS...") ---
$svc = Get-Service -ErrorAction SilentlyContinue |
       Where-Object { $_.DisplayName -like "*Network Optix*Media Server*" -and $_.DisplayName -notlike "*MetaVMS*" } |
       Select-Object -First 1

# --- 3. stop service (avoid locking a running exe), then copy ---
if ($svc) { Write-Host "Stopping service '$($svc.DisplayName)'..."; Stop-Service $svc.Name -Force -ErrorAction SilentlyContinue }
Remove-Item $SocketPath -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force $etcDir | Out-Null
Copy-Item $exeSrc $ppDir -Force
Copy-Item $dllSrc $ppDir -Force
if (Test-Path $iniSrc) { Copy-Item $iniSrc $etcDir -Force } else { Write-Warning "No plugin.metadata-exporter.ini in payload; using code defaults on target." }
Write-Host "Copied exe + dll -> postprocessors, ini -> etc." -ForegroundColor Green

# --- 4. build the registration entry and merge into the JSON ---
$entry = [ordered]@{
    Name                  = "Metadata Exporter"
    Command               = $exeDest
    SocketPath            = $SocketPath
    ReceiveInputTensor    = $true
    ReceiveConfidenceData = $true
    NoResponse            = $true
    Settings              = @(
        [ordered]@{ type="TextField";     name="externalprocessor.metadata_exporter_backend_url";      caption="Backend URL";         description="Destination URL for events (HTTP POST).";           defaultValue=$BackendUrl },
        [ordered]@{ type="DoubleSpinBox"; name="externalprocessor.metadata_exporter_min_confidence";   caption="Min Confidence";      description="Only send objects with confidence >= this value.";  defaultValue=0.0; minValue=0.0; maxValue=1.0 },
        [ordered]@{ type="SpinBox";       name="externalprocessor.metadata_exporter_heartbeat_seconds"; caption="Heartbeat (seconds)"; description="Send a periodic status event every N seconds; 0 = off."; defaultValue=30; minValue=0; maxValue=3600 },
        [ordered]@{ type="SwitchButton";  name="externalprocessor.metadata_exporter_send_track";        caption="Stream tracking";     description="Send per-frame object positions (heatmap / trajectories / live counts)."; defaultValue=$true },
        [ordered]@{ type="DoubleSpinBox"; name="externalprocessor.metadata_exporter_track_fps";         caption="Tracking rate (fps)"; description="Max tracking samples per second per camera; 0 = off."; defaultValue=5.0; minValue=0.0; maxValue=15.0 },
        [ordered]@{ type="SpinBox";       name="externalprocessor.metadata_exporter_scene_seconds";     caption="Scene refresh (seconds)"; description="Send a downscaled full-frame backdrop every N seconds; 0 = off."; defaultValue=60; minValue=0; maxValue=3600 }
    )
}

$others = @()
if (Test-Path $jsonPath) {
    Copy-Item $jsonPath "$jsonPath.bak" -Force
    Write-Host "Backed up existing JSON -> $jsonPath.bak"
    try {
        $root = Get-Content $jsonPath -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($root.externalPostprocessors) {
            $others = @($root.externalPostprocessors | Where-Object { $_.Name -ne "Metadata Exporter" })
        }
    } catch {
        Write-Warning "Existing JSON was invalid; a fresh file will be written (old one kept as .bak)."
    }
}

$all = @()
$all += $others
$all += $entry
# Serialize each entry on its own to avoid PowerShell 5.1 single-element-array unwrapping.
$entriesJson = @($all | ForEach-Object { $_ | ConvertTo-Json -Depth 30 })
$jsonText = "{`r`n  ""externalPostprocessors"": [`r`n" + ($entriesJson -join ",`r`n") + "`r`n  ]`r`n}"
[System.IO.File]::WriteAllText($jsonPath, $jsonText, (New-Object System.Text.UTF8Encoding($false)))
Write-Host "Wrote registration -> $jsonPath" -ForegroundColor Green

# --- 5. restart the service ---
if ($svc) {
    Write-Host "Starting service '$($svc.DisplayName)'..."
    Start-Service $svc.Name
} else {
    Write-Warning "Mediaserver service not found automatically. Restart it manually (services.msc)."
}

Write-Host ""
Write-Host "Done. Next steps:" -ForegroundColor Green
Write-Host "  1. In the NX Desktop Client, open the camera plugin settings -> Nx AI -> select 'Metadata Exporter'."
Write-Host "  2. Enable object tracking in the pipeline (required for 'detect' events)."
Write-Host "  3. Make sure your backend is reachable at: $BackendUrl"
Write-Host "  4. (Optional) verify the exe loads: run it once manually with the socket path."
