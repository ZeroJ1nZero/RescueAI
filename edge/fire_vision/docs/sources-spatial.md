# 공간 수집 입력 · SDK 근거

2026-11-17 개발 Mac에서 공식 Python wrapper 소스를 조회했다. 연결된 Jetson과
카메라가 없으므로 아래는 API 검토 결과이며 센서 획득·성능 검증 결과가 아니다.

조회한 `v2-main` commit: `68cdfa181e09f0ddd0f21b77dff29cb3e7a0f0d2`.
설치 SDK는 실제 런타임 `get_version()`과 distribution 버전을 metadata에 남긴다.
현재 공식 Python wrapper 안내는 distribution `pyorbbecsdk2`, import `pyorbbecsdk`를 사용한다.
기존 `pyorbbecsdk` distribution의 동일 API 지원을 가정하지 않는다. 자동 설치·펌웨어 갱신은 없다.

| 공식 소스 | 적용한 계약 |
|---|---|
| [지원 모델 표](https://orbbec.github.io/pyorbbecsdk/source/1_overview/Introduction.html) | Gemini 2의 SDK v2 지원을 확인. Gemini 2 XL과 혼동하지 않음 |
| [장치 조회 예제](https://github.com/orbbec/pyorbbecsdk/blob/68cdfa181e09f0ddd0f21b77dff29cb3e7a0f0d2/examples/beginner/01_hello_camera.py) | Context/query_devices/device info/profile API |
| [보정 예제](https://github.com/orbbec/pyorbbecsdk/blob/68cdfa181e09f0ddd0f21b77dff29cb3e7a0f0d2/examples/beginner/04_camera_calibration.py) | 시작 후 OBCameraParam; depth→color R/t, t는 mm이므로 m로 변환 |
| [독립 센서 binding](https://github.com/orbbec/pyorbbecsdk/blob/68cdfa181e09f0ddd0f21b77dff29cb3e7a0f0d2/src/pyorbbecsdk/sensor.cpp) | Sensor.start(profile,callback), 별도 accel·gyro 원래 속도로 수신 |
| [IMU 예제](https://github.com/orbbec/pyorbbecsdk/blob/68cdfa181e09f0ddd0f21b77dff29cb3e7a0f0d2/examples/beginner/07_imu.py) | get_index/get_timestamp_us/get_value, m/s² 및 rad/s |
| [Frame binding](https://github.com/orbbec/pyorbbecsdk/blob/68cdfa181e09f0ddd0f21b77dff29cb3e7a0f0d2/src/pyorbbecsdk/frame.cpp) | get_data()가 NumPy 소유 메모리로 memcpy. 추가 copy로 SDK 버전별 수명 의존성 제거 |
| [멀티스트림 예제](https://github.com/orbbec/pyorbbecsdk/blob/68cdfa181e09f0ddd0f21b77dff29cb3e7a0f0d2/examples/beginner/06_multi_streams.py) | depth_scale은 mm/raw unit이므로 0.001 곱해 m/raw unit 저장 |
| [타입 stub](https://github.com/orbbec/pyorbbecsdk/blob/68cdfa181e09f0ddd0f21b77dff29cb3e7a0f0d2/stubs/pyorbbecsdk.pyi) | RGB/Y16 명시 프로파일, ANY_SITUATION, property 읽기, distortion model 및 8개 계수 |

`source` 설정의 `kind`는 `synthetic`, `replay`, `orbbec`이다. 합성 기본은
64×48, 15FPS, 30 영상쌍, IMU 각 100Hz이며 모든 샘플과 자세는 synthetic이다.
2m 표면과 일부 invalid(0) 깊이를 생성한다. `realtime=true`이면 실제 시각 간격으로 방출한다.

실센서는 RGB/Y16 지정 프로파일이 없으면 실패한다. SDK 기본 포맷으로 조용히 바꾸지 않는다.
RGB·depth 원본에는 SDK D2C를 적용하지 않는다. 왜곡 모델, 모든 계수와 depth→color 변환을
후단으로 전달하며 지원하지 않는 왜곡 모델을 pinhole로 간주하지 않는다.

장치 timestamp(us)는 보존하며 처리 시간은 첫 준비 프레임의 공통 장치 epoch를 빼서 계산한다.
같은 기기 clock이라는 전제·호스트 anchor와 drift 미보정 상태를 metadata에 기록한다.
하드웨어 RGB-depth 동기화 또는 중력 정렬을 검증된 것으로 표시하지 않는다.
센서 reset은 원래 시간 역행을 그대로 후단에 전달한다. 재연결은 자동 시도하지 않고
timeout으로 세션을 안전 중단한다. IMU callback 큐 초과도 fatal이다.

재생은 raw 각 스트림의 독립 인덱스와 host 수신 순서로 한 샘플씩 읽는다.
원래 배열·dtype·스케일·센서 시간·호스트 시간·frame ID·time_us·보정을 유지한다.
전체 세션을 RAM으로 읽지 않는다. 저장된 derived pose를 참값으로 사용하지 않는다.
`/raw/synthetic_poses`는 원본 synthetic=true인 세션에서만 테스트 자세로 재생한다.

실기 확인 항목: SDK wheel의 Jetson Python/architecture 호환성, 정확한 모델 이름,
펌웨어, USB 모드, 선택 해상도/FPS와 RGB 출력, distortion model,
IMU 실제 지원·속도·camera 외부 보정, clock 일관성, 분리·큐 초과·SIGTERM의 종료 기록.
