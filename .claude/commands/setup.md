Set up the development environment for the NX AI Integration SDK from scratch. Run this once on a fresh machine or after cloning the repo.

## Steps

### 1. Identify the installed NX VMS and detect active product

This SDK supports **NX Meta** (`networkoptix-metavms`) and **NX Witness** (`networkoptix`). The install paths differ only in the base directory. Other Network Optix-based products (DW Spectrum, Hanwha Wisenet WAVE, etc.) are not supported — they use different paths and package names.

**a. Check for unsupported products first**
```shell
dpkg -l | grep -E "digitalwatchdog|hanwha|wisenet|dwspectrum"
```
If any match is found, stop and print:
```
❌ Unsupported VMS detected: <package name>
   This SDK supports networkoptix-metavms (NX Meta) and networkoptix (NX Witness) only.
```

**b. Detect which NX product is active** — run these checks in order and stop at the first match:

1. `systemctl is-active networkoptix-metavms-mediaserver` → if active, set `VMS_BASE=/opt/networkoptix-metavms`, `VMS_SERVICE=networkoptix-metavms-mediaserver`, `VMS_NAME="NX Meta"`
2. `systemctl is-active networkoptix-mediaserver` → if active, set `VMS_BASE=/opt/networkoptix`, `VMS_SERVICE=networkoptix-mediaserver`, `VMS_NAME="NX Witness"`
3. `ls /opt/networkoptix-metavms/mediaserver/var/nx_ai_manager/` → if exists, use metavms values above
4. `ls /opt/networkoptix/mediaserver/var/nx_ai_manager/` → if exists, use witness values above
5. None found → print warning and continue (build steps still work without a VMS install):
   ```
   ⚠️  No NX VMS installation found.
       Build steps will work, but registration and install steps require it.
       Set VMS_BASE=/opt/networkoptix-metavms or /opt/networkoptix manually if needed.
   ```

Print the detected product:
```
✅ Detected: NX Meta  →  /opt/networkoptix-metavms  (service: networkoptix-metavms-mediaserver)
```
or
```
✅ Detected: NX Witness  →  /opt/networkoptix  (service: networkoptix-mediaserver)
```

Use `VMS_BASE` and `VMS_SERVICE` for all paths in the remaining steps.

### 2. Check the submodule

Verify that `nxai-utilities/` is populated (it is a git submodule — without it nothing imports):

```shell
ls nxai-utilities/python-utilities/
```

If the directory is empty or missing, initialize it:

```shell
git submodule update --init --recurse
```

Report if this succeeds or fails and stop on failure.

### 3. Install system dependencies

Check whether each required package is already installed before running apt:

```shell
cmake --version
g++ --version
python3 --version
pip3 --version
python3 -m venv --help
patchelf --version
```

Install any that are missing:

```shell
sudo apt install cmake g++ python3-pip python3-venv patchelf
```

### 4. Configure the build directory

If `build/` does not exist or `build/CMakeCache.txt` is missing, run the full configure sequence:

```shell
mkdir -p build
cd build
python3 -m venv integrationsdk
source integrationsdk/bin/activate
cmake ..
```

If CMakeCache.txt already exists, skip this step and tell the user the build is already configured.

### 5. Check that the NX AI Manager is present

Verify the postprocessors directory exists at the detected `VMS_BASE`:

```shell
ls <VMS_BASE>/mediaserver/var/nx_ai_manager/nxai_manager/postprocessors/
```

If it does not exist, print this warning and continue:

```
⚠️  The NX AI Manager postprocessors directory was not found under <VMS_BASE>.
    The AI Manager must be installed before processors can be registered or run.
    Re-run /setup after installing the mediaserver package.
```

### 6. Ensure the postprocessors directory is executable

If the directory exists:

```shell
sudo chmod -R a+x <VMS_BASE>/mediaserver/var/nx_ai_manager/nxai_manager/postprocessors/
```

### 7. Create `external_postprocessors.json` if it does not exist

Path: `<VMS_BASE>/mediaserver/var/nx_ai_manager/nxai_manager/postprocessors/external_postprocessors.json`

If the file is absent, create it with an empty array:

```json
{
    "externalPostprocessors": []
}
```

If it already exists, leave it untouched and report its current content.

### 8. Print a summary and next steps

```
✅ VMS:             <VMS_NAME> (<VMS_BASE>)
✅ Submodule:       nxai-utilities/ populated
✅ System packages: cmake, g++, python3, pip3, python3-venv, patchelf
✅ Build dir:       build/ configured (CMakeCache.txt present)
✅ AI Manager dir:  found
✅ Permissions:     postprocessors/ executable
✅ JSON file:       external_postprocessors.json ready

You're set up. Typical next steps:

  /new-processor <name> [type]     — scaffold a new post-processor
  /register-processor <name>       — generate its JSON registration entry
  /install-processor <name>        — build and install it
  /check-registration              — verify JSON matches source code

Development shortcut (no build needed):
  Omit "Command" from the JSON entry, start the .py script manually,
  and the AI Manager will connect to it immediately.
  See .claude/docs/external_postprocessors_json.md for details.
```
