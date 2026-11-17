"""Read-only runtime audit. Missing evidence remains unverified."""
import platform
from ..environment import package_version, probe, read_optional


def inspect_runtime():
    return {"platform":platform.platform(),"architecture":platform.machine(),"python":platform.python_version(),
            "board_model":read_optional("/proc/device-tree/model"),"os_release":read_optional("/etc/os-release"),
            "l4t":read_optional("/etc/nv_tegra_release"),
            "jetpack":probe(["dpkg-query","-W","nvidia-jetpack","nvidia-l4t-core","libnvinfer10"]),
            "cuda":probe(["nvcc","--version"]),
            "repository_commit":probe(["git","rev-parse","HEAD"]),
            "python_packages":{name:package_version(name) for name in
                ("numpy","h5py","jsonschema","opencv-python-headless","open3d","pyorbbecsdk2","tensorrt","cuda-python")}}
