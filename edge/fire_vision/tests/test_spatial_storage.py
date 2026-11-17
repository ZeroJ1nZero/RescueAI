"""Risk tests: no fallback storage, raw preservation and truthful result references."""
import json
from pathlib import Path
import threading

import h5py
import numpy as np
import pytest

from fire_vision.spatial.storage import StorageGuard, RawRecorder, Exporter
from fire_vision.spatial.reader import Reader
from fire_vision.spatial.types import Capture, Sample


def test_mount_required_and_low_space(tmp_path):
    with pytest.raises((ValueError, OSError), match="mount|device|UUID"):
        StorageGuard({"path": str(tmp_path), "mount_path": str(tmp_path), "expected_uuid": "missing", "min_free_bytes": 1}).check()
    with pytest.raises(OSError, match="space"):
        StorageGuard({"path": str(tmp_path), "allow_local": True, "min_free_bytes": 10**30}, development=True).check()
    with pytest.raises(ValueError, match="development"):
        StorageGuard({"path": str(tmp_path), "allow_local": True}, development=False).check()


def make_raw(tmp_path):
    out=tmp_path / "session"
    out.mkdir()
    recorder=RawRecorder(out, {"synthetic": True}, {"version": "fixture"}, {})
    color=Sample("color", np.arange(36,dtype=np.uint8).reshape(3,4,3), 42, 9000, host_monotonic_ns=123, time_us=0)
    depth=Sample("depth", np.full((3,4),500,dtype=np.uint16), 43, 9100, host_monotonic_ns=124, time_us=100,depth_scale_m=.004)
    accel=Sample("accel",np.array([1.,2.,3.]),1,9030, time_us=30)
    assert recorder.append(Capture(color,depth,[accel])) == (0,0)
    recorder.close()
    return out,color,depth


def test_export_raw_reader_and_hash_corruption(tmp_path):
    out,color,depth=make_raw(tmp_path)
    result=Exporter(out,{}).finalize({"synthetic":True}, {"detector":{"status":"disabled"},"pose":{"status":"disabled"}}, {})
    assert result["status"] == "partial"
    assert (out / "map.json").exists()
    with Reader(out / "map.json") as reader:
        np.testing.assert_array_equal(reader.raw("color",0),color.data)
        np.testing.assert_array_equal(reader.raw("depth",0),depth.data)
        assert reader.objects() == []
        assert reader.trajectory().shape == (0,)
    with (out / "session.h5").open("ab") as f:
        f.write(b"corrupt")
    with pytest.raises(ValueError, match="hash|size"):
        Reader(out / "map.json")


def test_no_overwrite_or_ready_marker_for_partial(tmp_path):
    out,_,_=make_raw(tmp_path)
    assert not (out / "map.json").exists()
    with pytest.raises(FileExistsError):
        RawRecorder(out,{}, {}, {})


def test_schema_rejects_nan_and_broken_reference(tmp_path):
    out,_,_=make_raw(tmp_path)
    Exporter(out,{}).finalize({"synthetic":True}, {}, {})
    path=out / "map.json"
    data=json.loads(path.read_text())
    data["datasets"]["points"]="/missing"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="reference|dataset"):
        Reader(path)
    data["time"]["duration_us"]=float("nan")
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        Reader(path)


def test_final_invalidated_pose_clears_map_status(tmp_path):
    from fire_vision.spatial.sources import SyntheticSource
    from fire_vision.spatial.analysis import AnalysisPipeline
    source=SyntheticSource({"source":{"frames":1}})
    source.open()
    pipeline=AnalysisPipeline({"detector":{"backend":"synthetic"},"pose":{"backend":"synthetic"}},source.calibration,source.metadata)
    out=tmp_path/"revised"; out.mkdir()
    recorder=RawRecorder(out,source.metadata,source.calibration,{})
    cap=next(source.captures(threading.Event()))
    recorder.append(cap)
    recorder.analysis(pipeline.process(cap,0,0))
    pose=recorder.h5["derived/poses"][0]
    pose["status"]=b"lost"; pose["T_map_from_depth"]=np.nan; pose["submap_id"]=-1
    recorder.h5["derived/poses"][0]=pose
    recorder.close()
    Exporter(out,{}).finalize(source.metadata,pipeline.features,{})
    with Reader(out/"map.json") as r:
        assert r.objects()[0]["position_m"] is None
        assert r.objects()[0]["position_status"]=="camera_valid"
        assert r.objects()[0]["failure_reason"]=="final_pose_invalid"
        assert r.objects()[0]["submap_id"] is None


def test_utf8_labels_duration_and_independent_submaps(tmp_path):
    from fire_vision.spatial.sources import SyntheticSource
    from fire_vision.spatial.analysis import AnalysisPipeline
    source=SyntheticSource({"source":{"frames":2}}); source.open()
    pipeline=AnalysisPipeline({"detector":{"backend":"synthetic"},"pose":{"backend":"synthetic"}},source.calibration,source.metadata)
    out=tmp_path/"multimap"; out.mkdir()
    recorder=RawRecorder(out,source.metadata,source.calibration,{})
    for i,cap in enumerate(source.captures(threading.Event())):
        recorder.append(cap)
        if i: pipeline.pose_estimator.reset()
        result=pipeline.process(cap,i,i)
        result["detections"][0]["class"]="사람"
        result["observations"][0]["class"]="사람"
        recorder.analysis(result)
    recorder.close()
    Exporter(out,{}).finalize(source.metadata,pipeline.features,{})
    with Reader(out/"map.json") as r:
        assert r.objects()[0]["class"]=="사람"
        assert len(r.manifest["submaps"])==2
        with pytest.raises(ValueError,match="submap"):
            r.points()
        assert len(r.points(submap_id=0))>0
        assert "point_submap_id" in r.manifest["datasets"]
