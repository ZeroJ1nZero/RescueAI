"""Synthetic error-path checks, never physical validation."""
import json
from pathlib import Path
import numpy as np
import pytest
from test_contract import config
from test_e0 import normalized_fixture


def test_manifest_cannot_escape_dataset(tmp_path):
    from fire_vision.dataset_adapter import load_dataset
    root,c,m,cal=normalized_fixture(tmp_path)
    m["streams"]["rgb"][0]["path"]="../outside.npy"
    np.save(tmp_path/"outside.npy",np.zeros((2,2,3),np.uint8))
    (root/"manifest.json").write_text(json.dumps(m))
    with pytest.raises(ValueError,match="unsafe"):
        load_dataset(root)


def test_synchronization_rejects_skew_without_reusing_depth():
    from fire_vision.dataset_adapter import match_stamps
    assert match_stamps([100,200],[150,250],10)==([], [0,1])


def test_invalid_depth_values_remain_invalid_and_float_meters(tmp_path):
    from fire_vision.dataset_adapter import depth_meters
    _,c,_,_=normalized_fixture(tmp_path)
    c["dataset"]["depth_scale_m"]=1.0
    d=depth_meters(np.array([[np.nan,np.inf,-1.,0.,2.]],np.float32),c)
    assert np.isnan(d[0,:4]).all()
    assert d[0,4]==pytest.approx(2.)


def test_depth_encoding_cannot_multiply_metric_float_or_colorized_pixels(tmp_path):
    from fire_vision.dataset_adapter import depth_meters
    _,c,_,_=normalized_fixture(tmp_path)
    with pytest.raises(ValueError,match="float"):
        depth_meters(np.array([[2.]],np.float32),c)
    with pytest.raises(ValueError,match="uint16"):
        depth_meters(np.array([[200]],np.uint8),c)


def test_transform_rejects_ambiguous_parent_and_cycle():
    from fire_vision.dataset_adapter import resolve_transform
    tf={"header":{"frame_id":"a"},"child_frame_id":"b",
        "transform":{"translation":{"x":0,"y":0,"z":0},"rotation":{"x":0,"y":0,"z":0,"w":1}}}
    from copy import deepcopy
    other=deepcopy(tf); other["header"]["frame_id"]="c"
    with pytest.raises(ValueError,match="parent"):
        resolve_transform([tf,other],"a","b")
    other=deepcopy(tf); other["header"]["frame_id"]="b"; other["child_frame_id"]="a"
    with pytest.raises(ValueError,match="cycle"):
        resolve_transform([tf,other],"a","b")


def test_segment_offset_mismatch_cannot_pass_e0(tmp_path):
    from fire_vision.validation import validate_input
    root,c,m,_=normalized_fixture(tmp_path)
    m["extraction"]["requested"]={"start_offset_s":0,"duration_s":30}
    (root/"manifest.json").write_text(json.dumps(m))
    c["segment"]["start_offset_s"]=2
    out=tmp_path/"report"; out.mkdir()
    r=validate_input(root,c,out)
    assert r["status"]=="failed"
    assert "segment_offset_mismatch" in {i["code"] for i in r["issues"]}


def test_e0_cli_exception_records_failure(tmp_path):
    from fire_vision.cli import main
    bad_input=tmp_path/"bad-input"; bad_input.mkdir()
    c=config(); c["dataset"]["path"]=str(bad_input)
    cfg=tmp_path/"c.json"; cfg.write_text(json.dumps(c))
    out=tmp_path/"out"
    assert main(["check-input","--config",str(cfg),"--out",str(out)])==2
    s=json.loads((out/"session.json").read_text())
    assert s["stages"]["E0"]["status"]=="failed"
    assert (out/"failures.jsonl").read_text()
    assert not (out/"trajectory.csv").exists()


def test_replay_rejects_input_changed_since_e0(tmp_path):
    from fire_vision.replay import verified_input
    from fire_vision.validation import validate_input
    from fire_vision.export import Session
    root,c,_,_=normalized_fixture(tmp_path)
    s=Session(tmp_path/"e0",c,{"device_kind":"synthetic_test"})
    assert validate_input(root,c,s.path)["status"]=="passed"
    s.stage("E0","passed"); s.finish()
    verified_input(root,s.path,c)
    np.save(root/"rgb.npy",np.zeros((2,2,3),np.uint8))
    with pytest.raises(ValueError,match="changed"):
        verified_input(root,s.path,c)
    (root/"calibration.json").write_text("{}")
    with pytest.raises(ValueError,match="changed"):
        verified_input(root,s.path,c)


def test_exact_two_period_loss_is_counted():
    from fire_vision.dataset_adapter import timestamp_stats
    stat=timestamp_stats([0,8_000_000,16_000_000],expected_period_ns=4_000_000,gap_factor=2.0)
    assert stat["gaps"]==2
    assert stat["estimated_missing_samples"]==2
    rounded=timestamp_stats([0,66_666_666,100_000_000],expected_period_ns=1e9/30,gap_factor=2.0)
    assert rounded["gaps"]==1
    assert rounded["estimated_missing_samples"]==1


def test_invalid_depth_window_cannot_hide_behind_one_valid_frame(tmp_path):
    from fire_vision.validation import validate_input
    root,c,m,_=normalized_fixture(tmp_path)
    np.save(root/"invalid.npy",np.zeros((2,2),np.uint16))
    for row in m["streams"]["depth"][1:]:
        row["path"]="invalid.npy"
    (root/"manifest.json").write_text(json.dumps(m))
    out=tmp_path/"diagnostic"; out.mkdir()
    r=validate_input(root,c,out)
    assert r["status"]=="failed"
    assert r["depth"]["all_invalid_frame_count"]==899
    assert "depth_invalid_window" in {i["code"] for i in r["issues"]}


def test_extraction_never_writes_inside_source_directory(tmp_path):
    from fire_vision.dataset_adapter import extract_bag
    source=tmp_path/"raw-source"; source.mkdir()
    with pytest.raises(ValueError,match="source"):
        extract_bag(source,source/"output",config())
    assert list(source.iterdir())==[]


def test_no_inventory_or_session_output_inside_input(tmp_path):
    from fire_vision.cli import main
    from fire_vision.export import Session
    root=tmp_path/"input"; root.mkdir()
    assert main(["inspect-bag",str(root),"--out",str(root/"inventory.json")])==2
    assert not (root/"inventory.json").exists()
    c=config(); c["dataset"]["path"]=str(root)
    with pytest.raises(ValueError,match="source"):
        Session(root/"session",c,{})
    assert not (root/"session").exists()


def test_invalid_camera_rectification_and_projection_fail_e0(tmp_path):
    from fire_vision.validation import validate_input
    root,c,_,cal=normalized_fixture(tmp_path)
    cal["cameras"][0].update(R=None,P=None)
    (root/"calibration.json").write_text(json.dumps(cal))
    out=tmp_path/"diagnostics"; out.mkdir()
    r=validate_input(root,c,out)
    assert r["status"]=="failed"
    assert "invalid_camera_calibration" in {i["code"] for i in r["issues"]}


def test_export_detects_changed_artifact(tmp_path):
    from fire_vision.export import Session,write_json,verify_export
    s=Session(tmp_path/"session",config(),{})
    write_json(s.path/"calibration.json",{"actual":"test-only"})
    s.finish()
    assert verify_export(s.path)["hash_mismatches"]==[]
    (s.path/"calibration.json").write_text("{}")
    assert verify_export(s.path)["hash_mismatches"]==["calibration.json"]
