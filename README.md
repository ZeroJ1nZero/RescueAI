# 🚒 RescueAI - 영상 객체 분석 및 실내 공간지도 기반 소방 관제 시스템

> **영상 객체 분석에서 실내 공간지도 기반 관제까지 (연암소방대)**  
> 본 프로젝트는 화재·재난 현장에서 수집된 영상 프레임(Gemma 3 4B VLM 객체·맥락 분석) 및 센서 데이터를 구조화하여, 실내 공간지도 위에 실시간으로 시각화하고 작전 의사결정을 지원하는 **백엔드 서버 및 데이터 파이프라인 시스템**입니다.

---

## 👥 1. 팀원 구성 및 파트별 연동 가이드

GitHub 저장소를 클론한 후, 본인의 담당 파트에 맞는 섹션과 문서를 바로 확인하실 수 있습니다.

| 이름 | 담당 파트 | 주요 역할 | 필독 가이드 |
| :--- | :--- | :--- | :--- |
| **공진영** | **Infra & Cloud** | 인프라 아키텍처 구조 설계 및 서버 파이프라인 구축 | [7. 설치 및 서버 실행](#-7-설치-및-서버-실행-가이드) |
| **신경준** | **Data Engineering** | 데이터 엔지니어링 및 다종 데이터 저장소 파이프라인 | [6.2 AI 보드/세션 데이터 수집 규격](#62-수집-계층-ai-보드--세션-데이터-입력-규격), [8. 테스트 방법](#-8-api-연동-테스트-방법-swagger-ui--테스트-스크립트) |
| **정세빈** | **Frontend & UI** | 어플리케이션 프론트엔드 디자인 및 공간지도 UI 설계 | [6.1 주요 API 엔드포인트](#61-restful-api-일람), [6.3 실시간 WebSocket](#63-관제-계층-실시간-websocket-api) |
| **이세이** | **Frontend & UI** | 어플리케이션 프론트엔드 연동 및 관제 인터페이스 구현 | [6.1 주요 API 엔드포인트](#61-restful-api-일람), [6.3 실시간 WebSocket](#63-관제-계층-실시간-websocket-api) |

> 📄 **상세 입출력(I/O) 명세서**: 더 자세한 요청/응답 JSON 필드 설명은 [`docs/data_interface_specification.md`](docs/data_interface_specification.md) 문서에서 확인하세요.

---

## 🛠️ 2. 기술 스택 및 구현 환경

| 분류 | 적용 기술 | 선정 이유 및 역할 |
| :--- | :--- | :--- |
| **백엔드 언어** | **Python (3.10+)** | AI/데이터 엔지니어링 파트와 데이터 모델(Pydantic) 규격 공유 용이 |
| **API 프레임워크** | **FastAPI** | 비동기 고성능 REST API 제공, WebSocket 기본 내장, Swagger UI(`/docs`) 자동화 |
| **ASGI 서버** | **Uvicorn** | 초저지연 비동기 이벤트 루프 핸들링 |
| **ORM (DB 연동)** | **SQLAlchemy 2.0** | 코드 퍼스트(Code-First) 구조, 정적 타입 힌트(`Mapped`, `mapped_column`) |
| **데이터베이스** | **MariaDB (v10.x+)** | Save-First 원시 JSON 선저장(`raw_telemetry_logs`) 및 정형 메타/이벤트 트랜잭션 관리 |
| **AI 분석 모델** | **Gemma 3 4B VLM** | 샘플링 프레임 기반 객체 탐지(`detected_objects`) 및 현장 위험도(Red/Orange/Yellow) 판단 |
| **보안 및 인증** | **MDM + bcrypt + JWT** | 단말 인가(`X-Terminal-Id`), 공무원 보안 PIN 단방향 암호화, 역할 기반 RBAC 통제 |

---

## 🏛️ 3. 3계층 파이프라인 아키텍처 (Save-First & Clean Architecture)

```
┌─────────────────────────────────────────────────────────────────┐
│ [Layer 01. 수집 계층 (Ingestion)]                                │
│  - 현장 AI 보드/카메라 촬영 → 외장 SSD 세션 이동 (또는 무선 전송)│
│  - MDM 인가 단말 검증 (X-Terminal-Id 헤더 대조)                 │
│  - Save-First 원칙: 유입된 원시 JSON 데이터를 최우선 영구 선저장│
└───────────────────────────────┬─────────────────────────────────┘
                                │ HTTP POST /telemetry/raw 또는 /telemetry/batch
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│ [Layer 02. 분석 계층 (Processing)]                               │
│  - 서버 호스트 Gemma 3 4B VLM 프레임 샘플링 & 멀티모달 추론     │
│  - 인명 후보(person), 장애물(chair 등), 화염(fire) 검출 구조화  │
│  - 화면 위치(screen_box) 및 센서 메타데이터 정합                │
└───────────────┬─────────────────────────────────┬───────────────┘
                │ REST API (사후 세션 정밀 조회)   │ WebSocket (실시간 이벤트 스트리밍)
                ▼                                 ▼
┌─────────────────────────────────────────────────────────────────┐
│ [Layer 03. 관제 계층 (Control API & Map-First UI)]               │
│  - 3단계 심층 보안 (단말 검증 → PIN bcrypt → RBAC 권한 통제)    │
│  - 시맨틱 컬러 규격(Red/Orange/Yellow/Green/Blue) 마커 표출     │
└─────────────────────────────────────────────────────────────────┘
```

---

## 🔐 4. 3단계 심층 보안 접근 통제 체계

1. **1단계: 사용자 식별 및 인가 단말 고유 검증 (MDM)**
   * 사전에 등록된 합법적 장치 식별 정보(`X-Terminal-Id` 헤더) 대조 및 비인가 데이터 차단
   * 기본 등록 단말기 ID: `TAB-HQ-001`, `TAB-RESCUE-002`, `EDGE-CAM-01`
2. **2단계: 현장용 간편 PIN 단방향 암호화(`bcrypt`) 검증**
   * 공무원 식별번호(`service_number`)와 6자리 보안 PIN 검증
3. **3단계: 역할 기반 RBAC 통제 (`ADMIN` / `COMMANDER` / `OPERATOR`)**
   * `ADMIN` (보안 1급): 시스템 계정 관리, 인가 단말기 등록/차단, 건물 도면 관리
   * `COMMANDER` (보안 2급): 현장 지휘관, 출동 작전(Mission) 개시 및 종료
   * `OPERATOR` (보안 3급): 현장 대원, 실시간 관제 지도 및 위험 마커 조회

---

## 🗄️ 5. 데이터베이스 핵심 테이블 구조 (10개 엔티티)

서버 초기화 스크립트(`init_db.py`) 실행 시 아래 테이블이 자동으로 생성됩니다:

| 테이블명 | 주요 컬럼 | 설명 |
| :--- | :--- | :--- |
| **`raw_telemetry_logs`** | `log_id`, `mission_id`, `device_id`, `timestamp`, `raw_payload`(JSON), `is_processed` | **[Save-First]** 수집 계층 원시 JSON 데이터 최우선 선저장 테이블 |
| **`ai_assessments`** | `assessment_id`, `mission_id`, `hazard_level`, `situation_summary`, `poi_type`, `coord_x,y,z`, `assessment_json` | **[Gemma 3 4B]** 프레임 객체 분석 결과 및 관제 지도 POI 마커 테이블 |
| **`detection_events`** | `event_id`, `mission_id`, `timestamp`, `event_type`, `coord_x,y,z` | 탐지된 개별 객체(`PERSON`, `FIRE`, `HAZARD`) 이벤트 로그 |
| **`sensor_logs`** | `log_id`, `mission_id`, `timestamp`, `pos_x,y,z`, `imu_yaw`, `ambient_temp` | 대원/카메라 이동 궤적 시계열 로그 |
| **`users`** | `user_id`, `service_number`, `full_name`, `rank`, `role`, `security_clearance`, `pin_hash` | 소방 공무원 계정 및 RBAC 권한 정보 |
| **`authorized_terminals`** | `terminal_id`, `terminal_name`, `is_active` | MDM 사전 인가 단말기 목록 (`X-Terminal-Id` 검증용) |
| **`devices`** | `device_id`, `device_name`, `api_key`, `status` | 현장 AI 보드 / 카메라 장치 정보 |
| **`buildings` / `spatial_maps`** | `building_id`, `name`, `floor`, `floor_plan_image`, `width_meter`, `height_meter` | 건물 메타데이터 및 실내 2D/3D 도면 정보 |
| **`missions`** | `mission_id`, `building_id`, `device_id`, `commander_id`, `title`, `status` | 작전 세션 관리 (`ACTIVE` / `COMPLETED`) |

---

## 📡 6. API 엔드포인트 및 데이터 포맷 명세

### 6.1 RESTful API 일람

| Method | Endpoint | 설명 | 필수 인증 헤더 |
| :--- | :--- | :--- | :--- |
| `POST` | `/api/v1/auth/login` | 3단계 보안 로그인 및 JWT 발급 | `X-Terminal-Id: TAB-HQ-001` |
| `GET` | `/api/v1/auth/terminal/check` | 단말기 MDM 인가 상태 점검 | `X-Terminal-Id: TAB-HQ-001` |
| `GET` | `/api/v1/buildings` | 건물 목록 및 층별 도면 메타데이터 조회 | `Authorization: Bearer <JWT>` |
| `POST` | `/api/v1/missions` | 신규 작전 세션 개시 (지휘관용) | `Authorization: Bearer <JWT>` |
| `GET` | `/api/v1/missions/active` | 현재 진행 중인(`ACTIVE`) 작전 목록 조회 | `Authorization: Bearer <JWT>` |
| `POST` | `/api/v1/missions/{id}/telemetry/raw` | **[수집 계층]** 단일 프레임 객체/센서 JSON 선저장 및 분석 | `X-Terminal-Id: TAB-HQ-001` |
| `POST` | `/api/v1/missions/{id}/telemetry/batch` | **[수집 계층]** 외장 SSD 세션 다중 프레임(JSON 배열) 일괄 등록 | `X-Terminal-Id: TAB-HQ-001` |
| `GET` | `/api/v1/missions/{id}/map-state` | **[관제 UI용]** 실내 지도 초기화 데이터(위치, 궤적, 위험 마커) 통합 조회 | `Authorization: Bearer <JWT>` |
| `GET` | `/api/v1/missions/{id}/ai-assessments` | **[관제 UI용]** Gemma 3 4B 프레임 분석 이력 타임라인 조회 | `Authorization: Bearer <JWT>` |
| `GET` | `/api/v1/missions/{id}/replay` | **[관제 UI용]** 사후 세션 궤적 및 탐지 이벤트 전체 조회 | `Authorization: Bearer <JWT>` |

---

### 6.2 [수집 계층] AI 보드 / 세션 데이터 입력 규격

AI 보드 또는 세션 분석 워커에서 서버로 데이터를 전송할 때 아래 헤더와 JSON 스키마를 사용합니다.

* **URL (단건)**: `POST http://<서버IP>:8000/api/v1/missions/{mission_id}/telemetry/raw`
* **URL (일괄 배열)**: `POST http://<서버IP>:8000/api/v1/missions/{mission_id}/telemetry/batch`
* **Headers**:
  ```http
  Content-Type: application/json
  X-Terminal-Id: TAB-HQ-001
  ```
  *(기존 `X-Device-Id: EDGE-CAM-01` / `X-Device-Key: rescue-edge-secret-key-01` 헤더 방식도 호환됩니다.)*

* **Request Body (JSON 추출 데이터 스키마)**:
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
  * **필드 구성**: 관측 절대시각(`timestamp`), 프레임 번호(`frame_id`), 객체 분류 라벨(`class`), 2D 화면 좌표계 바운딩 박스(`screen_box`: `[x1, y1, x2, y2]`), 상황 서술 텍스트(`description`)
  * 일괄 등록(`/telemetry/batch`) 호출 시에는 위 JSON 객체를 리스트(`[ {...}, {...} ]`)로 묶어서 전송합니다.

---

### 6.3 [관제 계층] 실시간 WebSocket API

* **연결 URL**: `ws://<서버IP>:8000/ws/missions/{mission_id}/dashboard?token=<JWT_TOKEN>`
* **수신 이벤트**:
  * `LOCATION_UPDATE`: 대원/카메라 위치 갱신 (`x`, `y`, `z`, `frame_id`, `yaw`)
  * `AI_MARKER_ALERT`: 구조 대상(`PERSON_RESCUE`), 화점(`FIRE_HOTSPOT`), 통행 장애물(`OBSTACLE_HAZARD`) 탐지 시 실시간 마커 및 상세 설명 전송

---

## 🚀 7. 서버 동작을 위한 사전 준비 및 실행 가이드 (Getting Started)

GitHub 저장소를 클론(`git clone`)한 후, 로컬 PC에서 백엔드 서버를 구동하고 확인하기 위한 **필수 기반 환경(Prerequisites)**과 단계별 실행 방법입니다.

### 7.0 필수 기반 프로그램 (Prerequisites)
서버를 구동하기 위해 아래 두 가지가 설치되어 있어야 합니다:
1. **Python 3.10 이상** ([python.org](https://www.python.org/downloads/)에서 설치, 설치 시 `Add Python to PATH` 체크 필수)
2. **MariaDB (10.x 이상) 또는 MySQL Server (8.0 이상)**
   * **방법 A (로컬 설치)**: [MariaDB 다운로드](https://mariadb.org/download/)에서 설치 (기본 포트 `3306`, 설치 시 설정한 `root` 비밀번호 기억)
   * **방법 B (Docker 사용 시 - 설치 없이 1줄 실행)**:
     ```bash
     docker run -d --name rescue-mariadb -p 3306:3306 -e MYSQL_ROOT_PASSWORD=1234 mariadb:10.11
     ```

---

### 7.1 저장소 클론 및 파이썬 가상환경(venv) 패키지 설치
터미널(PowerShell 또는 명령 프롬프트)을 열고 프로젝트 폴더에서 아래 명령어를 순서대로 실행합니다:

```bash
# 1. 가상환경 생성 (최초 1회)
python -m venv .venv

# 2. 가상환경 활성화
# [Windows PowerShell]
.\.venv\Scripts\Activate.ps1
# [Windows CMD]
.\.venv\Scripts\activate.bat
# [Mac / Linux]
source .venv/bin/activate

# 3. 필수 라이브러리 일괄 설치 (FastAPI, SQLAlchemy, PyMySQL, Requests 등)
pip install -r requirements.txt
```

---

### 7.2 환경변수 파일(`.env`) 생성 및 DB 비밀번호 설정
보안을 위해 `.env` 파일은 GitHub에 올라가지 않으므로, 함께 제공되는 `.env.example` 파일을 복사하여 `.env` 파일을 만듭니다:

```bash
# [Windows PowerShell / CMD]
copy .env.example .env

# [Mac / Linux]
cp .env.example .env
```
생성된 `.env` 파일을 열어 본인의 MariaDB(또는 MySQL) `root` 비밀번호를 입력합니다:
```env
DB_HOST=127.0.0.1
DB_PORT=3306
DB_USER=root
DB_PASSWORD=본인_DB_비밀번호_입력
DB_NAME=rescue_ai
```
*(참고: `rescue_ai` 데이터베이스(스키마)를 직접 만들지 않아도 다음 단계의 초기화 스크립트가 자동으로 생성해 줍니다.)*

---

### 7.3 DB 테이블 및 기본 시드 데이터 자동 생성 (최초 1회)
MariaDB 서버가 켜져 있는 상태에서 아래 명령어를 실행하면 `rescue_ai` DB와 10개 테이블, 기본 테스트 계정이 자동으로 생성됩니다:

```bash
python app/scripts/init_db.py
```
* **자동 적재되는 초기 시드 데이터**:
  * **인가 단말기(`X-Terminal-Id`)**: `TAB-HQ-001`, `TAB-RESCUE-002`
  * **엣지 장비**: `EDGE-CAM-01` (API Key: `rescue-edge-secret-key-01`)
  * **지휘관 계정**: 사번 `FIRE-CMD-101` / PIN `123456`
  * **테스트 건물**: `building_id: 1` (소방방재 테스트빌딩 A동)

---

### 7.4 백엔드 서버 실행
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```
* **내 PC에서 접속**: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs) (Swagger UI), [http://127.0.0.1:8000/health](http://127.0.0.1:8000/health) (서버 상태 확인)
* **같은 Wi-Fi/네트워크의 팀원 PC에서 접속**: `http://<서버PC_IPv4주소>:8000/docs`
  *(참고: 다른 PC에서 접속이 안 될 경우 Windows 방화벽에서 `8000`번 포트를 허용해 주세요.)*

---

## 🧪 8. API 연동 테스트 방법 (Swagger UI & 테스트 스크립트)

### 방법 1: 웹 브라우저(Swagger UI)에서 코드 없이 바로 테스트하기

1. 브라우저에서 **[http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)** (또는 `http://<서버IP>:8000/docs`) 접속
2. **작전 세션 생성 (최초 1회)**:
   * `POST /api/v1/auth/login` 클릭 $\rightarrow$ **[Try it out]** $\rightarrow$ `X-Terminal-Id`에 `TAB-HQ-001` 입력, Body는 기본값(`FIRE-CMD-101` / `123456`) 그대로 **[Execute]** 클릭
   * 응답 결과의 `access_token` 문자열을 복사하여 페이지 우측 상단 초록색 **[Authorize]** 버튼에 등록
   * `POST /api/v1/missions` 클릭 $\rightarrow$ **[Try it out]** $\rightarrow$ `building_id: 1`, `device_id: "EDGE-CAM-01"`로 실행하여 **`mission_id: 1`** 생성
3. **프레임 데이터 전송 테스트**:
   * **`POST /api/v1/missions/{mission_id}/telemetry/raw`** (단건) 또는 **`/telemetry/batch`** (배열 일괄) 클릭 $\rightarrow$ **[Try it out]**
   * `mission_id`: `1` 입력
   * `X-Terminal-Id`: `TAB-HQ-001` 입력
   * Request body에 기본 세팅된 예시 JSON(`frame_id: 1042`, `class: "chair"`, `screen_box: [120, 240, 310, 450]`)을 확인하고 **[Execute]** 클릭
   * `200 OK` 응답과 함께 `SAVED_AND_ASSESSED` 및 위험도 판정 결과(`hazard_level`) 즉시 확인!

---

### 방법 2: 파이썬 테스트 스크립트(`mock_edge_sender.py`)로 전송하기

저장소에 포함된 [`app/scripts/mock_edge_sender.py`](app/scripts/mock_edge_sender.py) 스크립트를 실행하면 샘플 프레임 3건(통행 장애물 의자, 구조 대상 인명, 고온 화점)을 서버로 연속 전송하며 응답을 확인할 수 있습니다.

1. **(사전 확인)** 방법 1의 2번 과정을 통해 `mission_id: 1`이 생성(`ACTIVE` 상태)되어 있어야 합니다.
2. 원격 서버로 전송할 경우 `app/scripts/mock_edge_sender.py` 상단의 `SERVER_URL = "http://<서버IP>:8000"` 주소를 수정합니다 (내 PC에서 테스트할 때는 기본값 `http://127.0.0.1:8000` 그대로 사용).
3. 새 터미널을 열고 아래 명령어를 실행합니다:
   ```bash
   python app/scripts/mock_edge_sender.py 1
   ```
4. 실행 출력 예시:
   ```text
   [AI 보드 / 세션 수집 테스트] 작전 #1으로 JSON 프레임 데이터 전송 시작...
   [1/3] 전송 성공 (frame_id=1042) -> hazard_level: WARNING, assessment_id: 1
   [2/3] 전송 성공 (frame_id=1192) -> hazard_level: CRITICAL, assessment_id: 2
   [3/3] 전송 성공 (frame_id=1342) -> hazard_level: CRITICAL, assessment_id: 3
   ```
5. 전송된 결과는 `GET /api/v1/missions/1/map-state` 및 `GET /api/v1/missions/1/ai-assessments` API에서 바로 조회할 수 있습니다.


