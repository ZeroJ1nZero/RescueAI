"""Read-only bag adapter. No odometry, LiDAR or reference-pose input paths."""
from collections import deque
import math
from pathlib import Path
import json
import numpy as np

from .config import validate_config
from .export import sha256, write_json, protect_source
from .object_projection import rigid_matrix


def depth_meters(raw, config):
    validate_config(config)
    scale = config["dataset"]["depth_scale_m"]
    if scale is None:
        raise ValueError("depth_scale_m unverified")
    raw = np.asarray(raw)
    if raw.ndim != 2 or not (raw.dtype == np.uint16 or raw.dtype.kind == "f"):
        raise ValueError("raw uint16 or metric float single-channel depth required; colorized/8-bit depth unsupported")
    if raw.dtype.kind == "f" and scale != 1.0:
        raise ValueError("float depth must be confirmed metric values with scale 1.0; never multiply metric float by 0.001")
    if raw.dtype == np.uint16 and config["dataset"]["identity"] == "OpenLORIS-Scene" and config["dataset"]["sensor"] == "D435i" and scale != 0.001:
        raise ValueError("confirmed OpenLORIS D435i uint16 depth requires scale 0.001")
    depth = raw.astype(np.float32) * scale
    invalid = ~np.isfinite(depth) | (depth < config["depth"]["min_m"]) | (depth > config["depth"]["max_m"])
    for value in config["depth"]["invalid_raw"]:
        invalid |= raw == value
    depth[invalid] = np.nan
    return depth


def decode_image(msg):
    formats = {"rgb8": ("u1", 3), "bgr8": ("u1", 3), "16UC1": ("u2", 1),
               "mono16": ("u2", 1), "32FC1": ("f4", 1)}
    if msg.encoding not in formats:
        raise ValueError(f"unsupported image encoding: {msg.encoding}; compressed images need a dedicated decoder")
    dtype, channels = formats[msg.encoding]
    dt = np.dtype((">" if msg.is_bigendian else "<") + dtype)
    row_bytes = msg.width * channels * dt.itemsize
    raw = np.frombuffer(msg.data, dtype=np.uint8)
    if msg.height <= 0 or msg.width <= 0 or msg.step < row_bytes or raw.size != msg.height * msg.step:
        raise ValueError("image size/stride/data length invalid")
    packed = raw.reshape(msg.height, msg.step)[:, :row_bytes].copy()
    shape = (msg.height, msg.width, channels) if channels > 1 else (msg.height, msg.width)
    out = packed.view(dt).reshape(shape).astype(dt.newbyteorder("="))
    return out[..., ::-1].copy() if msg.encoding == "bgr8" else out


def stamp_ns(msg):
    return int(msg.header.stamp.sec) * 1_000_000_000 + int(msg.header.stamp.nanosec)


def timestamp_stats(stamps, expected_period_ns=None, gap_factor=2):
    t = np.asarray(stamps, dtype=np.int64)
    d = np.diff(t)
    period = expected_period_ns or (float(np.median(d[d > 0])) if np.any(d > 0) else None)
    # Integer ns stamps can round two nominal 30Hz periods down by <1ns.
    gaps = d >= math.floor(period * gap_factor) if period else np.zeros(d.shape, bool)
    return {"count": len(stamps), "first_ns": int(t[0]) if len(t) else None,
            "last_ns": int(t[-1]) if len(t) else None, "duplicates": int(np.sum(d == 0)),
            "backwards": int(np.sum(d < 0)), "gaps": int(gaps.sum()),
            "estimated_missing_samples": int(sum(max(0, round(x / period) - 1) for x in d[gaps])) if period else None,
            "expected_period_ns": period, "period_basis": "nominal" if expected_period_ns else "positive_delta_median",
            "max_interval_ns": int(d.max()) if len(d) else None}


def match_stamps(rgb_stamps, depth_stamps, tolerance_ns):
    """Ordered nearest, one-to-one matching; no reordering or depth reuse."""
    if tolerance_ns < 0:
        raise ValueError("negative tolerance")
    if any(b <= a for a, b in zip(rgb_stamps, rgb_stamps[1:])) or any(b <= a for a, b in zip(depth_stamps, depth_stamps[1:])):
        raise ValueError("timestamps must be strictly increasing; inspect duplicates/backwards first")
    pairs, missing, j = [], [], 0
    for i, t in enumerate(rgb_stamps):
        while j < len(depth_stamps) and depth_stamps[j] < t - tolerance_ns:
            j += 1
        k = j
        while k + 1 < len(depth_stamps) and abs(depth_stamps[k + 1] - t) < abs(depth_stamps[k] - t):
            k += 1
        if k < len(depth_stamps) and abs(depth_stamps[k] - t) <= tolerance_ns:
            pairs.append((i, k, depth_stamps[k] - t))
            j = k + 1
        else:
            missing.append(i)
    return pairs, missing


def open_reader(path):
    from rosbags.highlevel import AnyReader
    from rosbags.typesys import Stores, get_typestore
    return AnyReader([Path(path)], default_typestore=get_typestore(Stores.ROS2_HUMBLE))


def inventory_bag(path):
    with open_reader(path) as reader:
        return {"path": str(Path(path).resolve()), "format": "rosbag2" if reader.is2 else "rosbag1",
                "record_start_ns": reader.start_time, "record_end_ns": reader.end_time,
                "record_duration_s": reader.duration / 1e9,
                "topics": [{"topic": k, "msgtype": v.msgtype, "count": v.msgcount} for k, v in reader.topics.items()],
                "note": "record time inventory; header ranges require extraction. Topic names do not verify sensor identity."}


def plain(value):
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    if hasattr(value, "__dataclass_fields__"):
        return {k: plain(getattr(value, k)) for k in value.__dataclass_fields__ if not k.startswith("__")}
    if isinstance(value, (list, tuple)):
        return [plain(x) for x in value]
    return value


def extract_bag(path, out, config):
    """Extract selected header-time window. Never mutate or fix the source bag."""
    validate_config(config)
    source = Path(path).resolve()
    protect_source(out, source)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    write_json(out / "extraction.json", {"status": "running", "source": str(source), "config": config})
    try:
        manifest = _extract_bag(path, out, config)
    except Exception as e:
        write_json(out / "extraction.json", {"status": "failed", "source": str(source), "config": config, "reason": str(e)})
        (out / "failures.jsonl").write_text(json.dumps({"stage": "E0_extraction", "code": type(e).__name__, "detail": str(e)}) + "\n")
        raise
    write_json(out / "extraction.json", {"status": "completed", "source": str(source), "config": config})
    return manifest


def _extract_bag(path, out, config):
    inventory = inventory_bag(path)
    write_json(out / "bag_inventory.json", inventory)
    topics = config["topics"]
    required = {topics[k] for k in ("rgb", "depth", "camera_info", "accel", "gyro", "tf_static")}
    present = {t["topic"] for t in inventory["topics"]}
    if not required <= present:
        raise ValueError(f"required topics missing: {sorted(required - present)}; inspect bag and set topics explicitly")
    source = Path(path)
    source_files = [source] if source.is_file() else sorted(p for p in source.rglob("*") if p.is_file())
    manifest = {"format": "fire-vision-normalized-v1", "source": {**config["dataset"], "path": str(source.resolve()),
                "sha256": {str(p.relative_to(source)) if source.is_dir() else p.name: sha256(p) for p in source_files}},
                "extraction": {"requested": config["segment"], "timestamp_basis": "header", "complete": False},
                "streams": {k: [] for k in ("rgb", "depth", "accel", "gyro")}}
    calibration = {"cameras": [], "transforms": [], "imu_intrinsics": [],
                   "transform_convention": "T_parent_child maps child coordinates into parent; column vectors, meters",
                   "review": {"rgb_depth_registered": None, "registration_evidence": None,
                              "camera_imu_direction_verified": None, "extrinsics_evidence": None,
                              "imu_accel_unit": None, "imu_gyro_unit": None, "imu_axes": None,
                              "imu_includes_gravity": None, "imu_semantics_evidence": None,
                              "imu_intrinsics_applied": False, "release_corrections_verified": None}}
    reverse = {v: k for k, v in topics.items()}
    first_rgb = None
    start = stop = None
    # First RGB header establishes offset, independently of bag record timestamps.
    with open_reader(path) as reader:
        rgb_connections = [c for c in reader.connections if c.topic == topics["rgb"]]
        for conn, _, raw in reader.messages(connections=rgb_connections):
            first_rgb = stamp_ns(reader.deserialize(raw, conn.msgtype))
            break
        if first_rgb is None:
            raise ValueError("RGB topic contains no images")
        start = first_rgb + round(config["segment"]["start_offset_s"] * 1e9)
        stop = start + round(config["segment"]["duration_s"] * 1e9)
        manifest["extraction"].update(start_ns=start, stop_ns=stop)
        connections = [c for c in reader.connections if c.topic in reverse]
        for conn, record_ns, raw in reader.messages(connections=connections):
            key = reverse[conn.topic]
            msg = reader.deserialize(raw, conn.msgtype)
            if key == "camera_info":
                entry = {"topic": conn.topic, "header_ns": stamp_ns(msg), "frame_id": msg.header.frame_id,
                         "width": int(msg.width), "height": int(msg.height),
                         **{k: plain(getattr(msg, k.lower(), getattr(msg, k, None))) for k in ("K", "D", "R", "P")},
                         "distortion_model": msg.distortion_model}
                previous = calibration["cameras"][-1] if calibration["cameras"] else None
                if previous is None or any(entry[k] != previous[k] for k in entry if k != "header_ns"):
                    calibration["cameras"].append(entry)
                continue
            if key == "tf_static":
                for tf in msg.transforms:
                    entry = plain(tf)
                    if entry not in calibration["transforms"]:
                        calibration["transforms"].append(entry)
                continue
            if key.endswith("_info"):
                entry = {"topic": conn.topic, "message": plain(msg)}
                if entry not in calibration["imu_intrinsics"]:
                    calibration["imu_intrinsics"].append(entry)
                continue
            t = stamp_ns(msg)
            if not start <= t < stop:
                continue
            row = {"timestamp_ns": t, "record_ns": int(record_ns), "frame_id": msg.header.frame_id, "topic": conn.topic}
            if key in ("rgb", "depth"):
                arr = decode_image(msg)
                if (key == "rgb" and msg.encoding not in ("rgb8", "bgr8")) or (key == "depth" and arr.ndim != 2):
                    raise ValueError(f"unexpected {key} encoding")
                folder = out / key
                folder.mkdir(exist_ok=True)
                name = f"{key}/{len(manifest['streams'][key]):06d}_{t}.npy"
                np.save(out / name, arr, allow_pickle=False)
                row.update(path=name, sha256=sha256(out / name), original_encoding=msg.encoding, normalized_encoding="rgb8" if key == "rgb" else msg.encoding,
                           width=int(msg.width), height=int(msg.height), dtype=str(arr.dtype))
            else:
                v = msg.linear_acceleration if key == "accel" else msg.angular_velocity
                row["value"] = [float(v.x), float(v.y), float(v.z)]
            manifest["streams"][key].append(row)
    manifest["extraction"]["complete"] = True
    write_json(out / "manifest.json", manifest)
    write_json(out / "calibration.json", calibration)
    return manifest


def load_dataset(path):
    root = Path(path).resolve()
    manifest = json.loads((root / "manifest.json").read_text())
    calibration = json.loads((root / "calibration.json").read_text())
    if manifest.get("format") != "fire-vision-normalized-v1" or not manifest["extraction"]["complete"]:
        raise ValueError("unsupported/incomplete normalized dataset; use extract-bag on a ROS1/ROS2 recording")
    for key in ("rgb", "depth", "accel", "gyro"):
        if key not in manifest["streams"]:
            raise ValueError(f"missing stream {key}")
        for row in manifest["streams"][key]:
            if type(row["timestamp_ns"]) is not int or row["timestamp_ns"] < 0:
                raise ValueError("nonnegative integer nanosecond header required")
            if "path" in row:
                p = (root / row["path"]).resolve()
                if not p.is_relative_to(root) or not p.is_file():
                    raise ValueError("missing or unsafe image path")
    return manifest, calibration


def tf_matrix(entry):
    t = entry["transform"]["translation"]
    q = entry["transform"]["rotation"]
    x, y, z, w = (q[k] for k in ("x", "y", "z", "w"))
    if not np.isclose(x*x + y*y + z*z + w*w, 1, atol=1e-5):
        raise ValueError("non-unit TF quaternion")
    R = np.array([[1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)],
                  [2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w)],
                  [2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y)]])
    T = np.eye(4)
    T[:3, :3] = R
    T[:3, 3] = [t[k] for k in ("x", "y", "z")]
    return rigid_matrix(T)


def resolve_transform(transforms, target, source):
    """Return T_target_source. tf_static parent-child direction is preserved."""
    edges, parents, known = {}, {}, {}
    for tf in transforms:
        parent, child = tf["header"]["frame_id"], tf["child_frame_id"]
        T = tf_matrix(tf)
        if child in parents and parents[child] != parent:
            raise ValueError(f"multiple TF parents for {child}")
        if (parent, child) in known and not np.allclose(known[(parent,child)],T):
            raise ValueError(f"conflicting static transforms for {child}")
        parents[child] = parent
        known[(parent,child)] = T
        ancestor, seen = child, set()
        while ancestor in parents:
            if ancestor in seen:
                raise ValueError("TF cycle detected")
            seen.add(ancestor)
            ancestor = parents[ancestor]
        edges.setdefault(child, []).append((parent, T))
        edges.setdefault(parent, []).append((child, np.linalg.inv(T)))
    queue, visited = deque([(source, np.eye(4))]), set()
    while queue:
        frame, accumulated = queue.popleft()
        if frame == target:
            return accumulated.tolist()
        if frame in visited:
            continue
        visited.add(frame)
        queue.extend((next_frame, T @ accumulated) for next_frame, T in edges.get(frame, []) if next_frame not in visited)
    raise ValueError(f"no static transform {target} <- {source}")
