"""
    Diagnostic: read QTM's current real-time frame number on demand.

    Use this to confirm the frame number this code sees matches the "frame N of
    M" shown in QTM's playback/recording toolbar. It does NOT stream to LSL --
    it just polls QTM for the current frame and prints it.

    A video-only (Miqus Video) capture exposes the frame number only via the
    image stream, so we enable a tiny RT image first (same as the main script).

    Run QTM, open a recorded session (or record live), then run this script.
    Pausing playback at a known frame N should make this print framenumber = N;
    pressing play should make the printed number climb toward M.
"""

import asyncio

import qtm_rt

# Reuse the connection settings and image-enabling helper from the main script.
from qtm2lsl_framenumber import (
    QTM_HOST,
    QTM_IMAGE_CAMERA,
    QTM_RT_PASSWORD,
    enable_image_camera,
)

# How often to ask QTM for the current frame number, in seconds.
POLL_INTERVAL = 0.2


async def main():
    connection = await qtm_rt.connect(QTM_HOST)
    if connection is None:
        print("Could not connect to QTM at {}".format(QTM_HOST))
        return

    # Enable a tiny RT image so get_current_frame has per-frame data to return.
    settings = await connection.get_parameters(parameters=["image"])
    image_settings = enable_image_camera(settings, QTM_IMAGE_CAMERA)
    async with qtm_rt.TakeControl(connection, QTM_RT_PASSWORD):
        await connection.send_xml(image_settings)

    print("Polling QTM's current frame number (Ctrl+C to stop).")
    print("Compare each value with the 'frame N of M' shown in QTM.\n")
    while True:
        try:
            packet = await connection.get_current_frame(components=["image"])
        except asyncio.TimeoutError:
            print("no frame (is a measurement playing or recording in QTM?)")
        else:
            print(
                "current framenumber = {}   (timestamp = {})".format(
                    packet.framenumber, packet.timestamp
                )
            )
        await asyncio.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nStopped.")
