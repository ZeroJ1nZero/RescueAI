"""E0 diagnostics on measured inputs; unknown physical semantics fail the gate."""
import os
import tempfile
from pathlib import Path
import numpy as np
from PIL import Image

from .dataset_adapter import load_dataset, depth_meters, timestamp_stats, match_stamps, resolve_transform
from .export import write_json, sha256, protect_source


def plotting():
    os.environ.setdefault("MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "fire-vision-matplotlib"))
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    return plt


def validate_input(root, config, out):
    root, out = Path(root), Path(out)
    protect_source(out,root)
    manifest, calibration = load_dataset(root)
    streams, review = manifest["streams"], calibration.get("review", {})
    issues = []
    def issue(code, detail, severity="error"):
        issues.append({"code": code, "detail": detail, "severity": severity})
    result = {"status": "running", "input_manifest_sha256": sha256(root / "manifest.json"),
              "input_calibration_sha256": sha256(root / "calibration.json"), "issues": issues,
              "timestamp_unit": "ns", "depth_unit": "m", "timestamps": {}, "transforms": {},
              "source": manifest["source"], "segment": config["segment"], "input_file_sha256": {},
              "not_validated": ["SLAM", "Orin performance", "physical sensor accuracy", "body-worn motion", "absolute heading"]}
    if not 30 <= config["segment"]["duration_s"] <= 60:
        issue("e0_duration", "E0 requires a 30–60 second initial segment")
    source = manifest["source"]
    ds = config["dataset"]
    if not ds["provenance_verified"] or not ds.get("provenance_evidence"):
        issue("provenance_unverified", "Confirm downloaded dataset/device identity and retain source evidence")
    if any(source.get(k) != ds.get(k) for k in ("identity", "sensor", "sequence")):
        issue("source_config_mismatch", "Normalized source identity/sensor/sequence differs from current config")
    if review.get("rgb_depth_registered") is not True or not review.get("registration_evidence"):
        issue("registration_unverified", "Equal resolution/topic name alone does not establish RGB-depth registration")
    if review.get("camera_imu_direction_verified") is not True or not review.get("extrinsics_evidence"):
        issue("extrinsics_direction_unverified", "Review T_camera_imu direction and source calibration release")
    if review.get("release_corrections_verified") is not True:
        issue("release_corrections_unverified", "Check OpenLORIS historical IMU extrinsic corrections; do not modify reference data")
    if (review.get("imu_accel_unit") != "m/s^2" or review.get("imu_gyro_unit") != "rad/s" or
        not review.get("imu_axes") or not isinstance(review.get("imu_includes_gravity"), bool) or
        not review.get("imu_semantics_evidence")):
        issue("imu_semantics_unverified", "Acceleration/gyro units, axes and gravity inclusion require evidence")
    if not calibration.get("imu_intrinsics"):
        issue("imu_intrinsics_missing", "Raw IMU intrinsic calibration was not found; E2 requires its review", "warning")
    period = {"rgb": 1e9/30, "depth": 1e9/30, "accel": 1e9/250, "gyro": 1e9/400}
    start, stop = manifest["extraction"]["start_ns"], manifest["extraction"]["stop_ns"]
    requested_ns = round(config["segment"]["duration_s"] * 1e9)
    if stop - start != requested_ns:
        issue("segment_mismatch", "Extract again using this config's requested duration; no silent window changes")
    if manifest["extraction"].get("requested",{}).get("start_offset_s") != config["segment"]["start_offset_s"]:
        issue("segment_offset_mismatch", "Requested start offset differs from the extracted window or is unavailable")
    for key, rows in streams.items():
        stamps = [r["timestamp_ns"] for r in rows]
        stat = timestamp_stats(stamps, period[key], config["sync"]["gap_factor"])
        stat["header_minus_record_ns"] = summary([r["timestamp_ns"] - r["record_ns"] for r in rows])
        stat["frames"] = sorted({r["frame_id"] for r in rows})
        result["timestamps"][key] = stat
        if not rows:
            issue(f"{key}_missing", "No samples in requested segment")
        if stat["backwards"] or stat["duplicates"]:
            issue(f"{key}_timestamp_order", "Non-increasing header timestamps; original order retained")
        if stat["gaps"]:
            issue(f"{key}_gaps", f"{stat['gaps']} intervals exceed nominal period × gap_factor; inspect losses")
        if rows and (min(stamps) < start or max(stamps) >= stop):
            issue(f"{key}_out_of_window", "Header timestamps outside extraction window")
        if not rows or (max(stamps)-min(stamps) < requested_ns - 2 * period[key]) or (rows and abs(min(stamps)-start)>2*period[key]):
            issue(f"{key}_coverage", "Requested duration not fully covered by this stream; shorter recordings must be reported")
        if len(stat["frames"]) != 1:
            issue(f"{key}_frames", "Expected a single stable frame_id per stream")
    cameras = calibration.get("cameras", [])
    camera = cameras[0] if len(cameras) == 1 else None
    if camera is None:
        issue("invalid_camera_calibration", "Exactly one stable CameraInfo profile required")
    else:
        try:
            K, D = np.asarray(camera["K"], float).reshape(3, 3), np.asarray(camera["D"], float)
            R, P = np.asarray(camera["R"],float).reshape(3,3), np.asarray(camera["P"],float).reshape(3,4)
            if (not np.isfinite(R).all() or not np.isfinite(P).all() or
                not np.allclose(R.T @ R,np.eye(3),atol=1e-5) or not np.isclose(np.linalg.det(R),1,atol=1e-5) or
                P[0,0] <= 0 or P[1,1] <= 0 or not np.allclose(P[2],[0,0,1,0])):
                raise ValueError("invalid CameraInfo rectification R or projection P")
            if (not np.isfinite(K).all() or not np.isfinite(D).all() or K[0,0] <= 0 or K[1,1] <= 0 or
                not np.allclose(K[2], [0,0,1]) or camera["width"] <= 0 or camera["height"] <= 0 or
                not 0 <= K[0,2] <= camera["width"] or not 0 <= K[1,2] <= camera["height"]):
                raise ValueError("invalid focal length, principal point, distortion or image size")
            if camera["distortion_model"] not in {"plumb_bob", "rational_polynomial", "equidistant"}:
                raise ValueError("unsupported/unknown distortion model")
            if D.size not in {4,5,8,12,14}:
                raise ValueError("unexpected distortion coefficient count")
            result["camera"] = camera
            result["camera"]["rectification_required"] = bool(np.any(np.abs(D) > 1e-10))
            if result["camera"]["rectification_required"]:
                issue("rectification_required", "Nonzero distortion preserved; E1 must rectify RGB and aligned depth with identical geometry", "warning")
        except (KeyError, ValueError, TypeError) as e:
            issue("invalid_camera_calibration", str(e))
        for key in ("accel", "gyro"):
            try:
                frames = result["timestamps"][key]["frames"]
                result["transforms"][f"T_camera_{key}"] = resolve_transform(calibration.get("transforms", []), camera["frame_id"], frames[0])
            except (ValueError, KeyError, IndexError) as e:
                issue(f"{key}_extrinsic_missing", str(e))
    pairs, missing = [], []
    try:
        pairs, missing = match_stamps([r["timestamp_ns"] for r in streams["rgb"]],
                                     [r["timestamp_ns"] for r in streams["depth"]],
                                     round(config["sync"]["rgb_depth_tolerance_s"] * 1e9))
    except ValueError as e:
        issue("synchronization_invalid", str(e))
    result["rgb_depth"] = {"matched": len(pairs), "unmatched_rgb": len(missing),
                            "unmatched_depth": len(streams["depth"]) - len(pairs),
                            "signed_depth_minus_rgb_ns": summary([p[2] for p in pairs]),
                            "absolute_delta_ns": summary([abs(p[2]) for p in pairs]),
                            "policy": "ordered nearest one-to-one; no stamp replacement, interpolation or reuse"}
    if missing or len(pairs) != len(streams["depth"]):
        issue("rgb_depth_unmatched", "Unmatched RGB/depth frames must be reviewed before E1")
    scale_ok = ds["depth_scale_m"] is not None and ds["provenance_verified"]
    if not scale_ok:
        issue("depth_unit_unverified", "No metric conversion or depth preview claimed without confirmed scale")
    rgb_meta, depth_meta, valid_count, pixel_count, preview = [], [], 0, 0, None
    depth_min, depth_max = None, None
    quality = []
    for key in ("rgb", "depth"):
        for row in streams[key]:
            try:
                array = np.load(root / row["path"], allow_pickle=False)
                if row["path"] not in result["input_file_sha256"]:
                    result["input_file_sha256"][row["path"]] = sha256(root / row["path"])
                shape = array.shape
                if key == "rgb":
                    if array.ndim != 3 or shape[2] != 3 or array.dtype != np.uint8 or row.get("normalized_encoding") != "rgb8":
                        raise ValueError("RGB must be uint8 HxWx3 in confirmed RGB order")
                    rgb_meta.append((shape[1], shape[0], row["original_encoding"]))
                else:
                    if array.ndim != 2:
                        raise ValueError("depth must be HxW numeric raw measurements")
                    if (row.get("original_encoding") not in {"16UC1","mono16","32FC1"} or
                        (row["original_encoding"] in {"16UC1","mono16"} and array.dtype != np.uint16) or
                        (row["original_encoding"] == "32FC1" and array.dtype != np.float32)):
                        raise ValueError("depth original encoding and raw dtype disagree")
                    depth_meta.append((shape[1], shape[0], str(array.dtype)))
                    if scale_ok:
                        depth = depth_meters(array, config)
                        valid = np.isfinite(depth)
                        valid_count += int(valid.sum())
                        pixel_count += depth.size
                        quality.append({"timestamp_ns":row["timestamp_ns"],"valid_ratio":float(valid.mean())})
                        if valid.any():
                            lo, hi = float(depth[valid].min()), float(depth[valid].max())
                            depth_min = min(depth_min, lo) if depth_min is not None else lo
                            depth_max = max(depth_max, hi) if depth_max is not None else hi
                if camera and (shape[1],shape[0]) != (camera["width"],camera["height"]):
                    raise ValueError("resolution differs from CameraInfo")
                if row["frame_id"] != (camera or {}).get("frame_id"):
                    raise ValueError("RGB/aligned-depth frame differs from CameraInfo optical frame")
                if row.get("sha256") and result["input_file_sha256"][row["path"]] != row["sha256"]:
                    raise ValueError("image hash mismatch")
            except (OSError, ValueError, KeyError) as e:
                issue(f"{key}_image_invalid", f"{row.get('path')}: {e}")
    result["rgb"] = {"resolution_and_original_encoding": [list(x) for x in sorted(set(rgb_meta))], "normalized_order": "RGB"}
    result["depth"] = {"resolution_and_raw_dtype": [list(x) for x in sorted(set(depth_meta))],
                        "scale_m": ds["depth_scale_m"], "invalid_raw": config["depth"]["invalid_raw"],
                        "valid_ratio": valid_count / pixel_count if pixel_count else None,
                        "valid_pixel_count": valid_count if scale_ok else None,
                        "all_invalid_frame_count":sum(q["valid_ratio"]==0 for q in quality),
                        "per_frame_quality":quality,
                        "min_valid_m": depth_min, "max_valid_m": depth_max, "filter_m": config["depth"]}
    if pixel_count and valid_count == 0:
        issue("depth_all_invalid", "All metric depths invalid after configured filtering")
    minimum=config["depth"].get("min_valid_ratio_per_frame",0.05)
    low_quality=[q for q in quality if q["valid_ratio"] < minimum or q["valid_ratio"]==0]
    result["depth"]["low_quality_frame_count"]=len(low_quality)
    result["depth"]["min_valid_ratio_per_frame"]=minimum
    if low_quality:
        issue("depth_invalid_window", f"{len(low_quality)} frames have insufficient valid depth; see per_frame_quality timestamps")
    if len(set(rgb_meta)) > 1 or len(set(depth_meta)) > 1:
        issue("image_profile_changed", "Resolution/encoding changed during segment")
    result["imu"] = {"review": review, "intrinsics_applied": review.get("imu_intrinsics_applied", False),
                     "accel_norm_median": None, "gyro_norm_median": None}
    for key in ("accel", "gyro"):
        try:
            v = np.array([r["value"] for r in streams[key]], float)
            if v.ndim != 2 or v.shape[1] != 3 or not np.isfinite(v).all():
                raise ValueError("finite Nx3 IMU samples required")
            result["imu"][f"{key}_norm_median"] = float(np.median(np.linalg.norm(v, axis=1)))
            result["imu"][f"{key}_axis_std"] = v.std(axis=0).tolist()
            rgb_t = np.array([r["timestamp_ns"] for r in streams["rgb"]], dtype=np.int64)
            imu_t = np.array([r["timestamp_ns"] for r in streams[key]], dtype=np.int64)
            nearest = []
            if len(imu_t) and len(rgb_t) and np.all(np.diff(imu_t) > 0):
                for t in rgb_t:
                    j = int(np.searchsorted(imu_t,t))
                    nearest.append(int(min(abs(imu_t[k]-t) for k in {max(0,j-1),min(len(imu_t)-1,j)})))
            result["imu"][f"{key}_nearest_rgb_delta_ns"] = summary(nearest)
        except (ValueError, KeyError) as e:
            issue(f"{key}_values_invalid", str(e))
    result["imu"]["gravity_note"] = "Acceleration norm is a diagnostic, not evidence of axis convention or gravity semantics; yaw unobservable without other constraints."
    # Diagnostics can still be generated for a failed physical-verification gate.
    plt = plotting()
    fig, axes = plt.subplots(2, 1, figsize=(10, 6), constrained_layout=True)
    for ax, key in zip(axes, ("accel", "gyro")):
        rows = streams[key]
        if rows:
            v = np.asarray([r["value"] for r in rows], float)
            if v.shape == (len(rows),3):
                ax.plot([(r["timestamp_ns"]-start)/1e9 for r in rows], v)
        ax.set(xlabel="original header time - segment start (s)", ylabel=f"{key}: " + (review.get("imu_accel_unit" if key=="accel" else "imu_gyro_unit") or "UNVERIFIED units"))
        ax.grid(True)
    fig.savefig(out / "imu_plot.png", dpi=110); plt.close(fig)
    if pairs and scale_ok:
        i, j, _ = pairs[0]
        try:
            rgb = np.load(root / streams["rgb"][i]["path"], allow_pickle=False)
            depth = depth_meters(np.load(root / streams["depth"][j]["path"], allow_pickle=False),config)
            fig, axes = plt.subplots(1,2,figsize=(10,4),constrained_layout=True)
            axes[0].imshow(rgb); axes[0].set_title(f"RGB / {streams['rgb'][i]['timestamp_ns']} ns")
            image = axes[1].imshow(depth, vmin=config["depth"]["min_m"],vmax=config["depth"]["max_m"],cmap="viridis")
            axes[1].set_title("Depth (m); invalid pixels masked")
            fig.colorbar(image,ax=axes[1],label="m")
            fig.savefig(out / "rgb_depth_preview.png",dpi=110); plt.close(fig)
            folder = out / "evidence_frames"; folder.mkdir(exist_ok=True)
            Image.fromarray(rgb).save(folder / f"rgb_{streams['rgb'][i]['timestamp_ns']}.png")
            fig, ax = plt.subplots(figsize=(8,3),constrained_layout=True)
            ax.hist([p[2]/1e6 for p in pairs],bins=30)
            ax.set(xlabel="depth - RGB header time (ms)",ylabel="pairs")
            fig.savefig(out / "sync_histogram.png",dpi=110); plt.close(fig)
        except (ValueError, OSError, TypeError) as e:
            issue("preview_failed",str(e))
    result["status"] = "failed" if any(x["severity"] == "error" for x in issues) else "passed"
    write_json(out / "calibration.json", calibration)
    write_json(out / "e0_validation.json", result)
    return result


def summary(values):
    if not len(values):
        return {"count": 0, "min": None, "max": None, "p50": None, "p95": None}
    return {"count": len(values), "min": float(min(values)), "max": float(max(values)),
            "p50": float(np.percentile(values,50)), "p95": float(np.percentile(values,95))}
