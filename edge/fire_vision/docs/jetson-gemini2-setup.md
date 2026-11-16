# Jetson Orin · Orbbec Gemini 2 실험 환경 설정

작성·공식 자료 확인일: 2026-11-16. 대상 후보: **Jetson Orin Nano 8GB + Orbbec Gemini 2**.

이 문서는 보드에서 앞으로 수행할 절차다. 현재 Jetson·카메라에 접속하지 않았으며, 아래 명령은 대상 장치에서 실행 검증하지 않았다. 실제 값은 [보드 확인 기록표](jetson-board-checklist.md)에 기록한다. 기존 [실험 계획](../Orin_RGBD_IMU_Experiment_Plan.md)의 E0 → E1 → E2 순서를 유지한다.

## 1. 준비물과 완료 기준

- 보드 모델에 맞는 전원, 정상 냉각 팬·방열판, 유선 네트워크 또는 안정적인 Wi-Fi.
- Gemini 2 본체와 USB 3 데이터 케이블. 초기 확인은 허브 없이 보드에 직접 연결.
- 데이터·bag·결과를 저장할 SSD. 실제 마운트 위치와 여유 공간을 먼저 확인.
- 초기 목표: 보드 버전 기록 → 카메라 RGB/깊이/IMU 수신 → 45초 bag 저장·재생 확인.
- 그다음 목표: E0 입력 검증 → E1 RGB-D 지도 생성 구현·실험 → E2 IMU 비교. 장치 설정만으로 SLAM 구현이 완료되지는 않는다.

## 2. 저장소 수신과 원격 접속

[배포 안내](repository-setup.md)에 따라 GitHub 또는 Git bundle에서 clone한다. 아래 명령은 별도 표시가 없으면 **Jetson의 bash**에서 실행한다.

```bash
cd ~/RescueAI/edge/fire_vision
git status --short
git rev-parse HEAD
```

SSH를 사용할 경우 보드에 화면·키보드를 연결한 상태에서 먼저 사용자 계정과 네트워크를 확인한다.

```bash
hostname -I
systemctl status ssh --no-pager
# SSH 서버가 설치되지 않았고 원격 접속이 필요한 경우:
sudo apt install openssh-server
sudo systemctl enable --now ssh
```

이후 개발 PC에서 `ssh BOARD_USER@BOARD_IP`로 접속한다. BOARD_USER·BOARD_IP는 실제 값으로 바꾼다. ROS 토픽을 PC로 전송하기보다 보드 로컬 bag 기록부터 확인한다.

## 3. 설치 전 보드 상태 확인

```bash
tr -d '\0' < /proc/device-tree/model
uname -m
cat /etc/os-release
cat /etc/nv_tegra_release
dpkg-query -W nvidia-jetpack nvidia-l4t-core
python3 --version
nvcc --version
sudo nvpmodel -q
free -h
swapon --show
df -h
lsblk -o NAME,SIZE,FSTYPE,MOUNTPOINTS
lsusb -t
timedatectl status
```

개별 명령이나 메타 패키지가 없으면 그 사실을 기록한다. 예를 들어 `nvidia-jetpack` 미설치만으로 JetPack 구성 전체가 없다고 판단하지 않는다. CUDA toolkit 명령 부재와 GPU 부재도 구분한다.

| 확인값 | 이번 문서의 기준과 다음 행동 |
|---|---|
| 모델·메모리 | 기존 계획은 Orin Nano 8GB. 다른 모델이면 전력·메모리 조건을 다시 정한다 |
| 아키텍처 | `aarch64` 확인. Mac의 arm64 venv를 복사하지 않는다 |
| Ubuntu | 22.04일 때 이 문서의 Humble 경로 사용. 20.04·24.04라면 별도 조합을 결정 |
| JetPack/L4T | 설치된 버전을 우선 유지. 재설치·업그레이드는 별도 작업 |
| 전력·냉각 | 현재 모드 ID와 이름을 기록. 다른 보드의 모드 번호를 복사하지 않는다 |
| SSD·swap | bag 저장 경로와 여유 공간 확인. 빌드 OOM이면 우선 병렬 수를 줄인다 |
| 시각 | 시스템 시각과 NTP 상태 기록. 센서 timestamp와 호스트 시각의 차이를 별도로 검사 |

참고로 JetPack 6.2는 L4T 36.4.3, 6.2.1은 L4T 36.4.4에 대응한다. 이것은 확인용 대응표이며 설치 요구가 아니다. [NVIDIA 6.2 릴리스](https://docs.nvidia.com/jetson/jetpack/6.2/release-notes/index.html), [6.2.1 릴리스](https://docs.nvidia.com/jetson/jetpack/6.2.1/release-notes/index.html).

전력 설정은 설치된 L4T에 맞는 [NVIDIA 전력·성능 문서](https://docs.nvidia.com/jetson/archives/r36.4.4/DeveloperGuide/SD/PlatformPowerAndPerformance/JetsonOrinNanoSeriesJetsonOrinNxSeriesAndJetsonAgxOrinSeries.html)를 확인한다. `MAXN`·`jetson_clocks`를 초기값으로 강제하지 않는다. 성능 비교 때 같은 전력 모드·냉각 조건을 사용한다.

## 4. ROS 2 Humble과 시스템 Python

Ubuntu 22.04/arm64에서 진행한다. ROS가 없다면 [ROS Humble 공식 설치 절차](https://docs.ros.org/en/humble/Installation/Ubuntu-Install-Debs.html)의 locale·Ubuntu universe·ROS apt source 설정을 먼저 완료한다. Jetson의 NVIDIA apt source를 제거하거나 다른 Ubuntu 버전의 저장소를 섞지 않는다.

ROS apt source가 준비된 뒤 필요한 패키지를 설치한다. `ros-base`는 보드용 최소 환경이며 RViz는 선택이다.

```bash
sudo apt update
sudo apt install git build-essential cmake python3-dev python3-pip python3-venv \
  python3-colcon-common-extensions python3-rosdep usbutils \
  ros-humble-ros-base ros-humble-rosbag2-storage-default-plugins \
  ros-humble-cv-bridge ros-humble-tf2-ros
source /opt/ros/humble/setup.bash
printf '%s\n' "$ROS_DISTRO"
/usr/bin/python3 -c 'import rclpy, sensor_msgs, geometry_msgs, rosgraph_msgs, tf2_ros; print("ROS Python imports OK")'
ros2 doctor --report
```

ROS Humble의 Ubuntu deb 패키지는 Jammy 22.04 대상이다. [공식 설치 원문](https://github.com/ros2/ros2_documentation/blob/humble/source/Installation/Ubuntu-Install-Debs.rst).

프로젝트 Python 환경은 보드의 `/usr/bin/python3`로 만든다. 시스템 ROS 패키지를 볼 수 있도록 `--system-site-packages`를 사용한다. 기존 macOS `requirements-dev-macos.lock`은 설치하지 않는다. 아래 NumPy `<2`는 ROS의 바이너리 확장과의 ABI 충돌을 줄이기 위한 초기 제약이며 실기 검증 후 실제 버전을 보존한다.

```bash
cd ~/RescueAI/edge/fire_vision
source /opt/ros/humble/setup.bash
/usr/bin/python3 -m venv --system-site-packages .venv-jetson
source .venv-jetson/bin/activate
python -m pip install -e . 'numpy>=1.26,<2' 'pytest==8.3.3'
python -m pip check
python -c 'import numpy, cv_bridge, rclpy; print(numpy.__version__, "ROS imports OK")'
env PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q
```

CUDA·TensorRT용 임의 pip 패키지 설치는 필요 없다. 현재 E0는 GPU를 사용하지 않는다. 새 터미널에서는 ROS setup을 먼저 source하고 프로젝트 venv를 활성화한다. 카메라 드라이버의 colcon 빌드는 아래처럼 **venv를 활성화하지 않은 별도 터미널**에서 수행한다.

## 5. Orbbec 드라이버 준비

Orbbec은 Gemini 2를 ROS 2 wrapper v2 지원 목록에 포함한다. 제품명이 Gemini 2 L·XL이면 다른 launch/지원 조건을 확인한다. [공식 지원 목록](https://orbbec.github.io/OrbbecSDK_ROS2_Docs/source/1_overview/supported_cameras.html).

검토 후보는 ROS wrapper **v2.10.7**이다. 해당 릴리스의 Gemini 2 권장 펌웨어는 **1.4.98**이다. 권장값은 호환성 검토 자료이며 자동 펌웨어 업데이트 지시가 아니다. 실제 펌웨어·SDK·wrapper commit을 기록하고 필요한 변경만 판단한다. [고정 릴리스](https://github.com/orbbec/OrbbecSDK_ROS2/releases/tag/v2.10.7).

```bash
# 새 bash 터미널: 프로젝트 venv를 활성화하지 않는다.
source /opt/ros/humble/setup.bash
mkdir -p ~/orbbec_ws/src
cd ~/orbbec_ws/src
git clone --recursive --branch v2.10.7 https://github.com/orbbec/OrbbecSDK_ROS2.git
cd OrbbecSDK_ROS2
git rev-parse HEAD
git submodule status --recursive

# rosdep 초기화는 최초 한 번만 실행한다. 이미 초기화되어 있으면 건너뛴다.
sudo rosdep init
rosdep update
cd ~/orbbec_ws
rosdep install --from-paths src --ignore-src --rosdistro humble -y
MAKEFLAGS=-j2 CMAKE_BUILD_PARALLEL_LEVEL=2 colcon build \
  --executor sequential --event-handlers console_direct+ \
  --cmake-args -DCMAKE_BUILD_TYPE=Release
source ~/orbbec_ws/install/setup.bash
ros2 pkg prefix orbbec_camera
```

빌드 의존성과 udev 설치 흐름은 [Orbbec 공식 빌드 문서](https://orbbec.github.io/OrbbecSDK_ROS2_Docs/source/2_installation/build_the_package.html)를 따른다. 컴파일러가 종료되면 OOM·로그·여유 메모리를 먼저 확인하고 필요하면 병렬 수를 1로 낮춘다. apt 드라이버와 소스 드라이버를 동시에 설치해 어떤 버전이 실행되는지 모호하게 만들지 않는다.

Linux USB 접근용 udev 규칙을 검토한 뒤 설치하고 카메라를 다시 연결한다.

```bash
cd ~/orbbec_ws/src/OrbbecSDK_ROS2/orbbec_camera/scripts
less install_udev_rules.sh
sudo bash install_udev_rules.sh
sudo udevadm control --reload-rules
sudo udevadm trigger
lsusb
lsusb -t
```

카메라가 연결된 분기의 USB 속도를 확인한다. `480M`이면 USB 2 연결이며 케이블·포트·허브부터 점검한다. 드라이버를 root로 상시 실행해 권한 오류를 가리지 않는다. USB 버퍼·부팅 설정 변경은 초기 필수 작업이 아니며 실제 오류 근거가 있을 때 검토한다.

## 6. 카메라 실행과 데이터 확인

먼저 **설치한 버전의 launch 인자**를 확인한다. 아래 후보 인자가 없다면 실행하지 말고 고정한 소스의 인자에 맞게 조정·기록한다. 가변 브랜치의 [Gemini 2 launch 소스](https://github.com/orbbec/OrbbecSDK_ROS2/blob/v2-main/orbbec_camera/launch/gemini2.launch.py)는 비교 참고용이다.

```bash
source /opt/ros/humble/setup.bash
source ~/orbbec_ws/install/setup.bash
ros2 launch orbbec_camera gemini2.launch.py --show-args
ros2 launch orbbec_camera gemini2.launch.py \
  camera_name:=camera enable_color:=true enable_depth:=true enable_ir:=false \
  depth_registration:=true enable_frame_sync:=true \
  enable_accel:=true enable_gyro:=true enable_sync_output_accel_gyro:=false \
  enable_point_cloud:=false enable_colored_point_cloud:=false
```

초기 실행은 지원 기본 스트림으로 시작해 실제 해상도·FPS를 기록한다. 이후 장치가 지원하는 프로파일 중 RGB/깊이 대응이 확인된 조합으로 고정한다. 기본 예제는 분리 accel/gyro 관찰을 위해 동기 IMU 출력을 끈다. 이것은 IMU 보정이나 orientation 계산을 수행하지 않는다.

다른 터미널에서 같은 ROS와 Orbbec setup을 source한다.

```bash
ros2 topic list -t
ros2 node list
ros2 service list -t
ros2 topic info /camera/color/image_raw --verbose
ros2 topic info /camera/depth/image_raw --verbose
ros2 topic hz /camera/color/image_raw
# Ctrl-C 후 다음 토픽 확인
ros2 topic hz /camera/depth/image_raw
ros2 topic echo /camera/color/camera_info --once
ros2 topic echo /camera/depth/camera_info --once
```

토픽 이름은 실행 결과를 기준으로 바꾼다. 공식 문서는 `/camera/color/image_raw`, `/camera/depth/image_raw`, `/camera/gyro_accel/sample` 등의 토픽을 설명하지만 활성 스트림과 옵션에 따라 달라진다. [Orbbec 토픽·서비스 문서](https://orbbec.github.io/OrbbecSDK_ROS2_Docs/source/2_installation/package_description.html).

반드시 확인할 항목:

- RGB/depth header stamp, frame_id, 실제 FPS, RGB와 깊이의 시각차·누락.
- 깊이 encoding·단위·무효값. `16UC1`이라는 이유만으로 0.001 m를 적용하지 않고 SDK·드라이버의 depth scaling 설정과 실물 거리로 확인.
- 정렬 옵션 활성화뿐 아니라 물체 경계가 RGB에 대응하는지, 적용되는 CameraInfo와 해상도가 맞는지 확인.
- accel/gyro의 실제 토픽·단위·축·중력 포함 여부·timestamp·외부 보정. IMU 메시지가 존재해도 orientation 유효성을 별도 확인.
- TF의 parent/child 방향, optical frame 축, camera↔IMU 변환. 센서 내부 변환과 보드/착용 위치 변환을 구분.

## 7. 짧은 bag 기록과 재생

처음에는 정지 장면을 기록한 뒤 천천히 이동하는 45초 구간을 추가한다. 아래는 실제 토픽 목록과 메시지 형식을 확인한 뒤 수정해 사용할 **후보 명령**이다. accel/gyro와 imu_info가 이 이름으로 발행되는지 먼저 확인한다. 센서 보정·단위 근거도 별도 보존한다.

```bash
# 실제 SSD 마운트 경로로 변경하고 매번 새 기록 이름을 사용한다.
record_root=/mnt/ssd/fire_vision
mkdir -p "$record_root"
ros2 bag record --storage sqlite3 -o "$record_root/gemini2-static-01" \
  /camera/color/image_raw /camera/depth/image_raw \
  /camera/color/camera_info /camera/depth/camera_info \
  /camera/accel/sample /camera/gyro/sample \
  /camera/accel/imu_info /camera/gyro/imu_info /tf /tf_static
# 약 45초 후 Ctrl-C로 정상 종료하고 metadata.yaml 생성을 확인한다.
ros2 bag info "$record_root/gemini2-static-01"
```

종료 후 bag의 기간·토픽별 메시지 수·실제 파일 크기를 확인한다. 정적 TF나 CameraInfo가 없으면 기록 QoS·transient-local·드라이버 발행 여부를 점검하고 재기록한다. bag을 반복 복사해 결측을 숨기지 않는다.

실시간 카메라 드라이버를 종료한 뒤 별도 터미널에서 재생한다.

```bash
ros2 bag play "$record_root/gemini2-static-01" --clock --rate 0.25
```

재생 소비 노드는 `use_sim_time=true`로 설정한다. 라이브 센서와 재생 토픽을 동시에 발행하지 않는다. header timestamp는 유지하며 느린 재생을 원속도 처리 성능으로 보고하지 않는다.

**기존 E0와의 연결은 추가 작업이다.** `configs/e0.json`은 OpenLORIS D435i용이며 Gemini 2에 그대로 쓰지 않는다. 현재 어댑터가 Orbbec의 사용자 정의 IMUInfo·보정 형식·depth scaling을 보존하는지 먼저 확인하고 필요한 변환을 구현해야 한다. 단순 토픽 이름 변경만으로 호환된다고 주장하지 않는다. 원본 ROS 2 bag의 목록 조사는 다음 명령으로 시작할 수 있다.

```bash
cd ~/RescueAI/edge/fire_vision
source .venv-jetson/bin/activate
python -m fire_vision inspect-bag /mnt/ssd/fire_vision/gemini2-static-01 \
  --out results/gemini2-static-01-inventory.json
```

## 8. 환경 기록과 부하 로그

각 실험은 새 출력 디렉터리를 사용한다. 아래 run_dir는 같은 터미널에서 이후 버전 기록에도 사용한다.

```bash
cd ~/RescueAI/edge/fire_vision
source /opt/ros/humble/setup.bash
source .venv-jetson/bin/activate
run_dir="results/board-$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$run_dir"
python -m fire_vision environment --out "$run_dir/environment.json"
git rev-parse HEAD > "$run_dir/source-commit.txt"
python -m pip freeze > "$run_dir/python-freeze.txt"
dpkg-query -W > "$run_dir/debian-packages.txt"
git -C ~/orbbec_ws/src/OrbbecSDK_ROS2 rev-parse HEAD > "$run_dir/orbbec-commit.txt"
```

마지막 Orbbec commit 기록 명령은 드라이버 clone 후 실행한다. 환경 명령의 `orin_remote`는 원격 연결을 자동 탐지한 결과가 아니며, 실제 장비 여부는 `board_model`·`device_kind`와 함께 판단한다.

실험 터미널과 별도 bash에서 아래 블록을 실행해 해당 프로세스가 시작한 tegrastats만 종료한다. run_dir는 위에서 만든 실제 디렉터리로 설정한다.

```bash
run_dir=results/BOARD_RUN_DIRECTORY
tegrastats --interval 1000 --logfile "$run_dir/tegrastats.log" &
stats_pid=$!
trap 'kill "$stats_pid" 2>/dev/null || true' EXIT INT TERM
read -r -p '실험 종료 후 Enter: ' _
kill "$stats_pid" 2>/dev/null || true
wait "$stats_pid" 2>/dev/null || true
trap - EXIT INT TERM
```

NVIDIA의 [tegrastats 문서](https://docs.nvidia.com/jetson/archives/r36.4.3/DeveloperGuide/AT/JetsonLinuxDevelopmentTools/TegrastatsUtility.html)를 기준으로 RAM·온도·GPU·클럭·전력 원시 로그를 수집한다. 로그 파일만으로 부하 실험 통과를 선언하지 않는다.

## 9. 이후 실험 순서

| 순서 | 실행·구현할 작업 | 넘어가기 전 확인 |
|---|---|---|
| 보드 준비 | 이 문서 2~5절, 체크리스트 작성 | 전원·냉각·SSD·버전·USB 확인 |
| 카메라 초기 확인 | 6~7절, 정지/이동 bag 기록 | RGB·깊이·IMU·보정·TF·시각 수신 |
| 공개 데이터 E0 | README의 OpenLORIS 입력 검증 | 실제 30~60초 구간, 출처·보정·동기화 통과 |
| Gemini 2 어댑터 | SDK 보정/IMUInfo 변환과 깊이 단위 보존 구현 | 실측 bag E0 검증; 현재 연결 미구현 |
| E1 | RTAB-Map RGB-D runner·exporter 구현, 60~120초 구간 3회 | 지도·추정 경로·추적 실패·재초기화 기록 |
| E2 | 같은 구간에 보정된 IMU orientation 중력 제약 비교 | 축·중력·시각 보간 검증; 완전한 VIO와 구분 |
| E3 | 검출·유효 깊이·지도 좌표 연결 | pose 없는 관측은 null, 최종 pose로 재투영 |
| E4 | 동일 전력·입력 조건에서 부하 비교 | OOM·온도·생략 프레임·실제 실행 속도 기록 |
| E5 | 지도 저장·SLAM 종료 후 Gemma 별도 패스 | 근거 ID 연결, 기존 좌표·수치 보존 |

현재 `run E1`, `run E2`, `project-objects`는 준비 조건을 기록하고 종료코드 2를 반환한다. 지도 생성 명령으로 사용할 수 없다. 공개 데이터 E0 성공은 Gemini 2 하드웨어나 착용 상태 성능 검증을 대신하지 않는다.
