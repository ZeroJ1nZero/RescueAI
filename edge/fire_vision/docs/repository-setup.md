# RescueAI 저장소와 Jetson에서 가져오기

Fire Vision은 `https://github.com/ZeroJ1nZero/RescueAI`의 `main` 아래 `edge/fire_vision/`에 있다. `app/`은 기존 서버이며, 이 프로젝트와 Python 환경을 공유하지 않는다. 이전 독립 저장소 주소·과거 실행 기록은 현재 배포 경로가 아니다.

## GitHub에서 가져오기

비공개 저장소라면 읽기 권한이 있는 GitHub 인증을 먼저 준비한다.

```bash
git clone https://github.com/ZeroJ1nZero/RescueAI ~/RescueAI
cd ~/RescueAI/edge/fire_vision
git status --short
git rev-parse HEAD
```

이미 clone한 경우 저장소 루트에서 `git status --short`로 로컬 변경을 보존한 뒤 `git pull --ff-only`를 사용한다. 원격과 갈라진 이력에 force push하지 않는다. clone 후 [환경 설정 안내](jetson-gemini2-setup.md) 3절부터 시작한다.

## SSD에서 가져오기

[SSD 실행 안내](ssd-transfer.md)에 따라 **RescueAI 통합 commit 이후 새로 만든 bundle**과 최신 `scripts/jetson-setup.sh`를 함께 전달한다. 기존 독립 Fire Vision bundle에는 `edge/fire_vision/` 구조가 없으므로 이번 스크립트와 섞지 않는다.

```bash
cd "/media/BOARD_USER/MY SSD/jetson-ssd"
sha256sum -c SHA256SUMS
bash jetson-setup.sh project
```

스크립트의 기본 저장소는 `~/RescueAI`, 기본 Python 프로젝트는 `~/RescueAI/edge/fire_vision`이다. `project`는 기존 저장소를 자동 갱신하거나 덮어쓰지 않는다. `python`은 프로젝트 아래 `.venv-jetson`을 만든다.

```bash
# 기본 경로를 바꾸면 이후 단계에도 같은 설정을 유지한다.
export FV_REPO_DIR="$HOME/projects/RescueAI"
# 필요할 때만 패키지 위치를 별도로 지정한다.
export FV_PROJECT_DIR="$FV_REPO_DIR/edge/fire_vision"
bash jetson-setup.sh project
bash jetson-setup.sh --dry-run python
```

소스·테스트·설정·문서를 버전 관리한다. venv·실측 데이터·bag·실험 결과·ROS 빌드 산출물·`.env`·전달 bundle은 제외한다. 과거 검증 자료는 Jetson 실기 검증을 대신하지 않는다.
