Audit that `external_postprocessors.json` declarations are consistent with what each post-processor's source code actually does.

## Arguments

`$ARGUMENTS` — (optional) short or full processor name. If omitted, all registered processors are checked.

## Steps

1. **Detect the active NX VMS installation** by running these checks in order, stopping at the first match:
   - `systemctl is-active networkoptix-metavms-mediaserver` → `VMS_BASE=/opt/networkoptix-metavms`
   - `systemctl is-active networkoptix-mediaserver` → `VMS_BASE=/opt/networkoptix`
   - `ls /opt/networkoptix-metavms/mediaserver/var/nx_ai_manager/` exists → use metavms
   - `ls /opt/networkoptix/mediaserver/var/nx_ai_manager/` exists → use witness
   - Neither found → print warning, continue without production path check

3. **Locate** `external_postprocessors.json`. Try the production path first:
   ```
   <VMS_BASE>/mediaserver/var/nx_ai_manager/nxai_manager/postprocessors/external_postprocessors.json
   ```
   If that does not exist, search the repo for any file with that name. Report if neither is found.

4. **Parse** the JSON. If a name argument was given, filter to that processor only.

5. **For each processor**, locate its source directory in the repo by matching the `Name` field or the filename in `Command` against `postprocessor-python-*/` directories. Then read its `.py` file and run these checks:

   | Check | Detect in code | Compare against JSON |
   |-------|---------------|---------------------|
   | **Events** | `add_event("id", ...)` or `{"ID": "id", "Caption": ...}` | IDs in code vs `"Events"[].ID` |
   | **Objects** | `BBoxes_xyxy["id"]` assignments | Keys in code vs `"Objects"[].ID` |
   | **Settings** | `ExternalProcessorSettings.get("key")` or `ExternalProcessorSettings["key"]` | Keys in code vs `"Settings"[].name` |
   | **ReceiveBinaryData** | `BinaryOutputs` referenced | Code usage matches JSON flag |
   | **ReceiveInputTensor** | `SHMKEY` or `SharedMemory` referenced | Code usage matches JSON flag |
   | **Command path** | — | If `Command` is present, the file exists and is executable |

6. **Classify** each check:
   - ✅ **OK** — JSON and code agree
   - ⚠️ **In code, not declared** — processor uses it but JSON doesn't declare it (will be silently dropped by the UI)
   - ℹ️ **Declared, not used** — JSON declares it but code doesn't use it (harmless but noisy)
   - ❌ **Path missing** — `Command` path does not exist on disk

7. **Print** one block per processor:
   ```
   postprocessor-python-<name>
   ─────────────────────────────────────────────
   Events            ✅ OK
   Objects           ⚠️  "car" used in code but not declared in JSON
   Settings          ✅ OK
   ReceiveBinaryData ✅ OK
   Command path      ❌ file not found: /opt/.../postprocessor-python-<name>
   ```

8. For any ⚠️ or ❌ items, **print the exact fix** (e.g. the JSON snippet to add) and offer to apply it.
