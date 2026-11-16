import json
import math
from pathlib import Path


def load_config(path):
    c = json.loads(Path(path).read_text())
    validate_config(c)
    return c


def validate_config(c):
    def number(value, name, low=0, positive=False):
        if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
            raise ValueError(f"{name}: finite number required")
        if value < low or (positive and value == low):
            raise ValueError(f"{name}: outside allowed range")
    number(c["segment"]["start_offset_s"], "start_offset_s")
    number(c["segment"]["duration_s"], "duration_s", positive=True)
    number(c["replay"]["rate"], "rate", positive=True)
    for k in ("rgb_depth_tolerance_s", "pose_tolerance_s"):
        number(c["sync"][k], k)
    number(c["sync"]["gap_factor"], "gap_factor", low=1, positive=True)
    number(c["depth"]["min_m"], "min_m", positive=True)
    number(c["depth"]["max_m"], "max_m", low=c["depth"]["min_m"], positive=True)
    number(c["depth"].get("min_valid_ratio_per_frame",0.05), "min_valid_ratio_per_frame")
    if c["depth"].get("min_valid_ratio_per_frame",0.05) > 1:
        raise ValueError("minimum valid depth ratio must be within [0,1]")
    number(c["mapping"]["resolution_m"], "resolution_m", positive=True)
    if not c["mapping"]["height_min_m"] < c["mapping"]["height_max_m"]:
        raise ValueError("height bounds invalid")
    number(c["detection"]["frequency_hz"], "frequency_hz", positive=True)
    if c["detection"]["enabled"]:
        raise ValueError("detection integration deferred until E1 passes")
    ds = c["dataset"]
    scale = ds["depth_scale_m"]
    if scale is not None:
        number(scale, "depth_scale_m", positive=True)
        if not ds["provenance_verified"] or not ds.get("provenance_evidence"):
            raise ValueError("depth scale requires verified provenance and evidence")
        if scale == 0.001 and (ds["identity"] != "OpenLORIS-Scene" or ds["sensor"] != "D435i"):
            raise ValueError("0.001 profile requires confirmed OpenLORIS-Scene D435i")
    topics = list(c["topics"].values())
    if len(topics) != len(set(topics)) or not all(t.startswith("/") for t in topics):
        raise ValueError("topics must be distinct absolute names")
