"""ROS2 sensor-only replay. The ROS transport requires target validation."""
import json
import math
import time
from pathlib import Path
import numpy as np

from .dataset_adapter import load_dataset, depth_meters
from .export import sha256, verify_export, write_json


def schedule(stamps, rate):
    if not math.isfinite(rate) or rate <= 0:
        raise ValueError("positive finite replay rate required")
    if not stamps or any(b < a for a,b in zip(stamps,stamps[1:])):
        raise ValueError("nonempty nondecreasing schedule required")
    return [((t-stamps[0])/1e9/rate,t) for t in stamps]


def verified_input(root, validated_session, config):
    """Bind a replay to E0 diagnostics, input hashes and the exact config."""
    previous = Path(validated_session)
    s = json.loads((previous/"session.json").read_text())
    e0 = json.loads((previous/"e0_validation.json").read_text())
    if s["stages"]["E0"]["status"] != "passed" or e0["status"] != "passed":
        raise ValueError("measured E0 validation has not passed")
    if verify_export(previous)["hash_mismatches"]:
        raise ValueError("E0 session integrity check failed")
    if s["config"] != config:
        raise ValueError("config differs from validated E0 session")
    if sha256(Path(root)/"manifest.json") != e0["input_manifest_sha256"] or sha256(Path(root)/"calibration.json") != e0["input_calibration_sha256"]:
        raise ValueError("dataset changed after validation")
    if not e0.get("input_file_sha256"):
        raise ValueError("validated image hashes unavailable; rerun E0")
    if any(not (Path(root)/name).is_file() or sha256(Path(root)/name) != digest for name,digest in e0["input_file_sha256"].items()):
        raise ValueError("dataset image content changed after validation")
    return e0


def replay_ros(root, config, validated_session, session):
    """Publish raw accel and gyro separately. No interpolated/filtered IMU claim."""
    e0 = verified_input(root, validated_session, config)
    manifest, calibration = load_dataset(root)
    import rclpy
    from rclpy.node import Node
    from rclpy.parameter import Parameter
    from rclpy.qos import QoSProfile, ReliabilityPolicy
    from sensor_msgs.msg import Image, Imu, CameraInfo
    from geometry_msgs.msg import TransformStamped
    from rosgraph_msgs.msg import Clock
    from builtin_interfaces.msg import Time
    from tf2_ros.static_transform_broadcaster import StaticTransformBroadcaster
    rclpy.init()
    node = Node("fire_vision_replay", parameter_overrides=[Parameter("use_sim_time", value=True)])
    qos = QoSProfile(depth=100, reliability=ReliabilityPolicy.RELIABLE)
    streams = manifest["streams"]
    publishers = {k: node.create_publisher(Image if k in ("rgb","depth") else Imu,config["topics"][k],qos) for k in streams}
    camera_pub = node.create_publisher(CameraInfo,config["topics"]["camera_info"],qos)
    clock_pub = node.create_publisher(Clock,"/clock",qos)
    broadcaster = StaticTransformBroadcaster(node)
    def ros_time(t):
        return Time(sec=int(t//1_000_000_000),nanosec=int(t%1_000_000_000))
    transforms = []
    for tf in calibration["transforms"]:
        msg = TransformStamped()
        msg.header.stamp = ros_time(manifest["extraction"]["start_ns"])
        msg.header.frame_id, msg.child_frame_id = tf["header"]["frame_id"], tf["child_frame_id"]
        for axis in ("x","y","z"):
            setattr(msg.transform.translation,axis,float(tf["transform"]["translation"][axis]))
        for axis in ("x","y","z","w"):
            setattr(msg.transform.rotation,axis,float(tf["transform"]["rotation"][axis]))
        transforms.append(msg)
    broadcaster.sendTransform(transforms)
    events = sorted((r["timestamp_ns"],key,i) for key,rows in streams.items() for i,r in enumerate(rows))
    waits = schedule([t for t,_,_ in events],config["replay"]["rate"])
    counts = {k:0 for k in streams}
    lateness = []
    session.data["replay"] = {"status":"running","clock":"/clock","sensor_timestamps":"original",
                               "imu_policy":"separate raw accel and gyro; original intervals; no orientation fusion",
                               "consumer_clock_requirement":"Every consumer must set use_sim_time=true"}
    session.finish()
    log = (session.path/"replay_events.jsonl").open("w")
    began = time.monotonic()
    try:
        for (stamp,key,index),(offset,_) in zip(events,waits):
            while rclpy.ok() and time.monotonic()-began < offset:
                rclpy.spin_once(node,timeout_sec=min(0.01,max(0,offset-(time.monotonic()-began))))
            if not rclpy.ok():
                raise RuntimeError("ROS2 interrupted")
            clock_pub.publish(Clock(clock=ros_time(stamp)))
            row = streams[key][index]
            if key in ("rgb","depth"):
                array = np.load(Path(root)/row["path"],allow_pickle=False)
                if row.get("sha256") and sha256(Path(root)/row["path"]) != row["sha256"]:
                    raise ValueError("image modified after extraction")
                if key == "depth":
                    array = depth_meters(array,config).astype("<f4")
                msg = Image()
                msg.height,msg.width = array.shape[:2]
                msg.encoding = "rgb8" if key=="rgb" else "32FC1"
                msg.is_bigendian = 0
                msg.step = int(array.strides[0])
                msg.data = array.tobytes()
            else:
                msg = Imu()
                msg.orientation_covariance[0] = -1.0
                vector = msg.linear_acceleration if key=="accel" else msg.angular_velocity
                vector.x,vector.y,vector.z = row["value"]
                # An unavailable component is explicitly unknown, never a valid zero measurement.
                (msg.angular_velocity_covariance if key=="accel" else msg.linear_acceleration_covariance)[0] = -1.0
            msg.header.stamp,msg.header.frame_id = ros_time(stamp),row["frame_id"]
            publishers[key].publish(msg)
            if key == "rgb":
                c = calibration["cameras"][0]
                info = CameraInfo()
                info.header = msg.header
                info.width,info.height = c["width"],c["height"]
                info.k,info.d,info.r,info.p = c["K"],c["D"],c["R"],c["P"]
                info.distortion_model=c["distortion_model"]
                camera_pub.publish(info)
            late = max(0.,time.monotonic()-began-offset)
            lateness.append(late)
            counts[key] += 1
            log.write(json.dumps({"stream":key,"timestamp_ns":stamp,"scheduler_lateness_s":late})+"\n")
            rclpy.spin_once(node,timeout_sec=0)
        session.data["replay"]["status"] = "completed"
    finally:
        log.close()
        node.destroy_node()
        rclpy.shutdown()
        write_json(session.path/"replay_metrics.json",{"published_messages":counts,"wall_elapsed_s":time.monotonic()-began,
                  "scheduler_lateness_p50_s":float(np.percentile(lateness,50)) if lateness else None,
                  "scheduler_lateness_p95_s":float(np.percentile(lateness,95)) if lateness else None,
                  "note":"Publisher scheduling only; not SLAM latency, delivery acknowledgement, E4 performance or real-time proof"})
