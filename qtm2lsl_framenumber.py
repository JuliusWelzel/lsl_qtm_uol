"""
    Stream the QTM real-time frame number into LSL.

    Streams only the frame number of the markerless (skeleton) component so that
    other LSL streams (e.g. EEG) can be synchronised to the Qualisys capture
    timeline afterwards.

    Start QTM first, load/record a markerless session, then Play -> Play with
    Real-Time output before running this script.
"""

import asyncio

import pylsl
import qtm_rt

# QTM host. Use "127.0.0.1" when this script runs on the QTM machine.
QTM_HOST = "127.0.0.1"

# QTM markerless capture rate in Hz. Adjust to match your project settings.
QTM_FRAME_RATE = 85

# ID of a camera to receive RT images from (1 = first camera). For a video-only
# (Miqus Video) capture the image stream is the only per-frame data, so we ask
# QTM to send a tiny image per frame purely to carry the frame number in its
# header -- the pixels are never read. Set this to any camera that exists in
# your system.
QTM_IMAGE_CAMERA = 1


def create_lsl_outlet():
    """
    Creates and returns an LSL (Lab Streaming Layer) outlet for the QTM frame
    number.

    A single int32 channel is used since the frame number is a monotonically
    increasing integer counter (float32 would lose integer precision beyond
    ~16.7 million frames).

    Returns:
        pylsl.StreamOutlet: The LSL outlet object.

    Raises:
        None
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


def on_packet(packet):
    """
    Process a packet received from the Qualisys system.
    Each iteration of this function pushes the current frame number as a single
    sample to the LSL outlet.

    Args:
        packet: The packet received from the Qualisys system.

    Returns:
        None

    Raises:
        None
    """
    outlet.push_sample([packet.framenumber])
    print("Framenumber: {}".format(packet.framenumber))


async def setup():
    """
    Connects to the Qualisys system and sets up an LSL outlet for streaming the
    QTM real-time frame number (read from the packet header of the image stream).

    Returns:
        None

    Raises:
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

    # Tell QTM to actually transmit RT images for one camera. Subscribing to the
    # "image" component is NOT enough on its own -- QTM only sends camera images
    # over real-time when a client requests them via this XML settings message.
    # We request the smallest possible image (we only want the frame number in
    # the packet header), so the bandwidth/CPU cost is negligible.
    image_settings = (
        "<QTMSettings>"
        "<Image>"
        "<Camera>"
        "<ID>{}</ID>"
        "<Enabled>true</Enabled>"
        "<Format>RAWGrayscale</Format>"
        "<Width>64</Width>"
        "<Height>64</Height>"
        "<Left_Crop>0.0</Left_Crop>"
        "<Top_Crop>0.0</Top_Crop>"
        "<Right_Crop>1.0</Right_Crop>"
        "<Bottom_Crop>1.0</Bottom_Crop>"
        "</Camera>"
        "</Image>"
        "</QTMSettings>"
    ).format(QTM_IMAGE_CAMERA)
    await connection.send_xml(image_settings)

    # The frame number lives in the packet header, not in any component's data,
    # so we only need QTM to emit a packet per frame. A video-only (Miqus Video)
    # capture has no "skeleton"/"timecode" data, so we subscribe to "image" --
    # every video frame produces a packet whose header carries the frame number.
    # (on_packet never reads the image data itself.)
    await connection.stream_frames(components=["image"], on_packet=on_packet)


if __name__ == "__main__":
    asyncio.ensure_future(setup())
    asyncio.get_event_loop().run_forever()
