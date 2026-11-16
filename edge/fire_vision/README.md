# Fire Vision — Jetson Orin · Orbbec Gemini 2 프로토타입

RescueAI의 `edge/fire_vision/`에 있는 독립 Python 프로젝트다. Jetson 보드 환경을 점검하고 RGB-D/IMU 공간 인지 실험을 준비한다. 백엔드의 `app/`·`requirements.txt`·가상환경과 분리해 설치한다. 아래 명령은 이 디렉터리에서 실행한다. **Gemini 2는 Orbbec 깊이 카메라**이며, Google Gemini API를 뜻하지 않는다.

## 보드에서 시작하기

SSD로 옮겨 실행하려면 [SSD 실행 안내](docs/ssd-transfer.md)와 [명령 모음 스크립트](scripts/jetson-setup.sh)를 사용한다. 기본 실행은 보드 조회이며 설치는 단계별 명령으로 선택한다.

1. [저장소 배포·clone 안내](docs/repository-setup.md): GitHub 게시와 보드에서 가져오는 방법, Git bundle 전달 방법.
2. [Jetson·Gemini 2 환경 설정](docs/jetson-gemini2-setup.md): 보드 조사 → ROS/Python → 카메라 드라이버 → 센서 기록 → 후속 실험 순서.
3. [보드 확인 기록표](docs/jetson-board-checklist.md): 실제 장비에서 확인한 값과 근거를 기록하는 양식.
4. [장치 프로파일](profiles/jetson-gemini2.json): 미검증 후보 설정. 기존 E0 실행 config와 별개이며 CLI 입력으로 사용하지 않는다.

이 문서는 실제 Jetson·카메라 접속 없이 공식 자료를 확인하여 작성했다. 하드웨어 동작·실시간 성능을 검증한 결과가 아니다. 현재 구현은 아래의 오프라인 E0 입력 검증이며, Gemini 2 실시간 획득 노드와 E1 이후 runner는 후속 작업이다.

## 기존 오프라인 실험 — 환경 조사와 E0

`Orin_RGBD_IMU_Experiment_Plan.md`를 기준으로 만든 **E0 입력 검증 구현**이다. 원본 계획서는 수정하지 않았다. 실제 센서 좌표를 생성하는 SLAM·객체 검출 시스템까지 완성한 상태가 아니다.

현재 장치는 macOS26.6.2 / Apple M1 / 16GB 개발용 Mac이다. ROS2·CUDA·Orin·실측 bag이 없어 실제 E0 실험과 E1 이후를 실행하지 않았다. 테스트의 합성 입력은 `tests/`에만 있으며 실험 산출물로 전달하지 않는다.

## 구현 범위

| 책임 | 상태 |
|---|---|
| dataset_adapter | ROS1/ROS2 bag 목록 조사, 지정 토픽·header 구간 추출, RGB 정규화, 깊이 m 변환, 보정 보존, 시간 검사 |
| replay | ROS2 센서·정적 TF·단일 `/clock` 발행 코드. 시간 스케줄 단위 테스트만 수행; 실제 ROS 송수신 미검증 |
| localization | E1/E2 실행 차단·필요 조건 기록. RTAB-Map runner는 미구현 |
| mapping | 후속 구현 경계만 정의. 지도·경로 exporter 미구현 |
| detection | E1 통과 전 미통합. 모델·weights 미선택 |
| object_projection | 역투영·강체 변환·pose 시각 허용치·관측 스키마 검증 함수만 구현. 박스 깊이 군집·검출 연결·재투영은 미구현 |
| annotation | E5 경계만 정의. Gemma 미통합 |
| export | 설정·환경·Git 상태·실패·단계 상태·파일 SHA256·보고서 저장 및 무결성 검사 |

`run E1`/`run E2`/`project-objects`는 현재 준비 상태를 기록하고 종료코드2를 반환한다. 실행 기능으로 오해하지 않도록 E1~E5 미구현 상태를 명시한다. E1 통과 전 객체 탐지·Gemma를 우회 실행하는 경로는 없다.

## 설치와 현재 환경 재현

Mac 개발 환경은 **Python 3.13**으로 새로 만든다. 원본 Mac venv는 복사하지 않는다. 잠금 파일은 macOS arm64의 개발 버전이며 Ubuntu 22.04의 ROS Humble Python 3.10에 그대로 사용하지 않는다.

```bash
cd ~/IdeaProjects/RescueAI/edge/fire_vision
python3.13 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev-macos.lock -e .
.venv/bin/python -m pip check
env PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q
```

백엔드 설치는 RescueAI 루트의 기존 `requirements.txt`를 사용한다. 백엔드 `.venv`와 이 프로젝트 `.venv`를 공유하지 않는다. Jetson은 [환경 설정 안내](docs/jetson-gemini2-setup.md)의 시스템 Python·`--system-site-packages`·NumPy `<2` 제약을 사용한다. 이전 Conda 기반 실행 기록은 [과거 완료 보고서](docs/completion-report.md), 이번 이전 검증은 [RescueAI 이전 보고서](docs/rescueai-migration.md)에 기록한다.

Orin에서는 먼저 시스템 Python으로 `environment`를 실행할 수 있도록 이 패키지 경로에서 실행하고 실제 환경을 조사한다. `environment` 자체는 표준 라이브러리만 사용한다. ROS 재생에는 **설치된 ROS와 같은 Python ABI**의 인터프리터, rclpy·sensor_msgs·geometry_msgs·rosgraph_msgs·tf2_ros가 필요하다. 현재 Python3.13 개발 환경이 rclpy와 호환된다고 가정하지 않는다. [공식 자료와 조건부 버전 후보](docs/official-sources.md)를 확인한다.

## 데이터 없는 현재 상태 점검

출력 경로는 매번 새로 지정한다. 기존 결과를 덮어쓰지 않는다.

```bash
.venv/bin/python -m fire_vision environment --out results/environment.json
.venv/bin/python -m fire_vision check-input --config configs/e0.json --out results/e0-no-data
.venv/bin/python -m fire_vision run E1 --config configs/e0.json --out results/e1-preflight --repeat 3
.venv/bin/python -m fire_vision export results/e0-no-data
```

두 번째·세 번째 명령의 **예상 종료코드는2**다. `session.json`, `failures.jsonl`, `report.md`에 미실행 이유를 기록한다. `calibration.json`, 지도·경로·객체 파일, `metrics.json`, `tegrastats.log`는 만들지 않는다. 존재하지 않는 결과를 빈 파일로 채우지 않는다. 환경 보고의 `unverified`는 명령 없음·권한 부족·장치 부재 등 실제 이유를 포함한다. Git 정보는 실행 위치의 RescueAI 저장소에서 기록한다. Git 저장소 밖에서 실행했거나 commit이 없을 때만 commit은 null이다.

## 실제 OpenLORIS office bag으로 E0 재현

1. [공식 배포 목록](https://github.com/lifelong-robotic-vision/OpenLORIS-Scene/blob/master/download.md)에서 office 기록을 별도 SSD에 확보한다. 전체 묶음 자동 다운로드·압축 해제는 하지 않았다. 현재 약15GiB 여유 공간으로 대형 묶음 저장·추출이 가능한지 별도로 확인한다. 원본은 읽기 전용으로 취급한다.
2. ROS1 bag인지 실제 토픽·메시지 형식·기록 시간 범위부터 조사한다. 아래 토픽은 config의 후보값이며 실제 inventory와 다르면 수정한다. ROS1 bag을 `ros2 bag play`로 바로 재생하지 않는다.

```bash
.venv/bin/python -m fire_vision inspect-bag /mnt/ssd/openloris/office1-1.bag --out results/office1-1-inventory.json
cp configs/e0.json configs/office1-1-e0.json
```

3. `configs/office1-1-e0.json`에 실제 `dataset.sequence`, 출처 증거와 센서 확인을 기록한다. `provenance_verified=true`는 **사람의 출처 확인 선언**이며 자동 인증 결과가 아니다. `provenance_evidence`에는 다운로드 원문·배포 릴리스·파일 해시 확인 기록을 넣는다. OpenLORIS D435i uint16임을 확인한 경우만 `depth_scale_m=0.001`로 설정한다. `32FC1` float 미터 값이면 `1.0`을 명시한다. 색상화된 8-bit 깊이는 거부한다. E0의 `segment`는 시작 offset과30~60초를 지정한다.

```bash
.venv/bin/python -m fire_vision extract-bag /mnt/ssd/openloris/office1-1.bag --config configs/office1-1-e0.json --out /mnt/ssd/normalized/office1-1-e0
```

4. `dataset.path`를 `/mnt/ssd/normalized/office1-1-e0`로 지정한다. 추출한 `calibration.json`의 **review 영역**에서 아래 항목을 근거와 함께 확인한다. 원본 bag이나 원본 보정 파일을 수정하지 않는다. 추출본은 작업 사본이다. 수치 오류를 발견했다면 임의 수정 대신 원본 버전·수정 근거를 별도 기록하고 다시 추출한다.

| review 필드 | 확인할 내용 |
|---|---|
| rgb_depth_registered / registration_evidence | 실제 정렬 깊이인지와 RGB 대응을 검토. 같은 해상도·이름만으로 true 설정 금지 |
| camera_imu_direction_verified / extrinsics_evidence | `T_camera_imu`: IMU 점을 카메라로 변환. TF의 `T_parent_child`는 child→parent |
| release_corrections_verified | 배포 릴리스와 과거 IMU 외부 보정 수정 이력 확인 |
| imu_accel_unit / imu_gyro_unit | `m/s^2`, `rad/s` 확인 |
| imu_axes / imu_includes_gravity / imu_semantics_evidence | 축 방향을 문자열로 기록, 중력 포함 여부를 boolean으로 기록, 근거 첨부 |
| imu_intrinsics_applied | E0 추출은 raw IMU이므로 false 유지. imu_info의 보정 행렬은 보존하며 실제 적용은 E2 준비에서 검증 |

추출본 review를 변경하면 E0를 다시 실행한다. RGB CameraInfo의 K/D/R/P와 원본 인코딩·timestamp·프레임, tf_static·imu_info는 추출본에 보존된다. 깊이는 추출 시 원시값을 유지하고, 검증·재생 내부에서 m로 변환한다.

```bash
.venv/bin/python -m fire_vision check-input --config configs/office1-1-e0.json --out results/office1-1-e0-run1
.venv/bin/python -m fire_vision export results/office1-1-e0-run1
```

정상 입력이면 `calibration.json`, `e0_validation.json`, RGB/depth 미리보기, IMU 그래프, 동기화 히스토그램, 근거 RGB PNG와 세션 기록이 저장된다. 실패한 입력도 가능한 진단 그래프와 실패 기록을 보존한다. E0 통과 조건은 확인된 출처·보정·IMU 의미, 올바른 인코딩과 단위, 구간 coverage, 순서·누락·동기화 검사 통과다. IMU norm이 약9.8이라는 사실만으로 축·중력을 승인하지 않는다. 파일에 필요한 길이가 없으면 실패한다. 여러 시퀀스를 이어 가짜60초를 만들지 않는다. office1-6 알려진 깊이 누락은 실패로 보존하거나 누락을 포함하지 않는 실제 구간을 별도로 선택한다.

ROS1/ROS2 **bag 입력만 지원**한다. OpenLORIS 텍스트·이미지 package 묶음의 네이티브 파서는 미구현이다. `.db3` 파일 하나가 아니라 `metadata.yaml`이 있는 ROS2 디렉터리를 전달한다. 미지원 압축 이미지·손상 메시지는 변환 성공으로 처리하지 않는다. 원본 bag의 압축은 rosbags 지원 범위에 따른다.

## ROS2 재생과 E1 이후

E0를 통과한 **동일 설정과 파일 내용**만 재생할 수 있다. 예시는 대상 ROS 환경에서 실행해야 하며 현재 Mac에서는 미검증이다.

```bash
source /opt/ros/humble/setup.bash
python3 -m fire_vision replay --config configs/office1-1-e0.json --validated-session results/office1-1-e0-run1 --out results/office1-1-replay1
```

0.25배는 wall-clock 발행 간격만 늦춘다. 센서 header timestamp와 accel/gyro 간격은 바꾸지 않는다. accel·gyro는 분리된 raw 토픽으로 발행하며 필터 자세라고 표현하지 않는다. 모든 소비 노드도 `use_sim_time=true`로 설정해야 한다. `replay_metrics.json`은 발행 스케줄 지연·발행 수만 측정한다. 수신 보장·SLAM 처리 지연·실시간 성능 지표가 아니다.

다음 E1 작업은 실제 Orin 조사 → 설치 버전 고정 → 별도60~120초 입력 준비 → 비영 왜곡에 대한 RGB/정렬 깊이 동일 rectification 검증 → RGB-D odometry/RTAB-Map 연결 → 실패·재초기화·프레임 수 기록 → 최종 최적화 pose/점군/점유 지도 exporter 구현이다. RGB·깊이만 사용하며 정답 pose·wheel odometry·LiDAR를 연결하지 않는다. E1/E2 각각3회 실행 orchestration도 그때 구현한다. 현재 `--repeat 3`은 요청 조건 기록만 하며 실행한 횟수가 아니다.

```bash
python3 -m fire_vision run E1 --config configs/office1-1-e0.json --out results/office1-1-e1-preflight --repeat 3
python3 -m fire_vision run E2 --config configs/office1-1-e0.json --out results/office1-1-e2-preflight --repeat 3
python3 -m fire_vision project-objects --config configs/office1-1-e0.json --out results/office1-1-e3-preflight
```

이 명령은 아직 지도·객체를 만들지 않는다. E2에서는 raw IMU intrinsic 적용·축 변환·시각 보간·필터 버전을 검증한 뒤 orientation 중력 제약을 비교한다. 자기계 없는 절대 yaw나 완전한 VIO를 주장하지 않는다. E3에서는 유효 깊이 군집·분산·null 좌표 사유·키프레임 연결·최종 pose 재투영·이동 레이어를 구현해야 한다. 현재 수학 함수 테스트가 E3 검증을 대신하지 않는다.

E4 자동 측정도 미구현이다. 실제 Orin에서만 다음처럼 원시 로그 수집을 추가할 수 있다. PC 로그와 분리하고 종료 시 자신이 시작한 PID만 종료한다. 로그가 생성되었다고 GPU 성능 실험이 통과한 것은 아니다.

```bash
tegrastats --interval 1000 --logfile /mnt/ssd/experiment/tegrastats.log &
stats_pid=$!
# 실제 실험을 수행한 뒤:
kill "$stats_pid"
```

E5 Gemma는 지도 저장과 SLAM 프로세스 종료 이후 별도 패스이며 현재는 실행하지 않는다.

## 결과 계약과 한계

최종 세션 파일 계약은 [artifacts.md](docs/artifacts.md)에 있다. `session.json`은 실행 설정·환경·패키지·모델(null 포함)·Git(null 사유 포함)·단계 상태·생성하지 않은 파일의 이유를 기록한다. `export` 명령은 기존 세션 산출물의 무결성 검증이며 미실행 지도 생성 기능이 아니다.

검증 코드가 출처 선언이나 시각적인 RGB 정렬을 자동 인증하지는 않는다. E0의 엄격한 누락 기준은 불완전한 입력을 통과시키지 않는 초기 정책이며 실제 파일 검토 후 정당한 정책 변경이 필요하면 설정/근거를 함께 기록한다. 정답 경로 평가·ATE/RPE·스케일 고정 정합·지도 정확도·Orin OOM·GPU·반복 편차·객체 대응은 전부 미실행/미구현이다. 참고 경로를 입력해 보조 재구성을 수행하는 경로도 아직 없다.
