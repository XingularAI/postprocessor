Scaffold a new Python post-processor for the NX AI Integration SDK.

## Arguments

`$ARGUMENTS` — format: `<name> [type]`

- **name**: short name, e.g. `vehicle-counter`. Directory and file will be named `postprocessor-python-<name>`.
- **type** (optional, default: `simple`):

  | type | purpose | template |
  |------|---------|----------|
  | `simple` | Modify bounding boxes | `postprocessor-python-example` |
  | `events` | Emit events | `postprocessor-python-events-example` |
  | `settings` | Expose UI settings | `postprocessor-python-settings-example` |
  | `binary` | Consume raw model output tensors | `postprocessor-python-anpr-example` |
  | `noresponse` | Fire-and-forget side effect | `postprocessor-python-noresponse-example` |
  | `image` | Read the raw input image | `postprocessor-python-image-example` |

## Steps

1. **Parse** name and type from the arguments. If the name already starts with `postprocessor-python-`, strip that prefix before re-applying it.

2. **Check for an existing directory.** If `postprocessor-python-<name>/` already exists, stop immediately and print:
   ```
   ❌ postprocessor-python-<name>/ already exists. Choose a different name or delete it first.
   ```

3. **Confirm** before touching anything: print the full processor name, the chosen type, and the template being used.

4. **Create the processor directory** `postprocessor-python-<name>/`.

5. **Create the Python script** `postprocessor-python-<name>/postprocessor-python-<name>.py`:
   - Read the template `.py` file.
   - Replace every occurrence of the template's base name (e.g. `postprocessor-python-example`) with `postprocessor-python-<name>`.
   - Set `Postprocessor_Name` to a human-readable title, e.g. `"Python-<Name>-Postprocessor"`.
   - Update the default socket path to `/tmp/<name>-postprocessor.sock`.
   - Update the log/config file paths to `plugin.<name>.log` and `plugin.<name>.ini`.
   - Inside the main loop, immediately after the `ExitSignal` check, add:
     ```python
     # TODO: add your processing logic here
     ```
   - If type is `binary` (anpr template): remove the ANPR-specific imports, `OcrCache`, `EventDeduplicationCache`, worker pool setup, and OCR decoding logic. Replace the body of the main loop (after ExitSignal) with a comment block:
     ```python
     # TODO: read raw model outputs from input_object["BinaryOutputs"]
     # Each entry has: {"Name": str, "Type": int (dtype code), "Data": bytes}
     # See .claude/docs/input_from_ai_manager.md for dtype codes.
     ```
     Keep the socket, parse, ExitSignal check, writeInferenceResults, and send structure intact.

6. **Create `CMakeLists.txt`** `postprocessor-python-<name>/CMakeLists.txt`:
   - Read the template's `CMakeLists.txt`.
   - Replace the `PROCESSOR_NAME` value with `postprocessor-python-<name>`.
   - Leave everything else unchanged.

7. **Create `requirements.txt`**:
   - If the template has a `requirements.txt`, copy it verbatim.
   - Otherwise create a minimal one containing only `msgpack`.

8. **Wire into root `CMakeLists.txt`**: insert
   ```cmake
   add_subdirectory(${CMAKE_CURRENT_SOURCE_DIR}/postprocessor-python-<name>)
   ```
   after the last existing Python postprocessor `add_subdirectory` line (before the preprocessor entries).

9. **Print a summary**:
   ```
   Created postprocessor-python-<name>/
     postprocessor-python-<name>.py   ← add your logic at the TODO
     CMakeLists.txt
     requirements.txt

   Next steps:
   1. Edit the .py file — search for "TODO" to find where to add logic.
   2. Run /register-processor <name> to generate the JSON registration entry.
   3. Declare any new event IDs or object class names in that JSON before restarting.
   4. Run /install-processor <name> to build and install.
   ```
