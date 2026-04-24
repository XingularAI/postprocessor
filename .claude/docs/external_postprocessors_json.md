# `external_postprocessors.json` — Reference

This file is how you tell the NX AI Manager that an external post-processor exists, how to start it, and how to connect to it. Without an entry here, your compiled post-processor is invisible to the AI Manager.

An analogous `external_preprocessors.json` does the same for preprocessors. Most fields are shared; differences are called out at the end of this document.

---

## Where the file lives

**Linux**

```
/opt/networkoptix-metavms/mediaserver/var/nx_ai_manager/nxai_manager/postprocessors/external_postprocessors.json
```

**Windows**

```
C:\Windows\System32\config\systemprofile\AppData\Local\Network Optix\Network Optix MetaVMS Media Server\nx_ai_manager\nxai_manager\postprocessors\external_postprocessors.json
```

(Preprocessors live in a sibling `preprocessors/` directory with a file named `external_preprocessors.json`.)

The file must be readable by the mediaserver. After creating or editing it you also need to make sure the `postprocessors/` directory and the binaries inside it are executable:

```shell
sudo chmod -R a+x /opt/networkoptix-metavms/mediaserver/var/nx_ai_manager/nxai_manager/postprocessors/
```

Changes take effect only after restarting the mediaserver:

```shell
sudo service networkoptix-metavms-mediaserver restart
```

---

## File shape

The root object has a single key — `externalPostprocessors` — whose value is an array of processor definitions.

```json
{
    "externalPostprocessors": [
        { /* processor 1 */ },
        { /* processor 2 */ }
    ]
}
```

Each element in the array describes one external post-processor.

---

## Per-processor fields

The following table lists every field that appears in the SDK's example definitions, grouped by purpose. "Required" means the AI Manager needs it to route data; "optional" fields default to `false` for booleans and to absent/empty otherwise.

### Identity and transport

- **`Name`** (string, required) — A human-readable identifier shown in the NX Cloud Pipelines UI. This is how the user selects the processor in a pipeline. It does not need to match the binary filename.
- **`Command`** (string, optional in development, required in production) — Absolute path to the post-processor executable. The AI Manager starts this program when the mediaserver boots and terminates it on shutdown. **During development, omit this field entirely** — the AI Manager will then assume the process is already running and just send data to it (see "The development pattern" below).
- **`SocketPath`** (string, required) — Unix socket path (Linux) or named pipe path (Windows) where the post-processor listens and the AI Manager connects. This is also passed as the **first command-line argument** to the binary when `Command` is present, so the processor should prefer reading it from `argv[1]` rather than hardcoding it. See `postprocessor-python-example/postprocessor-python-example.py` for the canonical pattern.

### What the processor receives

These booleans extend the default inference-results message with additional data. All default to `false`.

- **`ReceiveInputTensor`** (bool) — When `true`, after the inference-results message the AI Manager sends a second message containing an image header with a shared-memory key. The processor can then read the raw input image via shared memory. See `postprocessor-python-image-example/` for the worked example.
- **`ReceiveBinaryData`** (bool) — When `true`, the inference-results message includes a `BinaryOutputs` array with the raw model output tensors (name, dtype, binary blob). Used when the processor needs the model's raw logits or embeddings. See `postprocessor-c-raw-example/` and `postprocessor-python-anpr-example/`.
- **`ReceiveConfidenceData`** (bool) — When `true`, per-object confidences are included in `ObjectsMetaData.<class>.Confidences`. See `postprocessor-python-confidences-example/`.

### Response behavior

- **`NoResponse`** (bool, default `false`) — When `true`, the AI Manager does not wait for a response. The processor is expected to consume the message and stay silent. Useful for fire-and-forget side effects like uploading to an external system. See `postprocessor-python-noresponse-example/` and `postprocessor-python-edgeimpulse-example/`.
- **`RunLast`** (bool, default `false`) — When `true`, this processor runs after all other post-processors in the pipeline. Use when the processor depends on outputs produced by the others.

### UI declarations

These fields let the processor declare things that must exist in the UI before the processor tries to use them. They affect the plugin settings dialog and how outputs are rendered, but they don't change the data the processor receives on the socket.

- **`Objects`** (array of `{ID, Name}`, optional) — Declares new class names the processor may add to `BBoxes_xyxy` or `ObjectsMetaData` in its response. Without this, any new classes the processor introduces will be dropped by the UI. Example from `postprocessor-python-example/README.md`:

  ```json
  "Objects": [
      { "ID": "test", "Name": "Test" }
  ]
  ```

- **`Events`** (array of `{ID, Name}`, optional) — Declares event IDs the processor may emit in the `Events` field of its response. Required for any event to surface in the NX event system. Example from `postprocessor-python-anpr-example/README.md`:

  ```json
  "Events": [
      { "ID": "anpr.plate_recognized", "Name": "Plate Recognized" }
  ]
  ```

- **`Settings`** (array, optional) — An inline Settings Model. Each entry is a UI control (TextField, SpinBox, CheckBox, ComboBox, PolygonFigure, etc.) that will appear in the NX plugin settings dialog for this processor. The user's selected values are delivered to the processor every frame in the `ExternalProcessorSettings` map inside the inference-results message. Setting names are conventionally prefixed `externalprocessor.` so they don't collide with other sources. Example:

  ```json
  "Settings": [
      {
          "type": "TextField",
          "name": "externalprocessor.attributeName",
          "caption": "Attribute Name",
          "description": "The name of the example attribute",
          "defaultValue": "Key"
      }
  ]
  ```

  The full list of control types and their JSON shape is documented in `postprocessor-python-settings-example/settings_model.md`. It includes TextField, PasswordField, SpinBox, DoubleSpinBox, ComboBox, RadioButtonGroup, CheckBox, CheckBoxGroup, SwitchButton, Link, Banner, Placeholder, PolygonFigure, BoxFigure, LineFigure, ObjectSizeConstraints, Button, and structural elements (Settings, Section, GroupBox, Separator, Repeater).

### Preprocessor-only

- **`Schedule`** (string, preprocessor-only) — Either `"IMAGE"` or `"TENSOR"`. Controls at which stage the preprocessor is invoked. `IMAGE` runs on the raw frame before any resizing/normalization; `TENSOR` runs after the frame has been converted into the model's input tensor. Documented in `preprocessor-python-tensor-example/README.md`.

---

## The development pattern: omit `Command`

For fast iteration, leave `Command` out of the entry entirely:

```json
{
    "Name": "My-Postprocessor",
    "SocketPath": "/tmp/my-postprocessor.sock",
    "ReceiveInputTensor": false
}
```

The AI Manager will not try to start your binary. Instead, it will send data each frame and wait on the socket. You start your processor manually from a terminal, iterate as needed, kill it, start it again. Once you're happy, add `Command` back and let the AI Manager manage the lifecycle. This pattern is described in the root `README.md` under "Development".

---

## Worked example

The following file registers five post-processors and exercises most of the optional fields:

```json
{
    "externalPostprocessors": [
        {
            "Name": "EI-Upload-Postprocessor",
            "Command": "/opt/networkoptix-metavms/mediaserver/var/nx_ai_manager/nxai_manager/postprocessors/postprocessor-python-edgeimpulse-example",
            "SocketPath": "/tmp/python-edgeimpulse-postprocessor.sock",
            "ReceiveInputTensor": true,
            "RunLast": false,
            "NoResponse": true
        },
        {
            "Name": "Example-Postprocessor",
            "Command": "/opt/networkoptix-metavms/mediaserver/var/nx_ai_manager/nxai_manager/postprocessors/postprocessor-python-example",
            "SocketPath": "/tmp/python-example-postprocessor.sock",
            "ReceiveInputTensor": false,
            "Objects": [
                { "ID": "test", "Name": "Test" }
            ]
        },
        {
            "Name": "Image-Postprocessor",
            "Command": "/opt/networkoptix-metavms/mediaserver/var/nx_ai_manager/nxai_manager/postprocessors/postprocessor-python-image-example",
            "SocketPath": "/tmp/python-image-postprocessor.sock",
            "ReceiveInputTensor": true
        },
        {
            "Name": "NoResponse-Postprocessor",
            "Command": "/opt/networkoptix-metavms/mediaserver/var/nx_ai_manager/nxai_manager/postprocessors/postprocessor-python-noresponse-example",
            "SocketPath": "/tmp/python-noresponse-postprocessor.sock",
            "ReceiveInputTensor": false,
            "ReceiveBinaryData": false,
            "NoResponse": true
        },
        {
            "Name": "ANPR-Example",
            "Command": "/opt/networkoptix-metavms/mediaserver/var/nx_ai_manager/nxai_manager/postprocessors/postprocessor-python-anpr-example",
            "SocketPath": "/tmp/postprocessor-anpr-example.sock",
            "ReceiveBinaryData": true,
            "Events": [
                { "ID": "anpr.plate_recognized", "Name": "Plate Recognized" }
            ]
        }
    ]
}
```

Taken together, this file wires up a silent uploader, a simple bounding-box adder, an image-reading processor, a silent inspector, and an event-producing ANPR processor.

---

## Preprocessor equivalent: `external_preprocessors.json`

Preprocessors use a near-identical schema. The root key is `externalPreprocessors`, the file lives in the sibling `preprocessors/` directory, and the per-entry fields are the same as above with two differences:

- `Schedule` (`"IMAGE"` or `"TENSOR"`) is required and controls when the preprocessor runs in the pipeline.
- `ReceiveInputTensor` / `ReceiveBinaryData` / `NoResponse` / `RunLast` / `Events` are typically not used.

Minimal example:

```json
{
    "externalPreprocessors": [
        {
            "Name": "Example-Preprocessor",
            "Command": "/opt/networkoptix-metavms/mediaserver/var/nx_ai_manager/nxai_manager/preprocessors/preprocessor-python-example",
            "SocketPath": "/tmp/example-preprocessor.sock",
            "Schedule": "IMAGE"
        }
    ]
}
```

---

## Checklist before restarting the server

- File parses as valid JSON (a single trailing comma will break the whole file).
- `Command` path exists and is executable (`chmod +x`), or is intentionally omitted for iteration.
- `SocketPath` is writable by the mediaserver and not already in use by another processor.
- Every class name you plan to add to `BBoxes_xyxy` in your response is listed in `Objects`.
- Every event ID you plan to emit is listed in `Events`.
- If you set `ReceiveInputTensor: true`, your processor reads a second MessagePack message per frame (the image header) before responding.
- If you set `ReceiveBinaryData: true`, your processor knows how to handle the extra `BinaryOutputs` array in the inference-results message.
- Restart: `sudo service networkoptix-metavms-mediaserver restart`. The processor's name should appear in the NX Cloud Pipelines UI.

---

## Evidence in the repo

- Root field list and worked multi-processor file: `README.md` (sections "Defining the pre/postprocessors" and "Development").
- Per-field semantics: `postprocessor-python-example/README.md`, `postprocessor-c-raw-example/README.md`, `postprocessor-python-noresponse-example/README.md`.
- `Objects` and `Events` declarations: `postprocessor-python-example/README.md`, `postprocessor-python-anpr-example/README.md`.
- `Settings` and the full Settings Model grammar: `postprocessor-python-settings-example/README.md` and `postprocessor-python-settings-example/settings_model.md`.
- `Schedule` (preprocessors): `preprocessor-python-tensor-example/README.md`, `preprocessor-python-image-example/README.md`.
