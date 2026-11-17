import numpy as np
import pytest
from fire_vision.spatial.inference import Detector, Tracker, decode_yolo


def test_model_missing_is_explicit_disabled(tmp_path):
    detector = Detector({"backend": "onnx", "model": str(tmp_path / "missing.onnx")}, synthetic=False)
    assert detector.feature["status"] == "disabled"
    assert detector.feature["reason"] == "model_missing"
    assert detector.detect(np.zeros((20, 30, 3), np.uint8), 0) == []


def test_required_model_missing_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        Detector({"backend": "onnx", "model": str(tmp_path / "missing"), "require_model": True}, False)


def test_synthetic_detector_cannot_label_real_input():
    with pytest.raises(ValueError, match="synthetic"):
        Detector({"backend": "synthetic"}, False)


def test_yolo_decode_scale_confidence_class_and_nms():
    # channels x candidates, x/y/w/h followed by exactly two configured classes
    out = np.array([[[50, 51, 20], [50, 51, 20], [20, 20, 5], [20, 20, 5],
                     [.9, .8, .1], [.1, .1, .2]]], np.float32)
    d = decode_yolo(out, ["chair", "person"], .5, (100, 100), (200, 100))
    assert len(d) == 1
    assert d[0]["class"] == "chair"
    assert d[0]["bbox"] == [80., 40., 120., 60.]
    assert d[0]["confidence"] == pytest.approx(.9)


def test_wrong_model_output_contract_rejected():
    with pytest.raises(ValueError, match="YOLO"):
        decode_yolo(np.zeros((1, 20, 7)), ["chair", "person"], .5, (100, 100), (100, 100))


def test_onnx_cpu_runs_fixture_model(tmp_path):
    """Exercise real OpenCV execution; this tiny model is not a trained detector."""
    onnx=pytest.importorskip("onnx")
    pytest.importorskip("cv2")
    h=onnx.helper
    t=onnx.TensorProto
    graph=h.make_graph([
        h.make_node("GlobalAveragePool",["image"],["pool"]),
        h.make_node("Conv",["pool","weights","bias"],["conv"],kernel_shape=[1,1]),
        h.make_node("Reshape",["conv","shape"],["output"])],"fixture",
        [h.make_tensor_value_info("image",t.FLOAT,[1,3,4,4])],
        [h.make_tensor_value_info("output",t.FLOAT,[1,5,1])],
        initializer=[h.make_tensor("weights",t.FLOAT,[5,3,1,1],[0.]*15),
                     h.make_tensor("bias",t.FLOAT,[5],[2,2,2,2,.9]),h.make_tensor("shape",t.INT64,[3],[1,5,1])])
    model=h.make_model(graph,opset_imports=[h.make_opsetid("",13)],ir_version=7)
    path=tmp_path/"fixture.onnx"
    onnx.save(model,path)
    detector=Detector({"backend":"onnx","model":str(path),"classes":["fixture_model"],"input_size":[4,4]},synthetic=True)
    result=detector.detect(np.zeros((8,8,3),np.uint8),0)
    assert result[0]["bbox"]==[2.,2.,6.,6.]
    assert result[0]["class"]=="fixture_model"
    assert result[0]["synthetic"] is True
    assert detector.feature["model_sha256"]


def detection(frame, label="chair", bbox=None):
    return {"color_index": frame, "class": label, "bbox": [0., 0., 20., 20.] if bbox is None else bbox}


def test_tracker_links_only_adjacent_consistent_observations():
    tracker = Tracker()
    first, motion = tracker.assign(detection(0), [0, 0, 2], 0)
    second, _ = tracker.assign(detection(1, bbox=[.5, 0., 20.5, 20.]), [.02, 0, 2], 0)
    assert first == second and motion == "unknown"
    assert tracker.assign(detection(5), [.02, 0, 2], 0)[0] != first


@pytest.mark.parametrize("label,point,submap", [("person", [0, 0, 2], 0), ("chair", [0, 0, 2.2], 0),
                                               ("chair", [0, 0, 2], 1), ("chair", None, 0),
                                               ("chair", [0, 0, 2], None)])
def test_tracker_rejects_class_depth_submap_or_invalid_geometry(label, point, submap):
    tracker = Tracker()
    first = tracker.assign(detection(0), [0, 0, 2], 0)[0]
    assert tracker.assign(detection(1, label), point, submap)[0] != first


def test_tracker_ambiguous_candidates_never_merge_and_one_track_once_per_frame():
    tracker = Tracker()
    a = tracker.assign(detection(0), [0, 0, 2], 0)[0]
    b = tracker.assign(detection(0), [.01, 0, 2], 0)[0]
    assert a != b
    assert tracker.assign(detection(1), [0, 0, 2], 0)[0] not in {a, b}
    single = Tracker()
    a = single.assign(detection(0), [0, 0, 2], 0)[0]
    assert single.assign(detection(1), [0, 0, 2], 0)[0] == a
    assert single.assign(detection(1), [0, 0, 2], 0)[0] != a


def test_tracker_memory_is_bounded_and_dynamic_observations_keep_identity():
    tracker = Tracker()
    for index in range(500):
        tracker.assign(detection(0), [index, 0, 2], 0)
    assert len(tracker.tracks) <= 64
    dynamic = Tracker()
    a, motion = dynamic.assign(detection(0, "person"), [0, 0, 2], 0)
    b, next_motion = dynamic.assign(detection(1, "person"), [.01, 0, 2], 0)
    assert a == b and motion == next_motion == "dynamic"


def test_tracker_reset_or_frame_regression_does_not_reuse_identity():
    tracker = Tracker()
    a = tracker.assign(detection(20), [0, 0, 2], 0)[0]
    b = tracker.assign(detection(0), [0, 0, 2], 0)[0]
    assert a != b
    tracker.reset()
    assert tracker.assign(detection(1), [0, 0, 2], 0)[0] not in {a, b}
