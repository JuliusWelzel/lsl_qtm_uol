# lsl_qtm_uol

Mark [Qualisys Track Manager (QTM)](https://www.qualisys.com/) **capture
start/stop events** in [Lab Streaming Layer (LSL)](https://labstreaminglayer.org/)
so a video (Miqus Video) recording can be aligned to any other LSL stream
(e.g. EEG) after recording — in particular to markerless 3D output produced
post-hoc by [Theia3D](https://www.theiamarkerless.ca/).

The script pushes one LSL marker the instant QTM reports that a capture has
started or stopped. The `EventCaptureStarted` marker pins the LSL time of QTM
frame 1; with the capture frame rate (and, for long recordings, the
`EventCaptureStopped` marker plus the total frame count) every video/Theia frame
maps onto the LSL timeline. See [Post-hoc alignment](#post-hoc-alignment).

## Why events instead of a per-frame number?

A **video-only** capture provides no per-frame real-time data: there are no
markers, no skeleton, and no timecode, and QTM's image stream does not deliver
frames live for this purpose. QTM's documented real-time **frame number is only
valid when at least one camera is in marker mode**
([RT protocol docs](https://docs.qualisys.com/qtm-rt-protocol/)) — and Miqus
Video cameras cannot run in marker mode. So streaming a frame number per frame
is not possible for a pure-video system.

What QTM *does* send to every connected client, regardless of camera mode, are
**capture start/stop events**. Anchoring the LSL timeline to those events and
reconstructing frame times from the known frame rate is therefore the reliable
way to synchronise a video capture. Qualisys' own
[LSL app](https://github.com/qualisys/qualisys_lsl_app) only streams 3D/6DOF
marker data and explicitly refuses captures without it.

## Requirements

- Python ≥ 3.13
- [uv](https://docs.astral.sh/uv/) for dependency management
- A QTM installation with Real-Time output enabled

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

1. Open `qtm2lsl_framenumber.py` and adjust the two settings at the top:

   ```python
   QTM_HOST = "127.0.0.1"   # QTM machine IP ("127.0.0.1" if same PC)
   QTM_FRAME_RATE = 85      # your video capture rate in Hz
   ```

   `QTM_FRAME_RATE` is not streamed — it is only documented for the post-hoc
   frame-time math below. Set it to your actual video capture rate.

2. Start **QTM**.

3. Run the script:

   ```bash
   uv run python qtm2lsl_framenumber.py
   ```

   On connect it prints QTM's current state once (e.g.
   `LSL marker: EventCaptureStopped @ lsl_clock …`), confirming the connection
   and event channel work.

4. When prompted (`Start LabRecorder ... Press Enter to continue`), arm your LSL
   recorder (e.g. LabRecorder) so the `Qualisys` marker stream is selected, then
   press **Enter**.

5. Record as usual in QTM. The script pushes a marker on every capture event:

   ```
   LSL marker: EventCaptureStarted @ lsl_clock 12345.678901
   LSL marker: EventCaptureStopped @ lsl_clock 12372.456789
   ```

The script runs until you stop it with `Ctrl+C`.

## LSL stream

| Property         | Value             |
| ---------------- | ----------------- |
| `name`           | `Qualisys`        |
| `type`           | `Markers`         |
| `source_id`      | `qtm_sync`        |
| `channel_count`  | `1`               |
| `channel_format` | `cf_string`       |
| `nominal_srate`  | `IRREGULAR_RATE`  |

Each sample is the QTM event name (e.g. `EventCaptureStarted`,
`EventCaptureStopped`), time-stamped on the LSL clock when the event arrived —
the standard LSL marker pattern, like LabRecorder markers.

## Post-hoc alignment

Recorded in the same XDF as your EEG, the markers anchor the Qualisys capture
timeline to the LSL timeline. Theia3D processes the same video QTM recorded, so
its frame indices are QTM's frame numbers (reconcile any 0- vs 1-based offset
against one known frame).

- `EventCaptureStarted` marker → LSL time of frame 1, `t_start`. This event is
  prompt (it fires the instant recording begins), so it is the reliable anchor.
- Simple map: `t(i) = t_start + (i - 1) / QTM_FRAME_RATE`. The capture rate comes
  from a crystal and is very stable, so this is usually accurate on its own.
- Optional drift correction, using the `EventCaptureStopped` marker and Theia's
  total frame count `N`:

  ```
  fps_effective = (N - 1) / (t_stop - t_start)
  t(i)          = t_start + (i - 1) / fps_effective
  ```

  `EventCaptureStopped` fires when the capture **stops** (before QTM fetches and
  saves the data — that later moment is the separate `EventCaptureSaved` marker,
  which the script also records). Cameras that buffer frames locally can delay
  the stopped event, so before using it for drift correction, verify that
  `t_stop - t_start` matches the actual recording duration. If it does not, rely
  on the `t_start` anchor + capture rate above.

The anchor is accurate to network latency (sub-millisecond on localhost, a few
milliseconds over LAN — well under one frame at typical rates), and the
stop-marker + frame-count correction removes clock drift across the recording.
For sub-frame, hardware-locked precision, feed QTM's
[synchronization output](https://docs.qualisys.com/qtm/content/project_options/synchronization_output.htm)
(a TTL per frame, available in video mode) into the EEG amplifier's trigger
input instead.

## How it works

The script connects to QTM via `qtm_rt` with an `on_event` callback. QTM pushes
capture events to the connection; each event is forwarded to the LSL marker
outlet:

```
QTM (capture events) ──on_event──> push_sample ──> LSL marker stream "Qualisys"
```
