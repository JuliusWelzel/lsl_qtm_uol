"""
    Stream the QTM real-time frame number into LSL.

    Streams only the QTM frame number (the "frame N of M" shown in QTM) so that
    other LSL streams (e.g. EEG) can be synchronised to the Qualisys capture
    timeline afterwards.

    A video-only (Miqus Video) capture produces no marker/skeleton/timecode data,
    so the only per-frame real-time data is the camera image. We enable a tiny RT
    image for one camera and read the QTM frame number from each packet's header
    -- the image pixels themselves are never used.

    Start QTM first, then record live (or Play -> Play with Real-Time output)
    before running this script.
"""

import asyncio
import xml.etree.ElementTree as ET

import pylsl
import qtm_rt

# QTM host. Use "127.0.0.1" when this script runs on the QTM machine.
QTM_HOST = "127.0.0.1"

# QTM capture rate in Hz. Adjust to match your project settings.
QTM_FRAME_RATE = 85

# Which QTM component to subscribe to. The frame number we push lives in every
# packet's header regardless of component -- the component only exists to make
# QTM emit a packet per frame.
#   "image" -> works for a video-only capture (the only per-frame data video
#              produces). Requires enabling RT image transmission (done below).
#   "2d"    -> use this if you put at least one camera in marker mode. Lighter
#              than images, and QTM's docs say the frame number is only valid
#              when a camera is in marker mode, so this is the robust choice.
QTM_COMPONENT = "image"

# ID of the camera to receive RT images from (1 = first camera). Only the frame
# number in the packet header is used; the image is shrunk to the smallest size
# so the bandwidth/CPU cost is negligible. Set this to a camera that exists.
QTM_IMAGE_CAMERA = 1

# Real-time client control password, as set in QTM under
# Project Options -> Real-Time output. Enabling image transmission is a settings
# change and requires becoming the controlling "master" client first. Leave as
# "" if no password is configured in QTM.
QTM_RT_PASSWORD = ""

# Diagnostic counter of how many packets on_packet has received.
_packet_count = 0


def create_lsl_outlet():
    """
    Creates and returns an LSL (Lab Streaming Layer) outlet for the QTM frame
    number.

    A single int32 channel is used since the frame number is a monotonically
    increasing integer counter (float32 would lose integer precision beyond
    ~16.7 million frames).

    Returns:
        pylsl.StreamOutlet: The LSL outlet object.
    """
    info = pylsl.StreamInfo(
        name="Qualisys",
        type="framenumber",
        channel_count=1,
        nominal_srate=QTM_FRAME_RATE,
        channel_format=pylsl.cf_int32,  # frame number is an integer counter
        source_id="qtm_framenumber",
    )
    outlet = pylsl.StreamOutlet(info)
    return outlet


def enable_image_camera(settings_xml, target_camera_id):
    """
    Turn QTM's image-transmission settings into a settings document that enables
    a small RT image for a single camera.

    QTM only sends camera images over real-time when a client asks for them, and
    the request must be QTM's own ``<Image>`` settings block with the root tag
    renamed to ``QTM_Settings`` (this mirrors the SDK's image_example.py). We
    fetch the live settings, enable only the target camera, shrink it to a tiny
    JPEG (we only want the frame number from the packet header, not the pixels),
    and disable every other camera to keep bandwidth minimal.

    Args:
        settings_xml: XML returned by ``get_parameters(["image"])``.
        target_camera_id: ID (int) of the camera to receive images from.

    Returns:
        str: A ``QTM_Settings`` XML document ready for ``send_xml``.
    """
    target = str(target_camera_id)
    xml = ET.fromstring(settings_xml)
    for camera in xml.findall("./Image/Camera"):
        is_target = camera.findtext("ID") == target
        camera.find("Enabled").text = "true" if is_target else "false"
        if is_target:
            for tag, value in (("Format", "jpg"), ("Width", "64"), ("Height", "64")):
                element = camera.find(tag)
                if element is not None:
                    element.text = value

    xml.tag = "QTM_Settings"
    return ET.tostring(xml).decode("utf-8")


def on_packet(packet):
    """
    Process a packet received from the Qualisys system.
    Each iteration of this function pushes the current frame number as a single
    sample to the LSL outlet.

    Args:
        packet: The packet received from the Qualisys system.

    Returns:
        None
    """
    global _packet_count
    _packet_count += 1
    outlet.push_sample([packet.framenumber])
    # Diagnostic: packet count distinguishes "one packet then silence" (stream
    # stops) from "many packets all numbered 1" (counter not advancing).
    print(
        "packet #{}  framenumber={}  timestamp={}  components={}".format(
            _packet_count,
            packet.framenumber,
            packet.timestamp,
            list(packet.components.keys()),
        )
    )


async def setup():
    """
    Connects to the Qualisys system and sets up an LSL outlet for streaming the
    QTM real-time frame number (read from each data packet's header).

    Returns:
        None
    """
    connection = await qtm_rt.connect(QTM_HOST)
    if connection is None:
        print("Could not connect to QTM at {}".format(QTM_HOST))
        return

    # create lsl outlet
    global outlet
    outlet = create_lsl_outlet()
    input("Start LabRecorder ... Press Enter to continue")

    # For a video-only capture we enable a tiny RT image for one camera: it is
    # the only per-frame data video provides. (Skipped when QTM_COMPONENT is a
    # marker component such as "2d".) Enabling transmission is a settings change,
    # so it must happen while we hold control ("master"); TakeControl releases it
    # again on exit so the QTM operator can still start/stop the recording.
    if QTM_COMPONENT == "image":
        settings = await connection.get_parameters(parameters=["image"])
        image_settings = enable_image_camera(settings, QTM_IMAGE_CAMERA)
        async with qtm_rt.TakeControl(connection, QTM_RT_PASSWORD):
            await connection.send_xml(image_settings)

    # Every packet carries the QTM frame number in its header; on_packet reads
    # packet.framenumber and never touches the component payload.
    await connection.stream_frames(components=[QTM_COMPONENT], on_packet=on_packet)


if __name__ == "__main__":
    asyncio.ensure_future(setup())
    asyncio.get_event_loop().run_forever()
