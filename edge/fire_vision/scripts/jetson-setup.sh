#!/usr/bin/env bash
# Copy this file and fire-vision.bundle to an SSD; run with bash on the board.
set -Eeuo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
REPO_DIR=${FV_REPO_DIR:-"$HOME/RescueAI"}
PROJECT_DIR=${FV_PROJECT_DIR:-"$REPO_DIR/edge/fire_vision"}
ORBBEC_WS=${FV_ORBBEC_WS:-"$HOME/orbbec_ws"}
LOG_DIR=${FV_LOG_DIR:-"$HOME/fire_vision-setup-logs"}
REMOTE_URL=https://github.com/ZeroJ1nZero/RescueAI
ORBBEC_TAG=v2.10.7
DRY_RUN=0
if [[ ${1:-} == --dry-run ]]; then DRY_RUN=1; shift; fi
ACTION=${1:-check}
if (( $# )); then shift; fi

fail() { printf '오류: %s\n' "$*" >&2; exit 2; }
usage() {
  cat <<'HELP'
사용법: bash jetson-setup.sh [--dry-run] 단계 [인자]

  check                 보드·OS·전력·USB 상태를 기록 (기본, 설치 없음)
  packages              Ubuntu 22.04/Orin용 ROS·빌드 패키지 설치
  project [BUNDLE]      옆의 fire-vision.bundle 또는 GitHub에서 RescueAI clone
  python                프로젝트 venv 생성·의존성 설치·테스트
  driver                Orbbec v2.10.7 빌드·udev 설치
  camera                Gemini 2 RGB/depth/분리 IMU 실행 (Ctrl-C로 종료)
  topics                실제 센서 토픽·노드·서비스 목록 표시
  record OUTPUT [TOPIC ...]  지정 경로에 ROS bag 기록 (Ctrl-C로 종료)
  replay BAG            저장 bag을 0.25배속·/clock으로 재생
  --help                이 도움말

경로 설정: FV_REPO_DIR (기본 ~/RescueAI), FV_PROJECT_DIR (기본 저장소/edge/fire_vision)
          FV_ORBBEC_WS, FV_LOG_DIR (기본: 사용자 홈 아래)
--dry-run: 실행할 명령만 표시. 설치·clone·로그 생성 없음.
packages 전에는 ROS Humble 공식 문서에 따라 apt source를 준비해야 합니다.
패키지·SDK 설치에는 인터넷이 필요합니다. 보드 OS·펌웨어·전력 모드는 변경하지 않습니다.
전체 스크립트를 sudo로 실행하지 마세요. 필요한 단계만 내부에서 sudo를 사용합니다.
HELP
}

run() {
  printf '+ '; printf '%q ' "$@"; printf '\n'
  if (( ! DRY_RUN )); then "$@"; fi
}
need_file() { (( DRY_RUN )) || [[ -f $1 ]] || fail "파일이 없습니다: $1"; }
source_setup() {
  need_file "$1"
  if (( DRY_RUN )); then printf '+ source %q\n' "$1"; return; fi
  # ROS-generated setup scripts may reference unset variables.
  set +u
  source "$1"
  set -u
}
require_target() {
  (( DRY_RUN )) && return 0
  [[ $(uname -s) == Linux ]] || fail '설치·센서 단계는 Jetson Linux에서 실행하세요.'
  [[ $(uname -m) == aarch64 ]] || fail '대상 아키텍처는 aarch64입니다.'
  [[ -r /etc/os-release ]] || fail '/etc/os-release가 없습니다.'
  local ID VERSION_ID
  source /etc/os-release
  [[ $ID == ubuntu && $VERSION_ID == 22.04 ]] || fail '이 설치 경로는 Ubuntu 22.04 / ROS Humble 대상입니다.'
  [[ -r /proc/device-tree/model ]] || fail 'Jetson 모델 정보를 읽을 수 없습니다.'
  grep -qi orin /proc/device-tree/model || fail 'Orin 보드인지 먼저 확인하세요.'
  (( EUID != 0 )) || fail '일반 사용자로 실행하세요. sudo는 필요한 명령에만 사용합니다.'
}
start_log() {
  (( DRY_RUN )) && return 0
  mkdir -p -- "$LOG_DIR"
  LOG_FILE=$(mktemp "$LOG_DIR/${ACTION}-$(date -u +%Y%m%dT%H%M%SZ).XXXXXX")
  printf '로그: %s\n' "$LOG_FILE"
}
probe() {
  printf '\n$ '; printf '%q ' "$@"; printf '\n'
  if ! "$@"; then printf '[미확인] 위 명령이 없거나 실행에 실패했습니다.\n'; fi
}
ros_env() { source_setup /opt/ros/humble/setup.bash; }
camera_env() { ros_env; source_setup "$ORBBEC_WS/install/setup.bash"; }

case "$ACTION" in
  --help|-h|help) usage; exit 0 ;;
  check|packages|project|python|driver|camera|topics) (( $# == 0 )) || [[ $ACTION == project && $# == 1 ]] || fail '불필요한 인자가 있습니다.' ;;
  record) (( $# >= 1 )) || fail 'record에는 SSD의 출력 경로가 필요합니다.' ;;
  replay) (( $# == 1 )) || fail 'replay에는 bag 경로 하나가 필요합니다.' ;;
  *) usage >&2; fail "알 수 없는 단계: $ACTION" ;;
esac
if [[ $ACTION != check && $ACTION != project ]]; then require_target; fi
start_log
execute_action() {
trap 'printf "실패: 단계=%s 줄=%s 종료코드=%s\n" "$ACTION" "$LINENO" "$?" >&2' ERR

case "$ACTION" in
  check)
    if (( DRY_RUN )); then printf '보드·OS·전력·메모리·SSD·USB 상태를 조회합니다.\n'; exit 0; fi
    printf '=== 보드 초기 조사 (누락 명령은 미확인으로 기록) ===\n'
    probe date -u
    probe uname -a
    probe cat /proc/device-tree/model
    probe cat /etc/os-release
    probe cat /etc/nv_tegra_release
    probe dpkg-query -W nvidia-jetpack nvidia-l4t-core
    probe /usr/bin/python3 --version
    probe nvcc --version
    probe nvpmodel -q
    probe free -h
    probe swapon --show
    probe df -h
    probe lsblk -o NAME,SIZE,FSTYPE,MOUNTPOINTS
    probe lsusb -t
    probe timedatectl status
    printf '\n보드 실측·전원·냉각·USB 연결을 검토한 뒤 다음 단계를 선택하세요.\n'
    ;;
  packages)
    printf '사전 조건: ROS Humble apt source 설정 완료 (docs/jetson-gemini2-setup.md 4절).\n'
    run sudo apt update
    if (( ! DRY_RUN )); then
      apt-cache show ros-humble-ros-base >/dev/null 2>&1 || fail 'ROS apt source를 먼저 설정하세요: https://docs.ros.org/en/humble/Installation/Ubuntu-Install-Debs.html'
    fi
    run sudo apt install -y git build-essential cmake python3-dev python3-pip python3-venv \
      python3-colcon-common-extensions python3-rosdep usbutils \
      ros-humble-ros-base ros-humble-rosbag2-storage-default-plugins \
      ros-humble-cv-bridge ros-humble-tf2-ros
    ;;
  project)
    if [[ -e $REPO_DIR ]]; then
      if [[ -d $REPO_DIR ]] && [[ $(git -C "$REPO_DIR" rev-parse --show-toplevel 2>/dev/null) == "$(cd "$REPO_DIR" && pwd -P)" ]]; then
        printf '기존 저장소를 유지합니다. 자동 pull·덮어쓰기를 하지 않습니다.\n'
        run git -C "$REPO_DIR" status --short
        run git -C "$REPO_DIR" log -1 --oneline
        exit 0
      fi
      fail "기존 경로가 저장소가 아닙니다. FV_REPO_DIR로 새 경로를 지정하세요: $REPO_DIR"
    fi
    bundle=${1:-"$SCRIPT_DIR/fire-vision.bundle"}
    if (( $# )) && [[ ! -f $bundle ]]; then fail "bundle이 없습니다: $bundle"; fi
    run mkdir -p -- "$(dirname -- "$REPO_DIR")"
    if [[ -f $bundle ]]; then
      run git clone -b main -- "$bundle" "$REPO_DIR"
      run git -C "$REPO_DIR" remote set-url origin "$REMOTE_URL"
    else
      printf '옆에 bundle이 없어 GitHub를 사용합니다. 비공개 저장소라면 보드 인증이 필요합니다.\n'
      run env GIT_TERMINAL_PROMPT=0 git clone -b main -- "$REMOTE_URL" "$REPO_DIR"
    fi
    run git -C "$REPO_DIR" log -1 --oneline
    ;;
  python)
    need_file "$PROJECT_DIR/pyproject.toml"
    ros_env
    run /usr/bin/python3 -m venv --system-site-packages "$PROJECT_DIR/.venv-jetson"
    run "$PROJECT_DIR/.venv-jetson/bin/python" -m pip install -e "$PROJECT_DIR" 'numpy>=1.26,<2' pytest==8.3.3
    run "$PROJECT_DIR/.venv-jetson/bin/python" -m pip check
    run "$PROJECT_DIR/.venv-jetson/bin/python" -c 'import numpy, cv_bridge, rclpy; print(numpy.__version__, "ROS imports OK")'
    if (( ! DRY_RUN )); then cd -- "$PROJECT_DIR"; fi
    run env PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 "$PROJECT_DIR/.venv-jetson/bin/python" -m pytest -q
    ;;
  driver)
    if (( ! DRY_RUN )) && [[ -n ${VIRTUAL_ENV:-}${CONDA_PREFIX:-} ]]; then
      fail 'venv·Conda를 비활성화한 새 터미널에서 driver를 실행하세요.'
    fi
    ros_env
    driver_src="$ORBBEC_WS/src/OrbbecSDK_ROS2"
    run mkdir -p -- "$ORBBEC_WS/src"
    if [[ ! -e $driver_src ]]; then
      run git clone --recursive --branch "$ORBBEC_TAG" https://github.com/orbbec/OrbbecSDK_ROS2.git "$driver_src"
    elif (( ! DRY_RUN )); then
      [[ -z $(git -C "$driver_src" status --porcelain) ]] || fail 'Orbbec 소스에 변경이 있습니다. 먼저 보존·검토하세요.'
      [[ $(git -C "$driver_src" rev-parse HEAD) == "$(git -C "$driver_src" rev-parse "$ORBBEC_TAG^{commit}")" ]] || fail "기존 Orbbec 소스가 $ORBBEC_TAG 버전이 아닙니다."
    fi
    run git -C "$driver_src" submodule update --init --recursive
    if [[ ! -f /etc/ros/rosdep/sources.list.d/20-default.list ]]; then run sudo rosdep init; fi
    run rosdep update
    run rosdep install --from-paths "$ORBBEC_WS/src" --ignore-src --rosdistro humble -y
    if (( ! DRY_RUN )); then cd -- "$ORBBEC_WS"; fi
    run env MAKEFLAGS=-j2 CMAKE_BUILD_PARALLEL_LEVEL=2 colcon build --executor sequential \
      --event-handlers console_direct+ --cmake-args -DCMAKE_BUILD_TYPE=Release
    if (( ! DRY_RUN )); then cd -- "$driver_src/orbbec_camera/scripts"; fi
    run sudo bash "$driver_src/orbbec_camera/scripts/install_udev_rules.sh"
    run sudo udevadm control --reload-rules
    run sudo udevadm trigger
    printf '카메라를 다시 연결하고 USB 3 링크·실제 펌웨어를 확인하세요.\n'
    ;;
  camera)
    camera_env
    run ros2 launch orbbec_camera gemini2.launch.py --show-args
    run ros2 launch orbbec_camera gemini2.launch.py camera_name:=camera \
      enable_color:=true enable_depth:=true enable_ir:=false \
      depth_registration:=true enable_frame_sync:=true \
      enable_accel:=true enable_gyro:=true enable_sync_output_accel_gyro:=false \
      enable_point_cloud:=false enable_colored_point_cloud:=false
    ;;
  topics)
    camera_env
    run ros2 node list
    run ros2 topic list -t
    run ros2 service list -t
    printf '실제 토픽과 보정·깊이 단위를 확인한 뒤 record를 실행하세요.\n'
    ;;
  record)
    camera_env
    output=$1; shift
    [[ ! -e $output ]] || fail "출력 경로가 이미 있습니다: $output"
    topics=("$@")
    if (( ${#topics[@]} == 0 )); then
      topics=(/camera/color/image_raw /camera/depth/image_raw /camera/color/camera_info \
        /camera/depth/camera_info /camera/accel/sample /camera/gyro/sample \
        /camera/accel/imu_info /camera/gyro/imu_info /tf_static)
    fi
    if (( ! DRY_RUN )); then
      available=$(ros2 topic list)
      for topic in "${topics[@]}"; do
        grep -Fxq -- "$topic" <<< "$available" || fail "발행 토픽이 없습니다: $topic (실제 토픽을 record 인자로 지정하세요.)"
      done
    fi
    run mkdir -p -- "$(dirname -- "$output")"
    printf '약 45초 뒤 Ctrl-C로 기록을 정상 종료하세요. 기록 후 ros2 bag info로 검사하세요.\n'
    run ros2 bag record --storage sqlite3 -o "$output" "${topics[@]}"
    ;;
  replay)
    ros_env
    need_file "$1/metadata.yaml"
    printf '라이브 카메라를 먼저 종료하세요. 소비 노드는 use_sim_time=true로 설정하세요.\n'
    run ros2 bag play "$1" --clock --rate 0.25
    ;;
esac
}

if (( DRY_RUN )); then
  execute_action "$@"
else
  execute_action "$@" 2>&1 | tee -a "$LOG_FILE"
fi
