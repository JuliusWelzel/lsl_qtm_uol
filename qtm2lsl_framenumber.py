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
    frame number of the markerless (skeleton) component.

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

    await connection.stream_frames(components=["skeleton"], on_packet=on_packet)


if __name__ == "__main__":
    asyncio.ensure_future(setup())
    asyncio.get_event_loop().run_forever()
