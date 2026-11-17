"""Owned sensor buffers. Timestamps retain original units and clock identity."""
from dataclasses import dataclass, field
from typing import Optional
import numpy as np


@dataclass
class Sample:
    stream: str
    data: np.ndarray
    frame_id: int
    sensor_timestamp: int
    timestamp_unit: str = "us"
    clock: str = "device"
    host_monotonic_ns: int = 0
    time_us: int = 0
    depth_scale_m: Optional[float] = None


@dataclass
class Capture:
    color: Optional[Sample] = None
    depth: Optional[Sample] = None
    imu: list = field(default_factory=list)
    synthetic_pose: Optional[np.ndarray] = None


# calibration contract (JSON-safe dictionary):
# color/depth: {K:3x3, distortion:[k1,k2,p1,p2,k3], width,height,
#              distortion_model:'brown_conrady'|'none'}
# T_color_from_depth:4x4 (translation meters), depth_registered_to_color:bool
# Metadata: synthetic:bool, device/sdk/firmware/settings, clock_conversion.
# Sources implement open(), captures(stop_event), close(); calibration and metadata
# are available after open(). captures must poll stop_event and own yielded buffers.
# AnalysisPipeline(config, calibration, metadata).process(capture, color_index,
# depth_index) -> dict: pair, detections:list, pose:dict, observations:list,
# points: Nx3 float32 (camera depth frame), point_colors:Nx3 uint8.
