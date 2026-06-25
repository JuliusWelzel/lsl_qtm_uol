"""
    Mark QTM capture start/stop in LSL for post-hoc frame alignment.

    A video-only (Miqus Video) capture provides no per-frame real-time data
    (no markers, skeleton, timecode; the image stream does not deliver live),
    and QTM's documented real-time frame number is only valid when a camera is
    in marker mode. So streaming a frame number per frame is not possible for a
    pure-video system.

    Instead we use what QTM *does* send to every connected client regardless of
    camera mode: capture start/stop events. We push an LSL marker the instant
    each event arrives, time-stamped on the LSL clock. Recorded alongside your
    EEG (and any other LSL streams), these markers anchor the Qualisys capture
    timeline to the LSL timeline.

    Post-hoc alignment (the Theia workflow):
      - The "EventCaptureStarted" marker is the LSL time of QTM frame 1.
      - With the capture frame rate, frame i occurs at:
            t(i) = t_start + (i - 1) / QTM_FRAME_RATE
      - For drift-free alignment over long recordings, use the
        "EventCaptureStopped" marker and Theia's total frame count N instead:
            fps_effective = (N - 1) / (t_stop - t_start)
            t(i) = t_start + (i - 1) / fps_effective
      Theia processes the same recorded video, so its frame indices are QTM's
      frame numbers (reconcile any 0- vs 1-based offset with one known frame).

    Start QTM first and run this script, then record as usual in QTM.
"""

import asyncio

import pylsl
import qtm_rt

# QTM host. Use "127.0.0.1" when this script runs on the QTM machine.
QTM_HOST = "127.0.0.1"

# QTM capture rate in Hz. Not streamed -- documented here for the post-hoc
# frame-time math above. Set it to your actual video capture rate.
QTM_FRAME_RATE = 85

# Set by setup() before any event can arrive.
outlet = None


def create_marker_outlet():
    """
    Create an LSL marker outlet for QTM capture events.

    An irregular-rate string marker stream (the standard LSL marker pattern,
    like LabRecorder markers): each sample is a QTM event name, time-stamped on
    the LSL clock when the event arrived.

    Returns:
        pylsl.StreamOutlet: The LSL marker outlet.
    """
    info = pylsl.StreamInfo(
        name="Qualisys",
        type="Markers",
        channel_count=1,
        nominal_srate=pylsl.IRREGULAR_RATE,
        channel_format=pylsl.cf_string,
        source_id="qtm_sync",
    )
    return pylsl.StreamOutlet(info)


def on_event(event):
    """
    Handle a QTM real-time event by pushing it to LSL as a marker.

    Args:
        event: A qtm_rt.QRTEvent (e.g. EventCaptureStarted/EventCaptureStopped).

    Returns:
        None
    """
    timestamp = pylsl.local_clock()
    outlet.push_sample([event.name], timestamp=timestamp)
    print("LSL marker: {}  @ lsl_clock {:.6f}".format(event.name, timestamp))


async def setup():
    """
    Connect to QTM, open the LSL marker outlet, and forward capture events.

    Returns:
        None
    """
    global outlet
    outlet = create_marker_outlet()

    connection = await qtm_rt.connect(QTM_HOST, on_event=on_event)
    if connection is None:
        print("Could not connect to QTM at {}".format(QTM_HOST))
        return

    # Sanity check: ask QTM for its current state so on_event fires once now,
    # confirming the connection and event channel work before we wait for a
    # recording. (This early marker lands before LabRecorder is armed, so it is
    # simply not recorded -- only the later capture start/stop matter.)
    try:
        await connection.get_state()
    except asyncio.TimeoutError:
        print("Connected, but QTM did not report its state within 30 s.")

    input("Start LabRecorder ... Press Enter to continue")
    print("Connected. An LSL marker is pushed on every QTM capture event.")
    print("Start (and later stop) a recording in QTM. Press Ctrl+C to quit.\n")

    # Keep the event loop alive so QTM events keep arriving and firing on_event.
    while True:
        await asyncio.sleep(3600)


if __name__ == "__main__":
    try:
        asyncio.ensure_future(setup())
        asyncio.get_event_loop().run_forever()
    except KeyboardInterrupt:
        pass
