# Deploy postprocessor-python-metadata-exporter to another Windows laptop

Move the **already-built** post-processor to another Windows machine **without
rebuilding**. The `.exe` is a Nuitka one-file build (it bundles Python and all
Python deps), so the target needs **no Python and no Visual Studio** — only the
VC++ runtime and, of course, NX AI Manager itself.

> **These scripts target Nx Witness** (`Network Optix Media Server`) by default — **not** Nx Meta.
> For Nx Meta or a custom layout, pass `-NxPostprocessorsDir "<path>"` to `2-deploy.ps1`.

## Folder contents

| Item | Purpose |
|------|---------|
| `1-package.ps1` | Run on the **source** laptop — collects the 3 files into `payload/`. |
| `2-deploy.ps1` | Run on the **target** laptop (Administrator) — installs + registers everything. |
| `external_postprocessors.entry.json` | Reference registration entry (for manual merge). |
| `payload/` | Where the prebuilt files land (filled by `1-package.ps1`). |

## Target prerequisites

- **Nx Witness + AI Manager installed**, with a camera AI pipeline and **object tracking
  enabled** (required for `detect` events).
- **Same architecture (x64)** as the source.
- VC++ x64 runtime — `2-deploy.ps1` installs it automatically via winget if missing.

## Steps

### A. On the SOURCE laptop

```powershell
cd "<repo>\postprocessor-python-metadata-exporter\deploy"
powershell -ExecutionPolicy Bypass -File .\1-package.ps1
```

This copies the exe, dll and ini into `payload/`.

### B. Carry the folder over

Copy the whole `deploy` folder (with the filled `payload/`) to the target laptop.

### C. On the TARGET laptop (Administrator)

```powershell
cd <path-to-copied-deploy-folder>
powershell -ExecutionPolicy Bypass -File .\2-deploy.ps1
# or set the backend URL default shown in the NX UI:
powershell -ExecutionPolicy Bypass -File .\2-deploy.ps1 -BackendUrl "http://192.168.1.50:8000/ingest"
```

`2-deploy.ps1` will:

1. Ensure the VC++ x64 runtime is present (install via winget if missing).
2. Use the **Nx Witness** postprocessors folder (override with `-NxPostprocessorsDir "<path>"`
   for Nx Meta or a custom layout).
3. Stop the mediaserver, copy `exe`+`dll` → `postprocessors/`, `ini` → `etc/`.
4. Merge/create `external_postprocessors.json` (backs up any existing file to `.bak`;
   an entry named `Metadata Exporter` is replaced, other processors are kept).
5. Restart the mediaserver.

### D. Finish in the NX Client

1. Open the camera plugin settings → **Nx AI** → select **Metadata Exporter**.
2. Ensure **object tracking** is enabled in the pipeline.
3. Make sure the backend is reachable at the configured **Backend URL**.

## Manual alternative (no scripts)

1. Install "Microsoft Visual C++ 2015-2022 Redistributable (x64)".
2. Copy `payload\postprocessor-python-metadata-exporter.exe` and `payload\nxai-c-utilities-shared.dll`
   into `...\nx_ai_manager\nxai_manager\postprocessors\`.
3. Copy `payload\plugin.metadata-exporter.ini` into the sibling `...\nx_ai_manager\nxai_manager\etc\`.
4. Merge `external_postprocessors.entry.json` into that folder's `external_postprocessors.json`.
5. Restart the service: `Restart-Service "Network Optix Media Server"`, then select the processor
   in the pipeline.

## Notes & gotchas

- **Targets Nx Witness by default.** The scripts use the `...\Network Optix Media Server\...`
  path and the Nx Witness service (the Nx Meta / `MetaVMS` service is explicitly excluded). For
  Nx Meta or a custom layout, pass `-NxPostprocessorsDir` and adjust the `Command` path in the JSON.
  The `Command` path and the install folder must belong to the same product.
- **DLL must be Release.** A Debug build needs the non-redistributable debug CRT and will fail
  with "...or one of its dependencies".
- **Antivirus** sometimes flags Nuitka one-file exes — if the exe is quarantined, add a Windows
  Defender exclusion for the postprocessors folder.
- **Backend reachability.** `127.0.0.1` only works if the backend runs on the target itself.
  For a remote backend use its IP and open the port in Windows Firewall.
- **Verify quickly** on the target: run the exe once with the socket path
  (`postprocessor-python-metadata-exporter.exe "C:\Windows\Temp\metadata-exporter.sock"`) — it should
  print `Listening on ...`. If it errors on a missing DLL, the VC++ runtime is not installed.
