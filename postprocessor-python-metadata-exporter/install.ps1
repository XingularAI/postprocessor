<#
    install.ps1  —  one-shot on THIS Windows machine (Nx Witness):
        build -> install (exe+dll -> postprocessors, ini -> etc)
        -> register in external_postprocessors.json -> restart the Nx Witness Media Server.
    After it finishes the processor is ready to select in the NX AI Manager.

    Prerequisites (one-time): VS 2022 Build Tools (Desktop C++), CMake >= 3.30,
    Python 3.12, and the nxai-utilities submodule fetched. See README.md.

    Run in an ELEVATED PowerShell (Administrator):
        powershell -ExecutionPolicy Bypass -File .\install.ps1
        powershell -ExecutionPolicy Bypass -File .\install.ps1 -BackendUrl "http://192.168.1.50:8000/ingest"
#>

param(
    [string]$BackendUrl = "http://127.0.0.1:8000/ingest",
    [string]$SocketPath = "C:\Windows\Temp\metadata-exporter.sock",
    [string]$NxNxaiDir  = ""    # override: ...\nx_ai_manager\nxai_manager  (e.g. for Nx Meta)
)

$ErrorActionPreference = "Stop"
$PROC      = "postprocessor-python-metadata-exporter"
$pluginDir = $PSScriptRoot
$sdkRoot   = Split-Path $pluginDir -Parent
$build     = Join-Path $sdkRoot "build"

# --- must be Administrator (systemprofile paths are protected) ---
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
           ).IsInRole([Security.Principal.WindowsBuiltinRole]::Administrator)
if (-not $isAdmin) { Write-Error "Please run this script as Administrator."; exit 1 }

# --- required tools ---
foreach ($t in @("cmake", "python")) {
    if (-not (Get-Command $t -ErrorAction SilentlyContinue)) {
        Write-Error "$t not found on PATH. Install the prerequisites first (see README.md)."; exit 1
    }
}

# --- activate the MSVC build environment (same as the "x64 Native Tools" prompt) ---
# Nuitka needs an active MSVC + Windows SDK environment; doing this here means the script
# works from a plain elevated PowerShell (no need to open the Native Tools prompt).
if (-not $env:VCINSTALLDIR) {
    $vswhere = Join-Path ${env:ProgramFiles(x86)} "Microsoft Visual Studio\Installer\vswhere.exe"
    if (Test-Path $vswhere) {
        $vsPath = & $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath | Select-Object -First 1
        if ($vsPath) {
            $devShell = Join-Path $vsPath "Common7\Tools\Microsoft.VisualStudio.DevShell.dll"
            if (Test-Path $devShell) {
                Import-Module $devShell
                Enter-VsDevShell -VsInstallPath $vsPath -SkipAutomaticLocation -DevCmdArguments "-arch=x64 -host_arch=x64" | Out-Null
                Write-Host "Activated VS x64 build environment: $vsPath" -ForegroundColor Green
            }
        }
    }
    if (-not $env:VCINSTALLDIR) {
        Write-Warning "Could not activate the VS build environment automatically. If the build cannot find a C compiler, run from the 'x64 Native Tools Command Prompt for VS 2022' or install the Windows SDK. (Otherwise Nuitka falls back to downloading Zig.)"
    }
}

# --- Nx Witness AI Manager folders ---
if ($NxNxaiDir) {
    $nxai = $NxNxaiDir
} else {
    $nxai = "C:\Windows\System32\config\systemprofile\AppData\Local\Network Optix\Network Optix Media Server\nx_ai_manager\nxai_manager"
}
if (-not (Test-Path $nxai)) {
    Write-Error "Nx Witness AI Manager folder not found:`n  $nxai`nIs Nx Witness + AI Manager installed? (Nx Meta / custom: pass -NxNxaiDir <path>)"
    exit 1
}
$ppDir  = Join-Path $nxai "postprocessors"
$preDir = Join-Path $nxai "preprocessors"

# --- register the target in the root CMakeLists.txt (idempotent) ---
$rootCMake = Join-Path $sdkRoot "CMakeLists.txt"
if (-not (Select-String -Path $rootCMake -Pattern $PROC -SimpleMatch -Quiet)) {
    Add-Content -Path $rootCMake -Value ('add_subdirectory(${CMAKE_CURRENT_SOURCE_DIR}/' + $PROC + ')')
    Write-Host "Registered '$PROC' in root CMakeLists.txt" -ForegroundColor Green
}

# --- self-heal root CMakeLists NUITKA_FLAGS for recent Nuitka ---
#     (a) '{PROGRAM_BASE}' is rejected mid-string -> use '{PID}'
#     (b) allow Nuitka to auto-download a C backend (Zig) if MSVC/Windows SDK is not usable
$cmakeText = Get-Content $rootCMake -Raw
$orig = $cmakeText
$cmakeText = $cmakeText -replace "onefile_\{PROGRAM_BASE\}", "onefile_{PID}"
if ($cmakeText -match 'set\(NUITKA_FLAGS' -and $cmakeText -notmatch "assume-yes-for-downloads") {
    $cmakeText = $cmakeText -replace '(set\(NUITKA_FLAGS\s+")([^"]*)(")', '$1$2 --assume-yes-for-downloads$3'
}
if ($cmakeText -ne $orig) {
    [System.IO.File]::WriteAllText($rootCMake, $cmakeText, (New-Object System.Text.UTF8Encoding($false)))
    Write-Host "Patched root CMakeLists.txt NUITKA_FLAGS (tempdir spec / allow compiler auto-download)." -ForegroundColor Green
}

# --- configure (force Nx Witness install destinations; -Wno-dev silences CMP0177 dev warnings) ---
Write-Host "Configuring CMake..." -ForegroundColor Cyan
cmake -S $sdkRoot -B $build -Wno-dev "-DINSTALL_DEST_POSTPROCESSORS=$ppDir" "-DINSTALL_DEST_PREPROCESSORS=$preDir"
if ($LASTEXITCODE -ne 0) { Write-Error "cmake configure failed."; exit 1 }

# --- build (Release) ---
Write-Host "Building $PROC (Release)... first build is slow (Nuitka)." -ForegroundColor Cyan
cmake --build $build --target $PROC --config Release
if ($LASTEXITCODE -ne 0) { Write-Error "Build failed."; exit 1 }

# --- Nx Witness service ("Network Optix Media Server"); exclude Nx Meta ("...MetaVMS...") ---
$svc = Get-Service -ErrorAction SilentlyContinue |
       Where-Object { $_.DisplayName -like "*Network Optix*Media Server*" -and $_.DisplayName -notlike "*MetaVMS*" } |
       Select-Object -First 1

# --- stop service + kill any running processor instance, then install ---
# Windows cannot overwrite a running .exe. Stopping the service is not enough: the AI Manager
# runs the post-processor as a CHILD process that can outlive (be orphaned by) the service stop
# and keep the exe locked -> `cmake --install` fails with "Permission denied". So: stop the
# service, wait for it to actually stop, kill any lingering processor process, and wait until the
# target binary is unlocked before installing.
if ($svc) {
    Write-Host "Stopping service '$($svc.DisplayName)'..."
    Stop-Service $svc.Name -Force -ErrorAction SilentlyContinue
    for ($i = 0; $i -lt 40 -and (Get-Service $svc.Name -ErrorAction SilentlyContinue).Status -ne 'Stopped'; $i++) { Start-Sleep -Milliseconds 500 }
}
Get-Process -Name $PROC -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Remove-Item $SocketPath -Force -ErrorAction SilentlyContinue
$targetExe = Join-Path $ppDir "$PROC.exe"
if (Test-Path $targetExe) {
    $unlocked = $false
    for ($i = 0; $i -lt 20; $i++) {
        try { $fs = [System.IO.File]::Open($targetExe, 'Open', 'ReadWrite', 'None'); $fs.Close(); $unlocked = $true; break }
        catch { Start-Sleep -Milliseconds 500 }
    }
    if (-not $unlocked) { Write-Warning "Target exe still locked after 10s; install may fail. Close any running '$PROC' process." }
}

Write-Host "Installing..." -ForegroundColor Cyan
cmake --install $build --component $PROC
if ($LASTEXITCODE -ne 0) {
    if ($svc) { Start-Service $svc.Name }
    Write-Error "Install failed."; exit 1
}

# --- register/merge external_postprocessors.json ---
$exeDest  = Join-Path $ppDir "$PROC.exe"
$jsonPath = Join-Path $ppDir "external_postprocessors.json"
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

# --- restart service ---
if ($svc) {
    Write-Host "Starting service '$($svc.DisplayName)'..."
    Start-Service $svc.Name
} else {
    Write-Warning "Nx Witness Media Server service not found. Restart it manually (services.msc)."
}

Write-Host ""
Write-Host "Done. Next steps:" -ForegroundColor Green
Write-Host "  1. In the NX Desktop Client, open the camera plugin settings -> Nx AI -> select 'Metadata Exporter'."
Write-Host "  2. Enable object tracking in the pipeline (required for 'detect' events)."
Write-Host "  3. Make sure your backend is reachable at: $BackendUrl  (see sample-backend/ to test locally)."
