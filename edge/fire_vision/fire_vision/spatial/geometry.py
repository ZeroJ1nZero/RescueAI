"""Metric geometry. Matrices are row-major; p_destination = T @ p_source.

map_local axes are forward/left/up, optical axes right/down/forward.
Depth-to-color projection always uses calibration, including distortion; matching
array shapes alone never establish registration.
"""
import numpy as np

from ..object_projection import rigid_matrix


AXIS_MAP_FROM_OPTICAL = np.array([[0., 0., 1., 0.], [-1., 0., 0., 0.],
                                  [0., -1., 0., 0.], [0., 0., 0., 1.]])


class Synchronizer:
    """Audit supplied framesets; delta_us is depth time minus color time.

    pair_times provides nearest-neighbor indices for independent recorded streams.
    Online source framesets are preserved, not silently replaced by fabricated frames.
    """
    def __init__(self, tolerance_us=20000):
        if int(tolerance_us) < 0:
            raise ValueError("sync tolerance_us must be nonnegative")
        self.tolerance_us = int(tolerance_us)
        self.last = {}
        self.events = []

    def pair_times(self, color_times, depth_times):
        depths = np.asarray(depth_times, dtype=np.int64)
        if len(depths) and np.any(np.diff(depths) < 0):
            raise ValueError("depth timeline must be monotonic within one clock epoch")
        result = []
        for i, t in enumerate(color_times):
            if len(depths) == 0:
                result.append(dict(color_index=i, depth_index=-1, delta_us=0, valid=False, reason="depth_missing"))
                continue
            at = int(np.searchsorted(depths, t))
            j = min({max(0, at - 1), min(at, len(depths) - 1)}, key=lambda k: (abs(int(depths[k]) - int(t)), k))
            delta = int(depths[j]) - int(t)
            result.append(dict(color_index=i, depth_index=j, delta_us=delta,
                               valid=abs(delta) <= self.tolerance_us,
                               reason="ok" if abs(delta) <= self.tolerance_us else "sync_tolerance_exceeded"))
        return result

    def pair(self, capture, color_index, depth_index):
        # Only this call's events are retained; the writer owns session history.
        self.events = []
        reason = "ok"
        for sample in (capture.color, capture.depth):
            if sample is None:
                continue
            old = self.last.get(sample.stream)
            current = (sample.clock, sample.timestamp_unit, int(sample.sensor_timestamp), int(sample.frame_id), int(sample.time_us))
            if old is not None and (current[:2] != old[:2] or current[2] < old[2] or current[3] < old[3] or current[4] < old[4]):
                reason = "timestamp_reset"
                self.events.append(dict(code=reason, stream=sample.stream, time_us=int(sample.time_us),
                                        detail="Clock identity, timestamp or frame sequence regressed; new epoch/submap required"))
            self.last[sample.stream] = current
        color, depth = capture.color, capture.depth
        delta = int(depth.time_us) - int(color.time_us) if color is not None and depth is not None else 0
        if reason == "ok":
            if color is None or depth is None:
                reason = "color_missing" if color is None else "depth_missing"
            elif color.clock != depth.clock:
                reason = "clock_conversion_unverified"
            elif abs(delta) > self.tolerance_us:
                reason = "sync_tolerance_exceeded"
        return dict(color_index=int(color_index), depth_index=int(depth_index), delta_us=delta,
                    valid=reason == "ok", reason=reason)


def _camera(cal):
    K = np.asarray(cal["K"], float).reshape(3, 3)
    if not np.isfinite(K).all() or K[0, 0] <= 0 or K[1, 1] <= 0 or not np.allclose(K[2], [0, 0, 1]):
        raise ValueError("finite pinhole calibration required")
    distortion = np.asarray(cal.get("distortion", [0.] * 5), float).ravel()
    model = cal.get("distortion_model", "none")
    if model not in {"none", "brown_conrady", "brown_conrady_k6", "plumb_bob", "rational_polynomial"}:
        raise ValueError(f"unsupported distortion model: {model}")
    if not np.isfinite(distortion).all() or len(distortion) not in {0, 4, 5, 8}:
        raise ValueError("distortion must contain 0, 4, 5 or 8 Brown-Conrady coefficients")
    if model == "none" and np.any(distortion):
        raise ValueError("nonzero distortion declared as none")
    return K, np.pad(distortion, (0, 8 - len(distortion)))


def _distort(x, y, d):
    k1, k2, p1, p2, k3, k4, k5, k6 = d
    r2 = x*x + y*y
    with np.errstate(invalid="ignore", divide="ignore", over="ignore"):
        radial = (1 + k1*r2 + k2*r2*r2 + k3*r2*r2*r2) / (1 + k4*r2 + k5*r2*r2 + k6*r2*r2*r2)
        return x*radial + 2*p1*x*y + p2*(r2 + 2*x*x), y*radial + p1*(r2 + 2*y*y) + 2*p2*x*y


def _rays(shape, K, distortion):
    v, u = np.indices(shape, dtype=float)
    distorted = np.stack([u, v, np.ones_like(u)], -1) @ np.linalg.inv(K).T
    xd, yd = distorted[..., 0], distorted[..., 1]
    x, y = xd.copy(), yd.copy()
    # Fixed-point inversion for the documented Brown-Conrady model. Residual
    # validation rejects pathological calibration instead of trusting divergence.
    if np.any(distortion):
        for _ in range(20):
            px, py = _distort(x, y, distortion)
            x += xd - px
            y += yd - py
        px, py = _distort(x, y, distortion)
        valid = np.isfinite(x + y) & (np.abs(px-xd) < 1e-6) & (np.abs(py-yd) < 1e-6)
        x[~valid] = np.nan
        y[~valid] = np.nan
    return np.stack([x, y, np.ones_like(x)], -1)


class Preprocessor:
    def __init__(self, calibration, config):
        self.calibration = calibration
        self.Kd, self.Dd = _camera(calibration["depth"])
        self.Kc, self.Dc = _camera(calibration["color"])
        self.T_color_from_depth = rigid_matrix(calibration["T_color_from_depth"])
        self.minimum = float(config.get("min_m", .1))
        self.maximum = float(config.get("max_m", 10.))
        if not 0 < self.minimum < self.maximum:
            raise ValueError("depth range must satisfy 0 < min_m < max_m")
        self._ray_cache = None
        self.feature = dict(status="success", backend="calibrated_brown_conrady", reason=None)

    def process(self, capture):
        if capture.color is None or capture.depth is None:
            raise ValueError("color and depth required")
        raw = np.asarray(capture.depth.data)
        color = np.asarray(capture.color.data)
        if raw.ndim != 2 or color.ndim != 3 or color.shape[2] != 3:
            raise ValueError("depth HxW and RGB HxWx3 required")
        for name, shape in (("depth", raw.shape), ("color", color.shape[:2])):
            camera = self.calibration[name]
            if shape != (int(camera["height"]), int(camera["width"])):
                raise ValueError(f"{name} frame dimensions changed from calibration")
        scale = capture.depth.depth_scale_m
        if scale is None or not np.isfinite(scale) or scale <= 0:
            raise ValueError("positive finite measured depth_scale_m required")
        metric = raw.astype(np.float64) * float(scale)
        valid = np.isfinite(metric) & (metric >= self.minimum) & (metric <= self.maximum) & (raw != 0)
        if self._ray_cache is None:
            self._ray_cache = _rays(raw.shape, self.Kd, self.Dd)
        points = self._ray_cache * metric[..., None]
        valid &= np.isfinite(points).all(-1)
        points[~valid] = np.nan
        pc = points @ self.T_color_from_depth[:3, :3].T + self.T_color_from_depth[:3, 3]
        with np.errstate(divide="ignore", invalid="ignore"):
            x, y = _distort(pc[..., 0]/pc[..., 2], pc[..., 1]/pc[..., 2], self.Dc)
            uvw = np.stack([x, y, np.ones_like(x)], -1) @ self.Kc.T
        uv = uvw[..., :2]
        h, w = color.shape[:2]
        finite_uv = np.isfinite(uv).all(-1)
        uv_int = np.rint(np.where(finite_uv[..., None], uv, -1)).astype(np.int64)
        visible = valid & finite_uv & (pc[..., 2] > 0) & (uv_int[..., 0] >= 0) & (uv_int[..., 0] < w) & (uv_int[..., 1] >= 0) & (uv_int[..., 1] < h)
        # Resolve occlusion with the nearest surface in the color optical frame.
        flat = np.flatnonzero(visible)
        order = flat[np.argsort(pc.reshape(-1, 3)[flat, 2], kind="stable")]
        pixels = uv_int.reshape(-1, 2)[order]
        linear = pixels[:, 1] * w + pixels[:, 0]
        _, keep = np.unique(linear, return_index=True)
        chosen = order[keep]
        pixel = uv_int.reshape(-1, 2)[chosen]
        registered = np.full((h, w, 3), np.nan)
        registered_color_z = np.zeros((h, w), np.float32)
        registered[pixel[:, 1], pixel[:, 0]] = points.reshape(-1, 3)[chosen]
        registered_color_z[pixel[:, 1], pixel[:, 0]] = pc.reshape(-1, 3)[chosen, 2]
        point_colors = np.zeros((*raw.shape, 3), np.uint8)
        point_colors[visible] = color[uv_int[..., 1][visible], uv_int[..., 0][visible]]
        return dict(points_depth=points, valid=valid, color_uv=uv, color_visible=visible,
                    point_colors=point_colors, aligned_points_depth=registered,
                    aligned_depth_color_m=registered_color_z, color=color,
                    metric_depth_m=metric, valid_depth_ratio=float(valid.mean()))


class SpatialEstimator:
    """Representative visible surface; no object center/size or error bound claim."""
    def estimate(self, bbox, processed):
        h, w = processed["aligned_points_depth"].shape[:2]
        x0, y0, x1, y1 = bbox
        x0, y0 = max(0, int(np.floor(x0))), max(0, int(np.floor(y0)))
        x1, y1 = min(w, int(np.ceil(x1))), min(h, int(np.ceil(y1)))
        empty = dict(point_camera_m=None, valid_depth_ratio=0., depth_variance_m2=None, reason="invalid_depth")
        if x1 <= x0 or y1 <= y0:
            return empty
        roi = processed["aligned_points_depth"][y0:y1, x0:x1]
        valid = np.isfinite(roi).all(-1) & (roi[..., 2] > 0)
        if not valid.any():
            return empty
        points = roi[valid]
        median = np.median(points[:, 2])
        mad = np.median(np.abs(points[:, 2] - median))
        consistent = np.abs(points[:, 2] - median) <= max(.02, min(.1*median, 3*1.4826*mad))
        selected = points[consistent]
        if not len(selected):
            return empty
        representative = np.median(selected, axis=0)
        return dict(point_camera_m=representative.tolist(), valid_depth_ratio=float(len(selected) / ((x1-x0)*(y1-y0))),
                    depth_variance_m2=float(np.var(selected[:, 2])), reason=None)
