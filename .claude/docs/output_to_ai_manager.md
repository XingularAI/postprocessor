# What the Post-processor Returns to the AI Manager

A post-processor sends back a single MessagePack-encoded message after processing each frame. The response is the **modified inference-results dict**, encoded with `nxai_communication_utils.writeInferenceResults()`. The AI Manager merges it downstream into the pipeline.

If `NoResponse: true` is set in the processor's JSON entry, no response is expected and the processor must not send one.

---

## Transport

The response is sent back on the same connection the AI Manager opened for the frame, before the processor calls `connection.close()`.

```python
output_message = nxai_communication_utils.writeInferenceResults(input_object)
connection.send(output_message)
connection.close()
```

The helper handles MessagePack encoding and length-prefix framing.

---

## What the processor can add or modify

The response dict is the same structure as the input (see `input_from_ai_manager.md`). The processor is free to modify any field. The fields that processors most commonly write are described below.

### Bounding boxes: `BBoxes_xyxy`

Add new detections or modify existing ones. The value for each class is a flat list of `float` coordinates — four per box: `x1, y1, x2, y2` in pixel space (matching the frame `Width` and `Height`).

```python
if "BBoxes_xyxy" not in input_object:
    input_object["BBoxes_xyxy"] = {}

# Add two boxes for a new class
input_object["BBoxes_xyxy"]["vehicle"] = [
    100.0, 200.0, 400.0, 500.0,   # box 1
    600.0, 150.0, 900.0, 450.0,   # box 2
]
```

Any class name added here must be declared in the `Objects` array of the processor's JSON entry, or the UI will silently drop it.

To remove all boxes for a class, set its value to an empty list. To remove the class entirely, delete the key.

### Events: `Events`

An array of event dicts. Each dict has three string fields:

```python
if "Events" not in input_object:
    input_object["Events"] = []

input_object["Events"].append({
    "ID":          "my.namespace.event_name",   # must match JSON "Events"[].ID
    "Caption":     "Short title shown in NX",
    "Description": "Longer explanation, may include runtime data",
})
```

- **`ID`** — must be declared in the `Events` array of the processor's JSON entry, or the event is dropped.
- **`Caption`** — displayed as the event title in the NX event log.
- **`Description`** — displayed as the event body. Can include dynamic information (detected plate number, count, etc.).

Multiple events can be appended in a single frame.

### Per-object attributes: `ObjectsMetaData`

Attach arbitrary key-value pairs to individual detected objects. `ObjectsMetaData` is a dict keyed by class name; each class holds parallel lists — the i-th element of every list refers to the i-th detected object.

```python
for class_name, class_data in input_object.get("ObjectsMetaData", {}).items():
    for i in range(len(class_data["AttributeKeys"])):
        class_data["AttributeKeys"][i].append("Confidence")
        class_data["AttributeValues"][i].append("0.91")
```

Rules:
- `AttributeKeys` and `AttributeValues` are always parallel. Every key you append must have a corresponding value appended at the same index.
- Values must be strings.
- Attributes are displayed in the NX object details panel.

See `postprocessor-python-confidences-example/` and `postprocessor-python-settings-example/` for worked examples.

---

## Filtering detections

To suppress all detections for a class:

```python
input_object["BBoxes_xyxy"].pop("unwanted_class", None)
input_object.get("ObjectsMetaData", {}).pop("unwanted_class", None)
```

To remove a single object at index `i` within a class (four floats per box):

```python
coords = input_object["BBoxes_xyxy"]["car"]
del coords[i*4 : i*4 + 4]
meta = input_object["ObjectsMetaData"]["car"]
for lst in (meta["ObjectIDs"], meta["AttributeKeys"], meta["AttributeValues"]):
    del lst[i]
```

---

## Minimal response example

The simplest valid response is to send the input dict back unmodified:

```python
output_message = nxai_communication_utils.writeInferenceResults(input_object)
connection.send(output_message)
connection.close()
```

A response that uses all three output types:

```python
# 1. Add a bounding box for a new class
input_object.setdefault("BBoxes_xyxy", {})["zone_violation"] = [200.0, 100.0, 700.0, 600.0]

# 2. Attach an attribute to every detected "person"
for i, _ in enumerate(input_object.get("ObjectsMetaData", {}).get("person", {}).get("ObjectIDs", [])):
    input_object["ObjectsMetaData"]["person"]["AttributeKeys"][i].append("Zone")
    input_object["ObjectsMetaData"]["person"]["AttributeValues"][i].append("Restricted")

# 3. Emit an event
input_object.setdefault("Events", []).append({
    "ID": "security.zone_violation",
    "Caption": "Zone Violation",
    "Description": "Person detected in restricted area",
})

output_message = nxai_communication_utils.writeInferenceResults(input_object)
connection.send(output_message)
connection.close()
```

---

## Evidence in the repo

- Encoding helper: `nxai-utilities/python-utilities/nxai_communication_utils.py` (`writeInferenceResults`).
- BBoxes_xyxy modification: `postprocessor-python-example/postprocessor-python-example.py`.
- Events emission: `postprocessor-python-events-example/postprocessor-python-events-example.py`.
- Attribute attachment: `postprocessor-python-confidences-example/`, `postprocessor-python-settings-example/`.
- Object filtering: `postprocessor-python-anpr-example/` (strips non-plate boxes before responding).
