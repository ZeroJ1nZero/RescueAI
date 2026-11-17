"""Analysis workers: calibrated surfaces, inference and optional real odometry.

Open3D is RGB-D odometry, not loop-closing SLAM. No absent estimator is replaced
with identity poses. Synthetic poses are accepted only for synthetic sources.
"""
import time
import numpy as np

from ..object_projection import rigid_matrix, transform_point
from .geometry import AXIS_MAP_FROM_OPTICAL, Preprocessor, SpatialEstimator, Synchronizer
from .inference import Detector, Tracker


class PoseEstimator:
    def __init__(self, config, calibration, metadata):
        self.config, self.calibration = config, calibration
        self.synthetic_input = bool(metadata.get("synthetic", False))
        self.backend = config.get("backend", "disabled")
        self.feature = dict(status="disabled", backend=self.backend, reason="configured_disabled",
                            loop_closure=False, gravity_aligned=False, synthetic=self.backend == "synthetic")
        self.previous = None
        self.T_map_from_color = None
        self.origin = None
        self.submap = -1
        self.last_time = None
        if self.backend not in {"synthetic", "open3d", "disabled"}:
            raise ValueError(f"unsupported pose backend: {self.backend}")
        if self.backend == "synthetic" and not self.synthetic_input:
            raise ValueError("synthetic pose backend requires synthetic input")
        try:
            self.T_color_from_depth = rigid_matrix(calibration["T_color_from_depth"])
        except (ValueError, KeyError, TypeError) as exc:
            self.T_color_from_depth = None
            self.feature["reason"] = f"calibration_invalid: {exc}"
            return
        if self.backend == "synthetic":
            if not self.synthetic_input:
                raise ValueError("synthetic pose backend requires synthetic input")
            self.feature.update(status="success", reason=None)
        elif self.backend == "open3d":
            try:
                import open3d as o3d
                self.o3d = o3d
            except ImportError as exc:
                self.feature["reason"] = f"backend_unavailable: {exc}"
            else:
                self.feature.update(status="success", reason=None, version=o3d.__version__, license="MIT")

    def reset(self):
        self.previous = None
        self.T_map_from_color = None
        self.origin = None
        self.last_time = None

    def _record(self, depth_index, time_us, status, matrix=None, reason=None):
        return dict(depth_index=int(depth_index), time_us=int(time_us), status=status,
                    submap_id=self.submap if matrix is not None else None,
                    T_map_from_depth=None if matrix is None else rigid_matrix(matrix).tolist(),
                    synthetic=self.backend == "synthetic", backend=self.backend, reason=reason)

    def estimate(self, capture, processed, depth_index, sync_valid):
        timestamp = int(capture.depth.time_us) if capture.depth is not None else 0
        if self.feature["status"] != "success":
            return self._record(depth_index, timestamp, "disabled", reason="pose_disabled")
        if not sync_valid:
            self.reset()
            return self._record(depth_index, timestamp, "invalid_sync", reason="invalid_sync")
        if self.last_time is not None and (timestamp < self.last_time or timestamp-self.last_time > int(self.config.get("max_gap_us", 2_000_000))):
            self.reset()
        self.last_time = timestamp
        if self.backend == "synthetic":
            try:
                if capture.synthetic_pose is None:
                    raise ValueError("synthetic_pose_missing")
                pose = rigid_matrix(capture.synthetic_pose)
            except ValueError as exc:
                self.reset()
                return self._record(depth_index, timestamp, "lost", reason=str(exc))
            if self.origin is None:
                self.origin = np.linalg.inv(pose)
                self.submap += 1
            return self._record(depth_index, timestamp, "tracked", AXIS_MAP_FROM_OPTICAL @ self.origin @ pose)
        if processed is None or not np.any(processed["aligned_depth_color_m"] > 0):
            self.reset()
            return self._record(depth_index, timestamp, "lost", reason="depth_unavailable")
        try:
            return self._estimate_open3d(processed, depth_index, timestamp)
        except (RuntimeError, ValueError) as exc:
            self.reset()
            return self._record(depth_index, timestamp, "lost", reason=f"odometry_failed: {exc}")

    def _estimate_open3d(self, processed, depth_index, timestamp):
        o3d = self.o3d
        rgb = np.asarray(processed["color"], np.uint8)
        depth = np.asarray(processed["aligned_depth_color_m"], np.float32)
        camera = self.calibration["color"]
        K = np.asarray(camera["K"], float)
        distortion = np.asarray(camera.get("distortion", []), float)
        if np.any(distortion):
            import cv2
            height, width = depth.shape
            maps = cv2.initUndistortRectifyMap(K, distortion, None, K, (width, height), cv2.CV_32FC1)
            rgb = cv2.remap(rgb, *maps, interpolation=cv2.INTER_LINEAR)
            depth = cv2.remap(depth, *maps, interpolation=cv2.INTER_NEAREST)
        current = o3d.geometry.RGBDImage.create_from_color_and_depth(
            o3d.geometry.Image(np.ascontiguousarray(rgb)), o3d.geometry.Image(np.ascontiguousarray(depth)),
            depth_scale=1., depth_trunc=float(self.config.get("max_depth_m", 10.)), convert_rgb_to_intensity=True)
        if self.previous is None:
            self.previous = current
            return self._record(depth_index, timestamp, "initializing", reason="odometry_needs_second_frame")
        intrinsic = o3d.camera.PinholeCameraIntrinsic(rgb.shape[1], rgb.shape[0], K[0, 0], K[1, 1], K[0, 2], K[1, 2])
        option = o3d.pipelines.odometry.OdometryOption()
        option.depth_min = float(self.config.get("min_depth_m", .1))
        option.depth_max = float(self.config.get("max_depth_m", 10.))
        success, T_current_from_previous, information = o3d.pipelines.odometry.compute_rgbd_odometry(
            self.previous, current, intrinsic, np.eye(4),
            o3d.pipelines.odometry.RGBDOdometryJacobianFromHybridTerm(), option)
        self.previous = current
        if not success or not np.isfinite(information).all():
            self.T_map_from_color = None
            return self._record(depth_index, timestamp, "lost", reason="odometry_tracking_failed")
        motion = rigid_matrix(T_current_from_previous)
        max_translation = float(self.config.get("max_step_translation_m", 1.))
        if np.linalg.norm(motion[:3, 3]) > max_translation:
            self.T_map_from_color = None
            return self._record(depth_index, timestamp, "lost", reason="odometry_motion_gate")
        if self.T_map_from_color is None:
            # Anchor only after a real successful estimate. The first valid depth
            # pose defines map origin; there is no valid identity on startup.
            self.T_map_from_color = AXIS_MAP_FROM_OPTICAL @ np.linalg.inv(self.T_color_from_depth)
            self.submap += 1
        else:
            # Open3D output maps previous/source points to current/target points.
            self.T_map_from_color = self.T_map_from_color @ np.linalg.inv(motion)
        return self._record(depth_index, timestamp, "tracked", self.T_map_from_color @ self.T_color_from_depth)


class AnalysisPipeline:
    def __init__(self, config, calibration, metadata):
        self.config, self.metadata = config, metadata
        self.sync = Synchronizer(config.get("sync", {}).get("tolerance_us", 20000))
        try:
            self.preprocessor = Preprocessor(calibration, config.get("depth", {}))
            preprocessing_feature = self.preprocessor.feature
        except (ValueError, KeyError, TypeError) as exc:
            # Raw data remain valuable when an unsupported lens/profile is met.
            # Disable only geometry, and expose why to the next system.
            self.preprocessor = None
            preprocessing_feature = dict(status="disabled", backend="calibrated_brown_conrady", reason=f"calibration_invalid: {exc}")
        self.detector = Detector(config.get("detector", {}), metadata.get("synthetic", False))
        self.tracker = Tracker(config.get("detector", {}).get("dynamic_classes"),
                               max_gap_frames=config.get("detector", {}).get("tracker_max_gap_frames", 2))
        self.observation_count = 0
        self.pose_estimator = PoseEstimator(config.get("pose", {}), calibration, metadata)
        self.spatial = SpatialEstimator()
        self.features = {"detector": self.detector.feature, "pose": self.pose_estimator.feature,
                         "preprocessor": preprocessing_feature,
                         "tracking": dict(status="success", backend="adjacent_iou_depth", reason="long_term_reidentification_disabled")}
        self.stride = int(config.get("depth", {}).get("sample_stride", 8))
        if self.stride < 1:
            raise ValueError("depth.sample_stride must be positive")

    def process(self, capture, color_index, depth_index, sync_pair=None):
        started = time.perf_counter()
        pair = self.sync.pair(capture, color_index, depth_index) if sync_pair is None else sync_pair
        if pair["reason"] == "timestamp_reset":
            self.pose_estimator.reset()
            self.tracker.reset()
        events = list(self.sync.events) if sync_pair is None else []
        processed = None
        spatial_reason = pair["reason"]
        if pair["valid"] and self.preprocessor is None:
            spatial_reason = "calibration_unsupported"
        elif pair["valid"]:
            try:
                processed = self.preprocessor.process(capture)
            except ValueError as exc:
                spatial_reason = "preprocessing_failed"
                events.append(dict(code=spatial_reason, detail=str(exc), time_us=int(capture.depth.time_us)))
        detect_started = time.perf_counter()
        detections = []
        inference_executed = (capture.color is not None and self.detector.feature["status"] == "success"
                              and color_index % self.detector.interval == 0)
        if capture.color is not None:
            try:
                detections = self.detector.detect(capture.color.data, color_index)
            except Exception as exc:
                self.detector.feature.update(status="failed", reason=f"inference_failed: {exc}")
                events.append(dict(code="inference_failed", detail=str(exc), time_us=int(capture.color.time_us)))
        inference_latency_ms = (time.perf_counter()-detect_started)*1000
        pose = self.pose_estimator.estimate(capture, processed, depth_index, pair["valid"] and processed is not None)
        observations = []
        for detection in detections:
            location = self.spatial.estimate(detection["bbox"], processed) if processed is not None else dict(
                point_camera_m=None, valid_depth_ratio=0., depth_variance_m2=None, reason=spatial_reason)
            point = location["point_camera_m"]
            identity, motion_status = self.tracker.assign(detection, point, pose["submap_id"])
            position = None
            reason = location["reason"]
            if point is not None:
                if pose["T_map_from_depth"] is not None:
                    position = transform_point(point, pose["T_map_from_depth"])
                    reason = None
                else:
                    reason = pose["reason"] or "pose_invalid"
            observation_id = f"observation-{self.observation_count:08d}"
            self.observation_count += 1
            observations.append(dict(id=observation_id, object_id=identity,
                color_index=int(color_index), depth_index=int(depth_index), time_us=int(capture.color.time_us),
                **{"class": detection["class"]}, bbox=detection["bbox"], detection_confidence=float(detection["confidence"]),
                point_camera_m=point, position_m=position, submap_id=pose["submap_id"] if position is not None else None,
                position_status="map_valid" if position is not None else "camera_valid" if point is not None else "invalid",
                failure_reason=reason, position_semantics="observed_surface_representative", motion_status=motion_status,
                valid_depth_ratio=location["valid_depth_ratio"], depth_variance_m2=location["depth_variance_m2"],
                synthetic=bool(self.metadata.get("synthetic", False))))
        points, colors = np.empty((0, 3), np.float32), np.empty((0, 3), np.uint8)
        if processed is not None:
            valid = processed["valid"].copy()
            uv = processed["color_uv"]
            for detection, observation in zip(detections, observations):
                if observation["motion_status"] == "dynamic":
                    x0, y0, x1, y1 = detection["bbox"]
                    valid &= ~((uv[..., 0] >= x0) & (uv[..., 0] < x1) & (uv[..., 1] >= y0) & (uv[..., 1] < y1))
            sampled = valid[::self.stride, ::self.stride]
            points = processed["points_depth"][::self.stride, ::self.stride][sampled].astype(np.float32)
            colors = processed["point_colors"][::self.stride, ::self.stride][sampled]
        return dict(pair=pair, detections=detections, pose=pose, observations=observations,
                    points=points, point_colors=colors, features=self.features, events=events,
                    inference_latency_ms=inference_latency_ms,
                    inference_executed=inference_executed,
                    analysis_latency_ms=(time.perf_counter()-started)*1000,
                    valid_depth_ratio=processed["valid_depth_ratio"] if processed is not None else 0.,
                    tracking_success=pose["status"] == "tracked")
