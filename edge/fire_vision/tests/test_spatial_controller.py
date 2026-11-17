import time
import threading
import numpy as np
import pytest

from fire_vision.spatial.controller import SessionController
from fire_vision.spatial.reader import Reader
from fire_vision.spatial.sources import SyntheticSource


def config(tmp_path):
    return {"source":{"kind":"synthetic","frames":12,"width":16,"height":12,"fps":30,"realtime":True},
            "storage":{"path":str(tmp_path),"allow_local":True,"min_free_bytes":1},
            "queues":{"raw":4,"ai":2,"result":2,"raw_timeout_s":.2},
            "detector":{"backend":"synthetic"},"pose":{"backend":"synthetic"},
            "gpio":{"debounce_ms":50},"depth":{"sample_stride":4}}


def test_repeated_sessions_and_debounce(tmp_path):
    c=SessionController(config(tmp_path))
    c.prepare()
    assert c.state=="READY"
    assert c.press(now=1.)
    assert c.state=="RECORDING"
    assert not c.press(now=1.01)
    assert c.press(now=1.1)
    assert c.state=="FINALIZING"
    assert not c.press(now=1.2)
    c.wait(10)
    assert c.state=="DONE",c.error
    first=c.session_directory
    assert (first/"map.json").exists()
    c.start()
    c.wait(10)
    assert c.state=="DONE",c.error
    assert first != c.session_directory
    with Reader(c.session_directory/"map.json") as r:
        assert r.manifest["synthetic"] is True
        assert r.manifest["status"]=="partial"
        assert r.manifest["quality"]["metrics"]["raw_dropped"]==0


class BrokenSource(SyntheticSource):
    def captures(self,stop_event):
        yield next(super().captures(stop_event))
        raise OSError("camera disconnected")


def test_camera_failure_preserves_partial_without_ready_marker(tmp_path):
    c=SessionController(config(tmp_path),source_factory=lambda cfg:BrokenSource(cfg))
    c.prepare(); c.start(); c.wait(10)
    assert c.state=="ERROR"
    assert "disconnected" in c.error
    assert not (c.session_directory/"map.json").exists()
    assert (c.session_directory/"failure.json").exists()


def test_analysis_backpressure_drops_ai_preserves_raw(tmp_path):
    from fire_vision.spatial.analysis import AnalysisPipeline
    class Slow(AnalysisPipeline):
        def process(self,*args):
            time.sleep(.03)
            return super().process(*args)
    cfg=config(tmp_path)
    cfg["source"].update(frames=30,realtime=False)
    cfg["queues"].update(raw=32,ai=1)
    c=SessionController(cfg,pipeline_factory=Slow)
    c.prepare(); c.start(); c.wait(20)
    assert c.state=="DONE",c.error
    with Reader(c.session_directory/"map.json") as r:
        assert len(r.h5["raw/depth/data"])==30
        assert len(r.h5["sync/pairs"])==30
        assert r.manifest["quality"]["metrics"]["ai_dropped"]>0
        assert r.manifest["status"]=="partial"


def test_write_failure_never_publishes_result(tmp_path):
    from fire_vision.spatial.storage import RawRecorder
    class BrokenWriter(RawRecorder):
        def append(self,capture):
            raise OSError("simulated SSD write failure")
    c=SessionController(config(tmp_path),recorder_factory=BrokenWriter)
    c.prepare(); c.start(); c.wait(10)
    assert c.state=="ERROR"
    assert not (c.session_directory/"map.json").exists()
    assert "write failure" in c.error


def test_sustained_raw_overflow_is_error(tmp_path):
    from fire_vision.spatial.storage import RawRecorder
    class SlowWriter(RawRecorder):
        def append(self,capture):
            time.sleep(.03)
            return super().append(capture)
    cfg=config(tmp_path)
    cfg["source"].update(frames=30,realtime=False)
    cfg["queues"].update(raw=1,raw_timeout_s=.005)
    c=SessionController(cfg,recorder_factory=SlowWriter)
    c.prepare(); c.start(); c.wait(10)
    assert c.state=="ERROR"
    assert c.health.snapshot()["raw_dropped"]>0
    assert not (c.session_directory/"map.json").exists()


def test_health_latency_averages_executed_inferences_only():
    from fire_vision.spatial.health import HealthMonitor
    health=HealthMonitor()
    health.analysis({"inference_executed":True,"inference_latency_ms":10})
    health.analysis({"inference_executed":False,"inference_latency_ms":1})
    result=health.snapshot()
    assert result["inferences"]==1
    assert result["inference_latency_mean_ms"]==10


def test_storage_loss_before_press_sets_error(tmp_path):
    c=SessionController(config(tmp_path))
    c.prepare()
    def missing(): raise OSError("SSD disconnected")
    c.guard.check=missing
    assert c.press() is False
    assert c.state=="ERROR"
    assert "SSD disconnected" in c.error


def test_sigterm_during_prepare_does_not_start_session(tmp_path,monkeypatch):
    import json
    import signal
    from fire_vision.spatial import cli
    path=tmp_path/"config.json"
    path.write_text(json.dumps(config(tmp_path)))
    prepare=SessionController.prepare
    starts=[]
    def prepare_and_signal(self):
        prepare(self)
        signal.raise_signal(signal.SIGTERM)
    def unexpected_start(self):
        starts.append(True)
        raise AssertionError("must not start after shutdown request")
    monkeypatch.setattr(SessionController,"prepare",prepare_and_signal)
    monkeypatch.setattr(SessionController,"start",unexpected_start)
    assert cli.main(["record","--config",str(path)])==0
    assert not starts


def test_record_replay_preserves_all_raw_streams(tmp_path):
    import h5py
    cfg=config(tmp_path)
    cfg["source"].update(frames=5,realtime=False)
    cfg["queues"].update(raw=64,ai=64)
    first=SessionController(cfg)
    first.prepare(); first.start(); first.wait(10)
    assert first.state=="DONE",first.error
    cfg["source"]={"kind":"replay","path":str(first.session_directory/"session.h5")}
    second=SessionController(cfg)
    second.prepare(); second.start(); second.wait(10)
    assert second.state=="DONE",second.error
    with h5py.File(first.session_directory/"session.h5") as a,h5py.File(second.session_directory/"session.h5") as b:
        for stream in ("color","depth","imu/accel","imu/gyro"):
            prefix="raw/"+stream
            for name in a[prefix]:
                np.testing.assert_array_equal(a[prefix+"/"+name][...],b[prefix+"/"+name][...])
            assert dict(a[prefix].attrs)==dict(b[prefix].attrs)
        assert a["calibration/json"][()]==b["calibration/json"][()]
    with Reader(second.session_directory/"map.json") as r:
        assert r.manifest["result_revision"]==2
        assert len(r.h5["sync/pairs"])==5
