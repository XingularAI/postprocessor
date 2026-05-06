# CLAUDE.md

Orientation for Claude Code working in this repo.

## What this repo is

The **NX AI Integration SDK** — tools and examples for writing external pre- and post-processors that plug into the NX AI Manager (part of Network Optix MetaVMS). A post-processor is a standalone program that receives the AI Manager's inference results as a MessagePack message over a Unix socket, optionally mutates them (adds boxes, tags objects, emits events), and returns them. A preprocessor does the analogous job on the input side.

The entire SDK is organized around one pattern: per-processor directories at the repo root, built and installed by a CMake tree. There is no runtime, no framework to learn beyond the MessagePack schema.

## Repo shape

- **`postprocessor-*/`** — 14 example post-processors in Python and C. Copy the closest one as a starting template.
- **`preprocessor-*/`** — 3 example preprocessors.
- **`nxai-utilities/`** — Git submodule with the C and Python helpers (socket I/O, MessagePack wrappers, shared-memory reader). Clone the repo with `--recurse-submodules` or you will get missing-file errors immediately.
- **`message_processing_utils/`** — Python helpers used by the ANPR and average-car-speed examples (OCR engine, deduplication caches). Not needed for simple processors.
- **`example_models/`** — ONNX models used by the advanced examples.
- **`CMakeLists.txt`** — Root build file. Add a new processor by appending one line here and creating the processor's own directory.
- **`build_all.sh`** / **`build_docker.sh`** — Convenience wrappers around the CMake invocation.
- **`.claude/docs/`** — Reference documentation for the wire protocol and JSON config. Start here when a question is "what fields exist" or "how is X encoded":
  - `external_postprocessors_json.md` — every field of the JSON registration file.
  - `input_from_ai_manager.md` — every field the processor receives.
  - `output_to_ai_manager.md` — every field the processor can return.

## Canonical workflow

Build a single processor:

```shell
mkdir -p build && cd build
python3 -m venv integrationsdk && source integrationsdk/bin/activate
cmake ..
cmake --build . --target <processor-name>
```

Install it:

```shell
cmake --install . --component <processor-name>
```

Register it by adding an entry to `<base>/mediaserver/var/nx_ai_manager/nxai_manager/postprocessors/external_postprocessors.json` (see Install paths below for `<base>`), then:

```shell
sudo service <vms-service> restart
```

See `docs/01-external-postprocessors-json.md` for the JSON schema.

## Development shortcut

For fast iteration, **omit the `Command` field** from the JSON entry. The AI Manager will then assume the processor is already running and just send data to it. You start the processor manually, edit, kill, restart — no rebuild-and-reinstall cycle. See the root `README.md` under "Development".

## Gotchas that cost hours

- **Clone with `--recurse-submodules`.** `nxai-utilities/` is a submodule; without it nothing imports.
- **Register new classes in the JSON.** Any new class name a post-processor adds to `BBoxes_xyxy` must also appear under `Objects: [{ID, Name}]` in its JSON entry, or the UI silently drops the box.
- **Register new event IDs in the JSON.** Same rule for `Events: [{ID, Name}]` — undeclared event IDs are dropped.
- **The socket path is `argv[1]`.** When the AI Manager starts the processor it passes the socket path as the first CLI argument. Read it from there rather than hardcoding a second copy.
- **`ReceiveInputTensor: true` means two messages per frame.** The processor must read the inference-results message and then the image-header message before responding.
- **Every frame can be `{"EXIT": ...}`.** The first thing a processor does after parsing is check for the exit key; if present, close the connection and break out of the main loop.

## Picking an example to copy

- Modify bounding boxes or filter detections → `postprocessor-python-example/` (Python), `postprocessor-c-example/` (C).
- Attach per-object attributes (labels in the UI) → `postprocessor-python-confidences-example/`.
- Emit events → `postprocessor-python-events-example/`.
- Expose settings in the NX plugin UI → `postprocessor-python-settings-example/` (see also its `settings_model.md`).
- Read the raw input image → `postprocessor-python-image-example/`, `postprocessor-c-image-example/`.
- Consume raw model outputs (logits, embeddings) → `postprocessor-c-raw-example/`, `postprocessor-python-anpr-example/`.
- Semantic similarity search with CLIP embeddings → `postprocessor-python-clip-example/`.
- Multi-frame tracking / speed analytics → `postprocessor-python-measure-average-car-speed/`.
- Offload inference to a cloud endpoint → `postprocessor-cloud-inference-example/`.
- Fire-and-forget (no response) → `postprocessor-python-noresponse-example/`, `postprocessor-python-edgeimpulse-example/`.
- Preprocessing (image stage) → `preprocessor-python-image-example/`.
- Preprocessing (tensor stage) → `preprocessor-python-tensor-example/`.
- Preprocessing with CLIP tokenization → `preprocessor-python-clip-example/`.

## Install paths (reference)

Both NX Meta and NX Witness are supported. The base path differs by product:

| Product | Base | Service |
|---------|------|---------|
| NX Meta | `/opt/networkoptix-metavms` | `networkoptix-metavms-mediaserver` |
| NX Witness | `/opt/networkoptix` | `networkoptix-mediaserver` |

- Post-processor binaries: `<base>/mediaserver/var/nx_ai_manager/nxai_manager/postprocessors/`
- Post-processor JSON: `.../postprocessors/external_postprocessors.json`
- Preprocessor binaries and JSON: analogous `.../preprocessors/` directory.
- CMake auto-detects the active product at configure time; override with `-DINSTALL_DEST_POSTPROCESSORS=<path>`.

Windows uses the mirrored tree under `C:\Windows\System32\config\systemprofile\AppData\Local\Network Optix\Network Optix MetaVMS Media Server\nx_ai_manager\nxai_manager\...`.

## When in doubt

Open the reference doc matching the question (`./.claude/docs/external_postprocessors_json.md`, `./.claude/docs/input_from_ai_manager.md`, `./.claude/docs/output_to_ai_manager.md`), then open the example from the list above that's closest to the target use case. The SDK is small enough that reading two examples end-to-end is often faster than guessing.
