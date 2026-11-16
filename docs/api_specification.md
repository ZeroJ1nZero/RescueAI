# 연암소방대 시스템 데이터 입출력(I/O) 및 API 상세 명세서

> **문서 버전**: v3.0 (JSON/JSONL 객체 추출 스키마 & 3계층 Save-First 파이프라인)  
> **최종 수정일**: 2026-10-18  
> **대상 독자**: 데이터 엔지니어링(신경준), 인프라/클라우드(공진영), 프론트엔드/UI(정세빈, 이세이)  
> **개정 배경**: 현장 AI 보드 촬영 $\rightarrow$ 외장 SSD 세션 이동 $\rightarrow$ 서버 Gemma 3 4B VLM 분석 $\rightarrow$ JSON/JSONL 구조화 및 Save-First 선저장 파이프라인 규격에 맞춰 데이터 수집 API 및 단말 인가 헤더(`X-Terminal-Id`)를 표준화함.

---

## 1. 시스템 데이터 흐름 및 역할 분담 (Architecture Overview)

```
┌────────────────────────────────────────────────────────────┐
│ [Layer 01. 수집 계층 (Ingestion)]                           │
│  - 01. 현장 AI 보드/카메라: 원시 세션 데이터 외장 SSD 기록 │
│  - 02. 오프라인 세션 이동 (현재: 외장 SSD / 향후: 무선망)  │
│  - MDM 인가 단말 검증 (X-Terminal-Id 헤더 대조)            │
│  - Save-First 원칙: 원시 데이터(raw_telemetry_logs) 선저장 │
└─────────────────────────────┬──────────────────────────────┘
                              │ HTTP POST /telemetry/raw 또는 /telemetry/batch
                              ▼
┌────────────────────────────────────────────────────────────┐
│ [Layer 02. 분석 계층 (Processing)]                          │
│  - 서버 호스트 Gemma 3 4B VLM 프레임 샘플링 & 멀티모달 추론│
│  - 인명 후보, 장애물, 화염 검출 → JSON/JSONL 구조화        │
│  - 화면 위치(screen_box) 및 센서 메타데이터 정합           │
└───────────────┬────────────────────────────┬───────────────┘
                │ REST API (사후 세션 조회)   │ WebSocket (실시간 스트리밍)
                ▼                            ▼
┌────────────────────────────────────────────────────────────┐
│ [Layer 03. 관제 계층 (Control API & Map-First UI)]          │
│  - 3단계 심층 보안 (단말 검증 → PIN bcrypt → RBAC 권한)    │
│  - 시맨틱 컬러 규격(Red/Orange/Yellow/Green/Blue) 마커 표출│
└────────────────────────────────────────────────────────────┘
```

### 담당 팀원별 참고 가이드
- **데이터 엔지니어링 / AI 보드 (신경준 님)**: [2. 공통 인증 규격](#2-공통-인증-규격-authentication), [3. AI 보드/세션 $\rightarrow$ 서버 데이터 수집 API 명세](#3-수집-계층-ai-보드세션--서버-데이터-입력-명세) 및 [8. Swagger UI 및 테스트 스크립트 실행 가이드](#8-swagger-ui-공유-및-테스트-스크립트-사용법) 참조
- **인프라 / 클라우드 (공진영 님)**: [1. 시스템 데이터 흐름](#1-시스템-데이터-흐름-및-역할-분담-architecture-overview) 및 [8. 서버 실행 및 Swagger 공유 가이드](#8-swagger-ui-공유-및-테스트-스크립트-사용법) 참조
- **프론트엔드 / UI 디자인 (정세빈 님, 이세이 님)**: [5. 모바일 관제 UI용 REST API 명세](#5-서버--모바일-지도-앱-rest-api-명세) 및 [6. 실시간 WebSocket 명세](#6-서버--모바일-지도-앱-실시간-websocket-명세), **[9. 안드로이드 앱 연동 가이드](#9-안드로이드-앱-연동-가이드-android-브랜치-기준)** 참조

---

## 2. 공통 인증 규격 (Authentication)

### 2.1 수집 계층 MDM 인가 단말 및 엣지 보드 인증
데이터 수집 API(`/telemetry`, `/telemetry/raw`, `/telemetry/batch`) 호출 시 아래 두 가지 방식 중 편한 헤더를 포함하여 전송합니다.

- **방식 A (MDM 인가 단말 헤더 - 권장)**:
  ```http
  X-Terminal-Id: TAB-HQ-001
  ```
  *(사전 등록된 인가 식별자: `TAB-HQ-001`, `TAB-RESCUE-002`, `EDGE-CAM-01`)*

- **방식 B (엣지 장비 API Key 헤더 - 호환 지원)**:
  ```http
  X-Device-Id: EDGE-CAM-01
  X-Device-Key: rescue-edge-secret-key-01
  ```

### 2.2 관제 계층 모바일/웹 대시보드 인증 (3단계 심층 보안)
- **로그인(`POST /api/v1/auth/login`)**: `X-Terminal-Id: TAB-HQ-001` 헤더 + 사번(`FIRE-CMD-101`) + PIN(`123456`)
- **REST API 헤더**: `Authorization: Bearer <JWT_TOKEN>`
- **WebSocket 쿼리 스트링**: `ws://<server-ip>:8000/ws/missions/{mission_id}/dashboard?token=<JWT_TOKEN>`

---

## 3. [수집 계층] AI 보드/세션 $\rightarrow$ 서버 데이터 입력 명세

단일 프레임 전송(`/telemetry/raw`)과 외장 SSD 세션 단위 일괄 배열 전송(`/telemetry/batch`)을 모두 지원합니다.

- **단일 프레임 등록 URL**: `POST http://<server-ip>:8000/api/v1/missions/{mission_id}/telemetry/raw` (또는 `/telemetry`)
- **세션 일괄(배치) 등록 URL**: `POST http://<server-ip>:8000/api/v1/missions/{mission_id}/telemetry/batch`
- **Content-Type**: `application/json`

### 3.1 요청 바디 (Request Body) 필드 정의

| 필드명 | 타입 | 필수 | 설명 및 단위 | 예시값 |
| :--- | :--- | :---: | :--- | :--- |
| `timestamp` | `string` \| `int` | **필수** | 관측 절대시각 (ISO 8601 문자열 또는 Unix Epoch ms) | `"2026-10-12T05:20:00Z"` |
| `frame_id` | `int` | 권장 | 샘플링된 영상 프레임 번호 | `1042` |
| `detected_objects` | `array` | 권장 | Gemma 3 4B VLM이 추출한 탐지 객체 배열 | 아래 서브 필드 참조 |
| `detected_objects[].class` | `string` | **필수** | 객체 분류 라벨 (`chair`, `person`, `fire`, `obstacle` 등) | `"chair"` |
| `detected_objects[].screen_box` | `int[4]` | **필수** | 2D 화면 좌표계 바운딩 박스 `[x1, y1, x2, y2]` | `[120, 240, 310, 450]` |
| `detected_objects[].description` | `string` | **필수** | 상황 서술 텍스트 | `"복도 중앙을 가로막고 있는 장애물 의자"` |
| `location` | `object` | 선택 | *(센서 확장용)* 실측 2D/3D 월드 좌표 `{x, y, z}` (미지정 시 `screen_box` 중심점으로 자동 매핑) | `{"x": 4.5, "y": 2.1, "z": 0.0}` |
| `imu` / `temperature` | `object` | 선택 | *(센서 확장용)* IMU 방위각 및 열화상 온도 계측치 | `{"max": 78.5, "avg": 28.5}` |

> **※ 화면상 위치(Screen Coords) vs 실제 공간 좌표(World Coords)**:  
> 현재 프로토타입 단계에서는 단일 카메라 2D 영상 픽셀 내 상대 위치(`screen_box`)만 전송해도 서버가 중심 픽셀 좌표를 추출하여 저장하며, 향후 RGB-D/IMU/열화상 센서(`location`, `imu`, `temperature`)를 함께 보내면 2D/3D 월드 좌표로 자동 확장됩니다.

### 3.2 단일 프레임 요청 JSON 페이로드 예시 (`POST /api/v1/missions/1/telemetry/raw`)
```json
{
  "timestamp": "2026-10-12T05:20:00Z",
  "frame_id": 1042,
  "detected_objects": [
    {
      "class": "chair",
      "screen_box": [120, 240, 310, 450],
      "description": "복도 중앙을 가로막고 있는 장애물 의자"
    }
  ]
}
```

### 3.3 외장 SSD 세션 일괄 등록 JSON 예시 (`POST /api/v1/missions/1/telemetry/batch`)
```json
[
  {
    "timestamp": "2026-10-12T05:20:00Z",
    "frame_id": 1042,
    "detected_objects": [
      {
        "class": "chair",
        "screen_box": [120, 240, 310, 450],
        "description": "복도 중앙을 가로막고 있는 장애물 의자"
      }
    ]
  },
  {
    "timestamp": "2026-10-12T05:20:05Z",
    "frame_id": 1192,
    "detected_objects": [
      {
        "class": "person",
        "screen_box": [200, 150, 380, 520],
        "description": "ROOM A 내부 바닥에 쓰러져 있는 구조 대상 후보 1명"
      }
    ]
  }
]
```

### 3.4 응답 JSON 예시 (200 OK)
```json
{
  "status": "SAVED_AND_ASSESSED",
  "mission_id": 1,
  "timestamp": "2026-10-12T05:20:00Z",
  "frame_id": 1042,
  "detected_objects_count": 1,
  "assessment_id": 105,
  "hazard_level": "WARNING"
}
```

---


## 4. AI 상황 판단 모델 (Gemma 3 4B) 입출력 규격

서버(`app/services/ai_assessor.py`)는 수신 프레임에 `detected_objects`가 있으면 이를 우선 매핑해 위험도를 판단하고, 없으면 센서 계측 수치(열화상 최고/평균/핫스팟, 전방 거리, CO 농도, 방위각)를 기반으로 상황 판단을 수행합니다.

### 4.1 모델 프롬프트 입력 형식
- **시스템 역할**: 소방·구조 현장 전술 AI 참모
- **입력 데이터**: ① 프레임 탐지 객체(`class`, `screen_box`, `description`) ② (센서 연결 시) 실시간 센서 계측 수치 요약

### 4.2 모델 정형 출력 규격 (Structured JSON)
```json
{
  "hazard_level": "CRITICAL",
  "situation_summary": "전방 고온 발화 위험 감지 (최고온도 78.5℃, CO 120ppm). 플래시오버(Flashover) 발생 우려 높음.",
  "human_detected": false,
  "human_status": null,
  "action_recommendation": "대원 즉시 살수 방수 실시 및 안전거리 5m 이상 확보 후 후퇴 권고.",
  "poi_type": "FIRE_HOTSPOT",
  "confidence": 0.94
}
```

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

## 8. Swagger UI 공유 및 테스트 스크립트 사용법

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

### 8.2 Swagger UI(`/docs`)에서 팀원이 바로 테스트하는 순서
1. 웹 브라우저에서 `http://<서버PC_IP>:8000/docs` 접속
2. **(작전이 아직 없는 경우)** 먼저 `POST /api/v1/auth/login`에서 `X-Terminal-Id: TAB-HQ-001`, 사번 `FIRE-CMD-101`, PIN `123456`으로 로그인 후 발급받은 `access_token`을 우측 상단 **[Authorize]** 버튼에 입력 $\rightarrow$ `POST /api/v1/missions`로 작전(`mission_id: 1`) 생성
3. **`POST /api/v1/missions/{mission_id}/telemetry/raw`** (또는 `/telemetry/batch`) 클릭 $\rightarrow$ **[Try it out]** 클릭
4. 파라미터 입력:
   - `mission_id`: `1`
   - `X-Terminal-Id`: `TAB-HQ-001`
   - Request body: 기본 예시 JSON 그대로 두고 **[Execute]** 클릭
5. `200 OK` 응답과 함께 `SAVED_AND_ASSESSED` 및 `hazard_level` 결과 즉시 확인!

### 8.3 파이썬 테스트 스크립트(`mock_edge_sender.py`) 공유 및 실행
팀원에게 `app/scripts/mock_edge_sender.py` 파일을 전달하거나, 레포지토리에서 바로 아래 명령어로 샘플 프레임 3건(장애물 의자, 구조 대상 인명, 고온 화점)을 연속 전송해 볼 수 있습니다.

```bash
# 작전 #1로 샘플 프레임(chair, person, fire) 전송 테스트
python app/scripts/mock_edge_sender.py 1
```
- 다른 PC에서 원격 서버로 쏠 때는 `app/scripts/mock_edge_sender.py` 상단의 `SERVER_URL = "http://<서버PC_IP>:8000"` 만 수정하여 실행하면 됩니다.

### 8.4 임베디드 SSD 세션 가져오기(`import_fire_vision_session.py`) — MVP 기본 경로
임베디드(`embedded` 브랜치 `edge/fire_vision`)가 SSD에 녹화한 ROS2 bag을 `extract-bag`으로 추출한 폴더(`manifest.json` + `rgb/*.npy`, 형식 `fire-vision-normalized-v1`)를 서버에서 직접 읽습니다. 서버 API를 거치지 않고 DB에 바로 기록하므로 서버(uvicorn)가 꺼져 있어도 됩니다.

```bash
# SSD를 노트북에 연결한 뒤 (프로젝트 루트에서)
python app/scripts/import_fire_vision_session.py E:/fire_vision/office1-1-e0 --mission 1
# 옵션: --interval 2 (샘플링 간격 초, 기본 1) / --max-frames 10 / --save-only (저장만)
```

| 단계 | 내용 |
| :--- | :--- |
| 1. Save-First | 목표 시각(0, 1, 2…초)에 가장 가까운 RGB 프레임을 골라 해시 검증 → JPEG(`static/snapshots/`) 저장 → 시각·원본 경로·해시·가장 가까운 IMU 원시값을 `raw_telemetry_logs`에 **프레임마다 즉시 커밋** (`is_processed=false`) |
| 2. 분석 | 미처리 프레임을 서버 Gemma 3 4B(Ollama `/api/generate` 호환)에 보내 `detected_objects`(class, screen_box, description) 수신 → 위험도는 기존 규칙 엔진으로 판정 → `ai_assessments`, `detection_events` 저장 |

- **Gemma 미연결 시**: 1단계만 수행하고 원본을 미처리로 남깁니다(가짜 결과 생성 안 함). Gemma를 켠 뒤 같은 명령을 다시 실행하면 분석만 이어서 합니다.
- **중복 방지**: `manifest.json` 해시로 세션을 식별합니다. 같은 SSD 세션을 다시 넣어도 이미 저장된 프레임은 건너뜁니다.
- **Gemma 응답 검증**: 허용 클래스(`person, fire, smoke, obstacle, door, stairs, fire_extinguisher, other`) 외 항목, 좌표가 잘못된 박스는 버리고, 이미지 밖 박스는 경계에서 자릅니다. Gemma에는 긴 변 896px로 줄여 보내고 결과 박스는 원본 해상도로 환산합니다.
- **좌표 주의**: 위치(pose)가 아직 없어 `sensor_logs`(이동 궤적)는 만들지 않습니다. `coord_x/y`는 screen_box 중심 **픽셀값**입니다(실제 공간 좌표 아님, `assessment_json.coord_meaning`에 명시).
- **앱 실시간 푸시**: 프레임 하나의 분석 결과가 DB에 확정될 때마다 서버 `POST /api/v1/missions/{id}/notify/assessments`(인증: `X-Device-Id`/`X-Device-Key`)에 알려, 접속 중인 앱에 `AI_MARKER_ALERT`·`ASSESSMENTS_IMPORTED`가 전송됩니다(9.7). 서버가 꺼져 있거나 거부하면 경고만 출력하고 분석·저장은 계속합니다. 옵션: `--server http://<서버>:8000`, `--no-notify`
- **Gemma 준비**: `ollama pull gemma3:4b` 후 `.env`에 `GEMMA_API_URL=http://127.0.0.1:11434/api/generate`

### 8.5 JSON 프레임 업로더(`ssd_session_uploader.py`) — 이미 구조화된 JSON용
AI 보드가 외장 SSD에 남긴 세션 폴더의 프레임 분석 결과(`*.json`, `*.jsonl`)를 읽어 `/telemetry/batch`로 묶음 전송합니다.

```bash
# 1) 전송 전 파일 검증만 (서버에 아무것도 보내지 않음)
python app/scripts/ssd_session_uploader.py E:/session_20261012_01 --mission 1 --dry-run

# 2) 실제 등록
python app/scripts/ssd_session_uploader.py E:/session_20261012_01 --mission 1 --server http://<서버PC_IP>:8000
```

- **읽는 파일**: 세션 폴더(하위 폴더 포함)의 `*.jsonl`(한 줄에 프레임 1개), `*.json`(프레임 1개 또는 배열). 파일명 순서대로 전송합니다.
- **프레임 형식**: 3.1의 `timestamp`, `frame_id`, `detected_objects` 규격. 선택 필드 `snapshot_file`(세션 폴더 기준 이미지 경로)이 있으면 이미지를 `snapshot_base64`로 첨부합니다.
- **사전 검증**: `timestamp` 누락, `screen_box`가 숫자 4개가 아님, 깨진 JSON 줄 등은 전송하지 않고 목록으로 알려줍니다. (잘못된 프레임 하나로 묶음 전체가 422로 거절되는 것을 방지)
- **이어 올리기**: 묶음 전송이 성공할 때마다 세션 폴더의 `.upload_state.json`에 진행 위치를 기록합니다. 중간에 끊겨도 같은 명령을 다시 실행하면 이어서 올리고, 이미 다 올린 세션은 다시 보내지 않습니다.
- **주의**: 서버에는 중복 제거 기능이 없습니다. 같은 세션을 처음부터 다시 올리려면 `--restart`를 명시해야 하며, 이때 기존 데이터는 그대로 남습니다.
- **옵션**: `--chunk-size`(기본 20), `--device-id` / `--device-key`(기본 `EDGE-CAM-01` 테스트 키, 환경변수 `RESCUE_DEVICE_ID` / `RESCUE_DEVICE_KEY` / `RESCUE_SERVER_URL`로도 지정 가능)

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
| `/telemetry/batch` | 고정 샘플 3건 전송, 응답을 `List`로 받아 파싱 실패, **실패해도 성공 토스트** | 시연용으로만 유지, 응답 DTO 수정 (9.9) |
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

> **SSD 가져오기(8.4) 결과도 WebSocket으로 푸시됩니다.** 가져오기 스크립트가 프레임 하나를 분석해 저장할 때마다 서버(`POST /missions/{id}/notify/assessments`)에 알리고, 서버가 `AI_MARKER_ALERT`(위험·인명)와 `ASSESSMENTS_IMPORTED`(새 결과 알림)를 방송합니다(9.7). 단, 가져오기 중 서버가 꺼져 있었다면 푸시가 없으므로, 앱은 화면 진입·재연결 시 `/map-state`를 다시 불러와야 합니다.

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
      "snapshot_url": "/static/snapshots/snapshot_m1_1763280000000_d79ae196.jpg"
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
  "snapshot_url": "/static/snapshots/...jpg", "created_at": "2026-11-16T20:10:00"
}]
```
여기는 `/map-state`와 달리 좌표가 `coord_x/coord_y` 평면 필드입니다. 앱 `PoiMarkerDto`를 이 형식으로 바꾸거나 이력 전용 DTO를 따로 두세요 (`marker_id` → `assessment_id`, `observed_at` → `timestamp`/`created_at`, `distance_m`·`ambient_temp` 제거).

### 9.7 실시간 WebSocket

- 연결: `ws://<서버>:8000/ws/missions/{id}/dashboard?token=<access_token>` (토큰이 없거나 틀리면 코드 1008로 끊김)
- **메시지 종류는 `"type"` 키로 구분합니다.** 앱은 현재 `"event"`를 읽고 있어 모든 메시지를 무시합니다.
- 연결 유지: 앱이 `"PING"` 텍스트를 보내면 서버가 응답합니다. OkHttp `pingInterval`도 유지하세요.
- 재연결 후에는 끊긴 동안의 경보를 받지 못하므로 `/map-state`를 다시 호출하세요.

```json
{ "type": "CONNECTION_ESTABLISHED", "mission_id": 1, "officer": "이지휘", "role": "COMMANDER", "message": "..." }

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

### 9.9 프레임 전송 API를 앱에서 쓸 경우

MVP의 현장 데이터는 SSD → 서버(8.4)로 들어오며, 앱은 **조회만** 하는 것이 원칙입니다. 카메라 탭의 "공간지도 생성 요청"은 시연용으로만 쓰고, 쓴다면 아래를 지켜 주세요.

- `/telemetry/batch` 응답은 리스트가 아니라 객체입니다.
  ```json
  { "status": "BATCH_SAVED_AND_ASSESSED", "mission_id": 1, "total_ingested": 3,
    "results": [ { "frame_id": 1042, "timestamp": "2026-10-12T05:20:00Z", "assessment_id": 105, "hazard_level": "WARNING" } ] }
  ```
- `onFailure`와 HTTP 오류(`!response.isSuccessful()`)에서는 **실패 메시지**를 보여 주세요. 지금은 실패해도 "반영 완료"가 표시되어 오류가 숨겨집니다.
- 이 API는 작전이 `ACTIVE`일 때만 받습니다(아니면 400).

### 9.10 저장소 구조 (main 병합 전 필수)

- 안드로이드 모듈 폴더(`app/`)가 서버 Python 패키지(`app/`)와 같은 폴더에 섞여 있습니다. 안드로이드 프로젝트 전체를 **`android/` 하위 폴더**로 옮겨 주세요 (`android/app/`, `android/build.gradle.kts`, `android/settings.gradle.kts`, `android/gradle/` …).
- `.gitignore`가 안드로이드용으로 교체되어 `.env`, `__pycache__`, `.venv`, `docs/*` 규칙이 빠졌습니다. **이대로 병합하면 DB 비밀번호가 든 `.env`가 GitHub에 올라갈 수 있습니다.** 원래 규칙을 되살리고 안드로이드 규칙을 `android/` 경로 기준으로 추가해 주세요.
- 녹음 기능을 쓰지 않으므로 `RECORD_AUDIO` 권한은 제거를 권장합니다.


