# 🚒 연암소방대 - 영상 객체 분석 및 실내 공간지도 기반 소방 관제 시스템

> **영상 객체 분석에서 실내 공간지도 기반 관제까지**  
> 본 프로젝트는 화재·재난 현장에서 수집된 영상 프레임(Gemma 3 4B VLM 객체·맥락 분석) 및 센서 데이터를 구조화하여, 실내 공간지도 위에 실시간으로 시각화하고 작전 의사결정을 지원하는 **백엔드 서버 및 데이터 파이프라인 시스템**입니다.

---

## 👥 1. 팀원 구성 및 파트별 연동 가이드

GitHub 저장소를 클론한 후, 본인의 담당 파트에 맞는 섹션과 문서를 바로 확인하실 수 있습니다.

| 이름 | 담당 파트 | 주요 역할 | 필독 가이드 |
| :--- | :--- | :--- | :--- |
| **공진영** | **Infra & Cloud** | 인프라 아키텍처 구조 설계 및 서버 파이프라인 구축 | [7. 설치 및 서버 실행](#-7-설치-및-서버-실행-가이드) |
| **신경준** | **Data Engineering** | 데이터 엔지니어링 및 다종 데이터 저장소 파이프라인 | [6.2 SSD 세션 인계 규격](#62-임베디드--서버-ssd-세션-인계-규격), [8. 시험 방법](#-8-시험-방법-시험-세션--swagger-ui) |
| **정세빈** | **Frontend & UI** | 어플리케이션 프론트엔드 디자인 및 공간지도 UI 설계 | [6.1 주요 API 엔드포인트](#61-restful-api-일람), [6.3 실시간 WebSocket](#63-관제-계층-실시간-websocket-api) |
| **이세이** | **Frontend & UI** | 어플리케이션 프론트엔드 연동 및 관제 인터페이스 구현 | [6.1 주요 API 엔드포인트](#61-restful-api-일람), [6.3 실시간 WebSocket](#63-관제-계층-실시간-websocket-api) |

> 📄 **상세 API 명세서**: 더 자세한 요청/응답 JSON 필드 설명은 [`docs/api_specification.md`](docs/api_specification.md) 문서에서 확인하세요.

---

## 🛠️ 2. 기술 스택 및 구현 환경

| 분류 | 적용 기술 | 선정 이유 및 역할 |
| :--- | :--- | :--- |
| **백엔드 언어** | **Python (3.10+)** | AI/데이터 엔지니어링 파트와 데이터 모델(Pydantic) 규격 공유 용이 |
| **API 프레임워크** | **FastAPI** | 비동기 고성능 REST API 제공, WebSocket 기본 내장, Swagger UI(`/docs`) 자동화 |
| **ASGI 서버** | **Uvicorn** | 초저지연 비동기 이벤트 루프 핸들링 |
| **ORM (DB 연동)** | **SQLAlchemy 2.0** | 코드 퍼스트(Code-First) 구조, 정적 타입 힌트(`Mapped`, `mapped_column`) |
| **데이터베이스** | **MariaDB (v10.x+)** | Save-First 원시 JSON 선저장(`raw_telemetry_logs`) 및 정형 메타/이벤트 트랜잭션 관리 |
| **AI 분석 모델** | **Gemma 3 4B VLM (Ollama)** | 서버에서 샘플링 프레임의 물체 탐지(`detected_objects`). 위험도(Red/Orange/Yellow)는 규칙 엔진이 판정 |
| **보안 및 인증** | **MDM + bcrypt + JWT** | 단말 인가(`X-Terminal-Id`), 공무원 보안 PIN 단방향 암호화, 역할 기반 RBAC 통제 |

---

## 🏛️ 3. 데이터 흐름 (SSD 세션 가져오기 단일 경로 · Save-First)

현장 데이터는 **외장 SSD 세션 폴더**로만 서버에 들어옵니다. 현장 데이터를 받는 HTTP 수집 API는 없습니다.

```
[임베디드: Jetson Orin + Orbbec Gemini 2]  (embedded 브랜치 edge/fire_vision)
  ① SSD에 ROS2 bag 녹화 → ② extract-bag → 세션 폴더 (manifest.json + rgb/*.npy)
        │  SSD를 서버 노트북에 유선 연결
        ▼
[서버: app/scripts/import_fire_vision_session.py]
  ③ Save-First: 프레임 JPEG + 원본 메타 → raw_telemetry_logs (프레임마다 즉시 커밋)
  ④ Gemma 3 4B 물체 탐지 → 규칙 엔진 위험도 → ai_assessments · detection_events
  ⑤ 결과마다 POST /missions/{id}/notify/assessments
        ▼
[서버: FastAPI]  ⑥ WebSocket 방송  ⑦ REST 조회
        ▼
[안드로이드 관제 앱]  로그인 → 작전 선택 → 지도·탐지 목록·스냅샷 (조회 전용)
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
| **`raw_telemetry_logs`** | `log_id`, `mission_id`, `device_id`, `timestamp`, `raw_payload`(JSON), `is_processed` | **[Save-First]** SSD 세션 프레임의 원본 메타(세션 키, 원본 경로·해시, 시각, IMU 원시값)를 분석 전에 먼저 저장 |
| **`ai_assessments`** | `assessment_id`, `mission_id`, `hazard_level`, `situation_summary`, `poi_type`, `coord_x,y,z`, `assessment_json` | **[Gemma 3 4B]** 프레임 객체 분석 결과 및 관제 지도 POI 마커 테이블 |
| **`detection_events`** | `event_id`, `mission_id`, `timestamp`, `event_type`, `coord_x,y,z` | 탐지된 개별 객체(`PERSON`, `FIRE`, `HAZARD`) 이벤트 로그 |
| **`sensor_logs`** | `log_id`, `mission_id`, `timestamp`, `pos_x,y,z`, `imu_yaw`, `ambient_temp` | 대원/카메라 이동 궤적 (위치 데이터가 생기는 임베디드 E1 이후 사용, 현재 미기록) |
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
| `POST` | `/api/v1/missions/{id}/notify/assessments` | **[내부 연동]** 가져오기 스크립트가 저장한 결과를 앱에 WebSocket 푸시 | `X-Device-Id` / `X-Device-Key` |
| `GET` | `/api/v1/missions/{id}/map-state` | **[관제 UI용]** 실내 지도 초기화 데이터(위치, 궤적, 위험 마커) 통합 조회 | `Authorization: Bearer <JWT>` |
| `GET` | `/api/v1/missions/{id}/ai-assessments` | **[관제 UI용]** Gemma 3 4B 프레임 분석 이력 타임라인 조회 | `Authorization: Bearer <JWT>` |
| `GET` | `/api/v1/missions/{id}/replay` | **[관제 UI용]** 사후 세션 궤적 및 탐지 이벤트 전체 조회 | `Authorization: Bearer <JWT>` |

---

### 6.2 [임베디드 → 서버] SSD 세션 인계 규격

임베디드 `extract-bag` 결과 폴더를 그대로 서버에서 읽습니다. 상세 규격은 [`docs/api_specification.md` 3장](docs/api_specification.md)을 보세요.

```text
<세션 폴더>/
  manifest.json               format = "fire-vision-normalized-v1", extraction.complete = true
  rgb/000000_<timestamp_ns>.npy   uint8 (H, W, 3) RGB
  calibration.json            (있으면 함께)
```

```bash
python app/scripts/import_fire_vision_session.py E:/session_20261120_01 --mission 1
```
* 프레임을 1초 간격으로 골라 원본을 먼저 저장(Save-First)한 뒤 Gemma 3 4B로 분석합니다.
* Gemma가 꺼져 있으면 원본만 저장하고, 나중에 같은 명령으로 분석만 이어서 합니다. 같은 세션을 다시 넣어도 중복 저장하지 않습니다.
* 탐지 좌표는 위치 데이터가 생기기 전까지 **프레임 픽셀값**입니다(실제 공간 좌표 아님).

---

### 6.3 [관제 계층] 실시간 WebSocket API

* **연결 URL**: `ws://<서버IP>:8000/ws/missions/{mission_id}/dashboard?token=<JWT_TOKEN>`
* **수신 이벤트**:
  * `LOCATION_UPDATE`: 대원/카메라 위치 갱신 (`x`, `y`, `z`, `frame_id`, `yaw`) — 위치 데이터 생성(임베디드 E1) 이후 사용, 현재 미발생
  * `AI_MARKER_ALERT`: 구조 대상(`PERSON_RESCUE`), 화점(`FIRE_HOTSPOT`), 통행 장애물(`OBSTACLE_HAZARD`) 탐지 시 마커·설명·탐지 박스(`detected_objects`) 전송
  * `ASSESSMENTS_IMPORTED`: SSD 가져오기로 새 분석 결과가 저장됨 (앱은 목록을 다시 조회)
* 안드로이드 연동 상세: [`docs/api_specification.md` 9장](docs/api_specification.md)

---

## 🚀 7. 서버 동작을 위한 사전 준비 및 실행 가이드 (Getting Started)

GitHub 저장소를 클론(`git clone`)한 후, 로컬 PC에서 백엔드 서버를 구동하고 확인하기 위한 **필수 기반 환경(Prerequisites)**과 단계별 실행 방법입니다.

### 7.0 필수 기반 프로그램 (Prerequisites)
서버를 구동하기 위해 아래 두 가지가 설치되어 있어야 합니다 (프레임 분석까지 하려면 3번도 필요):
1. **Python 3.10 이상** ([python.org](https://www.python.org/downloads/)에서 설치, 설치 시 `Add Python to PATH` 체크 필수)
2. **MariaDB (10.x 이상) 또는 MySQL Server (8.0 이상)**
   * **방법 A (로컬 설치)**: [MariaDB 다운로드](https://mariadb.org/download/)에서 설치 (기본 포트 `3306`, 설치 시 설정한 `root` 비밀번호 기억)
   * **방법 B (Docker 사용 시 - 설치 없이 1줄 실행)**:
     ```bash
     docker run -d --name rescue-mariadb -p 3306:3306 -e MYSQL_ROOT_PASSWORD=1234 mariadb:10.11
     ```
3. **(선택) Ollama + Gemma 3 4B** — SSD 세션 프레임 분석용 (GPU 8GB 권장)
   ```bash
   winget install Ollama.Ollama      # 또는 https://ollama.com 에서 설치
   ollama pull gemma3:4b
   ```
   `.env`에 `GEMMA_API_URL=http://127.0.0.1:11434/api/generate` 추가. 없으면 원본 저장까지만 수행합니다.

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

## 🧪 8. 시험 방법 (시험 세션 & Swagger UI)

Jetson·카메라 없이도 시험 세션을 만들어 전체 흐름을 확인할 수 있습니다. (시험 데이터는 실측이 아닙니다)

### 방법 1: 시험 세션 만들어 가져오기
1. **(사전 확인)** `mission_id: 1`이 `ACTIVE` 상태여야 합니다 (방법 2의 2번 참고).
2. 시험 세션 생성:
   ```bash
   # 실제 사진 폴더로 (사진 1장 = 1초 프레임) — Gemma 실제 성능 확인용
   python app/scripts/make_sample_fire_vision_session.py D:/test_session --images D:/photos
   # 사진 없이 합성 영상 — 동작 확인용
   python app/scripts/make_sample_fire_vision_session.py D:/test_session
   ```
3. 가져오기 (서버가 켜져 있으면 접속 중인 앱에 실시간 푸시):
   ```bash
   python app/scripts/import_fire_vision_session.py D:/test_session --mission 1
   ```
4. 실행 출력 예시:
   ```text
   [1/2 Save-First] 샘플 3개 → 새로 저장 3개, 이미 저장됨 0개, 실패 0개
   [2/2 분석] 대상 3개 → 완료 3개, 실패 0개 (위험도: CRITICAL 1, NORMAL 1, WARNING 1)
     [앱 푸시] 3건 방송 (경보 2건, 접속 중인 앱 1대)
   ```

### 방법 2: 웹 브라우저(Swagger UI)에서 결과 조회
1. 브라우저에서 **[http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)** (또는 `http://<서버IP>:8000/docs`) 접속
2. **작전 세션 생성 (최초 1회)**:
   * `POST /api/v1/auth/login` → **[Try it out]** → `X-Terminal-Id`에 `TAB-HQ-001`, Body 기본값(`FIRE-CMD-101` / `123456`) → **[Execute]**
   * 응답의 `access_token`을 우측 상단 **[Authorize]** 버튼에 등록
   * `POST /api/v1/missions` → `building_id: 1`, `device_id: "EDGE-CAM-01"`로 실행하여 **`mission_id: 1`** 생성
3. **결과 조회**: `GET /api/v1/missions/1/map-state`, `GET /api/v1/missions/1/ai-assessments`




