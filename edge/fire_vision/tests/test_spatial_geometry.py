import numpy as np
import pytest

from fire_vision.spatial.types import Capture, Sample
from fire_vision.spatial.geometry import AXIS_MAP_FROM_OPTICAL, Preprocessor, SpatialEstimator, Synchronizer
from fire_vision.spatial.analysis import AnalysisPipeline, PoseEstimator


def calibration(width=8, height=6):
    camera = {"K": [[4, 0, 3], [0, 4, 2], [0, 0, 1]], "width": width, "height": height,
              "distortion": [0, 0, 0, 0, 0], "distortion_model": "none"}
    return {"depth": camera.copy(), "color": camera.copy(), "T_color_from_depth": np.eye(4).tolist(),
            "depth_registered_to_color": True}


def capture(depth=None, scale=0.002, color_time=10, depth_time=12, pose=None):
    return Capture(Sample("color", np.zeros((6, 8, 3), np.uint8), 1, color_time, time_us=color_time),
                   Sample("depth", np.full((6, 8), 1000, np.uint16) if depth is None else depth,
                          1, depth_time, time_us=depth_time, depth_scale_m=scale), synthetic_pose=pose)


def test_scale_and_known_pixel_backprojection():
    p = Preprocessor(calibration(), {"min_m": 0.1, "max_m": 10}).process(capture())
    assert p["points_depth"][2, 3].tolist() == [0, 0, 2]
    assert p["points_depth"][2, 5].tolist() == [1, 0, 2]
    assert np.allclose(AXIS_MAP_FROM_OPTICAL @ [1, 2, 3, 1], [3, -1, -2, 1])


def test_nonregistered_bbox_uses_extrinsic_projection():
    c = calibration()
    c["depth_registered_to_color"] = False
    c["T_color_from_depth"][0][3] = 1.0
    p = Preprocessor(c, {"min_m": .1, "max_m": 10}).process(capture())
    # A 2m surface shifts +2 color pixels. Box around color x=5 corresponds to depth x=3.
    result = SpatialEstimator().estimate([5, 2, 6, 3], p)
    assert result["point_camera_m"] == [0, 0, 2]


def test_invalid_depth_never_becomes_zero_distance():
    p = Preprocessor(calibration(), {}).process(capture(np.zeros((6, 8), np.uint16)))
    result = SpatialEstimator().estimate([0, 0, 8, 6], p)
    assert result["point_camera_m"] is None
    assert result["valid_depth_ratio"] == 0
    assert result["reason"] == "invalid_depth"


def test_sync_tolerance_and_clock_reset_are_explicit():
    s = Synchronizer(20)
    assert s.pair(capture(), 0, 0)["valid"]
    assert not s.pair(capture(color_time=50, depth_time=100), 1, 1)["valid"]
    reset = s.pair(capture(color_time=1, depth_time=2), 2, 2)
    assert not reset["valid"]
    assert reset["reason"] == "timestamp_reset"
    assert s.events[-1]["code"] == "timestamp_reset"


def test_nearest_time_pairing_rejects_far_samples():
    pairs = Synchronizer(5).pair_times([10, 30, 50], [12, 39, 100])
    assert [(p["depth_index"], p["valid"]) for p in pairs] == [(0, True), (1, False), (1, False)]


def test_unrelated_clocks_cannot_be_spatially_paired():
    c=capture()
    c.color.clock="unconverted_other_device"
    pair=Synchronizer(20).pair(c,0,0)
    assert not pair["valid"]
    assert pair["reason"]=="clock_conversion_unverified"


def test_synthetic_pose_requires_synthetic_input_and_submaps_split():
    with pytest.raises(ValueError, match="synthetic"):
        PoseEstimator({"backend": "synthetic"}, calibration(), {"synthetic": False})
    estimator = PoseEstimator({"backend": "synthetic"}, calibration(), {"synthetic": True})
    c = capture(pose=np.eye(4))
    first = estimator.estimate(c, None, 0, True)
    assert first["submap_id"] == 0 and first["status"] == "tracked"
    assert np.allclose(first["T_map_from_depth"], AXIS_MAP_FROM_OPTICAL)
    lost = estimator.estimate(capture(pose=None), None, 1, True)
    assert lost["T_map_from_depth"] is None
    c.synthetic_pose[0, 3] = 10
    again = estimator.estimate(c, None, 2, True)
    assert again["submap_id"] == 1
    assert np.allclose(again["T_map_from_depth"], AXIS_MAP_FROM_OPTICAL)


def test_pipeline_missing_pose_keeps_camera_position_only():
    pipe = AnalysisPipeline({"detector": {"backend": "synthetic"}, "pose": {"backend": "disabled"}},
                            calibration(), {"synthetic": True})
    result = pipe.process(capture(), 0, 0)
    o = result["observations"][0]
    assert o["point_camera_m"] is not None
    assert o["position_m"] is None and o["failure_reason"] == "pose_disabled"
    assert o["synthetic"] is True


def test_pipeline_invalid_sync_prevents_spatial_calculation():
    pipe = AnalysisPipeline({"detector": {"backend": "synthetic"}, "pose": {"backend": "synthetic"},
                             "sync": {"tolerance_us": 2}}, calibration(), {"synthetic": True})
    result = pipe.process(capture(color_time=10, depth_time=30, pose=np.eye(4)), 0, 0)
    assert result["observations"][0]["point_camera_m"] is None
    assert result["pose"]["T_map_from_depth"] is None


def test_unsupported_distortion_is_not_silently_ignored():
    c = calibration()
    c["depth"]["distortion_model"] = "fisheye_unverified"
    with pytest.raises(ValueError, match="distortion"):
        Preprocessor(c, {})


def test_nonzero_distortion_depth_ray_matches_brown_conrady_equation():
    c = calibration()
    c["depth"]["distortion_model"] = "brown_conrady"
    c["depth"]["distortion"] = [.1, 0, 0, 0, 0]
    p = Preprocessor(c, {}).process(capture())
    x, y, z = p["points_depth"][2, 5]
    ideal = x/z
    assert ideal * (1 + .1*ideal*ideal) == pytest.approx(.5, abs=1e-7)
    assert ideal < .5


def test_surface_outlier_rejection_and_actual_depth_ratio():
    d = np.full((6, 8), 1000, np.uint16)
    d[2, 3] = 0
    d[2, 4] = 4000
    p = Preprocessor(calibration(), {}).process(capture(d))
    result = SpatialEstimator().estimate([0, 0, 8, 6], p)
    assert result["point_camera_m"][2] == 2.
    assert result["depth_variance_m2"] == 0.
    assert result["valid_depth_ratio"] == pytest.approx(46/48)


def test_synthetic_pose_motion_is_axis_rotated_with_column_vector_direction():
    estimator = PoseEstimator({"backend": "synthetic"}, calibration(), {"synthetic": True})
    first = np.eye(4)
    first[:3, 3] = [3, 5, 8]
    estimator.estimate(capture(pose=first), None, 0, True)
    moved = first.copy()
    moved[:3, 3] += [1, 2, 3]
    pose = estimator.estimate(capture(pose=moved), None, 1, True)
    assert np.allclose(np.array(pose["T_map_from_depth"])[:3, 3], [3, -1, -2])


def test_missing_color_is_a_recorded_pair_failure():
    c = capture()
    c.color = None
    pipe = AnalysisPipeline({"pose": {"backend": "synthetic"}}, calibration(), {"synthetic": True})
    result = pipe.process(c, -1, 0)
    assert result["pair"]["reason"] == "color_missing"
    assert result["points"].shape == (0, 3)
    assert result["pose"]["T_map_from_depth"] is None


def test_bad_synthetic_transform_is_not_exported_as_valid_pose():
    estimator = PoseEstimator({"backend": "synthetic"}, calibration(), {"synthetic": True})
    invalid = np.eye(4)
    invalid[0, 0] = 2
    result = estimator.estimate(capture(pose=invalid), None, 0, True)
    assert result["status"] == "lost" and result["T_map_from_depth"] is None


def test_reset_events_are_bounded_and_break_submap():
    pipe = AnalysisPipeline({"pose": {"backend": "synthetic"}}, calibration(), {"synthetic": True})
    pipe.process(capture(color_time=100, depth_time=102, pose=np.eye(4)), 0, 0)
    reset = pipe.process(capture(color_time=1, depth_time=2, pose=np.eye(4)), 1, 1)
    assert reset["pair"]["reason"] == "timestamp_reset"
    assert reset["pose"]["T_map_from_depth"] is None
    again = pipe.process(capture(color_time=10, depth_time=12, pose=np.eye(4)), 2, 2)
    assert again["pose"]["submap_id"] == 1
    assert again["events"] == []


def test_sdk_brown_conrady_k6_alias_uses_rational_radial_coefficients():
    c = calibration()
    c["depth"]["distortion_model"] = "brown_conrady_k6"
    c["depth"]["distortion"] = [.1, 0., 0., 0., 0., .02, 0., 0.]
    p = Preprocessor(c, {}).process(capture())
    x, _, z = p["points_depth"][2, 5]
    normalized = x/z
    assert normalized*(1 + .1*normalized**2)/(1 + .02*normalized**2) == pytest.approx(.5, abs=1e-7)


def test_pipeline_unsupported_lens_preserves_detection_but_invalidates_geometry():
    c = calibration()
    c["depth"]["distortion_model"] = "kannala_brandt4"
    pipe = AnalysisPipeline({"detector": {"backend": "synthetic"}, "pose": {"backend": "disabled"}}, c, {"synthetic": True})
    result = pipe.process(capture(), 0, 0)
    assert result["detections"]
    assert result["observations"][0]["point_camera_m"] is None
    assert result["points"].shape == (0, 3)
    assert pipe.features["preprocessor"]["status"] == "disabled"
    assert "unsupported distortion" in pipe.features["preprocessor"]["reason"]


def test_pipeline_bad_extrinsic_does_not_block_raw_recording_path():
    c = calibration()
    c["T_color_from_depth"] = [[1]]
    pipe = AnalysisPipeline({"pose": {"backend": "synthetic"}}, c, {"synthetic": True})
    result = pipe.process(capture(pose=np.eye(4)), 0, 0)
    assert result["pose"]["T_map_from_depth"] is None
    assert pipe.features["pose"]["status"] == "disabled"


def test_gemini2_rectified_depth_preserves_factory_distortion_provenance():
    from types import SimpleNamespace
    from fire_vision.spatial.sources import OrbbecSource
    intr = SimpleNamespace(fx=4, fy=4, cx=3, cy=2, width=8, height=6)
    dist = SimpleNamespace(model=SimpleNamespace(name="BROWN_CONRADY"), k1=.1, k2=.2, k3=.3,
                           k4=.4, k5=.5, k6=.6, p1=.01, p2=.02)
    depth = OrbbecSource._native_depth_intrinsic("Orbbec Gemini 2", intr, dist)
    assert depth["distortion_model"] == "none"
    assert depth["distortion"] == [0.]*8
    assert depth["factory_distortion"] == [.1, .2, .01, .02, .3, .4, .5, .6]
    assert depth["factory_distortion_model"] == "brown_conrady"
    other = OrbbecSource._native_depth_intrinsic("Other device", intr, dist)
    assert other["distortion_model"] == "brown_conrady"
    assert other["distortion"][0] == .1


def test_pipeline_tracks_temporal_object_but_observation_ids_stay_unique():
    pipeline = AnalysisPipeline({"detector": {"backend": "synthetic"}, "pose": {"backend": "synthetic"}},
                                calibration(), {"synthetic": True})
    a = pipeline.process(capture(color_time=10, depth_time=12, pose=np.eye(4)), 0, 0)["observations"][0]
    b = pipeline.process(capture(color_time=20, depth_time=22, pose=np.eye(4)), 1, 1)["observations"][0]
    assert a["object_id"] == b["object_id"]
    assert a["id"] != b["id"]
