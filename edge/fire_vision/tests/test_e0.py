"""Synthetic fixtures only: neither OpenLORIS observations nor Orin validation."""
import json
from copy import deepcopy
from pathlib import Path
import numpy as np
import pytest

from test_contract import config


def normalized_fixture(tmp_path):
    root = tmp_path / "input"
    root.mkdir()
    np.save(root / "rgb.npy", np.array([[[255,0,0],[0,255,0]],[[0,0,255],[255,255,255]]], np.uint8))
    np.save(root / "depth.npy", np.array([[1000,0],[1500,2000]], np.uint16))
    streams = {}
    for key, hz, frame in [("rgb",30,"color"),("depth",30,"color"),("accel",250,"imu"),("gyro",400,"imu")]:
        rows = []
        for i in range(30 * hz):
            t = 1_000_000_000 + round(i * 1e9 / hz)
            row = {"timestamp_ns":t,"record_ns":t+100,"frame_id":frame,"topic":config()["topics"][key]}
            if key in ("rgb","depth"):
                row.update(path=f"{key}.npy", original_encoding="rgb8" if key=="rgb" else "16UC1", normalized_encoding="rgb8" if key=="rgb" else "16UC1", width=2,height=2)
            else:
                row["value"] = [0,0,9.81] if key=="accel" else [0,0,0]
            rows.append(row)
        streams[key] = rows
    c = config()
    c["dataset"].update(path=str(root), sequence="synthetic-test-only", provenance_verified=True,
                         provenance_evidence="synthetic unit fixture, NOT measured data", depth_scale_m=0.001)
    c["segment"]["duration_s"] = 30
    manifest = {"format":"fire-vision-normalized-v1","source":deepcopy(c["dataset"]),
                "extraction":{"complete":True,"requested":{"start_offset_s":0,"duration_s":30},"start_ns":1_000_000_000,"stop_ns":31_000_000_000},"streams":streams}
    calibration = {"cameras":[{"frame_id":"color","width":2,"height":2,"K":[2,0,1,0,2,1,0,0,1],
                                "D":[0,0,0,0,0],"R":[1,0,0,0,1,0,0,0,1],"P":[2,0,1,0,0,2,1,0,0,0,1,0],"distortion_model":"plumb_bob"}],
                   "transforms":[{"header":{"frame_id":"color"},"child_frame_id":"imu",
                                  "transform":{"translation":{"x":0.1,"y":0,"z":0},"rotation":{"x":0,"y":0,"z":0,"w":1}}}],
                   "imu_intrinsics":[],
                   "review":{"rgb_depth_registered":True,"registration_evidence":"synthetic",
                             "camera_imu_direction_verified":True,"extrinsics_evidence":"synthetic",
                             "imu_accel_unit":"m/s^2","imu_gyro_unit":"rad/s","imu_axes":"x forward y left z up (synthetic)",
                             "imu_includes_gravity":True,"imu_semantics_evidence":"synthetic",
                             "imu_intrinsics_applied":False,"release_corrections_verified":True}}
    (root / "manifest.json").write_text(json.dumps(manifest))
    (root / "calibration.json").write_text(json.dumps(calibration))
    return root, c, manifest, calibration


def test_e0_analyzes_synthetic_recording_without_creating_slam_outputs(tmp_path):
    from fire_vision.validation import validate_input
    root,c,m,cal = normalized_fixture(tmp_path)
    out = tmp_path / "diagnostics"
    out.mkdir()
    report = validate_input(root, c, out)
    assert report["status"] == "passed"
    assert report["rgb_depth"]["matched"] == 900
    assert report["depth"]["valid_ratio"] == pytest.approx(0.75)
    assert report["imu"]["accel_norm_median"] == pytest.approx(9.81)
    assert report["transforms"]["T_camera_accel"][0][3] == pytest.approx(0.1)
    assert (out / "imu_plot.png").exists()
    assert (out / "rgb_depth_preview.png").exists()
    assert not (out / "map_2d.png").exists()


def test_e0_unknown_calibration_truncation_and_bad_timestamps_fail(tmp_path):
    from fire_vision.validation import validate_input
    root,c,m,cal = normalized_fixture(tmp_path)
    cal["review"]["rgb_depth_registered"] = None
    cal["cameras"][0]["K"][0] = -2
    m["streams"]["rgb"][5]["timestamp_ns"] = m["streams"]["rgb"][4]["timestamp_ns"]
    m["streams"]["gyro"] = m["streams"]["gyro"][:4]
    (root/"manifest.json").write_text(json.dumps(m))
    (root/"calibration.json").write_text(json.dumps(cal))
    out=tmp_path/"diagnostics"; out.mkdir()
    r = validate_input(root,c,out)
    assert r["status"] == "failed"
    codes = {x["code"] for x in r["issues"]}
    assert {"registration_unverified", "invalid_camera_calibration", "rgb_timestamp_order", "gyro_coverage"} <= codes


def test_tf_chain_and_inverse(tmp_path):
    from fire_vision.dataset_adapter import resolve_transform
    _,_,_,cal = normalized_fixture(tmp_path)
    assert resolve_transform(cal["transforms"],"imu","color")[0][3] == pytest.approx(-0.1)
    with pytest.raises(ValueError,match="no static transform"):
        resolve_transform(cal["transforms"],"world","imu")


def test_schema_rejects_missing_fields_and_nonfinite_values():
    from fire_vision.object_projection import validate_observation
    with pytest.raises(ValueError):
        validate_observation({"point_map_m":None})


def test_inventory_reads_real_ros1_binary_fixture(tmp_path):
    from rosbags.rosbag1 import Writer
    from rosbags.typesys import get_typestore, Stores
    from fire_vision.dataset_adapter import inventory_bag
    store=get_typestore(Stores.ROS1_NOETIC)
    msgtype="std_msgs/msg/String"
    bag=tmp_path/"synthetic.bag"
    with Writer(bag) as writer:
        connection=writer.add_connection("/test",msgtype,typestore=store)
        writer.write(connection,123,store.serialize_ros1(store.types[msgtype]("synthetic"),msgtype))
    inventory=inventory_bag(bag)
    assert inventory["format"] == "rosbag1"
    assert inventory["topics"] == [{"topic":"/test","msgtype":msgtype,"count":1}]


def test_bag_extract_preserves_header_time_and_pixels(tmp_path):
    from rosbags.rosbag1 import Writer
    from rosbags.typesys import get_typestore, Stores, get_types_from_msg
    from fire_vision.dataset_adapter import extract_bag
    store=get_typestore(Stores.ROS1_NOETIC)
    store.register(get_types_from_msg("geometry_msgs/TransformStamped[] transforms\n", "tf2_msgs/msg/TFMessage"))
    t=store.types
    bag=tmp_path/"synthetic.bag"
    c=config()
    header=t["std_msgs/msg/Header"](0,t["builtin_interfaces/msg/Time"](10,0),"color")
    with Writer(bag) as writer:
        for key in ("rgb","depth","camera_info","accel","gyro","tf_static"):
            msgtype="sensor_msgs/msg/Image" if key in ("rgb","depth") else (
                "sensor_msgs/msg/CameraInfo" if key=="camera_info" else "tf2_msgs/msg/TFMessage" if key=="tf_static" else "sensor_msgs/msg/Imu")
            connection=writer.add_connection(c["topics"][key],msgtype,typestore=store)
            if key in ("rgb","depth"):
                enc,step,data=("bgr8",3,[1,2,3]) if key=="rgb" else ("16UC1",2,[232,3])
                msg=t[msgtype](header,1,1,enc,0,step,np.array(data,np.uint8))
            elif key=="camera_info":
                roi=t["sensor_msgs/msg/RegionOfInterest"](0,0,0,0,False)
                msg=t[msgtype](header,1,1,"plumb_bob",np.zeros(5),np.eye(3).ravel(),np.eye(3).ravel(),np.zeros(12),0,0,roi)
            elif key=="tf_static":
                msg=t[msgtype]([])
            else:
                q=t["geometry_msgs/msg/Quaternion"](0.,0.,0.,1.)
                v=t["geometry_msgs/msg/Vector3"](0.,0.,0.)
                msg=t[msgtype](header,q,np.zeros(9),v,np.zeros(9),v,np.zeros(9))
            writer.write(connection,20_000_000_000,store.serialize_ros1(msg,msgtype))
    out=tmp_path/"normalized"
    m=extract_bag(bag,out,c)
    assert m["streams"]["rgb"][0]["timestamp_ns"]==10_000_000_000
    assert m["streams"]["rgb"][0]["record_ns"]==20_000_000_000
    assert np.load(out/m["streams"]["rgb"][0]["path"]).tolist()==[[[3,2,1]]]
    assert np.load(out/m["streams"]["depth"][0]["path"]).tolist()==[[1000]]
    assert json.loads((out/"calibration.json").read_text())["cameras"][0]["width"]==1
    assert m["source"]["sha256"]
