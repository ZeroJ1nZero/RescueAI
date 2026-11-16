# SSD로 Jetson 설정 스크립트 전달

## 1. Mac에서 SSD로 복사

RescueAI 통합 commit을 완료한 뒤 다음 명령으로 새 전달 폴더를 만든다. 이전 독립 저장소에서 만든 bundle을 재사용하지 않는다. 가상환경·SSD 데이터는 bundle에 넣지 않는다.

```bash
cd ~/IdeaProjects/RescueAI/edge/fire_vision
mkdir -p delivery/jetson-ssd
cp scripts/jetson-setup.sh delivery/jetson-ssd/
cp docs/ssd-transfer.md delivery/jetson-ssd/README.md
git bundle create "$PWD/delivery/jetson-ssd/fire-vision.bundle" embedded
git rev-parse embedded > delivery/jetson-ssd/SOURCE_COMMIT.txt
(cd delivery/jetson-ssd && shasum -a 256 jetson-setup.sh fire-vision.bundle SOURCE_COMMIT.txt README.md > SHA256SUMS)
```

`git bundle`은 commit한 `embedded` 브랜치를 포함하므로 미커밋 변경은 먼저 검토·commit한다. 구성:

```text
jetson-ssd/
  jetson-setup.sh       실행할 명령 모음
  fire-vision.bundle   RescueAI main의 Git 기록·소스 (네트워크 없이 clone 가능)
  SOURCE_COMMIT.txt    bundle의 기준 commit과 포함 범위
  README.md            이 안내
  SHA256SUMS           전달 파일 무결성 확인
```

예를 들어 SSD가 `/Volumes/MY SSD`에 마운트되어 있다면 Mac에서 다음과 같이 복사한다. 실제 볼륨 이름으로 바꾸고 Finder에서 복사해도 된다.

```bash
cp -R delivery/jetson-ssd "/Volumes/MY SSD/"
```

이 패키지는 **소스 전달**을 오프라인으로 할 수 있다. apt·pip·Orbbec 다운로드까지 오프라인 설치하는 패키지는 아니며, 해당 단계에는 보드의 인터넷 연결이 필요하다. GitHub 인증정보·Mac venv·실측 데이터는 포함하지 않는다.

## 2. 보드에서 첫 실행

SSD를 보드에 연결하고 파일 관리자에서 `jetson-ssd` 폴더를 연 뒤 터미널을 연다. `cd`는 실제 SSD 마운트 경로로 바꾼다.

```bash
cd "/media/BOARD_USER/MY SSD/jetson-ssd"
sha256sum -c SHA256SUMS
bash jetson-setup.sh --help
bash jetson-setup.sh check
bash jetson-setup.sh project
```

`bash`로 읽어 실행하므로 실행 권한이나 SSD의 `noexec` 옵션 때문에 `./jetson-setup.sh`가 실패하더라도 사용할 수 있다. 전체 스크립트를 `sudo bash`로 실행하지 않는다.

`check`는 보드·OS·L4T·전력 모드·메모리·SSD·USB를 조회한다. 누락된 명령은 미확인으로 남기고 나머지 조회를 계속한다. 전력 모드 조회가 권한 문제로 실패하면 별도로 `sudo nvpmodel -q`를 실행해 확인한다. 로그는 기본적으로 `~/fire_vision-setup-logs/` 아래에 매번 새 파일로 저장된다.

`project`는 같은 폴더의 bundle에서 `~/RescueAI`로 clone하고 origin을 `https://github.com/ZeroJ1nZero/RescueAI`로 등록한다. Python 프로젝트는 그 아래 `edge/fire_vision/`이다. **bundle에 담긴 commit**을 가져오며 나중에 원격에 추가된 commit을 자동으로 받지 않는다. 이미 해당 경로에 저장소가 있으면 상태만 표시하고 로컬 변경을 유지한다. bundle이 없을 때만 GitHub clone을 시도한다.

## 3. 환경 설치

보드 모델과 OS를 확인하고 `~/RescueAI/edge/fire_vision/docs/jetson-gemini2-setup.md` 4절에 따라 **ROS Humble apt source**를 먼저 준비한다. 설치·센서 단계는 Orin / aarch64 / Ubuntu 22.04에서만 진행한다. 다른 보드·OS에서는 초기 조회와 프로젝트 전달까지만 사용한다.

```bash
# 설치될 명령을 먼저 보기만 하려면:
bash jetson-setup.sh --dry-run packages

# ROS apt source 준비 후 실제 실행:
bash jetson-setup.sh packages
bash jetson-setup.sh python
bash jetson-setup.sh driver
```

각 명령이 성공한 뒤 다음 명령을 실행한다. `python`은 프로젝트 venv 생성·의존성 설치·ROS import 검사·테스트를 수행한다. `driver`는 Orbbec v2.10.7 소스 빌드와 udev 설치를 수행한다. venv·Conda를 활성화하지 않은 터미널에서 실행한다. 카메라는 Gemini 2인지, 펌웨어와 USB 3 연결이 적합한지 별도로 확인한다.

OS 재설치·펌웨어 갱신·전력 모드 변경·기존 작업 덮어쓰기는 수행하지 않는다. 실제 보드 실행은 아직 검증하지 않았다.

## 4. 카메라와 짧은 기록

첫 터미널에서 실행한다. 종료는 Ctrl-C다.

```bash
bash jetson-setup.sh camera
```

두 번째 터미널도 SSD 폴더에서 열어 실제 토픽을 확인한 뒤 새 SSD 경로에 기록한다.

```bash
bash jetson-setup.sh topics
bash jetson-setup.sh record "/media/BOARD_USER/MY SSD/experiments/gemini2-static-01"
```

기본 RGB·depth·CameraInfo·분리 accel/gyro·imu_info·정적 TF 중 없는 토픽이 있으면 기록을 시작하지 않는다. `topics`의 결과에 따라 `record 출력경로 토픽1 토픽2 ...`로 실제 토픽을 지정할 수 있다. 필요한 보정·TF·IMU 정보가 빠지지 않았는지 확인한다.

약 45초 후 Ctrl-C로 정상 종료한다. 카메라와 별개로 기록 프로세스도 종료해야 한다. 재생 전에 라이브 카메라를 종료한다.

```bash
source /opt/ros/humble/setup.bash
ros2 bag info "/media/BOARD_USER/MY SSD/experiments/gemini2-static-01"
bash jetson-setup.sh replay "/media/BOARD_USER/MY SSD/experiments/gemini2-static-01"
```

이 단계는 획득·기록 확인이다. SLAM/E1 이후 실행 기능을 새로 구현한 것은 아니다.

## 경로를 바꾸는 경우

```bash
FV_LOG_DIR="/media/BOARD_USER/MY SSD/setup-logs" bash jetson-setup.sh check
export FV_REPO_DIR="$HOME/projects/RescueAI"
bash jetson-setup.sh project
FV_ORBBEC_WS="$HOME/workspaces/orbbec" bash jetson-setup.sh driver
```

기본값을 바꿨다면 이후 단계에도 같은 변수를 지정한다. SSD를 분리하기 전 기록과 설치를 종료하고 파일 관리자의 꺼내기 기능을 사용한다.
