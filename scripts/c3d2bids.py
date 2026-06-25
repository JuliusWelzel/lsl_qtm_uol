"""
Convert Theia3D segment pose data from a .c3d file to BIDS motion format.

Unlike a classic Vicon recording (which stores 3D *marker* trajectories under
`data/points`), a Theia3D export stores one 4x4 homogeneous transformation
matrix per body *segment*, per frame, under `data/rotations`. Each matrix maps
the segment's local frame into the world frame, so its translation column
`T[:3, 3]` is the segment's 3D position in the world.

This script:
- Loads the C3D recording with ezc3d and reads the `rotations` array
- Extracts each segment's position (the translation column of its 4x4 matrix)
- Builds consistent BIDS Channel metadata for position (POS) data
- Validates and exports the recording as BIDS motion files
- Plots a stick-figure skeleton (one frame) and one segment trajectory to
  sanity-check the export

Requirements:
    pip install motionbids ezc3d numpy pandas matplotlib

Input data:
    A Theia3D C3D recording placed in the `data/` folder next to this script.
"""

from pathlib import Path

import pandas as pd
import ezc3d
from matplotlib import pyplot as plt

from motionbids import (
    MotionData,
    Channel,
    validate_motion_data,
    export_bids_motion,
    create_bids_directory_structure,
    export_dataset_description,
)

# Theia3D C3D recording to convert.
INPUT_FILE = (
    Path(__file__).parent.parent
    / "data"
    / "Test_JW_IMUs-T3D_250626_0.c3d"
)

# The three spatial axes each segment position is sampled on. Defined once and
# reused everywhere below so the DataFrame columns, the Channel metadata, and
# the plots can never drift apart.
AXES = ("x", "y", "z")

# Theia3D labels every segment "<name>_4X4" (it is a 4x4 transform). This is the
# suffix we strip to recover a clean BIDS-friendly tracked-point name.
LABEL_SUFFIX = "_4X4"

# Segments to skip when exporting. `worldbody` is the global reference frame
# (a constant identity transform at the origin), not a tracked body point.
EXCLUDE_SEGMENTS = {"worldbody"}

# Skeleton connections, used only for the sanity-check stick-figure plot.
CONNECTIONS = [
    ("head", "torso"),
    ("torso", "pelvis"),
    ("pelvis", "l_thigh"),
    ("l_thigh", "l_shank"),
    ("l_shank", "l_foot"),
    ("pelvis", "r_thigh"),
    ("r_thigh", "r_shank"),
    ("r_shank", "r_foot"),
    ("torso", "l_uarm"),
    ("l_uarm", "l_larm"),
    ("l_larm", "l_hand"),
    ("torso", "r_uarm"),
    ("r_uarm", "r_larm"),
    ("r_larm", "r_hand"),
]

# Configuration
bids_root = Path(__file__).parent.parent / "bids_dataset"
subject = "JW"
session = "01"
task_name = "test"
tracksys = "theia3d"


def clean_segment_label(label: str) -> str:
    """Return a clean, BIDS-friendly segment name from a Theia3D label.

    Theia3D names segments "pelvis_4X4", "l_thigh_4X4", ... The "_4X4" suffix
    just records that the entry is a 4x4 transform, so it is stripped to leave
    the anatomical name ("pelvis", "l_thigh", ...).
    """
    label = label.strip()
    if label.endswith(LABEL_SUFFIX):
        label = label[: -len(LABEL_SUFFIX)]
    return label


def channel_name(segment: str, axis: str) -> str:
    """Build the canonical channel name for a segment/axis pair (e.g. "pelvis_x").

    Using a single helper for naming guarantees the DataFrame column, the
    Channel object, and any later lookup (plotting, validation) all agree.
    """
    return f"{segment}_{axis}"


# =========================================================================
# 1) Load the C3D file
# =========================================================================
print("\n1. Loading C3D data")
c3d = ezc3d.c3d(str(INPUT_FILE))

# Segment transforms, shape = (4, 4, n_segments, n_frames):
#   axis 0, 1 -> the 4x4 homogeneous transformation matrix (rows, cols)
#   axis 2    -> segment index
#   axis 3    -> frame index
rotations = c3d["data"]["rotations"]

# inspect top-level and data keys + shapes
print("top keys:", list(c3d.keys()))
print("data keys:", list(c3d["data"].keys()))
for k, v in c3d["data"].items():
    print(f"{k}: shape={getattr(v, 'shape', None)}, dtype={getattr(v, 'dtype', None)}")

# Segment labels (one per segment) and the capture rate in Hz.
raw_segment_labels = c3d["parameters"]["ROTATION"]["LABELS"]["value"]
print("ROTATION labels:", raw_segment_labels)

sampling_frequency = c3d["parameters"]["ROTATION"]["RATE"]["value"][0]
n_frames = rotations.shape[3]

# Map every label to its index along the segment axis, then keep only the
# segments we actually want to export (dropping the world reference frame).
segment_index = {clean_segment_label(lbl): i for i, lbl in enumerate(raw_segment_labels)}
segment_names = [name for name in segment_index if name not in EXCLUDE_SEGMENTS]

print(
    f"   Found {len(raw_segment_labels)} segments "
    f"({len(segment_names)} exported, skipping {sorted(EXCLUDE_SEGMENTS)}), "
    f"{n_frames} frames at {sampling_frequency:.1f} Hz"
)


# =========================================================================
# 2) Convert transforms to positions, and build matching channel metadata
# =========================================================================
print("\n2. Extracting segment positions and building BIDS channel metadata")

# `data` holds one column per segment/axis; `channels` holds the BIDS metadata
# describing each of those columns. They are built together in the same loop so
# every column has exactly one matching Channel, in the same order.
#
# A segment's position is the translation column of its 4x4 transform:
#   rotations[:3, 3, seg_idx, :]  ->  (3, n_frames) = X, Y, Z over time.
# Theia3D already stores translations in metres, so no unit conversion is needed
# (verified: pelvis sits ~1 m off the floor, bottom matrix row is [0, 0, 0, 1]).
data = {}
channels = []

for segment in segment_names:
    seg_idx = segment_index[segment]
    xyz = rotations[:3, 3, seg_idx, :]  # (3, n_frames)

    for axis_idx, axis in enumerate(AXES):
        name = channel_name(segment, axis)

        # Column in the data table...
        data[name] = xyz[axis_idx]

        # ...and the BIDS Channel that describes it (POS = position data).
        channels.append(
            Channel(
                channel_name=name,
                channel_component=axis,
                channel_type="POS",
                channel_tracked_point=segment,
                channel_units="m",
            )
        )

df = pd.DataFrame(data)
print(f"   Built {df.shape[1]} channels ({len(segment_names)} segments x {len(AXES)} axes)")
print(df.head())


# =========================================================================
# 3) Assemble the MotionData object
# =========================================================================
print("\n3. Creating MotionData object")

# Each unique tracked point (segment) counts once, regardless of its 3 axes.
tracked_points_count = len({c.channel_tracked_point for c in channels})

motion = MotionData(
    subject=subject,
    session=session,
    task_name=task_name,
    tracksys=tracksys,
    tracked_points_count=tracked_points_count,
    data=df.to_numpy(),
    sampling_frequency=sampling_frequency,
    recording_duration=n_frames / sampling_frequency,
    channels=channels,
)

# Run the package's internal consistency checks (e.g. data columns vs channels).
validate_motion_data(motion)
print("   Package internal validation passed")


# =========================================================================
# 4) Export to BIDS
# =========================================================================
print(f"\n4. Exporting to BIDS format at {bids_root}")

# Create the sub-/ses-/motion directory tree and the top-level dataset metadata.
motion_dir = create_bids_directory_structure(
    base_dir=bids_root,
    subject=subject,
    session=session,
)

export_dataset_description(
    bids_root=bids_root,
    name="Theia3D Motion Dataset",
    authors=["Julius Welzel"],
    dataset_type="raw",
    task_description="Theia3D markerless segment poses",
)

# Write the *_motion.tsv / *_channels.tsv / *_motion.json files.
export_bids_motion(
    data=motion,
    out_dir=motion_dir,
    validate=True,
    overwrite=True,
)
print("   Export completed")


# =========================================================================
# 5) Sanity-check plots: read the exported TSV back, then visualise
# =========================================================================
print("\n5. Plotting exported data for a quick visual check")

bids_file = (
    motion_dir
    / f"sub-{subject}_ses-{session}_task-{task_name}_tracksys-{tracksys}_motion.tsv"
)

# Reload from disk to confirm the file round-trips correctly.
# IMPORTANT: BIDS motion.tsv files are written WITHOUT a header row (the column
# descriptions live in the companion channels.tsv). So we read with
# `header=None` and re-attach the channel names ourselves, in the same order
# they were exported.
column_names = [c.channel_name for c in channels]
exported = pd.read_csv(bids_file, sep="\t", header=None, names=column_names)


def segment_xyz(frame_df: pd.DataFrame, segment: str, frame: int):
    """Return the (x, y, z) position of a segment at a given frame, or None."""
    cols = [channel_name(segment, axis) for axis in AXES]
    if not all(c in frame_df.columns for c in cols):
        return None
    return frame_df.loc[frame, cols].to_numpy(dtype=float)


# --- 5a) Stick-figure skeleton at the middle frame ---------------------------
frame = n_frames // 2
fig = plt.figure(figsize=(12, 6))

ax3d = fig.add_subplot(1, 2, 1, projection="3d")
for parent, child in CONNECTIONS:
    p = segment_xyz(exported, parent, frame)
    c = segment_xyz(exported, child, frame)
    if p is None or c is None:
        continue  # skip connections whose segments aren't in this recording
    ax3d.plot([p[0], c[0]], [p[1], c[1]], [p[2], c[2]], "-o", color="tab:blue")

ax3d.set_title(f"Skeleton (frame {frame})")
ax3d.set_xlabel("X (m)")
ax3d.set_ylabel("Y (m)")
ax3d.set_zlabel("Z (m)")

# --- 5b) Trajectory of one segment over time --------------------------------
ax2d = fig.add_subplot(1, 2, 2)
segment = segment_names[0]
for axis in AXES:
    name = channel_name(segment, axis)
    ax2d.plot(exported[name], label=name)

ax2d.set_title(f"Segment {segment} trajectory")
ax2d.set_xlabel("Frame")
ax2d.set_ylabel("Position (m)")
ax2d.legend()
ax2d.grid(True)

plt.tight_layout()
plt.show()
