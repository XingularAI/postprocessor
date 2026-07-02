<#
    1-package.ps1  —  RUN ON THE SOURCE LAPTOP (the one where it was built).

    Collects the 3 files needed on the target into .\payload\ :
      - postprocessor-python-metadata-exporter.exe   (Nuitka one-file exe; self-contained)
      - nxai-c-utilities-shared.dll         (native helper; must sit next to the exe)
      - plugin.metadata-exporter.ini                 (config; goes into the target's etc/ folder)

    It looks in the installed Nx Witness folders first, then falls back to the build tree.
    After it finishes, carry the whole 'deploy' folder to the target laptop.
#>

$ErrorActionPreference = "Stop"

$deployDir = $PSScriptRoot
$payload   = Join-Path $deployDir "payload"
$pluginDir = Split-Path $deployDir -Parent          # postprocessor-python-metadata-exporter
$sdkRoot   = Split-Path $pluginDir -Parent          # repo root
New-Item -ItemType Directory -Force $payload | Out-Null

function Find-First([string[]]$paths) {
    foreach ($p in $paths) { if ($p -and (Test-Path $p)) { return (Get-Item $p).FullName } }
    return $null
}

# --- installed Nx Witness postprocessors / etc folders (source of the built files) ---
$ppDir = $null; $etcDir = $null
$witnessPP = "C:\Windows\System32\config\systemprofile\AppData\Local\Network Optix\Network Optix Media Server\nx_ai_manager\nxai_manager\postprocessors"
if (Test-Path $witnessPP) { $ppDir = $witnessPP; $etcDir = Join-Path (Split-Path $ppDir -Parent) "etc" }

# --- locate each file (installed first, then build tree) ---
$exeCands = @()
if ($ppDir) { $exeCands += (Join-Path $ppDir "postprocessor-python-metadata-exporter.exe") }
$exeCands += (Join-Path $sdkRoot "build\postprocessor-python-metadata-exporter\postprocessor-python-metadata-exporter.exe")
$exe = Find-First $exeCands

$dllCands = @()
if ($ppDir) { $dllCands += (Join-Path $ppDir "nxai-c-utilities-shared.dll") }
$buildDll = Get-ChildItem (Join-Path $sdkRoot "build") -Recurse -Filter "nxai-c-utilities-shared.dll" -ErrorAction SilentlyContinue |
            Where-Object { $_.FullName -match "\\Release\\" } |
            Select-Object -First 1 -ExpandProperty FullName
if ($buildDll) { $dllCands += $buildDll }
$dll = Find-First $dllCands

$iniCands = @()
if ($etcDir) { $iniCands += (Join-Path $etcDir "plugin.metadata-exporter.ini") }
$iniCands += (Join-Path $pluginDir "plugin.metadata-exporter.ini")
$ini = Find-First $iniCands

# --- copy into payload ---
if (-not $exe) { Write-Error "Could not find postprocessor-python-metadata-exporter.exe (installed or in build\). Build/install it first."; exit 1 }
if (-not $dll) { Write-Error "Could not find a Release nxai-c-utilities-shared.dll. Build it first (--config Release)."; exit 1 }

Copy-Item $exe $payload -Force
Copy-Item $dll $payload -Force
if ($ini) { Copy-Item $ini $payload -Force } else { Write-Warning "plugin.metadata-exporter.ini not found; target will use code defaults unless you add it." }

Write-Host ""
Write-Host "Packaged into: $payload" -ForegroundColor Green
Get-ChildItem $payload | Select-Object Name, Length, LastWriteTime | Format-Table -AutoSize
Write-Host "NOTE: the DLL must be a Release build (Debug needs the non-redistributable debug CRT)." -ForegroundColor Yellow
Write-Host "Next: copy the whole 'deploy' folder to the target laptop and run 2-deploy.ps1 there (as Administrator)."
