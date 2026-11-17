"""Real subprocess: systemd-style EOF must keep service alive until SIGTERM."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time


def test_service_eof_and_sigterm_finalize(tmp_path):
    cfg={"source":{"kind":"synthetic","frames":10000,"fps":30,"realtime":True},
         "storage":{"path":str(tmp_path/"sessions"),"allow_local":True,"min_free_bytes":1},
         "pose":{"backend":"synthetic"},"detector":{"backend":"synthetic"}}
    path=tmp_path/"config.json"; path.write_text(json.dumps(cfg))
    log=tmp_path/"service.log"
    with log.open("w") as output:
        proc=subprocess.Popen([sys.executable,"-m","fire_vision","spatial","serve","--config",str(path)],
                              stdin=subprocess.PIPE,stdout=output,stderr=subprocess.STDOUT,text=True)
        try:
            proc.stdin.write("start\n"); proc.stdin.flush(); proc.stdin.close()
            deadline=time.monotonic()+10
            while "state=RECORDING" not in log.read_text():
                assert proc.poll() is None,log.read_text()
                assert time.monotonic()<deadline,log.read_text()
                time.sleep(.02)
            time.sleep(.1)
            assert proc.poll() is None # EOF did not stop acquisition/service
            proc.send_signal(signal.SIGTERM)
            assert proc.wait(timeout=15)==0,log.read_text()
        finally:
            if proc.poll() is None:
                proc.kill(); proc.wait()
    manifests=list((tmp_path/"sessions").glob("*/map.json"))
    assert len(manifests)==1,log.read_text()
    from fire_vision.spatial.reader import Reader
    with Reader(manifests[0]) as r:
        assert r.manifest["status"]=="partial"
        assert len(r.h5["raw/depth/time_us"])<10000
