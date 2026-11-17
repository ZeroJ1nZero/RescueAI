# 공간 수집 시스템 구현·검증 보고서 — 2026-11-17

기존 FastAPI 서버와 E0 bag 검증/실험 명령을 보존하고 `edge/fire_vision` 패키지에 새
`fire-vision spatial` 실행 경로를 추가했다. 적용되는 AGENTS.md는 없었고 작업 시작 시
Git 작업 트리는 깨끗했다. 커밋·push·서비스 설치·디스크 포맷은 수행하지 않았다.

## 실행 환경과 검증 결과

실행 환경은 macOS arm64, Python 3.14.4이다. Jetson, Orbbec 카메라, 외장 SSD 및 GPIO는
연결되지 않았다. 새 개발 의존성은 `/private/tmp/rescueai-spatial-venv`에 분리 설치했다.
실제 설치 버전은 [개발 lock](../requirements-spatial-dev-macos-py314.lock)에 기록했다.
이 파일은 Jetson용 잠금 파일이 아니다. 런타임 OS/패키지/CUDA/JetPack 조회 결과와 모델·설정·보정
해시는 각 종합 파일 `/meta/json`에 들어간다. 확인할 수 없는 항목은 unverified/null이다.

```text
python -m pytest -q --junitxml=docs/verification/spatial-pytest.xml
120 passed in 16.40s

python -m pip check
No broken requirements found.

python -m compileall -q fire_vision
exit 0

python -m pip wheel . --no-deps --wheel-dir /private/tmp/rescueai-spatial-wheels
Successfully built fire-vision-experiments
```

[JUnit 원본](verification/spatial-pytest.xml), [원본·재생 비교 기록](verification/spatial-roundtrip.json)을
보존했다. wheel 안에 `fire_vision/spatial/map.schema.json`이 포함되는 것도 검사했다.
처음 `--no-build-isolation`로 wheel을 만들 때 개발 venv에 setuptools가 없어 실패했으며,
프로젝트의 정상 격리 빌드 명령으로 재실행해 성공했다.

위험 테스트는 깊이 스케일·왜곡/D2C·알려진 역투영·축/행렬 방향·시계 차이와 reset·시간 허용치,
무효 깊이/자세·submap 분리·동적 객체/보수적 track, 실제 ONNX/OpenCV CPU fixture 실행,
Schema·SHA256·HDF5 dataset/record 참조·외부 링크/경로 이탈·한글 클래스 저장,
원본 기록→재생 왕복 보존을 다룬다. ONNX fixture는 학습된 객체 모델이 아니다.

또한 미마운트/잘못된 SSD 식별 설정과 여유 공간 부족, 주입한 쓰기/카메라 실패,
raw 큐 지속 초과, AI backpressure에서 원본 보존과 전체 시간 대응 기록,
반복 세션/버튼 debounce/FINALIZING 중복 입력을 검사했다. 실제 subprocess로 serve의
stdin EOF 유지와 SIGTERM 후 마무리를 검증했다. 준비 중 SIGTERM, 중단과 IMU callback
초과의 경합도 재현 테스트로 보호한다. 실제 SSD 탈착/전원 차단 실험을 한 것은 아니다.

## 실제 생성한 예제

CLI로 30프레임 합성 세션을 생성한 뒤 해당 HDF5를 CLI로 재생했다. 완성된 두 파일을 내용 변경 없이
`examples`로 복사하고 Reader로 해시·참조를 재검증했다.

| 산출물 | 원본 합성 | 재생 재분석 |
|---|---|---|
| 종합 파일 | [session.h5](../examples/spatial-synthetic/session.h5) | [session.h5](../examples/spatial-replay/session.h5) |
| 다음 시스템 계약 | [map.json](../examples/spatial-synthetic/map.json) | [map.json](../examples/spatial-replay/map.json) |
| revision | 1 | 2 |
| RGB / depth | 30 / 30 | 30 / 30 |
| accel / gyro | 200 / 200 | 200 / 200 |
| 시간 대응 / 자세 / 관측 | 30 / 30 / 30 | 30 / 30 / 30 |
| 객체 / 표면 점 | 1 / 1200 | 1 / 1200 |
| raw / AI 누락 | 0 / 0 | 0 / 0 |
| synthetic / 결과 상태 | true / partial | true / partial |

RGB·depth·IMU의 모든 raw dataset과 attrs, 원래 시간·frame ID·스케일 및 보정값이 정확히
일치했다. 재생 결과는 원본을 덮어쓰지 않았다. HDF5 파일 해시는 분석 revision/환경/측정값이
다르므로 서로 다르며, 각 JSON이 자기 파일의 크기와 SHA-256을 정확히 참조한다.
샘플의 `fixture_object`와 자세는 전부 합성이고 실제 물체 탐지/측량 결과가 아니다.
샘플 JSON의 처리율/지연은 Mac의 소형 합성 입력 측정값이며 Jetson 성능 근거로 사용하지 않는다.

```bash
cd edge/fire_vision
.venv/bin/fire-vision spatial inspect examples/spatial-synthetic/map.json
.venv/bin/fire-vision spatial replay examples/spatial-synthetic/session.h5 --config configs/spatial-synthetic.json
```

## 구현 상태 구분과 남은 작업

| 영역 | 구현 및 검증 범위 | 실제 장치에서 남은 확인 |
|---|---|---|
| 센서 기록 | 공식 SDK 어댑터·복사 버퍼·원시 RGB/Y16/독립 IMU, 합성/재생 writer 검증 | Gemini 2 모델/펌웨어/프로파일, USB, SDK ABI와 연속 기록 |
| 카메라 기준 객체 위치 | ONNX/TensorRT adapter, 보정/D2C/깊이 군집/품질/null 처리; 합성 기하·CPU fixture 검증 | 실제 모델 정확도/라이선스, TensorRT engine, 실측 보정과 위치 오차 |
| 지도 좌표 | 합성 자세 테스트, 선택 실제 Open3D RGB-D odometry 연결, 최종 자세로 표면/관측 재계산 | Open3D 실행/드리프트/추적 품질; 현재 Mac에는 Open3D 없음 |
| SLAM 기반 지도 | loop closure와 재방문 최적화 미구현 | 실측 RGB-D 검증 후 호환 SLAM 백엔드와 최적화 경로 연결 |
| 배포/조작 | 설정 핀, LED 인터페이스, CLI/신호 처리, systemd 예제 제공 | GPIO pinmux/배선/외부 저항, udev/서비스 권한, SSD UUID/부팅 의존성 |

Open3D는 loop closure 없는 odometry이며 항등행렬이나 IMU 이중 적분으로 대체하지 않는다.
장기 객체 재식별, submap 간 정합, GPS·건물 좌표, 자유공간/통행 안전 판단은 제공하지 않는다.
실제 모델 파일이 없는 기본 Jetson 설정은 탐지 disabled이고 pose도 명시적으로 disabled다.
이때 원본 기록은 가능하지만 지도 위치는 null, 결과는 partial이다.

설치·촬영·재생·Reader·서비스 적용 명령과 데이터 규격은 [실행 안내](spatial-system.md)에 있다.
보드에서는 먼저 환경/SDK/모델/SSD/GPIO를 확인하고 실제 수집 FPS·추론 FPS·누락·큐·메모리·
처리량·지연·유효 깊이·추적 성공률·종료 후 생성 시간을 측정해야 한다.
