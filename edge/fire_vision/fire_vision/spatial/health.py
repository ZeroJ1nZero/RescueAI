"""Bounded-memory counters. Rates refer to this host run, not target estimates."""
import platform
import resource
import threading
import time


class HealthMonitor:
    def __init__(self):
        self.lock=threading.Lock()
        self.started=time.monotonic()
        self.counters={"color_frames":0,"depth_frames":0,"imu_samples":0,"raw_dropped":0,
                       "sensor_frame_gaps":0,"ai_dropped":0,"analysis_frames":0,"inferences":0,
                       "tracking_successes":0,"raw_bytes":0}
        self.peaks={"raw":0,"ai":0,"result":0}
        self.totals={"inference_latency_ms":0.,"valid_depth_ratio":0.}
        self.maximum_latency=0.
        self.last_frame={}
        self.last_time={}

    def add(self,key,value=1):
        with self.lock: self.counters[key]=self.counters.get(key,0)+value

    def sample(self,capture):
        events=[]
        with self.lock:
            for sample in (capture.color,capture.depth,*capture.imu):
                if sample is None: continue
                stream=sample.stream
                old=self.last_frame.get(stream)
                prev=self.last_time.get(stream)
                if old is not None and sample.frame_id>old+1:
                    self.counters["sensor_frame_gaps"]+=sample.frame_id-old-1
                    events.append({"code":"sensor_frame_gap","stream":stream,"time_us":sample.time_us,"count":sample.frame_id-old-1})
                if prev is not None and (sample.sensor_timestamp<prev[0] or sample.time_us<prev[1] or (old is not None and sample.frame_id<old)):
                    events.append({"code":"timestamp_reset","stream":stream,"time_us":sample.time_us})
                self.last_frame[stream]=sample.frame_id
                self.last_time[stream]=(sample.sensor_timestamp,sample.time_us)
                key=stream+"_frames" if stream in ("color","depth") else "imu_samples"
                self.counters[key]+=1
        return events

    def queues(self,**sizes):
        with self.lock:
            for name,size in sizes.items(): self.peaks[name]=max(self.peaks[name],size)

    def analysis(self,result):
        with self.lock:
            self.counters["analysis_frames"]+=1
            self.counters["inferences"]+=int(bool(result.get("inference_executed",False)))
            self.counters["tracking_successes"]+=int(result.get("tracking_success",False))
            self.totals["valid_depth_ratio"]+=float(result.get("valid_depth_ratio",0))
            if result.get("inference_executed",False):
                self.totals["inference_latency_ms"]+=float(result.get("inference_latency_ms",0))
                self.maximum_latency=max(self.maximum_latency,float(result.get("inference_latency_ms",0)))

    def snapshot(self,finalization_s=None):
        with self.lock:
            elapsed=max(time.monotonic()-self.started,1e-9)
            n=self.counters["analysis_frames"]
            inferences=self.counters["inferences"]
            rss=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            return {**self.counters,"elapsed_s":elapsed,"capture_fps":self.counters["depth_frames"]/elapsed,
                    "inference_fps":self.counters["inferences"]/elapsed,"ssd_payload_bytes_per_s":self.counters["raw_bytes"]/elapsed,
                    "queue_peak":dict(self.peaks),"memory_peak_bytes":int(rss if platform.system()=="Darwin" else rss*1024),
                    "inference_latency_mean_ms":self.totals["inference_latency_ms"]/inferences if inferences else None,
                    "inference_latency_max_ms":self.maximum_latency if inferences else None,
                    "valid_depth_ratio":self.totals["valid_depth_ratio"]/n if n else None,
                    "tracking_success_ratio":self.counters["tracking_successes"]/n if n else None,
                    "finalization_s":finalization_s}
