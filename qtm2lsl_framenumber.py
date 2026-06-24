"""
    Stream the QTM real-time frame number into LSL.

    Streams only the QTM frame number (the "frame N of M" shown in QTM) so that
    other LSL streams (e.g. EEG) can be synchronised to the Qualisys capture
    timeline afterwards.

    The frame number lives in the header of every QTM real-time data packet, so
    we request frames with NO data components -- no markers, skeleton or images
    are transmitted, only the bare frame header.

    Start QTM first, then record live (or Play -> Play with Real-Time output)
    before running this script.
"""

import asyncio

import pylsl
import qtm_rt

# QTM host. Use "127.0.0.1" when this script runs on the QTM machine.
QTM_HOST = "127.0.0.1"

# QTM capture rate in Hz. Adjust to match your project settings.
QTM_FRAME_RATE = 85

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

    # Request every frame with NO data components. QTM still sends a data packet
    # per frame, and its header carries the QTM frame number -- no markers,
    # skeleton or images are requested or transmitted. on_packet reads
    # packet.framenumber from that header.
    await connection.stream_frames(components=[], on_packet=on_packet)


if __name__ == "__main__":
    asyncio.ensure_future(setup())
    asyncio.get_event_loop().run_forever()
