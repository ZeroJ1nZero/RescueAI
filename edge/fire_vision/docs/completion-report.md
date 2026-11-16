# 공간 인지 실험 프로토타입 — 이번 작업 완료 보고

작성일: 2026-11-09. 기준 원본: ../Orin_RGBD_IMU_Experiment_Plan.md. 이번 전달물은 **환경 조사와 E0 소프트웨어 구현**이다. 실측 E0 실험, SLAM·지도 생성, Orin 실행 성공으로 보고하지 않는다.

## 1. 구현한 기능과 생성 파일

- `fire_vision/environment.py`: Orin/개발 PC 구분, OS·L4T·JetPack·CUDA·ROS·RAM·swap·저장 공간·전력 모드·패키지 읽기 전용 조회. 미확인은 이유를 보존한다. Mac 하드웨어 fallback에서는 식별용 일련번호·UUID를 저장하지 않는다.
- `dataset_adapter.py`: ROS1/ROS2 bag inventory 및 지정 센서 추출. 원본 파일 SHA256, header/bag record ns, RGB 원본 인코딩과 RGB 정규화, 깊이 원시값, CameraInfo·tf_static·IMU intrinsic 보존. 입력 폴더 내부 출력·기존 결과 덮어쓰기 방지. 부분 추출 실패 기록.
- `validation.py`: 출처·깊이 단위·무효값·프레임별 유효 비율, K/D/R/P, 카메라↔IMU 방향·TF 트리, header 순서·중복·명목 주기 누락·구간 coverage·RGB-depth 1:1 동기화, IMU 수치·의미 확인. 미리보기·근거 RGB·IMU 그래프·동기화 히스토그램 생성 코드.
- `replay.py`: 원본 센서 시각을 보존하는0.25배 스케줄, 단일 `/clock`, raw accel/gyro 분리 발행 코드. E0 세션과 동일 설정·보정·모든 이미지 해시를 검증한다. 스케줄만 합성 테스트했으며 ROS 송수신은 미검증이다.
- `object_projection.py`: m 단위 역투영, 방향이 명확한 강체 좌표 변환, 누락·오래된 pose에 null 반환, 원본 관측 필드·null 온도·실패 이유·수치 스키마 검사. 검출기 연결은 하지 않았다.
- `export.py` / `cli.py`: 세션 설정·환경·모델·Git 상태·단계·산출물 미생성 이유·실패·해시·보고서, 실제 입력 없는 단계의 명시적 종료코드2, 무결성 검사 명령.
- 설정·버전·문서: `configs/e0.json`, `requirements-dev-macos.lock`, 조건부 Orin profile, `README.md`, `docs/artifacts.md`, `docs/official-sources.md`, 구현 계획과 진행 기록, 테스트3개 파일·35개 사례, `docs/verification/pytest.xml`.

책임 모듈은 분리했지만 localization은 사전 점검만 구현했다. mapping/detection/annotation은 후속 책임 경계이며 구현 완료가 아니다. RTAB-Map runner·지도 exporter·객체 검출·Gemma는 현재 없다.

실제 생성 결과는 `results/2026-11-09/final/`에 있다:

```text
environment.json
e0-no-data/session.json
e0-no-data/failures.jsonl
e0-no-data/report.md
e1-preflight/session.json
e1-preflight/failures.jsonl
e1-preflight/report.md
```

데이터·측정이 없으므로 calibration/trajectory/object/map/metrics/tegrastats/evidence 결과는 이 두 세션에 생성하지 않았다. 합성 fixture의 그래프와 임시 bag은 pytest 임시 경로에만 생성되며 실험 결과로 제공하지 않는다.

## 2. 실제 실행 명령과 확인 결과

작업 경로: `/Users/rinaeshin/IdeaProjects/fire_vision`.

| 명령 | 관찰한 결과 |
|---|---|
| `uname -a`, `sw_vers`, `system_profiler SPHardwareDataType SPDisplaysDataType`, `df -h .`, command 조회, 패키지 조회 | 개발용 Mac / macOS26.6.2 / Apple M1 / 16GB. 초기 여유 공간 약15GiB. ROS2·CUDA·Jetson 명령 미발견 |
| `git status --short`, 파일·상위 AGENTS 조회 | Git 저장소 아님. 기준 계획서만 존재. 적용할 AGENTS 없음 |
| `uv venv --cache-dir /private/tmp/fire-vision-uv-cache --python /opt/anaconda3/bin/python --system-site-packages .venv` | Python3.13.5 개발 venv 생성. 기본 uv cache는 권한 밖이어서 실패 후 경로를 지정 |
| `uv pip install --python .venv/bin/python --cache-dir /private/tmp/fire-vision-uv-cache rosbags==0.10.11` | venv에 설치. 사용된 NumPy2.5.4 등 실제 버전을 lock 파일과 세션에 기록. 시스템 OS/JetPack/ROS 업그레이드 없음 |
| `env PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 MPLCONFIGDIR=/private/tmp/fire-vision-matplotlib .venv/bin/python -m pytest -q --junitxml=docs/verification/pytest.xml` | **35 passed**, 종료코드0. 단위·합성 통합 테스트이며 실측 실험 아님 |
| `.venv/bin/python -m compileall -q fire_vision` | 종료코드0 |
| `.venv/bin/python -m fire_vision environment --out results/2026-11-09/final/environment.json` | 종료코드0. 환경·패키지·미확인 사유 저장 |
| `.venv/bin/python -m fire_vision check-input --config configs/e0.json --out results/2026-11-09/final/e0-no-data` | 종료코드2. **E0 not_run / dataset_missing** |
| `.venv/bin/python -m fire_vision run E1 --config configs/e0.json --out results/2026-11-09/final/e1-preflight --repeat 3` | 종료코드2. **E1 not_run**. 3회 실행한 것이 아니라 반복 요청 조건만 기록 |
| `.venv/bin/python -m fire_vision export results/2026-11-09/final/e0-no-data` | 종료코드0. 기록된 실패 파일1개 해시 불일치0. 지도 검증이 아닌 세션 파일 무결성 검사 |
| `shasum -a 256 Orin_RGBD_IMU_Experiment_Plan.md` | 원본 유지: `920cfb543251a1fe8d0c941aa63fc9db4cb9ad74185d938058c9ffdfb9ef1433` |

최종 환경 기록에서 sysctl RAM/CPU 조회는 권한 부족으로 unverified이며, system_profiler fallback은 M1/16GB를 confirmed로 기록했다. JetPack/L4T/Ubuntu/CUDA/ROS2/Orin 전력 모드·원격 Orin 상태는 미확인이다. GPU는 초기 system_profiler에서 Apple M1 GPU를 확인했으나 CUDA/GPU 부하를 측정하지 않았다. Git commit은 null과 사유를 저장했다.

## 3. 실제 데이터로 검증한 범위

**없음.** OpenLORIS 실측 파일·센서·Orin을 확보하지 못했다. 실제 해상도·토픽·timestamp 범위·깊이 정렬·보정 수치·IMU 축과 중력 여부는 미확인이다. 문헌 확인을 실제 파일 확인으로 대체하지 않았다.

테스트는 바이너리 ROS1 합성 bag 직렬화/역직렬화, 원본 header와 record 시각 차이, endian/stride/BGR, metric 변환, 시간 역전·중복·누락·skew, TF 방향/모호성, 유효 깊이 부족, pose 없음·시각 허용치, 관측 스키마, 변경된 파일 탐지, 실패·미실행 기록을 확인했다. 미리보기 PNG도 합성 fixture로만 렌더링·시각 확인했다. 테스트 성공은 실제 데이터·ROS·Orin 성공을 의미하지 않는다.

## 4. 미실행 단계와 필요한 조건

| 단계 | 현재 상태 | 필요한 조건/후속 구현 |
|---|---|---|
| 실측 E0 | 미실행 | 공식 office 기록, 실제 inventory·출처 확인,30~60초 구간, 보정 review 근거, 실행 후 실패 검토 |
| ROS 재생 | 미실행 | 대상 ROS와 같은 Python ABI·rclpy/메시지/TF 패키지, 통과한 동일 E0. 소비 노드 전체 use_sim_time 및 실제 송수신 검증 |
| E1 | 미실행·runner/exporter 미구현 | 실제 장치·패키지 버전 고정,60~120초 데이터, RGB/정렬 깊이 rectification, RGB-D odometry/RTAB-Map 연결, 최종 경로·점군·점유 exporter와 실패 계측 |
| E2 | 미실행·미구현 | E1 통과, raw IMU intrinsic/축/시간 검증과 필터, orientation 중력 제약 비교, 같은 설정/전력3회씩 반복 |
| E3 | 미실행·미구현 | E1 통과, 지원 검출기/weights 고정, 유효 깊이 군집, 관측 근거·키프레임·최종 pose 재투영·이동 레이어 |
| E4 | 미실행·미구현 | 실제 Orin, 추론 빈도별 실험, tegrastats/프로세스 RAM/GPU/swap/OOM 계측·동기화·분석 |
| E5 | 미실행·미구현 | 지도 저장 및 SLAM 종료 후 Gemma3 4B 별도 실행, 근거 ID·원본 수치 불변 검사 |

조건부 Ubuntu22.04/Humble/RTAB-Map0.22.1 후보는 기존 Orin 버전과 맞는지 확인 전에는 활성화하지 않는다. 해당 release 이력은 공식 자료로 확인했지만 태그 직접 조회와 설치 검증은 제한으로 실패했다. 현재 OS를 다시 설치하거나 최신 버전으로 올리라는 절차는 없다. detector·IMU filter 버전은 아직 선택할 수 없어 null이다.

## 5. 실패 사례와 알려진 한계

- 실제 데이터와 ROS 부재는 정상적인 미실행 사유로 기록되었다. 모의 SLAM·임의 좌표·가짜 성능은 생성하지 않았다.
- 코드 리뷰에서 metric float 재축소, 검증 후 이미지 변경, 명목2주기 누락/나노초 반올림, 구간 offset 불일치, 모호한 TF, 입력 내부 출력, 일부 유효 프레임에 가려진 무효 깊이 구간, CameraInfo R/P 미검사 문제를 발견했다. 각 회귀 입력으로 실패를 확인하고 수정한 뒤35개 전체 테스트를 통과했다.
- 출처 확인·RGB 정렬·IMU 의미 review는 사람이 근거를 확인하는 선언이다. 문자열/true 설정 자체가 물리적 정확도 인증은 아니다.
- 초기 E0 정책은 누락/무효 구간을 엄격히 실패 처리한다. `depth.min_valid_ratio_per_frame=0.05`를 기록하며 per-frame timestamp/비율을 남긴다. 허용 정책을 바꾸면 설정과 사유를 남기고 재검증해야 한다.
- 파일 형식은 bag만 지원한다. 텍스트/이미지 package 파서·압축 이미지 decoder·변화하는 CameraInfo 지원은 없다. 비영 왜곡은 보존/경고하지만 rectification은 E1 후속이다.
- E0 추출은 raw IMU를 보존하며 intrinsic을 실제 적용하거나 accel/gyro를 병합하지 않는다. E2 준비에서 검증해야 한다.
- `replay_metrics`는 발행 스케줄 측정만 가능하다. 전송 수신·SLAM 처리 수·실시간 지연·ATE/RPE·지도 정확도·객체 위치 정확도·고유 물체 수·반복 편차·Orin 성능을 주장할 근거가 없다.
- 기본 pytest 실행에는 기존 Conda의 외부 asyncio 플러그인 경고가 있었다. 최종 검증은 플러그인 자동 로드를 끄고 프로젝트 전체 테스트를 실행했다.

## 6. 다음 실험 재현 절차

1. README의 현재 환경 재현 명령으로 테스트를 실행한다. Orin에서는 먼저 `python3 -m fire_vision environment --out <새 결과 경로>/environment.json`을 수행하고 그 장치에 맞는 의존성을 결정한다.
2. 별도 SSD에 공식 office bag을 확보한다. `inspect-bag`으로 실제 토픽·포맷·기록 시각을 조사한다. README의 `/mnt/ssd/...` 예시 경로는 확보한 파일 경로로 대체한다.
3. `configs/e0.json` 사본에 실제 sequence·topics·출처·확인된 depth_scale_m·30~60초 구간을 기록한다. `extract-bag`을 새 출력 폴더에 실행한다. header/record 시각을 혼동하지 않는다.
4. 추출본 calibration.review를 출처·시각 대조·보정 방향 근거로 확인하고 config.dataset.path를 추출본으로 지정한다. 확인할 수 없으면 null을 유지한다.
5. `check-input --config <실제 설정> --out <새 E0 세션>`을 실행한다. 종료코드0 및 `e0_validation.json.status=passed` 확인 전에는 E1로 넘어가지 않는다. 실패 수치·그래프·원본 보정과 timestamps를 검토한다.
6. 동일 설정·입력의 ROS replay를 대상 ROS 인터프리터로 실행하고 소비 노드 전체 시각을 확인한다. 설정·이미지·보정 변경 시 E0를 다시 수행한다.
7. E1 runner/exporter 구현과 실제 RGB-D 기준선 검증을 진행한다. 최소 길이가 없는 시퀀스를 임의로 연장하지 않는다. E1 통과 이후에만 E2→E3→E4→선택적 E5를 순서대로 진행한다.

정확한 명령 예시는 ../README.md에 있다. 이번 작업의 판정은 **코드 작성: E0 범위 완료 / 합성 테스트:35개 통과 / 실측 실행:없음 / Orin 실행:없음**이다.
