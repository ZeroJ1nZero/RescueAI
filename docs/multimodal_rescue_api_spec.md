# 연암소방대 AI 멀티모달 전술 관제 및 객체 인터랙션 시스템 데이터 인터페이스 명세서

> **문서 버전**: v1.0 (Standard Specification)  
> **시스템 명칭**: 연암소방대 AI 전술 관제 및 모바일 지도 시스템 (Yeonam Fire AI Tactical System)  
> **대상 독자**: 엣지 AI 하드웨어 개발팀, 모바일/태블릿 지도 앱 개발팀, AI 모델 및 백엔드 엔지니어  
> **시스템 목적**: 현장 AI 보드에서 수집한 멀티모달(센서 계측 JSON, 현장 스냅샷 이미지, 전술 동영상) 데이터를 실시간 융합·정제하고, 통제실 모바일 지도 앱을 통해 2D 좌표평면 및 현장 이미지 상에서 구조 대상자 선별, 위험도 평가, 객체 선택 인터랙션을 제공하는 통합 전술 관제 시스템

---

## 1. 시스템 아키텍처 및 데이터 흐름도

연암소방대 AI는 현장 엣지 보드, 백엔드 분석 서버(Gemma 3 4B AI 참모), 통제실 모바일 지도 앱 간의 유기적인 데이터 파이프라인으로 구성됩니다.

```
┌────────────────────────────────────────────────────────┐
│ [1. 현장 AI 엣지 보드] (Edge Hardware & Sensors)       │
│  - 📡 센서 계측: 위치(x,y,z), 방위각(Yaw), 온도, 거리, 가스│
│  - 📷 카메라 센서: 고화질 스냅샷 이미지 + 3~5초 전술 비디오 │
│  - 🧠 엣지 1차 전처리: 객체 탐지 바운딩 박스(BBox), 라벨 추출 │
└───────────────────────────┬────────────────────────────┘
                            │ HTTP POST /telemetry/multimodal (Multipart, 1Hz)
                            ▼
┌────────────────────────────────────────────────────────┐
│ [2. 백엔드 서버 & Gemma 3 4B AI 엔진] (Server Engine)  │
│  - [Step 1] 원시 데이터 영속화: 계측 JSON 선저장 & 미디어 보관│
│  - [Step 2] 1Hz 센서 정제: 대원 이동 궤적 시계열 데이터 추출 │
│  - [Step 3] Gemma 3 4B 멀티모달 융합 분석:             │
│      · 구조 대상자(체온 36.5℃ + 인명) 자동 선별 및 분류 │
│      · 발화 화점, 붕괴물 등 위험도(CRITICAL/WARNING) 판정│
│      · 이미지 BBox(픽셀 좌표) ⟷ 실내 좌표평면(x,y,z) 매핑│
└──────────────┬──────────────────────────┬──────────────┘
               │ REST API (초기 로딩)     │ WebSocket (실시간 스트림)
               ▼                          ▼
┌────────────────────────────────────────────────────────┐
│ [3. 통제실 모바일 지도 앱] (Mobile Map App)            │
│  - 🗺️ 2D 실내 평면도 좌표평면: 대원 핀/궤적 & 구조 대상자 핀 │
│  - 🖼️ 현장 이미지 뷰: 탐지 객체 인터랙티브 BBox 오버레이  │
│  - 👆 객체 선택 인터랙션: 물체 탭 시 위치·위험도 팝업 표출│
└────────────────────────────────────────────────────────┘
```

---

## 2. 공통 인증 규격 (Authentication)

### 2.1 엣지 AI 보드 인증 (Edge Auth)
엣지 보드는 서버와 통신 시 등록된 장치 식별자와 보안 API 키를 HTTP 헤더에 포함합니다.
* **헤더 규격**:
  ```http
  X-Device-Id: EDGE-CAM-01
  X-Device-Key: rescue-edge-secret-key-01
  ```

### 2.2 모바일 지도 앱 인증 (Mobile App Auth)
지휘관 및 구조대원은 로그인 후 발급받은 JWT 보안 토큰을 사용하여 인가된 권한으로 통신합니다.
* **REST API 헤더**: `Authorization: Bearer <JWT_ACCESS_TOKEN>`
* **WebSocket 연결**: `ws://<server-ip>:8000/ws/missions/{mission_id}/dashboard?token=<JWT>`

---

## 3. [엣지 $\rightarrow$ 서버] 멀티모달 텔레메트리 인입 API

현장 엣지 보드에서 수집한 센서 수치 JSON, 1차 전처리된 객체 탐지 목록, 현장 스냅샷 이미지, 전술 동영상 클립을 단일 트랜잭션으로 통합 전송합니다.

* **Method**: `POST`
* **URL**: `http://<server-ip>:8000/api/v1/missions/{mission_id}/telemetry/multimodal`
* **Content-Type**: `multipart/form-data`
* **전송 주기 권장**: 1Hz (초당 1회) 또는 주요 이벤트 감지 시

### 3.1 요청 파라미터 규격 (Multipart Form)

| 파라미터명 | 타입 | 필수 여부 | 설명 | 예시 |
| :--- | :--- | :---: | :--- | :--- |
| `payload` | `string (JSON)` | **필수** | 계측 센서 및 1차 객체 탐지 JSON | 아래 3.2 참조 |
| `image` | `UploadFile` | 선택 | 현장 고화질 RGB/열화상 스냅샷 | `snapshot_01.jpg` |
| `video` | `UploadFile` | 선택 | 현장 3~5초 전술 동영상 클립 | `clip_01.mp4` |

### 3.2 `payload` JSON 상세 구조
```json
{
  "timestamp": 1728028800000,
  "device_id": "EDGE-CAM-01",
  "location": {
    "x": 8.5,
    "y": 4.0,
    "z": 0.0
  },
  "imu": {
    "yaw": 75.0,
    "pitch": 0.5,
    "roll": -0.2
  },
  "temperature": {
    "max": 38.5,
    "avg": 27.0,
    "hotspots": [
      { "x": 160.0, "y": 110.0, "temp": 36.8 }
    ]
  },
  "distance_sensor_m": 1.1,
  "gas_co_ppm": 45.0,
  "edge_detections": [
    {
      "detection_id": "det_edge_001",
      "class_name": "PERSON",
      "confidence": 0.93,
      "bbox": [120, 80, 240, 210],
      "thermal_temp": 36.8,
      "estimated_rel_coord": { "x": 0.5, "y": 0.9, "z": 0.0 }
    },
    {
      "detection_id": "det_edge_002",
      "class_name": "FIRE",
      "confidence": 0.88,
      "bbox": [310, 40, 420, 160],
      "thermal_temp": 78.5,
      "estimated_rel_coord": { "x": 1.8, "y": 2.2, "z": 0.0 }
    }
  ],
  "extra_sensors": {
    "battery_pct": 92
  }
}
```

---

## 4. [서버 $\rightarrow$ 지도 앱] 실내 지도 및 공간 통신 API

모바일 지도 앱이 건물 내부 진입 시 층별 2D 평면도 도면과 실측 스케일 메타데이터를 수신하여 좌표평면을 초기화합니다.

### 4.1 건물 층별 2D 평면도 및 메타데이터 조회
* **Method**: `GET`
* **URL**: `/api/v1/buildings/{building_id}/floors/{floor}/map`
* **응답 규격 (JSON)**:
```json
{
  "building_id": 1,
  "building_name": "소방방재 테스트빌딩 A동",
  "floor": 1,
  "floor_plan_image_url": "/static/maps/floorplans/building_1_floor_1_2d.png",
  "spatial_3d_file_url": "/static/maps/building_1_floor_1.glb",
  "width_meter": 30.0,
  "height_meter": 20.0,
  "origin_offset": {
    "x": 0.0,
    "y": 0.0,
    "z": 0.0
  },
  "meter_to_pixel_ratio": 33.33
}
```

### 4.2 작전 지도 전체 상태 일괄 조회 (초기 로딩용)
* **Method**: `GET`
* **URL**: `/api/v1/missions/{mission_id}/map-state`
* **응답 규격 (JSON)**:
```json
{
  "mission_id": 1,
  "title": "A동 1층 인명구조 및 화재진압 작전",
  "status": "ACTIVE",
  "building_id": 1,
  "device_id": "EDGE-CAM-01",
  "current_location": { "x": 8.5, "y": 4.0, "z": 0.0 },
  "current_yaw": 75.0,
  "trajectory": [
    { "x": 2.0, "y": 1.0, "z": 0.0 },
    { "x": 4.5, "y": 2.0, "z": 0.0 },
    { "x": 8.5, "y": 4.0, "z": 0.0 }
  ],
  "active_markers": [
    {
      "mission_id": 1,
      "assessment_id": 101,
      "timestamp": 1728028800000,
      "hazard_level": "WARNING",
      "poi_type": "PERSON_RESCUE",
      "title": "[WARNING] 🚨 구조 대상자 발견",
      "summary": "침실 모퉁이 부근 36.8℃ 생체 체온 핫스팟 감지. 의식 저하 추정.",
      "action_recommendation": "구조팀 즉시 들것 및 보조 호흡마스크 휴대 진입 요망.",
      "coord": { "x": 8.5, "y": 4.0, "z": 0.0 },
      "snapshot_url": "/static/snapshots/snapshot_m1_1728028800000.jpg"
    }
  ]
}
```

---

## 5. [서버 $\rightarrow$ 지도 앱] AI 구조 대상자 선별 및 인터랙티브 객체 API

### 5.1 AI 선별 구조 대상자(Victims) 전용 목록 조회
Gemma 3 4B 멀티모달 모델이 계측 체온(34~38℃ 생체 열원), 영상 속 인명 형태, 유독가스 수치를 융합 분석하여 선별·정리한 구조 대상자 목록을 반환합니다.

* **Method**: `GET`
* **URL**: `/api/v1/missions/{mission_id}/victims`
* **응답 규격 (JSON)**:
```json
{
  "mission_id": 1,
  "total_victims_count": 1,
  "victims": [
    {
      "victim_id": "VIC-101",
      "status": "의식 저하 및 호흡 미약 (연기 흡입 의심)",
      "urgency": "CRITICAL",
      "detected_time": 1728028809000,
      "thermal_temp": 36.8,
      "ambient_temp": 28.5,
      "gas_co_ppm": 45.0,
      "map_coordinate": {
        "x": 8.5,
        "y": 4.0,
        "z": 0.0,
        "floor": 1
      },
      "distance_from_rescuer_m": 1.1,
      "snapshot_url": "/static/snapshots/snapshot_m1_1728028809000.jpg",
      "video_clip_url": "/static/videos/clip_m1_1728028809000.mp4",
      "target_bbox_on_image": [120, 80, 240, 210],
      "gemma_action_recommendation": "구조팀 즉시 들것 및 보조 호흡마스크 휴대 진입 요망. 후송 경로(동측 비상구) 확보."
    }
  ]
}
```

### 5.2 현장 이미지 내 탐지 객체 목록 조회 (인터랙션용)
모바일 앱이 현장 사진 뷰어를 열었을 때 이미지 위에 오버레이할 모든 객체의 바운딩 박스와 위치/위험도 메타데이터를 반환합니다.

* **Method**: `GET`
* **URL**: `/api/v1/missions/{mission_id}/snapshots/{snapshot_id}/objects`
* **응답 규격 (JSON)**:
```json
{
  "snapshot_id": "snap_1728028809000",
  "snapshot_url": "/static/snapshots/snapshot_m1_1728028809000.jpg",
  "timestamp": 1728028809000,
  "image_resolution": {
    "width": 640,
    "height": 480
  },
  "objects": [
    {
      "object_id": "obj_01_person",
      "class_name": "PERSON_RESCUE",
      "label": "구조 대상자 (성인 1명)",
      "hazard_level": "WARNING",
      "bbox": [120, 80, 240, 210],
      "confidence": 0.94,
      "thermal_temp": 36.8,
      "coord_in_map": { "x": 8.5, "y": 4.0, "z": 0.0 },
      "detail_summary": "생체 체온 포착 (36.8℃), 바닥면 협착 상태",
      "action_recommendation": "즉각 산소 투여 및 후송 조치"
    },
    {
      "object_id": "obj_02_fire",
      "class_name": "FIRE_HOTSPOT",
      "label": "발화 화점 (싱크대 부근)",
      "hazard_level": "CRITICAL",
      "bbox": [310, 40, 420, 160],
      "confidence": 0.88,
      "thermal_temp": 78.5,
      "coord_in_map": { "x": 10.3, "y": 6.2, "z": 0.0 },
      "detail_summary": "급격한 열기 축적 (최고 78.5℃), 플래시오버 주의",
      "action_recommendation": "대원 안전거리 5m 확보 및 선제 방수"
    }
  ]
}
```

### 5.3 특정 물체 상세 전술 정보 단건 조회
모바일 앱에서 사용자가 이미지 속 특정 물체(BBox) 또는 지도 핀을 탭했을 때 팝업 카드에 표시할 상세 정보를 반환합니다.

* **Method**: `GET`
* **URL**: `/api/v1/missions/{mission_id}/objects/{object_id}`
* **응답 규격 (JSON)**:
```json
{
  "object_id": "obj_01_person",
  "mission_id": 1,
  "class_name": "PERSON_RESCUE",
  "label": "구조 대상자 (성인 1명)",
  "hazard_level": "WARNING",
  "thermal_temp": 36.8,
  "coord_in_map": { "x": 8.5, "y": 4.0, "z": 0.0 },
  "distance_from_rescuer_m": 1.1,
  "detail_summary": "36.8℃ 생체 열원 감지, 연기 흡입으로 인한 의식 저하 유력",
  "action_recommendation": "구조팀 즉시 들것 및 산소 보조마스크 휴대 진입 요망",
  "snapshot_url": "/static/snapshots/snapshot_m1_1728028809000.jpg",
  "video_clip_url": "/static/videos/clip_m1_1728028809000.mp4"
}
```

---

## 6. [서버 $\rightarrow$ 지도 앱] 실시간 WebSocket 스트림 명세

* **연결 URL**: `ws://<server-ip>:8000/ws/missions/{mission_id}/dashboard?token=<JWT>`

### 6.1 구조 대상자 신규 식별 이벤트 (`VICTIM_IDENTIFIED`)
AI 모델이 새로운 구조 대상자를 감지 및 선별했을 때 즉시 지도 앱으로 푸시됩니다.

```json
{
  "type": "VICTIM_IDENTIFIED",
  "mission_id": 1,
  "timestamp": 1728028809000,
  "victim": {
    "victim_id": "VIC-101",
    "urgency": "CRITICAL",
    "status": "의식 저하 및 호흡 미약",
    "thermal_temp": 36.8,
    "coord": { "x": 8.5, "y": 4.0, "z": 0.0 },
    "snapshot_url": "/static/snapshots/snapshot_m1_1728028809000.jpg",
    "video_clip_url": "/static/videos/clip_m1_1728028809000.mp4",
    "bbox": [120, 80, 240, 210],
    "action_recommendation": "구조팀 즉시 들것 지참 진입 요망."
  }
}
```

### 6.2 대원 실시간 위치 갱신 이벤트 (`LOCATION_UPDATE`)
```json
{
  "type": "LOCATION_UPDATE",
  "mission_id": 1,
  "device_id": "EDGE-CAM-01",
  "timestamp": 1728028809000,
  "x": 8.5,
  "y": 4.0,
  "z": 0.0,
  "yaw": 75.0,
  "max_temperature": 38.5
}
```

---

## 7. 모바일 지도 앱 UI 및 인터랙션 시나리오

```
┌───────────────────────────────────────┬───────────────────────────────────────┐
│ [2D 실내 도면 좌표평면 뷰]             │ [현장 이미지 & 객체 인터랙션 뷰]      │
│                                       │                                       │
│   (0,20)┌──────────────────────┐      │   ┌───────────────────────────────┐   │
│         │        [101호]       │      │   │                               │   │
│         │                      │      │   │    ┌──────────┐               │   │
│         │    🚨(8.5, 4.0)       │      │   │    │ 🚨 구조자 │               │   │
│         │    구조 대상자 핀     │ 탭시 │   │    │ [VIC-101]│               │   │
│         │        ↑             │ 연동 │   │    └──────────┘  🔥 화재점    │   │
│         │   대원 🏃(7.0, 3.2)   │ ───► │   │                  ┌──────┐     │   │
│         │   (거리: 1.5m)       │ ◄─── │   │                  └──────┘     │   │
│         │                      │      │   │                               │   │
│    (0,0)└──────────────────────┘      │   └───────────────────────────────┘   │
│                                       │   * 이미지 속 BBox 탭 시 상세 팝업     │
└───────────────────────────────────────┴───────────────────────────────────────┘
```

1. **상호 하이라이트 (Bi-directional Highlighting)**
   * 좌표평면 상에서 **🚨 구조 대상자 핀**을 터치하면 우측 이미지 뷰에서 해당 대상자의 **바운딩 박스가 강조(하이라이트)**됩니다.
   * 우측 이미지 뷰에서 **특정 객체(BBox)**를 터치하면 좌측 좌표평면에서 해당 물체의 위치(x, y) 핀이 포커싱되며 상세 전술 카드가 팝업됩니다.
2. **현장 동영상 스트리밍 연동**
   * 팝업 카드 내 "현장 3초 영상 확인" 버튼 클릭 시 `video_clip_url`을 인라인 플레이어로 즉시 스트리밍 재생합니다.
