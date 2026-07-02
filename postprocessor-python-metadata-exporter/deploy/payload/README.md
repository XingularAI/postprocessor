# payload/

Holds the prebuilt files copied to the target laptop. Filled automatically by
[`../1-package.ps1`](../1-package.ps1) (run on the **source** laptop):

- `postprocessor-python-metadata-exporter.exe` — Nuitka one-file exe (self-contained, no Python needed)
- `nxai-c-utilities-shared.dll` — native helper (Release build; goes next to the exe)
- `plugin.metadata-exporter.ini` — config (goes into the target's `etc/` folder)

The `.exe` and `.dll` are build artifacts (binaries), so they are not committed here —
run `1-package.ps1` to populate this folder before carrying it to the target.
