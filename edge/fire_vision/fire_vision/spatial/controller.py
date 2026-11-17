"""State machine and bounded acquisition / recording / analysis workers."""
from collections import deque
from copy import deepcopy
from datetime import datetime, timezone
import json
import hashlib
import logging
from pathlib import Path
import queue
import threading
import time
import uuid

from .analysis import AnalysisPipeline
from .health import HealthMonitor
from .geometry import Synchronizer
from .io import StatusLED
from .runtime import inspect_runtime
from .sources import make_source
from .storage import Exporter, RawRecorder, StorageGuard, strict_json
from .types import Capture


class SessionController:
    def __init__(self,config,source_factory=make_source,pipeline_factory=AnalysisPipeline,
                 recorder_factory=RawRecorder,led=None):
        self.config=config
        self.source_factory=source_factory
        self.pipeline_factory=pipeline_factory
        self.recorder_factory=recorder_factory
        self.led=led or StatusLED()
        self.lock=threading.RLock()
        self.state="ERROR"
        self.error=None
        self.thread=None
        self.session_directory=None
        self.last_press=float("-inf")
        self.stop_event=threading.Event()
        self.shutdown_event=threading.Event()
        self.health=HealthMonitor()
        kind=config.get("source",{}).get("kind","synthetic")
        self.guard=StorageGuard(config["storage"],development=kind in ("synthetic","replay"))
        q=config.get("queues",{})
        self.sizes={name:int(q.get(name,default)) for name,default in (("raw",32),("ai",4),("result",8))}
        if min(self.sizes.values())<1: raise ValueError("queue capacities must be positive")
        self.raw_timeout=float(q.get("raw_timeout_s",2))
        if self.raw_timeout<=0: raise ValueError("raw queue timeout must be positive")

    def _state(self,state):
        self.state=state
        self.led.set_state(state)

    def prepare(self):
        with self.lock:
            if self.thread and self.thread.is_alive(): raise RuntimeError("session is active")
            source=None
            try:
                self.guard.check()
                self.environment=inspect_runtime()
                source=self.source_factory(self.config)
                source.open()
                pipeline=self.pipeline_factory(self.config,source.calibration,source.metadata)
                self.features=pipeline.features
                self.error=None
                self._state("READY")
            except Exception as exc:
                self.error=str(exc)
                self._state("ERROR")
                raise
            finally:
                if source is not None: source.close()

    def start(self):
        with self.lock:
            if self.shutdown_event.is_set() or self.state not in ("READY","DONE"): return False
            try:
                self.guard.check()
                name=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")+"-"+uuid.uuid4().hex[:12]
                self.session_directory=self.guard.path/name
                self.session_directory.mkdir(exist_ok=False)
            except Exception as exc:
                self.error=f"{type(exc).__name__}: {exc}"
                self._state("ERROR")
                logging.error("session start failed: %s",self.error)
                return False
            self.stop_event=threading.Event()
            self.health=HealthMonitor()
            self.error=None
            if hasattr(self,"stop_requested"): del self.stop_requested
            self.result=None
            self._state("RECORDING")
            self.thread=threading.Thread(target=self._run,name="spatial-session",daemon=False)
            self.thread.start()
            return True

    def stop(self):
        with self.lock:
            if self.state!="RECORDING": return False
            self.stop_requested=time.monotonic()
            self._state("FINALIZING")
            self.stop_event.set()
            return True

    def press(self,now=None):
        now=time.monotonic() if now is None else now
        with self.lock:
            if now-self.last_press<int(self.config.get("gpio",{}).get("debounce_ms",250))/1000:
                return False
            if self.state=="FINALIZING": return False
            self.last_press=now
            if self.state in ("READY","DONE"): return self.start()
            if self.state=="RECORDING": return self.stop()
            return False

    def wait(self,timeout=None):
        thread=self.thread
        if thread: thread.join(timeout)
        return self.state

    def status(self):
        return {"state":self.state,"error":self.error,"session_directory":str(self.session_directory) if self.session_directory else None,
                "health":self.health.snapshot(),"features":getattr(self,"features",{})}

    def close(self):
        self.request_shutdown()
        self.wait()
        self.led.close()

    def request_shutdown(self):
        self.shutdown_event.set()
        self.stop()

    def _run(self):
        raw_q=queue.Queue(self.sizes["raw"])
        ai_q=queue.Queue(self.sizes["ai"])
        result_q=queue.Queue(self.sizes["result"])
        collection_done=threading.Event()
        dispatch_done=threading.Event()
        analysis_done=threading.Event()
        writer_failed=threading.Event()
        errors=[]
        error_lock=threading.Lock()
        source=None
        workers=[]
        final_started=time.monotonic()

        def fail(exc):
            with error_lock:
                if not errors: errors.append(f"{type(exc).__name__}: {exc}")
            self.stop_event.set()

        try:
            source=self.source_factory(self.config)
            source.open()
            metadata=dict(source.metadata)
            calibration=deepcopy(source.calibration)
            metadata.update(result_revision=int(self.config.get("result_revision",1)), software="fire-vision-spatial/1.0.0",
                            environment=getattr(self,"environment",{}))
            metadata.update(config_sha256=hashlib.sha256(strict_json(self.config).encode()).hexdigest(),
                            calibration_sha256=hashlib.sha256(strict_json(calibration).encode()).hexdigest())
            if metadata.get("replay"):
                metadata["result_revision"]=int(source.metadata.get("result_revision",1))+1
                if self.session_directory.resolve().is_relative_to(Path(self.config["source"]["path"]).resolve()):
                    raise ValueError("replay output cannot overwrite input")
            pipeline=self.pipeline_factory(self.config,calibration,metadata)
            self.features=pipeline.features

            def analyze():
                epoch=-1
                try:
                    while not (dispatch_done.is_set() and ai_q.empty()):
                        if writer_failed.is_set(): return
                        try: capture,ci,di,new_epoch,pair=ai_q.get(timeout=.05)
                        except queue.Empty: continue
                        if new_epoch!=epoch:
                            pipeline.pose_estimator.reset()
                            pipeline.sync.last.clear()
                            epoch=new_epoch
                        result=pipeline.process(capture,ci,di,pair)
                        result["pair_recorded"]=True
                        result["inference_executed"]=bool(pipeline.detector.feature["status"]=="success" and ci>=0 and ci%pipeline.detector.interval==0)
                        self.health.analysis(result)
                        while not writer_failed.is_set():
                            try: result_q.put(result,timeout=.05); break
                            except queue.Full: continue
                        ai_q.task_done()
                        self.health.queues(result=result_q.qsize())
                except Exception as exc:
                    fail(exc)
                finally:
                    analysis_done.set()

            def write():
                recorder=None
                colors=deque(maxlen=2)
                pending=deque()
                epoch=0
                synchronizer=Synchronizer(self.config.get("sync",{}).get("tolerance_us",20000))
                last_check=0.

                def dispatch(capture,ci,di):
                    pair=synchronizer.pair(capture,ci,di)
                    recorder.pair(pair)
                    for event in synchronizer.events: recorder.event(event)
                    try: ai_q.put_nowait((capture,ci,di,epoch,pair))
                    except queue.Full:
                        self.health.add("ai_dropped")
                        recorder.event({"code":"ai_queue_full","depth_index":di,"time_us":capture.depth.time_us})
                    self.health.queues(ai=ai_q.qsize())

                def resolve(sample,di,pose):
                    nearest=min(colors,key=lambda x:abs(x[0].time_us-sample.time_us)) if colors else (None,-1)
                    dispatch(Capture(nearest[0],sample,synthetic_pose=pose),nearest[1],di)

                try:
                    self.guard.check()
                    recorder=self.recorder_factory(self.session_directory,metadata,calibration,self.config)
                    while True:
                        # Drain analysis in bounded batches, then return to raw priority.
                        for _ in range(self.sizes["result"] if raw_q.empty() else 0):
                            try: result=result_q.get_nowait()
                            except queue.Empty: break
                            recorder.analysis(result)
                            result_q.task_done()
                        if time.monotonic()-last_check>=float(self.config.get("storage",{}).get("check_interval_s",1)):
                            self.guard.check(); last_check=time.monotonic()
                        if collection_done.is_set() and raw_q.empty() and not dispatch_done.is_set():
                            while pending: resolve(*pending.popleft())
                            dispatch_done.set()
                        if dispatch_done.is_set() and analysis_done.is_set() and result_q.empty(): break
                        try: capture,events=raw_q.get(timeout=.01)
                        except queue.Empty:
                            if analysis_done.is_set() and not ai_q.empty():
                                while not ai_q.empty():
                                    try: ai_q.get_nowait(); ai_q.task_done()
                                    except queue.Empty: break
                            continue
                        ci,di=recorder.append(capture)
                        self.health.add("raw_bytes",sum(s.data.nbytes for s in (capture.color,capture.depth,*capture.imu) if s is not None))
                        for event in events: recorder.event(event)
                        if any(e["code"]=="timestamp_reset" for e in events):
                            while pending: resolve(*pending.popleft())
                            colors.clear(); epoch+=1
                        if capture.color is not None:
                            colors.append((capture.color,ci))
                            while pending and capture.color.time_us>=pending[0][0].time_us:
                                resolve(*pending.popleft())
                        if capture.depth is not None:
                            if capture.color is not None:
                                dispatch(capture,ci,di)
                            elif colors and colors[-1][0].time_us>=capture.depth.time_us:
                                resolve(capture.depth,di,capture.synthetic_pose)
                            else:
                                pending.append((capture.depth,di,capture.synthetic_pose))
                                if len(pending)>4: resolve(*pending.popleft())
                        raw_q.task_done()
                        self.health.queues(raw=raw_q.qsize(),ai=ai_q.qsize(),result=result_q.qsize())
                    self.health.add("hdf5_file_bytes_before_finalize",recorder.path.stat().st_size)
                except Exception as exc:
                    fail(exc)
                    writer_failed.set()
                    dispatch_done.set()
                finally:
                    if recorder is not None:
                        try: recorder.close()
                        except Exception as exc: fail(exc)

            workers=[threading.Thread(target=write,name="hdf5-writer"),threading.Thread(target=analyze,name="spatial-analysis")]
            for worker in workers: worker.start()
            try:
                # Source owns the stop policy and may emit a final IMU drain after stop.
                for capture in source.captures(self.stop_event):
                    if writer_failed.is_set(): break
                    events=self.health.sample(capture)
                    try:
                        raw_q.put((capture,events),timeout=self.raw_timeout)
                        self.health.queues(raw=raw_q.qsize())
                    except queue.Full:
                        self.health.add("raw_dropped",sum(s is not None for s in (capture.color,capture.depth))+len(capture.imu))
                        raise RuntimeError("raw recording queue sustained overflow; safe capture stop")
            except Exception as exc: fail(exc)
            finally:
                collection_done.set()
                source.close(); source=None
                final_started=getattr(self,"stop_requested",time.monotonic())
                with self.lock:
                    if self.state=="RECORDING": self._state("FINALIZING")
                for worker in workers: worker.join()
            if errors: raise RuntimeError(errors[0])
            self.guard.check()
            metrics=self.health.snapshot(time.monotonic()-final_started)
            self.result=Exporter(self.session_directory,self.config).finalize(metadata,pipeline.features,metrics,final_started)
            logging.info("result_ready=%s finalization_total_s=%.6f",self.session_directory/"map.json",time.monotonic()-final_started)
            with self.lock: self._state("DONE")
        except Exception as exc:
            self.stop_event.set()
            collection_done.set(); dispatch_done.set()
            writer_failed.set()
            for worker in workers:
                if worker.is_alive(): worker.join()
            self.error=str(exc)
            logging.exception("spatial session failed")
            try:
                with (self.session_directory/"failure.json").open("x") as f:
                    f.write(strict_json({"state":"ERROR","error":self.error,"health":self.health.snapshot()}))
            except OSError: logging.error("unable to persist failure record")
            with self.lock: self._state("ERROR")
        finally:
            if source is not None:
                try: source.close()
                except Exception: logging.exception("source close failed")
