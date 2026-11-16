# 연암소방대 시스템 데이터 입출력(I/O) 및 API 상세 명세서

> **문서 버전**: v4.0 (경로 B 단일화 — SSD 세션 가져오기 + 서버 Gemma 3 4B 분석)  
> **최종 수정일**: 2026-11-16  
> **대상 독자**: 임베디드/데이터(신경준·rinaeshin), 인프라(공진영), 안드로이드/UI(정세빈·이세이·Dies0101)  
> **개정 배경**: 임베디드는 SSD에 원본(ROS2 bag)만 기록하고, AI 분석(Gemma 3 4B)은 서버에서만 수행하기로 확정(2026-11-16). 이에 따라 HTTP 수집 API(`/telemetry`, `/telemetry/raw`, `/telemetry/batch`)를 **삭제**하고, 현장 데이터는 **SSD 세션 가져오기 스크립트 하나로만** 들어오도록 단일화함.

---

## 1. 시스템 데이터 흐름 및 역할 분담 (Architecture Overview)

```text
[임베디드: Jetson Orin + Orbbec Gemini 2]
  ① jetson-setup.sh record   → SSD에 ROS2 bag 녹화 (RGB·깊이·IMU)
  ② fire_vision extract-bag  → 세션 폴더 (manifest.json + rgb/*.npy)
        │  외장 SSD를 서버 노트북에 유선 연결
        ▼
[서버: import_fire_vision_session.py]                       (서버 uvicorn과 별도 프로세스)
  ③ Save-First: 프레임 JPEG + 원본 메타 → raw_telemetry_logs (프레임마다 즉시 커밋)
  ④ Gemma 3 4B(Ollama) 물체 탐지 → 규칙 엔진 위험도 판정 → ai_assessments, detection_events
  ⑤ 결과마다 POST /missions/{id}/notify/assessments ──┐
        ▼                                              │
[서버: FastAPI(uvicorn)]  ◄────────────────────────────┘
  ⑥ WebSocket 방송 (AI_MARKER_ALERT, ASSESSMENTS_IMPORTED)
  ⑦ REST 조회 (/map-state, /ai-assessments, /replay)
        ▼
[안드로이드 관제 앱]  로그인 → 작전 선택 → 지도·탐지 목록·스냅샷 표시 (조회 전용)
```

| 담당 | 하는 일 | 주고받는 것 |
| :--- | :--- | :--- |
| 임베디드 | 녹화, `extract-bag`으로 세션 폴더 생성 | **세션 폴더** (3장 규격) |
| 서버 | Save-First 저장, Gemma 분석, 저장·방송·조회 | DB, REST, WebSocket |
| 안드로이드 | 로그인, 결과 조회·표시 | **REST·WebSocket** (5·6·9장). 데이터를 서버로 보내지 않음 |

### 담당 팀원별 참고 가이드
- **임베디드 / 데이터 (신경준 님, rinaeshin 님)**: [3. SSD 세션 인계 규격](#3-임베디드--서버-ssd-세션-인계-규격) 및 [8.3 세션 가져오기](#83-임베디드-ssd-세션-가져오기import_fire_vision_sessionpy)
- **인프라 / 클라우드 (공진영 님)**: [1. 시스템 데이터 흐름](#1-시스템-데이터-흐름-및-역할-분담-architecture-overview) 및 [8. 서버 실행·시험 가이드](#8-서버-실행-및-시험-가이드)
- **안드로이드 / UI (정세빈 님, 이세이 님, Dies0101 님)**: [5. REST API](#5-서버--모바일-지도-앱-rest-api-명세), [6. WebSocket](#6-서버--모바일-지도-앱-실시간-websocket-명세), **[9. 안드로이드 앱 연동 가이드](#9-안드로이드-앱-연동-가이드-android-브랜치-기준)**

---

## 2. 공통 인증 규격 (Authentication)

### 2.1 관제 앱 인증 (3단계)
1. **인가 단말 확인**: `X-Terminal-Id` 헤더가 등록·활성 단말인지 확인 (시드: `TAB-HQ-001`, `TAB-RESCUE-002`)
2. **로그인**: `POST /api/v1/auth/login` — `X-Terminal-Id` 헤더 + 사번(`FIRE-CMD-101`) + PIN(`123456`, bcrypt 검증) → JWT 발급
3. **역할 권한(RBAC)**: `ADMIN`(1급) / `COMMANDER`(2급, 작전 개시·종료) / `OPERATOR`(3급, 조회)

- **REST API 헤더**: `Authorization: Bearer <JWT_TOKEN>`
- **WebSocket 쿼리 스트링**: `ws://<server-ip>:8000/ws/missions/{mission_id}/dashboard?token=<JWT_TOKEN>`

### 2.2 가져오기 스크립트 → 서버 알림 인증
`POST /api/v1/missions/{id}/notify/assessments`는 장비 키 헤더를 사용합니다. 가져오기 스크립트가 자동으로 붙입니다.
```http
X-Device-Id: EDGE-CAM-01
X-Device-Key: rescue-edge-secret-key-01
```
(`X-Terminal-Id` 헤더도 허용. 키는 `--device-id`/`--device-key` 옵션 또는 환경변수 `RESCUE_DEVICE_ID`/`RESCUE_DEVICE_KEY`로 변경)

---

## 3. [임베디드 → 서버] SSD 세션 인계 규격

현장 데이터는 **HTTP API가 아니라 SSD 세션 폴더**로 서버에 들어옵니다. 서버는 임베디드 `edge/fire_vision`의 `extract-bag` 결과를 그대로 읽습니다.

### 3.1 임베디드가 넘겨줄 것

```text
<세션 폴더>/                         ← fire_vision extract-bag --out 으로 만든 폴더
  manifest.json                      필수
  calibration.json                   있으면 함께 (서버는 현재 참조만)
  rgb/000000_<timestamp_ns>.npy      필수 — uint8, HxWx3, rgb8
  depth/..., (accel·gyro는 manifest 안)  있으면 함께 (서버는 현재 미사용)
```

| 항목 | 서버가 요구하는 값 |
| :--- | :--- |
| `manifest.format` | `"fire-vision-normalized-v1"` |
| `manifest.extraction.complete` | `true` (추출이 끝난 세션만) |
| `manifest.streams.rgb[]` | `timestamp_ns`(0 이상 정수), `path`(세션 폴더 안 상대경로), `sha256`(있으면 검증) |
| RGB 프레임 | `.npy`, `uint8`, `(H, W, 3)`, RGB 순서. 녹화 토픽 인코딩이 `rgb8`/`bgr8`이어야 `extract-bag`이 변환 가능 (압축 이미지 미지원) |
| `manifest.streams.accel/gyro[]` | 있으면 각 프레임에 가장 가까운 원시값을 원본 기록에 함께 저장 |

### 3.2 임베디드 작업 순서
```bash
# Jetson: 녹화 (SSD 경로에 ROS2 bag 생성)
bash jetson-setup.sh record /media/<user>/<SSD>/rec_20261120_01
# 추출 (설정 파일의 topics를 Gemini 2 실제 토픽(/camera/...)으로 맞춘 뒤)
python -m fire_vision extract-bag /media/<user>/<SSD>/rec_20261120_01 --config configs/<세션>.json --out /media/<user>/<SSD>/session_20261120_01
```
그다음 SSD를 서버 노트북에 연결하고 8.3의 가져오기를 실행합니다.

### 3.3 서버가 원본 기록(`raw_telemetry_logs.raw_payload`)에 남기는 것
```json
{
  "source_format": "fire-vision-normalized-v1",
  "session_key": "c71f3026bc6990c2",
  "session_dir": "E:\\session_20261120_01",
  "frame_index": 15, "frame_id": 15,
  "timestamp": 1763280001000, "timestamp_ns": 1763280001000000000,
  "rgb_path": "rgb/000015_1763280001000000000.npy", "rgb_sha256": "…",
  "width": 1280, "height": 800, "camera_frame_id": "camera_color_optical_frame",
  "imu_raw": { "accel": {"value": [0.1, -9.8, 0.2], "timestamp_ns": 1763280001000000000, "dt_ms": 0.0}, "gyro": { … } }
}
```
- `session_key`는 `manifest.json`의 해시입니다. 같은 세션을 다시 넣어도 이미 저장된 프레임은 건너뜁니다.

> **화면상 위치(Screen Coords) ≠ 실제 공간 좌표(World Coords)**: 임베디드 E1(SLAM)이 구현되어 위치가 생기기 전까지 탐지 좌표는 프레임 픽셀값입니다. 이동 궤적(`sensor_logs`)도 만들지 않습니다.

---

## 4. AI 분석 (서버 Gemma 3 4B)

분석은 **역할을 둘로 나눕니다.** Gemma는 "무엇이 보이는가"만 답하고, 위험도는 규칙 엔진이 일관되게 정합니다.

| 단계 | 담당 | 입력 → 출력 |
| :--- | :--- | :--- |
| 물체 탐지 | Gemma 3 4B (Ollama `/api/generate`, 긴 변 896px로 축소 전송) | 프레임 이미지 → `detected_objects`, `scene_summary` |
| 위험도 판정 | 규칙 엔진 `app/services/ai_assessor.py` | `detected_objects` → `hazard_level`, `poi_type`, `human_detected`, `action_recommendation` |

### 4.1 Gemma 출력 규격 (서버가 검증)
```json
{
  "detected_objects": [
    { "class": "person", "screen_box": [143, 286, 429, 714], "description": "바닥에 쓰러진 사람 형태" }
  ],
  "scene_summary": "복도 바닥에 사람이 쓰러져 있습니다."
}
```
- `class` 허용값: `person, fire, smoke, obstacle, door, stairs, fire_extinguisher, other` — 그 외는 버림
- `screen_box`: 숫자 4개가 아니면 버림, 이미지 밖은 경계로 자름, 원본 해상도로 환산해 저장
- 응답이 JSON이 아니면 그 프레임은 실패로 남기고(원본 보존) 다음 프레임 진행

### 4.2 위험도 규칙
| 탐지 | `hazard_level` | `poi_type` |
| :--- | :--- | :--- |
| `person` 포함 | `CRITICAL` (인명 발견) | `PERSON_RESCUE` |
| `fire` / `smoke` 포함 | `CRITICAL` | `FIRE_HOTSPOT` |
| 그 외 물체 | `WARNING` | `OBSTACLE_HAZARD` |
| 물체 없음 | `NORMAL` | `SAFE_PATH` |

> ⚠️ **정확도 미검증**: 단순 도형 시험 이미지에서 Gemma 3 4B가 사각형을 불·연기로 판단하는 오탐이 있었습니다. 실제 현장 영상으로 평가하기 전까지 결과를 확정 정보로 표시하지 마세요.

---

## 5. [서버 $\rightarrow$ 모바일 지도 앱] REST API 명세

모바일 지도 앱은 무거운 이미지 다운로드 없이 경량 텍스트/좌표 데이터만 빠르게 수신하여 즉각 화면에 표출합니다.

### 5.1 건물 정보 및 2D 평면도 도면 정보 조회
- **Method**: `GET`
- **URL**: `/api/v1/buildings/{building_id}`
- **응답 (200 OK)**:
```json
{
  "building_id": 1,
  "name": "소방방재 테스트빌딩 A동",
  "address": "서울특별시 종로구 세종대로 175",
  "floors_count": 2,
  "latitude": 37.5724,
  "longitude": 126.9769,
  "spatial_maps": [
    {
      "map_id": 1,
      "building_id": 1,
      "floor": 1,
      "floor_plan_image": "maps/floorplans/building_a_floor_1_2d.png",
      "width_meter": 30.0,
      "height_meter": 20.0
    }
  ]
}
```

---

### 5.2 지도 화면 초기화용 전체 레이어 조회 (초기 로딩)
- **Method**: `GET`
- **URL**: `/api/v1/missions/{mission_id}/map-state`
- **응답 (200 OK)**:
```json
{
  "mission_id": 1,
  "title": "테스트 작전 1호",
  "status": "ACTIVE",
  "building_id": 1,
  "device_id": "EDGE-CAM-01",
  "current_location": {
    "x": 10.0,
    "y": 5.0,
    "z": 0.0
  },
  "current_yaw": 45.0,
  "trajectory": [
    { "x": 2.0, "y": 1.0, "z": 0.0 },
    { "x": 5.0, "y": 2.5, "z": 0.0 },
    { "x": 10.0, "y": 5.0, "z": 0.0 }
  ],
  "active_markers": [
    {
      "type": "AI_MARKER_ALERT",
      "mission_id": 1,
      "assessment_id": 1,
      "timestamp": 1728028800000,
      "hazard_level": "CRITICAL",
      "poi_type": "FIRE_HOTSPOT",
      "title": "[CRITICAL] 🔥 화재 위험",
      "summary": "전방 고온 발화 위험 감지 (최고온도 78.5℃). 플래시오버 우려.",
      "action_recommendation": "대원 즉시 살수 방수 실시 및 후퇴 권고",
      "coord": {
        "x": 10.0,
        "y": 5.0,
        "z": 0.0
      },
      "snapshot_url": null
    }
  ]
}
```

---

### 5.3 AI 상황 판단 이력 타임라인 조회
- **Method**: `GET`
- **URL**: `/api/v1/missions/{mission_id}/ai-assessments?limit=50`
- **응답 (200 OK)**:
```json
[
  {
    "assessment_id": 1,
    "mission_id": 1,
    "device_id": "EDGE-CAM-01",
    "timestamp": 1728028800000,
    "hazard_level": "CRITICAL",
    "situation_summary": "전방 고온 발화 위험 감지 (최고온도 78.5℃)",
    "human_detected": false,
    "human_status": null,
    "action_recommendation": "대원 즉시 살수 방수 실시 및 후퇴 권고",
    "poi_type": "FIRE_HOTSPOT",
    "coord_x": 10.0,
    "coord_y": 5.0,
    "coord_z": 0.0,
    "snapshot_url": null,
    "created_at": "2026-10-04T16:34:24"
  }
]
```

---

## 6. [서버 $\rightarrow$ 모바일 지도 앱] 실시간 WebSocket 명세

초경량 센서 데이터만을 송수신하므로, 무선망 환경에서도 지연 시간(Latency) 100ms 미만으로 극초저지연 렌더링이 보장됩니다.

- **연결 URL**: `ws://<server-ip>:8000/ws/missions/{mission_id}/dashboard?token=<JWT_TOKEN>`

### 6.1 대원 실시간 위치 이동 이벤트 (`LOCATION_UPDATE`)

> **현재 발생하지 않음**: 위치(pose) 데이터가 없어 서버가 이 이벤트를 보내지 않습니다. 임베디드 E1(SLAM) 이후 사용 예정이며, 앱은 수신 처리만 준비해 두세요.

- **전송 주기**: 1초 주기 (1Hz)
- **용도**: 대원 핀 이동 및 헤딩각 화살표 회전
```json
{
  "type": "LOCATION_UPDATE",
  "mission_id": 1,
  "device_id": "EDGE-CAM-01",
  "timestamp": 1728028801000,
  "x": 10.8,
  "y": 5.3,
  "z": 0.0,
  "yaw": 52.0,
  "max_temperature": 78.5
}
```

### 6.2 AI 긴급 경보 & POI 마커 이벤트 (`AI_MARKER_ALERT`)
- **전송 조건**: `CRITICAL` / `WARNING` 이상치 또는 인명 발견 시
- **용도**: 지도 위 POI 마커(불꽃, 사람) 생성 및 하단 전술 브리핑 카드 표출
```json
{
  "type": "AI_MARKER_ALERT",
  "mission_id": 1,
  "assessment_id": 105,
  "timestamp": 1728028801000,
  "hazard_level": "CRITICAL",
  "poi_type": "FIRE_HOTSPOT",
  "title": "[CRITICAL] 🔥 화재 위험",
  "summary": "전방 고온 발화 위험 감지 (최고온도 78.5℃)",
  "action_recommendation": "대원 즉시 살수 방수 실시 및 안전거리 5m 이상 확보 후 후퇴 권고.",
  "coord": {
    "x": 10.8,
    "y": 5.3,
    "z": 0.0
  },
  "snapshot_url": null
}
```

---

## 7. 지도 앱 개발자를 위한 UI/UX 시나리오 가이드

1. **건물 2D 도면 오버레이**:
   - `GET /api/v1/buildings/{id}`의 `floor_plan_image`를 지도 위에 오버레이.
2. **실시간 위치 추적**:
   - WebSocket의 `LOCATION_UPDATE`로 대원 핀 위치와 방향 화살표를 즉시 업데이트하고 Polyline 궤적을 연장.
3. **AI 전술 마커 & 브리핑 카드 표출**:
   - `AI_MARKER_ALERT` 수신 시 해당 `coord`에 POI 핀 생성.
   - 마커 터치 시 하단에 **위험 등급 배지**, **Gemma 3 4B 현장 요약**, **지휘관 행동 권고**가 담긴 텍스트 전술 카드 표출 (이미지 로딩 대기시간 없이 즉시 반응).

---

## 8. 서버 실행 및 시험 가이드

### 8.1 백엔드 서버 실행 및 Swagger UI 공유 방법
다른 팀원(같은 Wi-Fi/네트워크망)이 웹 브라우저에서 바로 API 문서를 보고 테스트할 수 있도록 `--host 0.0.0.0` 옵션으로 서버를 띄웁니다.

1. **초기 DB 테이블 및 기본 시드 데이터(단말기/계정/건물) 생성** (최초 1회)
   ```bash
   python app/scripts/init_db.py
   ```
2. **FastAPI 서버 외부 접속 허용 실행**
   ```bash
   uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
   ```
3. **내 PC의 IP 주소 확인 후 팀원에게 공유**
   - Windows 파워셸/터미널에서 `ipconfig` 실행 후 **IPv4 주소**(예: `192.168.0.x`) 확인
   - 팀원 공유 링크:
     - **Swagger UI (인터랙티브 테스트)**: `http://<서버PC_IP>:8000/docs`
     - **ReDoc (문서 뷰어)**: `http://<서버PC_IP>:8000/redoc`

### 8.2 Swagger UI(`/docs`)에서 조회 API 시험
1. 브라우저에서 `http://<서버PC_IP>:8000/docs` 접속
2. `POST /api/v1/auth/login` → **[Try it out]** → `X-Terminal-Id: TAB-HQ-001`, Body 기본값(`FIRE-CMD-101` / `123456`) → **[Execute]**
3. 응답의 `access_token`을 우측 상단 **[Authorize]**에 입력
4. (작전이 없으면) `POST /api/v1/missions`로 `building_id: 1`, `device_id: "EDGE-CAM-01"` 작전 생성
5. 8.3으로 세션을 가져온 뒤 `GET /api/v1/missions/{id}/map-state`, `GET /api/v1/missions/{id}/ai-assessments`로 결과 확인

> 현장 데이터를 넣는 HTTP API는 없습니다. 데이터는 8.3의 가져오기 스크립트로만 들어옵니다.

### 8.3 임베디드 SSD 세션 가져오기(`import_fire_vision_session.py`)
3장 규격의 세션 폴더를 서버에서 직접 읽습니다. 서버(uvicorn)가 꺼져 있어도 가져오기·분석은 됩니다(앱 실시간 푸시만 생략).

```bash
# SSD를 노트북에 연결한 뒤 (프로젝트 루트에서)
python app/scripts/import_fire_vision_session.py E:/session_20261120_01 --mission 1
# 옵션: --interval 2 (샘플링 간격 초, 기본 1) / --max-frames 10 / --save-only (저장만)
#       --server http://<서버>:8000 (앱 푸시 대상) / --no-notify
```

| 단계 | 내용 |
| :--- | :--- |
| 1. Save-First | 목표 시각(0, 1, 2…초)에 가장 가까운 RGB 프레임을 골라 해시 검증 → JPEG(`static/snapshots/`) 저장 → 원본 메타(3.3)를 `raw_telemetry_logs`에 **프레임마다 즉시 커밋** (`is_processed=false`) |
| 2. 분석 | 미처리 프레임을 Gemma 3 4B로 분석(4장) → `ai_assessments`, `detection_events` 저장 |
| 3. 앱 푸시 | 결과가 확정될 때마다 `POST /missions/{id}/notify/assessments` → 서버가 `AI_MARKER_ALERT`·`ASSESSMENTS_IMPORTED` 방송 (6·9.7장) |

- **Gemma 미연결 시**: 1단계만 수행하고 원본을 미처리로 남깁니다(가짜 결과 생성 안 함). Gemma를 켠 뒤 같은 명령을 다시 실행하면 분석만 이어서 합니다.
- **중복 방지**: 같은 세션을 다시 넣어도 이미 저장된 프레임은 건너뜁니다.
- **서버 꺼짐·키 오류**: 경고만 출력하고 분석·저장은 계속합니다. 앱은 `/map-state` 새로고침으로 확인합니다.
- **Gemma 준비**: Ollama 설치 → `ollama pull gemma3:4b` → `.env`에 `GEMMA_API_URL=http://127.0.0.1:11434/api/generate` (GPU 8GB에서 프레임당 약 9초, 첫 로드 약 70초)

### 8.4 Jetson 없이 시험 세션 만들기(`make_sample_fire_vision_session.py`)
3장과 같은 구조의 시험 세션을 만듭니다. 안드로이드 화면 개발·서버 시험용입니다(**실측 데이터 아님**).

```bash
# 실제 사진 폴더로 (사진 1장 = 1초 프레임, Gemma 실제 성능 확인용)
python app/scripts/make_sample_fire_vision_session.py D:/test_session --images D:/photos
# 사진 없이 합성 영상 (5초, 15fps, 이동하는 주황 사각형 — 동작 확인용)
python app/scripts/make_sample_fire_vision_session.py D:/test_session

python app/scripts/import_fire_vision_session.py D:/test_session --mission 1
```

---

## 9. 안드로이드 앱 연동 가이드 (`android` 브랜치 기준)

> 2026-11-16 `android` 브랜치(커밋 `648a94c`)와 서버 코드를 대조해 작성했습니다. 아래 JSON은 **서버가 실제로 보내는 형식**이며, 앱 DTO를 이 형식에 맞춰야 합니다.

### 9.1 현재 연동 상태 요약

| 기능 | 앱 현재 상태 | 해야 할 일 |
| :--- | :--- | :--- |
| 로그인 | `login()` 정의만 있고 호출하는 곳 없음 → 토큰 없음 | 앱 시작 시 로그인 호출, 토큰 저장 (9.3) |
| `/map-state` | 토큰 없이 호출 → 401. 필드명 불일치, 응답을 쓰지 않음 | DTO 수정, `active_markers`로 지도 마커 생성 (9.5) |
| `/ai-assessments` | 필드명 불일치 | DTO 수정 (9.6) |
| WebSocket | 토큰 없음 → 연결 거부. `"event"` 키로 분기(서버는 `"type"`) | 9.7 |
| `/telemetry/raw`·`/batch` 전송 | 카메라 탭이 고정 샘플 3건을 서버로 전송 | **서버에서 API 삭제됨(404).** 전송 코드 제거, 카메라 탭은 스냅샷+박스 표시로 변경 (9.9) |
| 지도 마커 | `SpatialMapCanvasView`에 고정 샘플 5개 | 서버 응답으로 교체 |
| 서버 주소·단말·작전 | `10.0.2.2:8000`, `TAB-HQ-001`, 작전 1 고정 | 설정 화면에서 입력 (9.2) |

### 9.2 호출 순서와 설정값

```text
① 설정: 서버 주소 / 단말 ID 입력 (저장)
② GET  /api/v1/auth/terminal/check        헤더 X-Terminal-Id            → 인가 단말인지 확인
③ POST /api/v1/auth/login                 헤더 X-Terminal-Id + 사번/PIN → access_token 저장
④ GET  /api/v1/missions/active            헤더 Authorization: Bearer    → 작전 선택
⑤ GET  /api/v1/missions/{id}/map-state    → 지도 초기 표시
⑥ WS   /ws/missions/{id}/dashboard?token=<access_token>  → 실시간 갱신
⑦ (재연결·화면 복귀·새로고침 시) ⑤ 다시 호출
```

| 설정 | 값 |
| :--- | :--- |
| 서버 주소 | 에뮬레이터: `http://10.0.2.2:8000` / 실제 기기: `http://<서버PC_IPv4>:8000` (같은 Wi-Fi, 서버는 `--host 0.0.0.0`으로 실행) |
| 단말 ID | 시드 데이터: `TAB-HQ-001`, `TAB-RESCUE-002` |
| 테스트 계정 | 사번 `FIRE-CMD-101` / PIN `123456` |
| 토큰 유효시간 | 응답의 `expires_in`(초), 기본 43200초(12시간). 401을 받으면 로그인 화면으로 |

> **SSD 가져오기(8.3) 결과도 WebSocket으로 푸시됩니다.** 가져오기 스크립트가 프레임 하나를 분석해 저장할 때마다 서버(`POST /missions/{id}/notify/assessments`)에 알리고, 서버가 `AI_MARKER_ALERT`(위험·인명)와 `ASSESSMENTS_IMPORTED`(새 결과 알림)를 방송합니다(9.7). 단, 가져오기 중 서버가 꺼져 있었다면 푸시가 없으므로, 앱은 화면 진입·재연결 시 `/map-state`를 다시 불러와야 합니다.

### 9.3 로그인

**요청** `POST /api/v1/auth/login` · 헤더 `X-Terminal-Id: TAB-HQ-001`
```json
{ "service_number": "FIRE-CMD-101", "pin": "123456" }
```

**응답 200**
```json
{
  "access_token": "eyJhbGciOi...",
  "token_type": "bearer",
  "expires_in": 43200,
  "officer": {
    "user_id": 1, "service_number": "FIRE-CMD-101", "full_name": "이지휘",
    "rank": "소방경", "department": "...", "role": "COMMANDER", "security_clearance": 2
  },
  "terminal_id": "TAB-HQ-001"
}
```

**오류**: 401 미등록 사번 또는 PIN 불일치 / 403 비활성 계정 / 403 미등록·차단 단말. 본문은 `{"detail": "..."}`.

**앱 DTO 수정** — `role`, `full_name`은 최상위가 아니라 `officer` 안에 있습니다.
```java
public static class LoginResponse {
    @SerializedName("access_token") public String accessToken;
    @SerializedName("token_type")   public String tokenType;
    @SerializedName("expires_in")   public int expiresIn;
    @SerializedName("officer")      public OfficerInfo officer;
    @SerializedName("terminal_id")  public String terminalId;
}
public static class OfficerInfo {
    @SerializedName("user_id")            public int userId;
    @SerializedName("service_number")     public String serviceNumber;
    @SerializedName("full_name")          public String fullName;
    @SerializedName("rank")               public String rank;
    @SerializedName("department")         public String department;
    @SerializedName("role")               public String role;          // ADMIN / COMMANDER / OPERATOR
    @SerializedName("security_clearance") public int securityClearance;
}
```

**단말 확인** `GET /api/v1/auth/terminal/check` 응답: `{"terminal_id": "TAB-HQ-001", "terminal_name": "...", "is_authorized": true}`

### 9.4 작전 목록

`GET /api/v1/missions/active` 응답 (배열)
```json
[{ "mission_id": 1, "title": "테스트 작전 1호", "building_id": 1, "device_id": "EDGE-CAM-01",
   "commander_id": 1, "start_time": "2026-10-04T16:30:00", "end_time": null, "status": "ACTIVE" }]
```

### 9.5 지도 초기 데이터 `/map-state`

**응답 200**
```json
{
  "mission_id": 1,
  "title": "테스트 작전 1호",
  "status": "ACTIVE",
  "building_id": 1,
  "device_id": "EDGE-CAM-01",
  "current_location": { "x": 10.0, "y": 5.0, "z": 0.0 },
  "current_yaw": 45.0,
  "trajectory": [ { "x": 2.0, "y": 1.0, "z": 0.0 } ],
  "active_markers": [
    {
      "type": "AI_MARKER_ALERT",
      "mission_id": 1,
      "assessment_id": 39,
      "timestamp": 1763280000000,
      "hazard_level": "CRITICAL",
      "poi_type": "PERSON_RESCUE",
      "title": "[CRITICAL] 🚨 구조 대상자 발견",
      "summary": "바닥에 쓰러진 사람 형태",
      "action_recommendation": "구조 대상 후보 식별됨. ...",
      "coord": { "x": 286.0, "y": 500.0, "z": 0.0 },
      "snapshot_url": "/static/snapshots/snapshot_m1_1763280000000_d79ae196.jpg",
      "frame_id": 15,
      "detected_objects": [
        { "class": "person", "screen_box": [143, 286, 429, 714], "description": "바닥에 쓰러진 사람 형태" }
      ]
    }
  ]
}
```
- `active_markers`에는 `CRITICAL`·`WARNING`이거나 인명이 발견된 판단만 들어갑니다. 전체 이력은 9.6을 쓰세요.
- `current_location`은 위치 데이터가 없으면 `null`, `trajectory`는 빈 배열일 수 있습니다.
- `snapshot_url`은 서버 주소 뒤에 붙여서 이미지를 받습니다(`http://<서버>:8000/static/...`). `null`일 수 있습니다.

**앱 DTO 필드 대조**

| 앱 현재 (`MapStateResponse`/`PoiMarkerDto`) | 서버 실제 | 비고 |
| :--- | :--- | :--- |
| `building_name` | (없음) → `title` | 건물명이 필요하면 `building_id`로 별도 조회 |
| `markers` | `active_markers` | |
| `marker_id` | `assessment_id` (int) | 화면 표시용 ID(R-01 등)는 앱에서 생성 |
| `situation_summary` | `summary` | |
| `coord_x`, `coord_y` | `coord.x`, `coord.y` (중첩 객체) | 단위 주의 (9.8) |
| `distance_m`, `ambient_temp` | (없음) | 센서 미연결. 화면에 "—"로 표시, 가짜 기본값 금지 |
| `observed_at` | `timestamp` (Unix ms) | 앱에서 `HH:mm:ss`로 변환 |
| (없음) | `title`, `action_recommendation`, `snapshot_url` | 상세 카드에 활용 |
| (없음) | `frame_id`, `detected_objects[]` | 스냅샷 위에 `screen_box` 박스를 그릴 때 사용 (9.9) |

```java
public static class Coordinate { public float x; public float y; public float z; }

public static class MapStateResponse {
    @SerializedName("mission_id")       public int missionId;
    @SerializedName("title")            public String title;
    @SerializedName("status")           public String status;
    @SerializedName("building_id")      public int buildingId;
    @SerializedName("device_id")        public String deviceId;
    @SerializedName("current_location") public Coordinate currentLocation;   // null 가능
    @SerializedName("current_yaw")      public Float currentYaw;             // null 가능
    @SerializedName("trajectory")       public List<Coordinate> trajectory;
    @SerializedName("active_markers")   public List<MapMarker> activeMarkers;
}
public static class MapMarker {
    @SerializedName("assessment_id")         public int assessmentId;
    @SerializedName("timestamp")             public long timestamp;          // Unix ms
    @SerializedName("hazard_level")          public String hazardLevel;
    @SerializedName("poi_type")              public String poiType;
    @SerializedName("title")                 public String title;
    @SerializedName("summary")               public String summary;
    @SerializedName("action_recommendation") public String actionRecommendation;
    @SerializedName("coord")                 public Coordinate coord;
    @SerializedName("snapshot_url")          public String snapshotUrl;      // null 가능
    @SerializedName("frame_id")              public Integer frameId;         // null 가능
    @SerializedName("detected_objects")      public List<DetectedObject> detectedObjects;
}
public static class DetectedObject {
    @SerializedName("class")       public String objectClass;       // person, fire, smoke, obstacle, door, stairs, fire_extinguisher, other
    @SerializedName("screen_box")  public List<Integer> screenBox;  // [x1, y1, x2, y2] 스냅샷 원본 픽셀
    @SerializedName("description") public String description;
}
```

**`poi_type` → 앱 표시 대응** (UI 디자인 가이드 시맨틱 컬러)

| `poi_type` | 앱 `SpatialNode.NodeType` | 색 |
| :--- | :--- | :--- |
| `PERSON_RESCUE` | `RESCUE_TARGET` | Red `#FF4D4F` |
| `FIRE_HOTSPOT` | `HIGH_TEMP_ZONE` | Orange `#FF8A3D` |
| `OBSTACLE_HAZARD` | `OBSTACLE_WARN` | Yellow `#F5C542` |
| `SAFE_PATH` | (경로 표시) | Green `#4CAF78` |

`hazard_level`: `CRITICAL` / `WARNING` / `NORMAL` / `UNKNOWN`

### 9.6 AI 분석 이력 `/ai-assessments?limit=50`

응답은 배열이며 **최신순**입니다.
```json
[{
  "assessment_id": 39, "mission_id": 1, "device_id": "EDGE-CAM-01",
  "timestamp": 1763280000000, "hazard_level": "CRITICAL",
  "situation_summary": "바닥에 쓰러진 사람 형태",
  "human_detected": true, "human_status": "바닥에 쓰러진 사람 형태",
  "action_recommendation": "구조 대상 후보 식별됨. ...", "poi_type": "PERSON_RESCUE",
  "coord_x": 286.0, "coord_y": 500.0, "coord_z": 0.0,
  "snapshot_url": "/static/snapshots/...jpg", "frame_id": 15,
  "detected_objects": [ { "class": "person", "screen_box": [143, 286, 429, 714], "description": "바닥에 쓰러진 사람 형태" } ],
  "created_at": "2026-11-16T20:10:00"
}]
```
여기는 `/map-state`와 달리 좌표가 `coord_x/coord_y` 평면 필드입니다. `NORMAL` 판단도 포함되므로 탐지 목록 화면에 적합합니다. 앱 `PoiMarkerDto`를 이 형식으로 바꾸거나 이력 전용 DTO를 따로 두세요 (`marker_id` → `assessment_id`, `observed_at` → `timestamp`/`created_at`, `distance_m`·`ambient_temp` 제거).

### 9.7 실시간 WebSocket

- 연결: `ws://<서버>:8000/ws/missions/{id}/dashboard?token=<access_token>` (토큰이 없거나 틀리면 코드 1008로 끊김)
- **메시지 종류는 `"type"` 키로 구분합니다.** 앱은 현재 `"event"`를 읽고 있어 모든 메시지를 무시합니다.
- 연결 유지: 앱이 `"PING"` 텍스트를 보내면 서버가 응답합니다. OkHttp `pingInterval`도 유지하세요.
- 재연결 후에는 끊긴 동안의 경보를 받지 못하므로 `/map-state`를 다시 호출하세요.

```json
{ "type": "CONNECTION_ESTABLISHED", "mission_id": 1, "officer": "이지휘", "role": "COMMANDER", "message": "..." }

// LOCATION_UPDATE — 현재 발생하지 않음 (위치 데이터 생성 이후 사용)
{ "type": "LOCATION_UPDATE", "mission_id": 1, "device_id": "EDGE-CAM-01", "timestamp": 1763280000000,
  "frame_id": 1042, "x": 8.5, "y": 4.3, "z": 0.0, "yaw": null, "max_temperature": null }

{ "type": "AI_MARKER_ALERT", "mission_id": 1, "assessment_id": 105, "timestamp": 1763280000000,
  "frame_id": 1042, "hazard_level": "CRITICAL", "poi_type": "FIRE_HOTSPOT",
  "title": "[CRITICAL] 🔥 화재 위험", "summary": "...", "action_recommendation": "...",
  "coord": { "x": 8.5, "y": 4.3, "z": 0.0 },
  "detected_objects": [ { "class": "fire", "screen_box": [410, 100, 590, 390], "description": "..." } ],
  "snapshot_url": null }

{ "type": "ASSESSMENTS_IMPORTED", "mission_id": 1, "source": "fire_vision_import",
  "count": 1, "alert_count": 1, "assessment_ids": [52], "latest_timestamp": 1763280000000,
  "message": "새 분석 결과 1건이 저장되었습니다. 전체 상태는 /map-state를 다시 조회하세요." }
```

- `ASSESSMENTS_IMPORTED`: SSD 가져오기 등 서버 밖에서 저장된 결과가 생겼다는 알림입니다. 위험이 아닌(`NORMAL`) 결과도 포함되므로, 탐지 목록·이력 화면은 이 메시지를 받으면 `/ai-assessments`를 다시 불러오면 됩니다. 위험·인명 판단은 이 메시지 **앞에** `AI_MARKER_ALERT`로 먼저 옵니다.

**`MissionWebSocketClient.parseRealtimeMessage` 수정 대조**

| 앱 현재 | 서버 실제 |
| :--- | :--- |
| `root.optString("event")` | `root.optString("type")` |
| `marker_id` | `assessment_id` |
| `description` | `summary` (물체별 설명은 `detected_objects[].description`) |
| `coord_x`, `coord_y` | `root.getJSONObject("coord").optDouble("x")` / `"y"` |
| `distance_m`, `ambient_temp` | 없음 |
| `yaw`, `max_temperature` | 키는 있지만 값이 `null`일 수 있음 → `isNull()` 확인 |

`optDouble("x", 1.10)`, `optDouble("ambient_temp", 82.0)`처럼 **그럴듯한 기본값을 넣지 마세요.** 값이 없을 때 가짜 위치·온도가 화면에 표시됩니다. 없으면 표시하지 않거나 "—"로 두세요.

### 9.8 좌표 단위 주의

현재 위치(pose) 데이터가 없어서 마커 좌표(`coord`, `coord_x/y`)는 **카메라 화면의 픽셀값**(예: 286, 500)입니다. 실제 공간의 미터 좌표가 아닙니다.
- 앱에서 `"위치 X 3.52m"`처럼 m 단위로 표시하지 마세요. 발표자료 8쪽처럼 **"화면 위치 X:286, Y:500 (2D 프레임 기준)"** 으로 표시하세요.
- 지도 위 배치는 임베디드 E1(SLAM)으로 실제 좌표가 생긴 뒤에 합니다. 그 전까지는 탐지 목록과 카메라 화면(스냅샷 + `screen_box` 박스) 위주로 보여 주는 것을 권장합니다.

### 9.9 카메라 탭: 서버로 보내지 말고 결과를 보여 주세요

현장 데이터는 SSD → 서버 가져오기(8.3)로만 들어오며, **앱이 서버로 데이터를 보내는 API는 없습니다** (`/telemetry/raw`, `/telemetry/batch` 삭제 → 404).

- `RescueApiService`의 `sendRawTelemetry`, `sendBatchTelemetry`와 `ApiModels.TelemetryPayload`·`TelemetryResponse`를 제거하세요.
- 카메라 탭의 "공간지도 생성 요청" 버튼(고정 샘플 전송)은 제거하거나 "새로고침"(`/map-state`·`/ai-assessments` 재조회)으로 바꾸세요.
- 카메라 탭은 발표자료 8쪽 설계대로 **분석된 프레임을 보여 주는 화면**으로 쓰는 것을 권장합니다.
  1. `/ai-assessments`에서 판단 하나를 고름 (최신순)
  2. `snapshot_url` 이미지를 표시 (`http://<서버>:8000` + `snapshot_url`)
  3. `detected_objects[].screen_box`를 이미지 위에 박스로 그림 — 좌표는 **원본 이미지 픽셀** 기준이므로 화면 크기에 맞게 비율 변환
  4. 박스 색은 `class` 기준: `person` Red, `fire`·`smoke` Orange, 그 외 Yellow
  5. 관측 시각(`timestamp`)과 "세션 분석 결과"를 표시 (실시간 영상이 아님을 명확히)
- 시험 데이터가 필요하면 8.4로 시험 세션을 만들어 가져오세요.

### 9.10 저장소 구조 (main 병합 전 필수)

- 안드로이드 모듈 폴더(`app/`)가 서버 Python 패키지(`app/`)와 같은 폴더에 섞여 있습니다. 안드로이드 프로젝트 전체를 **`android/` 하위 폴더**로 옮겨 주세요 (`android/app/`, `android/build.gradle.kts`, `android/settings.gradle.kts`, `android/gradle/` …).
- `.gitignore`가 안드로이드용으로 교체되어 `.env`, `__pycache__`, `.venv`, `docs/*` 규칙이 빠졌습니다. **이대로 병합하면 DB 비밀번호가 든 `.env`가 GitHub에 올라갈 수 있습니다.** 원래 규칙을 되살리고 안드로이드 규칙을 `android/` 경로 기준으로 추가해 주세요.
- 녹음 기능을 쓰지 않으므로 `RECORD_AUDIO` 권한은 제거를 권장합니다.


