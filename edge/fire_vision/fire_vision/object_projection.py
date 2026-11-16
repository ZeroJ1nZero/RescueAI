"""Geometric contracts only. No detection integration before E1 passes."""
import math
import numpy as np


def rigid_matrix(T):
    T = np.asarray(T, dtype=float)
    if T.shape != (4, 4) or not np.isfinite(T).all() or not np.allclose(T[3], [0, 0, 0, 1]):
        raise ValueError("finite homogeneous 4x4 matrix required")
    R = T[:3, :3]
    if not np.allclose(R.T @ R, np.eye(3), atol=1e-5) or not np.isclose(np.linalg.det(R), 1, atol=1e-5):
        raise ValueError("proper rigid rotation required")
    return T


def backproject(u, v, depth_m, K):
    K = np.asarray(K, float).reshape(3, 3)
    if not np.isfinite(K).all() or K[0, 0] <= 0 or K[1, 1] <= 0 or not math.isfinite(depth_m) or depth_m <= 0:
        raise ValueError("valid metric depth and intrinsics required")
    if not math.isfinite(u) or not math.isfinite(v):
        raise ValueError("finite pixel required")
    return [(u - K[0, 2]) * depth_m / K[0, 0], (v - K[1, 2]) * depth_m / K[1, 1], depth_m]


def transform_point(point, T_destination_source):
    T = rigid_matrix(T_destination_source)
    p = np.asarray(point, float)
    if p.shape != (3,) or not np.isfinite(p).all():
        raise ValueError("finite point required")
    return (T @ np.r_[p, 1])[:3].tolist()


def project_with_pose(point_camera, timestamp_ns, pose, tolerance_ns):
    if pose is None:
        return None, "pose_missing"
    if abs(pose["timestamp_ns"] - timestamp_ns) > tolerance_ns:
        return None, "pose_time_tolerance_exceeded"
    if point_camera is None:
        return None, "invalid_depth"
    return transform_point(point_camera, pose["T_map_camera"]), "surface_position_approximation"


def observation(session_id, observation_id, timestamp_ns, image_ref, class_label, bbox, camera_frame,
                point_camera_m, pose_ref, keyframe_id, valid_depth_ratio, depth_dispersion, position_status,
                detector_model_version, point_map_m=None):
    o = dict(session_id=session_id, observation_id=observation_id, timestamp=timestamp_ns / 1e9,
             timestamp_ns=timestamp_ns, image_ref=image_ref, class_label=class_label, bbox=bbox, mask_ref=None,
             camera_frame=camera_frame, point_camera_m=point_camera_m, pose_ref=pose_ref, keyframe_id=keyframe_id,
             point_map_m=point_map_m, valid_depth_ratio=valid_depth_ratio, depth_dispersion=depth_dispersion,
             position_status=position_status, detector_model_version=detector_model_version, temperature=None,
             failure_reason=position_status if point_map_m is None else None,
             position_meaning="visible_surface_representative_approximation", layer="unclassified_motion")
    validate_observation(o)
    return o


def validate_observation(o):
    fields = {"session_id", "observation_id", "timestamp", "image_ref", "class_label", "bbox", "mask_ref",
              "camera_frame", "point_camera_m", "pose_ref", "keyframe_id", "point_map_m", "valid_depth_ratio",
              "depth_dispersion", "position_status", "detector_model_version", "temperature", "failure_reason"}
    if not fields <= o.keys():
        raise ValueError("observation schema fields missing")
    for key in ("session_id","observation_id","image_ref","class_label","camera_frame","position_status","detector_model_version"):
        if not isinstance(o[key],str) or not o[key].strip():
            raise ValueError(f"{key} must be a nonempty string")
    if not isinstance(o["timestamp"],(float,int)) or not math.isfinite(o["timestamp"]) or o["timestamp"] < 0:
        raise ValueError("nonnegative finite timestamp required")
    variance=o["depth_dispersion"]
    if variance is not None and (not isinstance(variance,(float,int)) or not math.isfinite(variance) or variance < 0):
        raise ValueError("depth_dispersion must be null or nonnegative finite variance in m^2")
    bbox=o["bbox"]
    if bbox is None:
        if not o["mask_ref"]:
            raise ValueError("bbox or mask reference required")
    else:
        box=np.asarray(bbox,float)
        if box.shape != (4,) or not np.isfinite(box).all() or box[0] < 0 or box[1] < 0 or box[2] <= box[0] or box[3] <= box[1]:
            raise ValueError("bbox must be finite [x0,y0,x1,y1] with positive area")
    if o["temperature"] is not None or not 0 <= o["valid_depth_ratio"] <= 1:
        raise ValueError("temperature must be null; valid depth ratio must be within [0,1]")
    if o["point_map_m"] is None and not o["failure_reason"]:
        raise ValueError("null map point requires failure reason")
    for key in ("point_camera_m", "point_map_m"):
        if o[key] is not None and (np.asarray(o[key]).shape != (3,) or not np.isfinite(o[key]).all()):
            raise ValueError("points must have 3 finite meter values")
    if o["point_map_m"] is not None and (o["point_camera_m"] is None or o["pose_ref"] is None):
        raise ValueError("map coordinate requires camera point and pose reference")
