"""Read-only probes. A failed/missing probe is retained, never guessed."""
import importlib.metadata
import json
import os
import platform
import shutil
import subprocess
from pathlib import Path


def probe(argv):
    if not shutil.which(argv[0]):
        return {"status": "unverified", "reason": "command_not_found", "command": argv}
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=20)
        return {"status": "confirmed" if p.returncode == 0 else "unverified", "command": argv,
                "returncode": p.returncode, "stdout": p.stdout.strip(), "stderr": p.stderr.strip()}
    except (OSError, subprocess.TimeoutExpired) as e:
        return {"status": "unverified", "command": argv, "reason": str(e)}


def read_optional(path):
    try:
        return {"status": "confirmed", "value": Path(path).read_text().replace("\x00", "").strip()}
    except OSError as e:
        return {"status": "unverified", "reason": str(e)}


def inspect_environment():
    model = read_optional("/proc/device-tree/model")
    orin = "orin" in model.get("value", "").lower()
    disk = shutil.disk_usage(Path.cwd())
    packages = sorted(({"name": d.metadata["Name"], "version": d.version}
                       for d in importlib.metadata.distributions()), key=lambda x: x["name"].lower())
    return {
        "device_kind": "jetson_orin" if orin else ("development_pc" if platform.system() == "Darwin" else "unverified_non_orin"),
        "platform": platform.platform(), "architecture": platform.machine(), "python": platform.python_version(),
        "cpu": probe(["sysctl", "-n", "machdep.cpu.brand_string"]) if platform.system() == "Darwin" else probe(["lscpu"]),
        "mac_hardware_fallback": mac_hardware() if platform.system() == "Darwin" else {"status":"not_applicable"},
        "board_model": model, "ubuntu_os_release": read_optional("/etc/os-release"),
        "l4t": read_optional("/etc/nv_tegra_release"),
        "jetpack": probe(["dpkg-query", "-W", "nvidia-jetpack", "nvidia-l4t-core"]),
        "cuda": probe(["nvcc", "--version"]), "gpu": probe(["nvidia-smi"]),
        "ros2": probe(["ros2", "doctor", "--report"]), "ros_distro_env": os.getenv("ROS_DISTRO"),
        "power_mode": probe(["nvpmodel", "-q"]),
        "memory": probe(["sysctl", "-n", "hw.memsize"]) if platform.system() == "Darwin" else read_optional("/proc/meminfo"),
        "swap": probe(["sysctl", "vm.swapusage"]) if platform.system() == "Darwin" else read_optional("/proc/swaps"),
        "disk_bytes": {"total": disk.total, "used": disk.used, "free": disk.free},
        "tegrastats_available": bool(shutil.which("tegrastats")),
        "system_packages": probe(["dpkg-query", "-W"]), "python_packages": packages,
        "selected_python_versions": {k: package_version(k) for k in ("numpy","Pillow","matplotlib","pytest","rosbags")},
        "orin_remote": {"status": "unverified", "reason": "no_remote_device_connected"},
    }


def package_version(name):
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def mac_hardware():
    # Only retain hardware type and RAM; omit serial number/UUID identifiers.
    result=probe(["system_profiler","SPHardwareDataType","-json"])
    if result["status"] != "confirmed":
        return {"status":"unverified","reason":result.get("stderr",result.get("reason"))}
    try:
        hardware=json.loads(result["stdout"])["SPHardwareDataType"][0]
        keys={"chip_type","cpu_type","physical_memory","machine_model","machine_name","number_processors"}
        return {"status":"confirmed","values":{k:v for k,v in hardware.items() if k in keys}}
    except (ValueError,KeyError,IndexError) as e:
        return {"status":"unverified","reason":str(e)}
