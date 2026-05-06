# What the Post-processor Receives from the AI Manager

This document describes everything a post-processor can be handed each frame. A post-processor is a long-running program that listens on a Unix/named-pipe socket and, for each frame, reads one or two MessagePack-encoded messages from the AI Manager.

For Python processors, unpacking is handled by `nxai_communication_utils.parseInferenceResults()` in the `nxai-utilities` submodule. For C processors, the `mpack` library is used directly against the fields documented below.

---

## Transport

- **Format:** MessagePack over socket. The socket path is passed to the processor as `argv[1]` when the AI Manager starts it.
- **Framing:** Each message is one complete MessagePack document. Helpers in `nxai-utilities` handle length-prefix framing so most processors don't need to think about it.
- **Connection lifecycle:** The AI Manager opens one socket per frame, writes the message(s), waits for the response (unless `NoResponse: true`), and closes.

---

## Messages per frame

The AI Manager sends **one or two** MessagePack messages per frame:

1. **Inference results** (always sent). The primary payload containing bounding boxes, scores, metadata, and — if requested — raw model outputs.
2. **Image header** (sent only when `ReceiveInputTensor: true` in the processor's JSON entry). A small MessagePack map with a shared-memory key that points at the raw input tensor.

The processor must read all expected messages before sending its response. See `postprocessor-python-image-example/postprocessor-python-image-example.py` for the canonical two-message loop.

---

## Exit signal

Before sending any frame data, the AI Manager may send a termination message. Every processor must check for it first:

```json
{ "EXIT": <value> }
```

The value does not matter — only the presence of the `EXIT` key. The Python helper returns an `ExitSignal` sentinel when this is seen (`nxai_communication_utils.py:560`). In C, it's detected with `mpack_node_map_cstr_optional(..., "EXIT")` (see `postprocessor-c-example/src/main.c:115`).

On receipt of an exit signal the processor should close the connection and terminate its main loop.

---

## Message 1: inference results

The full schema, expressed as JSON for readability. All fields are optional — which fields are present depends on the model selected in the pipeline and on the processor's JSON flags.

```json
{
    "DeviceID": "<Device ID>",
    "DeviceName": "<Device Name>",
    "Timestamp": <uint64>,
    "InputIndex": <uint32>,
    "Width": <uint32>,
    "Height": <uint32>,
    "BBoxes_xyxy": {
        "<Class Name>": <packed float32 array>
    },
    "ObjectsMetaData": {
        "<Class Name>": {
            "ObjectIDs":       [<16-byte UUID>, ...],
            "AttributeKeys":   [[<string>, ...], ...],
            "AttributeValues": [[<string>, ...], ...],
            "Confidences":     [<float>, ...]
        }
    },
    "Scores": {
        "<Class Name>": <float>
    },
    "Counts": {
        "<Class Name>": <uint32>
    },
    "BinaryOutputs": [
        {
            "Name": "<tensor name>",
            "Type": <uint8 dtype code>,
            "Data": <binary blob>
        }
    ],
    "Identity": <packed float32 array>,
    "OriginalObjectID": <16-byte UUID>,
    "ExternalProcessorSettings": {
        "<setting name>": <setting value>
    }
}
```

### Device and frame identity

- **`DeviceID`** (string) — Stable identifier for the camera/device the frame came from. Use this to separate state if the same processor is used across multiple cameras.
- **`DeviceName`** (string) — Human-readable name of the device. Suitable for logs; not stable across renames.
- **`Timestamp`** (uint64) — Timestamp of the frame. Read with `mpack_node_u64()` in C; a plain Python int after unpacking.
- **`InputIndex`** (uint32) — Index of the input within the frame (relevant for models with multiple inputs).
- **`Width`**, **`Height`** (uint32) — Frame dimensions in pixels. Bounding-box coordinates are in this pixel space.

### Detections: `BBoxes_xyxy`

A map from class name to a packed float32 array of corners, four floats per box: `x1, y1, x2, y2`.

On the wire the value is transmitted as a MessagePack **binary blob** of packed float32s. The Python helper `parseInferenceResults` unpacks it into a flat `list[float]` (so `len(list) / 4` = number of boxes). The C code reads the binary directly:

```c
const char *bin_data = mpack_node_bin_data(coordinates_data_node);
size_t bin_size      = mpack_node_bin_size(coordinates_data_node);
float *coords = (float *) bin_data;   // bin_size / sizeof(float) / 4 boxes
```

See `nxai-utilities/python-utilities/nxai_communication_utils.py:560` and `postprocessor-c-example/src/main.c:166`.

If the model is not a detector, this field is absent.

### Per-object metadata: `ObjectsMetaData`

A map from class name to a per-class struct. All lists inside are **parallel** — the i-th element of every list refers to the same object:

- **`ObjectIDs`** (list of 16-byte UUIDs) — Stable per-object IDs used by the tracker. Same object across frames → same UUID.
- **`AttributeKeys`** (list of list of strings) — Arbitrary attribute keys per object. Start empty; post-processors append to these lists to attach metadata.
- **`AttributeValues`** (list of list of strings) — Values parallel to `AttributeKeys`.
- **`Confidences`** (list of floats, only when `ReceiveConfidenceData: true`) — Per-object detection confidence.

The parallel structure is important — if you append one key for an object, you must also append one value in the same position. Worked examples in `postprocessor-python-confidences-example/` and `postprocessor-python-settings-example/`.

### Classification: `Scores`

A map from class name to a single float score. Present when the model produces classification outputs. Absent for pure detectors.

### Counts: `Counts`

A map from class name to a uint32 — the count of detected instances per class. Read in C via `mpack_node_u32(mpack_node_map_value_at(counts_node, i))`. Present when the pipeline emits aggregate counts.

### Raw model outputs: `BinaryOutputs`

Present only when the processor's JSON entry has `ReceiveBinaryData: true`. An array of output tensors, each of the form:

```
{
    "Name": "<tensor name>",   // e.g. "Identity:0"
    "Type": <uint8>,            // dtype code, see enum below
    "Data": <binary blob>       // raw bytes in tensor order
}
```

The dtype codes, defined in `nxai-utilities/c-utilities/include/nxai_data_structures.h`:

| Code | Type   | Code | Type    |
|------|--------|------|---------|
| 1    | FLOAT  | 8    | STRING  |
| 2    | UINT8  | 9    | BOOL    |
| 3    | INT8   | 11   | DOUBLE  |
| 4    | UINT16 | 12   | UINT32  |
| 5    | INT16  | 13   | UINT64  |
| 6    | INT32  |      |         |
| 7    | INT64  |      |         |

The shape is not transmitted in the message; the processor is expected to know it from the model. See `postprocessor-c-raw-example/src/main.c:171` for the C reader and `postprocessor-python-anpr-example/` for Python.

### Embedding vector: `Identity`

A packed float32 array — typically a feature vector (e.g. CLIP embedding) emitted by the model. Python's `parseInferenceResults` unpacks this automatically (`nxai_communication_utils.py:568`). Used by the CLIP examples.

### Tracking cross-reference: `OriginalObjectID`

A 16-byte UUID that links a downstream inference (e.g. OCR logits over a license-plate crop) back to the detector object that produced the crop. Only present when the pipeline performs a two-stage inference that hands results off between models. See `postprocessor-python-anpr-example/README.md`.

### UI settings from the user: `ExternalProcessorSettings`

A map carrying the current values of the UI controls declared in the processor's JSON `Settings` field. Keys match the `"name"` of each control and are conventionally prefixed `externalprocessor.`. String-typed controls (TextField, PasswordField, ComboBox) arrive as strings; controls with non-string types (SpinBox, DoubleSpinBox, CheckBox, PolygonFigure, etc.) may arrive as their native type or as a JSON-encoded string depending on the runtime — defensive conversion (e.g. `float(value)`) is the safe pattern, as shown in `postprocessor-python-anpr-example/`.

Example, given a `TextField` with `"name": "externalprocessor.attributeName"`:

```json
"ExternalProcessorSettings": {
    "externalprocessor.attributeName": "LicensePlate",
    "externalprocessor.attributeValue": "ABC-123"
}
```

The processor reads this every frame and applies whatever the user has configured in the NX plugin settings. See `postprocessor-python-settings-example/postprocessor-python-settings-example.py` for the read-and-apply pattern.

---

## Message 2: image header (only when `ReceiveInputTensor: true`)

A small MessagePack map that tells the processor where to find the raw input image in shared memory:

```json
{
    "Width":    <uint32>,
    "Height":   <uint32>,
    "Channels": <uint32>,
    "SHMKEY":   "<string key>"
}
```

- **`Width`**, **`Height`**, **`Channels`** — Dimensions of the raw input tensor (before any resizing into the model's input shape).
- **`SHMKEY`** — String key identifying the shared-memory segment. The processor opens this segment to read the pixel data.

Canonical read pattern (Python, from `postprocessor-python-image-example.py:55`):

```python
shared_memory = nxai_communication_utils.SharedMemory(key=shm_key)
image_data = shared_memory.read()      # bytes of length Width*Height*Channels
```

On Unix the key is typically numeric; on Windows it's an OS-specific handle name. The helper in `nxai_communication_utils` hides the platform difference. See `nxai-utilities/python-utilities/nxai_communication_utils.py` (the `SharedMemory` class, line 70).

---

## Worked example of a parsed message

After `parseInferenceResults(input_message)`, the Python dict for a single frame from a detection pipeline with confidence data enabled looks approximately like this:

```python
{
    'DeviceID': 'cam-01',
    'DeviceName': 'Front Gate',
    'Timestamp': 1729000000000,
    'InputIndex': 0,
    'Width': 1920,
    'Height': 1080,
    'BBoxes_xyxy': {
        'car':    [412.0, 200.0, 680.0, 430.0, 1100.0, 300.0, 1340.0, 510.0],
        'person': [900.0, 600.0, 980.0, 820.0]
    },
    'ObjectsMetaData': {
        'car': {
            'ObjectIDs':       [b'\xa1...', b'\xb2...'],
            'AttributeKeys':   [[], []],
            'AttributeValues': [[], []],
            'Confidences':     [0.91, 0.87]
        },
        'person': {
            'ObjectIDs':       [b'\xc3...'],
            'AttributeKeys':   [[]],
            'AttributeValues': [[]],
            'Confidences':     [0.76]
        }
    },
    'Counts': { 'car': 2, 'person': 1 },
    'ExternalProcessorSettings': {
        'externalprocessor.min_confidence': 0.85
    }
}
```

Two cars (8 floats = 2 boxes × 4 coords), one person, per-object UUIDs and confidences, one user-configured setting. The processor's job from here is to read, optionally mutate, and send back — see the companion document on output format.

---

## Evidence in the repo

- Schema definition: `postprocessor-python-example/README.md`, `postprocessor-python-image-example/README.md`, `postprocessor-python-events-example/README.md` (all repeat the same canonical schema block).
- Python parsing: `nxai-utilities/python-utilities/nxai_communication_utils.py` (`parseInferenceResults` at line 560, `SharedMemory` at line 70).
- C parsing: `postprocessor-c-example/src/main.c:102` (the `processMpackDocument` function reads every field).
- `BinaryOutputs` handling: `postprocessor-c-raw-example/src/main.c:171` and `postprocessor-python-anpr-example/`.
- `ExternalProcessorSettings` consumption: `postprocessor-python-settings-example/postprocessor-python-settings-example.py`.
- Dtype codes: `nxai-utilities/c-utilities/include/nxai_data_structures.h` (enum `nxai_data_type`).
