"""E1/E2 preflight only. No SLAM run is claimed without a real backend."""
import importlib.util
import shutil


def blockers(stage, config, e0_validated=False):
    reasons = []
    if not e0_validated:
        reasons.append("E0 has not passed on this exact input/configuration")
    if not config["dataset"]["path"]:
        reasons.append("real dataset is missing")
    if not shutil.which("ros2") or importlib.util.find_spec("rclpy") is None:
        reasons.append("ROS2/rclpy is not available in this interpreter")
    reasons.append("RTAB-Map runner/export integration is deferred until measured E0 and target dependency audit; not implemented in this E0 delivery")
    if stage == "E2":
        reasons.append("E1 not validated; IMU filter orientation constraint comparison deferred; not full VIO")
    return reasons
