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
- **프론트엔드 / UI 디자인 (정세빈 님, 이세이 님)**: [5. 모바일 관제 UI용 REST API 명세](#5-서버--모바일-지도-앱-rest-api-명세) 및 [6. 실시간 WebSocket 명세](#6-서버--모바일-지도-앱-실시간-websocket-명세) 참조

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

서버는 무거운 이미지 처리 없이, 계측된 센서 수치(열화상 최고/평균/핫스팟, 전방 거리, CO 농도, 방위각)를 기반으로 Gemma 3 4B 모델을 통해 초고속(수십 ms 이내) 전술 상황 판단을 수행합니다.

### 4.1 모델 프롬프트 입력 형식
- **시스템 역할**: 소방·구조 현장 전술 AI 참모
- **입력 데이터**: 실시간 센서 계측 수치 요약

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


