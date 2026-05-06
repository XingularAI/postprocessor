Build and install a named post-processor using the project's CMake workflow.

## Arguments

`$ARGUMENTS` — short name (e.g. `vehicle-counter`) or full CMake target name (e.g. `postprocessor-python-vehicle-counter`).

## Steps

1. **Detect the active NX VMS installation** by running these checks in order, stopping at the first match:
   - `systemctl is-active networkoptix-metavms-mediaserver` → `VMS_BASE=/opt/networkoptix-metavms`, `VMS_SERVICE=networkoptix-metavms-mediaserver`
   - `systemctl is-active networkoptix-mediaserver` → `VMS_BASE=/opt/networkoptix`, `VMS_SERVICE=networkoptix-mediaserver`
   - `/opt/networkoptix-metavms/mediaserver/var/nx_ai_manager/` exists → use metavms values
   - `/opt/networkoptix/mediaserver/var/nx_ai_manager/` exists → use witness values
   - Neither found → print error and stop

2. **Determine the CMake target name.** If the argument does not already start with `postprocessor-`, prepend `postprocessor-python-`. Verify the source directory exists; stop with an error if not.

3. **Check the build directory.** If `build/` does not exist at the repo root, or `build/CMakeCache.txt` is missing, run the full configure step first:
   ```shell
   mkdir -p build
   cd build
   python3 -m venv integrationsdk
   source integrationsdk/bin/activate
   cmake ..
   ```

4. **Build** the target:
   ```shell
   cd build && cmake --build . --target <target-name>
   ```
   If it fails, print the last 40 lines of build output and stop.

5. **Install** the target:
   ```shell
   cd build && cmake --install . --component <target-name>
   ```

6. **Fix permissions** on the postprocessors directory:
   ```shell
   sudo chmod -R a+x <VMS_BASE>/mediaserver/var/nx_ai_manager/nxai_manager/postprocessors/
   ```

7. **Ask** the user whether to restart the AI Manager service now. Only run the restart command if the user explicitly confirms:
   ```shell
   sudo service <VMS_SERVICE> restart
   ```

8. **Print** the installed binary path and the socket path the processor will listen on (read `Postprocessor_Socket_Path` from the `.py` file, or the `SocketPath` from its JSON entry if available).
