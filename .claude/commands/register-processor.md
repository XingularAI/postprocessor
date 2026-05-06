Generate the `external_postprocessors.json` registration entry for an existing post-processor by inspecting its source code.

## Arguments

`$ARGUMENTS` — short name (e.g. `vehicle-counter`) or full directory name (e.g. `postprocessor-python-vehicle-counter`).

## Steps

1. **Detect the active NX VMS installation** by running these checks in order, stopping at the first match:
   - `systemctl is-active networkoptix-metavms-mediaserver` → `VMS_BASE=/opt/networkoptix-metavms`
   - `systemctl is-active networkoptix-mediaserver` → `VMS_BASE=/opt/networkoptix`
   - `/opt/networkoptix-metavms/mediaserver/var/nx_ai_manager/` exists → use metavms
   - `/opt/networkoptix/mediaserver/var/nx_ai_manager/` exists → use witness
   - Neither found → set `VMS_BASE=/opt/networkoptix-metavms` as a placeholder (the snippet will still be correct once the VMS is installed)

2. **Locate** the processor directory. Try `postprocessor-python-<name>/` first, then the literal argument.

3. **Read** the main `.py` file.

4. **Detect** what the processor needs by scanning the source:

   | Flag | Detect when |
   |------|-------------|
   | `ReceiveBinaryData: true` | `BinaryOutputs` appears in the code |
   | `ReceiveInputTensor: true` | `SHMKEY` or `SharedMemory` appears |
   | `ReceiveConfidenceData: true` | `Confidences` is read from `ObjectsMetaData` |
   | `NoResponse: true` | `return_data = False` is set, or there is no `connection.send(` call |

   **Objects** — all string literals used as keys in `BBoxes_xyxy["..."]` assignments.

   **Events** — all string literals appearing as the first argument of `add_event(` calls, or as `"ID":` values inside dicts that also contain a `"Caption":` key.

   **Settings** — all string literals accessed via `ExternalProcessorSettings.get("..."` or `ExternalProcessorSettings["..."`.

5. **Read** the `Postprocessor_Socket_Path` assignment in the script to determine the socket path. Fall back to `/tmp/<name>-postprocessor.sock` if not found.

6. **Generate** the JSON snippet. Omit boolean flags that are `false` (the default). Omit empty arrays.

   ```json
   {
       "Name": "<Name>-Postprocessor",
       "Command": "<VMS_BASE>/mediaserver/var/nx_ai_manager/nxai_manager/postprocessors/postprocessor-python-<name>",
       "SocketPath": "<detected socket path>",
       <detected flags>,
       "Objects": [ { "ID": "<id>", "Name": "<Human Name>" } ],
       "Events":  [ { "ID": "<id>", "Name": "<Human Name>" } ]
   }
   ```

   For `Objects` and `Events`, derive `Name` from the ID by title-casing the last dot-separated segment (e.g. `anpr.plate_recognized` → `Plate Recognized`).

7. **Print** the snippet and this reminder:

   ```
   Add this entry inside the "externalPostprocessors": [...] array in:
     <VMS_BASE>/mediaserver/var/nx_ai_manager/nxai_manager/postprocessors/external_postprocessors.json

   Development mode (no build needed): omit the "Command" field and start the processor manually.
   The AI Manager will send data to the socket and assume the process is already running.

   After editing the JSON:
     sudo chmod -R a+x <VMS_BASE>/mediaserver/var/nx_ai_manager/nxai_manager/postprocessors/
     sudo service <VMS_SERVICE> restart
   ```
