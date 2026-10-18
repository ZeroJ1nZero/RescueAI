---

# RescueAI 시스템 엔지니어링 및 데이터 입출력·DB 상세 명세서

> **개정 이력 (v2.0)**:
> 1. **데이터 저장 구조 개편 (JSON 우선 영속화 - Save First)**: 엣지 장비의 연산 부하를 최소화하기 위해 원시 계측 JSON 데이터를 서버 DB에 무조건 선(先) 저장한 후 가공하는 ELT 파이프라인으로 전환.
> 2. **AI 파이프라인 고도화**: 단순 YOLO 객체 탐지를 넘어, **Gemma 3 4B 멀티모달 모델** 기반으로 "실 계측값 + 현장 영상 스냅샷"을 결합하여 종합 위험도/인명 상태/전술 권고를 도출하는 상황 판단(Situation Assessment) 체계 구축.
> 3. **모바일 지도 앱 연동 인터페이스 표준화**: 지도 앱 개발팀에 즉시 전달 가능한 2D 실내 도면/GPS 좌표계 메타데이터, 전체 지도 상태 초기화 API, 실시간 위치 및 AI 위험 마커 WebSocket 명세 완비.

---

## 1. 시스템 구성도 및 데이터 파이프라인

```
┌──────────────────────────────────────────────────────────────┐
│ [현장 엣지 보드 (Edge)] (경량 수집기 - Lightweight Client)  │
│  - 저조도/열화상 카메라 스냅샷 (Base64 인코딩)                │
│  - IMU 방위각, 열화상 온도(최고/평균), 거리 센서, 유독가스    │
└──────────────────────────────┬───────────────────────────────┘
                               │ HTTP POST /api/v1/missions/{id}/telemetry/raw
                               │ (유선 LAN / 1~2Hz 주기 전송)
                               ▼
┌──────────────────────────────────────────────────────────────┐
│ [백엔드 서버 (Server)]                                       │
│                                                              │
│  [Step 1. 원시 JSON 선(先) 저장]                             │
│   └─► DB `raw_telemetry_logs`에 원본 JSON 통째로 즉시 INSERT │
│                                                              │
│  [Step 2. 서버 비동기 데이터 가공 & AI 상황 판단]            │
│   ├─► 1Hz 정제/다운샘플링 ──► `sensor_logs` (이동 궤적)      │
│   └─► Gemma 3 4B 멀티모달 추론 (계측값 + 영상 스냅샷)        │
│        ──► `ai_assessments` (위험등급, 현장요약, 전술권고)   │
│                                                              │
│  [Step 3. 실시간 지도 앱 브로드캐스팅]                      │
│   └─► WebSocket `/ws/missions/{id}/dashboard`                │
└──────────────────────────────┬───────────────────────────────┘
                               │
            ┌──────────────────┴──────────────────┐
            │ REST API (초기 로딩)                │ WebSocket (실시간 스트림)
            ▼                                     ▼
┌──────────────────────────────────────────────────────────────┐
│ [통제실 모바일 지도 앱 (Mobile Map App)] (Android / iOS)     │
│  - GIS 실외 건물 핀 & 2D 실내 층별 평면도(Floor Plan) 오버레이│
│  - 실시간 대원 위치 마커 이동 & 이동 궤적(Polyline) 렌더링   │
│  - AI 전술 상황 판단 POI 마커(화재/인명/장애물) & 팝업 카드  │
└──────────────────────────────────────────────────────────────┘
```

---

## 2. 컴포넌트별 기술 스택 및 역할 정의

| 컴포넌트 | 확정 기술 스택 | 주요 역할 |
| :--- | :--- | :--- |
| **현장 엣지 보드** | **Python** (OpenCV, 센서 드라이버) | 복잡한 AI 배제. 센서 수집 및 영상 스냅샷을 묶어 서버로 원시 JSON 단순 송신 |
| **백엔드 서버** | **Python (FastAPI + SQLAlchemy + Uvicorn)** | 원시 JSON 무유실 선저장, 센서 데이터 1Hz 정제, REST API 및 WebSocket 브로드캐스트 |
| **상황 판단 AI** | **Gemma 3 4B (Multimodal VLM)** | 실 계측값(온도, 거리, 가스, IMU) + 카메라 영상을 종합 분석하여 정형화된 JSON 상황 판단 도출 |
| **데이터베이스** | **MariaDB (v10.x 이상)** | 원시 JSON 로그, AI 상황 판단 결과, 대원 궤적, 2D/3D 지도 도면 및 메타데이터 영속화 |
| **통제실 지도 앱** | **Android / Multiplatform (Map App)** | 층별 2D 도면 표출, 실시간 위치/궤적 렌더링, AI 위험 경보 마커 및 브리핑 표출 |

---

## 3. MariaDB 데이터베이스 상세 설계 (DDL 명세)

```sql
-- 1. 소방/군 공무원 사용자 테이블
CREATE TABLE users (
    user_id INT AUTO_INCREMENT PRIMARY KEY,
    service_number VARCHAR(50) NOT NULL UNIQUE,  -- 소방공무원 식별번호/군번 (예: "FIRE-CMD-101")
    full_name VARCHAR(50) NOT NULL,               -- 성명
    rank VARCHAR(30) NOT NULL,                    -- 계급 (소방위, 소방경, 소방령 등)
    department VARCHAR(100) NOT NULL,             -- 소속 (예: "서울종로소방서 현장대응단")
    role ENUM('ADMIN', 'COMMANDER', 'OPERATOR') NOT NULL DEFAULT 'OPERATOR',
    security_clearance INT DEFAULT 2,             -- 보안인가등급 (1: 관리자, 2: 지휘관, 3: 대원)
    pin_hash VARCHAR(255) NOT NULL,               -- 공무원증 보안 PIN 해시
    is_active BOOLEAN DEFAULT TRUE,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 2. 인가된 현장 전용 단말기 테이블 (MDM)
CREATE TABLE authorized_terminals (
    terminal_id VARCHAR(100) PRIMARY KEY,        -- 태블릿 기기 식별자 (UUID/MAC)
    terminal_name VARCHAR(100) NOT NULL,         -- 단말기 명칭 (예: "현장지휘 전용 태블릿 1호")
    is_active BOOLEAN DEFAULT TRUE,              -- 원격 차단(킬스위치)
    registered_at DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 3. 엣지 디바이스 테이블
CREATE TABLE devices (
    device_id VARCHAR(50) PRIMARY KEY,           -- 엣지 장비 ID (예: "EDGE-CAM-01")
    device_name VARCHAR(100) NOT NULL,
    api_key VARCHAR(128) NOT NULL,
    status ENUM('ONLINE', 'OFFLINE') DEFAULT 'OFFLINE',
    last_heartbeat DATETIME NULL,
    registered_at DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 4. 건물 정보 테이블 (지도 앱 연동 GPS 좌표 포함)
CREATE TABLE buildings (
    building_id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    address VARCHAR(255) NOT NULL,
    floors_count INT NOT NULL DEFAULT 1,
    description TEXT,
    latitude FLOAT NULL,                         -- 건물 실외 GPS 위도 (지도 앱 핀 표출용)
    longitude FLOAT NULL,                        -- 건물 실외 GPS 경도 (지도 앱 핀 표출용)
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 5. 공간지도 및 2D 층별 평면도 테이블 (모바일 지도 앱 오버레이용)
CREATE TABLE spatial_maps (
    map_id INT AUTO_INCREMENT PRIMARY KEY,
    building_id INT NOT NULL,
    floor INT NOT NULL DEFAULT 1,                -- 건물 층수 (1, 2, -1 등)
    file_path VARCHAR(255) NULL,                 -- 3D .glb 파일 상대경로 (선택)
    floor_plan_image VARCHAR(255) NULL,          -- 모바일 지도 앱용 2D 평면도 이미지 경로 (PNG/SVG)
    width_meter FLOAT NULL,                      -- 도면 실제 가로 길이 (m)
    height_meter FLOAT NULL,                     -- 도면 실제 세로 길이 (m)
    scale_factor FLOAT DEFAULT 1.0,
    origin_x FLOAT DEFAULT 0.0,
    origin_y FLOAT DEFAULT 0.0,
    origin_z FLOAT DEFAULT 0.0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (building_id) REFERENCES buildings(building_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 6. 출동 작전 세션 테이블
CREATE TABLE missions (
    mission_id INT AUTO_INCREMENT PRIMARY KEY,
    building_id INT NOT NULL,
    device_id VARCHAR(50) NOT NULL,
    commander_id INT NOT NULL,
    title VARCHAR(150) NOT NULL,
    start_time DATETIME DEFAULT CURRENT_TIMESTAMP,
    end_time DATETIME NULL,
    status ENUM('ACTIVE', 'COMPLETED', 'CANCELLED') DEFAULT 'ACTIVE',
    FOREIGN KEY (building_id) REFERENCES buildings(building_id),
    FOREIGN KEY (device_id) REFERENCES devices(device_id),
    FOREIGN KEY (commander_id) REFERENCES users(user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 7. [핵심] 원시 계측 JSON 우선 영속화 테이블 (Save-First Raw Ingest)
CREATE TABLE raw_telemetry_logs (
    log_id BIGINT AUTO_INCREMENT PRIMARY KEY,
    mission_id INT NOT NULL,
    device_id VARCHAR(50) NOT NULL,
    timestamp BIGINT NOT NULL,                   -- 계측 시점 Unix Epoch (ms)
    raw_payload JSON NOT NULL,                   -- 엣지가 전송한 원본 JSON 전체 그대로 저장
    snapshot_path VARCHAR(255) NULL,             -- 저장된 스냅샷 이미지 파일 경로
    is_processed BOOLEAN DEFAULT FALSE,          -- 서버 가공/AI 분석 완료 여부
    processed_at DATETIME NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (mission_id) REFERENCES missions(mission_id) ON DELETE CASCADE,
    FOREIGN KEY (device_id) REFERENCES devices(device_id),
    INDEX idx_raw_mission_time (mission_id, timestamp),
    INDEX idx_raw_processed (is_processed)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 8. [핵심] Gemma 3 4B 전술 상황 판단 결과 테이블 (지도 앱 POI 마커 매핑)
CREATE TABLE ai_assessments (
    assessment_id BIGINT AUTO_INCREMENT PRIMARY KEY,
    mission_id INT NOT NULL,
    device_id VARCHAR(50) NOT NULL,
    raw_log_id BIGINT NULL,                      -- 원본 원시 로그 매핑 FK
    timestamp BIGINT NOT NULL,                   -- 판단 시점 Unix Epoch (ms)
    hazard_level ENUM('CRITICAL', 'WARNING', 'NORMAL', 'UNKNOWN') NOT NULL,
    situation_summary TEXT NOT NULL,             -- 현장 상황 요약
    human_detected BOOLEAN DEFAULT FALSE,        -- 인명 발견 여부
    human_status VARCHAR(100) NULL,              -- 발견된 인명 상태
    action_recommendation TEXT NULL,             -- 대원 행동 권고
    poi_type ENUM('FIRE_HOTSPOT', 'PERSON_RESCUE', 'OBSTACLE_HAZARD', 'SAFE_PATH') NULL,
    coord_x FLOAT NULL,                          -- 지도 x좌표 (m)
    coord_y FLOAT NULL,                          -- 지도 y좌표 (m)
    coord_z FLOAT NULL,                          -- 지도 z좌표 (m)
    assessment_json JSON NOT NULL,               -- Gemma 3 4B 원본 JSON 결과
    snapshot_path VARCHAR(255) NULL,             -- 분석에 사용된 이미지 경로
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (mission_id) REFERENCES missions(mission_id) ON DELETE CASCADE,
    FOREIGN KEY (device_id) REFERENCES devices(device_id),
    FOREIGN KEY (raw_log_id) REFERENCES raw_telemetry_logs(log_id) ON DELETE SET NULL,
    INDEX idx_ai_mission_time (mission_id, timestamp),
    INDEX idx_ai_hazard_level (hazard_level)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 9. 정제된 센서 시계열 및 이동 궤적 로그 테이블 (1Hz 다운샘플링, Polyline용)
CREATE TABLE sensor_logs (
    log_id BIGINT AUTO_INCREMENT PRIMARY KEY,
    mission_id INT NOT NULL,
    device_id VARCHAR(50) NOT NULL,
    timestamp BIGINT NOT NULL,                   -- 계측 시점 Unix Epoch (ms)
    pos_x FLOAT NOT NULL,                        -- 지도 x좌표 (m)
    pos_y FLOAT NOT NULL,                        -- 지도 y좌표 (m)
    pos_z FLOAT NOT NULL,                        -- 지도 z좌표 (m)
    imu_yaw FLOAT NULL,                          -- 방위각 (0~360도)
    ambient_temp FLOAT NULL,                     -- 주변 온도
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (mission_id) REFERENCES missions(mission_id) ON DELETE CASCADE,
    INDEX idx_mission_time (mission_id, timestamp)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 10. 이상 이벤트 로그 테이블 (하위 호환용)
CREATE TABLE detection_events (
    event_id BIGINT AUTO_INCREMENT PRIMARY KEY,
    mission_id INT NOT NULL,
    device_id VARCHAR(50) NOT NULL,
    timestamp BIGINT NOT NULL,
    event_type ENUM('PERSON', 'FIRE', 'HAZARD') NOT NULL,
    confidence FLOAT NULL,
    coord_x FLOAT NOT NULL,
    coord_y FLOAT NOT NULL,
    coord_z FLOAT NOT NULL,
    max_temperature FLOAT NULL,
    snapshot_path VARCHAR(255) NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (mission_id) REFERENCES missions(mission_id) ON DELETE CASCADE,
    INDEX idx_detection_mission_time (mission_id, timestamp)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

---

## 4. [전달용] 데이터 입출력(I/O) 상세 인터페이스 명세서

> 아래 명세는 **모바일 지도 앱 개발팀** 및 **현장 엣지/AI 연동 엔지니어**에게 그대로 공유하여 개발을 진행할 수 있는 공식 규격입니다.

### 4.1 [입력 명세] 현장 엣지 보드 $\rightarrow$ 백엔드 서버
- **Method**: `POST`
- **URL**: `/api/v1/missions/{mission_id}/telemetry/raw`
- **전송 주기**: 1~2Hz (초당 1~2회)
- **요청 헤더**:
  ```http
  Content-Type: application/json
  X-Device-Id: EDGE-CAM-01
  X-Device-Key: rescue-edge-secret-key-01
  ```
- **요청 본문 (Request Body JSON)**:
  ```json
  {
    "timestamp": 1728028800000,
    "device_id": "EDGE-CAM-01",
    "location": {
      "x": 4.5,
      "y": 2.1,
      "z": 0.0
    },
    "imu": {
      "pitch": 0.5,
      "roll": -0.2,
      "yaw": 45.0
    },
    "temperature": {
      "max": 78.5,
      "avg": 28.5,
      "hotspots": [
        { "x": 120.0, "y": 80.0, "temp": 78.5 }
      ]
    },
    "distance_sensor_m": 1.2,
    "gas_co_ppm": 120.0,
    "snapshot_base64": "/9j/4AAQSkZJRgABAQEASABIAAD/...",
    "extra_sensors": {
      "battery_pct": 92
    }
  }
  ```
- **응답 본문 (Response Body JSON)**:
  ```json
  {
    "status": "SAVED_AND_ASSESSED",
    "mission_id": 1,
    "timestamp": 1728028800000,
    "assessment_id": 105,
    "hazard_level": "CRITICAL"
  }
  ```

---

### 4.2 [AI 추론 명세] Gemma 3 4B 멀티모달 상황 판단 규격
서버는 엣지로부터 수신된 `실 계측값`과 `영상 스냅샷`을 Gemma 3 4B에 전달하고, 모델은 아래 정형화된 JSON 포맷으로 상황 판단을 출력합니다:

```json
{
  "hazard_level": "CRITICAL",
  "situation_summary": "전방 고온 발화 위험 감지 (최고온도 78.5℃, CO 120ppm). 플래시오버 발생 우려 높음.",
  "human_detected": false,
  "human_status": null,
  "action_recommendation": "대원 즉시 살수 방수 실시 및 안전거리 5m 이상 확보 후 후퇴 권고.",
  "poi_type": "FIRE_HOTSPOT",
  "confidence": 0.94
}
```

---

### 4.3 [출력 명세: REST API] 백엔드 서버 $\rightarrow$ 모바일 지도 앱

#### (1) 건물 상세 및 2D 층별 평면도 정보 조회
- **Method**: `GET`
- **URL**: `/api/v1/buildings/{building_id}`
- **설명**: 모바일 지도 앱이 건물의 GPS 좌표 및 층별 2D 도면 이미지 URL과 크기(m)를 로딩합니다.
- **응답 예시 (200 OK)**:
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
        "height_meter": 20.0,
        "scale_factor": 1.0,
        "origin_x": 0.0,
        "origin_y": 0.0,
        "origin_z": 0.0
      }
    ]
  }
  ```

#### (2) 작전 지도 초기 전체 상태 조회 (초기 로딩용)
- **Method**: `GET`
- **URL**: `/api/v1/missions/{mission_id}/map-state`
- **설명**: 지도 앱 진입 시 대원의 최신 위치, 지나온 이동 경로(Polyline), 지도 위에 띄워야 할 위험/인명 POI 마커 목록을 한 번에 조회합니다.
- **응답 예시 (200 OK)**:
  ```json
  {
    "mission_id": 1,
    "title": "A동 모의화재 진압 및 인명구조 작전",
    "status": "ACTIVE",
    "building_id": 1,
    "device_id": "EDGE-CAM-01",
    "current_location": { "x": 8.2, "y": 4.1, "z": 0.0 },
    "current_yaw": 45.0,
    "trajectory": [
      { "x": 2.0, "y": 1.0, "z": 0.0 },
      { "x": 4.5, "y": 2.1, "z": 0.0 },
      { "x": 8.2, "y": 4.1, "z": 0.0 }
    ],
    "active_markers": [
      {
        "type": "AI_MARKER_ALERT",
        "mission_id": 1,
        "assessment_id": 105,
        "timestamp": 1728028800000,
        "hazard_level": "CRITICAL",
        "poi_type": "FIRE_HOTSPOT",
        "title": "[CRITICAL] 🔥 화재 위험",
        "summary": "전방 고온 발화 위험 감지 (최고온도 78.5℃)",
        "action_recommendation": "즉시 살수 방수 실시 및 후퇴 권고",
        "coord": { "x": 8.2, "y": 4.1, "z": 0.0 },
        "snapshot_url": "/static/snapshots/snapshot_m1_1728028800000.jpg"
      }
    ]
  }
  ```

#### (3) AI 상황 판단 타임라인 이력 조회
- **Method**: `GET`
- **URL**: `/api/v1/missions/{mission_id}/ai-assessments?limit=50`
- **응답 예시 (200 OK)**:
  ```json
  [
    {
      "assessment_id": 105,
      "mission_id": 1,
      "device_id": "EDGE-CAM-01",
      "timestamp": 1728028800000,
      "hazard_level": "CRITICAL",
      "situation_summary": "전방 고온 발화 위험 감지 (최고온도 78.5℃)",
      "human_detected": false,
      "human_status": null,
      "action_recommendation": "즉시 살수 방수 실시 및 후퇴 권고",
      "poi_type": "FIRE_HOTSPOT",
      "coord_x": 8.2,
      "coord_y": 4.1,
      "coord_z": 0.0,
      "snapshot_url": "/static/snapshots/snapshot_m1_1728028800000.jpg",
      "created_at": "2026-10-04T16:30:00"
    }
  ]
  ```

---

### 4.4 [출력 명세: WebSocket] 백엔드 서버 $\rightarrow$ 모바일 지도 앱 실시간 스트림

- **연결 URL**: `ws://<server-ip>:8000/ws/missions/{mission_id}/dashboard?token=<JWT_TOKEN>`
- **연결 성공 시 수신 메시지**:
  ```json
  {
    "type": "CONNECTION_ESTABLISHED",
    "mission_id": 1,
    "officer": "이지휘",
    "role": "COMMANDER",
    "message": "작전 #1 실시간 전술 채널에 정상 연결되었습니다."
  }
  ```

#### (1) 대원 실시간 위치 이동 이벤트 (`LOCATION_UPDATE`)
- **전송 주기**: 약 1초 주기
- **용도**: 지도 위 대원 핀 아이콘 위치 이동 및 방향 화살표(Yaw) 회전
- **메시지 규격**:
  ```json
  {
    "type": "LOCATION_UPDATE",
    "mission_id": 1,
    "device_id": "EDGE-CAM-01",
    "timestamp": 1728028801000,
    "x": 8.5,
    "y": 4.3,
    "z": 0.0,
    "yaw": 52.0,
    "max_temperature": 78.5
  }
  ```

#### (2) AI 긴급 경보 & POI 마커 팝업 이벤트 (`AI_MARKER_ALERT`)
- **전송 조건**: Gemma 3 4B 판단 결과가 `CRITICAL`, `WARNING`이거나 `인명(human_detected=true)` 발견 시 즉시 전송
- **용도**: 지도 위에 위험 아이콘(불꽃, 구조자 마커) 핀 생성 및 진동/팝업 카드 표시
- **메시지 규격**:
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
      "x": 8.5,
      "y": 4.3,
      "z": 0.0
    },
    "snapshot_url": "/static/snapshots/snapshot_m1_1728028801000.jpg"
  }
  ```

---

## 5. 단계별 테스트 및 시뮬레이션 가이드

1. **DB 초기화 및 테이블 생성**:
   ```bash
   python app/scripts/init_db.py
   ```
2. **백엔드 서버 구동**:
   ```bash
   uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
   ```
3. **모의 엣지 원시 JSON 패킷 전송 시뮬레이션**:
   ```bash
   python app/scripts/mock_edge_sender.py 1
   ```
4. **지도 앱 데이터 수신 테스트**:
   - `GET http://localhost:8000/api/v1/missions/1/map-state`
   - WebSocket 클라이언트로 `ws://localhost:8000/ws/missions/1/dashboard?token=<JWT>` 연결 후 실시간 마커 및 위치 수신 확인
