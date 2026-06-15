# lsl_qtm_uol

Stream the [Qualisys Track Manager (QTM)](https://www.qualisys.com/) real-time
**frame number** into [Lab Streaming Layer (LSL)](https://labstreaminglayer.org/).

The frame number of the **markerless** (skeleton) component is pushed to an LSL
outlet, so any other LSL stream recorded alongside it (e.g. EEG) can be
synchronised to the Qualisys capture timeline after recording.

## Requirements

- Python ≥ 3.13
- [uv](https://docs.astral.sh/uv/) for dependency management
- A QTM installation with Real-Time output enabled
- A markerless (skeleton) capture loaded or running in QTM

Python dependencies (installed automatically, see below):

- [`qtm-rt`](https://github.com/qualisys/qualisys_python_sdk) — QTM real-time SDK
- [`pylsl`](https://github.com/labstreaminglayer/pylsl) — LSL Python bindings
  (ships the native `liblsl` binary on Windows)

## Install

```bash
uv sync
```

This creates a `.venv` and installs the locked dependencies from
`pyproject.toml` / `uv.lock`.

## Usage

1. Start **QTM**, load or record a markerless session.
2. Enable real-time output: **Play → Play with Real-Time output**.
3. Open `qtm2lsl_framenumber.py` and adjust the two settings at the top:

   ```python
   QTM_HOST = "127.0.0.1"   # QTM machine IP ("127.0.0.1" if same PC)
   QTM_FRAME_RATE = 85      # your markerless capture rate in Hz
   ```

   `QTM_FRAME_RATE` only sets LSL's `nominal_srate` metadata (used for jitter
   correction on import) — set it to your actual markerless capture rate.

4. Run the script:

   ```bash
   uv run python qtm2lsl_framenumber.py
   ```

5. When prompted (`Start LabRecorder ... Press Enter to continue`), arm your LSL
   recorder (e.g. LabRecorder), then press **Enter** to start streaming.

The script then runs forever, printing and pushing each frame number until you
stop it with `Ctrl+C`.

## LSL stream

| Property         | Value             |
| ---------------- | ----------------- |
| `name`           | `Qualisys`        |
| `type`           | `framenumber`     |
| `source_id`      | `qtm_framenumber` |
| `channel_count`  | `1`               |
| `channel_format` | `cf_int32`        |
| `nominal_srate`  | `QTM_FRAME_RATE`  |

The frame number is sent as a single `int32` channel. `int32` is used instead of
`float32` because the frame number is a monotonically increasing integer
counter, and `float32` would lose integer precision beyond ~16.7 million frames.

## How it works

The script connects to QTM via `qtm_rt`, subscribes to the `skeleton` component
(the markerless data), and registers an `on_packet` callback. The frame number
lives in every packet's header (`packet.framenumber`), so on each incoming frame
the callback pushes it to the LSL outlet:

```
QTM (markerless RT) ──packet──> on_packet ──push_sample──> LSL outlet "Qualisys"
```

It follows the same structure as the 3D streaming example in
[StepuP_setup/sync_scripts/qualisys2lsl.py](https://github.com/JuliusWelzel/StepuP_setup/blob/main/sync_scripts/qualisys2lsl.py).
