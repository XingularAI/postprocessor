Find and display the log file for a running post-processor.

## Arguments

`$ARGUMENTS` — short name (e.g. `vehicle-counter`) or full processor name (e.g. `postprocessor-python-vehicle-counter`).

## Background

Post-processors write logs to a file named `plugin.<shortname>.log`. The location depends on how the processor was started:

- **Production** (started by the AI Manager): the binary lives in `.../postprocessors/`, so `../etc/` resolves to:
  ```
  <VMS_BASE>/mediaserver/var/nx_ai_manager/nxai_manager/etc/
  ```
  where `VMS_BASE` is `/opt/networkoptix-metavms` (NX Meta) or `/opt/networkoptix` (NX Witness).
- **Dev mode** (started manually from the source directory): the fallback path puts the log in the same directory as the script, e.g. `postprocessor-python-<name>/plugin.<shortname>.log`.

The short name embedded in the filename is not always predictable — e.g. `postprocessor-python-edgeimpulse-example` uses `plugin.cloud-edgeimpulse.log`. Read the `LOG_FILE` assignment in the processor's `.py` file to determine the exact name.

## Steps

1. **Detect the active NX VMS installation** by running these checks in order, stopping at the first match:
   - `systemctl is-active networkoptix-metavms-mediaserver` → `VMS_BASE=/opt/networkoptix-metavms`
   - `systemctl is-active networkoptix-mediaserver` → `VMS_BASE=/opt/networkoptix`
   - `/opt/networkoptix-metavms/mediaserver/var/nx_ai_manager/` exists → use metavms
   - `/opt/networkoptix/mediaserver/var/nx_ai_manager/` exists → use witness
   - Neither found → skip the production path search, check only dev-mode paths

2. **Determine the short log name** by reading the `LOG_FILE` assignment in the processor's `.py` file. Extract the filename (e.g. `plugin.events.log`).

3. **Search for the log file** in order of likelihood:
   ```shell
   # Production path
   <VMS_BASE>/mediaserver/var/nx_ai_manager/nxai_manager/etc/<logfile>

   # Dev mode: script directory
   postprocessor-python-<name>/<logfile>

   # Dev mode: working directory fallback
   ./<logfile>
   ```

4. **If found**, print the last 50 lines and offer to tail it live:
   ```shell
   tail -n 50 <path>
   ```
   For live tailing suggest the user run in their terminal:
   ```shell
   tail -f <path>
   ```

5. **If not found**, print:
   ```
   ⚠️  No log file found for postprocessor-python-<name>.

   Expected filename: <logfile>
   Searched:
     <VMS_BASE>/.../nxai_manager/etc/<logfile>      (production)
     postprocessor-python-<name>/<logfile>    (dev mode, script dir)

   The processor may not have run yet, or it may have started with a
   different working directory. Check the LOG_FILE variable in:
     postprocessor-python-<name>/postprocessor-python-<name>.py
   ```

6. **Also check** for the AI Manager's own log, which captures processor startup errors:
   ```shell
   <VMS_BASE>/mediaserver/var/log/log_file.log
   ```
   Search it for lines containing the processor name and print any found.
