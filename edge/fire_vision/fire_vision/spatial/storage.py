"""Single-writer HDF5, strict external-storage guard and commit protocol."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time

import h5py
import numpy as np

SCHEMA_VERSION = "1.0.0"
TEXT = h5py.string_dtype("utf-8")
PAIR = np.dtype([("color_index", "<i8"), ("depth_index", "<i8"), ("delta_us", "<i8"), ("valid", "?"), ("reason", "S96")])
DETECTION = np.dtype([("color_index", "<i8"), ("class", "S128"), ("bbox", "<f4", (4,)), ("confidence", "<f4"), ("synthetic", "?")])
POSE = np.dtype([("depth_index", "<i8"), ("time_us", "<i8"), ("submap_id", "<i8"), ("status", "S48"), ("T_map_from_depth", "<f8", (4,4)), ("synthetic", "?")])
OBSERVATION = np.dtype([
    ("id", "S96"), ("object_id", "S96"), ("color_index", "<i8"), ("depth_index", "<i8"),
    ("detection_index", "<i8"), ("pose_index", "<i8"), ("time_us", "<i8"), ("class", "S128"),
    ("bbox", "<f4", (4,)), ("detection_confidence", "<f8"), ("point_camera_m", "<f8", (3,)),
    ("position_m", "<f8", (3,)), ("submap_id", "<i8"), ("position_status", "S64"),
    ("failure_reason", "S128"), ("motion_status", "S32"), ("valid_depth_ratio", "<f8"),
    ("depth_variance_m2", "<f8"), ("synthetic", "?")])


def strict_json(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(1024*1024), b""):
            h.update(block)
    return h.hexdigest()


def fsync_directory(path):
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


class StorageGuard:
    def __init__(self, config, development=False):
        self.config = config
        self.path = Path(config["path"]).expanduser().resolve()
        self.development = development

    def check(self):
        c = self.config
        if c.get("allow_local", False):
            if not self.development:
                raise ValueError("local storage is restricted to explicit development inputs")
        else:
            mount = Path(c.get("mount_path", self.path)).resolve()
            if not mount.is_mount() or mount == Path("/"):
                raise OSError("expected external SSD mount is absent")
            if not self.path.is_relative_to(mount):
                raise ValueError("storage path must be inside expected mount")
            if not c.get("expected_uuid"):
                raise ValueError("expected SSD UUID must be configured")
            try:
                value = subprocess.run(["findmnt", "--json", "--target", str(self.path if self.path.exists() else mount),
                                        "--output", "TARGET,SOURCE,UUID"], check=True, capture_output=True, text=True)
                info = json.loads(value.stdout)["filesystems"][0]
            except (OSError, subprocess.SubprocessError, KeyError, IndexError, json.JSONDecodeError) as e:
                raise OSError("cannot verify SSD mount/device UUID") from e
            if Path(info["target"]).resolve() != mount or info.get("uuid") != c["expected_uuid"]:
                raise OSError("SSD mount/device UUID mismatch")
        # Only create directories after verifying the device. Never create a missing mount.
        self.path.mkdir(parents=True, exist_ok=True)
        free = shutil.disk_usage(self.path).free
        if free < int(c.get("min_free_bytes", 1024**3)):
            raise OSError("insufficient storage space")
        # A real write detects read-only mounts/ACLs that os.access cannot establish.
        with tempfile.TemporaryFile(dir=self.path) as f:
            f.write(b"storage-probe")
            f.flush()
        return free


def append_array(ds, rows):
    rows = np.asarray(rows, dtype=ds.dtype)
    start = len(ds)
    ds.resize(start + len(rows), axis=0)
    ds[start:] = rows
    return start


def decode(value):
    return value.decode("utf-8") if isinstance(value, bytes) else value


def vector_or_nan(value, shape):
    return np.full(shape, np.nan) if value is None else np.asarray(value).reshape(shape)


def table_value(dtype,value):
    if dtype.kind=="S" and isinstance(value,str):
        value=value.encode("utf-8")
        if len(value)>dtype.itemsize:
            raise ValueError("table string exceeds documented UTF-8 byte length")
    return value


class RawRecorder:
    """One owner thread throughout capture; ownership transfers only after close()."""
    def __init__(self, directory, metadata, calibration, config):
        self.directory = Path(directory)
        self.config = config
        self.path = self.directory / "session.h5.partial"
        if (self.directory / "session.h5").exists():
            raise FileExistsError(self.directory / "session.h5")
        cache_bytes=int(config.get("hdf5",{}).get("cache_bytes",8*1024*1024))
        if cache_bytes<1: raise ValueError("HDF5 cache_bytes must be positive")
        self.h5 = h5py.File(self.path, "x",rdcc_nbytes=cache_bytes)
        self.h5.attrs.update(schema_version=SCHEMA_VERSION, finalized=False, synthetic=bool(metadata.get("synthetic", False)))
        self.h5.create_dataset("meta/json", data=strict_json(metadata), dtype=TEXT)
        self.h5.create_dataset("meta/config", data=strict_json(config), dtype=TEXT)
        self.h5.create_dataset("calibration/json", data=strict_json(calibration), dtype=TEXT)
        for stream in ("color", "depth", "imu/accel", "imu/gyro"):
            g = self.h5.require_group("raw/" + stream)
            for name in ("frame_id", "sensor_timestamp", "host_monotonic_ns", "time_us"):
                self._dataset(g, name, (), "<i8")
            if stream == "depth":
                self._dataset(g, "depth_scale_m", (), "<f8")
            if stream.startswith("imu/"):
                self._dataset(g,"data",(3,),"<f8")
                g.attrs["unit"] = "m/s^2" if stream.endswith("accel") else "rad/s"
        self.h5["raw/color"].attrs.update(channel_order="RGB", color_space="sRGB")
        self._dataset(self.h5["raw"], "synthetic_poses", (4,4), "<f8")
        for name, dtype in (("sync/pairs", PAIR), ("derived/detections", DETECTION),
                            ("derived/poses", POSE), ("derived/observations", OBSERVATION)):
            parent, leaf = name.rsplit("/",1)
            self._dataset(self.h5.require_group(parent), leaf, (), dtype)
        for name in ("detections_by_color", "observations_by_color"):
            self._dataset(self.h5["derived"], name, (2,), "<i8")
        for group in ("derived/surface_points", "map/points"):
            g = self.h5.require_group(group)
            self._dataset(g,"positions",(3,),"<f4")
            self._dataset(g,"colors",(3,),"u1")
            self._dataset(g,"pose_index",(),"<i8")
            self._dataset(g,"depth_index",(),"<i8")
            g.attrs["unit"] = "m"
        self._dataset(self.h5["map/points"],"submap_id",(),"<i8")
        self.h5["derived/surface_points"].attrs["frame"] = "depth_optical"
        self.h5["map/points"].attrs["frame"] = "per_submap_map_local"
        self._dataset(self.h5.require_group("quality"),"events",(),TEXT)
        self.bytes_written = 0

    def _dataset(self, group, name, shape, dtype):
        compression = self.config.get("hdf5", {}).get("compression", "lzf")
        if compression not in (None, "gzip", "lzf"):
            raise ValueError("HDF5 compression must be null, gzip or lzf")
        n = max(1, int(self.config.get("hdf5", {}).get("chunk_rows", 128)))
        # Images are always frame-addressable without decompressing other frames.
        chunk = (1 if len(shape)>=2 else n,) + tuple(shape)
        return group.create_dataset(name, shape=(0,)+tuple(shape), maxshape=(None,)+tuple(shape),
                                    dtype=dtype, chunks=chunk, compression=compression)

    def append(self, capture):
        indices = []
        for name, sample in (("color", capture.color), ("depth", capture.depth)):
            indices.append(self._sample(name, sample) if sample is not None else None)
        for sample in capture.imu:
            if sample.stream not in ("accel", "gyro"):
                raise ValueError("unsupported IMU stream")
            self._sample("imu/" + sample.stream, sample)
        if capture.depth is not None:
            append_array(self.h5["raw/synthetic_poses"], [vector_or_nan(capture.synthetic_pose,(4,4))])
        if capture.color is not None:
            for name in ("detections_by_color", "observations_by_color"):
                append_array(self.h5["derived/"+name], [[-1,0]])
        return tuple(indices)

    def _sample(self, name, sample):
        g = self.h5["raw/"+name]
        if not isinstance(sample.sensor_timestamp, (int,np.integer)):
            raise ValueError("original sensor timestamp must be integer")
        if "data" not in g:
            self._dataset(g,"data",sample.data.shape,sample.data.dtype)
        if sample.data.shape != g["data"].shape[1:] or sample.data.dtype != g["data"].dtype:
            raise ValueError("stream profile/dtype changed within a session")
        if "clock" in g.attrs and (g.attrs["clock"] != sample.clock or g.attrs["timestamp_unit"] != sample.timestamp_unit):
            raise ValueError("stream clock/unit changed within a session")
        g.attrs.update(clock=sample.clock,timestamp_unit=sample.timestamp_unit,processing_time_unit="us")
        if name == "depth" and (sample.depth_scale_m is None or not np.isfinite(sample.depth_scale_m) or sample.depth_scale_m <= 0):
            raise ValueError("positive per-frame depth scale required")
        index = append_array(g["data"],sample.data[None])
        for field in ("frame_id", "sensor_timestamp", "host_monotonic_ns", "time_us"):
            append_array(g[field],[getattr(sample,field)])
        if name == "depth":
            append_array(g["depth_scale_m"],[sample.depth_scale_m])
        self.bytes_written += sample.data.nbytes
        return index

    def event(self, event):
        append_array(self.h5["quality/events"],[strict_json(event)])

    def pair(self,p):
        pair = np.zeros(1,PAIR)
        for key in PAIR.names:
            pair[key] = p.get(key, "" if key=="reason" else -1)
        append_array(self.h5["sync/pairs"], pair)

    def analysis(self, result):
        if not result.get("pair_recorded",False): self.pair(result["pair"])
        p = result["pose"]
        pose = np.zeros(1,POSE)
        for key in POSE.names:
            if key == "T_map_from_depth":
                pose[key] = vector_or_nan(p.get(key),(4,4))
            elif key == "submap_id":
                pose[key] = p.get(key) if p.get(key) is not None else -1
            else:
                pose[key] = p.get(key,False if key=="synthetic" else "" if key=="status" else -1)
        pose_index = append_array(self.h5["derived/poses"],pose)
        detections = result.get("detections", [])
        rows = np.zeros(len(detections),DETECTION)
        for i,d in enumerate(detections):
            for key in DETECTION.names:
                rows[key][i]=table_value(DETECTION[key],d[key])
        detection_start = append_array(self.h5["derived/detections"],rows)
        observations = result.get("observations", [])
        rows = np.zeros(len(observations), OBSERVATION)
        for i,o in enumerate(observations):
            for key in OBSERVATION.names:
                value = o.get(key)
                if key == "detection_index": value=detection_start+i
                elif key == "pose_index": value=pose_index
                elif key in ("point_camera_m", "position_m"): value=vector_or_nan(value,(3,))
                elif key == "depth_variance_m2": value=float("nan") if value is None else value
                elif key == "submap_id": value=-1 if value is None else value
                elif OBSERVATION[key].kind == "S": value="" if value is None else value
                rows[key][i]=table_value(OBSERVATION[key],value)
        observation_start = append_array(self.h5["derived/observations"],rows)
        if p.get("depth_index", -1) >= 0 and result["pair"].get("color_index", -1) >= 0:
            ci = result["pair"]["color_index"]
            # A color can pair to multiple depths; contiguous rows are preserved.
            for name,start,count in (("detections_by_color",detection_start,len(detections)),
                                     ("observations_by_color",observation_start,len(observations))):
                ds=self.h5["derived/"+name]
                old=ds[ci]
                if old[1] and old[0]+old[1] != start:
                    raise ValueError("noncontiguous per-color analysis records")
                ds[ci]=[start if not old[1] else old[0],old[1]+count]
        points = np.asarray(result.get("points",np.empty((0,3))),np.float32).reshape(-1,3)
        g=self.h5["derived/surface_points"]
        append_array(g["positions"],points)
        append_array(g["colors"],np.asarray(result.get("point_colors",np.zeros_like(points)),np.uint8).reshape(-1,3))
        append_array(g["pose_index"],np.full(len(points),pose_index))
        append_array(g["depth_index"],np.full(len(points),p["depth_index"]))
        for event in result.get("events",[]):
            self.event(event)

    def close(self):
        if self.h5:
            self.h5.flush()
            self.h5.close()


class MapBuilder:
    """Rebuild all map coordinates from final poses, retaining submap identity."""
    def build(self, h5):
        poses=h5["derived/poses"]
        output=h5["map/points"]
        for ds in output.values(): ds.resize(0,axis=0)
        surface=h5["derived/surface_points"]
        for start in range(0,len(surface["positions"]),8192):
            end=start+8192
            pts=surface["positions"][start:end]
            ids=surface["pose_index"][start:end]
            for pi in np.unique(ids):
                pose=poses[int(pi)]
                T=pose["T_map_from_depth"]
                if decode(pose["status"]) != "tracked" or not np.isfinite(T).all(): continue
                select=ids==pi
                transformed=pts[select] @ T[:3,:3].T+T[:3,3]
                append_array(output["positions"],transformed)
                append_array(output["colors"],surface["colors"][start:end][select])
                append_array(output["pose_index"],ids[select])
                append_array(output["depth_index"],surface["depth_index"][start:end][select])
                append_array(output["submap_id"],np.full(int(select.sum()),pose["submap_id"]))
        observations=h5["derived/observations"]
        for i in range(len(observations)):
            row=observations[i]
            pose=poses[int(row["pose_index"])]
            T=pose["T_map_from_depth"]
            if decode(pose["status"])=="tracked" and np.isfinite(T).all() and np.isfinite(row["point_camera_m"]).all():
                row["position_m"] = T[:3,:3] @ row["point_camera_m"] + T[:3,3]
                row["submap_id"]=pose["submap_id"]
                row["position_status"]=b"map_valid"
                row["failure_reason"]=b""
            else:
                row["position_m"]=np.nan
                row["submap_id"]=-1
                if np.isfinite(row["point_camera_m"]).all():
                    if decode(row["position_status"])=="map_valid" or not decode(row["failure_reason"]):
                        row["failure_reason"]=b"final_pose_invalid"
                    row["position_status"]=b"camera_valid"
                else:
                    row["position_status"]=b"invalid"
                    if not decode(row["failure_reason"]): row["failure_reason"]=b"invalid_depth"
            observations[i]=row


class Exporter:
    def __init__(self,directory,config):
        self.directory=Path(directory)
        self.config=config

    def finalize(self,metadata,features,health,finalization_started=None):
        finalization_started=time.monotonic() if finalization_started is None else finalization_started
        health=dict(health)
        health["queue_drain_s"]=health.pop("finalization_s",None)
        directory=self.directory
        if (directory/"map.json").exists() or (directory/"session.h5").exists():
            raise FileExistsError("final result already exists")
        temp=directory/"session.h5.partial"
        with h5py.File(temp,"r+") as f:
            MapBuilder().build(f)
            metadata=dict(metadata,features=features)
            f["meta/json"][()]=strict_json(metadata)
            f.create_dataset("quality/metrics",data=strict_json(health),dtype=TEXT)
            result=self._manifest(f,metadata,features,health)
            from .reader import validate_hdf5
            validate_hdf5(f,result)
            f.attrs["finalized"]=True
            f.flush()
        with temp.open("rb") as stream: os.fsync(stream.fileno())
        final=directory/"session.h5"
        temp.rename(final)
        fsync_directory(directory)
        result["hdf5"].update(size_bytes=final.stat().st_size,sha256=sha256(final))
        result["quality"]["metrics"].update(finalization_s=time.monotonic()-finalization_started,
            finalization_measurement_boundary="before_map_json_commit",hdf5_size_bytes=final.stat().st_size)
        from .reader import validate_manifest
        validate_manifest(result)
        path=directory/"map.json.partial"
        with path.open("x",encoding="utf-8") as stream:
            stream.write(strict_json(result)+"\n")
            stream.flush()
            os.fsync(stream.fileno())
        path.rename(directory/"map.json")
        fsync_directory(directory)
        return result

    def _manifest(self,f,metadata,features,health):
        poses=f["derived/poses"]
        submaps={}
        failures=[]
        for i in range(len(poses)):
            p=poses[i]
            if decode(p["status"])=="tracked":
                sid=int(p["submap_id"])
                if sid not in submaps:
                    submaps[sid]={"id":sid,"alignment_status":"local_only","aligned_to":None,"origin_pose_index":i}
            else:
                failures.append({"start_us":int(p["time_us"]),"end_us":int(p["time_us"]),"status":decode(p["status"])})
        objects={}
        for i in range(len(f["derived/observations"])):
            o=f["derived/observations"][i]
            position=o["position_m"].tolist() if np.isfinite(o["position_m"]).all() else None
            identity=decode(o["object_id"])
            previous=objects.get(identity)
            current={"id":identity,"class":decode(o["class"]),
                "submap_id":int(o["submap_id"]) if o["submap_id"]>=0 else None,"position_m":position,
                "position_semantics":"observed_surface_representative","detection_confidence":float(o["detection_confidence"]),
                "position_status":decode(o["position_status"]),"failure_reason":decode(o["failure_reason"]) or None,
                "motion_status":decode(o["motion_status"]),"first_seen_us":int(o["time_us"]),"last_seen_us":int(o["time_us"]),
                "observation_count":1,"observations":[{"dataset":"/derived/observations","index":i}],"synthetic":bool(o["synthetic"])}
            if previous is not None:
                current["first_seen_us"]=min(previous["first_seen_us"],current["first_seen_us"])
                current["observation_count"]+=previous["observation_count"]
                current["observations"]=previous["observations"]+current["observations"]
            objects[identity]=current
        times=[]
        for name in ("color","depth","imu/accel","imu/gyro"):
            ds=f["raw/"+name+"/host_monotonic_ns"]
            for offset in range(0,len(ds),8192):
                block=ds[offset:offset+8192]
                if len(block): times.extend((int(block.min()),int(block.max())))
        warnings=["unobserved_space_unknown","surface_points_do_not_establish_safe_routes"]
        if metadata.get("synthetic"): warnings.append("synthetic_input_not_a_measured_map")
        if len(submaps)>1: warnings.append("submaps_are_not_registered_to_each_other")
        if not len(f["derived/detections"]): warnings.append("no_object_detections")
        if features.get("pose",{}).get("loop_closure") is False: warnings.append("odometry_or_fixture_only_no_loop_closure")
        complete=(bool(submaps) and not failures and not metadata.get("synthetic") and
                  not health.get("ai_dropped",0) and not health.get("sensor_frame_gaps",0) and
                  all(features.get(k,{}).get("status")=="success" for k in ("detector","pose","preprocessor")))
        states=dict(features)
        states["mapping"]={"status":"success" if submaps else "disabled","reason":None if submaps else "valid_pose_unavailable"}
        states["recording"]={"status":"success"}
        return {"schema_version":SCHEMA_VERSION,"session_id":directory_name(self.directory),"result_revision":metadata.get("result_revision",1),
            "status":"complete" if complete else "partial","synthetic":bool(metadata.get("synthetic",False)),
            "hdf5":{"path":"session.h5","size_bytes":0,"sha256":"0"*64},
            "coordinates":{"length_unit":"m","angle_unit":"rad","depth_optical":"X right, Y down, Z forward",
                "color_optical":"X right, Y down, Z forward","map_local":"X forward, Y left, Z up",
                "matrix_storage":"row-major","multiplication":"column vectors: p_map = T_map_from_depth @ p_depth",
                "T_initial_map_from_depth":[[0,0,1,0],[-1,0,0,0],[0,-1,0,0],[0,0,0,1]],
                "origin":"first valid camera pose of each independent submap","gravity_aligned":False},
            "time":{"unit":"us","dtype":"int64","basis":"session_start","duration_us":(max(times)-min(times))//1000 if times else 0,
                "duration_basis":"host_monotonic_receive_span",
                "clock_conversion":metadata.get("clock_conversion",{})},
            "submaps":list(submaps.values()),"datasets":{"points":"/map/points/positions","point_colors":"/map/points/colors",
                "point_pose_index":"/map/points/pose_index","point_submap_id":"/map/points/submap_id",
                "trajectory":"/derived/poses","observations":"/derived/observations"},
            "objects":list(objects.values()),"features":states,"quality":{"metrics":health,"tracking_failures":failures,"warnings":warnings,
                "events_dataset":"/quality/events"}}


def directory_name(path):
    return Path(path).name
