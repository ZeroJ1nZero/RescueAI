"""Synthetic unit tests. These are NOT real sensor experiments."""
import json
import subprocess
from copy import deepcopy
from pathlib import Path
import numpy as np
import pytest


def config():
    return json.loads(Path("configs/e0.json").read_text())


def test_config_rejects_unsafe_scale_and_invalid_ranges():
    from fire_vision.config import validate_config
    c = config()
    c["dataset"]["depth_scale_m"] = 0.001
    with pytest.raises(ValueError, match="provenance"):
        validate_config(c)
    c = config()
    c["replay"]["rate"] = 0
    with pytest.raises(ValueError):
        validate_config(c)
    c = config()
    c["segment"]["duration_s"] = float("nan")
    with pytest.raises(ValueError):
        validate_config(c)


@pytest.mark.parametrize("with_git", [False, True])
def test_blocked_session_has_no_fake_artifacts(tmp_path, monkeypatch, with_git):
    from fire_vision.export import Session
    cfg = config()
    work = tmp_path / "work"
    work.mkdir()
    expected_commit = None
    if with_git:
        subprocess.run(["git", "init", "-b", "main", str(work)], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(work), "-c", "user.name=Fixture",
                        "-c", "user.email=fixture@example.invalid", "-c", "commit.gpgsign=false",
                        "commit", "--allow-empty", "-m", "synthetic fixture"], check=True, capture_output=True)
        expected_commit = subprocess.check_output(["git", "-C", str(work), "rev-parse", "HEAD"], text=True).strip()
    monkeypatch.chdir(work)
    s = Session(tmp_path / "session", cfg, {"device_kind": "development_pc"})
    s.stage("E0", "not_run", "dataset_missing")
    s.finish()
    data = json.loads((s.path / "session.json").read_text())
    assert data["stages"]["E0"] == {"status": "not_run", "reason": "dataset_missing"}
    assert not (s.path / "map_3d.ply").exists()
    assert not (s.path / "metrics.json").exists()
    assert not (s.path / "tegrastats.log").exists()
    assert data["git"]["commit"] == expected_commit
    assert data["git"]["reason"] == (None if with_git else "not_a_git_repository_or_no_commit")
    with pytest.raises(FileExistsError):
        Session(s.path, cfg, {})


def test_metric_depth_requires_identity_and_rejects_invalid():
    from fire_vision.dataset_adapter import depth_meters
    c = config()
    raw = np.array([[1000, 0, 65535, 7000]], dtype=np.uint16)
    with pytest.raises(ValueError):
        depth_meters(raw, c)
    c["dataset"].update(provenance_verified=True, provenance_evidence="source SHA256 and README", depth_scale_m=0.001)
    d = depth_meters(raw, c)
    assert d[0, 0] == pytest.approx(1)
    assert np.isnan(d[0, 1:]).all()
    c["dataset"]["sensor"] = "unknown"
    with pytest.raises(ValueError):
        depth_meters(raw, c)


def test_decode_padding_endian_and_bgr():
    from types import SimpleNamespace as NS
    from fire_vision.dataset_adapter import decode_image
    msg = NS(height=1, width=2, step=6, is_bigendian=1, encoding="16UC1", data=np.array([3, 232, 7, 208, 9, 9], np.uint8))
    assert decode_image(msg).tolist() == [[1000, 2000]]
    msg = NS(height=1, width=1, step=4, is_bigendian=0, encoding="bgr8", data=np.array([1, 2, 3, 0], np.uint8))
    assert decode_image(msg).tolist() == [[[3, 2, 1]]]
    msg.step = 2
    with pytest.raises(ValueError):
        decode_image(msg)


def test_timestamp_stats_and_matching_do_not_hide_loss():
    from fire_vision.dataset_adapter import timestamp_stats, match_stamps
    s = timestamp_stats([0, 10, 10, 5, 40], expected_period_ns=10, gap_factor=2)
    assert s["duplicates"] == 1
    assert s["backwards"] == 1
    assert s["gaps"] == 1
    pairs, missing = match_stamps([100, 105, 130], [102, 135], 5)
    assert pairs == [(0, 0, 2), (2, 1, 5)]
    assert missing == [1]
    with pytest.raises(ValueError):
        match_stamps([2, 1], [1], 1)


def test_geometry_transform_direction_and_pose_failure():
    from fire_vision.object_projection import backproject, transform_point, project_with_pose
    p = backproject(4, 3, 2, [2, 0, 2, 0, 2, 1, 0, 0, 1])
    assert p == pytest.approx([2, 2, 2])
    T = np.array([[0, -1, 0, 10], [1, 0, 0, 20], [0, 0, 1, 30], [0, 0, 0, 1]])
    assert transform_point(p, T) == pytest.approx([8, 22, 32])
    assert project_with_pose(p, 100, None, 5) == (None, "pose_missing")
    pose = {"timestamp_ns": 106, "T_map_camera": T.tolist()}
    assert project_with_pose(p, 100, pose, 5) == (None, "pose_time_tolerance_exceeded")
    pose["timestamp_ns"] = 105
    assert project_with_pose(p, 100, pose, 5)[0] == pytest.approx([8, 22, 32])
    with pytest.raises(ValueError):
        backproject(0, 0, float("nan"), [1,0,0,0,1,0,0,0,1])
    with pytest.raises(ValueError):
        transform_point(p, np.diag([2, 1, 1, 1]))


def test_observation_schema_requires_failure_reason_and_null_temperature():
    from fire_vision.object_projection import observation, validate_observation
    o = observation("s", "obs-1", 100, "evidence_frames/a.png", "chair", [0,0,2,2], "camera", None, None, None, 0.0, None, "invalid_depth", "test-only")
    validate_observation(o)
    assert o["point_map_m"] is None
    assert o["temperature"] is None
    o["temperature"] = 23
    with pytest.raises(ValueError):
        validate_observation(o)


@pytest.mark.parametrize("field,value", [("timestamp",float("nan")),("valid_depth_ratio",float("nan")),
    ("depth_dispersion",-1),("depth_dispersion",float("inf")),("bbox",[2,0,1,2]),("class_label","")])
def test_observation_rejects_nonserializable_or_invalid_measurements(field,value):
    from fire_vision.object_projection import observation,validate_observation
    o=observation("s","o",1,"evidence_frames/a.png","chair",[0,0,2,2],"camera",None,None,None,0,None,"invalid_depth","synthetic-only")
    o[field]=value
    with pytest.raises(ValueError):
        validate_observation(o)


def test_replay_schedule_does_not_scale_sensor_timestamps():
    from fire_vision.replay import schedule
    rows = schedule([1_000_000_000, 1_002_500_000, 2_000_000_000], 0.25)
    assert rows == [(0.0, 1_000_000_000), (0.01, 1_002_500_000), (4.0, 2_000_000_000)]


def test_e0_missing_data_and_later_stage_gate(tmp_path):
    from fire_vision.cli import main
    assert main(["check-input", "--config", "configs/e0.json", "--out", str(tmp_path / "e0")]) == 2
    data = json.loads((tmp_path / "e0/session.json").read_text())
    assert data["stages"]["E0"]["status"] == "not_run"
    assert main(["run", "E1", "--config", "configs/e0.json", "--out", str(tmp_path / "e1")]) == 2
    assert json.loads((tmp_path / "e1/session.json").read_text())["stages"]["E1"]["status"] == "not_run"
