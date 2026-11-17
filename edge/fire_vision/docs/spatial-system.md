# 공간 데이터 수집·생성 실행 안내

새 `fire_vision.spatial` 모듈은 기존 E0 입력 검증과 FastAPI 서버를 보존하며 독립 세션을
생성한다. 다음 시스템은 최종 `map.json`의 존재를 준비 신호로 사용한다. `session.h5`만
있거나 `.partial` 파일만 있는 디렉터리는 결과 전달 대상으로 사용하지 않는다.

## 현재 구현 범위

| 기능 | 실행 경로와 사용 가능 범위 |
|---|---|
| 센서 기록 | SDK RGB/Y16·독립 accel/gyro 수집 코드, 합성 입력, HDF5 스트리밍 재생. 실제 Gemini 2 획득은 보드 검증 필요 |
| 카메라 기준 객체 위치 | RGB 탐지 → 보정된 깊이 투영 → 유효 깊이 군집 → 관측 표면 대표점. 합성 fixture로 수학/저장 검증 |
| 지도 좌표 | 합성 입력의 테스트 자세 또는 선택 Open3D RGB-D odometry. 정상 SLAM·loop closure로 표현하지 않음 |
| SLAM 기반 전역 지도 | loop closure, 재방문 최적화, 건물/GPS 정합 백엔드 미구현. 미설치 pose는 null, 결과 partial |
| 객체 연결 | 인접 프레임의 class·bbox IoU·카메라 표면 거리·동일 submap 조건이 유일하게 대응할 때만 연결. 장기 재식별·서로 다른 지도 병합은 지원하지 않음 |

`DONE`은 결과 생성 종료이며 지도 품질과 별개다. `map.json.status`의 complete/partial/failed와
`features`를 함께 읽는다. complete도 건물 전체 coverage나 통행 안전을 의미하지 않는다.
합성 결과는 항상 `synthetic=true` 및 경고로 표시한다.

## 개발 설치와 합성 실행

다음 명령은 `edge/fire_vision` 디렉터리 기준이다. 백엔드 가상환경과 분리한다.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[spatial,test]'
.venv/bin/fire-vision spatial record --config configs/spatial-synthetic.json --duration 3
```

`configs/spatial-synthetic.json`은 소형 30 RGB-D 프레임·각 100Hz accel/gyro fixture다.
설정 내 상대 경로는 설정 파일 디렉터리를 기준으로 해석한다. 로컬 저장은 이처럼 명시적인 개발 입력에서만 허용한다. 실제 센서 설정은 SSD 확인을 우회하지
않는다. 매 실행마다 `results/spatial-synthetic/` 아래 새 세션 디렉터리를 생성한다.
테스트 프레임의 `fixture_object`는 학습된 실제 물체 종류가 아니다.

```bash
.venv/bin/fire-vision spatial inspect results/spatial-synthetic/SESSION_ID/map.json
.venv/bin/fire-vision spatial replay results/spatial-synthetic/SESSION_ID/session.h5 --config configs/spatial-synthetic.json
env PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q
```

`SESSION_ID`는 실제 출력 디렉터리 이름으로 바꾼다. 재생은 입력 HDF5의 센서 획득을 생략하고
raw 배열·시간·스케일·보정을 그대로 사용한다. 원본 세션을 수정하지 않고 새 세션/분석 revision으로
기록한다. 실센서 HDF5 재생에는 synthetic detector/pose 설정을 사용하지 않는다.

## Jetson 설치와 준비 확인

현재 개발 환경에는 Jetson·카메라가 연결되지 않았다. 실제 버전 조사 없이 CUDA/TensorRT,
JetPack 또는 펌웨어를 자동 설치·업데이트하지 않는다. 먼저 기존 환경 조사 명령과
[보드 안내](jetson-gemini2-setup.md), [SDK API 근거](sources-spatial.md)를 사용한다.

```bash
uname -a
cat /etc/os-release
cat /etc/nv_tegra_release
dpkg-query -W nvidia-jetpack nvidia-l4t-core libnvinfer8 libnvinfer10
lsusb
findmnt --output TARGET,SOURCE,FSTYPE,UUID
python3 -m fire_vision environment --out /tmp/rescueai-board-environment.json
python3 -m venv --system-site-packages .venv
.venv/bin/python -m pip install -e '.[spatial]' 'numpy<2'
.venv/bin/python -m pip check
```

패키지 이름이 없는 `dpkg-query` 항목의 실패도 실제 설치 상태의 근거다. 현재 공식 Python wrapper는
distribution `pyorbbecsdk2`, import `pyorbbecsdk`를 안내한다. 보드 Python ABI/aarch64용 wheel과
설치 JetPack의 라이브러리 호환성을 공식 배포에서 확인한 뒤 해당 버전을 설치한다.
원하는 버전의 wheel이 없으면 공식 빌드 절차를 따른다. Mac lockfile을 보드에 복사하지 않는다.

`configs/spatial-jetson.json`을 별도 설정 파일로 복사하고 다음을 실제 값으로 수정한다.

- `storage.mount_path`, `storage.path`, `storage.expected_uuid`: 기존 SSD의 실제 마운트·UUID.
- `source.expected_model`, `source.serial`, RGB/Y16 해상도·FPS: SDK가 조회한 정확한 장치·프로파일.
- `gpio`: 배선 검토 후 `backend=jetson`, 번호 체계와 버튼·LED 핀. 예제는 핀을 지정하지 않는다.
- `detector`와 `pose`: 모델/런타임 검증 후 활성화한다. 예제의 disabled 상태는 JSON에도 그대로 표시된다.

프로파일 예제 640×480@30은 요청값이다. SDK가 해당 RGB/Y16 프로파일을 제공하지 않으면 명시적으로
실패하며 다른 포맷으로 바꾸지 않는다. IMU는 지원되고 시작된 스트림만 원래 샘플 속도로 기록한다.
원시 IMU를 영상 FPS로 축소하거나 단순 이중 적분해 자세로 사용하지 않는다.

```bash
.venv/bin/fire-vision spatial record --config /etc/rescueai/spatial.json --duration 10
.venv/bin/fire-vision spatial serve --config /etc/rescueai/spatial.json
```

대화형 serve 입력은 `start`, `stop`, `press`, `status`, `quit`이다.
GPIO 버튼과 CLI는 동일한 SessionController를 사용한다. READY/DONE에서 press는 시작,
RECORDING에서 press는 종료, FINALIZING에서 입력은 무시한다. 설정된 debounce가 연속 입력을
제한한다. 준비·기록·마무리·오류 상태는 LED 인터페이스를 통해 표시되며 GPIO 없는 환경은 no-op이다.

## 모델과 위치 추정

학습은 포함하지 않는다. 소형 YOLOv8/11 계열의 raw 출력 ONNX 또는 대상 Jetson에서 빌드한
TensorRT engine을 사용한다. 모델과 가중치 라이선스를 별도로 확인한다. `classes`는 그 모델의
출력 순서와 정확히 같아야 한다. 다음 계약에 맞지 않는 end-to-end/NMS 내장 출력은 지원하지 않는다.

- 입력: RGB NCHW, 0~1 float, 설정한 `[width,height]`로 직접 resize.
- 출력: `[1,4+C,N]`, cx/cy/w/h(입력 픽셀), C개 class probability, objectness 채널 없음.
- ONNX: OpenCV DNN CPU 대체 경로. OpenCV 설치가 필요하다.
- TensorRT: named-I/O `set_tensor_address/execute_async_v3`와 cuda-python runtime. 단일 입력/출력,
  해석 가능한 고정 출력 크기, float32/float16 이미지 입력. 실제 TensorRT/GPU에서 engine 호환성 확인 필요.

`detector.model`, `input_size`, `interval`, `confidence`, `classes`, `require_model`을 설정한다.
모델 미제공 시 `model_missing`으로 비활성화하거나 `require_model=true`이면 준비 단계에서 실패한다.
실측하지 않은 탐지 클래스를 채우거나 가중치를 자동 다운로드하지 않는다.
`pip install -e '.[inference]'`는 CPU/OpenCV 대체 경로를 설치한다. TensorRT는 기존 JetPack 제공
런타임과 그 CUDA에 맞는 `cuda-python` 바인딩을 사용한다. 최신 CUDA/TensorRT pip wheel로
JetPack을 덮어쓰지 않는다. [JetPack 6.2.1 공식 조합](https://docs.nvidia.com/jetson/jetpack/release-notes/index.html)은
CUDA 12.6 / TensorRT 10.3이며 현재 보드 설치값이라는 뜻은 아니다.
실제 ONNX CPU adapter smoke test에는 개발용 `onnx`도 설치한다. 작은 상수 출력 fixture 모델을
실행하는 테스트이며 학습된 물체 탐지 성능 검증은 아니다.

Tracker는 최대 64개 최근 상태만 유지한다. 기본 원본 RGB 프레임 간격 2 이내에서 같은 class,
bbox IoU ≥ 0.8, 카메라 표면점 거리 ≤ 0.1m, 동일한 유효 submap 조건을 모두 통과한 후보가 하나일
때만 연결한다. 간격은 `detector.tracker_max_gap_frames`로 조절한다. 추론 interval이 이 간격보다 크면
관측을 새 ID로 분리한다. 깊이/자세가 없거나 후보가 모호하면 병합하지 않으며 reset·submap 변경 후
ID를 재사용하지 않는다. 이 임계값은 보수적인 대응 규칙이며 물체 동일성 확률이나 검증된 오차가 아니다.
각 관측에는 고유 ID가 있고 객체 목록은 연결된 시간별 관측을 참조한다. 사람 등 dynamic class는
연결되더라도 dynamic으로 유지하고 해당 검출 영역을 표면 점군의 고정 구조로 통합하지 않는다.

`pose.backend=open3d`는 설치된 MIT Open3D의 실제 RGB-D odometry를 호출한다. 설치 가능한 Python/
아키텍처 버전을 확인해야 하며 기본 의존성으로 강제하지 않는다. 첫 성공한 추정 자세를 submap 원점으로
삼고 추적 손실·시간 reset 후에는 새 submap을 시작한다. Open3D가 없으면 pose 기능은 disabled이고
카메라 기준 객체 위치까지만 유효하다. TensorRT와 Open3D 경로는 현재 보드에서 실행 검증하지 않았다.
선택 설치는 `pip install -e '.[odometry]'`이며 Open3D 0.19.0을 고정한다.
[공식 ARM 안내](https://www.open3d.org/docs/release/arm.html)와 보드 Python ABI wheel 제공 여부를
확인한 후 설치하며 CUDA 가속을 자동 가정하지 않는다.

[NVIDIA TensorRT 공식 추론 API](https://docs.nvidia.com/deeplearning/tensorrt/10.x.x/inference-library/python-api-docs.html),
[Open3D source→target 변환 규약](https://open3d.org/docs/latest/tutorial/pipelines/rgbd_odometry.html)을 확인해 연결했다.
최종 MapBuilder는 저장된 최종 pose를 다시 읽어 점군·객체 위치를 계산한다. 현재 백엔드는 재방문 경로
최적화를 제공하지 않는다. nvblox는 초기 의존성에 포함하지 않았다.

## 시간·좌표·깊이 계약

원래 센서 timestamp와 unit/clock, frame ID, host monotonic 수신 ns를 보존한다. 처리 시간은 int64
마이크로초다. 변환 epoch·방법·동기화 검증 여부는 `/meta/json` 및 JSON `time.clock_conversion`에 있다.
장치 epoch 역행·frame ID reset을 정상 연속 궤적으로 취급하지 않는다. RGB·depth 대응은
`/sync/pairs`, `delta_us=depth.time_us-color.time_us`이며 tolerance를 넘으면 공간 계산에서 제외한다.
시간 대응은 AI 생략 여부와 독립적으로 저장한다. 서로 다른 미변환 clock 조합도 공간 계산에서
제외한다. 세션 `duration_us`는 reset 가능한 장치 시간 끝값이 아닌 host monotonic 수신 범위에서
계산하며 `duration_basis`로 구분한다.

길이는 m, 각도는 rad. depth/color optical은 X 오른쪽·Y 아래·Z 전방, map_local은 X 전방·Y 왼쪽·Z 위다.
행렬은 row-major로 저장하고 열벡터 왼쪽 곱을 사용한다.

```text
p_map_homogeneous = T_map_from_depth @ p_depth_homogeneous
T_initial_map_from_depth = [[ 0, 0, 1, 0],
                            [-1, 0, 0, 0],
                            [ 0,-1, 0, 0],
                            [ 0, 0, 0, 1]]
```

submap마다 독립 원점이며 서로 정합되지 않은 점군을 하나의 전역 지도처럼 합치지 않는다.
`gravity_aligned=false`; GPS·건물 좌표는 생성하지 않는다. 원시 깊이에 프레임별 scale을 곱하고,
0·비정상·범위 밖 깊이를 제외한다. 왜곡 보정과 depth→color extrinsic 투영 후 z-buffer로 대응 표면을
선택하므로 RGB bbox를 정렬되지 않은 깊이에 그대로 적용하지 않는다. 실제 객체 중심·전체 크기·
검증되지 않은 오차 반경을 주장하지 않는다. 관측되지 않은 공간은 unknown이다.

## HDF5 데이터 규격 v1.0.0

N은 해당 스트림 프레임 수, M은 테이블 행 수다. raw 이미지 dtype은 입력 원본이며 실센서 RGB는
uint8, Y16 깊이는 uint16이다. 모든 배열은 첫 축 chunk로 부분 접근한다. RGB/depth 영상 chunk는
한 프레임이고 테이블 chunk 크기와 lzf/gzip/null 압축은 `hdf5` 설정으로 조절한다.
`hdf5.cache_bytes`로 HDF5 chunk cache 크기를 지정할 수 있다(기본 8MiB).

| 경로 | dtype / shape / 의미 |
|---|---|
| `/meta/json`, `/meta/config`, `/calibration/json` | UTF-8 scalar; 장치·SDK·펌웨어·clock·synthetic·버전·설정 및 작은 보정 행렬 |
| `/raw/color/data` | 원시 uint8 `[N,H,W,3]`; attrs `channel_order=RGB`, `color_space=sRGB` |
| `/raw/depth/data` | 원시 depth dtype `[N,H,W]`; 필터/정렬 깊이로 덮어쓰지 않음 |
| `/raw/{color,depth}/{frame_id,sensor_timestamp,host_monotonic_ns,time_us}` | 각각 int64 `[N]`; 앞 두 항목 원본, 뒤 두 항목 ns/us |
| `/raw/depth/depth_scale_m` | float64 `[N]`; m/raw-unit, 프레임별 SDK 값 |
| `/raw/imu/{accel,gyro}/data` | float64 `[N,3]`; 각각 m/s², rad/s; 독립 시간 배열은 영상과 같은 필드 |
| `/raw/synthetic_poses` | float64 `[N_depth,4,4]`; 테스트 입력 자세만 보존, 나머지는 NaN(유효한 실측 자세가 아님) |
| `/sync/pairs` | compound `[M]`: color_index/depth_index/delta_us int64, valid bool, reason S96 |
| `/derived/detections` | compound `[M]`: color_index int64, class S128, bbox float32[4], confidence float32, synthetic bool |
| `/derived/poses` | compound `[M]`: depth_index/time_us/submap_id int64, status S48, T_map_from_depth float64[4,4], synthetic bool |
| `/derived/observations` | compound `[M]`; 아래 필드 목록 참고 |
| `/derived/{detections_by_color,observations_by_color}` | int64 `[N_color,2]`: `[start,count]`, 미처리 `[-1,0]` |
| `/derived/surface_points/positions` | float32 `[M,3]`; depth_optical 관측 표면, m |
| `/map/points/positions` | float32 `[M,3]`; 유효 pose만 최종 변환한 per-submap map_local 표면, m |
| 두 점군 그룹의 `colors` | uint8 `[M,3]`; 대응 RGB, 미대응 색상은 0 |
| 두 점군 그룹의 `pose_index`, `depth_index` | int64 `[M]`; 실제 pose/raw depth 참조, pose의 submap_id로 지도 구분 |
| `/map/points/submap_id` | int64 `[M]`; 각 점의 독립 지도 ID, JSON datasets.point_submap_id로 참조 |
| `/quality/events` | UTF-8 `[M]`; 작은 진단 이벤트 JSON 레코드 |
| `/quality/metrics` | UTF-8 scalar; 측정 환경에서 얻은 카운터·시간·큐·처리율 |

raw 스트림 attrs에 `timestamp_unit`, `clock`, `processing_time_unit=us`를 기록한다. 비활성 IMU는
빈 배열이며 샘플을 만들어 채우지 않는다. 큰 영상·점군은 JSON 문자열로 저장하지 않는다.

관측 테이블: `id/object_id S96`, `color_index/depth_index/detection_index/pose_index/time_us int64`,
`class S128`, `bbox float32[4]`, `detection_confidence float64`, `point_camera_m/position_m float64[3]`,
`submap_id int64`, `position_status S64`, `failure_reason S128`, `motion_status S32`,
`valid_depth_ratio/depth_variance_m2 float64`, `synthetic bool`.
HDF5의 유효하지 않은 수치는 NaN 및 상태 필드로 구별하고, JSON에서는 반드시 null로 변환한다.
없는 submap 참조는 -1이다. bbox는 RGB `[x0,y0,x1,y1]`, 끝 좌표 제외다. depth variance 단위는 m²다.
모든 객체 위치 의미는 `observed_surface_representative`다.
S96/S128 등 문자열은 최대 길이가 UTF-8 바이트 수이며 한글도 저장한다. 클래스는 시작 전
128바이트 제한을 검사한다. 모델 해시와 설정/보정 해시·런타임 환경은 `/meta/json`에 보존한다.

## JSON과 다음 시스템 Reader

`map.json`에는 schema_version/session_id/result_revision/status, HDF5 상대 경로·크기·SHA-256,
시간·좌표 규약, 독립 submap, 데이터셋 참조, 객체별 원본 관측 인덱스, 기능별 상태, 경고·측정값이 있다.
Schema와 Reader 검증은 NaN/Infinity, 경로/해시 불일치와 존재하지 않는 dataset/record 참조를 거부한다.
점군 전체는 HDF5에서 읽는다. JSON만으로 synthetic 여부, pose 지원, 지도 좌표 유효성과 submap 범위를
판단할 수 있다. 자세가 없으면 `position_m=null`이고 관측의 `point_camera_m`은 별도로 읽을 수 있다.

```python
from fire_vision.spatial.reader import Reader

with Reader("results/spatial-synthetic/SESSION_ID/map.json") as reader:
    print(reader.manifest["status"], reader.manifest["features"])
    objects = reader.objects()
    for obj in objects:
        print(obj["id"], obj["class"], obj["position_m"], obj["position_status"])
    if objects:
        index = objects[0]["observations"][0]["index"]
        observation = reader.observation(index)
        rgb, raw_depth = reader.observation_frames(index)
        print(observation["point_camera_m"], rgb.shape, raw_depth.shape if raw_depth is not None else None)
        depth_index = observation["depth_index"]
        if depth_index >= 0:
            scale_m = float(reader.h5["/raw/depth/depth_scale_m"][depth_index])
            metric_depth = raw_depth.astype("float32") * scale_m
            # 원시 0은 invalid이며 0m 물체가 아니다.
    # 명시적 구간을 읽어 긴 세션 전체가 RAM으로 들어가지 않게 한다.
    poses = reader.trajectory(start=0, stop=500)
    for submap in reader.manifest["submaps"]:
        local_points = reader.points(start=0, stop=10000, submap_id=submap["id"])
```

기본 Reader는 SHA-256 및 전체 참조 무결성을 bounded block으로 확인한다. `points()`와
`trajectory()`는 요청된 구간 배열을 반환하므로 대형 세션에서는 `start/stop`을 지정한다.
다른 submap의 점을 정합 없이 같은 좌표계로 해석하지 않는다.
submap이 여러 개면 `points()`의 `submap_id` 생략은 오류다. 직접 dataset을 읽을 때에도
`/map/points/submap_id`를 함께 읽어 서로 다른 지도 좌표를 구분해야 한다.

## 저장·오류·서비스

수집·단일 HDF5 writer·AI worker는 bounded queue로 분리한다. raw 기록이 우선이고 AI 초과는
추론 프레임 생략과 카운터로 남긴다. raw queue의 지속 초과, SSD 누락·UUID 불일치·쓰기 실패·용량 부족,
카메라 timeout은 ERROR로 안전 종료한다. 내부 저장장치로 대체 기록하지 않는다. 센서 프레임은 SDK
소유 버퍼에서 복사한 뒤 worker로 전달한다. 원시 배열을 처리 중인 SDK 객체에 의존하지 않는다.
JSON 측정값의 `finalization_s`는 종료 요청부터 HDF5 확정/해시/검증 후 JSON 쓰기 직전까지다.
정확한 측정 경계는 `finalization_measurement_boundary`에 기록한다. HDF5에는 그 이전 queue drain
시점 지표가 들어가며 전체 완료 시간은 서비스 로그의 `finalization_total_s`에서도 확인한다.

종료 순서는 수집 중지 → 큐 drain/분석 → 지도 재계산/참조 검증 → HDF5 close/fsync →
`session.h5` rename → SHA-256 → JSON 검증/fsync → `map.json` 최종 rename이다.
중단/오류의 `.partial`은 정상 완료로 공개하지 않는다. flush/fsync가 SSD 컨트롤러·파일시스템의
전원 차단 복구를 보장한다는 의미는 아니다. 중단 파일은 보존하며 자동 삭제·포맷하지 않는다.

서비스 예제는 `deploy/rescueai-spatial.service`다. 아래 명령은 시스템에 적용할 **예시**이며 개발 중
실행하지 않았다. 저장소/가상환경을 `/opt/rescueai/edge/fire_vision`에 배치하고 실제 SSD가 지정 경로에
마운트된 상태에서 사용자·권한을 준비한다. OS 부팅 자동 마운트는 기존 파일시스템 UUID를 이용한
관리자 설정으로 수행하며 디스크 포맷은 필요하지 않다.

```bash
sudo useradd --system --user-group --home-dir /opt/rescueai --shell /usr/sbin/nologin rescueai
sudo groupadd -f gpio
sudo usermod -aG video,plugdev,gpio rescueai
sudo install -d -m 0750 -o rescueai -g rescueai /mnt/rescue-ssd/rescue-sessions
sudo install -d -m 0755 /etc/rescueai
sudo install -m 0640 -o root -g rescueai configs/spatial-jetson.json /etc/rescueai/spatial.json
# 위 파일에 실제 UUID, serial/profiles, GPIO 배선, 모델 설정을 반영한다.
sudo install -m 0644 deploy/rescueai-spatial.service /etc/systemd/system/rescueai-spatial.service
sudo systemctl daemon-reload
sudo systemctl enable --now rescueai-spatial.service
systemctl status rescueai-spatial.service
journalctl -u rescueai-spatial.service -b -f
```

이미 있는 계정은 재생성하지 않는다. 카메라 공식 udev 규칙과 Jetson.GPIO의 공식 권한 설정을 설치한
버전에 맞게 적용한다. 단순히 그룹 이름을 추가하는 것만으로 장치 접근 권한이 생기지는 않는다.
[NVIDIA GPIO 문서](https://github.com/NVIDIA/jetson-gpio)의 pinmux·udev·외부 pull 저항 배선을
확인한다. 설정의 `pull`은 활성 edge 선택에 사용하며 실제 보드에 적절한 외부 저항을 준비해야 한다.
서비스는 SSD mount 의존성·mountpoint 조건과 애플리케이션 UUID 검사를 함께 사용한다.
실제 USB/GPU/GPIO 장치를 사용하므로 PrivateDevices 격리는 켜지 않았다.
`TimeoutStopSec=300` 내 종료되지 않으면 systemd가 강제 종료할 수 있으며 해당 결과는 준비 신호가
없는 중단 세션으로 남는다. 운영 기록 길이에 맞춰 종료 시간을 검증한다.

## 보드에서만 확인할 항목

OS/JetPack/CUDA/TensorRT/SDK/펌웨어와 USB 링크, 선택 스트림·깊이 scale·보정/D2C,
IMU 샘플/단위/외부 보정, GPIO 배선·debounce·LED, 실제 SSD 분리/쓰기 실패·SIGTERM을 확인한다.
최소 2회 반복 시작·종료하고 FINALIZING 입력 중복이 새 세션을 만들지 않는지 확인한다.
실측 수집 FPS·추론 FPS·누락·큐 최고 사용량·SSD 처리량·메모리·추론 지연·깊이 유효 비율·추적 성공률·
촬영 종료 후 마무리 시간을 보고한다. Mac 합성 테스트의 수치를 Jetson 성능으로 사용하지 않는다.

다음 구현은 실측 RGB-D와 공식 pose backend 조합 검증, loop-closing SLAM/최적화 경로 연결,
장기 cross-view object association이다. 표면 점군만으로 통행 가능·안전 경로를 확정하지 않는다.
